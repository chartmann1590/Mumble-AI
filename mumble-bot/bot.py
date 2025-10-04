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
import random
import functools
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from psycopg2 import pool
from pymumble_py3 import Mumble
from pymumble_py3.constants import PYMUMBLE_AUDIO_PER_PACKET
from typing import Optional, Callable, Any, Tuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class RetryError(Exception):
    """Custom exception for retry failures"""
    pass


class CircuitBreakerError(Exception):
    """Custom exception for circuit breaker failures"""
    pass


class RetryConfig:
    """Configuration for retry mechanisms"""
    def __init__(self, max_attempts: int = 3, base_delay: float = 1.0, 
                 max_delay: float = 60.0, exponential_base: float = 2.0, 
                 jitter: bool = True):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter


class CircuitBreaker:
    """Circuit breaker pattern implementation"""
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = 'CLOSED'  # CLOSED, OPEN, HALF_OPEN
        self._lock = threading.Lock()

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection"""
        with self._lock:
            if self.state == 'OPEN':
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    self.state = 'HALF_OPEN'
                    logger.info("Circuit breaker transitioning to HALF_OPEN")
                else:
                    raise CircuitBreakerError("Circuit breaker is OPEN")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        """Handle successful call"""
        with self._lock:
            self.failure_count = 0
            if self.state == 'HALF_OPEN':
                self.state = 'CLOSED'
                logger.info("Circuit breaker transitioning to CLOSED")

    def _on_failure(self):
        """Handle failed call"""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                self.state = 'OPEN'
                logger.warning(f"Circuit breaker opened after {self.failure_count} failures")


def retry_with_exponential_backoff(config: RetryConfig = None):
    """Decorator for retry with exponential backoff"""
    if config is None:
        config = RetryConfig()

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            
            for attempt in range(config.max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if attempt == config.max_attempts - 1:
                        logger.error(f"Function {func.__name__} failed after {config.max_attempts} attempts: {e}")
                        raise RetryError(f"Function {func.__name__} failed after {config.max_attempts} attempts") from e
                    
                    # Calculate delay with exponential backoff
                    delay = min(
                        config.base_delay * (config.exponential_base ** attempt),
                        config.max_delay
                    )
                    
                    # Add jitter to prevent thundering herd
                    if config.jitter:
                        delay *= (0.5 + random.random() * 0.5)
                    
                    logger.warning(f"Function {func.__name__} failed (attempt {attempt + 1}/{config.max_attempts}): {e}. Retrying in {delay:.2f}s...")
                    time.sleep(delay)
            
            raise RetryError(f"Function {func.__name__} failed after {config.max_attempts} attempts") from last_exception
        
        return wrapper
    return decorator


def safe_execute(func: Callable, *args, default_return: Any = None, 
                log_errors: bool = True, **kwargs) -> Any:
    """Safely execute a function with error handling"""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        if log_errors:
            logger.error(f"Error in {func.__name__}: {e}", exc_info=True)
        return default_return


class HealthCheckHandler(BaseHTTPRequestHandler):
    """HTTP handler for health check endpoint"""
    
    def __init__(self, bot_instance, *args, **kwargs):
        self.bot = bot_instance
        super().__init__(*args, **kwargs)
    
    def do_GET(self):
        if self.path == '/health':
            try:
                health_status = self.bot.check_health()
                status_code = 200 if self.bot.is_healthy else 503
                
                response = {
                    'status': 'healthy' if self.bot.is_healthy else 'unhealthy',
                    'services': health_status,
                    'timestamp': time.time()
                }
                
                self.send_response(status_code)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                error_response = {'status': 'error', 'message': str(e)}
                self.wfile.write(json.dumps(error_response).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        # Suppress default logging
        pass


def create_health_handler(bot_instance):
    """Factory function to create health check handler with bot instance"""
    def handler(*args, **kwargs):
        return HealthCheckHandler(bot_instance, *args, **kwargs)
    return handler


class MumbleAIBot:
    def __init__(self):
        # Configuration
        self.mumble_host = os.getenv('MUMBLE_HOST', 'mumble-server')
        self.mumble_port = int(os.getenv('MUMBLE_PORT', '64738'))
        self.mumble_username = os.getenv('MUMBLE_USERNAME', 'AI-Bot')
        self.mumble_password = os.getenv('MUMBLE_PASSWORD', '')

        self.whisper_url = os.getenv('WHISPER_URL', 'http://faster-whisper:5000')
        self.piper_url = os.getenv('PIPER_URL', 'http://piper-tts:5001')
        self.silero_url = os.getenv('SILERO_URL', 'http://silero-tts:5004')
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
        
        # Error handling and retry configuration
        self.retry_config = RetryConfig(
            max_attempts=int(os.getenv('RETRY_MAX_ATTEMPTS', '3')),
            base_delay=float(os.getenv('RETRY_BASE_DELAY', '1.0')),
            max_delay=float(os.getenv('RETRY_MAX_DELAY', '60.0'))
        )
        
        # Circuit breakers for external services
        self.whisper_circuit_breaker = CircuitBreaker(
            failure_threshold=int(os.getenv('WHISPER_CIRCUIT_THRESHOLD', '5')),
            recovery_timeout=float(os.getenv('WHISPER_CIRCUIT_TIMEOUT', '60.0'))
        )
        self.piper_circuit_breaker = CircuitBreaker(
            failure_threshold=int(os.getenv('PIPER_CIRCUIT_THRESHOLD', '5')),
            recovery_timeout=float(os.getenv('PIPER_CIRCUIT_TIMEOUT', '60.0'))
        )
        self.ollama_circuit_breaker = CircuitBreaker(
            failure_threshold=int(os.getenv('OLLAMA_CIRCUIT_THRESHOLD', '5')),
            recovery_timeout=float(os.getenv('OLLAMA_CIRCUIT_TIMEOUT', '60.0'))
        )
        self.db_circuit_breaker = CircuitBreaker(
            failure_threshold=int(os.getenv('DB_CIRCUIT_THRESHOLD', '3')),
            recovery_timeout=float(os.getenv('DB_CIRCUIT_TIMEOUT', '30.0'))
        )
        
        # Health check tracking
        self.last_health_check = {}
        self.health_check_interval = float(os.getenv('HEALTH_CHECK_INTERVAL', '60.0'))  # Increased to 60 seconds
        self.is_healthy = True
        
        # Health server configuration
        self.health_port = int(os.getenv('HEALTH_PORT', '8080'))
        self.health_server = None

    @retry_with_exponential_backoff(RetryConfig(max_attempts=30, base_delay=2.0, max_delay=30.0))
    def wait_for_services(self):
        """Wait for dependent services to be ready with retry logic"""
        services = [
            (f"{self.whisper_url}/health", "Whisper"),
            (f"{self.piper_url}/health", "Piper"),
        ]

        for url, name in services:
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    logger.info(f"{name} service is ready")
                    self.last_health_check[name] = time.time()
                else:
                    raise requests.RequestException(f"Service {name} returned status {response.status_code}")
            except Exception as e:
                logger.warning(f"Service {name} not ready: {e}")
                raise

    @retry_with_exponential_backoff(RetryConfig(max_attempts=10, base_delay=2.0, max_delay=30.0))
    def init_database(self):
        """Initialize database connection pool with retry logic"""
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
            self.last_health_check['database'] = time.time()
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    def get_db_connection(self):
        """Get a connection from the pool with circuit breaker protection"""
        try:
            return self.db_circuit_breaker.call(self._get_db_connection_internal)
        except CircuitBreakerError:
            logger.error("Database circuit breaker is open, cannot get connection")
            return None

    def _get_db_connection_internal(self):
        """Internal method to get database connection"""
        if not self.db_pool:
            raise Exception("Database pool not initialized")
        return self.db_pool.getconn()

    def release_db_connection(self, conn):
        """Release a connection back to the pool"""
        if conn and self.db_pool:
            try:
                self.db_pool.putconn(conn)
            except Exception as e:
                logger.error(f"Error releasing database connection: {e}")

    def save_message(self, user_name, user_session, message_type, role, message):
        """Save a message to the conversation history asynchronously (non-blocking)"""
        # Run DB write in background thread to avoid blocking the main pipeline
        threading.Thread(
            target=self._save_message_sync,
            args=(user_name, user_session, message_type, role, message),
            daemon=True
        ).start()
        return True

    def _save_message_sync(self, user_name, user_session, message_type, role, message):
        """Internal synchronous save method run in background thread"""
        conn = None
        try:
            conn = self.get_db_connection()
            if not conn:
                logger.warning("Cannot save message: database connection unavailable")
                return False

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
            return True
        except Exception as e:
            logger.error(f"Error saving message to database: {e}")
            if conn:
                try:
                    conn.rollback()
                except Exception as rollback_error:
                    logger.error(f"Error during rollback: {rollback_error}")
            return False
        finally:
            if conn:
                self.release_db_connection(conn)

    def get_conversation_history(self, user_name=None, limit=10):
        """Retrieve recent conversation history with error handling"""
        conn = None
        try:
            conn = self.get_db_connection()
            if not conn:
                logger.warning("Cannot retrieve conversation history: database connection unavailable")
                return []

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
        """Get a config value from the database with error handling"""
        conn = None
        try:
            conn = self.get_db_connection()
            if not conn:
                logger.warning(f"Cannot get config {key}: database connection unavailable")
                return default
                
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

    @retry_with_exponential_backoff(RetryConfig(max_attempts=10, base_delay=3.0, max_delay=60.0))
    def connect(self):
        """Connect to Mumble server with retry logic"""
        logger.info(f"Connecting to Mumble server at {self.mumble_host}:{self.mumble_port}")

        try:
            self.mumble = Mumble(self.mumble_host, self.mumble_username,
                                port=self.mumble_port, password=self.mumble_password)

            self.mumble.callbacks.set_callback('sound_received', self.on_sound_received)
            self.mumble.callbacks.set_callback('text_received', self.on_text_received)
            self.mumble.set_receive_sound(True)

            self.mumble.start()
            self.mumble.is_ready()

            logger.info("Connected to Mumble server")
            self.last_health_check['mumble'] = time.time()
        except Exception as e:
            logger.error(f"Failed to connect to Mumble server: {e}")
            raise

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
        """Process a text message and send a text-only response"""
        try:
            # Get Ollama response FIRST (before saving to avoid duplication in history)
            logger.info(f"Getting Ollama response for text from {sender_name}...")
            response_text = self.get_ollama_response(message, user_name=sender_name)
            logger.info(f"Ollama text response: {response_text}")

            # Now save both messages to database (after getting response)
            self.save_message(sender_name, sender_session, 'text', 'user', message)
            self.save_message(sender_name, sender_session, 'text', 'assistant', response_text)

            # Send text-only response (no TTS for text messages)
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
        """Send audio to Whisper for transcription with circuit breaker protection"""
        try:
            return self.whisper_circuit_breaker.call(self._transcribe_internal, audio_data)
        except CircuitBreakerError:
            logger.error("Whisper circuit breaker is open, cannot transcribe audio")
            return None

    def _transcribe_internal(self, audio_data):
        """Internal transcription method"""
        # Get language setting from database
        language = self.get_config('whisper_language', 'auto')

        files = {'audio': ('audio.wav', audio_data, 'audio/wav')}
        data = {'language': language}
        response = requests.post(f"{self.whisper_url}/transcribe", files=files, data=data, timeout=30)

        if response.status_code == 200:
            return response.json().get('text', '')
        else:
            raise requests.RequestException(f"Transcription failed: {response.text}")

    def get_ollama_response(self, text, user_name=None):
        """Get response from Ollama with conversation history context and circuit breaker protection"""
        try:
            return self.ollama_circuit_breaker.call(self._get_ollama_response_internal, text, user_name)
        except CircuitBreakerError:
            logger.error("Ollama circuit breaker is open, cannot get response")
            return "Sorry, I am temporarily unavailable due to service issues."

    def _get_ollama_response_internal(self, text, user_name=None):
        """Internal Ollama response method"""
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
            raise requests.RequestException(f"Ollama request failed: {response.text}")

    def build_prompt_with_context(self, current_message, user_name=None):
        """Build a prompt that includes persona and conversation history for context"""
        try:
            # Get bot persona from config
            persona = self.get_config('bot_persona', '')

            # Get recent conversation history
            history = self.get_conversation_history(user_name=user_name, limit=10)

            # Build the full prompt
            full_prompt = ""

            # Add conciseness instruction and no emoji rule
            full_prompt = "Keep your responses brief and conversational (1-3 sentences). Never use emojis in your responses. "

            # Add persona if configured
            if persona and persona.strip():
                full_prompt += f"{persona.strip()}\n\n"
            else:
                full_prompt += "\n\n"

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
        """Send text to Piper for TTS with circuit breaker protection"""
        try:
            return self.piper_circuit_breaker.call(self._synthesize_speech_internal, text)
        except CircuitBreakerError:
            logger.error("Piper circuit breaker is open, cannot synthesize speech")
            return None

    def _synthesize_speech_internal(self, text):
        """Internal TTS synthesis method - routes to Piper or Silero based on config"""
        # Get TTS engine from database
        tts_engine = self.get_config('tts_engine', 'piper')

        if tts_engine == 'silero':
            # Use Silero TTS
            response = requests.post(
                f"{self.silero_url}/synthesize",
                json={'text': text},
                timeout=30
            )
        else:
            # Use Piper TTS (default)
            response = requests.post(
                f"{self.piper_url}/synthesize",
                json={'text': text},
                timeout=30
            )

        if response.status_code == 200:
            return io.BytesIO(response.content)
        else:
            raise requests.RequestException(f"TTS failed: {response.text}")

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

    def check_health(self):
        """Check health of all services"""
        current_time = time.time()
        health_status = {}
        
        # Check Whisper service
        try:
            response = requests.get(f"{self.whisper_url}/health", timeout=5)
            health_status['whisper'] = response.status_code == 200
            if health_status['whisper']:
                self.last_health_check['whisper'] = current_time
        except Exception as e:
            health_status['whisper'] = False
            logger.warning(f"Whisper health check failed: {e}")

        # Check Piper service
        try:
            response = requests.get(f"{self.piper_url}/health", timeout=5)
            health_status['piper'] = response.status_code == 200
            if health_status['piper']:
                self.last_health_check['piper'] = current_time
        except Exception as e:
            health_status['piper'] = False
            logger.warning(f"Piper health check failed: {e}")

        # Check database
        try:
            conn = self.get_db_connection()
            if conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
                self.release_db_connection(conn)
                health_status['database'] = True
                self.last_health_check['database'] = current_time
            else:
                health_status['database'] = False
        except Exception as e:
            health_status['database'] = False
            logger.warning(f"Database health check failed: {e}")

        # Check Mumble connection
        try:
            if self.mumble:
                # Check if we can access the users object, which indicates connection
                try:
                    # Try to access a simple property to test connection
                    _ = self.mumble.users
                    health_status['mumble'] = True
                    self.last_health_check['mumble'] = current_time
                except Exception:
                    health_status['mumble'] = False
            else:
                health_status['mumble'] = False
        except Exception as e:
            health_status['mumble'] = False
            logger.warning(f"Mumble health check failed: {e}")

        # Overall health status
        self.is_healthy = all(health_status.values())
        
        if not self.is_healthy:
            logger.warning(f"Health check failed: {health_status}")
        else:
            logger.debug(f"All services healthy: {health_status}")
            
        return health_status

    def auto_recovery(self):
        """Attempt to recover from service failures"""
        # Prevent multiple simultaneous recovery attempts
        if hasattr(self, '_reconnecting') and self._reconnecting:
            logger.info("Auto-recovery already in progress, skipping...")
            return
            
        self._reconnecting = True
        logger.info("Attempting auto-recovery...")
        
        try:
            # Only try to reconnect to Mumble if it's actually disconnected
            if not self.mumble:
                try:
                    logger.info("Attempting to reconnect to Mumble...")
                    self.connect()
                    logger.info("Mumble reconnection successful")
                except Exception as e:
                    logger.error(f"Mumble reconnection failed: {e}")
            else:
                logger.info("Mumble connection appears to be active, skipping reconnection")

            # Reset circuit breakers if services are healthy
            health_status = self.check_health()
            if health_status.get('whisper', False):
                if self.whisper_circuit_breaker.state == 'OPEN':
                    logger.info("Resetting Whisper circuit breaker")
                    self.whisper_circuit_breaker.state = 'HALF_OPEN'
                    self.whisper_circuit_breaker.failure_count = 0

            if health_status.get('piper', False):
                if self.piper_circuit_breaker.state == 'OPEN':
                    logger.info("Resetting Piper circuit breaker")
                    self.piper_circuit_breaker.state = 'HALF_OPEN'
                    self.piper_circuit_breaker.failure_count = 0

            if health_status.get('database', False):
                if self.db_circuit_breaker.state == 'OPEN':
                    logger.info("Resetting database circuit breaker")
                    self.db_circuit_breaker.state = 'HALF_OPEN'
                    self.db_circuit_breaker.failure_count = 0
                    
        finally:
            self._reconnecting = False

    def run(self):
        """Main run loop with health monitoring and auto-recovery"""
        logger.info("Starting Mumble AI Bot")

        # Initialize database
        self.init_database()

        # Wait for services
        self.wait_for_services()

        # Connect to Mumble
        self.connect()

        logger.info("Bot is ready and listening...")

        # Start health monitoring thread
        health_thread = threading.Thread(target=self._health_monitor, daemon=True)
        health_thread.start()

        # Keep running
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            if self.mumble:
                self.mumble.stop()

    def _health_monitor(self):
        """Background health monitoring thread"""
        while True:
            try:
                time.sleep(self.health_check_interval)
                
                # Check if we need to perform health check
                current_time = time.time()
                last_check = min(self.last_health_check.values()) if self.last_health_check else 0
                
                if current_time - last_check > self.health_check_interval:
                    health_status = self.check_health()
                    
                    # Only attempt auto-recovery if we've been unhealthy for a while
                    # and not currently in the middle of a reconnection
                    if not self.is_healthy and not hasattr(self, '_reconnecting'):
                        # Add a delay before auto-recovery to prevent rapid reconnection loops
                        time.sleep(5)
                        if not self.is_healthy:
                            self.auto_recovery()
                        
            except Exception as e:
                logger.error(f"Error in health monitor: {e}")
                time.sleep(10)  # Wait before retrying

    def start_health_server(self):
        """Start the health check HTTP server"""
        try:
            handler = create_health_handler(self)
            self.health_server = HTTPServer(('0.0.0.0', self.health_port), handler)
            health_thread = threading.Thread(target=self.health_server.serve_forever, daemon=True)
            health_thread.start()
            logger.info(f"Health check server started on port {self.health_port}")
        except Exception as e:
            logger.error(f"Failed to start health server: {e}")

    def stop_health_server(self):
        """Stop the health check HTTP server"""
        if self.health_server:
            try:
                self.health_server.shutdown()
                self.health_server.server_close()
                logger.info("Health check server stopped")
            except Exception as e:
                logger.error(f"Error stopping health server: {e}")

    def run(self):
        """Main run loop with health monitoring and auto-recovery"""
        logger.info("Starting Mumble AI Bot")

        # Initialize database
        self.init_database()

        # Wait for services
        self.wait_for_services()

        # Connect to Mumble
        self.connect()

        # Start health server
        self.start_health_server()

        logger.info("Bot is ready and listening...")

        # Start health monitoring thread
        health_thread = threading.Thread(target=self._health_monitor, daemon=True)
        health_thread.start()

        # Keep running
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            self.stop_health_server()
            if self.mumble:
                self.mumble.stop()


if __name__ == '__main__':
    bot = MumbleAIBot()
    bot.run()
