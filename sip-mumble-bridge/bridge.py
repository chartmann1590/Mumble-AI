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
import uuid
import hashlib
from psycopg2 import pool
from collections import deque
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional

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

            # Find media port (m=) and codecs
            for line in lines:
                if line.startswith('m=audio'):
                    # m=audio 16970 RTP/AVP 0 8 101
                    parts = line.split()
                    if len(parts) >= 2:
                        self.remote_rtp_port = int(parts[1])
                        # Extract payload types (codecs)
                        if len(parts) >= 4:
                            codecs = ' '.join(parts[3:])
                            logger.info(f"Client offered codecs (payload types): {codecs}")

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
        self.silero_url = config.SILERO_URL

        # DB config
        self.db_host = config.DB_HOST
        self.db_port = config.DB_PORT
        self.db_name = config.DB_NAME
        self.db_user = config.DB_USER
        self.db_password = config.DB_PASSWORD
        self.db_pool = None
        self._init_db_pool()
        self._wait_for_services()

        # Semantic memory and session tracking
        self.user_sessions = {}  # Track active sessions per user
        self.session_lock = threading.Lock()
        self.embedding_cache = {}  # Cache embeddings to reduce API calls

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

    def save_message(self, user_name, user_session, message_type, role, message, session_id=None):
        """Save a message to the conversation history asynchronously (non-blocking)"""
        # Run DB write in background thread to avoid blocking the main pipeline
        threading.Thread(
            target=self._save_message_sync,
            args=(user_name, user_session, message_type, role, message, session_id),
            daemon=True
        ).start()
        return True

    def _save_message_sync(self, user_name, user_session, message_type, role, message, session_id=None):
        """Internal synchronous save method run in background thread"""
        conn = None
        try:
            conn = self.get_db_connection()
            if not conn:
                logger.warning("Cannot save message: database connection unavailable")
                return False

            # Generate embedding for the message
            embedding = self.generate_embedding(message)

            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO conversation_history
                (user_name, user_session, session_id, message_type, role, message, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (user_name, user_session, session_id, message_type, role, message, embedding)
            )
            conn.commit()
            cursor.close()
            logger.debug(f"Saved {role} {message_type} message from {user_name} (session: {session_id})")
            return True
        except Exception as e:
            logger.error(f"Error saving message to database: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                self.release_db_connection(conn)

    def get_conversation_history(self, user_name=None, limit=10, session_id=None):
        conn = None
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()

            if session_id:
                # Get history for specific session
                cursor.execute(
                    """
                    SELECT role, message, message_type, timestamp
                    FROM conversation_history
                    WHERE session_id = %s
                    ORDER BY timestamp DESC
                    LIMIT %s
                    """,
                    (session_id, limit)
                )
            elif user_name:
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

    def generate_embedding(self, text: str) -> Optional[List[float]]:
        """Generate embedding vector for text using Ollama's embedding model"""
        # Check cache first
        text_hash = hashlib.md5(text.encode()).hexdigest()
        if text_hash in self.embedding_cache:
            return self.embedding_cache[text_hash]

        try:
            embedding_model = self.get_config('embedding_model', 'nomic-embed-text:latest')
            ollama_url = self.get_config('ollama_url', config.DEFAULT_OLLAMA_URL)

            response = requests.post(
                f"{ollama_url}/api/embeddings",
                json={
                    'model': embedding_model,
                    'prompt': text
                },
                timeout=30
            )

            if response.status_code == 200:
                embedding = response.json().get('embedding', [])
                # Cache the embedding
                self.embedding_cache[text_hash] = embedding
                return embedding
            else:
                logger.warning(f"Failed to generate embedding: {response.text}")
                return None
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return None

    def get_or_create_session(self, user_name: str, user_session: int) -> str:
        """Get or create a conversation session ID for a user"""
        with self.session_lock:
            # Check if user has an active session
            if user_name in self.user_sessions:
                session_id = self.user_sessions[user_name]
                # Update session activity
                self._update_session_activity(session_id)
                return session_id

            # Create new session
            session_id = f"{user_name}_{uuid.uuid4().hex[:8]}_{int(time.time())}"
            self.user_sessions[user_name] = session_id

            # Store in database
            conn = None
            try:
                conn = self.get_db_connection()
                if conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        INSERT INTO conversation_sessions (user_name, session_id, started_at, last_activity)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (session_id) DO UPDATE SET last_activity = EXCLUDED.last_activity
                        """,
                        (user_name, session_id, datetime.now(), datetime.now())
                    )
                    conn.commit()
                    cursor.close()
                    logger.info(f"Created new session {session_id} for {user_name}")
            except Exception as e:
                logger.error(f"Error creating session: {e}")
                if conn:
                    conn.rollback()
            finally:
                if conn:
                    self.release_db_connection(conn)

            return session_id

    def _update_session_activity(self, session_id: str):
        """Update the last activity timestamp for a session"""
        conn = None
        try:
            conn = self.get_db_connection()
            if conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE conversation_sessions
                    SET last_activity = %s, message_count = message_count + 1
                    WHERE session_id = %s
                    """,
                    (datetime.now(), session_id)
                )
                conn.commit()
                cursor.close()
        except Exception as e:
            logger.error(f"Error updating session activity: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                self.release_db_connection(conn)

    def close_idle_sessions(self):
        """Close sessions that have been idle for too long"""
        timeout_minutes = int(self.get_config('session_timeout_minutes', '30'))
        timeout_delta = timedelta(minutes=timeout_minutes)

        conn = None
        try:
            conn = self.get_db_connection()
            if conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE conversation_sessions
                    SET state = 'idle'
                    WHERE state = 'active' AND last_activity < %s
                    RETURNING session_id, user_name
                    """,
                    (datetime.now() - timeout_delta,)
                )
                idle_sessions = cursor.fetchall()
                conn.commit()
                cursor.close()

                # Remove from active sessions
                with self.session_lock:
                    for session_id, user_name in idle_sessions:
                        if user_name in self.user_sessions and self.user_sessions[user_name] == session_id:
                            del self.user_sessions[user_name]
                            logger.info(f"Closed idle session {session_id} for {user_name}")
        except Exception as e:
            logger.error(f"Error closing idle sessions: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                self.release_db_connection(conn)

    def extract_and_save_memory(self, user_message: str, assistant_response: str, user_name: str, session_id: str):
        """Extract important information from conversation and save as persistent memory"""
        try:
            ollama_url = self.get_config('ollama_url', config.DEFAULT_OLLAMA_URL)
            ollama_model = self.get_config('ollama_model', config.DEFAULT_OLLAMA_MODEL)

            # Get current date for context
            from zoneinfo import ZoneInfo
            from datetime import datetime
            ny_tz = ZoneInfo("America/New_York")
            current_datetime = datetime.now(ny_tz)
            current_date_str = current_datetime.strftime("%Y-%m-%d (%A, %B %d, %Y)")

            # Prompt to extract important information with stricter JSON format requirements
            extraction_prompt = f"""Analyze this conversation and extract important information to remember.

CURRENT DATE: {current_date_str}

User: "{user_message}"
Assistant: "{assistant_response}"

Categories:
- schedule: appointments, meetings, events with dates/times
- fact: personal information, preferences, relationships, details
- task: things to do, reminders, action items
- preference: likes, dislikes, habits
- other: other important information

CRITICAL RULES:
1. ONLY extract information that is actually mentioned and important
2. Do NOT create entries with empty content
3. If there's nothing important to remember, return an empty array: []
4. You MUST respond with ONLY valid JSON, nothing else
5. DO NOT extract schedule memories when the user is just ASKING or QUERYING about their schedule
6. ONLY extract schedule memories when the user is TELLING you about NEW events or appointments
7. If the user asks "what's on my schedule", "tell me my calendar", "do I have anything", etc., return []

IMPORTANT: Query questions should return empty array. Examples:
- "What's on my schedule?" → []
- "Tell me about my calendar" → []
- "Do I have anything tomorrow?" → []
- "What do I have next week?" → []

For SCHEDULE category memories:
- Extract the date expression as spoken: "next Friday", "tomorrow", "October 15", etc.
- Use date_expression field for the raw expression
- Use HH:MM format (24-hour) for event_time, or null if no specific time
- Include description in content field

Format (return empty array if nothing important):
[
  {{"category": "schedule", "content": "Haircut appointment", "importance": 6, "date_expression": "next Friday", "event_time": "09:30"}},
  {{"category": "fact", "content": "Likes tea over coffee", "importance": 4}}
]

Valid categories: schedule, fact, task, preference, other
Importance: 1-10 (1=low, 10=critical)

JSON:"""

            response = requests.post(
                f"{ollama_url}/api/generate",
                json={
                    'model': ollama_model,
                    'prompt': extraction_prompt,
                    'stream': False,
                    'options': {'temperature': 0.3}  # Lower temp for more consistent extraction
                },
                timeout=30
            )

            if response.status_code == 200:
                result = response.json().get('response', '').strip()

                # Try to parse JSON
                import json
                import re

                # Extract JSON from response (might have extra text)
                json_match = re.search(r'\[.*\]', result, re.DOTALL)
                if json_match:
                    memories = json.loads(json_match.group())

                    # Filter out memories with empty or whitespace-only content
                    valid_memories = []
                    for mem in memories:
                        if isinstance(mem, dict) and 'content' in mem and 'category' in mem:
                            content = mem.get('content', '')
                            # Skip if content is not a string or is empty/whitespace
                            if isinstance(content, str) and content.strip():
                                valid_memories.append(mem)
                            else:
                                # Debug level for expected LLM artifacts
                                logger.debug(f"Filtered out empty memory: category={mem.get('category')}, importance={mem.get('importance')}")

                    # Save each valid extracted memory
                    for memory in valid_memories:
                        # Parse date expression for schedule memories
                        event_date = None
                        event_time = memory.get('event_time')

                        if memory.get('category') == 'schedule':
                            date_expression = memory.get('date_expression') or memory.get('event_date')
                            if date_expression:
                                event_date = self.parse_date_expression(date_expression)

                        self.save_persistent_memory(
                            user_name=user_name,
                            category=memory.get('category', 'other'),
                            content=memory['content'],
                            session_id=session_id,
                            importance=memory.get('importance', 5),
                            event_date=event_date,
                            event_time=event_time
                        )
                        if event_date:
                            logger.info(f"Extracted memory for {user_name}: [{memory.get('category')}] {memory['content']} on {event_date} at {event_time or 'all day'}")
                        else:
                            logger.info(f"Extracted memory for {user_name}: [{memory.get('category')}] {memory['content']}")

        except Exception as e:
            logger.error(f"Error extracting memory: {e}")

    def save_persistent_memory(self, user_name: str, category: str, content: str, session_id: str = None, importance: int = 5, tags: List[str] = None, event_date: str = None, event_time: str = None):
        """Save a persistent memory to the database (with deduplication)"""
        conn = None
        try:
            conn = self.get_db_connection()
            if conn:
                cursor = conn.cursor()

                # Check for duplicates based on category type
                if category == 'schedule' and event_date:
                    # For schedule memories, check user, category, event_date, and event_time
                    cursor.execute(
                        """
                        SELECT id, content, importance
                        FROM persistent_memories
                        WHERE user_name = %s AND category = %s AND event_date = %s
                        AND event_time IS NOT DISTINCT FROM %s AND active = TRUE
                        """,
                        (user_name, category, event_date, event_time)
                    )
                else:
                    # For non-schedule memories, check for exact content match
                    cursor.execute(
                        """
                        SELECT id, importance
                        FROM persistent_memories
                        WHERE user_name = %s AND category = %s AND content = %s AND active = TRUE
                        """,
                        (user_name, category, content)
                    )

                existing = cursor.fetchone()

                if existing:
                    if category == 'schedule':
                        existing_id, existing_content, existing_importance = existing
                        logger.info(f"Duplicate schedule memory detected for {user_name} on {event_date}. Skipping. Existing ID: {existing_id}")
                    else:
                        existing_id, existing_importance = existing
                        logger.info(f"Duplicate {category} memory detected for {user_name}: '{content[:50]}...'. Skipping. Existing ID: {existing_id}")

                    # If new importance is higher, update it
                    if importance > existing_importance:
                        cursor.execute(
                            "UPDATE persistent_memories SET importance = %s WHERE id = %s",
                            (importance, existing_id)
                        )
                        conn.commit()
                        logger.info(f"Updated importance of existing memory ID {existing_id} from {existing_importance} to {importance}")

                    cursor.close()
                    return

                # No duplicate found, insert new memory
                cursor.execute(
                    """
                    INSERT INTO persistent_memories
                    (user_name, category, content, session_id, importance, tags, event_date, event_time)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (user_name, category, content, session_id, importance, tags or [], event_date, event_time)
                )
                conn.commit()
                cursor.close()
                logger.info(f"Saved new {category} memory for {user_name}")
        except Exception as e:
            logger.error(f"Error saving persistent memory: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                self.release_db_connection(conn)

    def get_schedule_events(self, user_name: str = None, start_date: str = None, end_date: str = None, limit: int = 50) -> List[Dict]:
        """Retrieve schedule events for a user within a date range"""
        conn = None
        try:
            conn = self.get_db_connection()
            if not conn:
                return []

            cursor = conn.cursor()

            # Build query based on filters
            query = """
                SELECT id, user_name, title, event_date, event_time, description, importance, created_at
                FROM schedule_events
                WHERE active = TRUE
            """
            params = []

            if user_name:
                query += " AND user_name = %s"
                params.append(user_name)

            if start_date:
                query += " AND event_date >= %s"
                params.append(start_date)

            if end_date:
                query += " AND event_date <= %s"
                params.append(end_date)

            query += " ORDER BY event_date, event_time LIMIT %s"
            params.append(limit)

            cursor.execute(query, params)
            results = cursor.fetchall()
            cursor.close()

            events = []
            for row in results:
                events.append({
                    'id': row[0],
                    'user_name': row[1],
                    'title': row[2],
                    'event_date': row[3],
                    'event_time': row[4],
                    'description': row[5],
                    'importance': row[6],
                    'created_at': row[7]
                })

            logger.info(f"Retrieved {len(events)} schedule events for {user_name}")
            return events

        except Exception as e:
            logger.error(f"Error retrieving schedule events: {e}")
            return []
        finally:
            if conn:
                self.release_db_connection(conn)

    def add_schedule_event(self, user_name: str, title: str, event_date: str, event_time: str = None,
                          description: str = None, importance: int = 5) -> int:
        """Add a new schedule event (with deduplication)"""
        conn = None
        try:
            conn = self.get_db_connection()
            if not conn:
                return None

            cursor = conn.cursor()

            # Check for duplicate: same user, title, and date
            cursor.execute(
                """
                SELECT id, event_time, description, importance
                FROM schedule_events
                WHERE user_name = %s AND title = %s AND event_date = %s AND active = TRUE
                """,
                (user_name, title, event_date)
            )

            existing = cursor.fetchone()

            if existing:
                existing_id, existing_time, existing_desc, existing_importance = existing
                logger.info(f"Duplicate schedule event detected for {user_name}: '{title}' on {event_date}. Using existing ID {existing_id}")

                # If new info is more detailed, update the existing event
                should_update = False
                updates = []
                params = []

                if event_time and not existing_time:
                    updates.append("event_time = %s")
                    params.append(event_time)
                    should_update = True

                if description and not existing_desc:
                    updates.append("description = %s")
                    params.append(description)
                    should_update = True

                if importance and importance > existing_importance:
                    updates.append("importance = %s")
                    params.append(importance)
                    should_update = True

                if should_update:
                    params.append(existing_id)
                    update_query = f"UPDATE schedule_events SET {', '.join(updates)} WHERE id = %s"
                    cursor.execute(update_query, params)
                    conn.commit()
                    logger.info(f"Updated existing schedule event ID {existing_id} with new details")

                cursor.close()
                return existing_id

            # No duplicate found, create new event
            cursor.execute(
                """
                INSERT INTO schedule_events (user_name, title, event_date, event_time, description, importance)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (user_name, title, event_date, event_time, description, importance)
            )

            event_id = cursor.fetchone()[0]
            conn.commit()
            cursor.close()

            logger.info(f"Added schedule event ID {event_id} for {user_name}: {title} on {event_date}")
            return event_id

        except Exception as e:
            logger.error(f"Error adding schedule event: {e}")
            if conn:
                conn.rollback()
            return None
        finally:
            if conn:
                self.release_db_connection(conn)

    def update_schedule_event(self, event_id: int, title: str = None, event_date: str = None,
                             event_time: str = None, description: str = None, importance: int = None) -> bool:
        """Update an existing schedule event"""
        conn = None
        try:
            conn = self.get_db_connection()
            if not conn:
                return False

            cursor = conn.cursor()

            # Build update query dynamically
            updates = []
            params = []

            if title is not None:
                updates.append("title = %s")
                params.append(title)
            if event_date is not None:
                updates.append("event_date = %s")
                params.append(event_date)
            if event_time is not None:
                updates.append("event_time = %s")
                params.append(event_time)
            if description is not None:
                updates.append("description = %s")
                params.append(description)
            if importance is not None:
                updates.append("importance = %s")
                params.append(importance)

            if not updates:
                return False

            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(event_id)

            query = f"UPDATE schedule_events SET {', '.join(updates)} WHERE id = %s AND active = TRUE"
            cursor.execute(query, params)

            affected = cursor.rowcount
            conn.commit()
            cursor.close()

            logger.info(f"Updated schedule event ID {event_id}, affected rows: {affected}")
            return affected > 0

        except Exception as e:
            logger.error(f"Error updating schedule event: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                self.release_db_connection(conn)

    def delete_schedule_event(self, event_id: int) -> bool:
        """Delete (deactivate) a schedule event"""
        conn = None
        try:
            conn = self.get_db_connection()
            if not conn:
                return False

            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE schedule_events
                SET active = FALSE, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (event_id,)
            )

            affected = cursor.rowcount
            conn.commit()
            cursor.close()

            logger.info(f"Deleted schedule event ID {event_id}, affected rows: {affected}")
            return affected > 0

        except Exception as e:
            logger.error(f"Error deleting schedule event: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                self.release_db_connection(conn)

    def parse_date_expression(self, date_expr: str, reference_date: datetime = None) -> Optional[str]:
        """Parse natural language date expressions into YYYY-MM-DD format"""
        if not date_expr or date_expr == "null":
            return None

        from zoneinfo import ZoneInfo
        import re

        ny_tz = ZoneInfo("America/New_York")
        if reference_date is None:
            reference_date = datetime.now(ny_tz)

        date_expr = date_expr.lower().strip()

        # Already in YYYY-MM-DD format
        if re.match(r'^\d{4}-\d{2}-\d{2}$', date_expr):
            return date_expr

        # Handle "tomorrow"
        if date_expr == "tomorrow":
            result_date = reference_date + timedelta(days=1)
            return result_date.strftime('%Y-%m-%d')

        # Handle "today"
        if date_expr == "today":
            return reference_date.strftime('%Y-%m-%d')

        # Handle "in X days/weeks/months"
        in_match = re.match(r'in (\d+) (day|days|week|weeks|month|months)', date_expr)
        if in_match:
            count = int(in_match.group(1))
            unit = in_match.group(2)
            if 'day' in unit:
                result_date = reference_date + timedelta(days=count)
            elif 'week' in unit:
                result_date = reference_date + timedelta(weeks=count)
            elif 'month' in unit:
                result_date = reference_date + timedelta(days=count * 30)  # Approximate
            return result_date.strftime('%Y-%m-%d')

        # Handle day names: "this Monday", "next Friday", "Monday", etc.
        day_names = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

        for i, day_name in enumerate(day_names):
            if day_name in date_expr:
                current_weekday = reference_date.weekday()  # Monday is 0
                target_weekday = i

                # Determine if "this" or "next"
                if 'next' in date_expr:
                    # "next Friday" means next week's Friday
                    days_ahead = (target_weekday - current_weekday) % 7
                    if days_ahead == 0:
                        days_ahead = 7  # If today is Friday, "next Friday" is 7 days away
                    else:
                        days_ahead += 7  # Always go to next week
                elif 'this' in date_expr:
                    # "this Friday" means this week's Friday
                    days_ahead = (target_weekday - current_weekday) % 7
                    if days_ahead == 0:
                        days_ahead = 7  # If today is Friday, "this Friday" might mean next occurrence
                else:
                    # Just "Friday" - means upcoming Friday (could be this week or next)
                    days_ahead = (target_weekday - current_weekday) % 7
                    if days_ahead == 0:
                        days_ahead = 7  # If today is Friday, assume next Friday

                result_date = reference_date + timedelta(days=days_ahead)
                return result_date.strftime('%Y-%m-%d')

        # Try parsing common date formats
        try:
            from dateutil import parser
            parsed_date = parser.parse(date_expr, fuzzy=True)
            return parsed_date.strftime('%Y-%m-%d')
        except:
            pass

        logger.warning(f"Could not parse date expression: {date_expr}")
        return None

    def extract_and_manage_schedule(self, user_message: str, assistant_response: str, user_name: str):
        """Extract scheduling information from conversation and manage schedule events"""
        try:
            ollama_url = self.get_config('ollama_url', self.ollama_url)
            ollama_model = self.get_config('ollama_model', self.ollama_model)

            # Get current date for context
            from zoneinfo import ZoneInfo
            from datetime import timedelta
            ny_tz = ZoneInfo("America/New_York")
            current_datetime = datetime.now(ny_tz)
            current_date_str = current_datetime.strftime("%Y-%m-%d (%A, %B %d, %Y)")

            extraction_prompt = f"""You are a scheduling assistant analyzing a conversation to manage calendar events.

CURRENT DATE: {current_date_str}

Conversation:
User: {user_message}
Assistant: {assistant_response}

Analyze this conversation and determine if the user wants to:
1. ADD a new event to their schedule
2. UPDATE an existing event
3. DELETE/CANCEL an event
4. NOTHING - just asking about schedule or casual conversation

If scheduling action is needed, extract:
- Action: ADD, UPDATE, DELETE, or NOTHING
- Event title (brief description)
- Date expression (use these formats):
  * Specific date: "2025-10-15" or "October 15" or "Oct 15"
  * Relative: "tomorrow", "next Monday", "next Friday", "in 3 days"
- Time (HH:MM format in 24-hour, or null if not specified)
- Description (optional additional details)
- Importance (1-10, default 5)
- Event ID (if updating/deleting - look for "that event", "the appointment", etc.)

CRITICAL INSTRUCTIONS:
- ONLY use action "ADD" if the user is CREATING or SCHEDULING a NEW event
- If the user is ASKING, QUERYING, READING, or CHECKING their schedule, ALWAYS use action "NOTHING"
- DO NOT create events when the user asks "what's on my calendar", "tell me my schedule", "what do I have", "do I have anything", etc.
- When in doubt, use "NOTHING" - it's better to not create than to create a duplicate

IMPORTANT: For relative dates like "next Friday", just return "next Friday" - do NOT calculate the actual date.

Respond ONLY with a JSON object (no markdown, no extra text):
{{"action": "ADD|UPDATE|DELETE|NOTHING", "title": "...", "date_expression": "next Friday", "time": "HH:MM or null", "description": "...", "importance": 5, "event_id": null}}

Examples:
User: "I have a dentist appointment tomorrow at 3pm"
{{"action": "ADD", "title": "Dentist appointment", "date_expression": "tomorrow", "time": "15:00", "description": null, "importance": 7, "event_id": null}}

User: "Schedule me for next Friday at 9:30am for my haircut"
{{"action": "ADD", "title": "haircut", "date_expression": "next Friday", "time": "09:30", "description": null, "importance": 5, "event_id": null}}

User: "Cancel my meeting on Monday"
{{"action": "DELETE", "title": "meeting", "date_expression": null, "time": null, "description": null, "importance": 5, "event_id": null}}

User: "What's on my schedule?"
{{"action": "NOTHING", "title": null, "date_expression": null, "time": null, "description": null, "importance": 5, "event_id": null}}

User: "Tell me about my calendar"
{{"action": "NOTHING", "title": null, "date_expression": null, "time": null, "description": null, "importance": 5, "event_id": null}}

User: "Do I have anything tomorrow?"
{{"action": "NOTHING", "title": null, "date_expression": null, "time": null, "description": null, "importance": 5, "event_id": null}}

User: "What do I have next week?"
{{"action": "NOTHING", "title": null, "date_expression": null, "time": null, "description": null, "importance": 5, "event_id": null}}
"""

            response = requests.post(
                f"{ollama_url}/api/generate",
                json={
                    'model': ollama_model,
                    'prompt': extraction_prompt,
                    'stream': False,
                    'temperature': 0.1
                },
                timeout=30
            )

            if response.status_code == 200:
                import json
                result_text = response.json().get('response', '').strip()

                # Parse JSON response
                try:
                    result = json.loads(result_text)
                    action = result.get('action', 'NOTHING')

                    if action == 'ADD':
                        # Parse the date expression into YYYY-MM-DD format
                        date_expression = result.get('date_expression') or result.get('date')
                        parsed_date = self.parse_date_expression(date_expression, current_datetime)

                        event_id = self.add_schedule_event(
                            user_name=user_name,
                            title=result.get('title', 'Untitled Event'),
                            event_date=parsed_date,
                            event_time=result.get('time'),
                            description=result.get('description'),
                            importance=result.get('importance', 5)
                        )
                        if event_id:
                            logger.info(f"Added schedule event {event_id} for {user_name}: {result.get('title')} on {parsed_date}")

                    elif action == 'UPDATE' and result.get('event_id'):
                        # Parse the date expression if present
                        date_expression = result.get('date_expression') or result.get('date')
                        parsed_date = self.parse_date_expression(date_expression, current_datetime) if date_expression else None

                        success = self.update_schedule_event(
                            event_id=result.get('event_id'),
                            title=result.get('title'),
                            event_date=parsed_date,
                            event_time=result.get('time'),
                            description=result.get('description'),
                            importance=result.get('importance')
                        )
                        if success:
                            logger.info(f"Updated schedule event {result.get('event_id')} for {user_name}")

                    elif action == 'DELETE':
                        # Find and delete matching events
                        title_search = result.get('title', '')
                        if title_search:
                            events = self.get_schedule_events(user_name=user_name)
                            for event in events:
                                if title_search.lower() in event['title'].lower():
                                    self.delete_schedule_event(event['id'])
                                    logger.info(f"Deleted schedule event {event['id']} for {user_name}")
                                    break

                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse schedule extraction result: {result_text}")

        except Exception as e:
            logger.error(f"Error in schedule extraction: {e}")
            import traceback
            traceback.print_exc()

    def get_persistent_memories(self, user_name: str, category: str = None, limit: int = 20) -> List[Dict]:
        """Retrieve persistent memories for a user"""
        conn = None
        try:
            conn = self.get_db_connection()
            if not conn:
                return []

            cursor = conn.cursor()

            if category:
                cursor.execute(
                    """
                    SELECT id, category, content, extracted_at, importance, tags, event_date, event_time
                    FROM persistent_memories
                    WHERE user_name = %s AND category = %s AND active = TRUE
                    ORDER BY importance DESC, extracted_at DESC
                    LIMIT %s
                    """,
                    (user_name, category, limit)
                )
            else:
                cursor.execute(
                    """
                    SELECT id, category, content, extracted_at, importance, tags, event_date, event_time
                    FROM persistent_memories
                    WHERE user_name = %s AND active = TRUE
                    ORDER BY importance DESC, extracted_at DESC
                    LIMIT %s
                    """,
                    (user_name, limit)
                )

            results = cursor.fetchall()
            cursor.close()

            memories = []
            for row in results:
                memories.append({
                    'id': row[0],
                    'category': row[1],
                    'content': row[2],
                    'extracted_at': row[3],
                    'importance': row[4],
                    'tags': row[5] or [],
                    'event_date': row[6],
                    'event_time': row[7]
                })

            return memories

        except Exception as e:
            logger.error(f"Error retrieving persistent memories: {e}")
            return []
        finally:
            if conn:
                self.release_db_connection(conn)

    def get_semantic_context(self, query_text: str, user_name: str, current_session_id: str, limit: int = 3) -> List[Dict]:
        """Retrieve semantically similar messages from long-term memory"""
        # Generate embedding for the query
        query_embedding = self.generate_embedding(query_text)
        if not query_embedding:
            return []

        conn = None
        try:
            conn = self.get_db_connection()
            if not conn:
                return []

            cursor = conn.cursor()

            # Get similarity threshold from config
            threshold = float(self.get_config('semantic_similarity_threshold', '0.7'))

            # Find similar messages from past conversations (excluding current session)
            cursor.execute(
                """
                SELECT id, role, message, message_type, timestamp, embedding,
                       cosine_similarity(%s::FLOAT8[], embedding) as similarity
                FROM conversation_history
                WHERE user_name = %s
                  AND session_id != %s
                  AND embedding IS NOT NULL
                  AND cosine_similarity(%s::FLOAT8[], embedding) > %s
                ORDER BY similarity DESC, timestamp DESC
                LIMIT %s
                """,
                (query_embedding, user_name, current_session_id, query_embedding, threshold, limit)
            )

            results = cursor.fetchall()
            cursor.close()

            context = []
            for row in results:
                context.append({
                    'role': row[1],
                    'message': row[2],
                    'message_type': row[3],
                    'timestamp': row[4],
                    'similarity': row[6]
                })

            return context

        except Exception as e:
            logger.error(f"Error retrieving semantic context: {e}")
            return []
        finally:
            if conn:
                self.release_db_connection(conn)

    def build_prompt_with_context(self, current_message, user_name=None, session_id=None):
        """Build a prompt with short-term (current session) and long-term (semantic) memory"""
        try:
            # Get bot persona from config
            persona = self.get_config('bot_persona', '')

            # Get memory limits from config
            short_term_limit = int(self.get_config('short_term_memory_limit', '3'))
            long_term_limit = int(self.get_config('long_term_memory_limit', '3'))

            # Build the full prompt
            full_prompt = ""

            # Get current date and time in New York timezone
            ny_tz = ZoneInfo("America/New_York")
            current_datetime = datetime.now(ny_tz)
            current_date_str = current_datetime.strftime("%A, %B %d, %Y")
            current_time_str = current_datetime.strftime("%I:%M %p %Z")

            # Add system instructions with anti-repetition and anti-hallucination guidance
            full_prompt = f"""You are having a natural, flowing conversation. CRITICAL RULES - FOLLOW EXACTLY:

CURRENT DATE AND TIME (New York): {current_date_str} at {current_time_str}
Use this information when answering questions about scheduling, planning, or time-sensitive topics.

SCHEDULING CAPABILITIES:
- You can access the user's calendar/schedule automatically
- When users mention events, appointments, or plans, they are AUTOMATICALLY saved to their schedule
- You can answer questions about upcoming events using the schedule shown below
- Users can ask "What's on my schedule?", "Do I have anything tomorrow?", etc.

1. BREVITY: Keep responses to 1-2 short sentences maximum. Be conversational but concise.
2. TRUTH: NEVER make up information. If you don't know something, say "I don't know" or "I'm not sure."
3. NO HALLUCINATION: Do NOT invent schedules, events, plans, or details that weren't mentioned by the user.
4. NO EMOJIS: Never use emojis in your responses.
5. NO REPETITION: Do NOT repeat or rephrase what you just said in previous messages.
6. NO SUMMARIES: Do NOT summarize the conversation.
7. BUILD NATURALLY: Add new information or perspectives, don't restate previous points.
8. STAY GROUNDED: Only discuss things that were actually mentioned in the conversation.
9. RESPOND TO CURRENT MESSAGE: Focus ONLY on what the user just said. Do NOT bring up unrelated topics from past conversations.

"""

            # Add persona if configured (but subordinate to truthfulness)
            if persona and persona.strip():
                full_prompt += f"Your personality/character: {persona.strip()}\n\n"
                full_prompt += "IMPORTANT: Stay in character BUT prioritize truthfulness over role-playing. "
                full_prompt += "If you don't have information, admit it rather than making something up to fit your character.\n\n"

            # Get persistent memories (important saved information)
            persistent_memories = []
            if user_name:
                persistent_memories = self.get_persistent_memories(user_name, limit=10)
                logger.info(f"Retrieved {len(persistent_memories)} persistent memories for {user_name}")

            # Get schedule events for the user (next 30 days)
            schedule_events = []
            if user_name:
                from datetime import timedelta
                end_date = (current_datetime + timedelta(days=30)).strftime('%Y-%m-%d')
                schedule_events = self.get_schedule_events(
                    user_name=user_name,
                    start_date=current_datetime.strftime('%Y-%m-%d'),
                    end_date=end_date,
                    limit=20
                )
                logger.info(f"Retrieved {len(schedule_events)} schedule events for {user_name}")

            # Add schedule events to context - ALWAYS include this section
            full_prompt += f"📅 {user_name.upper()}'S UPCOMING SCHEDULE (next 30 days from {current_datetime.strftime('%A, %B %d, %Y')}):\n"
            if schedule_events:
                for event in schedule_events:
                    event_date_obj = event['event_date']
                    event_date_str = event_date_obj.strftime('%A, %B %d, %Y') if hasattr(event_date_obj, 'strftime') else str(event_date_obj)
                    event_time_str = str(event['event_time']) if event['event_time'] else "All day"
                    importance_emoji = "🔴" if event['importance'] >= 9 else "🟠" if event['importance'] >= 7 else "🔵"
                    full_prompt += f"{importance_emoji} {event['title']} - {event_date_str} at {event_time_str}\n"
                    if event['description']:
                        full_prompt += f"   Details: {event['description']}\n"
                full_prompt += "\n⚠️ CRITICAL SCHEDULE INSTRUCTIONS:\n"
                full_prompt += "- These are the ONLY events scheduled. Do not mention any events not listed above.\n"
                full_prompt += "- Use the EXACT dates shown. Do not guess or approximate dates.\n"
                full_prompt += "- If asked about a specific time period, only mention events that fall within that period based on the dates shown.\n\n"
            else:
                full_prompt += "NO EVENTS SCHEDULED\n\n"
                full_prompt += "⚠️ CRITICAL: The schedule is EMPTY. When asked about schedule/calendar:\n"
                full_prompt += "- Say clearly: \"You don't have anything on your schedule\" or \"Your calendar is clear\"\n"
                full_prompt += "- DO NOT make up events, appointments, or plans\n"
                full_prompt += "- DO NOT suggest events that might exist\n"
                full_prompt += "- DO NOT hallucinate schedule information\n\n"

            # Add persistent memories to context
            if persistent_memories:
                full_prompt += "IMPORTANT SAVED INFORMATION (use this to answer questions accurately):\n"
                for mem in persistent_memories:
                    category_label = mem['category'].upper()
                    # For schedule memories with date/time, format them specially
                    if mem['category'] == 'schedule' and mem.get('event_date'):
                        event_date_obj = mem['event_date']
                        event_date_str = event_date_obj.strftime('%A, %B %d, %Y') if hasattr(event_date_obj, 'strftime') else str(event_date_obj)
                        event_time_str = str(mem.get('event_time', 'all day'))
                        full_prompt += f"[{category_label}] {mem['content']} (Date: {event_date_str}, Time: {event_time_str})\n"
                    else:
                        full_prompt += f"[{category_label}] {mem['content']}\n"
                    logger.debug(f"Adding memory to prompt: [{category_label}] {mem['content']}")
                full_prompt += "\nUse this information to answer questions. If asked about schedules, tasks, or facts, refer to the saved information above.\n\n"

            # Get short-term memory (current session)
            short_term_memory = []
            if session_id:
                short_term_memory = self.get_conversation_history(session_id=session_id, limit=short_term_limit)

            # Get long-term memory (semantically similar past conversations)
            long_term_memory = []
            if user_name and session_id:
                long_term_memory = self.get_semantic_context(
                    current_message, user_name, session_id, limit=long_term_limit
                )

            # Add long-term memory context (if available)
            if long_term_memory:
                full_prompt += "BACKGROUND CONTEXT (for understanding only - DO NOT bring up these old topics unless directly asked):\n"
                for mem in long_term_memory:
                    role_label = "User" if mem['role'] == 'user' else "You"
                    full_prompt += f"{role_label}: {mem['message']}\n"
                full_prompt += "\nREMEMBER: This background context is ONLY for understanding the user better. Focus on their CURRENT message, NOT old topics.\n\n"

            # Add short-term memory (current conversation)
            if short_term_memory:
                full_prompt += "Current conversation:\n"
                for role, message, msg_type, timestamp in short_term_memory:
                    if role == 'user':
                        full_prompt += f"User: {message}\n"
                    else:
                        full_prompt += f"You: {message}\n"
                full_prompt += "\n"

            # Add current message
            full_prompt += f"User: {current_message}\nYou:"

            return full_prompt

        except Exception as e:
            logger.error(f"Error building prompt with context: {e}")
            # Fallback to just the current message if there's an error
            return current_message

    def transcribe_wav_file(self, wav_path):
        try:
            # Get language setting from database
            language = self.get_config('whisper_language', 'auto')

            with open(wav_path, 'rb') as f:
                resp = requests.post(
                    f"{self.whisper_url}/transcribe",
                    files={'audio': f},
                    data={'language': language},
                    timeout=60
                )
            if resp.status_code == 200:
                return resp.json().get('text', '').strip()
            logger.error(f"Whisper error: {resp.text}")
            return ''
        except Exception as e:
            logger.error(f"Transcription request failed: {e}")
            return ''

    def ollama_generate(self, message, user_name=None, session_id=None):
        try:
            # Get Ollama configuration from database (same as mumble-bot)
            ollama_url = self.get_config('ollama_url', config.DEFAULT_OLLAMA_URL)
            ollama_model = self.get_config('ollama_model', config.DEFAULT_OLLAMA_MODEL)
            logger.info(f"Using Ollama: {ollama_url} with model: {ollama_model}")

            prompt = self.build_prompt_with_context(message, user_name, session_id)
            resp = requests.post(
                f"{ollama_url}/api/generate",
                json={
                    "model": ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.7,  # Lower temperature for more consistent, focused responses
                        "top_p": 0.9,  # Nucleus sampling for better quality
                        "num_predict": 100,  # Limit response length (roughly 1-2 sentences)
                        "stop": ["\n\n", "User:", "Assistant:"]  # Stop at conversation breaks
                    }
                },
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
            # Get TTS engine configuration from database (same as mumble-bot)
            tts_engine = self.get_config('tts_engine', 'piper')

            if tts_engine == 'silero':
                # Use Silero TTS
                logger.info("Using Silero TTS engine")
                resp = requests.post(f"{self.silero_url}/synthesize", json={'text': text}, timeout=60)
            else:
                # Use Piper TTS (default)
                voice_config = self.get_config('piper_voice', 'en_US-lessac-medium')
                logger.info(f"Using Piper TTS engine with voice: {voice_config}")
                resp = requests.post(f"{self.piper_url}/synthesize", json={'text': text}, timeout=60)

            if resp.status_code == 200:
                return io.BytesIO(resp.content)
            logger.error(f"TTS error ({tts_engine}): {resp.text}")
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

    def __init__(self, sip_call, pipeline=None):
        self.sip_call = sip_call
        self.active = False
        self.rtp_thread = None
        self.pipeline = pipeline if pipeline else AIPipeline()
        # Voice activity detection on 8kHz PCM
        # Check if manual override is set via config
        if config.VOICE_THRESHOLD > 0:
            self.voice_threshold = config.VOICE_THRESHOLD
            self.adaptive_threshold = False  # Manual override disables adaptive calibration
            logger.info(f"Using manual voice threshold: {self.voice_threshold}")
        else:
            self.voice_threshold = 100  # Initial threshold before calibration
            self.adaptive_threshold = True  # Enable adaptive calibration
            logger.info("Using adaptive voice threshold calibration")
        
        self.silence_threshold = config.SILENCE_THRESHOLD
        self.recording = False
        self.last_audio_time = None
        self.audio_buffer_8k = []  # list of 16-bit PCM @8kHz
        self.processing = False
        # RMS monitoring for debugging
        self.rms_samples = []
        self.max_rms = 0
        # Adaptive threshold for cellular/low-volume audio
        self.baseline_rms_samples = []  # Collect baseline noise floor
        self.baseline_collection_time = 3.0  # seconds to collect baseline
        self.baseline_collected = False if self.adaptive_threshold else True
        # Identify caller
        self.caller_name = self._extract_caller_name()
        self.user_session = 0
        # Audio muting during TTS playback to prevent feedback loop
        # Start muted to prevent processing audio during welcome message
        self.muted = True
        self.mute_lock = threading.Lock()

    def start(self):
        """Start the call session"""
        try:
            logger.info(f"Starting call session with {self.sip_call.caller_addr}")

            self.active = True

            # Start RTP receive thread first (starts muted to prevent feedback during welcome)
            self.rtp_thread = threading.Thread(target=self._rtp_receive_loop, daemon=True)
            self.rtp_thread.start()

            # Small delay to ensure RTP loop is running
            time.sleep(0.2)

            # Play welcome message (will handle mute/unmute)
            self._play_welcome_message()

            # Clear any accumulated audio buffer from acoustic echo and reset baseline
            with self.mute_lock:
                self.audio_buffer_8k = []
                self.recording = False
                self.last_audio_time = None
                # Reset adaptive threshold calibration to start fresh after welcome message
                self.baseline_rms_samples = []
                self.baseline_collected = False

            logger.info("Call session active, ready for user input. Adaptive threshold calibration will begin.")
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
                
                # Extract payload type from header
                payload_type = header[1] & 0x7F  # Lower 7 bits

                packet_count += 1
                if packet_count % 100 == 1:  # Log every 100th packet
                    logger.debug(f"Received RTP packet {packet_count}, payload type: {payload_type}, payload size: {len(payload)} bytes")

                # μ-law (8-bit) -> 16-bit PCM @8kHz
                try:
                    pcm_8k = audioop.ulaw2lin(payload, 1)

                    # Check if we're muted (bot is speaking) - discard incoming audio to prevent feedback
                    with self.mute_lock:
                        is_muted = self.muted

                    if is_muted:
                        # Bot is speaking, discard incoming audio to prevent echo/feedback
                        # Still track RMS for debugging but don't record
                        rms = audioop.rms(pcm_8k, 2)
                        self.rms_samples.append(rms)
                        if packet_count % 200 == 1:
                            avg_rms = sum(self.rms_samples[-200:]) / min(len(self.rms_samples), 200)
                            logger.debug(f"Audio muted (bot speaking) - RMS: {rms}, Avg: {avg_rms:.1f}")
                        continue  # Skip processing this audio

                    # Voice activity detection
                    rms = audioop.rms(pcm_8k, 2)

                    # Track RMS statistics
                    self.rms_samples.append(rms)
                    if rms > self.max_rms:
                        self.max_rms = rms

                    # Adaptive threshold: collect baseline noise floor during first few seconds
                    if self.adaptive_threshold and not self.baseline_collected:
                        self.baseline_rms_samples.append(rms)
                        # After collecting baseline, calculate adaptive threshold
                        if len(self.baseline_rms_samples) >= int(self.baseline_collection_time * 50):  # 50 packets/sec
                            # Calculate noise floor statistics
                            sorted_baseline = sorted(self.baseline_rms_samples)
                            noise_floor = sorted_baseline[len(sorted_baseline) // 2]  # Median
                            
                            # Calculate 75th percentile (peak background noise)
                            percentile_75_idx = int(len(sorted_baseline) * 0.75)
                            peak_noise = sorted_baseline[percentile_75_idx]
                            
                            # For cellular/low-volume audio: set threshold between noise floor and peak
                            # This is more sensitive than 3x multiplier
                            # Use: noise_floor + (peak_noise - noise_floor) * 1.5
                            # With minimum of 40 and maximum of 300
                            adaptive_value = noise_floor + int((peak_noise - noise_floor) * 1.5)
                            self.voice_threshold = max(40, min(300, adaptive_value))
                            self.baseline_collected = True
                            logger.info(f"Adaptive threshold calibrated: noise_floor={noise_floor}, peak_noise={peak_noise}, new_threshold={self.voice_threshold}")

                    # Log RMS levels more frequently for debugging cellular issues
                    if packet_count % 50 == 1:  # Log every 50 packets instead of 200
                        avg_rms = sum(self.rms_samples[-200:]) / min(len(self.rms_samples), 200)
                        calibration_status = "CALIBRATING" if (self.adaptive_threshold and not self.baseline_collected) else "ACTIVE"
                        logger.info(f"Audio stats [{calibration_status}] - Current RMS: {rms}, Avg RMS: {avg_rms:.1f}, Max RMS: {self.max_rms}, Threshold: {self.voice_threshold}")
                        # Log last 10 RMS values for pattern analysis
                        recent_rms = self.rms_samples[-10:] if len(self.rms_samples) >= 10 else self.rms_samples
                        logger.info(f"Recent RMS values: {recent_rms}")

                    if rms > self.voice_threshold:
                        self.audio_buffer_8k.append(pcm_8k)
                        self.last_audio_time = time.time()
                        if not self.recording:
                            self.recording = True
                            logger.info(f"Started recording from caller (RMS: {rms}, threshold: {self.voice_threshold})")
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

    def _play_tts(self, wav_bytes, description="audio"):
        """Play TTS audio while muting incoming audio to prevent feedback"""
        if not wav_bytes:
            logger.warning(f"No audio to play for {description}")
            return

        try:
            # Mute incoming audio to prevent feedback loop
            with self.mute_lock:
                self.muted = True
            logger.debug(f"Muted incoming audio for {description} playback")

            # Play the audio
            self.pipeline.play_tts_over_rtp(self.sip_call, wav_bytes)

            # Add delay after playback to allow acoustic echo to settle
            # Longer delay for welcome message to ensure echo fully dissipates
            if "welcome" in description.lower():
                delay = 1.0  # 1 second for welcome message
            else:
                delay = 0.5  # 500ms for other audio

            logger.debug(f"Waiting {delay}s for acoustic echo to settle")
            time.sleep(delay)

        finally:
            # Clear any audio buffer that accumulated during playback (acoustic echo)
            with self.mute_lock:
                if self.audio_buffer_8k:
                    logger.debug(f"Clearing {len(self.audio_buffer_8k)} buffered audio chunks from feedback")
                    self.audio_buffer_8k = []
                    self.recording = False
                    self.last_audio_time = None
                # Unmute incoming audio
                self.muted = False
            logger.debug(f"Unmuted incoming audio after {description} playback")

    def _process_utterance(self, chunks_8k):
        try:
            logger.info(f"Silence detected, processing and transcribing audio ({len(chunks_8k)} chunks)...")

            if not chunks_8k:
                logger.warning("No audio chunks to process")
                self.processing = False
                return

            # Combine all 8kHz chunks
            combined_8k = b''.join(chunks_8k)
            duration_8k = len(combined_8k) / 2 / 8000  # 16-bit samples at 8kHz
            logger.info(f"Processing {duration_8k:.2f} seconds of audio ({len(combined_8k)} bytes @ 8kHz)")

            # Check if we have enough audio
            if duration_8k < 0.3:  # Less than 300ms
                logger.warning(f"Audio too short ({duration_8k:.2f}s), skipping transcription")
                self.processing = False
                return

            # Upsample from 8kHz to 16kHz for better Whisper accuracy
            logger.debug(f"Upsampling audio from 8kHz to 16kHz")
            combined_16k, _ = audioop.ratecv(combined_8k, 2, 1, 8000, 16000, None)

            # Apply audio normalization to improve quality
            # Find peak amplitude
            max_amp = audioop.max(combined_16k, 2)
            avg_amp = audioop.rms(combined_16k, 2)
            logger.info(f"Audio levels - Peak: {max_amp}, RMS: {avg_amp}")

            # Check if audio has sufficient energy to be real speech
            # Whisper often hallucinates "Thank you" or similar on silence/noise
            if avg_amp < 50:  # Very low RMS indicates silence or noise, not speech
                logger.warning(f"Audio RMS too low ({avg_amp}), likely silence/noise. Skipping transcription to avoid Whisper hallucination.")
                self.processing = False
                return

            if max_amp > 0:
                # Normalize to 90% of maximum to avoid clipping while maximizing signal
                target_amp = int(32767 * 0.9)
                factor = target_amp / max_amp
                combined_16k = audioop.mul(combined_16k, 2, factor)
                logger.info(f"Normalized audio by factor {factor:.2f}")

            # Write enhanced 16kHz PCM to WAV
            with tempfile_named(suffix='.wav') as wav_path:
                with wave.open(wav_path, 'wb') as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(16000)  # 16kHz for better Whisper performance
                    w.writeframes(combined_16k)

                logger.info("Sending audio to Whisper for transcription...")
                # Transcribe
                transcript = self.pipeline.transcribe_wav_file(wav_path)

            if not transcript:
                logger.info("Transcript empty; skipping LLM/TTS")
                self.processing = False
                return

            # Filter out common Whisper hallucinations (phrases it generates from silence/noise)
            hallucinations = [
                "thank you", "thank you.", "thanks", "thanks.",
                "bye", "bye.", "goodbye", "goodbye.",
                "thank you for watching", "thank you for watching.",
                "you", "you."
            ]
            if transcript.strip().lower() in hallucinations:
                logger.warning(f"Detected Whisper hallucination: '{transcript}' - skipping (likely silence/acoustic echo)")
                self.processing = False
                return

            logger.info(f"Transcribed: {transcript}")

            # Get or create session for this user
            session_id = self.pipeline.get_or_create_session(self.caller_name, self.user_session)

            # Save user message SYNCHRONOUSLY first so it's in the context for immediate follow-ups
            self.pipeline.save_message(self.caller_name, self.user_session, 'voice', 'user', transcript, session_id)

            # Cue: "Let me think about that..." before LLM
            logger.info("Playing thinking cue...")
            thinking_cue = self.pipeline.tts_wav("Let me think about that...")
            self._play_tts(thinking_cue, "thinking cue")

            # LLM with session context (now with user message in DB)
            response_text = self.pipeline.ollama_generate(transcript, user_name=self.caller_name, session_id=session_id)
            logger.info(f"Ollama response: {response_text}")

            # Save assistant response asynchronously (not needed for immediate context)
            self.pipeline.save_message(self.caller_name, self.user_session, 'voice', 'assistant', response_text, session_id=session_id)

            # Extract and save memories in background (non-blocking)
            threading.Thread(
                target=self.pipeline.extract_and_save_memory,
                args=(transcript, response_text, self.caller_name, session_id),
                daemon=True
            ).start()

            # Extract and manage schedule in background (non-blocking)
            threading.Thread(
                target=self.pipeline.extract_and_manage_schedule,
                args=(transcript, response_text, self.caller_name),
                daemon=True
            ).start()

            # Cue 3: "Here's my response..." before final response
            logger.info("Playing response cue...")
            response_cue = self.pipeline.tts_wav("Here's my response...")
            self._play_tts(response_cue, "response cue")

            # TTS
            wav_bytes = self.pipeline.tts_wav(response_text)

            # Play over RTP
            self._play_tts(wav_bytes, "response")

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

    def _play_welcome_message(self):
        """Generate and play a personalized welcome message using persona and Ollama"""
        try:
            logger.info("Generating welcome message...")

            # Generate welcome message using persona and Ollama
            welcome_text = self._generate_welcome_message()

            if welcome_text:
                logger.info(f"Playing welcome message: {welcome_text}")

                # Convert to speech and play over RTP
                wav_bytes = self.pipeline.tts_wav(welcome_text)
                if wav_bytes:
                    self._play_tts(wav_bytes, "welcome message")
                    logger.info("Welcome message played successfully")
                else:
                    logger.error("Failed to generate TTS for welcome message")
            else:
                logger.warning("No welcome message generated, using default")
                # Fallback to a simple default message
                default_welcome = "Hello! I'm your AI assistant. How can I help you today?"
                wav_bytes = self.pipeline.tts_wav(default_welcome)
                if wav_bytes:
                    self._play_tts(wav_bytes, "default welcome message")

        except Exception as e:
            logger.error(f"Error playing welcome message: {e}")
            # Don't fail the call if welcome message fails
            pass

    def _generate_welcome_message(self):
        """Generate a personalized welcome message using persona and Ollama"""
        try:
            # Get bot persona from config
            persona = self.pipeline.get_config('bot_persona', '')
            
            # Build a prompt specifically for welcome message generation
            welcome_prompt = self._build_welcome_prompt(persona)
            
            # Get Ollama configuration
            ollama_url = self.pipeline.get_config('ollama_url', config.DEFAULT_OLLAMA_URL)
            ollama_model = self.pipeline.get_config('ollama_model', config.DEFAULT_OLLAMA_MODEL)
            
            logger.info(f"Generating welcome message using Ollama: {ollama_url} with model: {ollama_model}")
            
            # Call Ollama to generate welcome message
            response = requests.post(
                f"{ollama_url}/api/generate",
                json={"model": ollama_model, "prompt": welcome_prompt, "stream": False},
                timeout=30,  # Shorter timeout for welcome message
            )
            
            if response.status_code == 200:
                welcome_text = response.json().get('response', '').strip()
                if welcome_text:
                    # Clean up the response (remove any assistant prefix if present)
                    welcome_text = welcome_text.replace('Assistant:', '').strip()
                    return welcome_text
                else:
                    logger.warning("Ollama returned empty response for welcome message")
                    return None
            else:
                logger.error(f"Ollama error generating welcome message: {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error generating welcome message: {e}")
            return None

    def _build_welcome_prompt(self, persona):
        """Build a prompt specifically for generating welcome messages"""
        prompt = "Generate a brief, friendly welcome message for when someone calls you. "
        prompt += "Keep it conversational and welcoming (1-2 sentences). "
        prompt += "Never use emojis. "
        
        if persona and persona.strip():
            prompt += f"Use this persona: {persona.strip()}\n\n"
        else:
            prompt += "\n\n"
            
        prompt += "Generate a welcome message for an incoming phone call:"
        
        return prompt


class SIPMumbleBridge:
    """Main SIP-Mumble bridge application"""

    def __init__(self):
        self.sip_server = SimpleSIPServer(port=config.SIP_PORT)
        self.active_calls = {}
        # Create shared pipeline for session management
        self.pipeline = AIPipeline()

    def _session_cleanup_thread(self):
        """Background thread for session cleanup"""
        while True:
            try:
                time.sleep(300)  # Run every 5 minutes
                logger.info("Running periodic session cleanup...")
                self.pipeline.close_idle_sessions()
            except Exception as e:
                logger.error(f"Error in session cleanup thread: {e}")

    def start(self):
        """Start the bridge"""
        logger.info("=" * 60)
        logger.info("SIP-Mumble Bridge Starting")
        logger.info("=" * 60)
        logger.info(f"SIP Port: {config.SIP_PORT}")
        logger.info(f"Mumble Server: {config.MUMBLE_HOST}:{config.MUMBLE_PORT}")
        logger.info("=" * 60)

        # Start session cleanup thread
        cleanup_thread = threading.Thread(target=self._session_cleanup_thread, daemon=True)
        cleanup_thread.start()
        logger.info("Session cleanup thread started")

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

            # Create call session with shared pipeline
            session = CallSession(sip_call, pipeline=self.pipeline)

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
