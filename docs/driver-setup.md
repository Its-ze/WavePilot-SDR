# Driver Setup

## Windows

WavePilot SDR can install the app and Python dependencies without administrator rights. USB driver replacement is different: Windows requires approval before binding an RTL-SDR dongle to WinUSB.

Run:

```powershell
.\scripts\install-windows.ps1 -InstallDriver
```

The installer downloads public Zadig/libwdi, then launches it elevated. In Zadig:

1. Open `Options` and enable `List All Devices`.
2. Select `RTL2838UHIDIR`, `Bulk-In Interface 0`, or the matching Realtek RTL-SDR entry.
3. Choose `WinUSB`.
4. Click `Install Driver` or `Replace Driver`.
5. Unplug and replug the SDR dongle.

The installer also downloads public RTL-SDR Blog Windows runtime DLLs unless `-SkipDriverDlls` is passed.

## Linux

Run:

```bash
./scripts/install-linux.sh --udev
```

The installer can install system RTL-SDR packages and add udev rules for common Realtek devices:

- `0bda:2832`
- `0bda:2838`

Unplug and replug the dongle afterward. If a DVB kernel module claims the device on your distro, blacklist rules may still be needed; WavePilot does not write those automatically because some users still want TV tuner behavior.
