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
from resemblyzer import VoiceEncoder, preprocess_wav
from sklearn.cluster import SpectralClustering
import librosa

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

# Initialize voice encoder globally (lazy loading)
_voice_encoder = None

def get_voice_encoder():
    """Get or initialize the voice encoder (lazy loading)"""
    global _voice_encoder
    if _voice_encoder is None:
        logger.info("Initializing Resemblyzer voice encoder...")
        _voice_encoder = VoiceEncoder()
        logger.info("Voice encoder initialized successfully")
    return _voice_encoder

def detect_speakers_advanced(audio_path, segments_data, num_speakers=None):
    """
    Advanced speaker diarization using Resemblyzer voice embeddings + spectral clustering
    No HuggingFace authentication required - completely free!

    Returns: (segments_data, speaker_embeddings_dict)
        - segments_data: list of segments with speaker labels
        - speaker_embeddings_dict: dict mapping speaker labels to their average embeddings
    """
    if not segments_data or len(segments_data) == 0:
        logger.info("No segments data provided for speaker detection")
        return segments_data, {}

    logger.info(f"Starting advanced speaker diarization for {len(segments_data)} segments")

    try:
        # Load audio file
        logger.info(f"Loading audio from {audio_path}")
        wav, sr = librosa.load(audio_path, sr=16000, mono=True)
        logger.info(f"Audio loaded: {len(wav)} samples at {sr}Hz")

        # Get voice encoder
        encoder = get_voice_encoder()

        # Extract embeddings for each segment
        embeddings = []
        valid_segments = []

        for i, seg in enumerate(segments_data):
            try:
                start_sample = int(seg['start'] * sr)
                end_sample = int(seg['end'] * sr)

                # Extract segment audio
                segment_wav = wav[start_sample:end_sample]

                # Skip ONLY extremely short segments (< 0.15 seconds) - very sensitive
                if len(segment_wav) < int(0.15 * sr):
                    logger.warning(f"Segment {i} too short ({len(segment_wav)/sr:.2f}s), skipping")
                    continue

                # Normalize audio for better embedding extraction
                segment_wav = segment_wav / (np.max(np.abs(segment_wav)) + 1e-6)

                # Get embedding for this segment
                embedding = encoder.embed_utterance(segment_wav)
                embeddings.append(embedding)
                valid_segments.append(i)

            except Exception as e:
                logger.error(f"Error processing segment {i}: {e}")
                continue

        if len(embeddings) == 0:
            logger.warning("No valid embeddings extracted, falling back to single speaker")
            for seg in segments_data:
                seg['speaker'] = "Speaker 1"
            return segments_data, {}

        embeddings = np.array(embeddings)
        logger.info(f"Extracted {len(embeddings)} embeddings with shape {embeddings.shape}")

        # Auto-detect number of speakers if not specified
        if num_speakers is None:
            # AGGRESSIVE speaker detection: favor detecting more speakers
            from sklearn.decomposition import PCA
            from sklearn.metrics import silhouette_score
            from scipy.spatial.distance import pdist

            # Analyze variance to get initial estimate
            pca = PCA(n_components=min(10, len(embeddings)))
            pca.fit(embeddings)
            variance_ratio = np.cumsum(pca.explained_variance_ratio_)

            # Calculate pairwise distances to detect diversity
            distances = pdist(embeddings, metric='cosine')
            avg_distance = np.mean(distances)
            max_distance = np.max(distances)

            logger.info(f"Embedding diversity - Avg distance: {avg_distance:.3f}, Max distance: {max_distance:.3f}")

            # VERY aggressive thresholds - favor multiple speakers
            # Lower thresholds = more likely to detect multiple speakers
            if variance_ratio[0] > 0.98 and avg_distance < 0.05:  # EXTREMELY strong single mode
                initial_estimate = 1
            elif variance_ratio[1] > 0.92:  # Two speakers (lowered from 0.95)
                initial_estimate = 2
            elif variance_ratio[2] > 0.94:  # Three speakers (lowered from 0.96)
                initial_estimate = 3
            else:
                # More aggressive default: assume multiple speakers
                # If we have diversity, favor more speakers
                if avg_distance > 0.15:  # High diversity
                    initial_estimate = min(6, max(3, int(len(embeddings) / 8)))
                else:
                    initial_estimate = min(5, max(2, int(len(embeddings) / 10)))

            # Try multiple speaker counts with BROADER range
            best_score = -1
            best_k = initial_estimate

            # Test from 2 to 8 speakers if we have enough segments
            test_range = range(2, min(8, len(embeddings) // 2))

            for k in test_range:
                if k >= len(embeddings):
                    break
                try:
                    from sklearn.cluster import AgglomerativeClustering
                    temp_clustering = AgglomerativeClustering(
                        n_clusters=k,
                        linkage='ward',
                        metric='euclidean'
                    )
                    temp_labels = temp_clustering.fit_predict(embeddings)
                    score = silhouette_score(embeddings, temp_labels)

                    logger.debug(f"Testing {k} speakers: silhouette score = {score:.3f}")

                    # Favor solutions with positive silhouette score
                    if score > best_score and score > 0:
                        best_score = score
                        best_k = k
                except Exception as e:
                    logger.debug(f"Error testing {k} speakers: {e}")
                    pass

            num_speakers = best_k
            logger.info(f"Auto-detected {num_speakers} speakers (initial estimate: {initial_estimate}, silhouette score: {best_score:.3f}, diversity: {avg_distance:.3f})")

        # Cluster embeddings to identify speakers
        if num_speakers == 1 or len(embeddings) < num_speakers:
            labels = np.zeros(len(embeddings), dtype=int)
            logger.info("Only 1 speaker or insufficient segments for clustering")
        else:
            logger.info(f"Clustering {len(embeddings)} embeddings into {num_speakers} speakers")

            # Try multiple clustering approaches and pick the best
            from sklearn.cluster import AgglomerativeClustering, KMeans

            # Use Agglomerative Clustering (better for speaker diarization)
            clustering = AgglomerativeClustering(
                n_clusters=num_speakers,
                linkage='ward',  # Ward minimizes variance within clusters
                metric='euclidean'
            )
            labels = clustering.fit_predict(embeddings)

            # Post-process to merge ONLY very short speaker turns (likely errors)
            # Be less aggressive with merging to preserve legitimate speaker changes
            min_segment_length = 2  # Only merge if 1 segment (lowered from 3)
            label_counts = np.bincount(labels)
            for label in range(len(label_counts)):
                if label_counts[label] < min_segment_length:
                    # Reassign to the most common neighbor
                    label_indices = np.where(labels == label)[0]
                    for idx in label_indices:
                        # Find nearest different label
                        neighbors = []
                        if idx > 0:
                            neighbors.append(labels[idx-1])
                        if idx < len(labels) - 1:
                            neighbors.append(labels[idx+1])
                        if neighbors:
                            labels[idx] = max(set(neighbors), key=neighbors.count)

        # Assign speaker labels to segments and collect embeddings per speaker
        speaker_map = {}
        speaker_embeddings_dict = {}  # Map speaker label to list of embeddings

        for seg_idx, label in zip(valid_segments, labels):
            speaker_id = int(label) + 1  # 1-indexed
            speaker_label = f"Speaker {speaker_id}"
            segments_data[seg_idx]['speaker'] = speaker_label
            speaker_map[speaker_id] = speaker_map.get(speaker_id, 0) + 1

            # Collect embeddings for this speaker
            if speaker_label not in speaker_embeddings_dict:
                speaker_embeddings_dict[speaker_label] = []
            speaker_embeddings_dict[speaker_label].append(embeddings[valid_segments.index(seg_idx)])

        # Calculate average embedding for each speaker
        speaker_avg_embeddings = {}
        for speaker_label, embs in speaker_embeddings_dict.items():
            speaker_avg_embeddings[speaker_label] = np.mean(embs, axis=0).tolist()

        # Fill in any skipped segments with nearest neighbor's speaker
        last_speaker = "Speaker 1"
        for i, seg in enumerate(segments_data):
            if 'speaker' not in seg or not seg['speaker']:
                seg['speaker'] = last_speaker
            else:
                last_speaker = seg['speaker']

        logger.info(f"Speaker diarization complete: {num_speakers} speakers detected")
        logger.info(f"Speaker distribution: {speaker_map}")

        return segments_data, speaker_avg_embeddings

    except Exception as e:
        logger.error(f"Error in speaker diarization: {e}", exc_info=True)
        logger.warning("Falling back to simple speaker assignment")
        # Fallback: assign all to one speaker
        for seg in segments_data:
            seg['speaker'] = "Speaker 1"
        return segments_data, {}

def match_speakers_to_profiles(speaker_embeddings, similarity_threshold=0.75):
    """
    Match detected speaker embeddings to stored speaker profiles.

    Args:
        speaker_embeddings: dict mapping speaker labels to their average embeddings
        similarity_threshold: minimum cosine similarity to consider a match (default 0.75)

    Returns:
        dict mapping detected speaker labels to matched profile info
        {
            "Speaker 1": {
                "matched": True/False,
                "profile_id": int or None,
                "profile_name": str or None,
                "similarity": float
            }
        }
    """
    if not speaker_embeddings:
        return {}

    conn = get_db_connection()
    if not conn:
        logger.warning("Cannot match speakers: no database connection")
        return {}

    try:
        cursor = conn.cursor()

        # Get all active speaker profiles
        cursor.execute("""
            SELECT id, speaker_name, voice_embedding
            FROM speaker_profiles
            WHERE is_active = TRUE
            ORDER BY last_seen DESC
        """)

        profiles = cursor.fetchall()
        cursor.close()

        if not profiles:
            logger.info("No existing speaker profiles to match against")
            return {label: {"matched": False, "profile_id": None, "profile_name": None, "similarity": 0.0}
                    for label in speaker_embeddings.keys()}

        logger.info(f"Matching {len(speaker_embeddings)} detected speakers against {len(profiles)} stored profiles")

        matches = {}

        for speaker_label, embedding in speaker_embeddings.items():
            best_match = None
            best_similarity = 0.0

            embedding_array = np.array(embedding)

            # Compare against all stored profiles
            for profile_id, profile_name, stored_embedding in profiles:
                if not stored_embedding:
                    continue

                stored_array = np.array(stored_embedding)

                # Calculate cosine similarity
                similarity = np.dot(embedding_array, stored_array) / (
                    np.linalg.norm(embedding_array) * np.linalg.norm(stored_array)
                )

                logger.debug(f"{speaker_label} vs {profile_name}: similarity = {similarity:.3f}")

                if similarity > best_similarity:
                    best_similarity = similarity
                    best_match = (profile_id, profile_name)

            # Check if best match meets threshold
            if best_similarity >= similarity_threshold and best_match:
                matches[speaker_label] = {
                    "matched": True,
                    "profile_id": best_match[0],
                    "profile_name": best_match[1],
                    "similarity": float(best_similarity)
                }
                logger.info(f"Matched {speaker_label} to '{best_match[1]}' (similarity: {best_similarity:.3f})")
            else:
                matches[speaker_label] = {
                    "matched": False,
                    "profile_id": None,
                    "profile_name": None,
                    "similarity": float(best_similarity)
                }
                logger.info(f"No match for {speaker_label} (best similarity: {best_similarity:.3f})")

        return matches

    except Exception as e:
        logger.error(f"Error matching speakers to profiles: {e}")
        return {}
    finally:
        return_db_connection(conn)

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
            
            # Apply advanced speaker detection using Resemblyzer (voice embeddings + clustering)
            logger.info("Starting advanced speaker diarization")
            segments, speaker_embeddings = detect_speakers_advanced(whisper_path, segments)

            # Match speakers to stored profiles
            logger.info("Matching speakers to stored profiles")
            speaker_matches = match_speakers_to_profiles(speaker_embeddings)

            # Update segment speaker labels with matched names
            for seg in segments:
                original_label = seg.get('speaker', 'Speaker 1')
                if original_label in speaker_matches and speaker_matches[original_label]['matched']:
                    matched_name = speaker_matches[original_label]['profile_name']
                    seg['speaker'] = matched_name
                    seg['speaker_matched'] = True
                    seg['similarity'] = speaker_matches[original_label]['similarity']
                else:
                    seg['speaker_matched'] = False

            # Format with timestamps for easy reading
            transcription_formatted = format_with_timestamps(segments)
            logger.info(f"Formatted transcription with {len(segments)} segments")
            
            processing_time = time.time() - start_time

            # Generate title using Ollama
            logger.info("Generating title for transcription")
            title = generate_title(transcription_text)
            if not title:
                # Fallback to filename if title generation fails
                title = os.path.splitext(filename)[0]

            # Save to database with both formats and title
            conn = get_db_connection()
            if not conn:
                return jsonify({'error': 'Database connection failed'}), 500

            try:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO transcriptions
                    (filename, original_format, file_size_bytes, duration_seconds,
                     transcription_text, transcription_segments, transcription_formatted,
                     language, language_probability, processing_time_seconds, title)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (filename, original_format, file_size_bytes, duration_seconds,
                      transcription_text, json.dumps(segments), transcription_formatted,
                      language, language_probability, processing_time, title))

                transcription_id = cursor.fetchone()[0]
                logger.info(f"Saved transcription {transcription_id} with title: {title}")

                # Save speaker mappings to database
                for speaker_label, embedding in speaker_embeddings.items():
                    match_info = speaker_matches.get(speaker_label, {})

                    # Calculate segment stats for this speaker
                    speaker_segments = [s for s in segments if s.get('speaker') == (match_info.get('profile_name') or speaker_label)]
                    segment_count = len(speaker_segments)
                    total_duration = sum(s.get('end', 0) - s.get('start', 0) for s in speaker_segments)

                    # Insert mapping record
                    cursor.execute("""
                        INSERT INTO speaker_transcription_mapping
                        (transcription_id, speaker_profile_id, detected_speaker_label,
                         segment_count, total_duration_seconds, average_embedding,
                         similarity_score, is_confirmed)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        transcription_id,
                        match_info.get('profile_id'),
                        speaker_label,
                        segment_count,
                        total_duration,
                        embedding,
                        match_info.get('similarity', 0.0),
                        match_info.get('matched', False)
                    ))

                conn.commit()
                logger.info(f"Saved {len(speaker_embeddings)} speaker mappings for transcription {transcription_id}")
                cursor.close()

                return jsonify({
                    'success': True,
                    'transcription_id': transcription_id,
                    'transcription_text': transcription_text,
                    'transcription_segments': segments,
                    'transcription_formatted': transcription_formatted,
                    'language': language,
                    'language_probability': language_probability,
                    'processing_time_seconds': processing_time,
                    'speaker_matches': speaker_matches
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

@app.route('/api/regenerate-title', methods=['POST'])
def regenerate_title():
    """Regenerate title for transcription using Ollama"""
    try:
        data = request.get_json()
        if not data or 'transcription_id' not in data or 'transcription_text' not in data:
            return jsonify({'error': 'Transcription ID and text required'}), 400

        transcription_id = data['transcription_id']
        transcription_text = data['transcription_text']

        logger.info(f"Regenerating title for transcription ID {transcription_id}")

        # Generate new title
        new_title = generate_title(transcription_text)

        if not new_title:
            return jsonify({'error': 'Failed to generate title. Please try again.'}), 500

        # Update database with new title
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500

        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE transcriptions
                SET title = %s
                WHERE id = %s
            """, (new_title, transcription_id))

            conn.commit()
            cursor.close()

            logger.info(f"Successfully regenerated title for transcription ID {transcription_id}: {new_title}")

            return jsonify({
                'success': True,
                'title': new_title
            }), 200

        finally:
            return_db_connection(conn)

    except Exception as e:
        logger.error(f"Title regeneration error: {e}")
        return jsonify({'error': str(e)}), 500

def generate_title(transcription_text):
    """Generate a concise title for transcription using Ollama"""
    try:
        # Truncate text for title generation (first 2000 chars is usually enough)
        text_sample = transcription_text[:2000] if len(transcription_text) > 2000 else transcription_text

        prompt = f"""Based on the following transcription, generate a short, descriptive title (maximum 8 words). The title should capture the main topic or purpose of the conversation. Return ONLY the title, nothing else.

Transcription:
{text_sample}

Title:"""

        ollama_payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False
        }

        logger.info(f"Generating title using Ollama model {OLLAMA_MODEL}")

        try:
            response = requests.post(f"{OLLAMA_URL}/api/generate",
                                   json=ollama_payload,
                                   timeout=300)  # 5 minute timeout for title generation
        except requests.exceptions.Timeout:
            logger.warning("Title generation timed out after 5 minutes, using default")
            return None
        except requests.exceptions.RequestException as e:
            logger.warning(f"Title generation failed: {e}")
            return None

        if response.status_code != 200:
            logger.warning(f"Ollama title generation error: {response.text}")
            return None

        ollama_result = response.json()
        title = ollama_result.get('response', '').strip()

        # Clean up the title (remove quotes, extra whitespace, etc.)
        title = title.strip('"\'').strip()

        # Limit title length
        if len(title) > 100:
            title = title[:97] + '...'

        logger.info(f"Generated title: {title}")
        return title

    except Exception as e:
        logger.error(f"Error generating title: {e}")
        return None

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
                       summary_model, processing_time_seconds, created_at, title
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
                    'created_at': row[13].isoformat() if row[13] else None,
                    'title': row[14]
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
                       summary_model, processing_time_seconds, created_at, title
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
                'created_at': row[13].isoformat() if row[13] else None,
                'title': row[14]
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

@app.route('/api/transcriptions/<int:transcription_id>/update-speakers', methods=['POST'])
def update_speakers(transcription_id):
    """Update speaker names in a transcription"""
    try:
        data = request.get_json()
        if not data or 'speaker_mappings' not in data:
            return jsonify({'error': 'speaker_mappings required'}), 400

        speaker_mappings = data['speaker_mappings']
        if not isinstance(speaker_mappings, dict):
            return jsonify({'error': 'speaker_mappings must be a dictionary'}), 400

        logger.info(f"Updating speakers for transcription {transcription_id}: {speaker_mappings}")

        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500

        try:
            cursor = conn.cursor()

            # Get current transcription data
            cursor.execute("""
                SELECT transcription_segments, transcription_formatted
                FROM transcriptions
                WHERE id = %s
            """, (transcription_id,))

            row = cursor.fetchone()
            if not row:
                return jsonify({'error': 'Transcription not found'}), 404

            segments = row[0] if row[0] else []
            formatted_text = row[1] if row[1] else ""

            # Update segments with new speaker names
            if segments:
                for segment in segments:
                    old_speaker = segment.get('speaker', '')
                    if old_speaker in speaker_mappings:
                        segment['speaker'] = speaker_mappings[old_speaker]

            # Update formatted text with new speaker names
            if formatted_text:
                for old_speaker, new_speaker in speaker_mappings.items():
                    # Replace speaker names in formatted text
                    formatted_text = formatted_text.replace(f"[{old_speaker}]", f"[{new_speaker}]")

            # Save updated data to database
            cursor.execute("""
                UPDATE transcriptions
                SET transcription_segments = %s,
                    transcription_formatted = %s,
                    speaker_mappings = %s
                WHERE id = %s
            """, (json.dumps(segments), formatted_text, json.dumps(speaker_mappings), transcription_id))

            conn.commit()
            cursor.close()

            logger.info(f"Successfully updated speakers for transcription {transcription_id}")

            return jsonify({
                'success': True,
                'message': 'Speaker names updated successfully',
                'transcription_segments': segments,
                'transcription_formatted': formatted_text,
                'speaker_mappings': speaker_mappings
            }), 200

        finally:
            return_db_connection(conn)

    except Exception as e:
        logger.error(f"Update speakers error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/transcriptions/<int:transcription_id>/update-segment-speakers', methods=['POST'])
def update_segment_speakers(transcription_id):
    """Update individual segment speaker assignments"""
    try:
        data = request.get_json()
        if not data or 'segment_updates' not in data:
            return jsonify({'error': 'segment_updates required'}), 400

        segment_updates = data['segment_updates']
        if not isinstance(segment_updates, dict):
            return jsonify({'error': 'segment_updates must be a dictionary'}), 400

        logger.info(f"Updating segment speakers for transcription {transcription_id}: {segment_updates}")

        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500

        try:
            cursor = conn.cursor()

            # Get current transcription data
            cursor.execute("""
                SELECT transcription_segments, transcription_formatted
                FROM transcriptions
                WHERE id = %s
            """, (transcription_id,))

            row = cursor.fetchone()
            if not row:
                return jsonify({'error': 'Transcription not found'}), 404

            segments = row[0] if row[0] else []
            formatted_text = row[1] if row[1] else ""

            # Update specific segments with new speaker assignments
            if segments:
                for segment_index, new_speaker in segment_updates.items():
                    try:
                        index = int(segment_index)
                        if 0 <= index < len(segments):
                            segments[index]['speaker'] = new_speaker
                            logger.info(f"Updated segment {index} speaker to {new_speaker}")
                    except (ValueError, IndexError) as e:
                        logger.warning(f"Invalid segment index {segment_index}: {e}")
                        continue

            # Regenerate formatted text with updated speakers
            if segments:
                formatted_text = format_with_timestamps(segments)

            # Save updated data to database
            cursor.execute("""
                UPDATE transcriptions
                SET transcription_segments = %s,
                    transcription_formatted = %s
                WHERE id = %s
            """, (json.dumps(segments), formatted_text, transcription_id))

            conn.commit()
            cursor.close()

            logger.info(f"Successfully updated segment speakers for transcription {transcription_id}")

            return jsonify({
                'success': True,
                'message': 'Segment speakers updated successfully',
                'transcription_segments': segments,
                'transcription_formatted': formatted_text
            }), 200

        finally:
            return_db_connection(conn)

    except Exception as e:
        logger.error(f"Update segment speakers error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/speakers', methods=['GET'])
def list_speakers():
    """List all speaker profiles"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500

        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, speaker_name, sample_count, first_seen, last_seen,
                       total_duration_seconds, description, tags, confidence_score, is_active
                FROM speaker_profiles
                ORDER BY last_seen DESC
            """)

            speakers = []
            for row in cursor.fetchall():
                speakers.append({
                    'id': row[0],
                    'speaker_name': row[1],
                    'sample_count': row[2],
                    'first_seen': row[3].isoformat() if row[3] else None,
                    'last_seen': row[4].isoformat() if row[4] else None,
                    'total_duration_seconds': float(row[5]) if row[5] else 0,
                    'description': row[6],
                    'tags': row[7] or [],
                    'confidence_score': float(row[8]) if row[8] else 1.0,
                    'is_active': row[9]
                })

            cursor.close()
            return jsonify({'speakers': speakers}), 200

        finally:
            return_db_connection(conn)

    except Exception as e:
        logger.error(f"List speakers error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/speakers', methods=['POST'])
def create_or_update_speaker():
    """Create a new speaker profile or update existing one from transcription"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        speaker_name = data.get('speaker_name')
        transcription_id = data.get('transcription_id')
        detected_speaker_label = data.get('detected_speaker_label')

        if not speaker_name or not transcription_id or not detected_speaker_label:
            return jsonify({'error': 'speaker_name, transcription_id, and detected_speaker_label required'}), 400

        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500

        try:
            cursor = conn.cursor()

            # Get the speaker embedding and stats from mapping table
            cursor.execute("""
                SELECT average_embedding, segment_count, total_duration_seconds
                FROM speaker_transcription_mapping
                WHERE transcription_id = %s AND detected_speaker_label = %s
            """, (transcription_id, detected_speaker_label))

            row = cursor.fetchone()
            if not row:
                return jsonify({'error': 'Speaker mapping not found'}), 404

            embedding, segment_count, duration = row

            # Check if speaker profile already exists
            cursor.execute("""
                SELECT id, voice_embedding, sample_count, total_duration_seconds
                FROM speaker_profiles
                WHERE speaker_name = %s
            """, (speaker_name,))

            existing = cursor.fetchone()

            if existing:
                # Update existing profile with weighted average
                profile_id = existing[0]
                old_embedding = existing[1]
                old_count = existing[2]
                old_duration = existing[3]

                # Weighted average of embeddings
                new_embedding_array = np.array(embedding)
                old_embedding_array = np.array(old_embedding)
                total_count = old_count + segment_count
                merged_embedding = (
                    (old_embedding_array * old_count + new_embedding_array * segment_count) / total_count
                ).tolist()

                cursor.execute("""
                    UPDATE speaker_profiles
                    SET voice_embedding = %s,
                        sample_count = %s,
                        total_duration_seconds = %s,
                        last_seen = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (merged_embedding, total_count, old_duration + duration, profile_id))

                logger.info(f"Updated speaker profile '{speaker_name}' (ID {profile_id})")

            else:
                # Create new profile
                description = data.get('description', '')
                tags = data.get('tags', [])

                cursor.execute("""
                    INSERT INTO speaker_profiles
                    (speaker_name, voice_embedding, sample_count, total_duration_seconds, description, tags)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (speaker_name, embedding, segment_count, duration, description, tags))

                profile_id = cursor.fetchone()[0]
                logger.info(f"Created new speaker profile '{speaker_name}' (ID {profile_id})")

            # Update mapping to link to profile
            cursor.execute("""
                UPDATE speaker_transcription_mapping
                SET speaker_profile_id = %s, is_confirmed = TRUE
                WHERE transcription_id = %s AND detected_speaker_label = %s
            """, (profile_id, transcription_id, detected_speaker_label))

            conn.commit()
            cursor.close()

            return jsonify({
                'success': True,
                'profile_id': profile_id,
                'speaker_name': speaker_name,
                'message': 'Speaker profile saved successfully'
            }), 200

        finally:
            return_db_connection(conn)

    except Exception as e:
        logger.error(f"Create/update speaker error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/speakers/<int:profile_id>', methods=['PUT'])
def update_speaker_profile(profile_id):
    """Update speaker profile metadata (name, description, tags)"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500

        try:
            cursor = conn.cursor()

            # Build update query dynamically based on provided fields
            updates = []
            params = []

            if 'speaker_name' in data:
                updates.append("speaker_name = %s")
                params.append(data['speaker_name'])

            if 'description' in data:
                updates.append("description = %s")
                params.append(data['description'])

            if 'tags' in data:
                updates.append("tags = %s")
                params.append(data['tags'])

            if not updates:
                return jsonify({'error': 'No fields to update'}), 400

            params.append(profile_id)
            query = f"UPDATE speaker_profiles SET {', '.join(updates)} WHERE id = %s"

            cursor.execute(query, params)
            conn.commit()
            cursor.close()

            logger.info(f"Updated speaker profile {profile_id}")

            return jsonify({
                'success': True,
                'message': 'Speaker profile updated successfully'
            }), 200

        finally:
            return_db_connection(conn)

    except Exception as e:
        logger.error(f"Update speaker profile error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/speakers/<int:profile_id>', methods=['DELETE'])
def deactivate_speaker_profile(profile_id):
    """Deactivate a speaker profile (soft delete)"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500

        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE speaker_profiles
                SET is_active = FALSE
                WHERE id = %s
            """, (profile_id,))

            conn.commit()
            cursor.close()

            logger.info(f"Deactivated speaker profile {profile_id}")

            return jsonify({
                'success': True,
                'message': 'Speaker profile deactivated successfully'
            }), 200

        finally:
            return_db_connection(conn)

    except Exception as e:
        logger.error(f"Deactivate speaker profile error: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5008, debug=False)
