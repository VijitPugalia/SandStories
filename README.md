# SandStories

[![iOS Swift](https://img.shields.io/badge/iOS-Swift_6-orange.svg?style=flat&logo=swift)](Sources/SandStories)
[![Build IPA](https://github.com/VijitPugalia/SandStories/actions/workflows/build-ipa.yml/badge.svg)](https://github.com/VijitPugalia/SandStories/actions/workflows/build-ipa.yml)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**SandStories** is an iOS application designed for high-fidelity storytelling capture, synchronized LiDAR depth mapping, RGB video, hand pose tracking, audio recording, and 3D stroke data.

Designed with an **Apple Camera-inspired liquid glass UI**, SandStories enables researchers and creators to capture spatial sessions on hardware-accelerated iOS devices or Azure Kinect, export portable sessions, and analyze/visualize them offline using Godot and Python tooling.

---

## 🚀 Download Latest Release

The latest release `.ipa` build is automatically compiled and published via GitHub Actions:

📦 **[Download SandStories.ipa (Latest Build)](https://github.com/VijitPugalia/SandStories/releases/download/latest-ipa/SandStories.ipa)**

> **Note**: Open this link from Safari on your iPhone/iPad while logged into GitHub, then import the `.ipa` into **Sideloadly**, **LiveContainer**, **SideStore**, or install via [`xtool install`](#deployment-with-xtool).

---

## ✨ Features & Architecture

```text
📱 iPhone ARKit + LiDAR ──▶  Session Writer ──▶  manifest.json + depth/RGB/audio/strokes
   - Raw / smoothed depth       - Timestamp sync     - Offline Godot 3D visualization
   - Hardware RGB video         - Manifest index     - Python / SAM / OpenCV analysis
   - Hand pose tracking         - Export session     - Portable ZIP archives
```

* **Liquid Glass Interface**: Minimalist, non-intrusive capture UI with native iOS 26 glass effect chrome and explicit capture controls.
* **LiDAR Depth Pipeline**: Continuous high-fidelity Float32 depth stream (`sceneDepth` / `smoothedSceneDepth`) synchronized with hardware video frames.
* **Hand Pose Tracking**: Real-time 3D hand tracking and stroke point recording.
* **In-App Diagnostics**: Real-time telemetry, thermal alerts, valid pixel ratios, frame drop counts, and diagnostic logging.
* **Azure Kinect DK Support**: Optional dual-mode support via Windows recording pipeline for Azure Kinect depth sessions.
* **Offline 3D Sandbox & Processing**: Subproject in `Godot/` for interactive session replay, foreground object removal, and depth surface mesh reconstruction.

---

## 🛠️ Deployment & Building

SandStories is built using **Swift Package Manager (SwiftPM)** and deployed cross-platform via [`xtool`](https://github.com/VijitPugalia/xtool).

### 1. Build and Run on Connected Device
```bash
cd SandStories

# Build and launch directly on connected iOS device
xtool dev
```

### 2. Manual IPA Packaging
```bash
# Build release IPA
bash scripts/build_release_ipa.sh release

# Install to connected device
xtool install xtool/SandStories.ipa
```

---

## 📁 Repository Structure

```
SandStories/
├── Sources/SandStories/       # Primary iOS Swift app source code
│   ├── ContentView.swift      # Liquid Glass capture UI
│   ├── GlassChrome.swift      # iOS 26 glass effect chrome components
│   ├── DepthCaptureManager.swift # ARKit LiDAR depth recording engine
│   ├── HandPoseCaptureManager.swift # Vision hand tracking manager
│   ├── AppDiagnostics.swift   # Telemetry & diagnostic logging
│   └── ...
├── Godot/                     # Offline 3D session visualizer & Python tools
├── scripts/                   # CI scripts & Azure Kinect utilities
├── docs/                      # Technical documentation
├── PROJECT_CONTEXT.md         # Shared project memory & design guidelines
├── AGENTS.md                  # Development & code navigation instructions
└── Package.swift              # SwiftPM project configuration
```

---

## 📖 Documentation

* [**PROJECT_CONTEXT.md**](PROJECT_CONTEXT.md): Product decisions, LiDAR depth rules, UI guidelines, and device constraints.
* [**AGENTS.md**](AGENTS.md): Code review navigation and knowledge graph workflows.
* [**Azure Kinect Recording Guide**](docs/AZURE_KINECT_RECORDING.md): Instructions for capturing and converting Azure Kinect sessions.

---

## Contact

For questions about this software or the SandStories research, contact
Vijit Vijay Pugalia at [VijitPugalia@gmail.com](mailto:VijitPugalia@gmail.com).

---

## 📄 License

This repository is maintained for SandStories development. Source code is licensed under the [MIT License](LICENSE).
