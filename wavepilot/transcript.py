"""Offline live speech transcription helpers for WavePilot SDR."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np
from scipy import signal

APP_ROOT = Path(__file__).resolve().parents[1]
MODEL_NAME = "vosk-model-small-en-us-0.15"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
DEFAULT_MODEL_DIR = APP_ROOT / ".runtime" / "models" / MODEL_NAME
TRANSCRIPT_SAMPLE_RATE = 16_000


class TranscriptUnavailable(RuntimeError):
    """Raised when live transcript cannot start."""


def model_candidates():
    explicit = os.environ.get("WAVEPILOT_VOSK_MODEL")
    if explicit:
        yield Path(explicit)
    yield DEFAULT_MODEL_DIR
    yield APP_ROOT / "models" / MODEL_NAME


def find_model_dir():
    for candidate in model_candidates():
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def transcript_status():
    model_dir = find_model_dir()
    return {
        "available": model_dir is not None,
        "model": str(model_dir) if model_dir else None,
        "model_name": MODEL_NAME,
        "model_url": MODEL_URL,
    }


def audio_to_pcm16(audio: np.ndarray, sample_rate: int):
    audio = np.asarray(audio, dtype=np.float32)
    if len(audio) == 0:
        return b""
    if int(sample_rate) != TRANSCRIPT_SAMPLE_RATE:
        ratio = TRANSCRIPT_SAMPLE_RATE / float(sample_rate)
        up = TRANSCRIPT_SAMPLE_RATE
        down = int(sample_rate)
        if ratio == 1.0:
            resampled = audio
        else:
            resampled = signal.resample_poly(audio, up, down).astype(np.float32)
    else:
        resampled = audio
    pcm = np.clip(resampled, -1.0, 1.0)
    return (pcm * 32767.0).astype("<i2").tobytes()


class LiveTranscriber:
    def __init__(self, model_dir=None):
        try:
            import vosk
        except Exception as exc:
            raise TranscriptUnavailable("Install the vosk Python package to enable live transcript.") from exc

        model_path = Path(model_dir) if model_dir else find_model_dir()
        if not model_path:
            raise TranscriptUnavailable(
                f"Transcript model missing. Re-run the installer or download {MODEL_NAME} into .runtime/models."
            )

        vosk.SetLogLevel(-1)
        self.model_dir = model_path
        self.model = vosk.Model(str(model_path))
        self.recognizer = vosk.KaldiRecognizer(self.model, TRANSCRIPT_SAMPLE_RATE)
        self.last_partial = ""

    def accept_audio(self, audio: np.ndarray, sample_rate: int):
        pcm = audio_to_pcm16(audio, sample_rate)
        if not pcm:
            return []

        events = []
        if self.recognizer.AcceptWaveform(pcm):
            text = (json.loads(self.recognizer.Result()).get("text") or "").strip()
            self.last_partial = ""
            if text:
                events.append({"type": "final", "text": text, "time": time.time()})
        else:
            partial = (json.loads(self.recognizer.PartialResult()).get("partial") or "").strip()
            if partial and partial != self.last_partial:
                self.last_partial = partial
                events.append({"type": "partial", "text": partial, "time": time.time()})
        return events

    def finish(self):
        text = (json.loads(self.recognizer.FinalResult()).get("text") or "").strip()
        if text:
            return [{"type": "final", "text": text, "time": time.time()}]
        return []
