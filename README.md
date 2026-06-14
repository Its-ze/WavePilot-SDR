# WavePilot SDR

WavePilot SDR is a local, cross-platform RTL-SDR scanner and live listener for Windows and Linux. It runs a small local web app on the computer with the SDR dongle attached, then opens a modern browser UI for presets, scanning, spectrum, waterfall, and live audio.

## Features

- RTL-SDR receive path through `librtlsdr` / `rtlsdr.dll`
- Modern local browser UI with live spectrum and waterfall
- Preset groups for NOAA weather, airband, FM broadcast, marine, ham, FRS/GMRS, MURS/business, and data channels
- Scan mode for strongest preset hits
- Listen Live mode for WFM, NFM, and AM audio
- Windows installer that can download public RTL-SDR runtime DLLs and launch Zadig for WinUSB driver setup
- Linux installer that can install `rtl-sdr` packages and udev access rules

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

After startup, open:

```text
http://127.0.0.1:8795/
```

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

- Debian/Ubuntu: `rtl-sdr`, `librtlsdr0`, `libusb-1.0-0`
- Fedora: `rtl-sdr`, `rtl-sdr-devel`, `libusb1`
- Arch: `rtl-sdr`, `libusb`
- openSUSE: `rtl-sdr`, `libusb-1_0-0`

The optional udev rule allows non-root access to common Realtek `0bda:2832` and `0bda:2838` SDR dongles. Unplug and replug the dongle after installing the rule.

## Source And Licenses

WavePilot SDR is GPL-2.0-or-later so it remains compatible with the public RTL-SDR driver stack it uses at runtime.

Public dependency sources:

- Osmocom RTL-SDR: <https://osmocom.org/projects/rtl-sdr/wiki>
- Osmocom RTL-SDR source mirror: <https://github.com/osmocom/rtl-sdr>
- RTL-SDR Blog Windows driver releases: <https://github.com/rtlsdrblog/rtl-sdr-blog/releases>
- Zadig/libwdi: <https://zadig.akeo.ie/> and <https://github.com/pbatard/libwdi>
- NumPy: <https://numpy.org/>
- SciPy: <https://scipy.org/>

## Legal

WavePilot SDR is receive-only software. Only monitor radio traffic that is lawful for you to receive in your location.
