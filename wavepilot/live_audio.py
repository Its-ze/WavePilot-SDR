"""Continuous low-latency audio streaming for WavePilot SDR."""

from __future__ import annotations

import threading
import time
from contextlib import nullcontext

import numpy as np

from .dsp import demodulate_audio, rf_score, should_squelch, spectrum_payload
from .radio import manager
from .transcript import LiveTranscriber, TranscriptUnavailable, transcript_status

AUDIO_SAMPLE_RATE = 48_000


def receiver_sample_rate(mode: str) -> int:
    return 1_024_000 if (mode or "").lower() == "wfm" else 250_000


def receiver_chunk_samples(mode: str) -> int:
    return 32_768 if (mode or "").lower() == "wfm" else 8_192


def _condition_audio(audio: np.ndarray, gain_scale: float) -> tuple[np.ndarray, float]:
    audio = np.asarray(audio, dtype=np.float32)
    if len(audio) == 0:
        return audio, gain_scale

    audio -= float(np.mean(audio))
    rms = float(np.sqrt(np.mean(audio * audio)))
    desired = 0.14 / max(rms, 0.0008)
    desired = max(0.4, min(42.0, desired))
    gain_scale = gain_scale * 0.88 + desired * 0.12
    return np.clip(audio * gain_scale, -0.96, 0.96).astype(np.float32, copy=False), gain_scale


def stream_audio(
    center_hz: int,
    mode: str,
    gain_tenths_db=None,
    auto_gain=True,
    muted=False,
    volume=1.0,
    squelch=False,
    transcript=False,
    stop_event: threading.Event | None = None,
    on_status=None,
    on_spectrum=None,
    on_transcript=None,
):
    """Stream demodulated audio directly to the system output device.

    The loop keeps ownership of SDR reads while it is active and reports
    spectrum frames from the same IQ chunks, avoiding competing receiver reads.
    """
    stop_event = stop_event or threading.Event()
    mode = (mode or "nfm").lower()
    if mode not in {"wfm", "nfm", "am"}:
        raise ValueError(f"unsupported mode: {mode}")
    muted = bool(muted)
    volume = max(0.0, min(1.5, float(volume)))
    squelch = bool(squelch)
    if not muted and volume > 0:
        import sounddevice as sd
    else:
        sd = None
    transcriber_state = {"engine": None}
    transcriber_lock = threading.Lock()
    if transcript:
        if on_transcript:
            on_transcript({"type": "status", "ok": True, "loading": True, "text": "Loading transcript model.", **transcript_status()})

        def load_transcriber():
            try:
                engine = LiveTranscriber()
                if stop_event.is_set():
                    return
                with transcriber_lock:
                    transcriber_state["engine"] = engine
                if on_transcript:
                    on_transcript(
                        {
                            "type": "status",
                            "ok": True,
                            "text": f"Transcript ready: {engine.model_dir.name}",
                            **transcript_status(),
                        }
                    )
            except TranscriptUnavailable as exc:
                if on_transcript and not stop_event.is_set():
                    on_transcript({"type": "status", "ok": False, "text": str(exc), **transcript_status()})
            except Exception as exc:
                if on_transcript and not stop_event.is_set():
                    on_transcript({"type": "status", "ok": False, "text": f"Transcript failed: {exc}", **transcript_status()})

        threading.Thread(target=load_transcriber, name="WavePilotTranscriptLoader", daemon=True).start()
    elif on_transcript:
        on_transcript({"type": "status", "ok": True, "text": "Transcript off.", **transcript_status()})

    sample_rate = receiver_sample_rate(mode)
    chunk_samples = receiver_chunk_samples(mode)
    radio = manager.get()
    gain_scale = 4.0 if mode == "wfm" else 9.0
    last_rf = {"snr_db": 0.0, "peak_db": 0.0, "floor_db": 0.0}
    last_spectrum = 0.0
    last_status = 0.0
    chunks = 0
    started = time.monotonic()

    with radio.lock:
        radio.configure(
            center_hz=int(center_hz),
            sample_rate=sample_rate,
            gain_tenths_db=gain_tenths_db,
            auto_gain=auto_gain,
        )
        radio.lib.rtlsdr_reset_buffer(radio.dev)

    stream_context = (
        sd.OutputStream(samplerate=AUDIO_SAMPLE_RATE, channels=1, dtype="float32", latency="low")
        if sd is not None
        else nullcontext(None)
    )

    with stream_context as stream:
        if on_status:
            on_status(
                {
                    "state": "started",
                    "center_hz": int(center_hz),
                    "mode": mode,
                    "sample_rate": sample_rate,
                    "audio_rate": AUDIO_SAMPLE_RATE,
                    "muted": muted or volume <= 0,
                    "volume": volume,
                    "squelch": squelch,
                    "chunks": chunks,
                    "seconds": 0.0,
                }
            )

        while not stop_event.is_set():
            with radio.lock:
                samples = radio.read_iq(chunk_samples)

            now = time.monotonic()
            if chunks % 3 == 0:
                last_rf = rf_score(samples[: min(len(samples), 32768)])

            audio = demodulate_audio(samples, sample_rate, mode)
            rf_squelched = should_squelch(audio, last_rf, mode)
            if squelch and rf_squelched:
                audio = np.zeros_like(audio)
            else:
                audio, gain_scale = _condition_audio(audio, gain_scale)

            with transcriber_lock:
                transcriber = transcriber_state["engine"]
            if transcriber is not None and not rf_squelched:
                for event in transcriber.accept_audio(audio, AUDIO_SAMPLE_RATE):
                    if on_transcript:
                        on_transcript(event)

            if stream is not None and len(audio):
                if volume != 1.0:
                    audio = np.clip(audio * volume, -0.96, 0.96).astype(np.float32, copy=False)
                stream.write(audio.reshape(-1, 1))

            chunks += 1
            if on_spectrum and now - last_spectrum >= 0.34:
                payload = spectrum_payload(samples, int(center_hz), sample_rate, 2048)
                payload.update(
                    {
                        "ok": True,
                        "time": time.time(),
                        "device": radio.device_info(),
                        "gain_tenths_db": radio.gain_tenths_db,
                        "auto_gain": radio.auto_gain,
                        "audio_stream": True,
                    }
                )
                on_spectrum(payload)
                last_spectrum = now

            if on_status and now - last_status >= 0.8:
                on_status(
                    {
                        "state": "streaming",
                        "center_hz": int(center_hz),
                        "mode": mode,
                        "sample_rate": sample_rate,
                        "audio_rate": AUDIO_SAMPLE_RATE,
                        "muted": muted or volume <= 0,
                        "volume": volume,
                        "squelch": squelch,
                        "chunks": chunks,
                        "seconds": max(0.0, now - started),
                    }
                )
                last_status = now

    with transcriber_lock:
        transcriber = transcriber_state["engine"]
    if transcriber is not None and on_transcript:
        for event in transcriber.finish():
            on_transcript(event)

    if on_status:
        on_status(
            {
                "state": "stopped",
                "center_hz": int(center_hz),
                "mode": mode,
                "sample_rate": sample_rate,
                "audio_rate": AUDIO_SAMPLE_RATE,
                "muted": muted or volume <= 0,
                "volume": volume,
                "squelch": squelch,
                "chunks": chunks,
                "seconds": max(0.0, time.monotonic() - started),
            }
        )
