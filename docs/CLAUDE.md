# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Mumble-AI is a multi-service Docker-based AI voice assistant system for Mumble VoIP servers. It provides real-time speech recognition, AI-powered conversation with memory, text-to-speech synthesis, and multiple access methods including traditional Mumble clients, web interfaces, and SIP phone integration.

## Common Development Commands

### Docker Operations
```bash
# Start all services
docker-compose up -d

# Build all services
docker-compose build

# Build specific service without cache
docker-compose build --no-cache mumble-bot

# View logs for all services
docker-compose logs -f

# View logs for specific service
docker-compose logs -f mumble-bot

# Stop all services
docker-compose down

# Stop and remove all data (WARNING: destructive)
docker-compose down -v

# Restart specific service
docker-compose restart mumble-bot

# Check service status
docker-compose ps
```

### Testing and Debugging
```bash
# Test Whisper service
curl -X POST http://localhost:5000/transcribe -F "audio=@test.wav"

# Test Piper TTS service
curl -X POST http://localhost:5001/synthesize -d '{"text":"Hello world","voice":"en_US-lessac-medium"}'

# Test Ollama connection
curl http://localhost:11434/api/generate -d '{"model":"llama2","prompt":"Hello"}'

# Check database connection
docker exec mumble-ai-postgres psql -U mumbleai mumble_ai -c "SELECT * FROM bot_config;"

# View conversation history
docker exec mumble-ai-postgres psql -U mumbleai mumble_ai -c "SELECT * FROM conversation_history ORDER BY timestamp DESC LIMIT 10;"

# Inspect container
docker exec -it mumble-bot bash

# Monitor resource usage
docker stats
```

### Web Client Development
```bash
# Build mumble-web-simple
cd mumble-web-simple
npm run build

# Build in development mode
npm run build:dev

# Force rebuild
npm run build:force

# Run tests
npm run test
```

## Architecture

### Service Communication Flow

**Voice Message (Mumble → AI Bot → Response):**
1. User speaks in Mumble client
2. Mumble Server → AI Bot (audio stream)
3. AI Bot buffers audio until 1.5s silence
4. AI Bot → Faster Whisper (PCM audio)
5. Whisper → AI Bot (transcribed text)
6. AI Bot saves to PostgreSQL
7. AI Bot retrieves conversation history + persona from database
8. AI Bot → Ollama (prompt with context)
9. Ollama → AI Bot (generated response)
10. AI Bot saves response to database
11. AI Bot → Piper TTS (response text + voice selection)
12. Piper → AI Bot (WAV audio, 22050Hz)
13. AI Bot resamples to 48kHz using FFmpeg
14. AI Bot → Mumble Server → User

**SIP Phone Integration:**
- SIP Bridge generates personalized welcome message using bot persona and Ollama
- Converts RTP audio ↔ Mumble audio format
- Integrates full AI pipeline (Whisper → Ollama → Piper)

**Text Message:**
- Skips audio processing steps (Whisper and Piper)
- Goes directly: User → AI Bot → Database → Ollama → Database → User

### Service Dependencies

```
mumble-server (port 64738)
├── mumble-bot (depends on mumble-server, postgres, whisper, piper)
│   ├── faster-whisper (port 5000)
│   ├── piper-tts (port 5001, depends on postgres)
│   ├── postgres (port 5432, internal)
│   └── ollama (external: host.docker.internal:11434)
├── sip-mumble-bridge (port 5060, 10000-10010)
│   └── depends on mumble-server, whisper, piper, postgres, ollama
├── mumble-web (port 8081)
└── web-control-panel (port 5002, depends on postgres)

tts-web-interface (port 5003, standalone)
└── depends on piper-tts
```

### Database Schema

**conversation_history table:**
- `id` (SERIAL): Primary key
- `user_name` (VARCHAR): Mumble username
- `user_session` (INTEGER): Session identifier
- `message_type` (VARCHAR): 'voice' or 'text'
- `role` (VARCHAR): 'user' or 'assistant'
- `message` (TEXT): Message content
- `timestamp` (TIMESTAMP): Message time

**bot_config table:**
- `key` (VARCHAR): Configuration key (PK)
- `value` (TEXT): Configuration value
- `updated_at` (TIMESTAMP): Last modification time

**Config keys:** `ollama_url`, `ollama_model`, `piper_voice`, `bot_persona`

## Key Implementation Details

### Audio Processing Requirements

**Critical: Mumble requires 48kHz PCM audio**
- Whisper receives: 48kHz mono 16-bit PCM
- Piper outputs: 22050Hz mono WAV
- Bot resamples Piper output to 48kHz using FFmpeg before sending to Mumble
- Failure to resample causes "chipmunk voice" effect

### Retry and Circuit Breaker Pattern

The AI bot (`mumble-bot/bot.py`) implements:
- **Retry with exponential backoff**: Configurable via env vars
  - `RETRY_MAX_ATTEMPTS` (default: 3)
  - `RETRY_BASE_DELAY` (default: 1.0s)
  - `RETRY_MAX_DELAY` (default: 60.0s)
- **Circuit breakers** for each external service:
  - `WHISPER_CIRCUIT_THRESHOLD`, `WHISPER_CIRCUIT_TIMEOUT`
  - `PIPER_CIRCUIT_THRESHOLD`, `PIPER_CIRCUIT_TIMEOUT`
  - `OLLAMA_CIRCUIT_THRESHOLD`, `OLLAMA_CIRCUIT_TIMEOUT`
  - `DB_CIRCUIT_THRESHOLD`, `DB_CIRCUIT_TIMEOUT`

### Service Health Monitoring

All Python services provide health endpoints:
- Whisper: `GET http://localhost:5000/health`
- Piper: `GET http://localhost:5001/health`
- Web Control Panel: `GET http://localhost:5002/health`
- Mumble Bot: `GET http://localhost:8082/health`

PostgreSQL uses `pg_isready` for health checks.

### Configuration Management

Configuration is stored in PostgreSQL `bot_config` table and can be modified via:
1. Web Control Panel at `http://localhost:5002`
2. Direct database updates
3. Environment variables (initial values only)

The bot reads configuration from database on each message, so changes take effect immediately.

## Important File Locations

### Core Services
- **AI Bot**: `mumble-bot/bot.py` - Main orchestration logic, Mumble client, audio processing
- **Faster Whisper**: `faster-whisper-service/app.py` - Flask API for speech-to-text
- **Piper TTS**: `piper-tts-service/app.py` - Flask API for text-to-speech
- **Web Control Panel**: `web-control-panel/app.py` - Flask admin interface
- **SIP Bridge**: `sip-mumble-bridge/bridge.py` - SIP/RTP to Mumble bridge
- **TTS Web Interface**: `tts-web-interface/app.py` - Standalone voice generator

### Configuration
- **Docker Compose**: `docker-compose.yml` - Service orchestration
- **Database Schema**: `init-db.sql` - PostgreSQL initialization
- **Mumble Config**: `mumble-config.ini` - Mumble server settings
- **Environment**: `.env` - Environment variables (create from `.env.example`)

### Web Clients
- **Mumble Web Simple**: `mumble-web-simple/` - Build-only simplified client
  - Entry: `app/index.js`, `app/worker.js`
  - Build: `smart-build.sh`, `webpack.config.js`
- **Mumble Web**: Uses `rankenstein/mumble-web:latest` Docker image

### Documentation
- **Architecture**: `docs/ARCHITECTURE.md` - System design details
- **Configuration**: `docs/CONFIGURATION.md` - Comprehensive config guide
- **API Reference**: `docs/API.md` - API documentation
- **Troubleshooting**: `docs/TROUBLESHOOTING.md` - Common issues

## Modifying Services

### Adding a New TTS Voice

1. Find voice at https://github.com/rhasspy/piper/releases
2. Edit `web-control-panel/download_voices.py`
3. Add to `VOICES` list: `("voice-name", "url-to-onnx-file", "url-to-json-config")`
4. Rebuild: `docker-compose build web-control-panel`
5. Restart: `docker-compose restart web-control-panel`

### Changing Whisper Model

Edit `.env`:
```bash
WHISPER_MODEL=small  # Options: tiny, base, small, medium, large
```
Restart: `docker-compose restart faster-whisper`

### Updating Bot Persona

Via web panel:
1. Navigate to `http://localhost:5002`
2. Scroll to "Bot Persona"
3. Enter description and click "AI Enhance" (optional)
4. Click "Save Persona"

Via database:
```bash
docker exec mumble-ai-postgres psql -U mumbleai mumble_ai -c "UPDATE bot_config SET value = 'Your persona here' WHERE key = 'bot_persona';"
```

### Modifying Silence Detection Threshold

Edit `mumble-bot/bot.py`:
```python
self.silence_threshold = 1.5  # Change to desired seconds
```
Rebuild: `docker-compose build mumble-bot`

### Changing Conversation History Limit

Edit `mumble-bot/bot.py`, search for `get_conversation_history` call:
```python
history = self.get_conversation_history(user_name=user_name, limit=10)  # Adjust limit
```

## External Dependencies

### Ollama (Required)

Ollama must be running on the host machine (not in Docker):

```bash
# Start Ollama
ollama serve

# Pull a model
ollama pull llama3.2

# List available models
ollama list
```

The bot connects via `host.docker.internal:11434` (configured in `OLLAMA_URL` env var).

### FFmpeg

Used by `mumble-bot` for audio resampling. Included in bot's Docker image.

## Common Patterns

### Adding New Database Configuration

1. Update `init-db.sql` to add default value:
```sql
INSERT INTO bot_config (key, value) VALUES ('new_key', 'default_value');
```

2. Add to web control panel UI in `web-control-panel/templates/index.html`

3. Add API endpoint in `web-control-panel/app.py`

4. Use in bot via `get_config()` method in `mumble-bot/bot.py`

### Creating a New Service

1. Create directory with `Dockerfile`, `requirements.txt`, and Python app
2. Add service to `docker-compose.yml` with appropriate ports and dependencies
3. Add to `mumble-ai-network` network
4. If using database, add dependency: `depends_on: postgres: condition: service_healthy`
5. Add health check endpoint for monitoring

### Debugging Service Communication

1. Check logs: `docker-compose logs -f <service-name>`
2. Verify network connectivity: `docker exec <service> ping <other-service>`
3. Test HTTP endpoints: `curl http://localhost:<port>/health`
4. Check environment variables: `docker exec <service> env`

## Security Considerations

- **Default setup is for trusted local networks** - no authentication by default
- **Production use requires**:
  - Reverse proxy with authentication (nginx with basic auth)
  - HTTPS/TLS termination
  - Secrets management (Docker secrets instead of `.env`)
  - Firewall rules restricting port access
  - Rate limiting on public endpoints
  - Input validation on all services

## Performance Tuning

### Whisper Model Selection
- `tiny`: ~1GB RAM, fastest, lowest accuracy
- `base`: ~1GB RAM, fast, good accuracy (default)
- `small`: ~2GB RAM, medium speed, better accuracy
- `medium`: ~5GB RAM, slow, high accuracy
- `large`: ~10GB RAM, slowest, best accuracy

### Ollama Model Selection
- Smaller models (1B-3B params): Faster, less accurate
- Medium models (7B-13B params): Balanced
- Large models (30B+ params): Slower, more accurate

### GPU Acceleration

For Whisper, edit `docker-compose.yml`:
```yaml
faster-whisper:
  environment:
    - DEVICE=cuda
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
```

## Accessing the System

- **Web Control Panel**: http://localhost:5002
- **Mumble Web Client**: http://localhost:8081
- **TTS Voice Generator**: http://localhost:5003
- **Mumble Server**: localhost:64738 (via Mumble desktop/mobile client)
- **SIP Bridge**: localhost:5060 (via SIP phone/softphone)
