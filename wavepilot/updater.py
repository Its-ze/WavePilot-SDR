"""Update checks and in-place installs for WavePilot SDR."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from . import __version__

APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_URL = "https://its-ze.github.io/WavePilot-SDR/update.json"
MANAGED_ENTRIES = [
    ".github",
    "docs",
    "scripts",
    "wavepilot",
    ".gitattributes",
    ".gitignore",
    "LICENSE.md",
    "README.md",
    "pyproject.toml",
    "requirements.txt",
]
ALLOWED_ARCHIVE_HOSTS = {"github.com", "codeload.github.com"}


class UpdateError(RuntimeError):
    pass


def manifest_url():
    return os.environ.get("WAVEPILOT_UPDATE_URL", DEFAULT_MANIFEST_URL)


def parse_version(value):
    parts = []
    for item in str(value).replace("-", ".").split("."):
        digits = "".join(ch for ch in item if ch.isdigit())
        parts.append(int(digits or 0))
    return tuple((parts + [0, 0, 0])[:3])


def fetch_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": f"WavePilot-SDR/{__version__}"})
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))


def is_git_checkout():
    return (APP_ROOT / ".git").exists()


def can_apply_updates():
    return not is_git_checkout()


def check_for_update():
    url = manifest_url()
    try:
        manifest = fetch_json(url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise UpdateError(f"Update check failed: {exc}") from exc

    latest = str(manifest.get("latest_version") or manifest.get("version") or "")
    if not latest:
        raise UpdateError("Update manifest does not declare latest_version")

    update_available = parse_version(latest) > parse_version(__version__)
    return {
        "ok": True,
        "current_version": __version__,
        "latest_version": latest,
        "update_available": update_available,
        "can_apply": can_apply_updates(),
        "app_root": str(APP_ROOT),
        "manifest_url": url,
        "source_zip_url": manifest.get("source_zip_url"),
        "release_page": manifest.get("release_page"),
        "commit": manifest.get("commit"),
        "notes": manifest.get("notes", []),
        "checked_at": time.time(),
        "apply_blocker": "Running from a git checkout; use git pull instead." if is_git_checkout() else None,
    }


def validate_archive_url(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_ARCHIVE_HOSTS:
        raise UpdateError("Update archive must be downloaded from the public GitHub repository")


def download_archive(url, destination):
    validate_archive_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": f"WavePilot-SDR/{__version__}"})
    with urllib.request.urlopen(request, timeout=60) as response:
        destination.write_bytes(response.read())


def find_source_root(extract_dir):
    for candidate in Path(extract_dir).iterdir():
        if candidate.is_dir() and (candidate / "wavepilot" / "__init__.py").exists():
            return candidate
    if (Path(extract_dir) / "wavepilot" / "__init__.py").exists():
        return Path(extract_dir)
    raise UpdateError("Downloaded archive did not contain a WavePilot SDR source tree")


def copy_entry(source, target):
    if target.exists():
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    if source.is_dir():
        shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".venv", ".runtime", ".git"))
    else:
        shutil.copy2(source, target)


def install_requirements():
    requirements = APP_ROOT / "requirements.txt"
    if not requirements.exists():
        return {"ran": False, "returncode": None}
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(requirements)],
        cwd=str(APP_ROOT),
        text=True,
        capture_output=True,
        timeout=360,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()[-6:]
        raise UpdateError("Dependency install failed: " + "\n".join(detail))
    return {"ran": True, "returncode": result.returncode}


def apply_update():
    if is_git_checkout():
        raise UpdateError("This copy is a git checkout. Use git pull instead of in-app update.")

    update = check_for_update()
    if not update["update_available"]:
        return {**update, "installed": False, "restart_required": False, "message": "Already up to date"}
    archive_url = update.get("source_zip_url")
    if not archive_url:
        raise UpdateError("Update manifest does not include source_zip_url")

    with tempfile.TemporaryDirectory(prefix="wavepilot-update-") as temp_dir:
        temp_path = Path(temp_dir)
        archive = temp_path / "source.zip"
        download_archive(archive_url, archive)
        extract_dir = temp_path / "src"
        extract_dir.mkdir()
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(extract_dir)
        source_root = find_source_root(extract_dir)

        for entry in MANAGED_ENTRIES:
            source = source_root / entry
            if source.exists():
                copy_entry(source, APP_ROOT / entry)

    pip_result = install_requirements()
    return {
        **update,
        "installed": True,
        "restart_required": True,
        "dependency_install": pip_result,
        "message": f"Installed WavePilot SDR {update['latest_version']}; restart to run it.",
    }


def restart_application():
    args = [sys.executable, "-m", "wavepilot"]
    kwargs = {"cwd": str(APP_ROOT), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen(args, **kwargs)
