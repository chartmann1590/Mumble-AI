# Architecture

System design and component interaction documentation.

## Overview

Mumble AI Bot is a microservices-based voice AI system built on Docker. It consists of 9 primary services that work together to provide voice and text interaction through multiple access methods including Mumble VoIP, web clients, and SIP phone integration.

## Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            User Access Layer                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐ │
│  │Mumble Client │  │ Web Clients  │  │ SIP Phones   │  │ Web Browser     │ │
│  │(Desktop/Mobile│  │(Port 8081)   │  │(Port 5060)  │  │(Control Panel)  │ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └────────┬────────┘ │
└─────────┼──────────────────┼──────────────────┼───────────────────┼─────────┘
          │                  │                  │                   │
┌─────────▼──────────────────▼──────────────────▼───────────────────▼─────────┐
│                        Application Layer                                      │
│  ┌──────────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐  │
│  │  Mumble Server   │  │ SIP Bridge   │  │ Web Control  │  │ Mumble Web  │  │
│  │   (Port 64738)   │  │(Port 5060)   │  │   Panel      │  │  Client     │  │
│  └─────────┬────────┘  └──────┬───────┘  │(Port 5002)   │  │(Port 8081)  │  │
│            │                  │          └──────────────┘  └─────────────┘  │
│       ┌────▼──────┐           │                                            │
│       │  AI Bot   │           │                                            │
│       └─┬───┬───┬─┘           │                                            │
└─────────┼───┼───┼─────────────┼────────────────────────────────────────────┘
          │   │   │             │
┌─────────▼───▼───▼─────────────▼────────────────────────────────────────────┐
│                            Service Layer                                    │
│  ┌──────────┐  ┌────────┐  ┌─────────┐  ┌──────────────┐  ┌─────────────┐  │
│  │ Faster   │  │ Piper  │  │ Ollama  │  │  PostgreSQL  │  │ Mumble Web  │  │
│  │ Whisper  │  │  TTS   │  │(External│  │              │  │   Simple    │  │
│  │(Port5000)│  │(5001)  │  │ :11434) │  │  (Internal)  │  │(Build Only) │  │
│  └──────────┘  └────────┘  └─────────┘  └──────────────┘  └─────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Data Flow

### Voice Message Flow (Mumble Client)

1. User speaks in Mumble client
2. Mumble Server transmits audio to AI Bot
3. AI Bot buffers audio until 1.5s silence
4. Audio (PCM) sent to Faster Whisper service
5. Whisper returns transcribed text
6. Bot saves user message to PostgreSQL
7. Bot retrieves conversation history from database
8. Bot gets persona configuration from database
9. Bot builds context-aware prompt
10. Prompt sent to Ollama
11. Ollama returns generated response
12. Bot saves assistant response to database
13. Response text sent to Piper TTS
14. Piper returns synthesized audio (WAV)
15. Bot resamples audio to 48kHz
16. Audio sent back through Mumble Server
17. User hears AI response

### Voice Message Flow (Web Client)

1. User speaks in web browser
2. WebRTC audio sent to Mumble Server
3. Mumble Server transmits audio to AI Bot
4. Steps 3-16 same as Mumble client flow
5. Audio sent back through Mumble Server to web client
6. User hears AI response in browser

### Voice Message Flow (SIP Phone)

1. User calls SIP bridge from phone
2. SIP bridge auto-answers call
3. **Welcome message generated using bot persona and Ollama**
4. **Welcome message converted to speech via TTS**
5. **Welcome message played to caller over RTP**
6. SIP bridge connects to Mumble Server as client
7. Phone audio (RTP) converted to Mumble audio format
8. Audio sent to Mumble Server → AI Bot
9. Steps 4-15 same as Mumble client flow
10. Audio sent back through Mumble Server → SIP bridge
11. SIP bridge converts audio back to RTP format
12. User hears AI response on phone

### Text Message Flow

1. User types message in Mumble chat (any client)
2. Message sent to AI Bot via Mumble Server
3. Steps 6-12 same as voice flow
4. Bot sends text response to Mumble Server
5. User receives text message

### Web Control Panel Flow

1. User accesses control panel in browser
2. Frontend requests data via REST API
3. Backend queries PostgreSQL for current config
4. Config displayed in UI
5. User makes changes
6. Frontend POSTs to API
7. Backend updates database
8. Bot picks up changes on next message

## Services

### 1. Mumble Server

- **Image:** `mumblevoip/mumble-server:latest`
- **Purpose:** VoIP communication hub
- **Ports:** 64738 (TCP/UDP)
- **Dependencies:** None
- **Data:** Persistent volume for server state

### 2. AI Bot

- **Image:** Custom (Python 3.11)
- **Purpose:** Core orchestration and Mumble client
- **Dependencies:** Whisper, Piper, PostgreSQL, Ollama
- **Features:**
  - Audio buffering and silence detection
  - Dual-mode communication (voice/text)
  - Context-aware conversation
  - Database interaction

### 3. Faster Whisper

- **Image:** Custom (Python 3.11)
- **Purpose:** Speech-to-text transcription
- **Port:** 5000
- **Model:** Configurable (tiny/base/small/medium/large)
- **API:** POST /transcribe, GET /health

### 4. Piper TTS

- **Image:** Custom (Python 3.11)
- **Purpose:** Text-to-speech synthesis
- **Port:** 5001
- **Voices:** 31 pre-loaded models
- **API:** POST /synthesize, GET /health

### 5. PostgreSQL

- **Image:** postgres:16-alpine
- **Purpose:** Persistent data storage
- **Port:** 5432 (internal only)
- **Data:**
  - Conversation history
  - Bot configuration
  - User statistics

### 6. Web Control Panel

- **Image:** Custom (Python 3.11 + Flask)
- **Purpose:** Management interface
- **Port:** 5002
- **Features:**
  - Real-time statistics
  - Model/voice selection
  - Persona management
  - History viewing

### 7. SIP Bridge

- **Image:** Custom (Python 3.11)
- **Purpose:** SIP/RTP to Mumble integration
- **Ports:** 5060 (UDP/TCP), 10000-10010 (UDP)
- **Dependencies:** Mumble Server, Whisper, Piper, PostgreSQL, Ollama
- **Features:**
  - Auto-answer SIP calls
  - **Personalized welcome messages using bot persona and Ollama**
  - RTP audio conversion
  - Mumble client connection
  - AI pipeline integration

### 8. Mumble Web

- **Image:** `rankenstein/mumble-web:latest`
- **Purpose:** Web-based Mumble client
- **Port:** 8081
- **Features:**
  - WebRTC audio connection
  - Text chat interface
  - Voice activity detection
  - Modern responsive UI

### 9. Mumble Web Simple

- **Image:** Custom (Node.js build)
- **Purpose:** Simplified web client (build only)
- **Port:** N/A (build service)
- **Features:**
  - Lightweight web client
  - Customizable themes
  - Development-friendly

## Database Schema

### conversation_history

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| user_name | VARCHAR(255) | Mumble username |
| user_session | INTEGER | Session ID |
| message_type | VARCHAR(10) | 'voice' or 'text' |
| role | VARCHAR(20) | 'user' or 'assistant' |
| message | TEXT | Message content |
| timestamp | TIMESTAMP | When message occurred |

### bot_config

| Column | Type | Description |
|--------|------|-------------|
| key | VARCHAR(255) | Config key (PK) |
| value | TEXT | Config value |
| updated_at | TIMESTAMP | Last update |

**Config Keys:**
- `ollama_url` - Ollama server URL
- `ollama_model` - Active model name
- `piper_voice` - Active TTS voice
- `bot_persona` - Personality description

## Audio Processing

### Input Audio (Mumble → Whisper)
- Format: PCM 48kHz mono 16-bit
- Buffered in memory per user
- Converted to WAV for Whisper
- Transcription happens after silence threshold

### Output Audio (Piper → Mumble)
- Piper outputs: 22050Hz mono
- FFmpeg resamples to: 48000Hz mono 16-bit
- Format required by Mumble protocol
- Prevents chipmunk voice effect

## Security Considerations

- **No Authentication:** Default setup is for trusted local networks
- **Database Credentials:** Stored in .env file
- **Ollama Access:** Uses host network for local access
- **Web Panel:** No HTTPS by default

**Production Recommendations:**
- Add reverse proxy with auth
- Use secrets management
- Enable HTTPS
- Implement rate limiting
- Add input validation

## Scaling Considerations

Current architecture is single-instance. For scaling:

1. **Multiple Bots:** Deploy multiple bot instances
2. **Load Balancing:** Use nginx for Whisper/Piper
3. **Database:** Consider connection pooling tuning
4. **Ollama:** Deploy multiple Ollama instances
5. **Storage:** Use external volume for voices

## Network Architecture

```
mumble-ai-network (bridge)
├── mumble-server (64738)
├── faster-whisper (5000)
├── piper-tts (5001)
├── web-control-panel (5002)
├── sip-mumble-bridge (5060, 10000-10010)
├── mumble-web (8081)
├── postgres (5432 internal)
└── mumble-bot (client only)
```

External:
- Ollama: host.docker.internal:11434
- SIP Phones: localhost:5060
- Web Browsers: localhost:8081, localhost:5002

## Monitoring

**Health Checks:**
- PostgreSQL: pg_isready every 10s
- Whisper: GET /health
- Piper: GET /health

**Logs:**
- Centralized via docker-compose logs
- JSON structured logging
- Log levels: INFO, WARNING, ERROR

## Recovery

**Service Restart Policy:** unless-stopped

**Failure Scenarios:**
1. **Ollama Down:** Bot continues, returns error message
2. **Whisper Down:** Bot waits for service recovery
3. **Piper Down:** Bot waits for service recovery
4. **Database Down:** Services wait for recovery
5. **Mumble Down:** Bot reconnects automatically

## Future Enhancements

- WebSocket support for real-time updates
- Multi-channel support
- Voice activity detection improvements
- Caching layer for frequent queries
- Metrics and observability (Prometheus)
- Container health endpoints
