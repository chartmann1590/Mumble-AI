from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import psycopg2
import psycopg2.pool
import requests
import os
import tempfile
import logging
import time
import json
from datetime import datetime
from pydub import AudioSegment
from werkzeug.utils import secure_filename
import mimetypes
import wave
import struct
import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Configuration
DB_HOST = os.getenv('DB_HOST', 'postgres')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'mumble_ai')
DB_USER = os.getenv('DB_USER', 'mumbleai')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'mumbleai123')
WHISPER_URL = os.getenv('WHISPER_URL', 'http://faster-whisper:5000')
OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://host.docker.internal:11434')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'llama3.2:latest')
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB

# Database connection pool
db_pool = None

def init_db_pool():
    """Initialize database connection pool"""
    global db_pool
    try:
        db_pool = psycopg2.pool.SimpleConnectionPool(
            1, 20,
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        logger.info("Database connection pool initialized")
    except Exception as e:
        logger.error(f"Failed to initialize database pool: {e}")
        raise

def get_db_connection():
    """Get database connection from pool"""
    try:
        return db_pool.getconn()
    except Exception as e:
        logger.error(f"Failed to get database connection: {e}")
        return None

def return_db_connection(conn):
    """Return database connection to pool"""
    try:
        db_pool.putconn(conn)
    except Exception as e:
        logger.error(f"Failed to return database connection: {e}")

# Initialize database pool on startup
init_db_pool()

# Supported file formats
SUPPORTED_AUDIO_FORMATS = {'.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a'}
SUPPORTED_VIDEO_FORMATS = {'.mp4', '.webm', '.avi', '.mov', '.mkv'}
ALL_SUPPORTED_FORMATS = SUPPORTED_AUDIO_FORMATS | SUPPORTED_VIDEO_FORMATS

def is_supported_file(filename):
    """Check if file format is supported"""
    ext = os.path.splitext(filename.lower())[1]
    return ext in ALL_SUPPORTED_FORMATS

def extract_audio_from_video(video_path, output_path):
    """Extract audio from video file using pydub"""
    try:
        # Load video file
        video = AudioSegment.from_file(video_path)
        
        # Convert to mono 16kHz WAV for Whisper
        audio = video.set_channels(1).set_frame_rate(16000)
        
        # Export as WAV
        audio.export(output_path, format="wav")
        logger.info(f"Extracted audio from video: {output_path}")
        return True
    except Exception as e:
        logger.error(f"Error extracting audio from video: {e}")
        return False

def convert_audio_to_wav(input_path, output_path):
    """Convert audio file to WAV format for Whisper"""
    try:
        # Load audio file
        audio = AudioSegment.from_file(input_path)
        
        # Convert to mono 16kHz WAV for Whisper
        audio = audio.set_channels(1).set_frame_rate(16000)
        
        # Export as WAV
        audio.export(output_path, format="wav")
        logger.info(f"Converted audio to WAV: {output_path}")
        return True
    except Exception as e:
        logger.error(f"Error converting audio to WAV: {e}")
        return False

def get_audio_duration(file_path):
    """Get audio duration in seconds"""
    try:
        audio = AudioSegment.from_file(file_path)
        return len(audio) / 1000.0  # Convert milliseconds to seconds
    except Exception as e:
        logger.error(f"Error getting audio duration: {e}")
        return None

def calculate_audio_energy(audio_path, start_time, end_time):
    """Calculate RMS energy for audio segment"""
    try:
        with wave.open(audio_path, 'rb') as wav:
            framerate = wav.getframerate()
            start_frame = int(start_time * framerate)
            end_frame = int(end_time * framerate)
            
            wav.setpos(start_frame)
            frames = wav.readframes(end_frame - start_frame)
            
            # Convert to numpy array
            samples = np.frombuffer(frames, dtype=np.int16)
            rms = np.sqrt(np.mean(samples.astype(float)**2))
            return rms
    except Exception as e:
        logger.error(f"Error calculating audio energy: {e}")
        return 0.0

def detect_speakers_simple(audio_path, segments_data):
    """Simple speaker detection based on pauses and energy changes"""
    if not segments_data:
        logger.info("No segments data provided for speaker detection")
        return segments_data
    
    logger.info(f"Processing {len(segments_data)} segments for speaker detection")
    current_speaker = 1
    previous_energy = 0
    previous_end = 0
    
    for i, seg in enumerate(segments_data):
        try:
            # Calculate energy for this segment
            energy = calculate_audio_energy(audio_path, seg['start'], seg['end'])
            
            # Detect speaker change based on:
            # 1. Pause duration > 1.5 seconds
            # 2. Significant energy change (>40% difference)
            pause_duration = seg['start'] - previous_end
            energy_change = abs(energy - previous_energy) / (previous_energy + 1) if previous_energy > 0 else 0
            
            if i > 0 and (pause_duration > 1.5 or energy_change > 0.4):
                current_speaker += 1
                logger.info(f"Speaker change detected at segment {i}: pause={pause_duration:.2f}s, energy_change={energy_change:.2f}")
            
            seg['speaker'] = f"Speaker {current_speaker}"
            previous_energy = energy
            previous_end = seg['end']
        except Exception as e:
            logger.error(f"Error processing segment {i}: {e}")
            seg['speaker'] = f"Speaker {current_speaker}"
    
    logger.info(f"Speaker detection complete: {current_speaker} speakers detected")
    return segments_data

def format_timestamp(seconds):
    """Format seconds as HH:MM:SS or MM:SS"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"

def format_with_timestamps(segments):
    """Format segments with inline timestamps and speakers"""
    if not segments:
        return ""
    
    result = []
    current_speaker = None
    
    for seg in segments:
        timestamp = format_timestamp(seg['start'])
        speaker = seg.get('speaker', 'Speaker 1')
        
        if speaker != current_speaker:
            current_speaker = speaker
            result.append(f"\n[{timestamp}] {speaker}: {seg['text']}")
        else:
            result.append(f"[{timestamp}] {seg['text']}")
    
    return '\n'.join(result).strip()

@app.route('/')
def index():
    """Serve React frontend"""
    response = send_from_directory('static', 'index.html')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/<path:path>')
def serve_static(path):
    """Serve static files"""
    response = send_from_directory('static', path)
    if path.endswith('.js') or path.endswith('.css'):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'service': 'whisper-web-interface'}), 200

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Upload and validate file"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # Validate file size
        file.seek(0, 2)  # Seek to end
        file_size = file.tell()
        file.seek(0)  # Reset to beginning
        
        if file_size > MAX_FILE_SIZE:
            return jsonify({'error': f'File too large. Maximum size is {MAX_FILE_SIZE // (1024*1024)}MB'}), 400
        
        # Validate file format
        if not is_supported_file(file.filename):
            return jsonify({'error': 'Unsupported file format'}), 400
        
        # Save file temporarily
        filename = secure_filename(file.filename)
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp_file:
            file.save(tmp_file.name)
            temp_path = tmp_file.name
        
        # Get file info
        original_format = os.path.splitext(filename)[1][1:].lower()
        duration = get_audio_duration(temp_path)
        
        return jsonify({
            'success': True,
            'filename': filename,
            'original_format': original_format,
            'file_size_bytes': file_size,
            'duration_seconds': duration,
            'temp_path': temp_path
        }), 200
        
    except Exception as e:
        logger.error(f"Upload error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/transcribe', methods=['POST'])
def transcribe():
    """Transcribe audio file using Whisper service"""
    try:
        data = request.get_json()
        if not data or 'temp_path' not in data:
            return jsonify({'error': 'No file path provided'}), 400
        
        temp_path = data['temp_path']
        filename = data.get('filename', 'unknown')
        original_format = data.get('original_format', 'unknown')
        file_size_bytes = data.get('file_size_bytes', 0)
        duration_seconds = data.get('duration_seconds', 0)
        
        start_time = time.time()
        
        # Prepare audio file for Whisper
        with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as whisper_file:
            whisper_path = whisper_file.name
        
        # Convert to WAV if needed
        file_ext = os.path.splitext(temp_path)[1].lower()
        if file_ext in SUPPORTED_VIDEO_FORMATS:
            # Extract audio from video
            if not extract_audio_from_video(temp_path, whisper_path):
                return jsonify({'error': 'Failed to extract audio from video'}), 500
        elif file_ext != '.wav':
            # Convert audio to WAV
            if not convert_audio_to_wav(temp_path, whisper_path):
                return jsonify({'error': 'Failed to convert audio to WAV'}), 500
        else:
            # Already WAV, just copy
            import shutil
            shutil.copy2(temp_path, whisper_path)
        
        try:
            # Call Whisper service (30 minute timeout for large files)
            with open(whisper_path, 'rb') as audio_file:
                files = {'audio': audio_file}
                response = requests.post(f"{WHISPER_URL}/transcribe", files=files, timeout=1800)
            
            if response.status_code != 200:
                logger.error(f"Whisper service error: {response.text}")
                return jsonify({'error': 'Transcription failed'}), 500
            
            whisper_result = response.json()
            transcription_text = whisper_result.get('text', '')
            language = whisper_result.get('language', 'unknown')
            language_probability = whisper_result.get('language_probability', 0.0)
            
            # Get segments if available (faster-whisper may return them)
            segments = whisper_result.get('segments', [])
            logger.info(f"Whisper returned {len(segments)} segments")
            
            # If no segments from Whisper, create pseudo-segments from text
            # This provides basic timestamp functionality even without Whisper segments
            if not segments:
                logger.info("No segments from Whisper, creating pseudo-segments")
                # Split text into sentences for basic segmentation
                sentences = transcription_text.replace('! ', '!|').replace('? ', '?|').replace('. ', '.|').split('|')
                segment_duration = duration_seconds / max(len(sentences), 1)
                
                segments = []
                current_time = 0
                for i, sentence in enumerate(sentences):
                    if sentence.strip():
                        segments.append({
                            'start': current_time,
                            'end': current_time + segment_duration,
                            'text': sentence.strip()
                        })
                        current_time += segment_duration
                logger.info(f"Created {len(segments)} pseudo-segments")
            
            # Apply speaker detection using audio analysis
            logger.info("Starting speaker detection")
            segments = detect_speakers_simple(whisper_path, segments)
            
            # Format with timestamps for easy reading
            transcription_formatted = format_with_timestamps(segments)
            logger.info(f"Formatted transcription with {len(segments)} segments")
            
            processing_time = time.time() - start_time
            
            # Save to database with both formats
            conn = get_db_connection()
            if not conn:
                return jsonify({'error': 'Database connection failed'}), 500
            
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO transcriptions 
                    (filename, original_format, file_size_bytes, duration_seconds, 
                     transcription_text, transcription_segments, transcription_formatted,
                     language, language_probability, processing_time_seconds)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (filename, original_format, file_size_bytes, duration_seconds,
                      transcription_text, json.dumps(segments), transcription_formatted,
                      language, language_probability, processing_time))
                
                transcription_id = cursor.fetchone()[0]
                conn.commit()
                cursor.close()
                
                return jsonify({
                    'success': True,
                    'transcription_id': transcription_id,
                    'transcription_text': transcription_text,
                    'transcription_segments': segments,
                    'transcription_formatted': transcription_formatted,
                    'language': language,
                    'language_probability': language_probability,
                    'processing_time_seconds': processing_time
                }), 200
                
            finally:
                return_db_connection(conn)
        
        finally:
            # Clean up temporary files
            try:
                os.unlink(whisper_path)
                os.unlink(temp_path)
            except:
                pass
        
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/summarize', methods=['POST'])
def summarize():
    """Summarize transcription using Ollama"""
    try:
        data = request.get_json()
        if not data or 'transcription_id' not in data or 'transcription_text' not in data:
            return jsonify({'error': 'Transcription ID and text required'}), 400
        
        transcription_id = data['transcription_id']
        transcription_text = data['transcription_text']
        
        # Call Ollama for summarization
        logger.info(f"Starting summarization for transcription ID {transcription_id}, text length: {len(transcription_text)}")
        
        # Use a more sophisticated prompt for better summarization
        prompt = f"""Please provide a comprehensive summary of the following transcription. Focus on the main topics, key points, decisions made, and important details. Make sure to capture the full context and meaning:

{transcription_text}"""
        
        ollama_payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False
        }
        
        logger.info(f"Calling Ollama at {OLLAMA_URL}/api/generate with model {OLLAMA_MODEL}")
        try:
            # Use a much longer timeout for long transcriptions (30 minutes)
            timeout_duration = 1800
            response = requests.post(f"{OLLAMA_URL}/api/generate", 
                                   json=ollama_payload, 
                                   timeout=timeout_duration)
        except requests.exceptions.Timeout:
            logger.error(f"Ollama request timed out after {timeout_duration} seconds for transcription ID {transcription_id}")
            return jsonify({'error': f'Summarization timed out after {timeout_duration//60} minutes. The transcription is very long and may need to be processed in smaller chunks.'}), 500
        except requests.exceptions.RequestException as e:
            logger.error(f"Ollama request failed: {e}")
            return jsonify({'error': 'Failed to connect to Ollama service'}), 500
        
        if response.status_code != 200:
            logger.error(f"Ollama service error: {response.text}")
            return jsonify({'error': 'Summarization failed'}), 500
        
        ollama_result = response.json()
        summary_text = ollama_result.get('response', '').strip()
        
        # Update database with summary
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE transcriptions 
                SET summary_text = %s, summary_model = %s
                WHERE id = %s
            """, (summary_text, OLLAMA_MODEL, transcription_id))
            
            conn.commit()
            cursor.close()
            
            return jsonify({
                'success': True,
                'summary_text': summary_text,
                'summary_model': OLLAMA_MODEL
            }), 200
            
        finally:
            return_db_connection(conn)
        
    except Exception as e:
        logger.error(f"Summarization error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/transcriptions', methods=['GET'])
def get_transcriptions():
    """Get list of transcriptions with pagination"""
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 10))
        search = request.args.get('search', '')
        
        offset = (page - 1) * per_page
        
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        
        try:
            cursor = conn.cursor()
            
            # Build search query
            where_clause = ""
            params = []
            if search:
                where_clause = "WHERE filename ILIKE %s OR transcription_text ILIKE %s"
                params = [f"%{search}%", f"%{search}%"]
            
            # Get total count
            count_query = f"SELECT COUNT(*) FROM transcriptions {where_clause}"
            cursor.execute(count_query, params)
            total_count = cursor.fetchone()[0]
            
            # Get transcriptions
            query = f"""
                SELECT id, filename, original_format, file_size_bytes, duration_seconds,
                       transcription_text, transcription_segments, transcription_formatted,
                       language, language_probability, summary_text,
                       summary_model, processing_time_seconds, created_at
                FROM transcriptions {where_clause}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """
            cursor.execute(query, params + [per_page, offset])
            
            transcriptions = []
            for row in cursor.fetchall():
                transcriptions.append({
                    'id': row[0],
                    'filename': row[1],
                    'original_format': row[2],
                    'file_size_bytes': row[3],
                    'duration_seconds': row[4],
                    'transcription_text': row[5],
                    'transcription_segments': row[6],
                    'transcription_formatted': row[7],
                    'language': row[8],
                    'language_probability': row[9],
                    'summary_text': row[10],
                    'summary_model': row[11],
                    'processing_time_seconds': row[12],
                    'created_at': row[13].isoformat() if row[13] else None
                })
            
            cursor.close()
            
            return jsonify({
                'transcriptions': transcriptions,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total': total_count,
                    'pages': (total_count + per_page - 1) // per_page
                }
            }), 200
            
        finally:
            return_db_connection(conn)
        
    except Exception as e:
        logger.error(f"Get transcriptions error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/transcriptions/<int:transcription_id>', methods=['GET'])
def get_transcription(transcription_id):
    """Get single transcription details"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, filename, original_format, file_size_bytes, duration_seconds,
                       transcription_text, transcription_segments, transcription_formatted,
                       language, language_probability, summary_text,
                       summary_model, processing_time_seconds, created_at
                FROM transcriptions
                WHERE id = %s
            """, (transcription_id,))
            
            row = cursor.fetchone()
            cursor.close()
            
            if not row:
                return jsonify({'error': 'Transcription not found'}), 404
            
            return jsonify({
                'id': row[0],
                'filename': row[1],
                'original_format': row[2],
                'file_size_bytes': row[3],
                'duration_seconds': row[4],
                'transcription_text': row[5],
                'transcription_segments': row[6],
                'transcription_formatted': row[7],
                'language': row[8],
                'language_probability': row[9],
                'summary_text': row[10],
                'summary_model': row[11],
                'processing_time_seconds': row[12],
                'created_at': row[13].isoformat() if row[13] else None
            }), 200
            
        finally:
            return_db_connection(conn)
        
    except Exception as e:
        logger.error(f"Get transcription error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/transcriptions/<int:transcription_id>', methods=['DELETE'])
def delete_transcription(transcription_id):
    """Delete transcription"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM transcriptions WHERE id = %s", (transcription_id,))
            
            if cursor.rowcount == 0:
                return jsonify({'error': 'Transcription not found'}), 404
            
            conn.commit()
            cursor.close()
            
            return jsonify({'success': True, 'message': 'Transcription deleted successfully'}), 200
            
        finally:
            return_db_connection(conn)
        
    except Exception as e:
        logger.error(f"Delete transcription error: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5008, debug=False)
