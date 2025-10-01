FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libopus0 \
    libopus-dev \
    ffmpeg \
    git \
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
COPY requirements.txt .

# Install any additional requirements
RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "-u", "bot.py"]
