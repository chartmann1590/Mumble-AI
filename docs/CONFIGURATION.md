# Configuration Guide

Complete configuration reference for Mumble AI Bot.

## Environment Variables

### Database Configuration

```bash
# PostgreSQL credentials
POSTGRES_USER=mumbleai
POSTGRES_PASSWORD=mumbleai123
POSTGRES_DB=mumble_ai
```

### Mumble Server

```bash
# Mumble server superuser password
MUMBLE_PASSWORD=changeme

# Bot username in Mumble
BOT_USERNAME=AI-Bot
BOT_PASSWORD=  # Optional, leave empty for no password
```

### Whisper Configuration

```bash
# Model size: tiny, base, small, medium, large
WHISPER_MODEL=base

# Device: cpu or cuda (requires GPU setup)
DEVICE=cpu
```

### Ollama Configuration

```bash
# Ollama server URL (host.docker.internal for local)
OLLAMA_URL=http://host.docker.internal:11434

# Default model to use
OLLAMA_MODEL=llama3.2:latest
```

## Web Control Panel

Access: `http://localhost:5002`

### Changing Ports

Edit `docker-compose.yml`:

```yaml
web-control-panel:
  ports:
    - "8080:5002"  # Change 8080 to your desired port
```

## Voice Configuration

### Adding More Voices

1. Find voices at https://github.com/rhasspy/piper/releases
2. Edit `web-control-panel/download_voices.py`
3. Add voice to VOICES list:
```python
("voice-name", "https://url-to-voice.onnx")
```
4. Rebuild: `docker-compose build web-control-panel`

### Changing Default Voice

Via web panel or directly in database:
```sql
UPDATE bot_config SET value = 'en_GB-alba-medium' WHERE key = 'piper_voice';
```

## Bot Behavior

### Silence Threshold

Edit `mumble-bot/bot.py`:
```python
self.silence_threshold = 1.5  # seconds
```

### Conversation History Limit

Edit `mumble-bot/bot.py`:
```python
history = self.get_conversation_history(user_name=user_name, limit=10)
```

## Database

### Connection Pool Size

Edit `mumble-bot/bot.py`:
```python
self.db_pool = psycopg2.pool.SimpleConnectionPool(
    1, 10,  # min, max connections
    ...
)
```

### Backup

```bash
docker exec mumble-ai-postgres pg_dump -U mumbleai mumble_ai > backup.sql
```

### Restore

```bash
cat backup.sql | docker exec -i mumble-ai-postgres psql -U mumbleai mumble_ai
```

## Audio Settings

### Whisper Model Trade-offs

| Model | RAM | Speed | Accuracy |
|-------|-----|-------|----------|
| tiny | ~1GB | Fastest | Low |
| base | ~1GB | Fast | Good |
| small | ~2GB | Medium | Better |
| medium | ~5GB | Slow | High |
| large | ~10GB | Slowest | Best |

### GPU Acceleration

Edit `docker-compose.yml` for faster-whisper service:

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

## Advanced Configuration

### Custom System Prompt

Modify `mumble-bot/bot.py` in `build_prompt_with_context`:

```python
# Add system prompt before persona
system_prompt = "You are a helpful AI assistant.\n"
full_prompt = system_prompt
```

### Logging Level

Edit each service's Python file:

```python
logging.basicConfig(level=logging.DEBUG)  # or INFO, WARNING, ERROR
```

### Network Configuration

Custom network settings in `docker-compose.yml`:

```yaml
networks:
  mumble-ai-network:
    driver: bridge
    ipam:
      config:
        - subnet: 172.25.0.0/16
```

## Security Hardening

### Add Authentication to Web Panel

Use nginx reverse proxy:

```nginx
location / {
    auth_basic "Restricted";
    auth_basic_user_file /etc/nginx/.htpasswd;
    proxy_pass http://localhost:5002;
}
```

### Environment Secrets

Use Docker secrets instead of .env:

```yaml
services:
  postgres:
    secrets:
      - postgres_password
secrets:
  postgres_password:
    file: ./secrets/postgres_password.txt
```

### Firewall Rules

Only expose necessary ports:
```bash
# Allow only from specific IP
ufw allow from 192.168.1.0/24 to any port 64738
ufw allow from 192.168.1.0/24 to any port 5002
```

## Performance Tuning

### Increase Max Connections

PostgreSQL config:
```ini
max_connections = 100
shared_buffers = 256MB
```

### Ollama Performance

```bash
# Use faster models for better responsiveness
OLLAMA_MODEL=llama3.2:1b  # Fastest
OLLAMA_MODEL=llama3.2:3b  # Balance
OLLAMA_MODEL=llama3.2:8b  # Best quality
```

### Memory Limits

Add to docker-compose.yml:

```yaml
services:
  mumble-bot:
    mem_limit: 2g
    memswap_limit: 2g
```

## Troubleshooting Configuration

### View Current Config

```bash
# Database config
docker exec mumble-ai-postgres psql -U mumbleai mumble_ai -c "SELECT * FROM bot_config;"

# Environment
docker exec mumble-bot env | grep OLLAMA
```

### Reset to Defaults

```bash
docker-compose down -v  # WARNING: Deletes all data
docker-compose up -d
```
