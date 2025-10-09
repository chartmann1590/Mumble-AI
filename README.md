# Mumble AI Bot

A fully-featured AI-powered voice assistant for Mumble VoIP servers with speech recognition, text-to-speech, conversation memory, and a web-based control panel.

![Version](https://img.shields.io/badge/version-1.2.0-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

## Features

### 🎙️ Voice & Text Interaction
- **Speech-to-Text**: Real-time voice transcription using Faster Whisper
- **Text-to-Speech**: Dual TTS engines - Piper TTS (31 voices) and Silero TTS (20+ voices)
- **Dual Communication**: Responds to voice with voice, text with text
- **Silence Detection**: Automatically processes speech after 1.5 seconds of silence

### 🤖 AI Integration
- **Ollama Integration**: Local LLM support (llama3.2, qwen2.5-coder, gemma3, and more)
- **Persistent Memories**: AI-powered automatic extraction and storage of schedules, facts, tasks, and preferences
- **Smart Scheduling**: AI extracts dates from natural language ("next Friday at 3pm") and creates calendar events
- **Duplicate Prevention**: Intelligent deduplication system prevents duplicate events and memories from being created
- **Semantic Memory**: Dual memory architecture with short-term (session) and long-term (semantic search) context
- **Context-Aware**: Intelligent conversation flow with anti-repetition and anti-hallucination safeguards
- **Custom Personas**: Define and AI-enhance bot personalities

### 🌐 Multiple Access Methods
- **Mumble Client**: Traditional desktop/mobile Mumble clients
- **Web Clients**: Two web-based Mumble clients (simple and full-featured)
- **SIP Bridge**: Connect traditional phones via SIP/RTP to Mumble with personalized welcome messages
- **Web Control Panel**: Management interface for configuration
- **TTS Voice Generator**: Beautiful web interface supporting both Piper and Silero TTS engines

### 🎨 Web Control Panel
- **Real-Time Dashboard**: Live statistics, conversation monitoring, and upcoming events display
- **Schedule Manager**: Full calendar interface for managing events with importance levels and color-coding
- **Upcoming Events**: Dashboard widget showing next 7 days, list view showing next 30 days
- **Memory Management**: View, filter, and manage persistent memories by user and category
- **Email Summaries**: Beautiful HTML emails with AI summaries, schedule events, and extracted memories
- **Voice Selection**: Choose from 50+ diverse TTS voices across Piper and Silero engines
- **Model Management**: Switch between Ollama models on-the-fly
- **Persona Configuration**: Create custom bot personalities with AI enhancement
- **History Management**: View and clear conversation history

### 🎵 TTS Voice Generator (Standalone)
- **Independent Service**: Standalone web interface for voice generation
- **Beautiful Web Interface**: Modern, responsive design with gradient backgrounds
- **Dual TTS Engines**: Support for both Piper TTS (50+ voices) and Silero TTS (20+ voices)
- **Advanced Filtering**: Filter voices by region, gender, and quality level
- **Real-Time Preview**: Test voices before generating full audio
- **Text Input Validation**: Character counting and input validation (up to 5000 chars)
- **Audio Player**: Built-in player with duration display
- **Download Support**: Generate and download high-quality WAV files
- **Mobile Responsive**: Works perfectly on desktop, tablet, and mobile devices
- **On-Demand TTS**: Only uses TTS services when generating audio files

### 🔧 Technical Features
- **Docker Compose**: Full stack deployment with one command
- **Microservices Architecture**: Modular, scalable design
- **Health Checks**: Automatic service monitoring and recovery
- **Audio Processing**: Professional-grade audio resampling (48kHz for Mumble)
- **Database Persistence**: All configurations and history stored in PostgreSQL
- **SIP Integration**: Full SIP/RTP implementation for phone system integration

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    User Access Layer                        │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐   │
│  │Mumble Client │  │ Web Clients  │  │  SIP Phones     │   │
│  │(Desktop/Mobile│  │(Port 8081)   │  │(Port 5060)     │   │
│  └──────┬───────┘  └──────┬───────┘  └────────┬────────┘   │
└─────────┼──────────────────┼───────────────────┼────────────┘
          │                  │                   │
┌─────────▼──────────────────▼───────────────────▼────────────┐
│                  Mumble Server (Port 48000)                │
│         (Internal: 64738, External: 48000)                 │
└─────────┬──────────────────────────────────────────────────┘
          │
    ┌─────▼─────┐
    │  AI Bot   │
    └─┬───┬───┬─┘
      │   │   │
┌─────▼───▼───▼──────────────────────────────────────────────┐
│                    Service Layer                           │
│  ┌──────────┐  ┌────────┐  ┌─────────┐  ┌──────────────┐  │
│  │ Faster   │  │ Piper  │  │ Ollama  │  │  PostgreSQL  │  │
│  │ Whisper  │  │  TTS   │  │(External│  │              │  │
│  │(Port5000)│  │(5001)  │  │ :11434) │  │  (Internal)  │  │
│  └──────────┘  └────────┘  └─────────┘  └──────────────┘  │
│  ┌──────────┐                                             │
│  │ Silero   │                                             │
│  │  TTS     │                                             │
│  │(Port5004)│                                             │
│  └──────────┘                                             │
└─────────────────────────────────────────────────────────────┘
                      │
              ┌───────▼────────┐
              │ Web Control    │
              │ Panel (5002)   │
              └────────────────┘

┌─────────────────────────────────────────────────────────────┐
│              Standalone TTS Voice Generator                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │         TTS Voice Generator (Port 5003)           │   │
│  │              (Web Interface)                       │   │
│  └─────────────────┬───────────────────────────────────┘   │
│                    │                                       │
│  ┌─────────────────▼───────────────────────────────────┐   │
│  │         Uses Piper TTS & Silero TTS                 │   │
│  │            (On-demand only)                         │   │
│  └────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Prerequisites

- Docker and Docker Compose installed
- Ollama installed and running locally
- A Mumble client (download from https://www.mumble.info/)

## Setup

### 1. Configure Environment

Copy the example environment file and customize it:

```bash
cp .env.example .env
```

Edit `.env` to configure:
- `MUMBLE_PASSWORD` - Password for Mumble server superuser
- `BOT_USERNAME` - Name of the AI bot
- `WHISPER_MODEL` - Whisper model size (tiny, base, small, medium, large)
- `OLLAMA_MODEL` - Your Ollama model name (e.g., llama2, mistral, etc.)

### 2. Ensure Ollama is Running

Make sure Ollama is installed and running on your local machine:

```bash
ollama serve
```

Pull a model if you haven't already:

```bash
ollama pull llama2
```

### 3. Start the Stack

Build and start all services:

```bash
docker-compose up -d
```

On first run, this will:
- Download and set up the Mumble server
- Download Whisper models
- Download 31 Piper TTS voice models
- Initialize PostgreSQL database
- Build and start the bot

### 4. Access the Control Panel

Open your browser and navigate to:
```
http://localhost:5002
```

From here you can:
- Change AI models
- Select TTS voices
- Configure bot persona
- View conversation history
- Monitor statistics

### 5. Access the System

#### Option A: Traditional Mumble Client
1. Open your Mumble client
2. Add a new server:
   - **Address:** `localhost` (or your host's IP for remote connections)
   - **Port:** `48000` (changed from default 64738 due to Windows port reservation conflicts)
   - **Username:** Your name
   - **Password:** Leave empty (unless you set one)
3. Connect to the server
4. You should see the AI bot in the channel

> **Note:** The default Mumble port 64738 conflicts with Windows Hyper-V reserved port ranges. The external port has been changed to 48000, but the internal Docker network still uses 64738.

#### Option B: Web Client
1. Open your browser and navigate to:
   ```
   https://localhost:8081
   ```
2. Accept the self-signed certificate warning (click "Advanced" → "Proceed")
3. Enter your username
4. Grant microphone permissions when prompted
5. Connect to the server
6. The AI bot will be available in the channel

> **Note:** The web client uses HTTPS with a self-signed certificate for microphone access. Your browser will show a security warning - this is normal for local development. For production, replace with a proper SSL certificate.

#### Option C: SIP Phone (Advanced)
1. Configure your SIP client or phone system
2. Point to `localhost:5060`
3. Use credentials from `.env` file:
   - **Username:** `mumble-bridge` (or your `SIP_USERNAME`)
   - **Password:** `bridge123` (or your `SIP_PASSWORD`)
4. Make a call - you'll hear a personalized welcome message and be connected to the AI assistant

## Services

| Service | Port | Description |
|---------|------|-------------|
| Mumble Server | 48000 (external), 64738 (internal) | VoIP server |
| Faster Whisper | 5000 | Speech-to-text API |
| Piper TTS | 5001 | Text-to-speech API |
| Web Control Panel | 5002 | Management interface |
| TTS Voice Generator | 5003 | Standalone voice generation web interface |
| Silero TTS | 5004 | Alternative text-to-speech API |
| PostgreSQL | 5432 | Database (internal) |
| AI Bot | - | Mumble client |
| SIP Bridge | 5060 | SIP/RTP to Mumble bridge |
| Mumble Web | 8081 (HTTPS) | Web-based Mumble client with SSL |
| Mumble Web Nginx | - | SSL/TLS proxy for Mumble Web (internal) |
| Mumble Web Simple | - | Simplified web client (build only) |

**Port 48000 Explanation:** The standard Mumble port 64738 is reserved by Windows Hyper-V on many systems. Port 48000 is used externally to avoid conflicts, while internal Docker services still communicate on 64738.

**Mumble Web SSL:** The web client uses HTTPS on port 8081 with a self-signed certificate. This enables microphone access in modern browsers. For production use, replace with a CA-signed certificate.

## Usage

### Voice Interaction

1. Connect to the Mumble server with your client
2. Start speaking - the bot listens automatically
3. After you finish speaking (1.5 seconds of silence), the bot will:
   - Transcribe your speech
   - Send it to Ollama
   - Speak the response back to you

### Text Interaction

1. Send a text message in Mumble chat
2. The bot will respond with a text message

### TTS Voice Generator

Access at `http://localhost:5003`

**Features**
- **Dual TTS Engines**: Choose between Piper TTS (50+ voices) and Silero TTS (20+ voices)
- **Voice Selection**: Choose from 70+ voices across 9 languages and regions
- **Advanced Filtering**: Filter by region, gender, and quality level
- **Text Input**: Enter up to 5000 characters for synthesis
- **Real-Time Preview**: Test voices with sample text before generating
- **Audio Player**: Built-in player with duration display
- **Download Support**: Generate and download high-quality WAV files
- **Mobile Responsive**: Works on all devices

**Usage**
1. Select a TTS engine (Piper or Silero)
2. Select a voice from the filtered list
3. Enter your text (up to 5000 characters)
4. Click "Preview Voice" to test the voice
5. Click "Generate & Download" to create the audio file

### Web Control Panel Features

Access at `http://localhost:5002`

**Dashboard**
- Total messages, unique users
- Voice vs. text message counts
- Upcoming events for next 7 days with color-coded importance
- Auto-refresh every 10 and 30 seconds

**Schedule Manager** 📅
- Full calendar view with month/week/day display
- Add, edit, and delete events with drag-and-drop
- Color-coded importance levels (Critical/High/Normal)
- List view showing upcoming 30 days
- Filter events by user
- Click events to edit details
- AI integration - bot extracts dates from conversations

**Ollama Configuration**
- Change server URL
- Select AI model
- Refresh available models

**Voice Selection**
- Dropdown with 31 voices
- Instant voice switching
- Sorted alphabetically

**Bot Persona**
- Define custom personalities
- AI-enhanced persona generation
- Persistent across restarts

**Conversation History**
- Last 50 messages
- User/assistant separation
- Timestamps and message types
- One-click history clearing

**Persistent Memories** 🧠
- AI-powered automatic extraction of important information
- Filter by user and category (schedule, fact, task, preference, reminder)
- Importance scoring (1-10) for prioritization
- Visual color-coded cards by importance level
- Delete or manually add memories
- Bot uses memories to provide accurate, contextual responses

### Persistent Memories System

The bot automatically extracts and remembers important information from conversations:

**Categories:**
- 📅 **Schedule**: Appointments, meetings, events with dates/times
- 💡 **Fact**: Personal information, preferences, relationships
- ✓ **Task**: Things to do, reminders, action items
- ❤️ **Preference**: Likes, dislikes, habits
- ⏰ **Reminder**: Time-based reminders
- 📌 **Other**: Miscellaneous important info

**How it works:**
1. You tell the bot something important: "I have a meeting Monday at 2pm"
2. Bot automatically extracts and saves: [SCHEDULE] Meeting Monday at 2pm
3. Later you ask: "What's my schedule Monday?"
4. Bot retrieves the memory and responds accurately: "You have a meeting at 2pm"

**Managing Memories:**
- View all memories at `http://localhost:5002` under "🧠 Persistent Memories"
- Filter by user or category
- Add memories manually with the "+ Add Memory" button
- Delete outdated or incorrect memories
- Memories are shared across Mumble and SIP bridge

For detailed information, see [PERSISTENT_MEMORIES_GUIDE.md](./PERSISTENT_MEMORIES_GUIDE.md)

### Email Summaries

Stay informed with daily AI-generated email summaries of all conversations:

1. Go to `http://localhost:5002` and scroll to "📧 Email Summary Settings"
2. Configure your SMTP settings (host, port, credentials)
3. Set recipient email and preferred delivery time
4. Click "Send Test Email" to verify configuration
5. Enable "Daily Summaries" to activate automatic sending

The bot will send beautifully formatted HTML emails with:
- **Upcoming Events** - Next 7 days with color-coded importance badges
- **Schedule Changes** - New events added in last 24 hours
- **New Memories** - Recently extracted facts, tasks, and preferences with category icons
- **AI-Generated Summary** - Intelligent conversation highlights using Ollama
- **Professional Design** - Responsive HTML with gradient headers and card layouts
- **Scheduled Delivery** - Automatic sending at your chosen time (default: 10pm EST)

For detailed information, see [EMAIL_SUMMARIES_GUIDE.md](./EMAIL_SUMMARIES_GUIDE.md)

### Schedule Manager

Manage events and appointments with a full calendar interface:

1. Go to `http://localhost:5002` and click "📅 Schedule Manager" in the top navigation
2. **Add Events**: Click "+ Add Event" or click a date on the calendar
3. **Edit Events**: Click any event on the calendar or in the list view below
4. **Set Importance**: Choose 1-10 (Critical=8-10, High=5-7, Normal=1-4)
5. **Color Coding**: Events automatically color-coded by importance level
6. **Filter by User**: Select a user from the dropdown to show only their events
7. **List View**: Scroll below calendar to see upcoming 30 days in detail

**AI Integration:**
- Tell the bot: "Schedule me for next Friday at 9:30am for haircut"
- Bot automatically extracts date/time and creates calendar event
- Bot uses Python-based date parser for accurate "next Friday", "tomorrow", etc.
- Events appear in both calendar and upcoming events displays

### Setting a Persona

1. Go to `http://localhost:5002`
2. Scroll to "🤖 Bot Persona"
3. Enter: "You are a helpful pirate who loves sailing"
4. Click "✨ AI Enhance" to expand the description
5. Click "Save Persona"
6. Talk to the bot and experience the personality!

### Available Voices (70+ Total)

**Piper TTS (50+ voices):**
- **US English:** lessac, amy, kristin, kathleen, hfc_female, joe, bryce, danny, john, kusal, hfc_male
- **British English:** alba, jenny_dioco, southern_english_female, northern_english_male, alan
- **Multi-speaker:** l2arctic (24 speakers), arctic (18), libritts (904), aru (12), vctk (109)
- **Regional:** cori (Irish), semaine (Scottish), wavenet-a (Australian)

**Silero TTS (20+ voices):**
- **English:** 20 high-quality voices including clear female, warm male, professional voices
- **Quality:** All voices are high-quality with natural intonation
- **Gender:** Balanced selection of male and female voices
- **Style:** Professional, friendly, energetic, authoritative, and calm voice options

## Configuration

### Whisper Model Sizes

Larger models are more accurate but slower:

- `tiny` - Fastest, least accurate
- `base` - Good balance (default)
- `small` - Better accuracy
- `medium` - High accuracy
- `large` - Best accuracy, slowest

### Ollama Models

You can use any Ollama model. Popular options:

- `llama2` - General purpose
- `mistral` - Fast and capable
- `codellama` - For coding questions
- `orca-mini` - Smaller, faster

Change the model in `.env`:

```env
OLLAMA_MODEL=mistral
```

## Troubleshooting

### Bot can't connect to Ollama

Make sure Ollama is running and accessible. Test with:

```bash
curl http://localhost:11434/api/generate -d '{"model":"llama2","prompt":"Hello"}'
```

### Audio quality issues

Try increasing the Whisper model size in `.env`:

```env
WHISPER_MODEL=small
```

### Bot not responding

Check the logs:

```bash
docker-compose logs -f mumble-bot
```

### Services not starting

Ensure all ports are available:
- 48000 (Mumble - changed from 64738 to avoid Windows Hyper-V port conflicts)
- 5000 (Whisper)
- 5001 (Piper)

## Stopping the Stack

```bash
docker-compose down
```

To remove all data:

```bash
docker-compose down -v
```

## Project Structure

```
Mumble-AI/
├── docker-compose.yml          # Service orchestration
├── .env                        # Environment configuration
├── .gitignore                  # Git ignore rules
├── init-db.sql                 # Database schema
├── mumble-config.ini           # Mumble server config
├── README.md                   # This file
├── mumble-bot/                 # AI bot service
│   ├── bot.py
│   ├── Dockerfile
│   └── requirements.txt
├── faster-whisper-service/     # STT service
│   ├── app.py
│   └── Dockerfile
├── piper-tts-service/          # TTS service
│   ├── app.py
│   ├── download_model.py
│   └── Dockerfile
├── silero-tts-service/         # Alternative TTS service
│   ├── app.py
│   ├── download_models.py
│   ├── requirements.txt
│   └── Dockerfile
├── web-control-panel/          # Management UI
│   ├── app.py
│   ├── download_voices.py
│   ├── Dockerfile
│   ├── requirements.txt
│   └── templates/
│       └── index.html
├── sip-mumble-bridge/          # SIP/RTP bridge
│   ├── bridge.py
│   ├── config.py
│   ├── WELCOME_MESSAGE_FEATURE.md
│   └── Dockerfile
├── tts-web-interface/          # Standalone TTS voice generator
│   ├── app.py
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── app/
│   │   ├── static/
│   │   │   ├── css/style.css
│   │   │   └── js/app.js
│   │   └── templates/index.html
├── mumble-web/                 # Full web client
│   ├── app/                    # Client application
│   ├── themes/                 # UI themes
│   └── Dockerfile
├── mumble-web-simple/          # Simplified web client
│   ├── app/                    # Client application
│   ├── vendors/                # Third-party libraries
│   ├── themes/                 # UI themes
│   └── package.json
├── models/                     # AI model storage
│   ├── whisper/                # Whisper models
│   ├── piper/                  # Piper TTS models
│   └── silero/                 # Silero TTS models
└── docs/                       # Documentation
    ├── ARCHITECTURE.md
    ├── API.md
    ├── CONFIGURATION.md
    └── TROUBLESHOOTING.md
```

## Advanced Configuration

### Using GPU for Whisper

Edit `docker-compose.yml` in the `faster-whisper` service:

```yaml
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

### Custom Piper Voice

Download additional voices from https://github.com/rhasspy/piper and update the download URLs in `web-control-panel/download_voices.py`.

## Documentation

- [Architecture](docs/ARCHITECTURE.md) - System design and component interaction
- [API Reference](docs/API.md) - Complete API documentation
- [Configuration](docs/CONFIGURATION.md) - Detailed configuration guide
- [Troubleshooting](docs/TROUBLESHOOTING.md) - Common issues and solutions
- [Deduplication System](docs/CHANGELOG_DEDUPLICATION_SYSTEM.md) - Schedule and memory duplicate prevention

## Development

### Building from Source

```bash
# Build all services
docker-compose build

# Build specific service
docker-compose build mumble-bot

# Rebuild without cache
docker-compose build --no-cache
```

### Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f mumble-bot

# Last 100 lines
docker-compose logs --tail=100 mumble-bot
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

MIT License - see LICENSE file for details

## Acknowledgments

- [Mumble](https://www.mumble.info/) - Open source VoIP software
- [Piper TTS](https://github.com/rhasspy/piper) - Fast neural TTS
- [Faster Whisper](https://github.com/guillaumekln/faster-whisper) - Efficient speech recognition
- [Ollama](https://ollama.ai/) - Local LLM runtime
- [pymumble](https://github.com/azlux/pymumble) - Python Mumble client

## Support

For issues and questions:
- Open an issue on Gitea
- Check [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
- Review logs with `docker-compose logs`

---

**Built with ❤️ using Docker, Python, and AI**
