import re
import shutil
import subprocess
import tempfile
import uuid
import unicodedata
from pathlib import Path

_whisper = None


def ffmpeg_executable():
    """Prefer a system FFmpeg; fall back to the packaged executable."""
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise RuntimeError("FFmpeg is missing. Install FFmpeg and add it to PATH, or install imageio-ffmpeg.") from exc
    return imageio_ffmpeg.get_ffmpeg_exe()


def extract_audio(video_path):
    wav_path = Path(tempfile.gettempdir()) / f"family_game_{uuid.uuid4().hex}.wav"
    try:
        subprocess.run([ffmpeg_executable(), "-y", "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000", str(wav_path)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise RuntimeError("FFmpeg could not be started. Install FFmpeg and add it to PATH.") from exc
    except subprocess.CalledProcessError as exc:
        wav_path.unlink(missing_ok=True)
        raise ValueError("Could not extract audio from this video. Make sure it contains a valid audio track.") from exc
    return str(wav_path)


def transcribe(wav_path):
    global _whisper
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("faster-whisper is required for Say It Right; install requirements.txt") from exc
    if _whisper is None:
        _whisper = WhisperModel("small", compute_type="int8")
    segments, info = _whisper.transcribe(wav_path, vad_filter=True, language=None)
    result = [{"start": float(s.start), "end": float(s.end), "text": s.text.strip()} for s in segments]
    return {"text": " ".join(s["text"] for s in result).strip(), "language": info.language, "segments": result}


def normalize(text):
    text = text.lower()
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn" and not 0x064B <= ord(ch) <= 0x065F and ord(ch) != 0x0670)
    text = text.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"}))
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def match(text, accepted_answers):
    try:
        from rapidfuzz import fuzz
    except ImportError as exc:
        raise RuntimeError("rapidfuzz is required for answer matching; install requirements.txt") from exc
    normalized_text = normalize(text)
    best_score, best_answer = 0, ""
    for answer in accepted_answers:
        normalized_answer = normalize(answer)
        score = max(fuzz.token_set_ratio(normalized_text, normalized_answer), fuzz.partial_ratio(normalized_text, normalized_answer))
        if score > best_score:
            best_score, best_answer = score, answer
    return float(best_score), best_answer


def music_stop_time(wav_path):
    try:
        import numpy as np
        import soundfile as sf
        samples, rate = sf.read(wav_path)
    except (ImportError, OSError):
        try:
            import wave
            import numpy as np
            with wave.open(str(wav_path), "rb") as wav:
                rate, count = wav.getframerate(), wav.getnframes()
                samples = np.frombuffer(wav.readframes(count), dtype=np.int16).astype(np.float32) / 32768
        except (ImportError, OSError):
            return None
    if getattr(samples, "ndim", 1) > 1:
        samples = samples.mean(axis=1)
    window = max(1, int(rate * 0.1))
    rms = [float((np.mean(samples[i:i + window] ** 2)) ** 0.5) for i in range(0, len(samples), window) if len(samples[i:i + window])]
    if len(rms) < 10:
        return None
    median = float(np.median(rms))
    if median == 0:
        return None
    below = 0
    for i, value in enumerate(rms):
        below = below + 1 if value < median * 0.25 else 0
        if below >= 10:
            return max(0.0, (i - 9) * 0.1)
    return None
