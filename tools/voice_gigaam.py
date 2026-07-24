"""Локальная транскрибация голоса через GigaAM v3 int8 (ONNX) — бесплатно, без API.

Модель (`model.int8.onnx` + `vocab.txt`, ~214 МБ) вне git — лежит в
GIGAAM_MODEL_DIR (по умолчанию <repo>/models/giga-am-v3-int8). Требует
системный ffmpeg и пакеты numpy/soundfile/librosa/onnxruntime.
Порт из личного скрипта transcribe.py (GigaAM из Handy)."""
import os
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import numpy as np

MODEL_DIR = Path(os.environ.get(
    "GIGAAM_MODEL_DIR",
    str(Path(__file__).parent.parent / "models" / "giga-am-v3-int8"),
))

# Параметры модели GigaAM v3
SAMPLE_RATE = 16000
N_MELS = 64
N_FFT = 512
HOP_LENGTH = 160   # 10 мс
WIN_LENGTH = 400   # 25 мс
F_MIN = 0.0
F_MAX = 8000.0
BLANK_ID = 256     # <blk> для CTC
CHUNK_SECONDS = 30


def available() -> bool:
    """Готова ли локальная транскрибация: есть модель и ffmpeg."""
    model = MODEL_DIR / "model.int8.onnx"
    vocab = MODEL_DIR / "vocab.txt"
    if not (model.exists() and vocab.exists()):
        return False
    from shutil import which
    return which("ffmpeg") is not None


@lru_cache(maxsize=1)
def _load():
    """ONNX-сессия и словарь — загружаются один раз и кэшируются."""
    import onnxruntime as ort
    session = ort.InferenceSession(str(MODEL_DIR / "model.int8.onnx"))
    vocab = {}
    with open(MODEL_DIR / "vocab.txt", "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split(" ")
            if len(parts) == 2:
                vocab[int(parts[1])] = parts[0]
    return session, vocab


def _audio_to_mel(audio):
    import librosa
    mel = librosa.feature.melspectrogram(
        y=audio, sr=SAMPLE_RATE, n_mels=N_MELS, n_fft=N_FFT,
        hop_length=HOP_LENGTH, win_length=WIN_LENGTH, fmin=F_MIN, fmax=F_MAX, power=2.0,
    )
    return np.log(mel + 1e-9).astype(np.float32)  # [64, T]


def _ctc_greedy_decode(log_probs, vocab):
    indices = np.argmax(log_probs, axis=-1)
    tokens, prev = [], -1
    for idx in indices:
        if idx != prev and idx != BLANK_ID:
            tokens.append(vocab.get(int(idx), ""))
        prev = idx
    return "".join(tokens).replace("▁", " ").strip()


def _load_audio(audio_path: str):
    import soundfile as sf
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(audio_path), "-ar", str(SAMPLE_RATE),
             "-ac", "1", "-f", "wav", tmp_path],
            check=True, capture_output=True,
        )
        audio, _ = sf.read(tmp_path, dtype="float32")
        return audio
    finally:
        os.unlink(tmp_path)


def transcribe_voice_local(file_path) -> str:
    """Распознаёт аудиофайл локально через GigaAM. Возвращает текст (может быть пустым)."""
    session, vocab = _load()
    audio = _load_audio(file_path)

    chunk_size = CHUNK_SECONDS * SAMPLE_RATE
    overlap = SAMPLE_RATE  # 1 сек перекрытие
    results = []
    n_chunks = max(1, int(np.ceil(len(audio) / chunk_size)))
    for i in range(n_chunks):
        start = max(0, i * chunk_size - overlap)
        end = min(len(audio), (i + 1) * chunk_size)
        chunk = audio[start:end]
        if len(chunk) < HOP_LENGTH * 2:
            continue
        mel = _audio_to_mel(chunk)[np.newaxis, :, :]  # [1, 64, T]
        feat_len = np.array([mel.shape[2]], dtype=np.int64)
        outputs = session.run(["log_probs"], {"features": mel, "feature_lengths": feat_len})
        results.append(_ctc_greedy_decode(outputs[0][0], vocab))
    return " ".join(r for r in results if r).strip()
