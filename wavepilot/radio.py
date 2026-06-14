"""RTL-SDR hardware access for WavePilot SDR."""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import platform
import threading
import time
from pathlib import Path

import numpy as np

from . import __version__

APP_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_BIN = APP_ROOT / ".runtime" / "bin"
DEFAULT_CENTER_HZ = 162_550_000
DEFAULT_SAMPLE_RATE = 1_024_000
MAX_READ_SAMPLES = 262_144


class RadioError(RuntimeError):
    """Raised for recoverable radio and dependency failures."""


def _candidate_libraries():
    explicit = os.environ.get("WAVEPILOT_RTLSDR_LIBRARY")
    if explicit:
        yield explicit

    system = platform.system().lower()
    if system == "windows":
        search_dirs = [
            RUNTIME_BIN,
            APP_ROOT / "bin",
            Path("C:/Program Files/SDR++"),
            Path("C:/Program Files (x86)/SDR++"),
            APP_ROOT.parent / "SDR Tools" / "SDRPlusPlus" / "sdrpp_windows_x64",
        ]
        for item in os.environ.get("PATH", "").split(os.pathsep):
            if item:
                search_dirs.append(Path(item))
        for directory in search_dirs:
            yield str(directory / "rtlsdr.dll")
    else:
        found = ctypes.util.find_library("rtlsdr")
        if found:
            yield found
        yield "librtlsdr.so.0"
        yield "librtlsdr.so"
        yield "/usr/local/lib/librtlsdr.so"


def load_rtlsdr():
    errors = []
    for candidate in _candidate_libraries():
        try:
            path = Path(candidate)
            if path.suffix.lower() == ".dll" and path.parent.exists() and hasattr(os, "add_dll_directory"):
                os.add_dll_directory(str(path.parent))
            if path.suffix.lower() == ".dll" and not path.exists():
                continue
            return ctypes.CDLL(str(candidate)), str(candidate)
        except OSError as exc:
            errors.append(f"{candidate}: {exc}")
    detail = "; ".join(errors[-4:]) if errors else "no candidate library found"
    raise RadioError(f"RTL-SDR library unavailable. Install librtlsdr or place rtlsdr.dll in .runtime/bin. {detail}")


class RtlSdrDevice:
    def __init__(self):
        self.lib, self.library_path = load_rtlsdr()
        self._declare()
        self.lock = threading.RLock()
        self.dev = ctypes.c_void_p()
        self.opened = False
        self.center_hz = DEFAULT_CENTER_HZ
        self.sample_rate = DEFAULT_SAMPLE_RATE
        self.gain_tenths_db = 0
        self.auto_gain = True
        self.last_error = None
        self._open()

    def _declare(self):
        self.lib.rtlsdr_get_device_count.restype = ctypes.c_uint32
        self.lib.rtlsdr_get_device_name.argtypes = [ctypes.c_uint32]
        self.lib.rtlsdr_get_device_name.restype = ctypes.c_char_p
        self.lib.rtlsdr_open.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint32]
        self.lib.rtlsdr_open.restype = ctypes.c_int
        self.lib.rtlsdr_close.argtypes = [ctypes.c_void_p]
        self.lib.rtlsdr_close.restype = ctypes.c_int
        self.lib.rtlsdr_set_center_freq.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self.lib.rtlsdr_set_center_freq.restype = ctypes.c_int
        self.lib.rtlsdr_set_sample_rate.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self.lib.rtlsdr_set_sample_rate.restype = ctypes.c_int
        self.lib.rtlsdr_set_tuner_gain_mode.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.lib.rtlsdr_set_tuner_gain_mode.restype = ctypes.c_int
        self.lib.rtlsdr_set_tuner_gain.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.lib.rtlsdr_set_tuner_gain.restype = ctypes.c_int
        self.lib.rtlsdr_reset_buffer.argtypes = [ctypes.c_void_p]
        self.lib.rtlsdr_reset_buffer.restype = ctypes.c_int
        self.lib.rtlsdr_read_sync.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        self.lib.rtlsdr_read_sync.restype = ctypes.c_int

    def _check(self, result, operation):
        if int(result) != 0:
            if operation == "open" and platform.system().lower() == "windows" and int(result) in {-12, -3, -5}:
                raise RadioError(
                    f"WinUSB driver needed for the RTL-SDR (open code {result}). "
                    "Run scripts/install-windows.ps1 -InstallDriver, choose WinUSB in Zadig, then replug."
                )
            raise RadioError(f"{operation} failed with code {result}")

    def _open(self):
        count = int(self.lib.rtlsdr_get_device_count())
        if count < 1:
            raise RadioError("No RTL-SDR device found")
        self._check(self.lib.rtlsdr_open(ctypes.byref(self.dev), 0), "open")
        self.opened = True
        self._apply_settings(reset=True)

    def close(self):
        with self.lock:
            if self.opened:
                self.lib.rtlsdr_close(self.dev)
                self.opened = False

    def device_info(self):
        count = int(self.lib.rtlsdr_get_device_count())
        name = ""
        if count:
            raw = self.lib.rtlsdr_get_device_name(0)
            name = raw.decode("utf-8", "replace") if raw else ""
        return {"count": count, "name": name or "RTL-SDR", "library": self.library_path}

    def _apply_settings(self, reset=False):
        self._check(self.lib.rtlsdr_set_sample_rate(self.dev, int(self.sample_rate)), "set sample rate")
        self._check(self.lib.rtlsdr_set_center_freq(self.dev, int(self.center_hz)), "set center frequency")
        if self.auto_gain:
            self._check(self.lib.rtlsdr_set_tuner_gain_mode(self.dev, 0), "set auto gain")
        else:
            self._check(self.lib.rtlsdr_set_tuner_gain_mode(self.dev, 1), "set manual gain mode")
            self._check(self.lib.rtlsdr_set_tuner_gain(self.dev, int(self.gain_tenths_db)), "set tuner gain")
        if reset:
            self.lib.rtlsdr_reset_buffer(self.dev)

    def configure(self, center_hz=None, sample_rate=None, gain_tenths_db=None, auto_gain=None):
        changed = False
        if center_hz is not None:
            center_hz = max(24_000_000, min(1_766_000_000, int(center_hz)))
            changed = changed or center_hz != self.center_hz
            self.center_hz = center_hz
        if sample_rate is not None:
            sample_rate = max(250_000, min(2_400_000, int(sample_rate)))
            changed = changed or sample_rate != self.sample_rate
            self.sample_rate = sample_rate
        if auto_gain is not None:
            auto_gain = bool(auto_gain)
            changed = changed or auto_gain != self.auto_gain
            self.auto_gain = auto_gain
        if gain_tenths_db is not None:
            gain_tenths_db = max(0, min(496, int(gain_tenths_db)))
            changed = changed or gain_tenths_db != self.gain_tenths_db
            self.gain_tenths_db = gain_tenths_db
        if changed:
            self._apply_settings(reset=True)

    def read_iq(self, sample_count):
        sample_count = int(max(4096, min(MAX_READ_SAMPLES, sample_count)))
        byte_count = sample_count * 2
        buf = (ctypes.c_ubyte * byte_count)()
        n_read = ctypes.c_int()
        result = self.lib.rtlsdr_read_sync(self.dev, buf, byte_count, ctypes.byref(n_read))
        if result != 0 or n_read.value <= 0:
            raise RadioError(f"read failed with code {result}, bytes {n_read.value}")
        raw = np.frombuffer(buf, dtype=np.uint8, count=n_read.value).astype(np.float32)
        if len(raw) % 2:
            raw = raw[:-1]
        iq = (raw[0::2] - 127.5) / 127.5 + 1j * ((raw[1::2] - 127.5) / 127.5)
        iq -= np.mean(iq)
        return iq.astype(np.complex64, copy=False)

    def read_iq_exact(self, sample_count):
        sample_count = int(max(4096, sample_count))
        chunks = []
        remaining = sample_count
        while remaining > 0:
            take = min(MAX_READ_SAMPLES, remaining)
            chunks.append(self.read_iq(take))
            remaining -= take
        return np.concatenate(chunks)

    def spectrum(self, center_hz=None, sample_rate=None, gain_tenths_db=None, auto_gain=None, fft_size=2048):
        from .dsp import spectrum_payload

        with self.lock:
            self.configure(center_hz=center_hz, sample_rate=sample_rate, gain_tenths_db=gain_tenths_db, auto_gain=auto_gain)
            sample_count = max(int(fft_size) * 8, 32768)
            samples = self.read_iq(sample_count)
            payload = spectrum_payload(samples, self.center_hz, self.sample_rate, fft_size)
            payload.update(
                {
                    "ok": True,
                    "time": time.time(),
                    "device": self.device_info(),
                    "gain_tenths_db": self.gain_tenths_db,
                    "auto_gain": self.auto_gain,
                }
            )
            return payload

    def scan_channels(self, channels, sample_rate=1_024_000, max_channels=40):
        from .dsp import rf_score

        with self.lock:
            original = (self.center_hz, self.sample_rate, self.gain_tenths_db, self.auto_gain)
            results = []
            try:
                self.sample_rate = int(sample_rate)
                self.auto_gain = True
                for channel in channels[:max_channels]:
                    self.center_hz = int(channel["hz"])
                    self._apply_settings(reset=True)
                    samples = self.read_iq(32768)
                    score = rf_score(samples)
                    results.append(
                        {
                            "name": channel["name"],
                            "group": channel["group"],
                            "group_id": channel["group_id"],
                            "mode": channel["mode"],
                            "hz": int(channel["hz"]),
                            "mhz": float(channel["mhz"]),
                            "snr_db": score["snr_db"],
                            "peak_db": score["peak_db"],
                        }
                    )
            finally:
                self.center_hz, self.sample_rate, self.gain_tenths_db, self.auto_gain = original
                self._apply_settings(reset=True)
            results.sort(key=lambda item: item["snr_db"], reverse=True)
            return {"ok": True, "time": time.time(), "results": results[:16], "scanned": len(results)}

    def audio_clip(self, center_hz, mode, seconds=0.72, gain_tenths_db=None, auto_gain=None, squelch=False):
        from .dsp import demodulate_audio, pcm_wav, rf_score, should_squelch

        mode = (mode or "nfm").lower()
        if mode not in {"wfm", "nfm", "am"}:
            raise RadioError(f"unsupported mode: {mode}")
        sample_rate = 1_024_000 if mode == "wfm" else 250_000
        with self.lock:
            self.configure(
                center_hz=int(center_hz),
                sample_rate=sample_rate,
                gain_tenths_db=gain_tenths_db,
                auto_gain=auto_gain,
            )
            samples = self.read_iq_exact(int(sample_rate * max(0.25, min(1.4, float(seconds)))))
            rf = rf_score(samples[: min(len(samples), 32768)])
            audio = demodulate_audio(samples, sample_rate, mode)
            if squelch and should_squelch(audio, rf, mode):
                audio = np.zeros_like(audio)
            return pcm_wav(audio)


class RadioManager:
    def __init__(self):
        self._radio = None
        self._error = None
        self._lock = threading.RLock()

    def get(self):
        with self._lock:
            if self._radio is not None:
                return self._radio
            try:
                self._radio = RtlSdrDevice()
                self._error = None
                return self._radio
            except Exception as exc:
                self._error = str(exc)
                raise RadioError(str(exc)) from exc

    def reset(self):
        with self._lock:
            if self._radio is not None:
                try:
                    self._radio.close()
                except Exception:
                    pass
            self._radio = None

    def status(self):
        with self._lock:
            try:
                radio = self.get()
                return {
                    "ok": True,
                    "app": "WavePilot SDR",
                    "version": __version__,
                    "radio_available": True,
                    "device": radio.device_info(),
                    "center_hz": radio.center_hz,
                    "sample_rate": radio.sample_rate,
                    "error": None,
                }
            except Exception as exc:
                return {
                    "ok": True,
                    "app": "WavePilot SDR",
                    "version": __version__,
                    "radio_available": False,
                    "device": None,
                    "center_hz": None,
                    "sample_rate": None,
                    "error": str(exc),
                }


manager = RadioManager()
