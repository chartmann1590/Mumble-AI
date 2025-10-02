#!/usr/bin/env python3
"""
SIP-Mumble Bridge - Full SIP/RTP Implementation
This bridge receives SIP calls and routes audio to/from Mumble server
"""

import sys
import time
import threading
import logging
import socket
import struct
import queue
import random
import re
import audioop
import io
import os
import wave
import requests
import psycopg2
from psycopg2 import pool
from collections import deque

from pymumble_py3 import Mumble
from pymumble_py3.constants import PYMUMBLE_AUDIO_PER_PACKET
import numpy as np

import config

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SIPCall:
    """Represents a single SIP call with RTP audio"""

    def __init__(self, invite_msg, caller_addr, sip_socket):
        self.invite_msg = invite_msg
        self.caller_addr = caller_addr
        self.sip_socket = sip_socket
        self.rtp_socket = None
        self.rtp_port = None
        self.remote_rtp_ip = None
        self.remote_rtp_port = None
        self.running = False
        self.call_id = None
        self.from_tag = None
        self.to_tag = None

    def parse_sdp(self):
        """Parse SDP from INVITE message"""
        try:
            # Extract remote RTP info from SDP
            lines = self.invite_msg.split('\r\n')

            # Find connection address (c=)
            for line in lines:
                if line.startswith('c='):
                    # c=IN IP4 10.0.0.66
                    parts = line.split()
                    if len(parts) >= 3:
                        self.remote_rtp_ip = parts[2]

            # Find media port (m=)
            for line in lines:
                if line.startswith('m=audio'):
                    # m=audio 16970 RTP/AVP 0 8 101
                    parts = line.split()
                    if len(parts) >= 2:
                        self.remote_rtp_port = int(parts[1])

            logger.info(f"Parsed SDP: Remote RTP at {self.remote_rtp_ip}:{self.remote_rtp_port}")
            return self.remote_rtp_ip and self.remote_rtp_port

        except Exception as e:
            logger.error(f"Error parsing SDP: {e}")
            return False

    def create_rtp_socket(self):
        """Create RTP socket for audio within configured port range"""
        try:
            self.rtp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.rtp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # Try to bind to a port in the configured range
            for port in range(config.RTP_PORT_MIN, config.RTP_PORT_MAX + 1):
                try:
                    self.rtp_socket.bind(('0.0.0.0', port))
                    self.rtp_port = port
                    logger.info(f"Created RTP socket on port {self.rtp_port}")
                    return True
                except OSError:
                    continue

            # If all ports in range are busy, use any available port
            self.rtp_socket.bind(('0.0.0.0', 0))
            self.rtp_port = self.rtp_socket.getsockname()[1]
            logger.warning(f"RTP port range exhausted, using port {self.rtp_port}")
            return True

        except Exception as e:
            logger.error(f"Error creating RTP socket: {e}")
            return False

    def send_rtp(self, audio_data, payload_type=0):
        """Send RTP packet"""
        try:
            if not self.rtp_socket or not self.remote_rtp_ip:
                return

            # Build RTP header
            version = 2
            padding = 0
            extension = 0
            cc = 0
            marker = 0
            sequence = random.randint(0, 65535)
            timestamp = int(time.time() * 8000) & 0xFFFFFFFF
            ssrc = random.randint(0, 0xFFFFFFFF)

            # Pack RTP header (12 bytes)
            header = struct.pack('!BBHII',
                (version << 6) | (padding << 5) | (extension << 4) | cc,
                (marker << 7) | payload_type,
                sequence,
                timestamp,
                ssrc
            )

            packet = header + audio_data
            self.rtp_socket.sendto(packet, (self.remote_rtp_ip, self.remote_rtp_port))

        except Exception as e:
            logger.error(f"Error sending RTP: {e}")

    def close(self):
        """Close RTP socket"""
        self.running = False
        if self.rtp_socket:
            self.rtp_socket.close()


class SimpleSIPServer:
    """
    SIP server with proper SDP/RTP support
    """

    def __init__(self, host='0.0.0.0', port=5060):
        self.host = host
        self.port = port
        self.socket = None
        self.running = False
        self.call_handler = None
        self.active_calls = {}

    def start(self):
        """Start the SIP server"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind((self.host, self.port))
            self.running = True

            logger.info(f"SIP Server listening on {self.host}:{self.port}")

            # Start listening thread
            self.listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
            self.listen_thread.start()

            return True

        except Exception as e:
            logger.error(f"Failed to start SIP server: {e}")
            return False

    def _listen_loop(self):
        """Listen for incoming SIP messages"""
        while self.running:
            try:
                data, addr = self.socket.recvfrom(8192)
                message = data.decode('utf-8', errors='ignore')

                logger.debug(f"Received SIP message from {addr}:\n{message[:300]}")

                # Handle SIP message
                self._handle_sip_message(message, addr)

            except Exception as e:
                if self.running:
                    logger.error(f"Error in listen loop: {e}")

    def _handle_sip_message(self, message, addr):
        """Handle incoming SIP message"""
        lines = message.split('\r\n')
        if not lines:
            return

        request_line = lines[0]

        if request_line.startswith('INVITE'):
            logger.info(f"Incoming INVITE from {addr}")
            self._handle_invite(message, addr)

        elif request_line.startswith('ACK'):
            logger.info(f"ACK received from {addr}")
            # Call is now established, trigger handler
            call_id = self._extract_header(message, 'Call-ID')
            if call_id and call_id in self.active_calls:
                call = self.active_calls[call_id]
                # Only start handler once per call (check if call is not already running)
                if not hasattr(call, 'session_started'):
                    call.session_started = True
                    if self.call_handler:
                        threading.Thread(target=self.call_handler, args=(call,), daemon=True).start()
                else:
                    logger.debug(f"ACK for already-started call {call_id}, ignoring")

        elif request_line.startswith('BYE'):
            logger.info(f"Call ended by {addr}")
            self._send_response(200, 'OK', addr, message)

            # Clean up call
            call_id = self._extract_header(message, 'Call-ID')
            if call_id and call_id in self.active_calls:
                self.active_calls[call_id].close()
                del self.active_calls[call_id]

        elif request_line.startswith('OPTIONS'):
            self._send_response(200, 'OK', addr, message)

        elif request_line.startswith('CANCEL'):
            logger.info(f"Call cancelled by {addr}")
            self._send_response(200, 'OK', addr, message)

    def _handle_invite(self, message, addr):
        """Handle INVITE - send 180 Ringing then 200 OK with SDP"""
        try:
            # Check if this is a retransmitted INVITE for an existing call
            call_id = self._extract_header(message, 'Call-ID')
            if call_id and call_id in self.active_calls:
                logger.debug(f"Retransmitted INVITE for existing call {call_id}, re-sending 200 OK")
                call = self.active_calls[call_id]
                # Re-send responses
                self._send_response(100, 'Trying', addr, message)
                time.sleep(0.1)
                self._send_response(180, 'Ringing', addr, message, to_tag=call.to_tag)
                time.sleep(0.2)
                self._send_invite_ok(addr, message, call)
                return

            # Create call object
            call = SIPCall(message, addr, self.socket)

            # Parse SDP to get remote RTP info
            if not call.parse_sdp():
                logger.error("Failed to parse SDP from INVITE")
                self._send_response(400, 'Bad Request', addr, message)
                return

            # Create RTP socket
            if not call.create_rtp_socket():
                logger.error("Failed to create RTP socket")
                self._send_response(500, 'Internal Server Error', addr, message)
                return

            # Extract call info
            call.call_id = call_id
            from_header = self._extract_header(message, 'From')

            # Extract from-tag
            if from_header and 'tag=' in from_header:
                call.from_tag = from_header.split('tag=')[1].split(';')[0].split('>')[0]

            # Generate to-tag
            call.to_tag = f"tag-{random.randint(100000, 999999)}"

            # Store call
            if call.call_id:
                self.active_calls[call.call_id] = call

            # Send 100 Trying
            self._send_response(100, 'Trying', addr, message)

            # Send 180 Ringing
            time.sleep(0.1)
            self._send_response(180, 'Ringing', addr, message, to_tag=call.to_tag)

            # Send 200 OK with SDP
            time.sleep(0.2)
            self._send_invite_ok(addr, message, call)

        except Exception as e:
            logger.error(f"Error handling INVITE: {e}", exc_info=True)
            self._send_response(500, 'Internal Server Error', addr, message)

    def _send_invite_ok(self, addr, request, call):
        """Send 200 OK response with SDP"""
        try:
            # Use the IP that VitalPBX sent the INVITE to (from the request line)
            # This ensures we advertise the externally accessible IP
            request_lines = request.split('\r\n')
            request_line = request_lines[0]

            # Extract IP from "INVITE sip:10.0.0.56:5060 SIP/2.0"
            local_ip = '10.0.0.56'  # Default fallback
            if 'sip:' in request_line:
                try:
                    uri_part = request_line.split('sip:')[1].split()[0]
                    if ':' in uri_part:
                        local_ip = uri_part.split(':')[0]
                    else:
                        local_ip = uri_part
                except:
                    pass

            # Build SDP
            sdp = f"""v=0
o=MumbleBridge 0 0 IN IP4 {local_ip}
s=Call
c=IN IP4 {local_ip}
t=0 0
m=audio {call.rtp_port} RTP/AVP 0 8 101
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
a=rtpmap:101 telephone-event/8000
a=ptime:20
a=sendrecv
"""

            # Extract headers from request
            call_id = self._extract_header(request, 'Call-ID')
            from_header = self._extract_header(request, 'From')
            to_header = self._extract_header(request, 'To')
            cseq = self._extract_header(request, 'CSeq')
            via = self._extract_header(request, 'Via')

            # Add to-tag if not present
            if to_header and 'tag=' not in to_header:
                to_header = f"{to_header};{call.to_tag}"

            # Build response
            response = f"SIP/2.0 200 OK\r\n"
            if via:
                response += f"Via: {via}\r\n"
            if from_header:
                response += f"From: {from_header}\r\n"
            if to_header:
                response += f"To: {to_header}\r\n"
            else:
                response += f"To: <sip:5000@{local_ip}>;{call.to_tag}\r\n"
            if call_id:
                response += f"Call-ID: {call_id}\r\n"
            if cseq:
                response += f"CSeq: {cseq}\r\n"

            response += f"Contact: <sip:mumble-bridge@{local_ip}:{self.port}>\r\n"
            response += f"Content-Type: application/sdp\r\n"
            response += f"Content-Length: {len(sdp)}\r\n"
            response += "\r\n"
            response += sdp

            self.socket.sendto(response.encode('utf-8'), addr)
            logger.info(f"Sent 200 OK with SDP to {addr}")
            logger.debug(f"SDP:\n{sdp}")

        except Exception as e:
            logger.error(f"Error sending 200 OK: {e}", exc_info=True)

    def _send_response(self, code, reason, addr, request, to_tag=None):
        """Send SIP response"""
        try:
            # Extract Call-ID, From, To, CSeq from request
            call_id = self._extract_header(request, 'Call-ID')
            from_header = self._extract_header(request, 'From')
            to_header = self._extract_header(request, 'To')
            cseq = self._extract_header(request, 'CSeq')
            via = self._extract_header(request, 'Via')

            # Add to-tag if provided and not already present
            if to_tag and to_header and 'tag=' not in to_header:
                to_header = f"{to_header};{to_tag}"

            response = f"SIP/2.0 {code} {reason}\r\n"
            if via:
                response += f"Via: {via}\r\n"
            if from_header:
                response += f"From: {from_header}\r\n"
            if to_header:
                response += f"To: {to_header}\r\n"
            if call_id:
                response += f"Call-ID: {call_id}\r\n"
            if cseq:
                response += f"CSeq: {cseq}\r\n"
            response += f"Content-Length: 0\r\n"
            response += "\r\n"

            self.socket.sendto(response.encode('utf-8'), addr)
            logger.debug(f"Sent {code} {reason} to {addr}")

        except Exception as e:
            logger.error(f"Error sending response: {e}")

    def _extract_header(self, message, header_name):
        """Extract header value from SIP message"""
        for line in message.split('\r\n'):
            if line.startswith(f"{header_name}:"):
                return line.split(':', 1)[1].strip()
        return None

    def set_call_handler(self, handler):
        """Set callback for incoming calls"""
        self.call_handler = handler

    def stop(self):
        """Stop the SIP server"""
        self.running = False

        # Close all active calls
        for call in list(self.active_calls.values()):
            call.close()
        self.active_calls.clear()

        if self.socket:
            self.socket.close()
        logger.info("SIP server stopped")


class AudioBridge:
    """Legacy Mumble bridge (unused in SIP AI flow). Kept for compatibility."""

    def __init__(self):
        self.mumble_to_phone = queue.Queue(maxsize=100)
        self.phone_to_mumble = queue.Queue(maxsize=100)
        self.running = False

    def start(self):
        self.running = True
        logger.info("Audio bridge started")

    def stop(self):
        self.running = False
        while not self.mumble_to_phone.empty():
            try:
                self.mumble_to_phone.get_nowait()
            except:
                pass
        while not self.phone_to_mumble.empty():
            try:
                self.phone_to_mumble.get_nowait()
            except:
                pass
        logger.info("Audio bridge stopped")


class MumbleClient:
    """Legacy Mumble client (unused). Kept for compatibility."""

    def __init__(self, audio_bridge):
        self.audio_bridge = audio_bridge
        self.mumble = None
        self.connected = False

    def connect(self):
        logger.debug("Mumble client disabled in SIP AI flow")
        return False

    def disconnect(self):
        pass


class AIPipeline:
    """AI pipeline: STT -> LLM -> TTS + DB logging using shared config."""

    def __init__(self):
        # Service endpoints
        self.whisper_url = config.WHISPER_URL
        self.piper_url = config.PIPER_URL

        # DB config
        self.db_host = config.DB_HOST
        self.db_port = config.DB_PORT
        self.db_name = config.DB_NAME
        self.db_user = config.DB_USER
        self.db_password = config.DB_PASSWORD
        self.db_pool = None
        self._init_db_pool()
        self._wait_for_services()

    def _wait_for_services(self):
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

    def _init_db_pool(self):
        """Initialize database connection pool"""
        try:
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
            logger.error(f"Failed to initialize database pool: {e}")
            self.db_pool = None

    def get_db_connection(self):
        """Get a connection from the pool"""
        if self.db_pool:
            return self.db_pool.getconn()
        else:
            # Fallback to direct connection
            return psycopg2.connect(
                host=self.db_host,
                port=self.db_port,
                database=self.db_name,
                user=self.db_user,
                password=self.db_password,
            )

    def release_db_connection(self, conn):
        """Release a connection back to the pool"""
        if self.db_pool and conn:
            self.db_pool.putconn(conn)
        elif conn:
            conn.close()

    def db_conn(self):
        """Legacy method for compatibility"""
        return self.get_db_connection()

    def get_config(self, key, default=None):
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

    def save_message(self, user_name, user_session, message_type, role, message):
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

    def transcribe_wav_file(self, wav_path):
        try:
            with open(wav_path, 'rb') as f:
                resp = requests.post(f"{self.whisper_url}/transcribe", files={'audio': f}, timeout=60)
            if resp.status_code == 200:
                return resp.json().get('text', '').strip()
            logger.error(f"Whisper error: {resp.text}")
            return ''
        except Exception as e:
            logger.error(f"Transcription request failed: {e}")
            return ''

    def ollama_generate(self, message, user_name=None):
        try:
            # Get Ollama configuration from database (same as mumble-bot)
            ollama_url = self.get_config('ollama_url', config.DEFAULT_OLLAMA_URL)
            ollama_model = self.get_config('ollama_model', config.DEFAULT_OLLAMA_MODEL)
            logger.info(f"Using Ollama: {ollama_url} with model: {ollama_model}")
            
            prompt = self.build_prompt_with_context(message, user_name)
            resp = requests.post(
                f"{ollama_url}/api/generate",
                json={"model": ollama_model, "prompt": prompt, "stream": False},
                timeout=120,
            )
            if resp.status_code == 200:
                return resp.json().get('response', '').strip() or 'I did not understand that.'
            logger.error(f"Ollama error: {resp.text}")
            return 'Sorry, I encountered an error.'
        except Exception as e:
            logger.error(f"Ollama request failed: {e}")
            return 'Sorry, I am having trouble connecting to my language model.'

    def tts_wav(self, text):
        try:
            # Get voice configuration from database (same as mumble-bot)
            voice_config = self.get_config('piper_voice', 'en_US-lessac-medium')
            logger.info(f"Using voice: {voice_config}")
            
            resp = requests.post(f"{self.piper_url}/synthesize", json={'text': text}, timeout=60)
            if resp.status_code == 200:
                return io.BytesIO(resp.content)
            logger.error(f"Piper TTS error: {resp.text}")
            return None
        except Exception as e:
            logger.error(f"TTS request failed: {e}")
            return None

    def play_tts_over_rtp(self, sip_call: 'SIPCall', wav_bytes: io.BytesIO):
        if not wav_bytes:
            return
        try:
            wav_bytes.seek(0)
            with tempfile_named(suffix='.wav') as tmp_in:
                with open(tmp_in, 'wb') as f:
                    f.write(wav_bytes.read())
                # Read PCM from WAV
                with wave.open(tmp_in, 'rb') as w:
                    n_channels = w.getnchannels()
                    sampwidth = w.getsampwidth()
                    framerate = w.getframerate()
                    frames = w.readframes(w.getnframes())

                # Ensure mono 16-bit
                if n_channels > 1:
                    frames = audioop.tomono(frames, sampwidth, 0.5, 0.5)
                if sampwidth != 2:
                    frames = audioop.lin2lin(frames, sampwidth, 2)
                # Resample to 8kHz for PCMU
                if framerate != 8000:
                    frames, _ = audioop.ratecv(frames, 2, 1, framerate, 8000, None)

                # Chunk into 20ms (160 samples @ 8kHz -> 320 bytes 16-bit)
                chunk_size = 160 * 2
                for i in range(0, len(frames), chunk_size):
                    chunk = frames[i:i + chunk_size]
                    if len(chunk) == 0:
                        continue
                    # μ-law encode
                    ulaw = audioop.lin2ulaw(chunk, 2)
                    sip_call.send_rtp(ulaw, payload_type=0)
                    time.sleep(0.02)
        except Exception as e:
            logger.error(f"Error playing TTS over RTP: {e}")


class tempfile_named:
    """Context manager to create and auto-clean a temp file."""

    def __init__(self, suffix=''):
        self.suffix = suffix
        self.name = None

    def __enter__(self):
        import tempfile
        f = tempfile.NamedTemporaryFile(delete=False, suffix=self.suffix)
        self.name = f.name
        f.close()
        return self.name

    def __exit__(self, exc_type, exc, tb):
        try:
            if self.name and os.path.exists(self.name):
                os.unlink(self.name)
        except Exception:
            pass


class CallSession:
    """Manages a single call session with RTP audio and AI pipeline."""

    def __init__(self, sip_call):
        self.sip_call = sip_call
        self.active = False
        self.rtp_thread = None
        self.pipeline = AIPipeline()
        # Voice activity detection on 8kHz PCM
        self.voice_threshold = 500  # empirical
        self.silence_threshold = 1.5  # seconds
        self.recording = False
        self.last_audio_time = None
        self.audio_buffer_8k = []  # list of 16-bit PCM @8kHz
        self.processing = False
        # Identify caller
        self.caller_name = self._extract_caller_name()
        self.user_session = 0

    def start(self):
        """Start the call session"""
        try:
            logger.info(f"Starting call session with {self.sip_call.caller_addr}")

            self.active = True
            # Start RTP receive thread (handles VAD -> STT -> LLM -> TTS)
            self.rtp_thread = threading.Thread(target=self._rtp_receive_loop, daemon=True)
            self.rtp_thread.start()


            logger.info("Call session active with RTP audio")
            return True

        except Exception as e:
            logger.error(f"Error starting call session: {e}")
            self.stop()
            return False

    def _rtp_receive_loop(self):
        """Receive RTP packets, detect utterances, and run AI pipeline."""
        logger.info("RTP receive loop started")
        self.sip_call.rtp_socket.settimeout(0.1)
        packet_count = 0

        while self.active and self.sip_call.rtp_socket:
            try:
                data, addr = self.sip_call.rtp_socket.recvfrom(2048)

                if len(data) < 12:
                    continue  # Invalid RTP packet

                # Parse RTP header (12 bytes)
                header = struct.unpack('!BBHII', data[:12])
                payload = data[12:]

                packet_count += 1
                if packet_count % 100 == 1:  # Log every 100th packet
                    logger.debug(f"Received RTP packet {packet_count}, payload size: {len(payload)} bytes")

                # μ-law (8-bit) -> 16-bit PCM @8kHz
                try:
                    pcm_8k = audioop.ulaw2lin(payload, 1)
                    # Voice activity detection
                    rms = audioop.rms(pcm_8k, 2)
                    if rms > self.voice_threshold:
                        self.audio_buffer_8k.append(pcm_8k)
                        self.last_audio_time = time.time()
                        if not self.recording:
                            self.recording = True
                            logger.info("Started recording from caller")
                    elif self.recording:
                        # still buffer tail during trailing silence
                        self.audio_buffer_8k.append(pcm_8k)

                    # Check for end of utterance
                    if self.recording and self.last_audio_time:
                        if (time.time() - self.last_audio_time) >= self.silence_threshold and not self.processing:
                            # finalize current buffer and process in background
                            audio_chunks = self.audio_buffer_8k
                            self.audio_buffer_8k = []
                            self.recording = False
                            self.last_audio_time = None
                            self.processing = True
                            threading.Thread(target=self._process_utterance, args=(audio_chunks,), daemon=True).start()
                except Exception as e:
                    logger.error(f"Error handling incoming audio: {e}", exc_info=True)

            except socket.timeout:
                continue
            except OSError as e:
                # Socket closed (Bad file descriptor) - call ended
                if e.errno == 9:  # EBADF
                    logger.info("RTP socket closed, stopping receive loop")
                    break
                elif self.active:
                    logger.error(f"Error in RTP receive: {e}")
                    break
            except Exception as e:
                if self.active:
                    logger.error(f"Error in RTP receive: {e}")
                    break

        logger.info("RTP receive loop stopped")

    def _process_utterance(self, chunks_8k):
        try:
            logger.info("Silence detected, transcribing audio...")
            # Write PCM 8k 16-bit chunks to WAV
            with tempfile_named(suffix='.wav') as wav_path:
                with wave.open(wav_path, 'wb') as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(8000)
                    for ch in chunks_8k:
                        w.writeframes(ch)

                # Transcribe
                transcript = self.pipeline.transcribe_wav_file(wav_path)

            if not transcript:
                logger.info("Transcript empty; skipping LLM/TTS")
                return

            logger.info(f"Transcribed: {transcript}")

            # Save user voice to DB (same as mumble-bot)
            self.pipeline.save_message(self.caller_name, self.user_session, 'voice', 'user', transcript)

            # Cue: "Let me think about that..." before LLM
            logger.info("Playing thinking cue...")
            thinking_cue = self.pipeline.tts_wav("Let me think about that...")
            self.pipeline.play_tts_over_rtp(self.sip_call, thinking_cue)

            # LLM
            response_text = self.pipeline.ollama_generate(transcript, user_name=self.caller_name)
            logger.info(f"Ollama response: {response_text}")

            # Save assistant response to DB (same as mumble-bot)
            self.pipeline.save_message(self.caller_name, self.user_session, 'voice', 'assistant', response_text)

            # Cue 3: "Here's my response..." before final response
            logger.info("Playing response cue...")
            response_cue = self.pipeline.tts_wav("Here's my response...")
            self.pipeline.play_tts_over_rtp(self.sip_call, response_cue)

            # TTS
            wav_bytes = self.pipeline.tts_wav(response_text)

            # Play over RTP
            self.pipeline.play_tts_over_rtp(self.sip_call, wav_bytes)

        except Exception as e:
            logger.error(f"Error processing utterance: {e}", exc_info=True)
        finally:
            self.processing = False

    def stop(self):
        """Stop the call session"""
        self.active = False

        if self.sip_call:
            self.sip_call.close()

        logger.info("Call session stopped")

    def _extract_caller_name(self):
        try:
            from_header = self.sip_call.invite_msg
            # Prefer From header
            m = re.search(r"^From:\s*(.*)$", self.sip_call.invite_msg, re.MULTILINE)
            if m:
                from_val = m.group(1)
                # Try display name "Name" <sip:user@host>
                mname = re.search(r'"([^"]+)"', from_val)
                if mname:
                    return mname.group(1)
                # Try user part sip:user@
                muser = re.search(r'sip:([^@;>]+)', from_val)
                if muser:
                    return muser.group(1)
            return "SIP-Caller"
        except Exception:
            return "SIP-Caller"


class SIPMumbleBridge:
    """Main SIP-Mumble bridge application"""

    def __init__(self):
        self.sip_server = SimpleSIPServer(port=config.SIP_PORT)
        self.active_calls = {}

    def start(self):
        """Start the bridge"""
        logger.info("=" * 60)
        logger.info("SIP-Mumble Bridge Starting")
        logger.info("=" * 60)
        logger.info(f"SIP Port: {config.SIP_PORT}")
        logger.info(f"Mumble Server: {config.MUMBLE_HOST}:{config.MUMBLE_PORT}")
        logger.info("=" * 60)

        # Set call handler
        self.sip_server.set_call_handler(self._handle_incoming_call)

        # Start SIP server
        if not self.sip_server.start():
            logger.error("Failed to start SIP server")
            return False

        logger.info("SIP-Mumble Bridge is ready and waiting for calls")
        return True

    def _handle_incoming_call(self, sip_call):
        """Handle incoming call after ACK is received"""
        try:
            logger.info(f"Handling call from {sip_call.caller_addr}")

            # Create call session
            session = CallSession(sip_call)

            if session.start():
                self.active_calls[sip_call.call_id] = session
                logger.info(f"Call session created for {sip_call.caller_addr}")
            else:
                logger.error(f"Failed to start session for {sip_call.caller_addr}")

        except Exception as e:
            logger.error(f"Error handling call: {e}")

    def run(self):
        """Run the bridge"""
        if not self.start():
            return

        try:
            # Keep running
            while True:
                time.sleep(1)

        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            self.shutdown()

    def shutdown(self):
        """Shutdown the bridge"""
        # Stop all active calls
        for addr, session in list(self.active_calls.items()):
            session.stop()

        self.active_calls.clear()

        # Stop SIP server
        self.sip_server.stop()

        logger.info("Bridge shutdown complete")


def main():
    """Main entry point"""
    bridge = SIPMumbleBridge()
    bridge.run()


if __name__ == "__main__":
    main()
