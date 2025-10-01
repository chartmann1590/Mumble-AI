FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \
    faster-whisper \
    flask \
    numpy

# Copy application files
COPY app.py .

# Create models directory
RUN mkdir -p /app/models

EXPOSE 5000

CMD ["python", "app.py"]
