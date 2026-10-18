# TG WS Proxy Launcher

**An Android app that runs a local Telegram proxy on your phone** and lets you control it with one button,
a home-screen shortcut or a quick-settings tile. Built on
[Flowseal/tg-ws-proxy](https://github.com/Flowseal/tg-ws-proxy) (MTProto → WebSocket), core v1.11.2.

[Русский](README.md) | English

<p align="center">
  <img src="docs/images/status.png" width="240" alt="Status">
  <img src="docs/images/settings.png" width="240" alt="Settings">
  <img src="docs/images/adb.png" width="240" alt="ADB tab">
</p>

> The in-app screenshots show the Russian UI; the app also has an English interface (Settings → Language).

## ⚠️ Photos / media not loading? Do this first

If messages work but **photos and videos do not load**, keep only one line in the `DC:IP` list:

1. Open **Settings** → field **“DC:IP, one per line (--dc-ip)”**.
2. **Delete all lines** and leave exactly:
   ```
   4:149.154.167.220
   ```
3. Tap **Save**, then **Status → Restart**.

If it gets worse, tap “Reset to defaults” in Settings.

## Features

- Runs as a **foreground service**, survives closing the app.
- **All core parameters** (`--port`, `--dc-ip`, `--secret`, Cloudflare domains, fake-TLS …) in the UI with validation.
- One-tap **proxy setup in Telegram** (`tg://proxy`).
- **Home-screen shortcut**: starts the proxy, then opens Telegram (works with the app fully closed).
- **Quick-settings tile** (like Wi-Fi/Bluetooth): lit = on, dark = off; toggles the whole app, including the battery saver.
- **Battery saver**: pauses the proxy while Telegram is not on screen and resumes it automatically.
- **Core updates from GitHub** without reinstalling, with automatic rollback.
- **ADB tab**: short guide + status check for disabling Android's background-process killer.

## Install

Download the APK from **[Releases](../../releases)** (or [build it yourself](docs/BUILD.md)). Requires Android 8.0+.

## First run

1. **System tab**: grant Notifications, request *ignore battery optimization*, open autostart settings (Xiaomi/Huawei/Samsung/Oppo/Vivo) and allow background work.
2. **Status tab** → **Start** (status becomes “Running”).
3. **Set up proxy in Telegram** → confirm in Telegram (server `127.0.0.1`, port `1443`) — once.
4. Optional: **Create shortcut** and **Add tile to quick settings** (Android 13+ shows a system prompt; on older versions use the shade's edit mode).

## Battery saver

Settings → *Battery saver* → enable, and grant **Usage access** once (the button opens the right screen).
The proxy pauses after Telegram has been continuously inactive for the chosen time (default 5 min) and resumes within 1–2 s
when you open Telegram. “Saver debug” shows live notifications for verifying this.

## Background-kill protection (ADB tab)

On a PC with adb and USB debugging enabled:

```bash
adb shell "settings put global settings_enable_monitor_phantom_procs false"
adb shell "device_config set_sync_disabled_for_tests persistent"
adb shell "device_config put activity_manager max_phantom_processes 2147483647"
adb shell pm grant org.tgwsproxy.tgwsproxy android.permission.READ_DEVICE_CONFIG
```

The last command only lets the app verify the limit. Open the ADB tab and tap “Check again”.

## Build

See [docs/BUILD.md](docs/BUILD.md) (GitHub Actions or manual build on Linux/WSL2, Russian) and [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## License

MIT, see [LICENSE](LICENSE). The proxy core is © Flowseal (MIT), see [THIRD_PARTY_LICENSES](THIRD_PARTY_LICENSES).
Unofficial project, not affiliated with Telegram.
