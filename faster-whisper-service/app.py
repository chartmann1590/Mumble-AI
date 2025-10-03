from flask import Flask, request, jsonify
from faster_whisper import WhisperModel
import os
import tempfile
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Initialize model
model_size = os.getenv('MODEL_SIZE', 'base')
device = os.getenv('DEVICE', 'cpu')

# Use int8 for CUDA (stable for GTX 1080), int8 for CPU
compute_type = "int8"

logging.info(f"Loading Whisper model: {model_size} on {device} with compute type {compute_type}")
model = WhisperModel(model_size, device=device, compute_type=compute_type)
logging.info("Model loaded successfully")


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy'}), 200


@app.route('/transcribe', methods=['POST'])
def transcribe():
    try:
        if 'audio' not in request.files:
            return jsonify({'error': 'No audio file provided'}), 400

        audio_file = request.files['audio']

        # Get optional language parameter from form data
        language = request.form.get('language', None)
        if language and language.lower() == 'auto':
            language = None  # None means auto-detect

        # Save to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as tmp_file:
            audio_file.save(tmp_file.name)
            tmp_path = tmp_file.name

        try:
            # Transcribe with beam_size=1 for faster performance
            # Pass language parameter if specified (None for auto-detection)
            segments, info = model.transcribe(tmp_path, beam_size=1, language=language)

            # Collect all segments
            text = ' '.join([segment.text for segment in segments])

            logging.info(f"Transcribed: {text} (language: {info.language})")

            return jsonify({
                'text': text.strip(),
                'language': info.language,
                'language_probability': info.language_probability
            }), 200

        finally:
            # Clean up temp file
            os.unlink(tmp_path)

    except Exception as e:
        logging.error(f"Transcription error: {str(e)}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
