<div align="center">

# Ripple Charge Effect

[简体中文](/README.md)&nbsp;&nbsp;|&nbsp;&nbsp;English (Trans. by LLM)

</div>

> [!NOTE]
> This project was developed with the assistance of Gemini 3 Pro. Adapted for the Windows platform only.

## Introduction

Inspired by the Xiaomi HyperOS 3 charging animation.

This project implements a water ripple effect on Windows when connected to a power source, featuring `light distortion` and `chromatic aberration`.

### Preview

<img src="./doc/preview.png" width="80%">

## Features

* [x] Real-time calculated motion effects
* [x] All key parameters are adjustable
* [x] Automatically reads screen resolution and fills in default configurations on first run
* [x] Option to restore default settings to prevent configuration errors
* [x] Optimized to reduce black screen flickering (rare occurrences may still exist)
* [x] 6 presets for charging cable directions
* [x] Optional particle effects
* [x] Optional auto-start on boot
* [x] Optimized system tray appearance and logic
* [x] Advanced animation window layering (Z-order) handling
* [x] Startup efficiency optimization
* [x] i18n (Internationalization) support
* [x] And more...

## Usage

Download the latest version from [Releases](https://github.com/MrBocchi/RippleChargeEffect/releases).

## Build from Source

> Windows only. For reference.

```powershell
# Create a virtual environment
python -m venv venv

# Activate the virtual environment
.\venv\Scripts\Activate.ps1

# Install necessary dependencies
pip install -r requirements.txt
pip install pyinstaller

# Execute the build command
pyinstaller -F --noconsole --icon "assets/app.ico" --version-file "build/version_info_RippleChargeEffect.txt" RippleChargeEffect.py
```

Required dependency files in the executable directory:

```text
shader.glsl
config-default.json
assets/lightning.png
assets/app.ico
assets/tray_b.ico
assets/tray_w.ico
languages/zh-CN.json
languages/en.json
```
