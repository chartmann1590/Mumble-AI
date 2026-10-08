FROM python:3.11-slim

# pymumble 1.6.1 ships protos generated for protobuf 3.x; with protobuf 4/5 they only load
# through the pure-Python implementation.
ENV PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    libopus0 \
    libopus-dev \
    ffmpeg \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \
    pymumble \
    requests \
    numpy \
    opuslib \
    protobuf

# Copy application files
COPY bot.py .
COPY memory_manager.py .
COPY requirements.txt .

# Install pymumble first (has dependency issues)
RUN pip install --no-cache-dir pymumble==1.6.1

# Install other dependencies from requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Add health check script
RUN echo '#!/bin/bash\ncurl -f http://localhost:8080/health || exit 1' > /usr/local/bin/healthcheck.sh && \
    chmod +x /usr/local/bin/healthcheck.sh

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD /usr/local/bin/healthcheck.sh || exit 1

# Add restart policy and resource limits
LABEL restart.policy="unless-stopped"

CMD ["python", "-u", "bot.py"]
