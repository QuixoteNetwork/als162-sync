<img width="300" height="300" alt="logo-small" src="https://github.com/user-attachments/assets/a12d84f1-e7d6-4aa0-99ee-51d3c2491fc3" />

# ALS162 GPS Sync
![License](https://img.shields.io/badge/license-MIT-green)  ![Python](https://img.shields.io/badge/python-3.9%2B-blue)  ![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20MacOS-lightgrey)  ![Status](https://img.shields.io/badge/status-active-success)

**ALS162 GPS Sync** is a tool designed to **synchronize your computer clock using radio and GPS time sources**, even completely offline.

The application can decode the **ALS162 radio time signal** and also synchronize time using an external **GPS receiver connected via serial port (NMEA GPS, Galileo, GLONASS, Baidu, GNSS and QZSS)**. In addition, the integrated mapping system allows the use of both **offline and online maps** with live GPS positioning.

ALS162 Time Signal: https://en.wikipedia.org/wiki/ALS162_time_signal

The program listens to an audio input, analyzes the signal received from ALS162, detects valid time frames, and extracts date and time information transmitted over radio. Once successfully decoded, it can compare this time with the system clock and help keep your PC synchronized without relying on an internet connection.

For GPS synchronization, **ALS162 GPS Sync** can read positioning and UTC time data directly from compatible serial GPS devices, providing an additional high-precision time reference source. The GPS module can also be used together with offline or online maps for navigation, monitoring, and portable field operation.

---
## ✨ Features

- Decoding of the ALS162 radio time signal (accuracy ± 200 ms)
- GPS time synchronization through serial/NMEA GPS receivers
- Offline and online map support with live GPS positioning
- Audio input from sound card, SDR receiver, or external radio
- Tone detection and bit-level analysis
- Automatic search for valid ALS162 frames
- Extraction of date and time from received radio signals
- System clock synchronization
- Compatible with portable and offline operation environments
- Designed for amateur radio, lab, emergency, and field use

## 🎯 Purpose

The goal of this project is to provide a simple and fully independent way to synchronize a computer using alternative time references such as low-frequency radio signals and GPS systems.

ALS162 GPS Sync is especially useful in:
- Offline environments
- Amateur radio experimentation
- Portable and field operations
- Emergency communications
- SDR and radio laboratories
- GPS-based navigation and mapping systems

By combining **ALS162 radio synchronization**, **GPS timing**, and **mapping capabilities**, the project offers a versatile toolkit for reliable timekeeping and positioning without depending on internet services.

If you like this work:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/M4M81CV1EX)

---
## 📡 Preliminary Setup

Before running the decoder, you must first tune and verify the ALS162 radio signal correctly.

### 1️⃣ Tune the Receiver

Configure your SDR or radio receiver with the following settings:

- **Mode:** USB
- **Signal Frequency:** `162 kHz`
- **Center Frequency:** `161.500 kHz`
- **Recommended Bandwidth:** `500 Hz – 1000 Hz`

These settings help isolate the ALS162 signal and improve decoding reliability.

### 2️⃣ Verify Signal Reception

Before launching the program, make sure the signal is actually being received.

The **minimum verification test** is simply listening to the audio output:

- You should be able to clearly recognize the characteristic ALS162 modulation by ear.
- If the signal cannot be identified audibly, the decoder will most likely fail to synchronize properly.
- Good reception quality is extremely important for reliable decoding and time synchronization.

---

## 📟 Interfaces

ALS162 Sync is available in two versions:

  - **TUI (Terminal User Interface):**  
  Lightweight and terminal-based, ideal for low-resource systems, remote access (SSH), or headless setups.

  - **GUI (Graphical User Interface): ALS162 GPS Sync (GPS & Maps included)**  
  User-friendly interface with visual elements, making it easier to monitor decoding status and interact with the application.
---

# GUI (Graphical User Interface): ALS162 GPS Sync

<img width="333" height="445" alt="GUI" src="https://github.com/user-attachments/assets/51b6a06b-b769-4bc9-9b66-5e73495e6ef5" />

## Option 1 (for Windows):
- Go to Releases section and Download the lastest version: https://github.com/QuixoteNetwork/als162-sync/releases

## Option 2 (Linux, MacOS and Windows):

### 1. Clone the repository

```bash
git clone https://github.com/QuixoteNetwork/ALS162-Sync.git
cd ALS162-Sync
```

### 2. 🐍 Create a virtual environment

#### Windows (PowerShell)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

If activation is blocked:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then activate again:

```powershell
.\venv\Scripts\Activate.ps1
```

---

#### Linux / macOS

```bash
python3 -m venv venv
source venv/bin/activate
```

---

### 3. 📥 Install dependencies

Install using `requirements-gui.txt`:

```bash
pip install -r requirements-gui.txt
```

---

# TUI (Terminal User Interface)
<img width="422" height="452" alt="tui" src="https://github.com/user-attachments/assets/1f496bc7-81f9-4dee-af15-56d59a149b1e" />


## 📦 Installation

### 1. Clone the repository

```bash
git clone https://github.com/QuixoteNetwork/ALS162-Sync.git
cd ALS162-Sync
```

---

### 2. 🐍 Create a virtual environment

#### Windows (PowerShell)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

If activation is blocked:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then activate again:

```powershell
.\venv\Scripts\Activate.ps1
```

---

#### Linux / macOS

```bash
python3 -m venv venv
source venv/bin/activate
```

---

### 3. 📥 Install dependencies

Install using `requirements.txt`:

```bash
pip install -r requirements.txt
```


## 🚀 Sum Up Usage

```bash
python als162_decoder.py --list
python als162_decoder.py --device 2 --verbose
python als162_decoder.py --device 2 --set-time
python als162_decoder.py --device 2 --record 180 capture.wav   # record 3 minutes
python als162_decoder.py --play capture.wav --verbose          # decode from WAV
python als162_decoder.py --simulate                           # synthetic self-test
```
---
## All Commands

### 🎙️ List audio devices

```bash
python als162-decoder.py --list
```

## 🚀 Run the TUI decoder

```bash
python als162-decoder.py --device 2 --verbose
```

## 🕒 Decode and set system time

```bash
python als162-decoder.py --device 2 --set-time
```

> Note: This **require** administrator/root privileges.

Linux / macOS:

```bash
sudo python3 als162-decoder.py --device 2 --set-time
```

Windows: run terminal as Administrator.


## 💾 Record audio (WAV)

```bash
python als162-decoder.py --device 2 --record 180 capture.wav
```


## ▶️ Decode from WAV file

```bash
python als162-decoder.py --play capture.wav --verbose
```

## 🧪 Synthetic self-test

```bash
python als162-decoder.py --simulate
```
---
If you like this work:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/M4M81CV1EX)
