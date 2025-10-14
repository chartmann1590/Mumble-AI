# Mumble AI Flutter Control Panel

A comprehensive Flutter Android application for managing and controlling the Mumble AI system. This app provides a mobile interface to all the features available in the web control panel, plus additional mobile-specific functionality.

## Features

### ✅ Complete Feature Set

- **Server Connection Management** - Save and manage Mumble AI server URL
- **AI Chat Interface** - Direct chat with Ollama AI
- **Dashboard** - Statistics and upcoming events overview
- **Ollama Configuration** - Model and URL management for AI models
- **Conversation History** - View and manage conversation logs
- **Persistent Memories** - CRUD operations for AI memories
- **Schedule Manager** - Full calendar and event management
- **Email Settings** - Complete SMTP, IMAP, and auto-reply configuration
- **Email Logs** - View email history with filtering and retry functionality
- **Voice Configuration** - All TTS engines (Piper, Silero, Chatterbox) with audio preview
- **Persona Management** - Edit and enhance bot persona with AI assistance
- **Advanced Settings** - Fine-tune AI behavior and memory limits
- **Whisper Language Config** - Speech recognition language settings
- **Audio Playback** - Preview voices before selection
- **Navigation Drawer** - Complete menu system with all features
- **Material Design** - Modern, intuitive UI with consistent theming
- **Error Handling** - Comprehensive error handling and user feedback
- **Loading States** - Loading indicators and skeleton screens
- **Form Validation** - Input validation and user guidance

## Installation

### Prerequisites

- Android device with API level 21+ (Android 5.0+)
- Mumble AI server running and accessible
- Network connection to the Mumble AI server

### APK Installation

1. Download the latest APK from the `build/app/outputs/flutter-apk/` directory
2. Enable "Install from unknown sources" in your Android device settings
3. Install the APK file
4. Launch the app

### Development Setup

If you want to build from source:

```bash
# Clone the repository
git clone <repository-url>
cd mumble_ai_flutter

# Install Flutter dependencies
flutter pub get

# Build debug APK
flutter build apk --debug

# Build release APK
flutter build apk --release
```

## Usage

### First Time Setup

1. **Launch the app** - You'll see the server connection screen
2. **Enter server URL** - Input your Mumble AI server address (e.g., `http://192.168.1.100:5002`)
3. **Test connection** - Tap "Connect" to verify the server is reachable
4. **Start using** - You'll be taken to the dashboard

### Main Features

#### Dashboard
- View conversation statistics
- See upcoming scheduled events
- Quick access to all major features
- Pull-to-refresh for latest data

#### AI Chat
- Direct text chat with the AI
- Real-time responses from Ollama
- Message history
- Typing indicators

#### Ollama Configuration
- Set Ollama server URL
- Select AI models for different purposes
- Configure vision models for image analysis
- Set memory extraction models
- Test connections

#### Voice Configuration
- Choose TTS engine (Piper, Silero, Chatterbox)
- Preview voices with audio playback
- Select voices for each engine
- Voice cloning support (Chatterbox)

#### Memories Management
- View all AI memories
- Filter by user and category
- Add, edit, and delete memories
- Importance levels and tags

#### Schedule Manager
- Calendar and list views
- Create, edit, and delete events
- Email reminders
- Filter by user
- Importance levels

#### Conversations
- View conversation history
- Filter by message count
- Search functionality
- Reset conversations

## API Endpoints

The app connects to the following Mumble AI server endpoints:

### Core Endpoints
- `GET /api/stats` - Dashboard statistics
- `GET /health` - Server health check

### Ollama Configuration
- `GET /api/ollama/config` - Get Ollama settings
- `POST /api/ollama/config` - Update Ollama settings
- `GET /api/ollama/models` - Get available models
- `GET /api/ollama/vision_config` - Get vision model
- `POST /api/ollama/vision_config` - Update vision model
- `GET /api/ollama/vision_models` - Get vision models
- `GET /api/ollama/memory_model_config` - Get memory model
- `POST /api/ollama/memory_model_config` - Update memory model

### Conversations
- `GET /api/conversations` - Get conversation history
- `POST /api/conversations/reset` - Reset conversations

### Memories
- `GET /api/memories` - Get all memories
- `POST /api/memories` - Add new memory
- `PUT /api/memories/<id>` - Update memory
- `DELETE /api/memories/<id>` - Delete memory
- `GET /api/users` - Get users with memories

### Schedule
- `GET /api/schedule` - Get all events
- `POST /api/schedule` - Add new event
- `PUT /api/schedule/<id>` - Update event
- `DELETE /api/schedule/<id>` - Delete event
- `GET /api/schedule/upcoming` - Get upcoming events
- `GET /api/schedule/users` - Get users with events

### Voice/TTS
- `GET /api/tts/engine` - Get TTS engine
- `POST /api/tts/engine` - Set TTS engine
- `GET /api/piper/voices` - Get Piper voices
- `GET /api/piper/current` - Get current Piper voice
- `POST /api/piper/current` - Set Piper voice
- `POST /api/piper/preview` - Preview Piper voice
- `GET /api/silero/voices` - Get Silero voices
- `GET /api/silero/current` - Get current Silero voice
- `POST /api/silero/current` - Set Silero voice
- `POST /api/silero/preview` - Preview Silero voice
- `GET /api/chatterbox/voices` - Get Chatterbox voices
- `GET /api/chatterbox/current` - Get current voice
- `POST /api/chatterbox/current` - Set voice
- `POST /api/chatterbox/preview` - Preview voice

## Architecture

### Project Structure
```
lib/
├── main.dart                    # App entry point
├── models/                      # Data models
│   ├── conversation.dart
│   ├── memory.dart
│   ├── schedule_event.dart
│   ├── email_log.dart
│   └── stats.dart
├── services/                    # API & business logic
│   ├── api_service.dart         # HTTP client wrapper
│   ├── storage_service.dart     # Local storage
│   └── audio_service.dart       # Audio playback
├── screens/                     # UI screens
│   ├── server_connect_screen.dart
│   ├── dashboard_screen.dart
│   ├── ai_chat_screen.dart
│   ├── ollama_config_screen.dart
│   ├── conversations_screen.dart
│   ├── memories_screen.dart
│   ├── schedule_screen.dart
│   └── voice_config_screen.dart
├── widgets/                     # Reusable widgets
│   ├── stat_card.dart
│   ├── message_bubble.dart
│   └── loading_indicator.dart
└── utils/                       # Utilities
    ├── constants.dart
    └── theme.dart
```

### Technology Stack
- **Framework**: Flutter 2.10.2
- **State Management**: Provider
- **HTTP Client**: Dio
- **Local Storage**: SharedPreferences
- **Audio Playback**: AudioPlayers
- **Date/Time**: Intl
- **Navigation**: MaterialApp routes

## Configuration

### Server Requirements
- Mumble AI server running on accessible network
- CORS enabled for mobile app access
- All API endpoints available and functional

### Network Configuration
- Ensure the Mumble AI server is accessible from your mobile device
- Use local network IP (e.g., `http://192.168.1.100:5002`) for local servers
- Use public IP or domain for remote servers

## Troubleshooting

### Common Issues

#### Connection Failed
- Verify server URL is correct
- Check network connectivity
- Ensure Mumble AI server is running
- Verify firewall settings

#### Audio Not Playing
- Check device volume settings
- Ensure audio permissions are granted
- Verify TTS service is running on server

#### Models Not Loading
- Check Ollama is running and accessible
- Verify model files are downloaded
- Test Ollama connection in web panel first

#### App Crashes
- Check device compatibility (Android 5.0+)
- Clear app data and restart
- Reinstall the APK

### Debug Information
- Enable developer options on Android device
- Check device logs for error messages
- Verify server logs for API errors

## Development

### Building from Source
```bash
# Install Flutter SDK
# Clone repository
git clone <repository-url>
cd mumble_ai_flutter

# Install dependencies
flutter pub get

# Run in debug mode
flutter run

# Build APK
flutter build apk --release
```

### Code Style
- Follow Flutter/Dart conventions
- Use meaningful variable names
- Add comments for complex logic
- Maintain consistent formatting

### Testing
- Test on multiple Android versions
- Verify all API endpoints work
- Test network connectivity scenarios
- Validate audio playback functionality

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

This project is part of the Mumble AI system. Please refer to the main project license.

## Support

For issues and support:
1. Check the troubleshooting section
2. Review server logs
3. Test with web control panel
4. Create an issue with detailed information

## Changelog

### Version 1.0.0 - Complete Release
- **Core Features**: Server connection management, AI chat interface, dashboard
- **AI Configuration**: Ollama, vision models, memory models, persona management
- **Communication**: Email settings, logs, voice configuration with audio preview
- **Data Management**: Conversation history, persistent memories, schedule manager
- **Advanced Features**: Advanced settings, whisper language configuration
- **UI/UX**: Material Design, navigation drawer, error handling, loading states, form validation
- **Audio**: Voice preview for all TTS engines (Piper, Silero, Chatterbox)
- **Navigation**: Complete navigation drawer with all features accessible
- **Complete API Integration**: All 50+ endpoints from the web control panel