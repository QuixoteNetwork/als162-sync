<img width="300" height="300" alt="logo-small" src="https://github.com/user-attachments/assets/a12d84f1-e7d6-4aa0-99ee-51d3c2491fc3" />

# ALS162 Sync

**ALS162 Sync** is an tool designed to **decode the ALS162 radio time signal** and use it to **synchronize your computer’s clock**.

ALS162 Time Signal: https://en.wikipedia.org/wiki/ALS162_time_signal

The program listens to an audio input, analyzes the signal received from ALS162, detects valid time frames, and extracts date and time information transmitted over radio. Once successfully decoded, it can compare this time with the system clock and help keep your PC synchronized without relying on an internet connection.

---
## ✨ Features

- Decoding of the ALS162 time signal  (accuracy +-1 second)
- Audio input from sound card, SDR receiver, or external radio  
- Tone detection and bit-level analysis  
- Automatic search for valid frames  
- Extraction of date and time from the received signal  
- System clock synchronization  
- Designed for offline use, amateur radio, and lab environments  

## 🎯 Purpose

The goal of this project is to provide a simple way to synchronize a computer using a radio-based time reference, especially useful in offline scenarios or for experimentation with low-frequency time signals.

If you like this work:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/M4M81CV1EX)

---

## 📟 Interfaces

ALS162 Sync is available in two versions:

  - **TUI (Terminal User Interface):**  
  Lightweight and terminal-based, ideal for low-resource systems, remote access (SSH), or headless setups.

  - **GUI (Graphical User Interface):**  
  User-friendly interface with visual elements, making it easier to monitor decoding status and interact with the application.
---

# GUI (Graphical User Interface)

<img width="332" height="445" alt="gui" src="https://github.com/user-attachments/assets/592d50eb-9c20-4909-a3d6-9c04e3b8f15e" />

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
