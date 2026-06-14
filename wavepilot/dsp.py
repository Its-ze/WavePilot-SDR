"""DSP helpers for spectrum, scanning, and audio demodulation."""

from __future__ import annotations

import math
import wave
from fractions import Fraction
from io import BytesIO

import numpy as np
from scipy import signal


def reduce_bins(values: np.ndarray, target=512):
    values = np.asarray(values, dtype=np.float32)
    if len(values) <= target:
        return [float(v) for v in values]
    usable = values[: (len(values) // target) * target]
    return [float(v) for v in usable.reshape(target, -1).mean(axis=1)]


def find_signal_peaks(freq_axis: np.ndarray, db: np.ndarray, limit=8):
    floor = float(np.percentile(db, 35))
    spread = max(3.0, float(np.percentile(db, 96) - floor))
    candidates, _ = signal.find_peaks(db, distance=max(8, len(db) // 96), prominence=spread * 0.18)
    ordered = sorted(candidates, key=lambda idx: float(db[idx]), reverse=True)[:limit]
    return [
        {
            "hz": float(freq_axis[idx]),
            "mhz": float(freq_axis[idx] / 1_000_000.0),
            "db": float(db[idx]),
            "snr": float(db[idx] - floor),
        }
        for idx in ordered
    ]


def spectrum_payload(samples: np.ndarray, center_hz: int, sample_rate: int, fft_size=2048):
    fft_size = int(max(512, min(8192, fft_size)))
    if len(samples) < fft_size:
        raise RuntimeError("not enough samples returned")

    usable = samples[: (len(samples) // fft_size) * fft_size].reshape(-1, fft_size)
    window = np.hanning(fft_size).astype(np.float32)
    spectra = np.fft.fftshift(np.fft.fft(usable * window, axis=1), axes=1)
    power = np.mean(np.abs(spectra) ** 2, axis=0)
    db = 10.0 * np.log10(power + 1e-12)
    db = db - float(np.percentile(db, 10))

    freq_axis = center_hz + np.linspace(-sample_rate / 2, sample_rate / 2, fft_size, endpoint=False)
    peak_idx = int(np.argmax(db))
    floor_db = float(np.percentile(db, 35))
    peak_db = float(db[peak_idx])

    return {
        "center_hz": int(center_hz),
        "sample_rate": int(sample_rate),
        "fft_size": fft_size,
        "freq_start_hz": float(freq_axis[0]),
        "freq_step_hz": float((freq_axis[-1] - freq_axis[0]) / max(1, len(freq_axis) - 1)),
        "bins": reduce_bins(db, 512),
        "peak_hz": float(freq_axis[peak_idx]),
        "peak_db": peak_db,
        "floor_db": floor_db,
        "snr_db": float(peak_db - floor_db),
        "peaks": find_signal_peaks(freq_axis, db),
    }


def rf_score(samples: np.ndarray):
    if len(samples) < 4096:
        return {"snr_db": 0.0, "peak_db": 0.0, "floor_db": 0.0}
    payload = spectrum_payload(samples[: min(len(samples), 32768)], 0, 1_000_000, 1024)
    return {
        "snr_db": float(payload["snr_db"]),
        "peak_db": float(payload["peak_db"]),
        "floor_db": float(payload["floor_db"]),
    }


def fm_discriminator(samples: np.ndarray):
    shifted = samples[1:] * np.conj(samples[:-1])
    return np.angle(shifted).astype(np.float32)


def am_envelope(samples: np.ndarray):
    audio = np.abs(samples).astype(np.float32)
    audio -= float(np.mean(audio))
    return audio


def lowpass(audio: np.ndarray, sample_rate: int, cutoff_hz: int):
    sos = signal.butter(5, cutoff_hz, "lowpass", fs=sample_rate, output="sos")
    return signal.sosfilt(sos, audio).astype(np.float32)


def highpass(audio: np.ndarray, sample_rate: int, cutoff_hz: int):
    sos = signal.butter(3, cutoff_hz, "highpass", fs=sample_rate, output="sos")
    return signal.sosfilt(sos, audio).astype(np.float32)


def deemphasis(audio: np.ndarray, sample_rate: int, tau=75e-6):
    if len(audio) == 0:
        return audio
    dt = 1.0 / sample_rate
    alpha = dt / (tau + dt)
    out = np.empty_like(audio)
    out[0] = audio[0]
    for idx in range(1, len(audio)):
        out[idx] = out[idx - 1] + alpha * (audio[idx] - out[idx - 1])
    return out


def demodulate_audio(samples: np.ndarray, sample_rate: int, mode: str):
    mode = (mode or "nfm").lower()
    if mode == "am":
        demod = am_envelope(samples)
    else:
        demod = fm_discriminator(samples)
        if mode == "wfm":
            demod = lowpass(demod, sample_rate, min(120_000, sample_rate // 3))

    ratio = Fraction(48_000, int(sample_rate)).limit_denominator(1000)
    audio = signal.resample_poly(demod, ratio.numerator, ratio.denominator).astype(np.float32)

    if mode == "wfm":
        audio = deemphasis(audio, 48_000)
        audio = lowpass(audio, 48_000, 15_000)
        audio = highpass(audio, 48_000, 60)
    elif mode == "am":
        audio = highpass(audio, 48_000, 250)
        audio = lowpass(audio, 48_000, 4_000)
    else:
        audio = highpass(audio, 48_000, 90)
        audio = lowpass(audio, 48_000, 4_800)

    if len(audio):
        audio -= float(np.mean(audio))
    return audio


def audio_metrics(audio: np.ndarray):
    audio = np.asarray(audio, dtype=np.float32)
    if len(audio) < 256:
        return {"rms": 0.0, "peak": 0.0, "flatness": 1.0, "tone_ratio": 0.0}

    centered = audio - float(np.mean(audio))
    rms = float(np.sqrt(np.mean(centered * centered)))
    peak = float(np.max(np.abs(centered)))
    windowed = centered * np.hanning(len(centered)).astype(np.float32)
    spectrum = np.abs(np.fft.rfft(windowed)) + 1e-9
    flatness = float(math.exp(float(np.mean(np.log(spectrum)))) / float(np.mean(spectrum)))
    tone_ratio = float(np.max(spectrum) / (np.mean(spectrum) + 1e-9))
    return {"rms": rms, "peak": peak, "flatness": flatness, "tone_ratio": tone_ratio}


def should_squelch(audio: np.ndarray, rf: dict, mode: str):
    metrics = audio_metrics(audio)
    snr = float(rf.get("snr_db", 0.0))
    rms = float(metrics.get("rms", 0.0))
    flatness = float(metrics.get("flatness", 1.0))
    if mode == "wfm":
        return snr < 4.0 or rms < 0.002
    return snr < 6.0 or rms < 0.003 or flatness > 0.62


def pcm_wav(audio: np.ndarray, sample_rate=48_000):
    audio = np.asarray(audio, dtype=np.float32)
    peak = float(np.max(np.abs(audio))) if len(audio) else 1.0
    peak = max(peak, 0.02)
    pcm = np.clip(audio / peak * 0.92, -1.0, 1.0)
    pcm16 = (pcm * 32767.0).astype("<i2")
    out = BytesIO()
    with wave.open(out, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm16.tobytes())
    return out.getvalue()
