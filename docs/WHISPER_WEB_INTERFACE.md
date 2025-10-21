# Whisper Web Interface

A modern web interface for transcribing audio and video files using the Whisper AI model, with optional Ollama-powered summarization.

## Overview

The Whisper Web Interface is a new service in the Mumble-AI stack that provides a user-friendly web application for transcribing audio and video files. It integrates with the existing faster-whisper service and adds AI-powered summarization capabilities.

## Features

- **File Upload**: Support for audio (.mp3, .wav, .ogg, .flac, .aac, .m4a) and video (.mp4, .webm, .avi, .mov, .mkv) files up to 100MB
- **Real-time Transcription**: Uses the existing faster-whisper service for accurate speech-to-text conversion
- **AI Summarization**: Optional summarization using Ollama (requires local Ollama installation)
- **Modern UI**: React-based single-page application with Tailwind CSS
- **Database Storage**: PostgreSQL integration for storing transcriptions and summaries
- **Search & Filter**: Search through transcription history
- **Responsive Design**: Works on desktop and mobile devices

## Architecture

### Technology Stack

- **Backend**: Flask API with PostgreSQL connection pooling
- **Frontend**: React 18 with Vite build system
- **Audio Processing**: pydub + ffmpeg for format conversion
- **Database**: PostgreSQL with proper indexing for performance
- **Containerization**: Multi-stage Docker build

### Service Integration

- **Faster Whisper Service**: Handles the actual transcription
- **Ollama**: Provides AI summarization capabilities
- **PostgreSQL**: Stores transcription history and metadata
- **Redis**: Caching for improved performance

## API Endpoints

### Core Endpoints

- `POST /api/upload` - Upload and validate file
- `POST /api/transcribe` - Transcribe uploaded file
- `POST /api/summarize` - Generate AI summary
- `GET /api/transcriptions` - List transcriptions with pagination
- `GET /api/transcriptions/<id>` - Get single transcription
- `DELETE /api/transcriptions/<id>` - Delete transcription
- `GET /health` - Health check

### Request/Response Examples

#### Upload File
```bash
curl -X POST http://localhost:5008/api/upload \
  -F "file=@audio.wav" \
  -F "filename=audio.wav"
```

#### Transcribe File
```bash
curl -X POST http://localhost:5008/api/transcribe \
  -H "Content-Type: application/json" \
  -d '{"file_id": "123", "language": "auto"}'
```

#### Generate Summary
```bash
curl -X POST http://localhost:5008/api/summarize \
  -H "Content-Type: application/json" \
  -d '{"transcription_id": "123"}'
```

## Frontend Components

### React Components

- **UploadZone**: Drag-and-drop file upload interface
- **TranscriptionCard**: Display individual transcription results
- **TranscriptionList**: List view of all transcriptions
- **SummaryPanel**: AI-generated summary display
- **TimelineView**: Visual timeline of transcription segments
- **LoadingSpinner**: Loading states and progress indicators

### Key Features

- **Drag & Drop**: Intuitive file upload interface
- **Progress Tracking**: Real-time upload and processing status
- **Audio Visualization**: Waveform display for audio files
- **Search & Filter**: Find transcriptions by content or metadata
- **Export Options**: Download transcriptions in various formats

## File Format Support

### Audio Formats
- MP3 (.mp3)
- WAV (.wav)
- OGG (.ogg)
- FLAC (.flac)
- AAC (.aac)
- M4A (.m4a)

### Video Formats
- MP4 (.mp4)
- WebM (.webm)
- AVI (.avi)
- MOV (.mov)
- MKV (.mkv)

All formats are automatically converted to 16kHz mono WAV for optimal Whisper processing.

## Database Schema

### Transcriptions Table
```sql
CREATE TABLE transcriptions (
    id SERIAL PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    file_size BIGINT,
    file_type VARCHAR(10),
    duration FLOAT,
    language VARCHAR(10),
    transcription TEXT,
    summary TEXT,
    segments JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Indexes
```sql
CREATE INDEX idx_transcriptions_created_at ON transcriptions(created_at DESC);
CREATE INDEX idx_transcriptions_language ON transcriptions(language);
CREATE INDEX idx_transcriptions_file_type ON transcriptions(file_type);
```

## Configuration

### Environment Variables

- `DB_HOST` - PostgreSQL host (default: postgres)
- `DB_PORT` - PostgreSQL port (default: 5432)
- `DB_NAME` - Database name (default: mumble_ai)
- `DB_USER` - Database user (default: mumbleai)
- `DB_PASSWORD` - Database password (default: mumbleai123)
- `WHISPER_URL` - Whisper service URL (default: http://faster-whisper:5000)
- `OLLAMA_URL` - Ollama service URL (default: http://host.docker.internal:11434)
- `OLLAMA_MODEL` - Ollama model for summarization (default: llama3.2:latest)

### Docker Configuration

The service is configured in `docker-compose.yml`:

```yaml
whisper-web-interface:
  build:
    context: ./whisper-web-interface
    dockerfile: Dockerfile
  container_name: whisper-web-interface
  depends_on:
    postgres:
      condition: service_healthy
    faster-whisper:
      condition: service_started
  ports:
    - "5008:5008"
  environment:
    - DB_HOST=postgres
    - DB_PORT=5432
    - DB_NAME=${POSTGRES_DB:-mumble_ai}
    - DB_USER=${POSTGRES_USER:-mumbleai}
    - DB_PASSWORD=${POSTGRES_PASSWORD:-mumbleai123}
    - WHISPER_URL=http://faster-whisper:5000
    - OLLAMA_URL=${OLLAMA_URL:-http://host.docker.internal:11434}
    - OLLAMA_MODEL=${OLLAMA_MODEL:-llama3.2:latest}
  volumes:
    - /tmp:/tmp
  restart: unless-stopped
  networks:
    - mumble-ai-network
  extra_hosts:
    - "host.docker.internal:host-gateway"
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:5008/health"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 30s
```

## Usage Guide

### For End Users

1. **Access the Interface**: Navigate to `http://localhost:5008`
2. **Upload Files**: Drag and drop audio/video files or use the file browser
3. **Start Transcription**: Click "Start Transcription" to process the file
4. **View Results**: Review the transcription text and segments
5. **Generate Summary**: Optionally create an AI summary of the content
6. **Browse History**: View and search through previous transcriptions

### For Developers

#### Backend Development
```bash
cd whisper-web-interface
pip install -r requirements.txt
python app.py
```

#### Frontend Development
```bash
cd whisper-web-interface/client
npm install
npm run dev
```

#### Docker Build
```bash
docker-compose build whisper-web-interface
docker-compose up whisper-web-interface
```

## Performance Considerations

### File Size Limits
- Maximum file size: 100MB
- Recommended: < 50MB for optimal performance
- Large files are processed in chunks

### Processing Time
- Audio: ~1/10th of file duration
- Video: ~1/5th of file duration (due to audio extraction)
- Summary generation: 10-30 seconds depending on content length

### Resource Usage
- Memory: ~2GB for large files
- CPU: Moderate during processing
- Storage: Temporary files cleaned up automatically

## Troubleshooting

### Common Issues

1. **File Upload Fails**
   - Check file size (must be < 100MB)
   - Verify file format is supported
   - Ensure sufficient disk space

2. **Transcription Errors**
   - Verify faster-whisper service is running
   - Check audio quality and clarity
   - Try different language settings

3. **Summary Generation Fails**
   - Ensure Ollama is running and accessible
   - Check Ollama model is available
   - Verify network connectivity

### Health Checks

The service includes comprehensive health checks:
- Database connectivity
- Whisper service availability
- Ollama service availability
- File system access

## Security Considerations

- File upload validation and sanitization
- Temporary file cleanup
- Database connection pooling
- Input validation and sanitization
- CORS configuration for cross-origin requests

## Future Enhancements

- Real-time transcription streaming
- Batch file processing
- Custom model support
- Advanced audio analysis
- Integration with other Mumble-AI services
- User authentication and authorization
- API rate limiting
- Advanced search and filtering
