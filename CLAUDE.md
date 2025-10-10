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
mumble-server (port 48000 external, 64738 internal - changed to avoid Windows Hyper-V port conflicts)
├── mumble-bot (depends on mumble-server, postgres, whisper, piper, silero, chatterbox)
│   ├── faster-whisper (port 5000)
│   ├── piper-tts (port 5001, depends on postgres)
│   ├── silero-tts (port 5004, depends on postgres)
│   ├── chatterbox-tts (port 5005, depends on postgres)
│   ├── postgres (port 5432, internal, with pgvector extension)
│   └── ollama (external: host.docker.internal:11434)
├── sip-mumble-bridge (port 5060, 10000-10010)
│   └── depends on mumble-server, whisper, piper, silero, chatterbox, postgres, ollama
├── mumble-web (port 8081)
├── web-control-panel (port 5002, depends on postgres, tts-web-interface)
└── email-summary-service (depends on postgres, ollama)

tts-web-interface (port 5003, standalone)
└── depends on piper-tts, silero-tts, chatterbox-tts
```

### Database Schema

**conversation_history table:**
- `id` (SERIAL): Primary key
- `user_name` (VARCHAR): Mumble username
- `user_session` (INTEGER): Session identifier (deprecated, use session_id)
- `session_id` (VARCHAR): Unique session identifier
- `message_type` (VARCHAR): 'voice' or 'text'
- `role` (VARCHAR): 'user' or 'assistant'
- `message` (TEXT): Message content
- `timestamp` (TIMESTAMP): Message time
- `embedding` (VECTOR): Semantic search vector (pgvector extension)

**conversation_sessions table:**
- `id` (SERIAL): Primary key
- `user_name` (VARCHAR): Username
- `session_id` (VARCHAR): Unique session identifier
- `started_at` (TIMESTAMP): Session start time
- `last_activity` (TIMESTAMP): Last message timestamp
- `state` (VARCHAR): 'active', 'idle', or 'closed'
- `message_count` (INTEGER): Number of messages in session

**persistent_memories table:**
- `id` (SERIAL): Primary key
- `user_name` (VARCHAR): Username
- `category` (VARCHAR): 'schedule', 'fact', 'task', 'preference', 'reminder', 'other'
- `content` (TEXT): Memory content
- `extracted_at` (TIMESTAMP): Extraction time
- `importance` (INTEGER): 1-10 importance score
- `active` (BOOLEAN): Whether memory is active
- `event_date` (DATE): For schedule memories - exact date (YYYY-MM-DD)
- `event_time` (TIME): For schedule memories - exact time (HH:MM)

**email_settings table:**
- `id` (SERIAL): Primary key
- `smtp_host`, `smtp_port`, `smtp_username`, `smtp_password`: SMTP configuration
- `smtp_use_tls`, `smtp_use_ssl`: Security settings
- `from_email`, `recipient_email`: Email addresses
- `daily_summary_enabled` (BOOLEAN): Enable daily summaries
- `summary_time` (TIME): When to send daily summary
- `timezone` (VARCHAR): Timezone for scheduling
- `last_sent` (TIMESTAMP): Last email sent time

**schedule_events table:**
- `id` (SERIAL): Primary key
- `user_name` (VARCHAR): Username
- `title` (VARCHAR): Event title/description
- `event_date` (DATE): Event date
- `event_time` (TIME): Event time (optional, null for all-day)
- `description` (TEXT): Additional details
- `importance` (INTEGER): 1-10 importance score
- `active` (BOOLEAN): Whether event is active
- `created_at`, `updated_at` (TIMESTAMP): Timestamps

**bot_config table:**
- `key` (VARCHAR): Configuration key (PK)
- `value` (TEXT): Configuration value
- `updated_at` (TIMESTAMP): Last modification time

**Config keys:** `ollama_url`, `ollama_model`, `piper_voice`, `silero_voice`, `chatterbox_voice`, `tts_engine`, `bot_persona`, `session_timeout_minutes`, `session_reactivation_minutes`

## Key Implementation Details

### Audio Processing Requirements

**Critical: Mumble requires 48kHz PCM audio**
- Whisper receives: 48kHz mono 16-bit PCM
- Piper TTS outputs: 22050Hz mono WAV (resampled to 48kHz)
- Silero TTS outputs: 24000Hz mono WAV (resampled to 48kHz)
- Bot resamples TTS output to 48kHz using FFmpeg before sending to Mumble
- Failure to resample causes "chipmunk voice" effect

### Triple TTS Engine Support

The bot supports three TTS engines with voice selection stored in database:
- **Piper TTS**: 50+ voices, fast, neural TTS, lower memory usage
- **Silero TTS**: 20+ voices, high quality, more natural intonation
- **Chatterbox TTS**: Voice cloning with XTTS-v2, custom voices from audio samples
- Switch between engines via web control panel at `http://localhost:5002`
- Voice selection stored in `piper_voice`, `silero_voice`, or `chatterbox_voice` config keys
- **Voice preview**: All engines support audio preview directly in the web control panel
- **Voice cloning**: Use TTS Voice Generator at `http://localhost:5003` to clone new voices for Chatterbox

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

### Schedule and Memory Deduplication System

The bot implements a two-layer deduplication system to prevent duplicate calendar events and memories:

**Layer 1: Prompt Engineering**
- LLM prompts include CRITICAL INSTRUCTIONS distinguishing CREATE vs QUERY operations
- Explicit examples of query questions that should return "NOTHING" action
- Guidance: "When in doubt, use 'NOTHING' - better to not create than create a duplicate"

**Layer 2: Code-Level Deduplication**
- `add_schedule_event()` checks for existing events with same user, title, and date before creating
- If duplicate found, returns existing event ID (no new record created)
- If new info is more detailed, updates existing event with missing details
- `save_persistent_memory()` checks for duplicates based on category:
  - Schedule memories: matches on user, category, event_date, event_time
  - Other memories: matches on user, category, exact content
  - If duplicate found, skips insertion and updates importance if higher

**Files with deduplication logic:**
- `mumble-bot/bot.py`: Lines 1164 (save_persistent_memory), 1355 (add_schedule_event)
- `sip-mumble-bridge/bridge.py`: Lines 941 (save_persistent_memory), 1074 (add_schedule_event)
- `email-summary-service/app.py`: Lines 966 (save_persistent_memory), 1220 (add_schedule_event)

**Documentation:** See `docs/CHANGELOG_DEDUPLICATION_SYSTEM.md` for full details

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

### Persistent Memories System

The bot automatically extracts and stores important information from conversations:
- **Automatic extraction** after every conversation exchange using Ollama
- **Categories**: schedule, fact, task, preference, reminder, other
- **Importance scoring**: 1-10 scale for prioritization
- **Schedule date/time tracking**: Schedule memories include exact date (YYYY-MM-DD) and time (HH:MM)
  - AI calculates absolute dates from "tomorrow", "next Monday", etc.
  - Stored in `event_date` and `event_time` fields
  - Displayed with full formatted date in prompts
- **Semantic context**: Top 10 most important memories included in bot prompts
- **Web management**: View, filter, add, and delete memories via control panel
- **Per-user storage**: Memories are associated with individual users
- See `docs/PERSISTENT_MEMORIES_GUIDE.md` for details

### Session Management

Robust session lifecycle with automatic state management:
- **Session states**: active → idle (after 30 min) → closed (after 10 min idle)
- **Session reactivation**: Recent idle sessions can be reactivated to preserve context
- **Database persistence**: All sessions stored in `conversation_sessions` table
- **Configurable timeouts**: `session_timeout_minutes` and `session_reactivation_minutes`
- **Bot always available**: Session state doesn't affect bot availability
- See `docs/SESSION_MANAGEMENT.md` for details

### Semantic Memory (pgvector)

Advanced conversation search using embeddings:
- **pgvector extension** for PostgreSQL enables vector similarity search
- **Automatic embedding**: All messages embedded using sentence-transformers
- **Background context**: Similar past conversations included in prompts
- **Dual memory architecture**:
  - Short-term: Last 3 exchanges in current session
  - Long-term: Semantically similar past conversations
  - Persistent: Important extracted memories (schedules, facts, tasks)
- **Context window optimization**: Keeps prompts concise while maintaining relevance

### Email Bot & Summaries

**Two-Way Email Communication** - Intelligent email assistant with thread tracking:
- **IMAP Integration**: Bot checks for new emails at configured intervals
- **Thread-Aware Conversations**: Tracks email threads by subject line, maintains full conversation context
- **Action Tracking**: Every memory/calendar action logged with success/failure/error details
- **Synchronous Execution**: Actions executed BEFORE replying (not fire-and-forget)
- **Truthful Reporting**: Bot only claims what it actually did, provides Event IDs and timestamps
- **Brief Replies**: Under 100 words, no formal greetings, focused on user's question
- **Attachment Processing**: Analyzes PDFs (text extraction), images (vision AI), and documents
- **Smart Context**: Only includes schedule when user asks about calendar/events
- **Ownership Clarity**: Bot clearly distinguishes between adding to user's calendar vs its own

**Email Tables:**
- `email_threads`: Tracks conversation threads by normalized subject
- `email_thread_messages`: Stores conversation history per thread
- `email_actions`: Logs all action attempts with status (success/failed/skipped)
- `email_logs`: Email activity with thread_id and attachment metadata
- `email_user_mappings`: Maps email addresses to user names
- `email_settings`: SMTP/IMAP configuration

**Daily Email Summaries:**
- **Automated scheduling**: Send summaries at configured time (default 10pm EST)
- **AI-powered content**: Ollama generates intelligent summaries
- **SMTP support**: Full TLS/SSL authentication support
- **Beautiful HTML emails**: Responsive design with branding
- **Configurable via web panel**: SMTP settings, schedule, timezone
- See `docs/EMAIL_SUMMARIES_GUIDE.md` for details
- See `docs/CHANGELOG_EMAIL_THREAD_TRACKING.md` for thread tracking implementation
- See `docs/EMAIL_BOT_TRUTHFULNESS_FIX.md` for action result reporting improvements
- See `docs/EMAIL_BOT_SIMPLIFICATION_FIX.md` for reply simplification details

### AI Scheduling System

Comprehensive calendar management through natural conversation:
- **Automatic event detection**: AI extracts scheduling intent from conversations
- **Smart date parsing**: Understands "tomorrow", "next Monday", "in 3 days", etc.
- **Full CRUD operations**: Add, view, update, delete events via conversation
- **Context integration**: Upcoming events (30 days) included in AI prompts
- **Multi-access**: Works through Mumble voice/text, SIP phone, and web interface
- **Web calendar UI**: Full-featured calendar at `http://localhost:5002/schedule`
- **Color-coded importance**: Red (9-10), Orange (7-8), Blue (4-6), Gray (1-3)
- **Background extraction**: Non-blocking schedule management using Ollama
- **Database storage**: `schedule_events` table with soft deletes
- See `docs/AI_SCHEDULING_SYSTEM.md` for comprehensive guide
- See `docs/SCHEDULING_QUICK_REFERENCE.md` for usage examples

## Important File Locations

### Core Services
- **AI Bot**: `mumble-bot/bot.py` - Main orchestration logic, Mumble client, audio processing, memory extraction
- **Faster Whisper**: `faster-whisper-service/app.py` - Flask API for speech-to-text
- **Piper TTS**: `piper-tts-service/app.py` - Flask API for text-to-speech (50+ voices)
- **Silero TTS**: `silero-tts-service/app.py` - Flask API for high-quality TTS (20+ voices)
- **Web Control Panel**: `web-control-panel/app.py` - Flask admin interface
- **SIP Bridge**: `sip-mumble-bridge/bridge.py` - SIP/RTP to Mumble bridge with AI integration
- **TTS Web Interface**: `tts-web-interface/app.py` - Standalone voice generator (both engines)
- **Email Summary Service**: `email-summary-service/app.py` - Automated daily email summaries

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
- **Persistent Memories**: `docs/PERSISTENT_MEMORIES_GUIDE.md` - Memory system guide
- **Email Summaries**: `docs/EMAIL_SUMMARIES_GUIDE.md` - Email configuration guide
- **Session Management**: `docs/SESSION_MANAGEMENT.md` - Session lifecycle details
- **Bot Memory System**: `docs/BOT_MEMORY_SYSTEM.md` - Overall memory architecture
- **Prompting System**: `docs/PROMPTING_SYSTEM.md` - How prompts are constructed
- **AI Scheduling System**: `docs/AI_SCHEDULING_SYSTEM.md` - Comprehensive scheduling guide
- **Scheduling Quick Reference**: `docs/SCHEDULING_QUICK_REFERENCE.md` - Usage examples and commands

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

Edit `mumble-bot/bot.py`, search for conversation context building:
```python
# Short-term memory (current session)
history = self.get_conversation_history(user_name=user_name, session_id=session_id, limit=3)

# Long-term memory (semantic search)
similar_history = self.search_similar_conversations(user_name, user_input, limit=5)

# Persistent memories (facts, schedules, tasks)
persistent_memories = self.get_persistent_memories(user_name, limit=10)
```

### Managing Persistent Memories

Via web panel:
1. Navigate to `http://localhost:5002`
2. Scroll to "🧠 Persistent Memories"
3. Filter by user or category
4. Add new memories with "+ Add Memory"
5. Delete outdated memories with delete button

Via database:
```bash
# View all memories
docker exec mumble-ai-postgres psql -U mumbleai mumble_ai -c "SELECT * FROM persistent_memories WHERE user_name='YourName' ORDER BY importance DESC;"

# Add a memory manually
docker exec mumble-ai-postgres psql -U mumbleai mumble_ai -c "INSERT INTO persistent_memories (user_name, category, content, importance) VALUES ('YourName', 'schedule', 'Meeting Monday 2pm', 8);"
```

### Configuring Email Summaries

Via web panel:
1. Navigate to `http://localhost:5002`
2. Scroll to "📧 Email Summary Settings"
3. Configure SMTP settings (host, port, credentials)
4. Set recipient email and delivery time
5. Click "Send Test Email" to verify
6. Enable "Daily Summaries" checkbox
7. Click "Save Email Settings"

Via database:
```bash
docker exec mumble-ai-postgres psql -U mumbleai mumble_ai -c "UPDATE email_settings SET smtp_host='mail.example.com', smtp_port=587, recipient_email='admin@example.com', daily_summary_enabled=true;"
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

### PostgreSQL pgvector Extension

Required for semantic memory search. Automatically installed on container startup:
- Vector similarity search for conversation history
- Embeddings stored as 384-dimensional vectors
- Uses cosine similarity for finding similar conversations

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

### Debugging Memory Extraction

1. Check if memories are being extracted:
```bash
docker-compose logs -f mumble-bot | grep "Extracted memory"
```

2. View memories in database:
```bash
docker exec mumble-ai-postgres psql -U mumbleai mumble_ai -c "SELECT user_name, category, content, importance FROM persistent_memories ORDER BY extracted_at DESC LIMIT 10;"
```

3. Test memory API:
```bash
curl http://localhost:5002/api/memories
curl "http://localhost:5002/api/memories?user=YourName&category=schedule"
```

### Debugging Session Management

1. View active sessions:
```bash
docker exec mumble-ai-postgres psql -U mumbleai mumble_ai -c "SELECT session_id, user_name, state, last_activity FROM conversation_sessions WHERE state='active';"
```

2. Check session lifecycle:
```bash
docker-compose logs -f mumble-bot | grep -i "session"
```

3. Manually close idle sessions:
```bash
docker exec mumble-ai-postgres psql -U mumbleai mumble_ai -c "UPDATE conversation_sessions SET state='idle' WHERE last_activity < NOW() - INTERVAL '30 minutes' AND state='active';"
```

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

- **Web Control Panel**: http://localhost:5002 (config, memories, email settings, TTS engine selection with preview)
- **Mumble Web Client**: http://localhost:8081
- **TTS Voice Generator**: http://localhost:5003 (Piper, Silero, & Chatterbox voice cloning)
- **Mumble Server**: localhost:48000 (via Mumble desktop/mobile client) - *changed from 64738 to avoid Windows Hyper-V port conflicts*
- **SIP Bridge**: localhost:5060 (via SIP phone/softphone)

## Testing and Validation

### Test Whisper Service
```bash
curl -X POST http://localhost:5000/transcribe -F "audio=@test.wav"
```

### Test Piper TTS
```bash
curl -X POST http://localhost:5001/synthesize -d '{"text":"Hello world","voice":"en_US-lessac-medium"}'
```

### Test Silero TTS
```bash
curl -X POST http://localhost:5004/synthesize -d '{"text":"Hello world","voice":"en_0"}'
```

### Test Memory Extraction
```bash
# View logs for memory extraction
docker-compose logs -f mumble-bot | grep "memory"

# Check memories in database
docker exec mumble-ai-postgres psql -U mumbleai mumble_ai -c "SELECT * FROM persistent_memories ORDER BY extracted_at DESC LIMIT 5;"
```

### Test Email Summaries
```bash
# Check email service status
docker-compose logs -f email-summary-service

# Send test email via API
curl -X POST http://localhost:5002/api/email/test
```

### Test Semantic Search
```bash
# View conversation embeddings
docker exec mumble-ai-postgres psql -U mumbleai mumble_ai -c "SELECT id, user_name, LEFT(message, 50) as message_preview, timestamp FROM conversation_history WHERE embedding IS NOT NULL ORDER BY timestamp DESC LIMIT 5;"
```
