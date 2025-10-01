import os
import time
import wave
import io
import logging
import threading
import requests
import subprocess
import tempfile
import psycopg2
from psycopg2 import pool
from pymumble_py3 import Mumble
from pymumble_py3.constants import PYMUMBLE_AUDIO_PER_PACKET

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class MumbleAIBot:
    def __init__(self):
        # Configuration
        self.mumble_host = os.getenv('MUMBLE_HOST', 'mumble-server')
        self.mumble_port = int(os.getenv('MUMBLE_PORT', '64738'))
        self.mumble_username = os.getenv('MUMBLE_USERNAME', 'AI-Bot')
        self.mumble_password = os.getenv('MUMBLE_PASSWORD', '')

        self.whisper_url = os.getenv('WHISPER_URL', 'http://faster-whisper:5000')
        self.piper_url = os.getenv('PIPER_URL', 'http://piper-tts:5001')
        self.ollama_url = os.getenv('OLLAMA_URL', 'http://host.docker.internal:11434')
        self.ollama_model = os.getenv('OLLAMA_MODEL', 'llama2')

        # Database configuration
        self.db_host = os.getenv('DB_HOST', 'postgres')
        self.db_port = os.getenv('DB_PORT', '5432')
        self.db_name = os.getenv('DB_NAME', 'mumble_ai')
        self.db_user = os.getenv('DB_USER', 'mumbleai')
        self.db_password = os.getenv('DB_PASSWORD', 'mumbleai123')
        self.db_pool = None

        # Audio buffer for recording
        self.audio_buffer = {}
        self.recording = {}
        self.silence_threshold = 1.5  # seconds of silence before processing
        self.last_audio_time = {}

        self.mumble = None

    def wait_for_services(self):
        """Wait for dependent services to be ready"""
        services = [
            (f"{self.whisper_url}/health", "Whisper"),
            (f"{self.piper_url}/health", "Piper"),
        ]

        for url, name in services:
            while True:
                try:
                    response = requests.get(url, timeout=5)
                    if response.status_code == 200:
                        logger.info(f"{name} service is ready")
                        break
                except Exception as e:
                    logger.info(f"Waiting for {name} service... ({e})")
                    time.sleep(2)

    def init_database(self):
        """Initialize database connection pool"""
        try:
            logger.info("Initializing database connection...")
            self.db_pool = psycopg2.pool.SimpleConnectionPool(
                1, 10,
                host=self.db_host,
                port=self.db_port,
                database=self.db_name,
                user=self.db_user,
                password=self.db_password
            )
            logger.info("Database connection pool initialized")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    def get_db_connection(self):
        """Get a connection from the pool"""
        return self.db_pool.getconn()

    def release_db_connection(self, conn):
        """Release a connection back to the pool"""
        self.db_pool.putconn(conn)

    def save_message(self, user_name, user_session, message_type, role, message):
        """Save a message to the conversation history"""
        conn = None
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO conversation_history
                (user_name, user_session, message_type, role, message)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (user_name, user_session, message_type, role, message)
            )
            conn.commit()
            cursor.close()
            logger.debug(f"Saved {role} {message_type} message from {user_name}")
        except Exception as e:
            logger.error(f"Error saving message to database: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                self.release_db_connection(conn)

    def get_conversation_history(self, user_name=None, limit=10):
        """Retrieve recent conversation history"""
        conn = None
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()

            if user_name:
                cursor.execute(
                    """
                    SELECT role, message, message_type, timestamp
                    FROM conversation_history
                    WHERE user_name = %s
                    ORDER BY timestamp DESC
                    LIMIT %s
                    """,
                    (user_name, limit)
                )
            else:
                cursor.execute(
                    """
                    SELECT role, message, message_type, timestamp
                    FROM conversation_history
                    ORDER BY timestamp DESC
                    LIMIT %s
                    """,
                    (limit,)
                )

            results = cursor.fetchall()
            cursor.close()

            # Reverse to get chronological order
            return list(reversed(results))
        except Exception as e:
            logger.error(f"Error retrieving conversation history: {e}")
            return []
        finally:
            if conn:
                self.release_db_connection(conn)

    def get_config(self, key, default=None):
        """Get a config value from the database"""
        conn = None
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM bot_config WHERE key = %s", (key,))
            result = cursor.fetchone()
            cursor.close()

            if result:
                return result[0]
            return default
        except Exception as e:
            logger.error(f"Error getting config {key}: {e}")
            return default
        finally:
            if conn:
                self.release_db_connection(conn)

    def connect(self):
        """Connect to Mumble server"""
        logger.info(f"Connecting to Mumble server at {self.mumble_host}:{self.mumble_port}")

        self.mumble = Mumble(self.mumble_host, self.mumble_username,
                            port=self.mumble_port, password=self.mumble_password)

        self.mumble.callbacks.set_callback('sound_received', self.on_sound_received)
        self.mumble.callbacks.set_callback('text_received', self.on_text_received)
        self.mumble.set_receive_sound(True)

        self.mumble.start()
        self.mumble.is_ready()

        logger.info("Connected to Mumble server")

    def on_sound_received(self, user, sound):
        """Called when audio is received from a user"""
        if user['session'] == self.mumble.users.myself['session']:
            return  # Ignore our own audio

        user_id = user['session']
        current_time = time.time()

        # Initialize buffer for new user
        if user_id not in self.audio_buffer:
            self.audio_buffer[user_id] = []
            self.recording[user_id] = False
            self.last_audio_time[user_id] = current_time

        # Add audio to buffer
        self.audio_buffer[user_id].append(sound.pcm)
        self.last_audio_time[user_id] = current_time

        if not self.recording[user_id]:
            self.recording[user_id] = True
            logger.info(f"Started recording from {user['name']}")

            # Start a thread to check for silence
            threading.Thread(target=self.check_silence, args=(user_id, user['name'])).start()

    def on_text_received(self, text):
        """Called when a text message is received"""
        try:
            message = text.message.strip()
            sender = text.actor

            # Ignore our own messages
            if sender == self.mumble.users.myself['session']:
                return

            # Get sender name
            sender_name = self.mumble.users[sender]['name'] if sender in self.mumble.users else "Unknown"

            # Ignore empty messages
            if not message:
                return

            logger.info(f"Text message from {sender_name}: {message}")

            # Process in a separate thread to not block
            threading.Thread(target=self.process_text_message, args=(message, sender_name, sender)).start()

        except Exception as e:
            logger.error(f"Error handling text message: {e}", exc_info=True)

    def process_text_message(self, message, sender_name, sender_session=0):
        """Process a text message and send a text response"""
        try:
            # Save user's message to database
            self.save_message(sender_name, sender_session, 'text', 'user', message)

            logger.info(f"Getting Ollama response for text from {sender_name}...")
            response_text = self.get_ollama_response(message, user_name=sender_name)
            logger.info(f"Ollama text response: {response_text}")

            # Save assistant's response to database
            self.save_message(sender_name, sender_session, 'text', 'assistant', response_text)

            # Send text response to channel
            self.mumble.my_channel().send_text_message(response_text)
            logger.info("Text response sent")

        except Exception as e:
            logger.error(f"Error processing text message: {e}", exc_info=True)

    def check_silence(self, user_id, user_name):
        """Check if user has stopped speaking and process audio"""
        while True:
            time.sleep(0.5)

            if user_id not in self.last_audio_time:
                break

            time_since_audio = time.time() - self.last_audio_time[user_id]

            if time_since_audio > self.silence_threshold:
                logger.info(f"Silence detected from {user_name}, processing audio")
                self.process_audio(user_id, user_name)
                break

    def process_audio(self, user_id, user_name):
        """Process recorded audio through the AI pipeline"""
        if user_id not in self.audio_buffer or len(self.audio_buffer[user_id]) == 0:
            return

        try:
            # Get audio buffer
            audio_data = self.audio_buffer[user_id]
            self.audio_buffer[user_id] = []
            self.recording[user_id] = False

            # Convert PCM to WAV
            wav_data = self.pcm_to_wav(audio_data)

            # Transcribe with Whisper
            logger.info("Transcribing audio...")
            transcript = self.transcribe(wav_data)

            if not transcript or len(transcript.strip()) == 0:
                logger.info("No speech detected")
                return

            logger.info(f"Transcribed: {transcript}")

            # Save user's voice message to database
            self.save_message(user_name, user_id, 'voice', 'user', transcript)

            # Get response from Ollama
            logger.info("Getting response from Ollama...")
            response_text = self.get_ollama_response(transcript, user_name=user_name)
            logger.info(f"Ollama response: {response_text}")

            # Save assistant's voice response to database
            self.save_message(user_name, user_id, 'voice', 'assistant', response_text)

            # Synthesize speech
            logger.info("Synthesizing speech...")
            audio = self.synthesize_speech(response_text)

            # Play audio back to Mumble
            logger.info("Playing response...")
            self.play_audio(audio)

        except Exception as e:
            logger.error(f"Error processing audio: {e}", exc_info=True)

    def pcm_to_wav(self, pcm_chunks):
        """Convert PCM audio chunks to WAV format"""
        output = io.BytesIO()

        with wave.open(output, 'wb') as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(48000)  # 48kHz

            for chunk in pcm_chunks:
                wav_file.writeframes(chunk)

        output.seek(0)
        return output

    def transcribe(self, audio_data):
        """Send audio to Whisper for transcription"""
        files = {'audio': ('audio.wav', audio_data, 'audio/wav')}
        response = requests.post(f"{self.whisper_url}/transcribe", files=files, timeout=30)

        if response.status_code == 200:
            return response.json().get('text', '')
        else:
            logger.error(f"Transcription failed: {response.text}")
            return None

    def get_ollama_response(self, text, user_name=None):
        """Get response from Ollama with conversation history context"""
        try:
            # Get current Ollama config from database
            ollama_url = self.get_config('ollama_url', self.ollama_url)
            ollama_model = self.get_config('ollama_model', self.ollama_model)

            # Build prompt with conversation history
            prompt = self.build_prompt_with_context(text, user_name)

            response = requests.post(
                f"{ollama_url}/api/generate",
                json={
                    'model': ollama_model,
                    'prompt': prompt,
                    'stream': False
                },
                timeout=60
            )

            if response.status_code == 200:
                return response.json().get('response', 'I did not understand that.')
            else:
                logger.error(f"Ollama request failed: {response.text}")
                return "Sorry, I encountered an error."

        except Exception as e:
            logger.error(f"Ollama error: {e}")
            return "Sorry, I am having trouble connecting to my language model."

    def build_prompt_with_context(self, current_message, user_name=None):
        """Build a prompt that includes persona and conversation history for context"""
        try:
            # Get bot persona from config
            persona = self.get_config('bot_persona', '')

            # Get recent conversation history
            history = self.get_conversation_history(user_name=user_name, limit=10)

            # Build the full prompt
            full_prompt = ""

            # Add persona if configured
            if persona and persona.strip():
                full_prompt = f"{persona.strip()}\n\n"

            # Add conversation history if available
            if history:
                full_prompt += "Previous conversation:\n"
                for role, message, msg_type, timestamp in history:
                    if role == 'user':
                        full_prompt += f"User: {message}\n"
                    else:
                        full_prompt += f"Assistant: {message}\n"
                full_prompt += "\n"

            # Add current message
            full_prompt += f"User: {current_message}\nAssistant:"

            return full_prompt

        except Exception as e:
            logger.error(f"Error building prompt with context: {e}")
            # Fallback to just the current message if there's an error
            return current_message

    def synthesize_speech(self, text):
        """Send text to Piper for TTS"""
        response = requests.post(
            f"{self.piper_url}/synthesize",
            json={'text': text},
            timeout=30
        )

        if response.status_code == 200:
            return io.BytesIO(response.content)
        else:
            logger.error(f"TTS failed: {response.text}")
            return None

    def play_audio(self, audio_data):
        """Play audio to Mumble channel"""
        if not audio_data:
            return

        try:
            # Save input audio to temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as input_tmp:
                input_tmp.write(audio_data.read())
                input_path = input_tmp.name

            # Resample to 48kHz mono 16-bit PCM for Mumble
            with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as output_tmp:
                output_path = output_tmp.name

            try:
                # Use ffmpeg to resample audio to Mumble's expected format
                subprocess.run([
                    'ffmpeg', '-i', input_path,
                    '-ar', '48000',  # Sample rate 48kHz
                    '-ac', '1',      # Mono
                    '-sample_fmt', 's16',  # 16-bit PCM
                    '-y',            # Overwrite output
                    output_path
                ], check=True, capture_output=True)

                # Read resampled audio and send to Mumble
                with wave.open(output_path, 'rb') as wav_file:
                    frames = wav_file.readframes(wav_file.getnframes())
                    self.mumble.sound_output.add_sound(frames)

            finally:
                # Clean up temp files
                try:
                    os.unlink(input_path)
                    os.unlink(output_path)
                except:
                    pass

        except Exception as e:
            logger.error(f"Error playing audio: {e}")

    def run(self):
        """Main run loop"""
        logger.info("Starting Mumble AI Bot")

        # Initialize database
        self.init_database()

        # Wait for services
        self.wait_for_services()

        # Connect to Mumble
        self.connect()

        logger.info("Bot is ready and listening...")

        # Keep running
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            if self.mumble:
                self.mumble.stop()


if __name__ == '__main__':
    bot = MumbleAIBot()
    bot.run()
