"""Local HTTP server for WavePilot SDR."""

from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .presets import all_presets, flat_channels
from .radio import DEFAULT_CENTER_HZ, DEFAULT_SAMPLE_RATE, RadioError, manager

ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "static"


def json_response(payload, status=HTTPStatus.OK):
    return int(status), "application/json; charset=utf-8", json.dumps(payload).encode("utf-8")


def bytes_response(body, content_type, status=HTTPStatus.OK):
    return int(status), content_type, body


def parse_bool(value, default=False):
    if value is None:
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}


def first(query, key, default=None):
    value = query.get(key)
    if not value:
        return default
    return value[0]


def spectrum_params(query):
    center_mhz = float(first(query, "center_mhz", DEFAULT_CENTER_HZ / 1_000_000))
    sample_rate = int(float(first(query, "sample_rate", DEFAULT_SAMPLE_RATE)))
    gain_db = first(query, "gain_db")
    gain = int(float(gain_db) * 10) if gain_db not in {None, ""} else None
    auto_gain = parse_bool(first(query, "auto_gain", "1"), True)
    fft_size = int(float(first(query, "fft_size", 2048)))
    return {
        "center_hz": int(center_mhz * 1_000_000),
        "sample_rate": sample_rate,
        "gain_tenths_db": gain,
        "auto_gain": auto_gain,
        "fft_size": fft_size,
    }


def audio_params(query):
    center_mhz = float(first(query, "center_mhz", DEFAULT_CENTER_HZ / 1_000_000))
    mode = first(query, "mode", "nfm")
    seconds = float(first(query, "seconds", 0.72))
    gain_db = first(query, "gain_db")
    gain = int(float(gain_db) * 10) if gain_db not in {None, ""} else None
    auto_gain = parse_bool(first(query, "auto_gain", "1"), True)
    squelch = parse_bool(first(query, "squelch", "1"), True)
    return {
        "center_hz": int(center_mhz * 1_000_000),
        "mode": mode,
        "seconds": seconds,
        "gain_tenths_db": gain,
        "auto_gain": auto_gain,
        "squelch": squelch,
    }


class WavePilotHandler(BaseHTTPRequestHandler):
    server_version = "WavePilotSDR/0.1"

    def log_message(self, fmt, *args):
        if self.path.startswith("/api/spectrum"):
            return
        super().log_message(fmt, *args)

    def do_GET(self):
        try:
            status, content_type, body = self.route_get()
        except RadioError as exc:
            status, content_type, body = json_response({"ok": False, "error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
        except Exception as exc:
            status, content_type, body = json_response({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1")
        self.end_headers()
        self.wfile.write(body)

    def route_get(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path in {"/", "/index.html"}:
            return self.static_file("index.html")
        if path == "/healthz":
            return json_response({"ok": True, "time": time.time()})
        if path == "/api/status":
            return json_response(manager.status())
        if path == "/api/presets":
            return json_response({"ok": True, **all_presets()})
        if path == "/api/spectrum":
            return json_response(manager.get().spectrum(**spectrum_params(query)))
        if path == "/api/scan":
            group = first(query, "group", "weather")
            channels = flat_channels(group)
            return json_response(manager.get().scan_channels(channels))
        if path == "/api/audio":
            return bytes_response(manager.get().audio_clip(**audio_params(query)), "audio/wav")
        if path.startswith("/static/"):
            return self.static_file(path[len("/static/") :])
        return json_response({"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND)

    def static_file(self, relative):
        target = (STATIC_ROOT / relative).resolve()
        if not str(target).startswith(str(STATIC_ROOT.resolve())) or not target.exists() or not target.is_file():
            return json_response({"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND)
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        return bytes_response(target.read_bytes(), content_type)


def serve(host="127.0.0.1", port=8795, open_browser=True):
    server = ThreadingHTTPServer((host, int(port)), WavePilotHandler)
    url = f"http://{host}:{port}/"
    print(f"WavePilot SDR listening on {url}", flush=True)
    if open_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        manager.reset()
        server.server_close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run WavePilot SDR")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8795)
    parser.add_argument("--no-open", action="store_true", help="do not open the browser")
    parser.add_argument("--public", action="store_true", help="bind to 0.0.0.0 for LAN access")
    args = parser.parse_args(argv)
    host = "0.0.0.0" if args.public else args.host
    serve(host=host, port=args.port, open_browser=not args.no_open)


if __name__ == "__main__":
    main()
