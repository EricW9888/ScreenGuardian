# ScreenGuardian Dev (Tk)
Local webcam posture + screen distance monitor with a customtkinter UI (`screenguardian_dev.py`). All processing stays on device.  
[![CI](https://github.com/EricW9888/ScreenGuardian/actions/workflows/ci.yml/badge.svg)](https://github.com/EricW9888/ScreenGuardian/actions/workflows/ci.yml)



https://github.com/user-attachments/assets/4f151fc8-406b-4cf9-b860-e5c3bf0145ab



## Overview
ScreenGuardian Dev runs a live webcam loop to estimate posture and face-to-screen distance and trigger alerts. It is local-first: no raw video is uploaded or stored.

## Key points
- Posture/distance are calculated from MediaPipe landmarks (FaceMesh/Pose/Hands); face-touch and nail-biting alerts are heuristic layers on top.
- Real-time loop prioritizes UI responsiveness; Resource Saver processes every 3rd frame and skips overlay drawing when the window is minimized.
- SQLite stores alerts plus daily/hourly posture/distance aggregates; JSON stores config/calibration.

## Quickstart (≤5 minutes)
```bash
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python screenguardian_dev.py
```

## Architecture (high-level)
- Capture: OpenCV reads frames from the webcam (backend/index can be forced via env).
- Inference: MediaPipe FaceMesh/Pose/Hands return landmarks.
- Decisioning: Rules classify posture/distance/behaviors and trigger alerts; metrics accumulate.
- Persistence: SQLite stores alerts and daily/hourly aggregates; JSON stores config/calibration.
- UI: customtkinter renders video/dashboards; Resource Saver reduces draw/detect frequency when enabled.

## Data model (SQLite)
- Alerts: timestamp + message
- Daily totals: screen time, posture time, distance log (with counts)
- Hourly totals: screen time, posture time, distance sums (with counts)
- Startup: checks expected tables and merges duplicate day/hour rows into one (if present).

## Install & run
- Python 3.11+ with Tk support.
- Install deps: `pip install -r requirements.txt`
- Run: `python screenguardian_dev.py`

## Packaging (PyInstaller)
- mac: `pyinstaller --noconfirm --name "ScreenGuardianDev" --add-data "data:data" screenguardian_dev.py`
- Windows separator: `pyinstaller --noconfirm --name "ScreenGuardianDev" --add-data "data;data" screenguardian_dev.py`
- Outputs to `dist/ScreenGuardianDev/`; run `ScreenGuardianDev` / `ScreenGuardianDev.exe` from there. Runtime data is saved to the OS app-data directory (not inside `dist/`).

## Storage
- App data (config/DB/logs): macOS `~/Library/Application Support/ScreenGuardian/`; Windows `%AppData%\ScreenGuardian\`
- Assets: `data/`
- Stats exports: `stats/`

## Features
- Alerts: posture, distance, 20-20-20, nail biting (heuristic), face touch (heuristic)
- Calibration: card width + neutral pose capture
- Resource Saver: fewer frames processed (may reduce accuracy)
- Panic erase: wipe stored metrics/logs; optional calibration erase

## Tests & CI
- Smoke: `python -m pytest tests/test_smoke.py` (imports main entrypoints).
- CI runs on push/PR (see `.github/workflows/ci.yml`).

## Environment controls
- `SG_CAMERA_BACKEND`: `CAP_AVFOUNDATION` (macOS), `CAP_MSMF`/`CAP_DSHOW` (Windows), `CAP_ANY`
- `SG_CAMERA_INDEX`: integer camera index (default 0)

## Privacy & data
- Processing stays local; no video leaves your device.
- Stored data is limited to derived metrics/events and config/calibration in the app-data directory. No image or video data is ever stored.

## Known limits
- Webcam quality/lighting affects detection accuracy. (rare)
- CPU load depends on MediaPipe; Resource Saver lowers load at the cost of responsiveness.

## Troubleshooting
- No camera/detections: close other apps using the webcam; set `SG_CAMERA_BACKEND`/`SG_CAMERA_INDEX` if needed.
- MediaPipe install issues: `pip install "mediapipe==0.10.9"` (known version that works).
- `_tkinter` missing: use a Python build with Tk support.
