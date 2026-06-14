#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/share/wavepilot-sdr}"
REPOSITORY="${REPOSITORY:-Its-ze/WavePilot-SDR}"
YES=0
NO_SYSTEM=0
INSTALL_UDEV=0

for arg in "$@"; do
  case "$arg" in
    --yes|-y) YES=1 ;;
    --no-system) NO_SYSTEM=1 ;;
    --udev) INSTALL_UDEV=1 ;;
    --install-dir=*) INSTALL_DIR="${arg#*=}" ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

say() {
  printf '[WavePilot] %s\n' "$*"
}

confirm() {
  if [ "$YES" = "1" ]; then
    return 0
  fi
  printf '%s [y/N] ' "$1"
  read -r answer
  case "$answer" in
    y|Y|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

install_system_packages() {
  if [ "$NO_SYSTEM" = "1" ]; then
    say "Skipping system packages."
    return
  fi
  if ! confirm "Install Python and RTL-SDR packages with sudo if needed?"; then
    say "Skipping system package install."
    return
  fi

  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y python3 python3-venv python3-pip rtl-sdr librtlsdr0 libusb-1.0-0 portaudio19-dev
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3 python3-pip rtl-sdr rtl-sdr-devel libusb1 portaudio
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -Sy --needed python python-pip rtl-sdr libusb portaudio
  elif command -v zypper >/dev/null 2>&1; then
    sudo zypper install -y python3 python3-pip rtl-sdr libusb-1_0-0 portaudio
  else
    say "No supported package manager found. Install rtl-sdr/librtlsdr and Python venv support manually."
  fi
}

source_dir() {
  local script_root
  script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  if [ -f "$script_root/wavepilot/server.py" ]; then
    printf '%s\n' "$script_root"
    return
  fi

  local temp zip
  temp="$(mktemp -d)"
  zip="$temp/source.zip"
  curl -L "https://github.com/$REPOSITORY/archive/refs/heads/main.zip" -o "$zip"
  python3 - "$zip" "$temp" <<'PY'
import sys, zipfile
zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])
PY
  find "$temp" -mindepth 1 -maxdepth 1 -type d | head -n 1
}

copy_source() {
  local src="$1"
  mkdir -p "$INSTALL_DIR"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete --exclude .git --exclude .venv --exclude .runtime --exclude __pycache__ "$src/" "$INSTALL_DIR/"
  else
    cp -R "$src/." "$INSTALL_DIR/"
    rm -rf "$INSTALL_DIR/.git" "$INSTALL_DIR/.venv" "$INSTALL_DIR/.runtime"
  fi
}

install_python_deps() {
  python3 -m venv "$INSTALL_DIR/.venv"
  "$INSTALL_DIR/.venv/bin/python" -m pip install --upgrade pip wheel
  "$INSTALL_DIR/.venv/bin/python" -m pip install -r "$INSTALL_DIR/requirements.txt"
}

install_udev_rules() {
  if [ "$INSTALL_UDEV" != "1" ] && ! confirm "Install RTL-SDR udev access rules?"; then
    say "Skipping udev rules."
    return
  fi
  sudo tee /etc/udev/rules.d/20-wavepilot-rtlsdr.rules >/dev/null <<'RULES'
# WavePilot SDR - Realtek RTL2832/RTL2838 SDR dongles
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2832", MODE="0666", TAG+="uaccess"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", MODE="0666", TAG+="uaccess"
RULES
  sudo udevadm control --reload-rules || true
  sudo udevadm trigger || true
  say "Unplug and replug the RTL-SDR after installing udev rules."
}

install_launchers() {
  mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/512x512/apps"
  if [ -f "$INSTALL_DIR/wavepilot/assets/wavepilot-icon.png" ]; then
    cp "$INSTALL_DIR/wavepilot/assets/wavepilot-icon.png" "$HOME/.local/share/icons/hicolor/512x512/apps/wavepilot-sdr.png"
  fi
  cat > "$HOME/.local/bin/wavepilot-sdr" <<EOF
#!/usr/bin/env bash
cd "$INSTALL_DIR"
exec "$INSTALL_DIR/.venv/bin/python" -m wavepilot "\$@"
EOF
  chmod +x "$HOME/.local/bin/wavepilot-sdr"

  cat > "$HOME/.local/share/applications/wavepilot-sdr.desktop" <<EOF
[Desktop Entry]
Name=WavePilot SDR
Comment=RTL-SDR scanner and live listener
Exec=$HOME/.local/bin/wavepilot-sdr
Icon=wavepilot-sdr
Terminal=false
Type=Application
Categories=AudioVideo;HamRadio;
EOF
}

install_system_packages
SRC="$(source_dir)"
say "Installing from $SRC"
copy_source "$SRC"
install_python_deps
install_udev_rules
install_launchers

if command -v rtl_test >/dev/null 2>&1; then
  say "Quick rtl_test check:"
  rtl_test -t || true
fi

say "Installed to $INSTALL_DIR"
say "Start with: wavepilot-sdr"
