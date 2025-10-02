FROM python:3.10-slim

WORKDIR /app

# Install minimal system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libopus0 \
    libopus-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    pymumble \
    numpy \
    opuslib \
    protobuf \
    requests \
    psycopg2-binary

# Copy application files
COPY bridge.py .
COPY config.py .

# Expose SIP port
EXPOSE 5060/udp
EXPOSE 5060/tcp

CMD ["python", "bridge.py"]
