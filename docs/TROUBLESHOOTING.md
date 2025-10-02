# Troubleshooting Guide

Common issues and solutions for Mumble AI Bot.

## Service Issues

### Services Won't Start

**Symptom:** `docker-compose up -d` fails

**Solutions:**
```bash
# Check if ports are already in use
netstat -an | find "64738"  # Mumble
netstat -an | find "5002"   # Web Control Panel
netstat -an | find "8081"   # Mumble Web
netstat -an | find "5060"   # SIP Bridge

# Stop conflicting services
docker-compose down

# Remove old containers
docker-compose rm -f

# Rebuild and start
docker-compose up -d --build
```

### Container Keeps Restarting

**Symptom:** Container status shows "Restarting"

**Diagnosis:**
```bash
# Check logs
docker-compose logs [service-name]

# Common issues:
# - Database not ready
# - Missing environment variables
# - Port conflicts
```

**Solutions:**
```bash
# Wait for database
docker-compose up -d postgres
sleep 10
docker-compose up -d

# Check environment file
cat .env
```

## Bot Connection Issues

### Bot Can't Connect to Mumble

**Symptom:** Bot logs show connection errors

**Solutions:**
```bash
# Check Mumble server is running
docker-compose logs mumble-server

# Verify network
docker network inspect mumble-ai_mumble-ai-network

# Restart bot
docker-compose restart mumble-bot
```

### Bot Can't Connect to Ollama

**Symptom:** "Could not connect to Ollama" errors

**Solutions:**
```bash
# Check Ollama is running
curl http://localhost:11434/api/generate -d '{"model":"llama3.2","prompt":"test"}'

# Verify model is pulled
ollama list

# Pull model if missing
ollama pull llama3.2

# Check bot can reach host
docker exec mumble-bot ping host.docker.internal
```

## Audio Issues

### No Speech Recognition

**Symptom:** Bot doesn't respond to voice

**Solutions:**
```bash
# Check Whisper service
docker-compose logs faster-whisper
curl http://localhost:5000/health

# Test Whisper directly
curl -F "audio=@test.wav" http://localhost:5000/transcribe

# Restart Whisper
docker-compose restart faster-whisper
```

### Chipmunk Voice / Distorted Audio

**Symptom:** TTS sounds too fast or high-pitched

**Solution:**
This should be fixed with audio resampling. If it persists:

```bash
# Check FFmpeg is installed in bot container
docker exec mumble-bot ffmpeg -version

# Rebuild bot container
docker-compose build mumble-bot
docker-compose up -d mumble-bot
```

### No TTS Output

**Symptom:** Bot responds but no voice

**Solutions:**
```bash
# Check Piper service
docker-compose logs piper-tts
curl http://localhost:5001/health

# Verify voices are downloaded
docker exec piper-tts ls /app/models/*.onnx | wc -l

# Restart Piper
docker-compose restart piper-tts
```

## Web Control Panel Issues

### Can't Access Control Panel

**Symptom:** localhost:5002 not accessible

**Solutions:**
```bash
# Check service is running
docker-compose ps web-control-panel

# Check logs
docker-compose logs web-control-panel

# Verify port mapping
docker port web-control-panel

# Test from inside container
docker exec web-control-panel curl localhost:5002
```

### Changes Not Taking Effect

**Symptom:** Config changes don't work

**Solutions:**
```bash
# Verify database update
docker exec mumble-ai-postgres psql -U mumbleai mumble_ai -c "SELECT * FROM bot_config;"

# Restart bot to pick up changes
docker-compose restart mumble-bot

# Clear browser cache
Ctrl+Shift+R (hard refresh)
```

### AI Enhance Not Working

**Symptom:** Persona enhancement fails

**Solutions:**
```bash
# Check Ollama is accessible
curl http://localhost:11434/api/tags

# Verify model is loaded
ollama list

# Check control panel logs
docker-compose logs web-control-panel | grep enhance
```

## Database Issues

### Database Connection Refused

**Symptom:** "could not connect to database" errors

**Solutions:**
```bash
# Check PostgreSQL is healthy
docker-compose ps postgres

# Wait for database to be ready
docker-compose logs postgres | grep "ready"

# Restart database
docker-compose restart postgres

# Verify credentials
docker exec mumble-ai-postgres psql -U mumbleai mumble_ai -c "SELECT 1;"
```

### Conversation History Not Saving

**Symptom:** No history in control panel

**Solutions:**
```bash
# Check table exists
docker exec mumble-ai-postgres psql -U mumbleai mumble_ai -c "\d conversation_history"

# Check for errors
docker-compose logs mumble-bot | grep "Error saving message"

# Verify bot can connect
docker-compose logs mumble-bot | grep "Database connection pool"
```

## Performance Issues

### Slow Response Times

**Symptom:** Long delays between input and response

**Diagnosis:**
```bash
# Check each service response time
time curl http://localhost:5000/health
time curl http://localhost:5001/health
time curl http://localhost:11434/api/tags
```

**Solutions:**
```bash
# Use smaller Whisper model
WHISPER_MODEL=tiny  # in .env

# Use faster Ollama model
OLLAMA_MODEL=llama3.2:1b

# Check system resources
docker stats

# Limit container memory
# Add to docker-compose.yml:
mem_limit: 2g
```

### High Memory Usage

**Symptom:** System running out of RAM

**Solutions:**
```bash
# Check memory usage
docker stats

# Use smaller models
WHISPER_MODEL=tiny
OLLAMA_MODEL=llama3.2:1b

# Reduce history limit in bot.py
limit=5  # instead of 10

# Restart services
docker-compose restart
```

## Network Issues

### DNS Resolution Failed

**Symptom:** Services can't find each other

**Solutions:**
```bash
# Check Docker network
docker network ls
docker network inspect mumble-ai_mumble-ai-network

# Recreate network
docker-compose down
docker-compose up -d

# Use IP addresses instead of hostnames
docker inspect postgres | grep IPAddress
```

## Data Issues

### Lost All Configuration

**Symptom:** Settings reset after restart

**Solutions:**
```bash
# Check volumes exist
docker volume ls | grep mumble-ai

# Don't use -v flag when stopping
docker-compose down  # Good
# docker-compose down -v  # Bad - deletes volumes

# Restore from backup
cat backup.sql | docker exec -i mumble-ai-postgres psql -U mumbleai mumble_ai
```

### Voices Missing After Update

**Symptom:** Only 1 voice available

**Solutions:**
```bash
# Trigger voice download
docker exec web-control-panel python /app/download_voices.py

# Check volume
docker volume inspect mumble-ai_piper-voices

# Restart affected services
docker-compose restart piper-tts web-control-panel
```

## New Service Issues

### SIP Bridge Issues

#### SIP Call Not Answered

**Symptom:** Phone calls to SIP bridge are not answered

**Solutions:**
```bash
# Check SIP bridge logs
docker logs sip-mumble-bridge

# Verify SIP port is listening
netstat -an | grep 5060

# Check firewall rules
sudo ufw status | grep 5060

# Test SIP registration
docker logs sip-mumble-bridge | grep "SIP account created"
```

#### No Audio on SIP Call

**Symptom:** SIP call connects but no audio

**Solutions:**
```bash
# Check RTP ports are open
netstat -an | grep 10000

# Verify Mumble server connection
docker logs sip-mumble-bridge | grep "Connected to Mumble"

# Check audio conversion logs
docker logs sip-mumble-bridge | grep "Audio bridge"
```

#### SIP Bridge Can't Connect to Mumble

**Symptom:** SIP bridge fails to connect to Mumble server

**Solutions:**
```bash
# Check Mumble server is running
docker ps | grep mumble-server

# Test network connectivity
docker exec sip-mumble-bridge ping mumble-server

# Check Mumble server logs
docker logs mumble-server
```

### Web Client Issues

#### Web Client Not Loading

**Symptom:** localhost:8081 shows error or doesn't load

**Solutions:**
```bash
# Check web client container
docker ps | grep mumble-web

# Check logs
docker logs mumble-web

# Verify port mapping
docker port mumble-web

# Test connectivity
curl http://localhost:8081
```

#### Web Client Can't Connect to Mumble

**Symptom:** Web client loads but can't connect to Mumble server

**Solutions:**
```bash
# Check Mumble server is running
docker ps | grep mumble-server

# Test network connectivity
docker exec mumble-web ping mumble-server

# Check Mumble server logs
docker logs mumble-server

# Verify Mumble server configuration
docker exec mumble-server cat /etc/mumble-server.ini
```

#### Web Client Audio Issues

**Symptom:** No audio in web client

**Solutions:**
```bash
# Check browser console for errors
# Open Developer Tools (F12) and check Console tab

# Verify microphone permissions
# Check browser microphone settings

# Test with different browser
# Try Chrome/Chromium for best compatibility

# Check WebRTC support
# Visit https://webrtc.github.io/samples/src/content/devices/input-output/
```

### Mumble Web Simple Build Issues

#### Build Fails

**Symptom:** `npm run build` fails

**Solutions:**
```bash
# Check Node.js version
node --version  # Should be >= 22.0.0

# Clean and reinstall
cd mumble-web-simple
rm -rf node_modules package-lock.json
npm ci

# Check for specific errors
npm run build 2>&1 | tee build.log
```

#### Build Succeeds But Client Doesn't Work

**Symptom:** Build completes but web client has issues

**Solutions:**
```bash
# Check if dist folder was created
ls -la mumble-web-simple/dist/

# Verify all files are present
ls -la mumble-web-simple/dist/app/

# Test with development build
npm run build:dev
```

## Common Error Messages

### "relation 'bot_config' does not exist"

**Cause:** Database not initialized

**Solution:**
```bash
# Re-run init script
docker exec -i mumble-ai-postgres psql -U mumbleai mumble_ai < init-db.sql

# Or recreate database
docker-compose down -v
docker-compose up -d
```

### "ECONNREFUSED 127.0.0.1:11434"

**Cause:** Ollama not accessible

**Solution:**
```bash
# Start Ollama
ollama serve

# Check it's running
curl http://localhost:11434/api/tags

# Verify from container
docker exec mumble-bot curl host.docker.internal:11434/api/tags
```

### "ffmpeg: not found"

**Cause:** FFmpeg not installed in bot container

**Solution:**
```bash
# Rebuild bot
docker-compose build mumble-bot
docker-compose up -d mumble-bot

# Verify installation
docker exec mumble-bot ffmpeg -version
```

### "SIP account creation failed"

**Cause:** SIP bridge can't create SIP account

**Solution:**
```bash
# Check port 5060 is available
netstat -an | grep 5060

# Restart SIP bridge
docker-compose restart sip-mumble-bridge

# Check logs for specific error
docker logs sip-mumble-bridge | grep -i error
```

### "WebRTC connection failed"

**Cause:** Web client can't establish WebRTC connection

**Solution:**
```bash
# Check Mumble server is accessible
docker exec mumble-web ping mumble-server

# Verify Mumble server configuration
docker exec mumble-server cat /etc/mumble-server.ini | grep -i webrtc

# Check browser compatibility
# Try Chrome/Chromium browser
```

## Debug Mode

Enable detailed logging:

```bash
# Edit service files, set logging level
logging.basicConfig(level=logging.DEBUG)

# Rebuild and restart
docker-compose build [service]
docker-compose up -d [service]

# Monitor logs
docker-compose logs -f [service]
```

## Complete Reset

If all else fails:

```bash
# FULL RESET - WARNING: Deletes all data
docker-compose down -v
docker system prune -a
rm -rf mumble-data/

# Start fresh
docker-compose up -d --build
```

## Getting Help

1. Check logs: `docker-compose logs`
2. Search issues on Gitea
3. Include in report:
   - Error messages
   - Service logs
   - Docker version
   - System info
