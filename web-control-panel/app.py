from flask import Flask, render_template, jsonify, request
import psycopg2
import os
import requests
import json
import subprocess

app = Flask(__name__)

# Database configuration
DB_HOST = os.getenv('DB_HOST', 'postgres')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'mumble_ai')
DB_USER = os.getenv('DB_USER', 'mumbleai')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'mumbleai123')

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
            'timestamp': row[5].isoformat()
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
        'extracted_at': m[4].isoformat() if m[4] else None,
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
               timezone, last_sent
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
        'last_sent': row[10].isoformat() if row[10] else None
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

    if 'daily_summary_enabled' in data:
        updates.append("daily_summary_enabled = %s")
        params.append(data['daily_summary_enabled'])

    if 'summary_time' in data:
        updates.append("summary_time = %s")
        params.append(data['summary_time'])

    if 'timezone' in data:
        updates.append("timezone = %s")
        params.append(data['timezone'])

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
