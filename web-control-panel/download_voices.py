import os
import urllib.request

# Comprehensive list of diverse Piper TTS voices with multiple accents and styles
VOICES = [
    # === US English - Female Voices ===
    ("en_US-lessac-medium", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx"),
    ("en_US-lessac-high", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/high/en_US-lessac-high.onnx"),
    ("en_US-amy-medium", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium/en_US-amy-medium.onnx"),
    ("en_US-amy-low", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/low/en_US-amy-low.onnx"),
    ("en_US-hfc_female-medium", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/hfc_female/medium/en_US-hfc_female-medium.onnx"),
    ("en_US-kristin-medium", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/kristin/medium/en_US-kristin-medium.onnx"),
    ("en_US-kathleen-low", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/kathleen/low/en_US-kathleen-low.onnx"),

    # === US English - Male Voices ===
    ("en_US-hfc_male-medium", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/hfc_male/medium/en_US-hfc_male-medium.onnx"),
    ("en_US-joe-medium", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/joe/medium/en_US-joe-medium.onnx"),
    ("en_US-bryce-medium", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/bryce/medium/en_US-bryce-medium.onnx"),
    ("en_US-danny-low", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/danny/low/en_US-danny-low.onnx"),
    ("en_US-john-medium", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/john/medium/en_US-john-medium.onnx"),
    ("en_US-kusal-medium", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/kusal/medium/en_US-kusal-medium.onnx"),

    # === US English - Multi-Speaker (includes diverse accents from L2 speakers) ===
    ("en_US-l2arctic-medium", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/l2arctic/medium/en_US-l2arctic-medium.onnx"),
    ("en_US-arctic-medium", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/arctic/medium/en_US-arctic-medium.onnx"),
    ("en_US-libritts_r-medium", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/libritts_r/medium/en_US-libritts_r-medium.onnx"),
    ("en_US-libritts-high", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/libritts/high/en_US-libritts-high.onnx"),

    # === British English - Female Voices ===
    ("en_GB-alba-medium", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/alba/medium/en_GB-alba-medium.onnx"),
    ("en_GB-jenny_dioco-medium", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/jenny_dioco/medium/en_GB-jenny_dioco-medium.onnx"),
    ("en_GB-southern_english_female-low", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/southern_english_female/low/en_GB-southern_english_female-low.onnx"),

    # === British English - Male Voices ===
    ("en_GB-northern_english_male-medium", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/northern_english_male/medium/en_GB-northern_english_male-medium.onnx"),
    ("en_GB-alan-low", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/alan/low/en_GB-alan-low.onnx"),
    ("en_GB-alan-medium", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/alan/medium/en_GB-alan-medium.onnx"),

    # === British English - Regional & Multi-Speaker ===
    ("en_GB-cori-medium", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/cori/medium/en_GB-cori-medium.onnx"),
    ("en_GB-cori-high", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/cori/high/en_GB-cori-high.onnx"),
    ("en_GB-semaine-medium", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/semaine/medium/en_GB-semaine-medium.onnx"),
    ("en_GB-aru-medium", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/aru/medium/en_GB-aru-medium.onnx"),
    ("en_GB-vctk-medium", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/vctk/medium/en_GB-vctk-medium.onnx"),
]

def download_voice(name, url):
    """Download a voice model and its config"""
    voices_dir = "/app/piper_voices"
    os.makedirs(voices_dir, exist_ok=True)

    model_path = os.path.join(voices_dir, f"{name}.onnx")
    config_path = os.path.join(voices_dir, f"{name}.onnx.json")

    if not os.path.exists(model_path):
        print(f"Downloading {name}...")
        try:
            urllib.request.urlretrieve(url, model_path)
            print(f"  ✓ Model downloaded")

            # Download config
            config_url = url + ".json"
            urllib.request.urlretrieve(config_url, config_path)
            print(f"  ✓ Config downloaded")
        except Exception as e:
            print(f"  ✗ Error: {e}")
    else:
        print(f"  → {name} already exists")

if __name__ == "__main__":
    print("Downloading Piper TTS voices...")
    print("=" * 50)

    for name, url in VOICES:
        download_voice(name, url)

    print("=" * 50)
    print("✓ Voice download complete!")
