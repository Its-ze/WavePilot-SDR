# WavePilot SDR

WavePilot SDR is a native, cross-platform RTL-SDR scanner and live listener for Windows and Linux. It opens as a desktop app on the computer with the SDR dongle attached and provides presets, scanning, spectrum, waterfall, live audio, and in-app updates.

## Features

- RTL-SDR receive path through `librtlsdr` / `rtlsdr.dll`
- Native Qt desktop UI with grouped receiver, audio, and action controls plus live spectrum and waterfall
- WavePilot app icon and brand treatment across desktop, shortcuts, launchers, and Pages
- Preset groups for NOAA weather, airband, FM broadcast, marine, ham, FRS/GMRS, MURS/business, and data channels
- Scan mode for strongest preset hits
- Real-time Listen Live mode for continuous WFM, NFM, and AM audio, with channel-select auto-listen plus Mute and Squelch controls
- Offline live transcript panel for analog speech channels when the Vosk model is installed
- In-app update check, install, and restart flow
- Windows installer that can download public RTL-SDR runtime DLLs, the transcript model, and launch Zadig for WinUSB driver setup
- Linux installer that can install `rtl-sdr` packages, transcript dependencies, the transcript model, and udev access rules

## Quick Install

Windows PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\scripts\install-windows.ps1
.\scripts\start-windows.ps1
```

Linux:

```bash
chmod +x scripts/install-linux.sh scripts/start-linux.sh
./scripts/install-linux.sh
./scripts/start-linux.sh
```

After startup, the WavePilot SDR desktop window opens directly.

## Windows Driver Notes

The app needs two separate Windows pieces:

- Runtime DLLs: the installer can download the public RTL-SDR Blog Windows release and copy `rtlsdr.dll` plus supporting DLLs into `.runtime/bin`.
- USB driver binding: the installer can download and launch public Zadig. Zadig needs administrator approval because it installs or replaces the USB driver. Select the RTL2838 / Bulk-In Interface 0 device and choose WinUSB.

If Windows still shows the dongle as a TV/media device or with a driver error, run the installer again with:

```powershell
.\scripts\install-windows.ps1 -InstallDriver
```

## Linux Driver Notes

On Linux, the installer uses your package manager when allowed:

- Debian/Ubuntu/Pop!_OS: `rtl-sdr`, `librtlsdr2` on Noble/24.04 or `librtlsdr0` on older releases, `libusb-1.0-0`
- Fedora: `rtl-sdr`, `rtl-sdr-devel`, `libusb1`
- Arch: `rtl-sdr`, `libusb`
- openSUSE: `rtl-sdr`, `libusb-1_0-0`

The optional udev rule allows non-root access to common Realtek `0bda:2832` and `0bda:2838` SDR dongles. Unplug and replug the dongle after installing the rule.

## In-App Updates

Use the `Updates` button in the desktop app. Installed copies check:

```text
https://its-ze.github.io/WavePilot-SDR/update.json
```

When an update is available, WavePilot downloads the public GitHub source archive, refreshes managed app files, runs the Python dependency install step, and asks for a restart. In-app apply is disabled when running from a git checkout so development work is not overwritten.

## Dev Auto-Sync

On a Windows development machine, you can keep the local checkout synced with GitHub using a scheduled task:

```powershell
.\scripts\install-windows-dev-autosync.ps1 -RunNow
```

The task runs every five minutes by default. In `AutoCommitAndPush` mode it pulls safe fast-forward changes from GitHub, auto-commits local edits with a timestamp, and pushes them back to `main`. It never force-pushes; if local and remote changes diverge, it skips and writes a log to `%LOCALAPPDATA%\WavePilotSDR\dev-sync.log`. Because this repository is public, the sync script refuses to auto-publish common secret-looking paths such as `.env`, key files, and files with `secret`, `token`, or `password` in the path.

## Live Transcript

WavePilot can transcribe analog speech from the same real-time audio stream used by Listen Live. The transcript is local/offline through Vosk and works best on clear WFM/NFM/AM voice signals. Encrypted, trunked, digital, or weak/noisy signals will not produce useful text.

The installers can download the public Vosk small English model into:

```text
.runtime/models/vosk-model-small-en-us-0.15
```

Set `WAVEPILOT_VOSK_MODEL` to use a different local Vosk model folder.

## Source And Licenses

WavePilot SDR is GPL-2.0-or-later so it remains compatible with the public RTL-SDR driver stack it uses at runtime.

Public dependency sources:

- Osmocom RTL-SDR: <https://osmocom.org/projects/rtl-sdr/wiki>
- Osmocom RTL-SDR source mirror: <https://github.com/osmocom/rtl-sdr>
- RTL-SDR Blog Windows driver releases: <https://github.com/rtlsdrblog/rtl-sdr-blog/releases>
- Zadig/libwdi: <https://zadig.akeo.ie/> and <https://github.com/pbatard/libwdi>
- NumPy: <https://numpy.org/>
- PySide: <https://doc.qt.io/qtforpython-6/>
- SciPy: <https://scipy.org/>
- sounddevice: <https://python-sounddevice.readthedocs.io/>
- Vosk: <https://alphacephei.com/vosk/>
- Vosk models: <https://alphacephei.com/vosk/models>

## Legal

WavePilot SDR is receive-only software. Only monitor radio traffic that is lawful for you to receive in your location.
