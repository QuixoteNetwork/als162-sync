# ALS162 Sync

**ALS162 Sync** is an experimental tool designed to **decode the ALS162 radio time signal** and use it to **synchronize your computer’s clock**.

The program listens to an audio input, analyzes the signal received from ALS162, detects valid time frames, and extracts date and time information transmitted over radio. Once successfully decoded, it can compare this time with the system clock and help keep your PC synchronized without relying on an internet connection.

## Features

- Decoding of the ALS162 time signal  (accuracy +-1 second)
- Audio input from sound card, SDR receiver, or external radio  
- Tone detection and bit-level analysis  
- Automatic search for valid frames  
- Extraction of date and time from the received signal  
- System clock synchronization  
- Designed for offline use, amateur radio, and lab environments  

## Purpose

The goal of this project is to provide a simple way to synchronize a computer using a radio-based time reference, especially useful in offline scenarios or for experimentation with low-frequency time signals.
## Interfaces

ALS162 Sync is available in two versions:

- **TUI (Text User Interface):**  
  Lightweight and terminal-based, ideal for low-resource systems, remote access (SSH), or headless setups.

- **GUI (Graphical User Interface):**  
  User-friendly interface with visual elements, making it easier to monitor decoding status and interact with the application.

  
