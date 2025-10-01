# API Reference

Complete API documentation for the Mumble AI Bot web control panel.

Base URL: `http://localhost:5002`

## Table of Contents

- [Statistics](#statistics)
- [Ollama Configuration](#ollama-configuration)
- [Piper TTS](#piper-tts)
- [Bot Persona](#bot-persona)
- [Conversation History](#conversation-history)

## Statistics

### Get Statistics

Retrieve current usage statistics.

**Endpoint:** `GET /api/stats`

**Response:**
```json
{
  "total_messages": 42,
  "unique_users": 3,
  "voice_messages": 28,
  "text_messages": 14
}
```

**Fields:**
- `total_messages` - Total number of messages processed
- `unique_users` - Number of unique users who have interacted
- `voice_messages` - Count of voice interactions
- `text_messages` - Count of text interactions

## Ollama Configuration

### Get Ollama Config

Get current Ollama server URL and model.

**Endpoint:** `GET /api/ollama/config`

**Response:**
```json
{
  "url": "http://host.docker.internal:11434",
  "model": "llama3.2:latest"
}
```

### Update Ollama Config

Update Ollama server URL and/or model.

**Endpoint:** `POST /api/ollama/config`

**Request Body:**
```json
{
  "url": "http://host.docker.internal:11434",
  "model": "qwen2.5-coder:latest"
}
```

**Response:**
```json
{
  "success": true
}
```

**Notes:**
- Both `url` and `model` are optional
- Changes take effect immediately for new conversations

### List Available Models

Get list of available Ollama models.

**Endpoint:** `GET /api/ollama/models`

**Response:**
```json
{
  "models": [
    "llama3.2:latest",
    "qwen2.5-coder:latest",
    "gemma3:latest",
    "gemma3:4b"
  ]
}
```

**Error Response (Ollama unreachable):**
```json
{
  "error": "Could not connect to Ollama server"
}
```

## Piper TTS

### List Available Voices

Get all available Piper TTS voices.

**Endpoint:** `GET /api/piper/voices`

**Response:**
```json
{
  "voices": [
    "en_US-lessac-medium",
    "en_US-amy-medium",
    "en_GB-alba-medium",
    "en_GB-northern_english_male-medium",
    ...
  ]
}
```

**Notes:**
- Returns 31 voices by default
- Voices are sorted alphabetically

### Get Current Voice

Get the currently selected voice.

**Endpoint:** `GET /api/piper/current`

**Response:**
```json
{
  "voice": "en_US-lessac-medium"
}
```

### Set Current Voice

Change the active TTS voice.

**Endpoint:** `POST /api/piper/current`

**Request Body:**
```json
{
  "voice": "en_GB-alba-medium"
}
```

**Response:**
```json
{
  "success": true
}
```

**Error Response (Invalid voice):**
```json
{
  "error": "Voice not found"
}
```

## Bot Persona

### Get Persona

Retrieve the current bot persona.

**Endpoint:** `GET /api/persona`

**Response:**
```json
{
  "persona": "You are a friendly pirate who loves to talk about sailing..."
}
```

**Notes:**
- Returns empty string if no persona is configured

### Save Persona

Update the bot's persona.

**Endpoint:** `POST /api/persona`

**Request Body:**
```json
{
  "persona": "You are a professional butler who speaks formally..."
}
```

**Response:**
```json
{
  "success": true
}
```

**Notes:**
- Use empty string to clear the persona
- Changes take effect immediately for new messages

### AI-Enhance Persona

Use Ollama to expand and improve a persona description.

**Endpoint:** `POST /api/persona/enhance`

**Request Body:**
```json
{
  "persona": "You are a pirate"
}
```

**Response:**
```json
{
  "enhanced_persona": "You are a seasoned pirate captain with decades of experience sailing the seven seas. Your speech is peppered with nautical terms and pirate slang like 'ahoy', 'matey', and 'arr'. You're friendly but tough, with a deep love for adventure and treasure hunting..."
}
```

**Error Responses:**

No persona provided:
```json
{
  "error": "No persona provided"
}
```

Ollama unavailable:
```json
{
  "error": "Failed to enhance persona"
}
```

**Notes:**
- Requires Ollama to be running and accessible
- Uses the currently configured Ollama model
- Typical response time: 5-10 seconds
- Does NOT automatically save the enhanced persona

## Conversation History

### Get Conversations

Retrieve recent conversation history.

**Endpoint:** `GET /api/conversations?limit=50`

**Query Parameters:**
- `limit` (optional) - Number of messages to return (default: 50)

**Response:**
```json
{
  "conversations": [
    {
      "user_name": "John",
      "user_session": 12345,
      "message_type": "voice",
      "role": "user",
      "message": "What's the weather like?",
      "timestamp": "2025-09-30T10:30:45"
    },
    {
      "user_name": "John",
      "user_session": 12345,
      "message_type": "voice",
      "role": "assistant",
      "message": "I don't have access to weather information.",
      "timestamp": "2025-09-30T10:30:50"
    }
  ]
}
```

**Fields:**
- `user_name` - Name of the Mumble user
- `user_session` - Mumble session ID
- `message_type` - Either "voice" or "text"
- `role` - Either "user" or "assistant"
- `message` - The message content
- `timestamp` - ISO 8601 formatted timestamp

### Reset Conversation History

Clear all conversation history from the database.

**Endpoint:** `POST /api/conversations/reset`

**Request Body:** None

**Response:**
```json
{
  "success": true
}
```

**Warning:** This operation is irreversible and deletes all conversation data.

## Error Handling

All endpoints use standard HTTP status codes:

- `200` - Success
- `400` - Bad request (invalid parameters)
- `404` - Resource not found
- `500` - Server error

Error responses follow this format:
```json
{
  "error": "Description of what went wrong"
}
```

## Rate Limiting

Currently, there is no rate limiting implemented. This may be added in future versions.

## Authentication

Currently, there is no authentication required. The control panel is designed for local network use. If exposing to the internet, implement reverse proxy authentication.

## CORS

CORS is not enabled by default. All requests must originate from the same host.

## Examples

### cURL Examples

Get statistics:
```bash
curl http://localhost:5002/api/stats
```

Change voice:
```bash
curl -X POST http://localhost:5002/api/piper/current \
  -H "Content-Type: application/json" \
  -d '{"voice": "en_GB-alba-medium"}'
```

Enhance persona:
```bash
curl -X POST http://localhost:5002/api/persona/enhance \
  -H "Content-Type: application/json" \
  -d '{"persona": "You are a wizard"}'
```

### Python Examples

```python
import requests

# Get statistics
response = requests.get('http://localhost:5002/api/stats')
stats = response.json()
print(f"Total messages: {stats['total_messages']}")

# Change Ollama model
requests.post('http://localhost:5002/api/ollama/config', json={
    'model': 'qwen2.5-coder:latest'
})

# Set persona
requests.post('http://localhost:5002/api/persona', json={
    'persona': 'You are a friendly robot assistant'
})
```

### JavaScript Examples

```javascript
// Get current voice
fetch('http://localhost:5002/api/piper/current')
  .then(response => response.json())
  .then(data => console.log('Current voice:', data.voice));

// Change voice
fetch('http://localhost:5002/api/piper/current', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({voice: 'en_US-amy-medium'})
});

// Get conversation history
fetch('http://localhost:5002/api/conversations?limit=10')
  .then(response => response.json())
  .then(data => console.log('Recent messages:', data.conversations));
```

## WebSocket Support

Currently, there is no WebSocket support. All communication is via HTTP REST API. Real-time updates are achieved through polling (the web UI refreshes stats every 10 seconds).

Future versions may include WebSocket support for real-time notifications.
