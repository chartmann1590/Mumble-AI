from flask import Flask, render_template, jsonify, request
import psycopg2
import os
import requests
import json
import subprocess
import pytz
from datetime import datetime

app = Flask(__name__)

# Database configuration
DB_HOST = os.getenv('DB_HOST', 'postgres')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'mumble_ai')
DB_USER = os.getenv('DB_USER', 'mumbleai')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'mumbleai123')

# Timezone configuration
NY_TZ = pytz.timezone('America/New_York')

def format_timestamp_ny(timestamp):
    """Convert UTC timestamp to NY time and format as ISO string"""
    if timestamp is None:
        return None
    # Ensure timestamp is timezone-aware (assume UTC if naive)
    if timestamp.tzinfo is None:
        timestamp = pytz.utc.localize(timestamp)
    # Convert to NY time
    ny_time = timestamp.astimezone(NY_TZ)
    return ny_time.isoformat()

# Config storage in database
def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )

def init_config_table():
    """Initialize config table if it doesn't exist"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_config (
            key VARCHAR(255) PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Initialize schedule_events table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schedule_events (
            id SERIAL PRIMARY KEY,
            user_name VARCHAR(255) NOT NULL,
            title VARCHAR(500) NOT NULL,
            event_date DATE NOT NULL,
            event_time TIME,
            description TEXT,
            importance INTEGER DEFAULT 5 CHECK (importance >= 1 AND importance <= 10),
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Insert default values if not exists
    cursor.execute("""
        INSERT INTO bot_config (key, value) VALUES ('ollama_url', 'http://host.docker.internal:11434')
        ON CONFLICT (key) DO NOTHING
    """)
    cursor.execute("""
        INSERT INTO bot_config (key, value) VALUES ('ollama_model', 'llama3.2:latest')
        ON CONFLICT (key) DO NOTHING
    """)
    cursor.execute("""
        INSERT INTO bot_config (key, value) VALUES ('piper_voice', 'en_US-lessac-medium')
        ON CONFLICT (key) DO NOTHING
    """)
    cursor.execute("""
        INSERT INTO bot_config (key, value) VALUES ('bot_persona', '')
        ON CONFLICT (key) DO NOTHING
    """)
    cursor.execute("""
        INSERT INTO bot_config (key, value) VALUES ('whisper_language', 'auto')
        ON CONFLICT (key) DO NOTHING
    """)
    cursor.execute("""
        INSERT INTO bot_config (key, value) VALUES ('tts_engine', 'piper')
        ON CONFLICT (key) DO NOTHING
    """)
    cursor.execute("""
        INSERT INTO bot_config (key, value) VALUES ('silero_voice', 'en_0')
        ON CONFLICT (key) DO NOTHING
    """)

    conn.commit()
    cursor.close()
    conn.close()

# Initialize on startup
init_config_table()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/schedule')
def schedule():
    return render_template('schedule.html')

# Ollama Management
@app.route('/api/ollama/config', methods=['GET'])
def get_ollama_config():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM bot_config WHERE key = 'ollama_url'")
    url = cursor.fetchone()[0]
    cursor.execute("SELECT value FROM bot_config WHERE key = 'ollama_model'")
    model = cursor.fetchone()[0]
    cursor.close()
    conn.close()

    return jsonify({'url': url, 'model': model})

@app.route('/api/ollama/config', methods=['POST'])
def update_ollama_config():
    data = request.json
    conn = get_db_connection()
    cursor = conn.cursor()

    if 'url' in data:
        cursor.execute("UPDATE bot_config SET value = %s, updated_at = CURRENT_TIMESTAMP WHERE key = 'ollama_url'", (data['url'],))

    if 'model' in data:
        cursor.execute("UPDATE bot_config SET value = %s, updated_at = CURRENT_TIMESTAMP WHERE key = 'ollama_model'", (data['model'],))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'success': True})

@app.route('/api/ollama/models', methods=['GET'])
def get_ollama_models():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM bot_config WHERE key = 'ollama_url'")
    url = cursor.fetchone()[0]
    cursor.close()
    conn.close()

    try:
        response = requests.get(f"{url}/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get('models', [])
            return jsonify({'models': [m['name'] for m in models]})
        else:
            return jsonify({'error': 'Failed to fetch models'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Conversation History
@app.route('/api/conversations', methods=['GET'])
def get_conversations():
    limit = request.args.get('limit', 100, type=int)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, user_name, message_type, role, message, timestamp
        FROM conversation_history
        ORDER BY timestamp DESC
        LIMIT %s
    """, (limit,))

    conversations = []
    for row in cursor.fetchall():
        conversations.append({
            'id': row[0],
            'user_name': row[1],
            'message_type': row[2],
            'role': row[3],
            'message': row[4],
            'timestamp': format_timestamp_ny(row[5])
        })

    cursor.close()
    conn.close()

    return jsonify({'conversations': conversations})

@app.route('/api/conversations/reset', methods=['POST'])
def reset_conversations():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM conversation_history")
    deleted_count = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'success': True, 'deleted': deleted_count})

# Voice metadata mapping
VOICE_METADATA = {
    # English - US
    'en_US': {'region': 'English - US', 'lang': 'English'},
    # English - GB
    'en_GB': {'region': 'English - UK', 'lang': 'English'},
    # Czech
    'cs_CZ': {'region': 'Czech', 'lang': 'Czech'},
    # Spanish
    'es_AR': {'region': 'Spanish - Argentina', 'lang': 'Spanish'},
    'es_ES': {'region': 'Spanish - Spain', 'lang': 'Spanish'},
    'es_MX': {'region': 'Spanish - Mexico', 'lang': 'Spanish'},
    # Hindi
    'hi_IN': {'region': 'Hindi - India', 'lang': 'Hindi'},
    # Malayalam
    'ml_IN': {'region': 'Malayalam - India', 'lang': 'Malayalam'},
    # Nepali
    'ne_NP': {'region': 'Nepali', 'lang': 'Nepali'},
    # Vietnamese
    'vi_VN': {'region': 'Vietnamese', 'lang': 'Vietnamese'},
    # Chinese
    'zh_CN': {'region': 'Chinese - Mandarin', 'lang': 'Chinese'},
}

# Gender indicators in voice names
FEMALE_NAMES = ['lessac', 'amy', 'kristin', 'kathleen', 'hfc_female', 'alba', 'jenny', 'female', 'daniela', 'priyamvada', 'meera']
MALE_NAMES = ['joe', 'bryce', 'danny', 'john', 'kusal', 'hfc_male', 'alan', 'male', 'carlfm', 'davefx', 'pratham']

def get_voice_gender(voice_name):
    """Determine gender from voice name"""
    voice_lower = voice_name.lower()
    for female in FEMALE_NAMES:
        if female in voice_lower:
            return 'Female'
    for male in MALE_NAMES:
        if male in voice_lower:
            return 'Male'
    return 'Neutral'

def parse_voice_name(voice_name):
    """Parse voice name into components"""
    parts = voice_name.split('-')
    if len(parts) >= 3:
        region_code = parts[0]
        speaker = parts[1]
        quality = parts[2]

        region_info = VOICE_METADATA.get(region_code, {'region': region_code, 'lang': region_code})
        gender = get_voice_gender(speaker)

        return {
            'name': voice_name,
            'region': region_info['region'],
            'language': region_info['lang'],
            'speaker': speaker,
            'quality': quality,
            'gender': gender
        }
    return {
        'name': voice_name,
        'region': 'Unknown',
        'language': 'Unknown',
        'speaker': voice_name,
        'quality': 'unknown',
        'gender': 'Neutral'
    }

# Piper Voice Management
@app.route('/api/piper/voices', methods=['GET'])
def get_piper_voices():
    voices_dir = '/app/piper_voices'
    voices = []

    if os.path.exists(voices_dir):
        for filename in os.listdir(voices_dir):
            if filename.endswith('.onnx'):
                voice_name = filename.replace('.onnx', '')
                voice_info = parse_voice_name(voice_name)
                voices.append(voice_info)

    # Sort by region, then gender, then speaker name
    voices.sort(key=lambda x: (x['region'], x['gender'], x['speaker']))

    return jsonify({'voices': voices})

@app.route('/api/piper/current', methods=['GET'])
def get_current_voice():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM bot_config WHERE key = 'piper_voice'")
    voice = cursor.fetchone()[0]
    cursor.close()
    conn.close()

    return jsonify({'voice': voice})

@app.route('/api/piper/current', methods=['POST'])
def set_current_voice():
    data = request.json
    voice = data.get('voice')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE bot_config SET value = %s, updated_at = CURRENT_TIMESTAMP WHERE key = 'piper_voice'", (voice,))
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'success': True})

@app.route('/api/piper/preview', methods=['POST'])
def preview_voice():
    """Preview a voice by generating sample audio"""
    data = request.json
    voice = data.get('voice')

    if not voice:
        return jsonify({'error': 'No voice specified'}), 400

    # Update the current voice temporarily for preview
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM bot_config WHERE key = 'piper_voice'")
    original_voice = cursor.fetchone()[0]

    # Set the voice to preview
    cursor.execute("UPDATE bot_config SET value = %s WHERE key = 'piper_voice'", (voice,))
    conn.commit()
    cursor.close()
    conn.close()

    try:
        # Generate preview audio
        preview_text = "Hello, this is a preview of this voice. How do I sound?"
        response = requests.post(
            'http://piper-tts:5001/synthesize',
            json={'text': preview_text},
            timeout=10
        )

        if response.status_code == 200:
            # Restore original voice
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE bot_config SET value = %s WHERE key = 'piper_voice'", (original_voice,))
            conn.commit()
            cursor.close()
            conn.close()

            # Return audio as response
            return response.content, 200, {'Content-Type': 'audio/wav'}
        else:
            return jsonify({'error': 'Failed to generate preview'}), 500

    except Exception as e:
        # Restore original voice on error
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE bot_config SET value = %s WHERE key = 'piper_voice'", (original_voice,))
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({'error': str(e)}), 500

# Persona Management
@app.route('/api/persona', methods=['GET'])
def get_persona():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM bot_config WHERE key = 'bot_persona'")
    result = cursor.fetchone()
    persona = result[0] if result else ''
    cursor.close()
    conn.close()

    return jsonify({'persona': persona})

@app.route('/api/persona', methods=['POST'])
def set_persona():
    data = request.json
    persona = data.get('persona', '')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE bot_config SET value = %s, updated_at = CURRENT_TIMESTAMP WHERE key = 'bot_persona'", (persona,))
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'success': True})

@app.route('/api/persona/enhance', methods=['POST'])
def enhance_persona():
    """Use Ollama to enhance the persona description"""
    data = request.json
    current_persona = data.get('persona', '')

    if not current_persona:
        return jsonify({'error': 'No persona provided'}), 400

    try:
        # Get Ollama config
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM bot_config WHERE key = 'ollama_url'")
        ollama_url = cursor.fetchone()[0]
        cursor.execute("SELECT value FROM bot_config WHERE key = 'ollama_model'")
        ollama_model = cursor.fetchone()[0]
        cursor.close()
        conn.close()

        # Create enhancement prompt
        enhancement_prompt = f"""You are an expert at creating detailed AI assistant personas.

The user has provided this basic persona description:
"{current_persona}"

Expand and enhance this persona description to create a comprehensive, detailed character profile that an AI can use to guide its behavior and responses. Include:
- Personality traits and communication style
- Tone and manner of speaking
- Areas of expertise or interests
- How they should interact with users
- Any quirks or distinctive characteristics

Keep it concise but detailed (2-4 paragraphs). Write in second person (e.g., "You are...").

Enhanced persona:"""

        # Call Ollama
        response = requests.post(
            f"{ollama_url}/api/generate",
            json={
                'model': ollama_model,
                'prompt': enhancement_prompt,
                'stream': False
            },
            timeout=60
        )

        if response.status_code == 200:
            enhanced_persona = response.json().get('response', '').strip()
            return jsonify({'enhanced_persona': enhanced_persona})
        else:
            return jsonify({'error': 'Failed to enhance persona'}), 500

    except Exception as e:
        print(f"Error enhancing persona: {e}")
        return jsonify({'error': str(e)}), 500

# Whisper Language Configuration
@app.route('/api/whisper/language', methods=['GET'])
def get_whisper_language():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM bot_config WHERE key = 'whisper_language'")
    result = cursor.fetchone()
    language = result[0] if result else 'auto'
    cursor.close()
    conn.close()

    return jsonify({'language': language})

@app.route('/api/whisper/language', methods=['POST'])
def set_whisper_language():
    data = request.json
    language = data.get('language', 'auto')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE bot_config SET value = %s, updated_at = CURRENT_TIMESTAMP WHERE key = 'whisper_language'", (language,))
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'success': True})

# TTS Engine Configuration
@app.route('/api/tts/engine', methods=['GET'])
def get_tts_engine():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM bot_config WHERE key = 'tts_engine'")
    result = cursor.fetchone()
    engine = result[0] if result else 'piper'
    cursor.close()
    conn.close()

    return jsonify({'engine': engine})

@app.route('/api/tts/engine', methods=['POST'])
def set_tts_engine():
    data = request.json
    engine = data.get('engine', 'piper')

    if engine not in ['piper', 'silero']:
        return jsonify({'error': 'Invalid TTS engine'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE bot_config SET value = %s, updated_at = CURRENT_TIMESTAMP WHERE key = 'tts_engine'", (engine,))
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'success': True})

# Silero Voice Configuration
@app.route('/api/silero/voices', methods=['GET'])
def get_silero_voices():
    """Get available Silero voices from the Silero service"""
    try:
        response = requests.get('http://silero-tts:5004/voices', timeout=5)
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({'error': 'Failed to fetch voices'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/silero/current', methods=['GET'])
def get_current_silero_voice():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM bot_config WHERE key = 'silero_voice'")
    result = cursor.fetchone()
    voice = result[0] if result else 'en_0'
    cursor.close()
    conn.close()

    return jsonify({'voice': voice})

@app.route('/api/silero/current', methods=['POST'])
def set_current_silero_voice():
    data = request.json
    voice = data.get('voice')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE bot_config SET value = %s, updated_at = CURRENT_TIMESTAMP WHERE key = 'silero_voice'", (voice,))
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'success': True})

@app.route('/api/silero/preview', methods=['POST'])
def preview_silero_voice():
    """Preview a Silero voice by generating sample audio"""
    from flask import Response
    data = request.json
    voice = data.get('voice')

    if not voice:
        return jsonify({'error': 'No voice specified'}), 400

    try:
        # Generate preview audio
        preview_text = "Hello, this is a preview of this voice. How do I sound?"
        response = requests.post(
            'http://silero-tts:5004/synthesize',
            json={'text': preview_text, 'voice': voice},
            timeout=10
        )

        if response.status_code == 200:
            # Return audio as response using Flask Response
            return Response(response.content, mimetype='audio/wav')
        else:
            return jsonify({'error': 'Failed to generate preview'}), 500

    except Exception as e:
        logging.error(f"Error in Silero preview: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# Statistics
@app.route('/api/stats', methods=['GET'])
def get_stats():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM conversation_history")
    total_messages = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT user_name) FROM conversation_history")
    unique_users = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM conversation_history WHERE message_type = 'voice'")
    voice_messages = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM conversation_history WHERE message_type = 'text'")
    text_messages = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    return jsonify({
        'total_messages': total_messages,
        'unique_users': unique_users,
        'voice_messages': voice_messages,
        'text_messages': text_messages
    })

# Persistent Memories API
@app.route('/api/memories', methods=['GET'])
def get_memories():
    """Get all persistent memories, optionally filtered by user"""
    user_name = request.args.get('user')
    category = request.args.get('category')

    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
        SELECT id, user_name, category, content, extracted_at, importance, tags, active
        FROM persistent_memories
        WHERE active = TRUE
    """
    params = []

    if user_name:
        query += " AND user_name = %s"
        params.append(user_name)

    if category:
        query += " AND category = %s"
        params.append(category)

    query += " ORDER BY importance DESC, extracted_at DESC"

    cursor.execute(query, params)
    memories = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify([{
        'id': m[0],
        'user_name': m[1],
        'category': m[2],
        'content': m[3],
        'extracted_at': format_timestamp_ny(m[4]) if m[4] else None,
        'importance': m[5],
        'tags': m[6] or [],
        'active': m[7]
    } for m in memories])

@app.route('/api/memories', methods=['POST'])
def add_memory():
    """Manually add a persistent memory"""
    data = request.json

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO persistent_memories (user_name, category, content, importance, tags)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
    """, (
        data.get('user_name'),
        data.get('category', 'other'),
        data.get('content'),
        data.get('importance', 5),
        data.get('tags', [])
    ))

    memory_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'id': memory_id, 'status': 'created'})

@app.route('/api/memories/<int:memory_id>', methods=['DELETE'])
def delete_memory(memory_id):
    """Delete (deactivate) a memory"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE persistent_memories
        SET active = FALSE
        WHERE id = %s
    """, (memory_id,))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'status': 'deleted'})

@app.route('/api/memories/<int:memory_id>', methods=['PUT'])
def update_memory(memory_id):
    """Update a memory"""
    data = request.json

    conn = get_db_connection()
    cursor = conn.cursor()

    # Build update query dynamically based on provided fields
    updates = []
    params = []

    if 'content' in data:
        updates.append("content = %s")
        params.append(data['content'])

    if 'category' in data:
        updates.append("category = %s")
        params.append(data['category'])

    if 'importance' in data:
        updates.append("importance = %s")
        params.append(data['importance'])

    if 'tags' in data:
        updates.append("tags = %s")
        params.append(data['tags'])

    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(memory_id)

        query = f"UPDATE persistent_memories SET {', '.join(updates)} WHERE id = %s"
        cursor.execute(query, params)
        conn.commit()

    cursor.close()
    conn.close()

    return jsonify({'status': 'updated'})

@app.route('/api/users', methods=['GET'])
def get_users():
    """Get list of users who have memories"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT user_name
        FROM persistent_memories
        WHERE active = TRUE
        ORDER BY user_name
    """)

    users = [row[0] for row in cursor.fetchall()]

    cursor.close()
    conn.close()

    return jsonify(users)

# Email Settings API
@app.route('/api/email/settings', methods=['GET'])
def get_email_settings():
    """Get email configuration settings"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT smtp_host, smtp_port, smtp_username, smtp_use_tls, smtp_use_ssl,
               from_email, recipient_email, daily_summary_enabled, summary_time,
               timezone, last_sent, imap_enabled, imap_host, imap_port, imap_username,
               imap_use_ssl, imap_mailbox, auto_reply_enabled, reply_signature,
               check_interval_seconds, last_checked
        FROM email_settings
        WHERE id = 1
    """)

    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        return jsonify({'error': 'Email settings not found'}), 404

    return jsonify({
        'smtp_host': row[0],
        'smtp_port': row[1],
        'smtp_username': row[2],
        'smtp_use_tls': row[3],
        'smtp_use_ssl': row[4],
        'from_email': row[5],
        'recipient_email': row[6],
        'daily_summary_enabled': row[7],
        'summary_time': str(row[8]) if row[8] else '22:00:00',
        'timezone': row[9],
        'last_sent': format_timestamp_ny(row[10]) if row[10] else None,
        'imap_enabled': row[11] if row[11] is not None else False,
        'imap_host': row[12],
        'imap_port': row[13] if row[13] is not None else 993,
        'imap_username': row[14],
        'imap_use_ssl': row[15] if row[15] is not None else True,
        'imap_mailbox': row[16] if row[16] else 'INBOX',
        'auto_reply_enabled': row[17] if row[17] is not None else False,
        'reply_signature': row[18] if row[18] else '',
        'check_interval_seconds': row[19] if row[19] is not None else 300,
        'last_checked': format_timestamp_ny(row[20]) if row[20] else None
    })

@app.route('/api/email/settings', methods=['POST'])
def update_email_settings():
    """Update email configuration settings"""
    data = request.json
    conn = get_db_connection()
    cursor = conn.cursor()

    # Build update query
    updates = []
    params = []

    # SMTP settings
    if 'smtp_host' in data:
        updates.append("smtp_host = %s")
        params.append(data['smtp_host'])

    if 'smtp_port' in data:
        updates.append("smtp_port = %s")
        params.append(data['smtp_port'])

    if 'smtp_username' in data:
        updates.append("smtp_username = %s")
        params.append(data['smtp_username'])

    if 'smtp_password' in data:
        updates.append("smtp_password = %s")
        params.append(data['smtp_password'])

    if 'smtp_use_tls' in data:
        updates.append("smtp_use_tls = %s")
        params.append(data['smtp_use_tls'])

    if 'smtp_use_ssl' in data:
        updates.append("smtp_use_ssl = %s")
        params.append(data['smtp_use_ssl'])

    if 'from_email' in data:
        updates.append("from_email = %s")
        params.append(data['from_email'])

    if 'recipient_email' in data:
        updates.append("recipient_email = %s")
        params.append(data['recipient_email'])

    # Daily summary settings
    if 'daily_summary_enabled' in data:
        updates.append("daily_summary_enabled = %s")
        params.append(data['daily_summary_enabled'])

    if 'summary_time' in data:
        updates.append("summary_time = %s")
        params.append(data['summary_time'])

    if 'timezone' in data:
        updates.append("timezone = %s")
        params.append(data['timezone'])

    # IMAP settings
    if 'imap_enabled' in data:
        updates.append("imap_enabled = %s")
        params.append(data['imap_enabled'])

    if 'imap_host' in data:
        updates.append("imap_host = %s")
        params.append(data['imap_host'])

    if 'imap_port' in data:
        updates.append("imap_port = %s")
        params.append(data['imap_port'])

    if 'imap_username' in data:
        updates.append("imap_username = %s")
        params.append(data['imap_username'])

    if 'imap_password' in data:
        updates.append("imap_password = %s")
        params.append(data['imap_password'])

    if 'imap_use_ssl' in data:
        updates.append("imap_use_ssl = %s")
        params.append(data['imap_use_ssl'])

    if 'imap_mailbox' in data:
        updates.append("imap_mailbox = %s")
        params.append(data['imap_mailbox'])

    # AI reply settings
    if 'auto_reply_enabled' in data:
        updates.append("auto_reply_enabled = %s")
        params.append(data['auto_reply_enabled'])

    if 'reply_signature' in data:
        updates.append("reply_signature = %s")
        params.append(data['reply_signature'])

    if 'check_interval_seconds' in data:
        updates.append("check_interval_seconds = %s")
        params.append(data['check_interval_seconds'])

    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(1)  # id = 1

        query = f"UPDATE email_settings SET {', '.join(updates)} WHERE id = %s"
        cursor.execute(query, params)
        conn.commit()

    cursor.close()
    conn.close()

    return jsonify({'success': True})

@app.route('/api/email/test', methods=['POST'])
def send_test_email():
    """Send a test email using current settings"""
    try:
        # Import the email service functionality
        import sys
        sys.path.insert(0, '/email-summary-service')

        # Get email settings
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT smtp_host, smtp_port, smtp_username, smtp_password,
                   smtp_use_tls, smtp_use_ssl, from_email, recipient_email, timezone
            FROM email_settings
            WHERE id = 1
        """)

        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if not row:
            return jsonify({'error': 'Email settings not configured'}), 400

        settings = {
            'smtp_host': row[0],
            'smtp_port': row[1],
            'smtp_username': row[2],
            'smtp_password': row[3],
            'smtp_use_tls': row[4],
            'smtp_use_ssl': row[5],
            'from_email': row[6],
            'recipient_email': row[7],
            'timezone': row[8]
        }

        if not settings['recipient_email']:
            return jsonify({'error': 'No recipient email configured'}), 400

        # Send test email inline
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from email.utils import formatdate
        from datetime import datetime
        import pytz

        msg = MIMEMultipart('alternative')
        msg['Subject'] = '[TEST] Mumble AI Email System'
        msg['From'] = settings['from_email']
        msg['To'] = settings['recipient_email']
        msg['Date'] = formatdate(localtime=True)

        plain_text = "This is a test email from Mumble AI. If you received this, your email settings are configured correctly!"
        html_text = """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px; }
        .content { padding: 20px; background: #f4f4f4; border-radius: 8px; margin-top: 20px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 style="margin: 0;">🤖 Mumble AI Test Email</h1>
        </div>
        <div class="content">
            <p><strong>This is a test email from Mumble AI.</strong></p>
            <p>If you received this, your email settings are configured correctly!</p>
            <p>Daily summaries will be sent at your configured time.</p>
        </div>
    </div>
</body>
</html>
"""

        msg.attach(MIMEText(plain_text, 'plain', 'utf-8'))
        msg.attach(MIMEText(html_text, 'html', 'utf-8'))

        # Send email
        if settings['smtp_use_ssl']:
            smtp = smtplib.SMTP_SSL(settings['smtp_host'], settings['smtp_port'], timeout=30)
        else:
            smtp = smtplib.SMTP(settings['smtp_host'], settings['smtp_port'], timeout=30)
            if settings['smtp_use_tls']:
                smtp.starttls()

        # Login if credentials provided
        if settings['smtp_username'] and settings['smtp_password']:
            smtp.login(settings['smtp_username'], settings['smtp_password'])

        smtp.send_message(msg)
        smtp.quit()

        return jsonify({'success': True, 'message': 'Test email sent successfully'})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/email/generate-signature', methods=['POST'])
def generate_email_signature():
    """Generate an email signature based on the bot's persona using AI"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get bot persona and Ollama config
        cursor.execute("SELECT value FROM bot_config WHERE key = 'bot_persona'")
        row = cursor.fetchone()
        bot_persona = row[0] if row else "a helpful AI assistant"

        cursor.execute("SELECT value FROM bot_config WHERE key = 'ollama_url'")
        row = cursor.fetchone()
        ollama_url = row[0] if row else 'http://host.docker.internal:11434'

        cursor.execute("SELECT value FROM bot_config WHERE key = 'ollama_model'")
        row = cursor.fetchone()
        ollama_model = row[0] if row else 'llama3.2:latest'

        cursor.close()
        conn.close()

        # Generate signature using Ollama
        import requests

        signature_prompt = f"""You are {bot_persona}.

Generate a professional email signature for yourself that will be used in email replies. The signature should:
- Be concise (2-4 lines maximum)
- Reflect your personality/persona
- Be professional but friendly
- Include a sign-off like "Best regards" or similar
- DO NOT include contact information, emails, or phone numbers
- Just the text - no HTML or markdown formatting

Example format:
Best regards,
[Your Name/Title]
[Optional tagline]

Your signature:"""

        response = requests.post(
            f"{ollama_url}/api/generate",
            json={
                'model': ollama_model,
                'prompt': signature_prompt,
                'stream': False,
                'options': {
                    'temperature': 0.7,
                    'num_predict': 150
                }
            },
            timeout=60
        )

        if response.status_code == 200:
            result = response.json()
            signature = result.get('response', '').strip()
            return jsonify({'success': True, 'signature': signature})
        else:
            return jsonify({'error': 'Failed to generate signature from Ollama'}), 500

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# Email User Mappings API
@app.route('/api/email/mappings', methods=['GET'])
def get_email_mappings():
    """Get all email user mappings"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, email_address, user_name, notes, created_at, updated_at
            FROM email_user_mappings
            ORDER BY created_at DESC
        """)

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        mappings = []
        for row in rows:
            mappings.append({
                'id': row[0],
                'email_address': row[1],
                'user_name': row[2],
                'notes': row[3],
                'created_at': format_timestamp_ny(row[4]) if row[4] else None,
                'updated_at': format_timestamp_ny(row[5]) if row[5] else None
            })

        return jsonify(mappings)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/email/mappings', methods=['POST'])
def add_email_mapping():
    """Add a new email user mapping"""
    try:
        data = request.json
        email_address = data.get('email_address', '').strip()
        user_name = data.get('user_name', '').strip()
        notes = data.get('notes', '').strip()

        if not email_address or not user_name:
            return jsonify({'error': 'email_address and user_name are required'}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO email_user_mappings (email_address, user_name, notes)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (email_address, user_name, notes if notes else None))

        new_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({'success': True, 'id': new_id})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/email/mappings/<int:mapping_id>', methods=['PUT'])
def update_email_mapping(mapping_id):
    """Update an existing email user mapping"""
    try:
        data = request.json
        email_address = data.get('email_address', '').strip()
        user_name = data.get('user_name', '').strip()
        notes = data.get('notes', '').strip()

        if not email_address or not user_name:
            return jsonify({'error': 'email_address and user_name are required'}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE email_user_mappings
            SET email_address = %s,
                user_name = %s,
                notes = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (email_address, user_name, notes if notes else None, mapping_id))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({'success': True})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/email/mappings/<int:mapping_id>', methods=['DELETE'])
def delete_email_mapping(mapping_id):
    """Delete an email user mapping"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            DELETE FROM email_user_mappings
            WHERE id = %s
        """, (mapping_id,))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({'success': True})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/email/logs', methods=['GET'])
def get_email_logs():
    """Get email logs with optional filtering"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get query parameters
        direction = request.args.get('direction')  # 'received' or 'sent'
        email_type = request.args.get('type')  # 'reply', 'summary', 'test', 'other'
        status = request.args.get('status')  # 'success' or 'error'
        limit = int(request.args.get('limit', 100))  # Default 100 logs
        offset = int(request.args.get('offset', 0))  # For pagination

        # Build query with filters
        query = """
            SELECT id, direction, email_type, from_email, to_email, subject,
                   body_preview, full_body, status, error_message, mapped_user,
                   timestamp, created_at
            FROM email_logs
            WHERE 1=1
        """
        params = []

        if direction:
            query += " AND direction = %s"
            params.append(direction)

        if email_type:
            query += " AND email_type = %s"
            params.append(email_type)

        if status:
            query += " AND status = %s"
            params.append(status)

        # Order by newest first
        query += " ORDER BY timestamp DESC"

        # Add pagination
        query += " LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        cursor.execute(query, params)
        logs = cursor.fetchall()

        # Get total count for pagination
        count_query = """
            SELECT COUNT(*) FROM email_logs WHERE 1=1
        """
        count_params = []

        if direction:
            count_query += " AND direction = %s"
            count_params.append(direction)

        if email_type:
            count_query += " AND email_type = %s"
            count_params.append(email_type)

        if status:
            count_query += " AND status = %s"
            count_params.append(status)

        cursor.execute(count_query, count_params)
        total_count = cursor.fetchone()[0]

        cursor.close()
        conn.close()

        return jsonify({
            'logs': [{
                'id': log[0],
                'direction': log[1],
                'email_type': log[2],
                'from_email': log[3],
                'to_email': log[4],
                'subject': log[5],
                'body_preview': log[6],
                'full_body': log[7],
                'status': log[8],
                'error_message': log[9],
                'mapped_user': log[10],
                'timestamp': format_timestamp_ny(log[11]) if log[11] else None,
                'created_at': format_timestamp_ny(log[12]) if log[12] else None
            } for log in logs],
            'total': total_count,
            'limit': limit,
            'offset': offset
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# Schedule API
@app.route('/api/schedule', methods=['GET'])
def get_schedule():
    """Get all schedule events, optionally filtered by user"""
    user_name = request.args.get('user')

    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
        SELECT id, user_name, title, event_date, event_time, description, importance, created_at,
               reminder_enabled, reminder_minutes, recipient_email, reminder_sent
        FROM schedule_events
        WHERE active = TRUE
    """
    params = []

    if user_name:
        query += " AND user_name = %s"
        params.append(user_name)

    query += " ORDER BY event_date, event_time"

    cursor.execute(query, params)
    events = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify([{
        'id': e[0],
        'user_name': e[1],
        'title': e[2],
        'event_date': e[3].isoformat() if e[3] else None,
        'event_time': str(e[4]) if e[4] else None,
        'description': e[5],
        'importance': e[6],
        'created_at': format_timestamp_ny(e[7]) if e[7] else None,
        'reminder_enabled': e[8] if len(e) > 8 else False,
        'reminder_minutes': e[9] if len(e) > 9 else 60,
        'recipient_email': e[10] if len(e) > 10 else None,
        'reminder_sent': e[11] if len(e) > 11 else False
    } for e in events])

@app.route('/api/schedule', methods=['POST'])
def add_schedule_event():
    """Add a new schedule event"""
    data = request.json

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO schedule_events (user_name, title, event_date, event_time, description, importance, 
                                     reminder_enabled, reminder_minutes, recipient_email)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        data.get('user_name'),
        data.get('title'),
        data.get('event_date'),
        data.get('event_time'),
        data.get('description'),
        data.get('importance', 5),
        data.get('reminder_enabled', False),
        data.get('reminder_minutes', 60),
        data.get('recipient_email')
    ))

    event_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'id': event_id, 'status': 'created'})

@app.route('/api/schedule/<int:event_id>', methods=['PUT'])
def update_schedule_event(event_id):
    """Update a schedule event"""
    data = request.json

    conn = get_db_connection()
    cursor = conn.cursor()

    # Build update query dynamically based on provided fields
    updates = []
    params = []

    if 'user_name' in data:
        updates.append("user_name = %s")
        params.append(data['user_name'])

    if 'title' in data:
        updates.append("title = %s")
        params.append(data['title'])

    if 'event_date' in data:
        updates.append("event_date = %s")
        params.append(data['event_date'])

    if 'event_time' in data:
        updates.append("event_time = %s")
        params.append(data['event_time'])

    if 'description' in data:
        updates.append("description = %s")
        params.append(data['description'])

    if 'importance' in data:
        updates.append("importance = %s")
        params.append(data['importance'])

    if 'reminder_enabled' in data:
        updates.append("reminder_enabled = %s")
        params.append(data['reminder_enabled'])

    if 'reminder_minutes' in data:
        updates.append("reminder_minutes = %s")
        params.append(data['reminder_minutes'])

    if 'recipient_email' in data:
        updates.append("recipient_email = %s")
        params.append(data['recipient_email'])

    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(event_id)

        query = f"UPDATE schedule_events SET {', '.join(updates)} WHERE id = %s"
        cursor.execute(query, params)
        conn.commit()

    cursor.close()
    conn.close()

    return jsonify({'status': 'updated'})

@app.route('/api/schedule/<int:event_id>', methods=['DELETE'])
def delete_schedule_event(event_id):
    """Delete (deactivate) a schedule event"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE schedule_events
        SET active = FALSE
        WHERE id = %s
    """, (event_id,))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'status': 'deleted'})

@app.route('/api/schedule/users', methods=['GET'])
def get_schedule_users():
    """Get list of users who have schedule events"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT user_name
        FROM schedule_events
        WHERE active = TRUE
        ORDER BY user_name
    """)

    users = [row[0] for row in cursor.fetchall()]

    cursor.close()
    conn.close()

    return jsonify(users)

@app.route('/api/schedule/upcoming', methods=['GET'])
def get_upcoming_events():
    """Get upcoming schedule events for the next N days"""
    days_ahead = request.args.get('days', 7, type=int)
    limit = request.args.get('limit', 10, type=int)
    user_name = request.args.get('user')

    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
        SELECT id, user_name, title, event_date, event_time, description, importance, created_at,
               reminder_enabled, reminder_minutes, recipient_email, reminder_sent
        FROM schedule_events
        WHERE active = TRUE
          AND event_date >= CURRENT_DATE
          AND event_date <= CURRENT_DATE + INTERVAL '%s days'
    """
    params = [days_ahead]

    if user_name:
        query += " AND user_name = %s"
        params.append(user_name)

    query += " ORDER BY event_date, event_time LIMIT %s"
    params.append(limit)

    cursor.execute(query, params)

    events = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify([{
        'id': e[0],
        'user_name': e[1],
        'title': e[2],
        'event_date': e[3].isoformat() if e[3] else None,
        'event_time': str(e[4]) if e[4] else None,
        'description': e[5],
        'importance': e[6],
        'created_at': format_timestamp_ny(e[7]) if e[7] else None,
        'reminder_enabled': e[8] if len(e) > 8 else False,
        'reminder_minutes': e[9] if len(e) > 9 else 60,
        'recipient_email': e[10] if len(e) > 10 else None,
        'reminder_sent': e[11] if len(e) > 11 else False
    } for e in events])

def init_voices():
    """Ensure voices are downloaded on startup"""
    voices_dir = "/app/piper_voices"
    # Count how many .onnx files we have
    onnx_files = [f for f in os.listdir(voices_dir) if f.endswith('.onnx')]

    # If we have fewer than 25 voices, run the download script
    if len(onnx_files) < 25:
        print(f"Found only {len(onnx_files)} voices, downloading all voices...")
        try:
            subprocess.run(['python', '/app/download_voices.py'], check=True)
            print("Voice download complete!")
        except Exception as e:
            print(f"Error downloading voices: {e}")
    else:
        print(f"Found {len(onnx_files)} voices, skipping download")

if __name__ == '__main__':
    init_config_table()
    init_voices()
    app.run(host='0.0.0.0', port=5002, debug=False)
