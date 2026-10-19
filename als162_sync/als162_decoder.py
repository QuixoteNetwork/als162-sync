#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ALS162 Time Signal Decoder (v2 — protocolo correcto)
====================================================
Decodifica la señal horaria francesa ALS162 (transmisor de Allouis, 162 kHz).
Pensado para receptores SDR en modo USB cuya salida de audio se inyecta por
la entrada de línea/micrófono del PC.

PROTOCOLO REAL DE ALS162 (corregido respecto a la primera versión):
-------------------------------------------------------------------
- La portadora de 162 kHz **siempre está presente** (no hay corte de portadora).
- La información se transmite por **modulación de fase** ±1 rad inaudible.
- Un "elemento de señal" es un pulso triangular de 100 ms:
      Rampa A (25 ms): fase   0 → +1 rad
      Rampa B (50 ms): fase  +1 → -1 rad   ← cruce por cero = inicio del segundo UTC
      Rampa C (25 ms): fase  -1 →  0 rad
- Codificación de bit:
      bit "0"  ⇒ UN  pulso al inicio del segundo
      bit "1"  ⇒ DOS pulsos consecutivos (200 ms en total)
- El **segundo 59** de cada minuto NO lleva pulso → marcador de fin de minuto.
- Frame: 59 bits útiles (segundos 0..58), idéntico a DCF77 a partir del bit 15.

Layout de bits (segundos del minuto):
  bit  0      siempre 0 (start of minute)
  bit  1      aviso leap second positivo
  bit  2      aviso leap second negativo
  bits 3..6   reservados
  bits 7..12  no usados (siempre 0)
  bit 13      día anterior a festivo
  bit 14      día festivo
  bit 15      operación anómala del transmisor
  bit 16      anuncio cambio de hora (último 60 min antes del cambio)
  bit 17      1 = UTC+2 (CEST, verano)
  bit 18      1 = UTC+1 (CET,  invierno)   (bits 17/18 son complementarios)
  bit 19      aviso leap second (compatibilidad DCF77)
  bit 20      siempre 1 (start of time encoding)
  bits 21..27 minutos  (BCD, LSB primero)
  bit 28      paridad par sobre bits 21..27
  bits 29..34 horas    (BCD)
  bit 35      paridad par sobre bits 29..34
  bits 36..41 día del mes (BCD)
  bits 42..44 día de la semana (1=Lun..7=Dom)
  bits 45..49 mes      (BCD)
  bits 50..57 año      (BCD, 2 dígitos)
  bit 58      paridad par sobre bits 36..58
  bit 59      sin pulso → marcador de minuto

Método de detección:
  1) Auto-detecta la frecuencia exacta de la portadora en el audio (FFT).
  2) Mezcla a banda base: y(t) = x(t) · exp(-j·2π·fc·t).
  3) Filtro paso bajo (≈100 Hz) para preservar el ancho de banda del pulso.
  4) Fase instantánea desenrollada y detrendada (elimina deriva residual).
  5) Correlación con plantilla triangular de 100 ms → posición de cada pulso.
  6) Histograma de pulsos mod 1 s → fija el origen del segundo (timing recovery).
  7) Clasifica cada segundo: 0 pulsos = marcador, 1 = bit 0, 2 = bit 1.
  8) Tras el marcador acumula 59 bits y decodifica BCD.

"""

import sys
import time
import wave
import argparse
import threading
from collections import deque
from datetime import datetime

try:
    import numpy as np
except ImportError:
    sys.exit("Falta numpy: pip install numpy")

try:
    from scipy.signal import butter, sosfiltfilt, find_peaks
except ImportError:
    sys.exit("Falta scipy: pip install scipy")

try:
    import pyaudio
except ImportError:
    pyaudio = None  # solo necesario para captura en vivo


# ── Idioma de salida (modificable desde CLI con --lang) ───────────────────────
_LANG = 'en'   # 'en' | 'es'

_TUI = {
    'en': {
        # detect_carrier_live
        'measuring':        'Measuring carrier ({s}s)',
        # sdr_report
        'sdr_header':       'SDR Signal Report  ({sr} Hz)',
        'rms_level':        'RMS Level   :',
        'clipping':         'Clipping    :',
        'reduce_gain':      '⚠  Reduce gain',
        'no_clip':          '✓  No clipping',
        'carrier_lbl':      'Carrier     :',
        'snr_lbl':          'Est. SNR    :',
        'snr_good':         '✓  Good',
        'snr_low':          '⚠  Low (<20 dB)',
        'spectrum_hdr':     'Spectrum 300-900 Hz:',
        'carrier_marker':   '← carrier',
        'top_peaks':        'Top peaks in band:',
        'tip_low':          ('🔴  Signal too weak.\n'
                             '    → Increase SDR RF/IF gain (SDR#, GQRX, SDR++).\n'
                             '    → Or raise line volume in OS mixer.'),
        'tip_high':         ('🟡  Signal clipping (phase distortion likely).\n'
                             '    → Reduce SDR RF gain or line volume.\n'
                             '    → Target range: −45 to −10 dBFS.'),
        'tip_ok':           '🟢  Level OK. Decoding should work.',
        'tip_snr_primary':  ('🟡  Level in range but SNR too low (<15 dB).\n'
                             '    Decoding may be unreliable. Possible causes:\n'
                             '    · Interference near 510 Hz → check SDR USB mode\n'
                             '    · RF gain too high → raises noise floor\n'
                             '    · Antenna too short for 162 kHz'),
        'tip_clip_warn':    '\n    ⚠  Digital clipping: {p:.1f}% of samples saturated.',
        'tip_snr_warn':     ('\n    ⚠  Low SNR (<15 dB). Possible causes:\n'
                             '    · Interference near 510 Hz → check SDR USB mode\n'
                             '    · RF gain too high → raises noise floor\n'
                             '    · Antenna too short for 162 kHz'),
        # periodic level
        'level_lbl':        'Level',
        'level_weak':       '🔴 weak    — increase SDR gain',
        'level_clip':       '🟡 clipping — reduce SDR gain',
        'level_ok':         '🟢 OK',
        # set_system_time
        'time_unknown_os':  '[ALS162] Unrecognized OS for time adjustment: {os}',
        'time_ok':          '[ALS162] ✔ System time set → {dt} (local)',
        'time_fail':        '[ALS162] ✗ Could not set time: {err}',
        'time_sudo':        '          (missing sudo or root privileges?)',
        'time_admin':       '          (run as Administrator or enable "Run as admin")',
        'time_notfound':    '[ALS162] ✗ Command not found: {exc}',
        'time_error':       '[ALS162] ✗ Unexpected error setting time: {exc}',
        # run_offline_wav
        'wav_info':         '[ALS162] WAV: {dur:.1f}s @ {sr} Hz',
        'carrier_det':      '[ALS162] Carrier detected: {fc:.3f} Hz',
        'offline_done':     '[ALS162] Offline: {bits} bits, {frames} frame(s) decoded.',
        # run_live
        'live_info':        '[ALS162] Device {dev} @ {sr} Hz | Carrier: {fc:.3f} Hz',
        'live_wait':        '[ALS162] Capturing… (waiting ~70 s for first frame).{stop}',
        'live_ctrlc':       '\n[INFO] Ctrl + C to Stop and Exit.',
        'live_autoclose':   '\n[INFO] Will close automatically after setting time.',
        'live_done':        '[ALS162] Stopped. {bits} bits emitted, {frames} frame(s) decoded.',
        # record_wav
        'rec_start':        '[ALS162] Recording {s}s to {p}...',
        'rec_progress':     '  {i}s / {total}s',
        'rec_done':         '[ALS162] Recording saved to {p}',
        # list_devices
        'dev_name':         'Name',
        'dev_inputs':       'Inputs',
        # run_simulate
        'sim_start':        '[ALS162] Synthetic self-test',
        'sim_gen':          '[ALS162] Generating synthetic signal for {dt} (DST=on)',
        'sim_carrier':      '[ALS162] Carrier in synthetic signal: {fc:.3f} Hz (expected 510.000)',
        'sim_fail_none':    '[ALS162] FAIL: no frame decoded',
        'sim_fail_inv':     '[ALS162] FAIL: invalid frame: {err}',
        'sim_fail_time':    '[ALS162] FAIL: decoded time differs from expected',
        'sim_ok':           '[ALS162] ✔ Self-test OK',
        # default_on_frame
        'dst_yes':          'Yes (summer)',
        'dst_no':           'No (winter)',
    },
    'es': {
        # detect_carrier_live
        'measuring':        'Midiendo portadora ({s}s)',
        # sdr_report
        'sdr_header':       'Informe de señal SDR  ({sr} Hz)',
        'rms_level':        'Nivel RMS   :',
        'clipping':         'Saturación  :',
        'reduce_gain':      '⚠  Reducir ganancia',
        'no_clip':          '✓  Sin recorte',
        'carrier_lbl':      'Portadora   :',
        'snr_lbl':          'SNR estimado:',
        'snr_good':         '✓  Bueno',
        'snr_low':          '⚠  Bajo (<20 dB)',
        'spectrum_hdr':     'Espectro 300-900 Hz:',
        'carrier_marker':   '← portadora',
        'top_peaks':        'Top picos en banda:',
        'tip_low':          ('🔴  Señal demasiado débil.\n'
                             '    → Sube la ganancia RF/IF del SDR (SDR#, GQRX, SDR++).\n'
                             '    → O sube el volumen de línea en el mezclador del SO.'),
        'tip_high':         ('🟡  Señal saturada (posible distorsión de fase).\n'
                             '    → Baja la ganancia RF del SDR o el volumen de línea.\n'
                             '    → Objetivo: entre −45 y −10 dBFS.'),
        'tip_ok':           '🟢  Nivel correcto. La decodificación debería funcionar.',
        'tip_snr_primary':  ('🟡  Nivel en rango pero SNR demasiado bajo (<15 dB).\n'
                             '    La decodificación puede ser poco fiable. Posibles causas:\n'
                             '    · Interferencias cerca de 510 Hz → revisa modo USB del SDR\n'
                             '    · Ganancia RF muy alta → aumenta el ruido de fondo\n'
                             '    · Antena demasiado corta para 162 kHz'),
        'tip_clip_warn':    '\n    ⚠  Saturación digital: {p:.1f}% de muestras recortadas.',
        'tip_snr_warn':     ('\n    ⚠  SNR bajo (<15 dB). Posibles causas:\n'
                             '    · Interferencias cerca de 510 Hz → revisa modo USB del SDR\n'
                             '    · Ganancia RF muy alta → aumenta el ruido de fondo\n'
                             '    · Antena demasiado corta para 162 kHz'),
        # periodic level
        'level_lbl':        'Nivel',
        'level_weak':       '🔴 débil    — sube ganancia SDR',
        'level_clip':       '🟡 saturado — baja ganancia SDR',
        'level_ok':         '🟢 OK',
        # set_system_time
        'time_unknown_os':  '[ALS162] Sistema no reconocido para ajuste de hora: {os}',
        'time_ok':          '[ALS162] ✔ Hora del sistema ajustada → {dt} (local)',
        'time_fail':        '[ALS162] ✗ No se pudo ajustar la hora: {err}',
        'time_sudo':        '          (¿falta sudo o privilegios de root?)',
        'time_admin':       '          (ejecuta como Administrador o activa "Ejecutar como admin")',
        'time_notfound':    '[ALS162] ✗ Comando no encontrado: {exc}',
        'time_error':       '[ALS162] ✗ Error inesperado al ajustar hora: {exc}',
        # run_offline_wav
        'wav_info':         '[ALS162] WAV: {dur:.1f}s @ {sr} Hz',
        'carrier_det':      '[ALS162] Portadora detectada: {fc:.3f} Hz',
        'offline_done':     '[ALS162] Procesado offline: {bits} bits, {frames} frame(s) decodificado(s).',
        # run_live
        'live_info':        '[ALS162] Dispositivo {dev} @ {sr} Hz | Portadora: {fc:.3f} Hz',
        'live_wait':        '[ALS162] Capturando… (espera ~70 s al primer frame).{stop}',
        'live_ctrlc':       '\n[INFO] Ctrl + C para Detener y Salir.',
        'live_autoclose':   '\n[INFO] Se cerrará automáticamente al ajustar la hora.',
        'live_done':        '[ALS162] Detenido. {bits} bits emitidos, {frames} frame(s) decodificado(s).',
        # record_wav
        'rec_start':        '[ALS162] Grabando {s}s a {p}...',
        'rec_progress':     '  {i}s / {total}s',
        'rec_done':         '[ALS162] Grabación guardada en {p}',
        # list_devices
        'dev_name':         'Nombre',
        'dev_inputs':       'Entradas',
        # run_simulate
        'sim_start':        '[ALS162] Autotest sintético',
        'sim_gen':          '[ALS162] Generando señal sintética para {dt} (DST=on)',
        'sim_carrier':      '[ALS162] Portadora en sintético: {fc:.3f} Hz (esperada 510.000)',
        'sim_fail_none':    '[ALS162] FALLO: no se decodificó ningún frame',
        'sim_fail_inv':     '[ALS162] FALLO: frame inválido: {err}',
        'sim_fail_time':    '[ALS162] FALLO: hora decodificada distinta de la esperada',
        'sim_ok':           '[ALS162] ✔ Autotest OK',
        # default_on_frame
        'dst_yes':          'Sí (verano)',
        'dst_no':           'No (invierno)',
    },
}

def _t(key, **kw):
    """Devuelve la cadena traducida al idioma activo (_LANG)"""
    s = _TUI.get(_LANG, _TUI['en']).get(key, key)
    return s.format(**kw) if kw else s

# ── Constantes ────────────────────────────────────────────────────────────────
SAMPLE_RATE     = 8000
CARRIER_FREQ_DEFAULT = 510.0       # Hz, suele ser ~510 con SDR# en USB

# Especificación del pulso ALS162
PULSE_MS        = 100.0            # duracion total del elemento de señal
RAMP_MS         = 25.0             # cada subrampa
PULSE_AMP_RAD   = 1.0              # ±1 radian

# Procesado
LPF_CUTOFF_HZ   = 120.0            # paso bajo en banda base
FREQ_MIN_HZ     = 300.0
FREQ_MAX_HZ     = 900.0
AUTODETECT_S    = 5
PEAK_THR_REL    = 0.40             # umbral correlación (frac. del maximo en ventana)
PEAK_MIN_DIST_MS = 80              # distancia mínima entre pulsos
SECOND_LOCK_PULSES = 8             # mínimos pulsos para fijar el origen del segundo
PROCESS_WINDOW_S = 5               # ventana de proceso (segundos)
PROCESS_HOP_S   = 1                # avance entre procesos (segundos)

# Frame
FRAME_BITS      = 59               # segundos 0..58
MARKER_BIT_IDX  = 59               # segundo 59 sin pulso = marcador

# Header
HEADER=(f"\n********************************************************************\
        \n****************** ALS162 DECODER & SYNC TIME **********************\
        \n********************************************************************\
        \n********************** by Quixote Network **************************\
        \n**************************** v 0.2 *********************************\n")


# ── Utilidades ────────────────────────────────────────────────────────────────
def bcd(bits, start, length):
    """Decodifica `length` bits BCD a partir de `start` (LSB primero)."""
    return sum(int(bits[start + i]) * (1 << i) for i in range(length))


def even_parity_ok(bits, start, length, parity_bit):
    """Devuelve True si la paridad par de bits[start:start+length] coincide
    con `parity_bit`. ALS162/DCF77 usan paridad par (XOR de los bits + paridad = 0)."""
    s = sum(int(bits[start + i]) for i in range(length)) + int(parity_bit)
    return s % 2 == 0


# ── Plantilla del pulso ───────────────────────────────────────────────────────
def make_pulse_template(sample_rate=SAMPLE_RATE, ramp_ms=RAMP_MS,
                        amp=PULSE_AMP_RAD):
    """Trayectoria de fase esperada de un elemento de senyal (100 ms)."""
    nr = int(round(ramp_ms * sample_rate / 1000))   # muestras por rampa de 25 ms
    a = np.linspace(0,    amp,  nr,    endpoint=False)
    b = np.linspace(amp, -amp, 2*nr,  endpoint=False)
    c = np.linspace(-amp, 0,    nr,    endpoint=True)
    tpl = np.concatenate([a, b, c]).astype(np.float64)
    tpl -= tpl.mean()
    n = np.sqrt((tpl ** 2).sum())
    return tpl / n if n > 0 else tpl


# ── Detección de portadora ────────────────────────────────────────────────────
def detect_carrier_from_samples(samples, sample_rate, fmin=FREQ_MIN_HZ,
                                fmax=FREQ_MAX_HZ):
    """FFT y pico (con interpolacion parabolica) en [fmin..fmax]. La portadora
    ALS162 es continua, asi que NO hay que elevar al cuadrado: la perturbacion
    de fase es minuscula (±1 rad pulso de 100 ms cada segundo) y el tono esta
    limpio en el espectro."""
    n = len(samples)
    win = np.hanning(n)
    spec = np.abs(np.fft.rfft(samples * win))
    freqs = np.fft.rfftfreq(n, 1.0 / sample_rate)
    mask = (freqs >= fmin) & (freqs <= fmax)
    if not mask.any():
        raise ValueError("Rango de frecuencias inválido")
    fm = freqs[mask]
    sm = spec[mask]
    i0 = int(np.argmax(sm))
    if 0 < i0 < len(sm) - 1:
        a, b_, g = sm[i0 - 1], sm[i0], sm[i0 + 1]
        denom = a - 2 * b_ + g
        delta = 0.5 * (a - g) / denom if denom != 0 else 0.0
        df = freqs[1] - freqs[0]
        return float(fm[i0] + delta * df)
    return float(fm[i0])


def sdr_analyze(samples, sample_rate, carrier_freq=None):
    """Analiza la senyal y devuelve un dict con metricas SDR (sin imprimir nada).

    Devuelve:
        dbfs        – nivel RMS en dBFS (referencia 0 dBFS = full-scale int16)
        clip_pct    – porcentaje de muestras saturadas (|x| ≥ 32000)
        snr_db      – SNR estimado: pico de portadora vs mediana del ruido de fondo
        top5        – lista de hasta 5 tuplas (freq_hz, pct_relativo) picos principales
        freqs       – array np de frecuencias (Hz) del espectro en banda 300-900 Hz
        amps        – array np de amplitudes correspondientes
        ascii_spec  – cadena ASCII de 50 caracteres con el espectro (para TUI)
        carrier_freq– portadora usada en el cálculo (puede ser None)
    """
    rms      = np.sqrt(np.mean(samples ** 2))
    dbfs     = 20.0 * np.log10(max(rms, 1.0) / 32768.0)
    clip_pct = 100.0 * float(np.mean(np.abs(samples) >= 32000))

    n     = min(len(samples), 131072)
    win   = np.hanning(n)
    spec  = np.abs(np.fft.rfft(samples[:n] * win))
    freqs = np.fft.rfftfreq(n, 1.0 / sample_rate)
    mask  = (freqs >= FREQ_MIN_HZ) & (freqs <= FREQ_MAX_HZ)
    fm, sm = freqs[mask], spec[mask]

    # SNR
    if carrier_freq is not None and len(sm) and sm.max() > 0:
        sig_mask  = np.abs(fm - carrier_freq) <= 12
        noise_med = np.median(sm[~sig_mask]) if (~sig_mask).any() else 1e-9
        snr_db    = 20.0 * np.log10(sm[sig_mask].max() / max(noise_med, 1e-9)) \
                    if sig_mask.any() else 0.0
    else:
        noise_med = np.median(sm) if len(sm) else 1e-9
        snr_db    = 20.0 * np.log10(sm.max() / max(noise_med, 1e-9)) if len(sm) else 0.0

    # Top 5 picos
    top5 = []
    if len(sm):
        t_max = sm.max()
        top5  = [(float(fm[i]), 100.0 * float(sm[i]) / t_max)
                 for i in np.argsort(sm)[-5:][::-1]]

    # Espectro ASCII 50 columnas
    COLS = 50
    bins = []
    for k in range(COLS):
        f0 = FREQ_MIN_HZ + k * (FREQ_MAX_HZ - FREQ_MIN_HZ) / COLS
        f1 = f0 + (FREQ_MAX_HZ - FREQ_MIN_HZ) / COLS
        b  = sm[(fm >= f0) & (fm < f1)]
        bins.append(b.max() if len(b) else 0.0)
    bmax       = max(bins) if bins else 1.0
    ascii_spec = ''.join(
        '█' if v / bmax > 0.66 else '▄' if v / bmax > 0.25 else '·'
        for v in bins
    )

    return {
        'dbfs': dbfs, 'clip_pct': clip_pct, 'snr_db': snr_db,
        'top5': top5, 'freqs': fm, 'amps': sm,
        'ascii_spec': ascii_spec, 'carrier_freq': carrier_freq,
    }


def sdr_report(samples, sample_rate, carrier_freq=None):
    """Imprime el informe SDR en la terminal (TUI). Llama a sdr_analyze internamente."""
    s    = sdr_analyze(samples, sample_rate, carrier_freq)
    LINE = "─" * 64
    DB_LOW, DB_HIGH = -45.0, -10.0
    DB_MIN, DB_MAX  = -65.0, -5.0
    BAR_W = 28
    dbfs, clip_pct, snr_db = s['dbfs'], s['clip_pct'], s['snr_db']
    fill  = int(max(0, min(BAR_W, (dbfs - DB_MIN) / (DB_MAX - DB_MIN) * BAR_W)))
    sym   = '▒' if dbfs < DB_LOW else ('█' if dbfs > DB_HIGH else '▓')
    ctag  = '🔴' if dbfs < DB_LOW else ('🟡' if dbfs > DB_HIGH else '🟢')
    bar   = sym * fill + '░' * (BAR_W - fill)

    if dbfs < DB_LOW:
        tip = _t('tip_low')
        if snr_db < 15.0:
            tip += _t('tip_snr_warn')
    elif dbfs > DB_HIGH:
        tip = _t('tip_high')
        if snr_db < 15.0:
            tip += _t('tip_snr_warn')
    elif snr_db < 15.0:
        # Nivel en rango pero SNR muy bajo. Bajo el nivel para warning
        tip = _t('tip_snr_primary')
    else:
        tip = _t('tip_ok')
    if clip_pct > 1.0:
        tip += _t('tip_clip_warn', p=clip_pct)

    COLS = 50
    print(f"\n{LINE}")
    print(f"  {_t('sdr_header', sr=sample_rate)}")
    print(LINE)
    print(f"  {_t('rms_level')} {dbfs:+6.1f} dBFS  [{bar}]  {ctag}")
    print(f"  {_t('clipping')} {clip_pct:5.1f} %    "
          f"{_t('reduce_gain') if clip_pct > 1 else _t('no_clip')}")
    if carrier_freq is not None:
        print(f"  {_t('carrier_lbl')} {carrier_freq:.3f} Hz")
    print(f"  {_t('snr_lbl')} {snr_db:+5.1f} dB   "
          f"{_t('snr_good') if snr_db >= 20 else _t('snr_low')}")
    print()
    print(f"  {_t('spectrum_hdr')}")
    print(f"  300 Hz{' ':8s}500 Hz{' ':8s}700 Hz{' ':5s}900 Hz")
    print(f"  |{s['ascii_spec']}|")
    if carrier_freq is not None:
        mp = int((carrier_freq - FREQ_MIN_HZ) / (FREQ_MAX_HZ - FREQ_MIN_HZ) * COLS)
        mp = max(1, min(COLS - 1, mp))
        print(f"  |{' ' * (mp-1)}↑{' ' * (COLS-mp)}|  {_t('carrier_marker')}")
    print()
    if s['top5']:
        print(f"  {_t('top_peaks')}")
        for rank, (f, pct) in enumerate(s['top5'][:5], 1):
            bar5 = '█' * int(pct / 5)
            print(f"    {rank}  {f:7.2f} Hz  {bar5:<20s}  {pct:5.1f}%")
        print()
    print(f"  {tip}")
    print(f"{LINE}\n")


def detect_carrier_live(device_index, sample_rate, seconds=AUTODETECT_S,
                        silent=False):
    """Captura `seconds` s de audio, detecta la portadora y la devuelve en Hz.

    silent=True  → no imprime el informe SDR (para uso desde GUI).
    silent=False → imprime el informe SDR completo en la terminal (TUI).
    """
    if pyaudio is None:
        raise RuntimeError("pyaudio no instalado")
    
    print(HEADER)
    print(f"[ALS162] {_t('measuring', s=seconds)}", end="", flush=True)
    pa = pyaudio.PyAudio()
    try:
        stream = pa.open(format=pyaudio.paInt16, channels=1, rate=sample_rate,
                         input=True, input_device_index=device_index,
                         frames_per_buffer=sample_rate)
        frames = []
        for _ in range(seconds):
            frames.append(stream.read(sample_rate, exception_on_overflow=False))
            print(".", end="", flush=True)
        stream.stop_stream()
        stream.close()
    finally:
        pa.terminate()
    samples = np.frombuffer(b"".join(frames), dtype=np.int16).astype(np.float64)
    fc = detect_carrier_from_samples(samples, sample_rate)
    print(f" {fc:.3f} Hz")
    if not silent:
        sdr_report(samples, sample_rate, fc)
    return fc


# ── Demodulacion de fase ──────────────────────────────────────────────────────
def demodulate_phase(samples, sample_rate, carrier_freq,
                     lpf_hz=LPF_CUTOFF_HZ):
    """Mezcla a banda base, filtra paso bajo, devuelve la fase desenrollada
    y detrendada (radianes). El detrend lineal elimina la deriva residual en
    frecuencia dentro de la ventana"""
    samples = np.asarray(samples, dtype=np.float64)
    n = len(samples)
    t = np.arange(n) / sample_rate
    bb = samples * np.exp(-2j * np.pi * carrier_freq * t)
    sos = butter(4, lpf_hz, fs=sample_rate, output='sos')
    bb = sosfiltfilt(sos, bb)
    phase = np.unwrap(np.angle(bb))
    # Detrend lineal (sin BIAS por valores extremos)
    coef = np.polyfit(t, phase, 1)
    return phase - (coef[0] * t + coef[1])


# ── Deteccion de pulsos ───────────────────────────────────────────────────────
def detect_pulses_in_window(phase, sample_rate, template,
                            thr_rel=PEAK_THR_REL,
                            min_dist_ms=PEAK_MIN_DIST_MS):
    """Correla la fase con la plantilla y devuelve las posiciones (en muestras
    relativas a la ventana) del INICIO de cada pulso detectado, junto con su
    amplitud de correlacion."""
    if len(phase) < len(template):
        return np.array([], dtype=int), np.array([], dtype=float)

    # Correlacion normalizada (mode='same' centra el pico en el centro de la plantilla)
    corr = np.convolve(phase, template[::-1], mode='same')
    # Umbral basado en el máximo POSITIVO: find_peaks solo busca picos positivos,
    # así que basar el umbral en np.max(np.abs(corr)) lo infla si hay un valle
    # negativo grande y el segundo pulso de bit=1 (ligeramente más débil) queda
    # por debajo → todos los bits salen 0.
    max_corr = np.max(corr)
    if max_corr <= 1e-9:
        return np.array([], dtype=int), np.array([], dtype=float)

    threshold = thr_rel * max_corr
    min_dist  = int(min_dist_ms * sample_rate / 1000)
    peaks, props = find_peaks(corr, height=threshold, distance=min_dist)
    heights = props["peak_heights"]
    half_tpl = len(template) // 2
    starts = peaks - half_tpl
    # Descarta los que se salen del rango
    valid = (starts >= 0) & (starts < len(phase))
    return starts[valid], heights[valid]


# ── Tracker de segundos ───────────────────────────────────────────────────────
class SecondTracker:
    """Acumula posiciones absolutas de pulsos y, cuando tiene suficientes,
    fija el offset (en muestras dentro de cada segundo) del inicio del segundo.
    Despues emite, para cada segundo completado en el buffer, el numero de
    pulsos detectados en su ventana inicial (0..0.3 s)."""

    def __init__(self, sample_rate=SAMPLE_RATE, verbose=False):
        self.sr = sample_rate
        self.verbose = verbose
        # cada elemento: (sample_index_absoluto, height)
        self.pulses = deque(maxlen=1200)         # ~5 minutos de pulsos
        self.second_offset = None                # muestras (0..sr-1)
        self.next_second_start = None            # próximo segundo a emitir (abs. sample)
        self._last_lock_attempt_count = 0

    def add_pulses(self, sample_indices, heights):
        for s, h in zip(sample_indices, heights):
            self.pulses.append((int(s), float(h)))
        if self.second_offset is None and \
           len(self.pulses) - self._last_lock_attempt_count >= SECOND_LOCK_PULSES:
            self._last_lock_attempt_count = len(self.pulses)
            self._try_lock()

    def _try_lock(self):
        positions = np.array([p % self.sr for p, _ in self.pulses])
        # Histograma circular: 200 bins de 5 ms cada uno
        nbins = 200
        hist, edges = np.histogram(positions, bins=nbins, range=(0, self.sr))
        # El offset del segundo es donde aparece el pulso "primer-pulso-del-segundo".
        # Para bit 0 hay 1 pulso (en t≈0), para bit 1 hay 2 pulsos (en t≈0 y t≈100ms).
        # Por tanto el bin con MAS pulsos suele ser t≈0.
        # Aplicamos suavizado circular para robustez:
        smooth = np.convolve(np.r_[hist, hist, hist],
                             np.ones(5) / 5, mode='same')[nbins:2*nbins]
        peak_bin = int(np.argmax(smooth))
        offset = int((edges[peak_bin] + edges[peak_bin + 1]) / 2)
        self.second_offset = offset
        if self.verbose:
            print(f"  [TIMING] Origen de segundo fijado en muestra {offset} "
                  f"(= {offset * 1000.0 / self.sr:.1f} ms dentro del segundo)")

    def _classify_pulses(self, window_pulses):
        """Clasifica los pulsos de un segundo usando análisis de pulso pareado.
        Ordena los pulsos por posición (tiempo) y busca si hay un segundo pulso
        a ~100 ms del primero.
        Retorna 0 (marcador), 1 (bit=0, 1 pulso), 2 (bit=1, 2 pulsos)."""
        if not window_pulses:
            return 0  # sin pulsos → marcador

        # Ordenar por posicion (tiempo): el primer pulso real llega antes
        sorted_pulses = sorted(window_pulses, key=lambda x: x[0])

        # Recorrer todos los picos buscando un par valido separado ~100 ms
        for i, (p1, h1) in enumerate(sorted_pulses):
            p2_lo = p1 + int(0.075 * self.sr)
            p2_hi = p1 + int(0.130 * self.sr)
            for p2, h2 in sorted_pulses[i + 1:]:
                if p2 >= p2_hi:
                    break   # ya pasamos el rango → no hay segundo pulso aqui
                if p2 >= p2_lo and h2 >= 0.45 * h1:
                    return 2  # par valido encontrado → bit=1

        return 1  # ningun par encontrado → bit=0 (un pulso)

    def emit(self, buffer_end_sample):
        """Emite (segundo_inicio_abs, n_pulsos_clasificación) para cada segundo
        cuyo borde + ventana de clasificación esté antes de buffer_end_sample."""
        if self.second_offset is None:
            return []

        # Ventana de clasificacion: 300 ms tras el inicio del segundo
        win_samples = int(0.30 * self.sr)

        if self.next_second_start is None:
            # Primer segundo: el primero >= primer pulso observado
            first_pulse = self.pulses[0][0]
            # Encuentra el inicio de segundo más cercano <= first_pulse
            base = first_pulse - ((first_pulse - self.second_offset) % self.sr)
            self.next_second_start = base

        events = []
        while self.next_second_start + win_samples <= buffer_end_sample:
            sec_start = self.next_second_start
            sec_end_w = sec_start + win_samples
            tol_back = int(0.04 * self.sr)

            # Recoger pulsos de la ventana (posicion + altura)
            window_pulses = [
                (p, h) for p, h in self.pulses
                if sec_start - tol_back <= p < sec_end_w
            ]

            # Clasificar con analisis de pulso pareado
            n = self._classify_pulses(window_pulses)

            events.append((sec_start, n))
            self.next_second_start += self.sr

        # Limpia pulsos antiguos (>10 segundos) para evitar crecimiento ilimitado
        cutoff = buffer_end_sample - 10 * self.sr
        while self.pulses and self.pulses[0][0] < cutoff:
            self.pulses.popleft()

        return events


# ── Frame decoder ─────────────────────────────────────────────────────────────
class ALS162Frame:
    DOW       = ["", "Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"]
    DOW_FULL  = ["", "Lunes", "Martes", "Miércoles", "Jueves",
                 "Viernes", "Sábado", "Domingo"]
    MONTH     = ["", "Ene", "Feb", "Mar", "Abr", "May", "Jun",
                 "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    MONTH_FULL= ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

    DOW_FULL_EN  = ["", "Monday", "Tuesday", "Wednesday", "Thursday",
                    "Friday", "Saturday", "Sunday"]
    MONTH_FULL_EN= ["", "January", "February", "March", "April", "May", "June",
                    "July", "August", "September", "October", "November", "December"]

    def __init__(self, bits):
        if len(bits) < FRAME_BITS:
            raise ValueError(f"Frame demasiado corto: {len(bits)} bits")
        self.bits = [int(x) for x in bits[:FRAME_BITS]]
        self.valid = False
        self.error = ""
        self._decode()

    def _decode(self):
        b = self.bits
        if b[0] != 0:
            self.error = f"Bit 0 debe ser 0 (es {b[0]})"
            return
        if b[20] != 1:
            self.error = f"Bit 20 debe ser 1 (es {b[20]})"
            return
        # bits 17/18 deben ser complementarios (DST/STD)
        if b[17] == b[18]:
            self.error = f"Bits DST 17/18 incoherentes ({b[17]},{b[18]})"
            return

        # Paridades
        if not even_parity_ok(b, 21, 7,  b[28]):
            self.error = "Paridad de minutos"
            return
        if not even_parity_ok(b, 29, 6,  b[35]):
            self.error = "Paridad de horas"
            return
        if not even_parity_ok(b, 36, 22, b[58]):
            self.error = "Paridad de fecha"
            return

        # BCD
        self.minute  = bcd(b, 21, 4) + bcd(b, 25, 3) * 10
        self.hour    = bcd(b, 29, 4) + bcd(b, 33, 2) * 10
        self.day     = bcd(b, 36, 4) + bcd(b, 40, 2) * 10
        self.weekday = bcd(b, 42, 3)
        self.month   = bcd(b, 45, 4) + bcd(b, 49, 1) * 10
        self.year    = 2000 + bcd(b, 50, 4) + bcd(b, 54, 4) * 10
        self.dst          = bool(b[17])   # 1 = CEST (verano)
        self.std          = bool(b[18])   # 1 = CET  (invierno)
        self.dst_ann      = bool(b[16])   # cambio de hora proximo
        self.leap_pos_ann = bool(b[1])
        self.leap_neg_ann = bool(b[2])
        self.holiday_eve  = bool(b[13])   # bit 13: dia anterior a festivo
        self.holiday_today= bool(b[14])   # bit 14: hoy es festivo

        # Validacion
        if not (0 <= self.minute  <= 59): self.error = f"Minuto inválido: {self.minute}";   return
        if not (0 <= self.hour    <= 23): self.error = f"Hora inválida: {self.hour}";        return
        if not (1 <= self.day     <= 31): self.error = f"Día inválido: {self.day}";          return
        if not (1 <= self.month   <= 12): self.error = f"Mes inválido: {self.month}";        return
        if not (1 <= self.weekday <=  7): self.error = f"Día semana inválido: {self.weekday}"; return
        self.valid = True

    def utc_offset(self):
        return 2 if self.dst else 1

    def as_dict(self):
        if not self.valid:
            return {"valid": False, "error": self.error}
        uo = self.utc_offset()
        return {
            "valid": True, "year": self.year, "month": self.month,
            "day": self.day, "weekday": self.weekday,
            "weekday_name": self.DOW_FULL[self.weekday],
            "hour": self.hour, "minute": self.minute,
            "dst": self.dst, "dst_change": self.dst_ann,
            "holiday_today": self.holiday_today,
            "holiday_eve":   self.holiday_eve,
            "leap_pos": self.leap_pos_ann, "leap_neg": self.leap_neg_ann,
            "utc_offset": uo,
            "iso": (f"{self.year:04d}-{self.month:02d}-{self.day:02d}T"
                    f"{self.hour:02d}:{self.minute:02d}:00+0{uo}:00"),
        }

    def __str__(self):
        return format_frame(self, _LANG)


def format_frame(frame, lang='en'):
    """Devuelve la representacion en pantalla del frame en el idioma indicado."""
    if not frame.valid:
        msg = frame.error
        return (f"[INVALID FRAME: {msg}]" if lang == 'en'
                else f"[FRAME INVÁLIDO: {msg}]")

    tz = "CEST (UTC+2)" if frame.dst else "CET  (UTC+1)"

    if lang == 'en':
        header  = "ALS162 — French Time Signal"
        ann     = "\n  ⚠  DST change upcoming"      if frame.dst_ann       else ""
        ann    += "\n  ⚠  Positive leap second"      if frame.leap_pos_ann  else ""
        ann    += "\n  ⚠  Negative leap second"      if frame.leap_neg_ann  else ""
        hoy     = "🎉 Today is a holiday"            if frame.holiday_today else "✓  Not a holiday today"
        man     = "⚠  Holiday announced this week"  if frame.holiday_eve   else "✓  No holiday this week"
        dow     = frame.DOW_FULL_EN[frame.weekday]
        mon     = frame.MONTH_FULL_EN[frame.month]
    else:
        header  = "ALS162 — Señal horaria francesa"
        ann     = "\n  ⚠  Cambio de hora próximo"    if frame.dst_ann       else ""
        ann    += "\n  ⚠  Leap second positivo"      if frame.leap_pos_ann  else ""
        ann    += "\n  ⚠  Leap second negativo"      if frame.leap_neg_ann  else ""
        hoy     = "🎉 Hoy es festivo"                if frame.holiday_today else "✓  Hoy no es festivo"
        man     = "⚠  Festivo anunciado esta semana" if frame.holiday_eve   else "✓  Sin festivo esta semana"
        dow     = frame.DOW_FULL[frame.weekday]
        mon     = frame.MONTH_FULL[frame.month]

    hol = f"\n  {hoy}  |  {man}"
    return ("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"  {header}\n"
            f"  {dow}, {frame.day:02d} {mon} {frame.year}\n"
            f"  {frame.hour:02d}:{frame.minute:02d}  {tz}{ann}{hol}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


# ── Frame assembler ───────────────────────────────────────────────────────────
class FrameAssembler:
    """Recibe (sec_start, n_pulses). Estado:
       WAIT_MARKER → COLLECT (59 bits) → emite frame → WAIT_MARKER."""
    WAIT_MARKER = 0
    COLLECT     = 1

    def __init__(self, on_frame, verbose=False):
        self.on_frame = on_frame
        self.verbose  = verbose
        self.state    = self.WAIT_MARKER
        self.bits     = []
        self.pending_marker_count = 0

    def push(self, sec_start_sample, n_pulses, sample_rate=SAMPLE_RATE):
        # n_pulses == 0  → marcador de minuto (segundo 59 sin pulso)
        # n_pulses == 1  → bit 0
        # n_pulses == 2  → bit 1
        # n_pulses >= 3  → ruido / error de deteccion, asumimos bit 1
        if n_pulses == 0:
            if self.state == self.COLLECT:
                if len(self.bits) == FRAME_BITS:
                    if self.verbose:
                        print(f"  [FRAME] {len(self.bits)} bits + marcador → emito")
                    self.on_frame(self.bits[:])
                else:
                    if self.verbose:
                        print(f"  [FRAME] marcador prematuro tras {len(self.bits)} bits, descarto")
            self.bits = []
            self.state = self.COLLECT
            return

        if self.state == self.WAIT_MARKER:
            # Estamos esperando un minuto entero antes de empezar
            return

        bit = 1 if n_pulses >= 2 else 0
        self.bits.append(bit)
        if self.verbose:
            ts = time.strftime("%H:%M:%S")
            print(f"  [{ts}] sec_start={sec_start_sample}  pulsos={n_pulses}  bit={bit}  ({len(self.bits)}/{FRAME_BITS})")
        if len(self.bits) == FRAME_BITS:
            # Esperamos el marcador en el siguiente segundo
            pass


# ── Decodificador principal (procesado de un buffer) ──────────────────────────
class ALS162Processor:
    """Estado compartido para procesado por ventanas. Mantiene:
       - origen absoluto del buffer (n.º de muestra de la primera muestra del buffer)
       - tracker de segundos
       - ensamblador de frames
    """

    def __init__(self, sample_rate, carrier_freq, on_frame, verbose=False):
        self.sr = sample_rate
        self.fc = carrier_freq
        self.verbose = verbose
        self.template = make_pulse_template(sample_rate)
        self.tracker  = SecondTracker(sample_rate, verbose=verbose)
        self.assembler = FrameAssembler(self._frame_ready, verbose=verbose)
        self.on_frame = on_frame
        self.bits_emitted = 0
        self.frames_decoded = 0
        # Para no contar el mismo pulso dos veces entre ventanas solapadas
        self._last_emitted_until_abs = None
        # Histórico de pulsos ya añadidos (timestamps absolutos)
        self._added_pulses = set()

    def _frame_ready(self, bits):
        try:
            frame = ALS162Frame(bits)
        except Exception as e:
            print(f"[ALS162] Error decodificando frame: {e}")
            return
        self.frames_decoded += 1
        self.on_frame(frame)

    def process_window(self, samples, window_start_abs):
        """Procesa una ventana de muestras (np.float64). `window_start_abs` es
        el índice absoluto de la primera muestra de `samples`."""
        if len(samples) < int(0.5 * self.sr):
            return

        phase = demodulate_phase(samples, self.sr, self.fc)
        pulse_starts_rel, heights = detect_pulses_in_window(
            phase, self.sr, self.template)

        # Convierte a posiciones absolutas, dedup
        new_starts = []
        new_heights = []
        for s, h in zip(pulse_starts_rel.tolist(), heights.tolist()):
            abs_s = window_start_abs + int(s)
            # Dedup: si ya hay un pulso a < 50 ms de este, lo ignoramos
            duplicated = any(abs(abs_s - p) < int(0.05 * self.sr)
                             for p, _ in self.tracker.pulses)
            if not duplicated:
                new_starts.append(abs_s)
                new_heights.append(h)

        if new_starts:
            self.tracker.add_pulses(new_starts, new_heights)

        # Emite segundos completados (con margen al final de la ventana)
        buffer_end_abs = window_start_abs + len(samples) - int(0.30 * self.sr)
        for sec_start, n_pulses in self.tracker.emit(buffer_end_abs):
            if self._last_emitted_until_abs is not None and sec_start <= self._last_emitted_until_abs:
                continue
            self._last_emitted_until_abs = sec_start
            self.bits_emitted += 1
            self.assembler.push(sec_start, n_pulses, self.sr)


# ── Captura de audio (en vivo / WAV) ──────────────────────────────────────────
class LiveAudioCapture:
    """Captura por callback de PyAudio en chunks de 1 segundo."""
    def __init__(self, device_index, sample_rate, on_chunk):
        self.device_index = device_index
        self.sr = sample_rate
        self.on_chunk = on_chunk
        self._pa = None
        self._stream = None
        self._abs_sample = 0
        self._lock = threading.Lock()

    def _cb(self, in_data, frame_count, time_info, status):
        samples = np.frombuffer(in_data, dtype=np.int16).astype(np.float64)
        with self._lock:
            start = self._abs_sample
            self._abs_sample += len(samples)
        self.on_chunk(samples, start)
        return (None, pyaudio.paContinue)

    def start(self):
        if pyaudio is None:
            raise RuntimeError("pyaudio no instalado")
        self._pa = pyaudio.PyAudio()
        self._stream = self._pa.open(
            format=pyaudio.paInt16, channels=1, rate=self.sr,
            input=True, input_device_index=self.device_index,
            frames_per_buffer=self.sr, stream_callback=self._cb)
        self._stream.start_stream()

    def stop(self):
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
        if self._pa:
            self._pa.terminate()


def read_wav_mono(path):
    with wave.open(path, 'rb') as wf:
        sr = wf.getframerate()
        nch = wf.getnchannels()
        sw = wf.getsampwidth()
        nframes = wf.getnframes()
        raw = wf.readframes(nframes)
    if sw != 2:
        raise ValueError(f"Solo soporto WAV 16-bit (sampwidth={sw})")
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
    if nch > 1:
        samples = samples.reshape(-1, nch).mean(axis=1)
    return samples, sr


def record_wav(device_index, sample_rate, seconds, path):
    if pyaudio is None:
        raise RuntimeError("pyaudio no instalado")
    print(_t('rec_start', s=seconds, p=path))
    pa = pyaudio.PyAudio()
    stream = pa.open(format=pyaudio.paInt16, channels=1, rate=sample_rate,
                     input=True, input_device_index=device_index,
                     frames_per_buffer=sample_rate)
    frames = []
    try:
        for i in range(seconds):
            frames.append(stream.read(sample_rate, exception_on_overflow=False))
            if (i + 1) % 10 == 0:
                print(_t('rec_progress', i=i+1, total=seconds))
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()
    with wave.open(path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"".join(frames))
    print(_t('rec_done', p=path))


# ── Orquestacion ──────────────────────────────────────────────────────────────
def default_on_frame(frame):
    print(frame)
    if frame.valid:
        d = frame.as_dict()
        print(f"  ISO 8601 : {d['iso']}")
        print(f"  DST      : {_t('dst_yes') if d['dst'] else _t('dst_no')}")
    print(flush=True)


def set_system_time(frame, extra_hours=0):
    """Ajusta el reloj del sistema a la hora ALS162 + un offset opcional.

    extra_hours: diferencia horaria respecto a Francia (ej. +1 para Europa del
    Este en invierno).  En Linux/macOS se fija UTC (siempre correcto; el SO
    muestra la hora local según su timezone).  En Windows se usa la hora local
    ajustada con el offset, ya que Set-Date trabaja en hora local del sistema.
    """
    import subprocess, platform
    from datetime import datetime, timedelta

    # Hora local francesa al inicio del minuto recien marcado
    local_dt = datetime(frame.year, frame.month, frame.day,
                        frame.hour, frame.minute, 0)
    # UTC verdadero (independiente del offset del usuario)
    utc_dt = local_dt - timedelta(hours=frame.utc_offset())
    # Hora local del usuario (hora francesa + desplazamiento)
    user_local_dt = local_dt + timedelta(hours=extra_hours)

    sistema = platform.system()
    try:
        if sistema == 'Linux':
            # UTC es correcto independientemente del offset del usuario
            cmd = ['sudo', 'date', '-u', '-s', utc_dt.strftime('%Y-%m-%d %H:%M:%S')]
            res = subprocess.run(cmd, capture_output=True, text=True)
        elif sistema == 'Darwin':   # macOS
            cmd = ['sudo', 'date', '-u', utc_dt.strftime('%m%d%H%M%Y.%S')]
            res = subprocess.run(cmd, capture_output=True, text=True)
        elif sistema == 'Windows':
            # Set-Date usa hora local del sistema → aplicar offset del usuario
            local_str = user_local_dt.strftime('%Y-%m-%d %H:%M:%S')
            ps = f'Set-Date -Date "{local_str}"'
            res = subprocess.run(['powershell', '-NoProfile', '-Command', ps],
                                 capture_output=True, text=True)
        else:
            print(_t('time_unknown_os', os=sistema))
            return

        if res.returncode == 0:
            print(_t('time_ok', dt=local_dt.strftime('%Y-%m-%d %H:%M:%S')))
        else:
            err = res.stderr.strip() or res.stdout.strip()
            if sistema == 'Windows':
                raise PermissionError(_t('time_admin'))
            else:
                raise PermissionError(_t('time_sudo'))
    except PermissionError:
        raise   # propagar al llamador
    except FileNotFoundError as exc:
        raise PermissionError(_t('time_notfound', exc=exc))
    except Exception as exc:
        raise RuntimeError(_t('time_error', exc=exc))


def run_offline_wav(path, carrier_freq=None, verbose=False, on_frame=None,
                    set_time=False, utc_offset=None):
    samples, sr = read_wav_mono(path)
    print(_t('wav_info', dur=len(samples)/sr, sr=sr))
    if carrier_freq is None:
        head = samples[:min(len(samples), AUTODETECT_S * sr)]
        carrier_freq = detect_carrier_from_samples(head, sr)
        print(_t('carrier_det', fc=carrier_freq))
    sdr_report(samples[:min(len(samples), 30 * sr)], sr, carrier_freq)

    def _cb(frame):
        (on_frame or default_on_frame)(frame)
        if set_time and frame.valid:
            try:
                extra = (utc_offset - frame.utc_offset()) if utc_offset is not None else 0
                set_system_time(frame, extra_hours=extra)
            except (PermissionError, RuntimeError) as exc:
                print(f'\n{exc}')

    proc = ALS162Processor(sr, carrier_freq, _cb, verbose=verbose)
    win = PROCESS_WINDOW_S * sr
    hop = PROCESS_HOP_S * sr
    pos = 0
    while pos + win <= len(samples):
        proc.process_window(samples[pos:pos + win], pos)
        pos += hop
    # Última ventana
    if pos < len(samples):
        proc.process_window(samples[pos:], pos)
    print(_t('offline_done', bits=proc.bits_emitted, frames=proc.frames_decoded))


def run_live(device_index, sample_rate, carrier_freq, verbose=False,
             on_frame=None, set_time=False, utc_offset=None):
    if carrier_freq is None:
        carrier_freq = detect_carrier_live(device_index, sample_rate)

    # Evento para detener el bucle principal cuando --set-time está activo
    stop_event = threading.Event()

    def _cb(frame):
        (on_frame or default_on_frame)(frame)
        if set_time and frame.valid:
            try:
                extra = (utc_offset - frame.utc_offset()) if utc_offset is not None else 0
                set_system_time(frame, extra_hours=extra)
                stop_event.set()   # señal de cierre tras ajustar la hora
            except (PermissionError, RuntimeError) as exc:
                print(f'\n{exc}')

    proc = ALS162Processor(sample_rate, carrier_freq, _cb,
                           verbose=verbose)

    # Buffer rolling de PROCESS_WINDOW_S segundos
    rolling = np.zeros(0, dtype=np.float64)
    rolling_start = 0       # índice absoluto de rolling[0]
    last_processed = 0      # índice absoluto del último inicio de ventana procesada
    lock = threading.Lock()
    _last_level_t = [0.0]   # último instante en que se imprimió el nivel
    _LEVEL_INTERVAL = 30.0  # segundos entre impresiones de nivel

    def on_chunk(samples, abs_start):
        nonlocal rolling, rolling_start, last_processed
        if stop_event.is_set():
            return   # ignorar nuevos chunks tras el cierre

        # ── Nivel periódico (cada _LEVEL_INTERVAL s) ─────────────────────
        now = time.time()
        if now - _last_level_t[0] >= _LEVEL_INTERVAL:
            _last_level_t[0] = now
            rms  = np.sqrt(np.mean(samples ** 2))
            dbfs = 20.0 * np.log10(max(rms, 1.0) / 32768.0)
            DB_LOW, DB_HIGH = -45.0, -10.0
            if dbfs < DB_LOW:
                sym, hint = '▒', _t('level_weak')
            elif dbfs > DB_HIGH:
                sym, hint = '█', _t('level_clip')
            else:
                sym, hint = '▓', _t('level_ok')
            BAR_W = 20
            fill = int(max(0, min(BAR_W, (dbfs - (-65.0)) / 60.0 * BAR_W)))
            bar = sym * fill + '░' * (BAR_W - fill)
            ts = datetime.now().strftime('%H:%M:%S')
            print(f"  [{ts}] {_t('level_lbl')}: {dbfs:+.1f} dBFS [{bar}]  {hint}",
                  flush=True)

        with lock:
            # Append
            if len(rolling) == 0:
                rolling = samples.copy()
                rolling_start = abs_start
            else:
                rolling = np.concatenate([rolling, samples])
            # Procesa cuantas ventanas quepan, avanzando PROCESS_HOP_S
            win = PROCESS_WINDOW_S * sample_rate
            hop = PROCESS_HOP_S * sample_rate
            while True:
                buf_end = rolling_start + len(rolling)
                next_start = max(last_processed, rolling_start)
                if next_start + win > buf_end:
                    break
                rel = next_start - rolling_start
                proc.process_window(rolling[rel:rel + win], next_start)
                last_processed = next_start + hop
            # Recorta rolling para no crecer indefinidamente
            keep_from = max(0, last_processed - rolling_start - win)
            if keep_from > 0:
                rolling = rolling[keep_from:]
                rolling_start += keep_from

    cap = LiveAudioCapture(device_index, sample_rate, on_chunk)
    msg_stop = _t('live_ctrlc') if not set_time else _t('live_autoclose')
    dev_str  = device_index if device_index is not None else 'default'
    print(_t('live_info', dev=dev_str, sr=sample_rate, fc=carrier_freq))
    print(_t('live_wait', stop=msg_stop) + '\n')
    cap.start()
    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        cap.stop()
        print('\n' + _t('live_done', bits=proc.bits_emitted, frames=proc.frames_decoded))


# ── Generador sintetico (autotest) ────────────────────────────────────────────
def synthesize_signal(dt, carrier_freq=510.0, sample_rate=SAMPLE_RATE,
                      duration_s=125, dst=True, snr_db=30.0):
    """Genera audio sintético con la modulación ALS162 que codifica el datetime
    `dt` como tiempo del MINUTO siguiente al primer marcador. Útil para verificar
    el decodificador end-to-end sin necesidad de captura real."""
    n = duration_s * sample_rate
    t = np.arange(n) / sample_rate
    # Plantilla de pulso (sin normalizar) en radianes
    nr = int(round(RAMP_MS * sample_rate / 1000))
    pulse = np.concatenate([
        np.linspace(0,  1, nr,    endpoint=False),
        np.linspace(1, -1, 2*nr, endpoint=False),
        np.linspace(-1, 0, nr,    endpoint=True),
    ]) * PULSE_AMP_RAD
    pulse_len = len(pulse)

    # Construye el frame de bits para `dt`
    bits = build_frame_bits(dt, dst=dst)

    phase_track = np.zeros(n, dtype=np.float64)
    # Empezamos con un marcador (segundo 59) seguido del minuto cuya hora es `dt`
    # Así el decoder ve: marcador, bit0, bit1, ..., bit58, marcador, ...
    # Layout: segundo 0 inicia en t=1.0 (justo después del marcador)
    sec_offset = 1.0  # arrancamos con un segundo limpio inicial
    # Primer marcador: nada en [0..1]
    # Luego para cada bit i en [0..58], pulsos según valor
    second_start = sec_offset
    for i, b in enumerate(bits):
        s0 = int(second_start * sample_rate)
        if s0 + pulse_len <= n:
            phase_track[s0:s0 + pulse_len] += pulse
        if b == 1:
            s1 = s0 + pulse_len
            if s1 + pulse_len <= n:
                phase_track[s1:s1 + pulse_len] += pulse
        second_start += 1.0
    # Segundo 59 (marcador): nada
    # Ahora repite el frame (mismo bits) para tener 2 minutos de señal
    second_start += 1.0
    for i, b in enumerate(bits):
        s0 = int(second_start * sample_rate)
        if s0 + pulse_len <= n:
            phase_track[s0:s0 + pulse_len] += pulse
        if b == 1:
            s1 = s0 + pulse_len
            if s1 + pulse_len <= n:
                phase_track[s1:s1 + pulse_len] += pulse
        second_start += 1.0

    # Señal: amplitud constante con la fase modulada
    signal = np.cos(2 * np.pi * carrier_freq * t + phase_track)
    # Ruido
    sig_pow = 0.5
    noise_pow = sig_pow / (10 ** (snr_db / 10.0))
    noise = np.random.normal(0, np.sqrt(noise_pow), n)
    audio = (signal + noise) * 16000  # escala a int16-like
    return audio.astype(np.float64), bits


def build_frame_bits(dt, dst=True):
    """Construye los 59 bits de un frame ALS162 para el datetime `dt`.
    La hora codificada es la del MINUTO QUE EMPIEZA, según protocolo."""
    bits = [0] * FRAME_BITS
    bits[0]  = 0
    # bits 1..14 mayormente 0
    bits[17] = 1 if dst else 0
    bits[18] = 0 if dst else 1
    bits[20] = 1
    # minutos
    m = dt.minute
    for i in range(4):
        bits[21 + i] = (m % 10 >> i) & 1
    for i in range(3):
        bits[25 + i] = (m // 10 >> i) & 1
    bits[28] = sum(bits[21:28]) % 2  # paridad par
    # horas
    h = dt.hour
    for i in range(4):
        bits[29 + i] = (h % 10 >> i) & 1
    for i in range(2):
        bits[33 + i] = (h // 10 >> i) & 1
    bits[35] = sum(bits[29:35]) % 2
    # día del mes
    d = dt.day
    for i in range(4):
        bits[36 + i] = (d % 10 >> i) & 1
    for i in range(2):
        bits[40 + i] = (d // 10 >> i) & 1
    # día de la semana (1=Lun..7=Dom)
    wd = dt.isoweekday()
    for i in range(3):
        bits[42 + i] = (wd >> i) & 1
    # mes
    mo = dt.month
    for i in range(4):
        bits[45 + i] = (mo % 10 >> i) & 1
    bits[49] = (mo // 10) & 1
    # año (2 dígitos)
    y = dt.year % 100
    for i in range(4):
        bits[50 + i] = (y % 10 >> i) & 1
    for i in range(4):
        bits[54 + i] = (y // 10 >> i) & 1
    bits[58] = sum(bits[36:58]) % 2
    return bits


def run_simulate():
    print(HEADER)
    print(_t('sim_start'))
    test_dt = datetime(2026, 5, 3, 14, 30)
    print(_t('sim_gen', dt=test_dt))
    audio, bits = synthesize_signal(test_dt, dst=True, snr_db=25)
    sr = SAMPLE_RATE
    fc = detect_carrier_from_samples(audio[:5*sr], sr)
    print(_t('sim_carrier', fc=fc))

    decoded = []
    def on_frame(f):
        decoded.append(f)
        print(f)

    proc = ALS162Processor(sr, fc, on_frame, verbose=False)
    win = PROCESS_WINDOW_S * sr
    hop = PROCESS_HOP_S * sr
    pos = 0
    while pos + win <= len(audio):
        proc.process_window(audio[pos:pos + win], pos)
        pos += hop
    if pos < len(audio):
        proc.process_window(audio[pos:], pos)

    if not decoded:
        print(_t('sim_fail_none')); sys.exit(1)
    f0 = decoded[0]
    if not f0.valid:
        print(_t('sim_fail_inv', err=f0.error)); sys.exit(1)
    if (f0.year, f0.month, f0.day, f0.hour, f0.minute) != \
       (test_dt.year, test_dt.month, test_dt.day, test_dt.hour, test_dt.minute):
        print(_t('sim_fail_time')); sys.exit(1)
    print(_t('sim_ok'))


# ── CLI ───────────────────────────────────────────────────────────────────────
def list_devices():
    if pyaudio is None:
        sys.exit("pyaudio no instalado")
    pa = pyaudio.PyAudio()
    print(f"\n{'Idx':>4}  {_t('dev_name'):<44}  {_t('dev_inputs')}")
    print("─" * 60)
    seen_names = set()
    for i in range(pa.get_device_count()):
        d = pa.get_device_info_by_index(i)
        if d["maxInputChannels"] > 0:
            name = d["name"]
            if name in seen_names:
                continue
            seen_names.add(name)
            print(f"{i:>4}  {name[:44]:<44}  {int(d['maxInputChannels'])}")
    pa.terminate()


def main():
    ap = argparse.ArgumentParser(
        description="Decodificador ALS162 (162 kHz, modulación de fase ±1 rad)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python als162_decoder.py --list
  python als162_decoder.py --device 2 --verbose
  python als162_decoder.py --device 2 --freq 510.155
  python als162_decoder.py --device 2 --set-time
  python als162_decoder.py --device 2 --set-time --utc 2
  python als162_decoder.py --device 2 --record 180 captura.wav
  python als162_decoder.py --play captura.wav --verbose
  python als162_decoder.py --simulate
        """)
    ap.add_argument("--list",     action="store_true", help="Lista dispositivos y sale")
    ap.add_argument("--device",   type=int,   default=None,
                    help="Indice dispositivo entrada")
    ap.add_argument("--rate",     type=int,   default=SAMPLE_RATE,
                    help=f"Sample rate Hz (def {SAMPLE_RATE})")
    ap.add_argument("--freq",     type=float, default=None,
                    help="Portadora en audio Hz (def: auto-detectar)")
    ap.add_argument("--verbose",  action="store_true",
                    help="Muestra detección de pulsos, bits y eventos de timing")
    ap.add_argument("--record",   nargs=2,   metavar=("SEC", "WAV"),
                    help="Graba SEC segundos a WAV y termina")
    ap.add_argument("--play",     metavar="WAV",
                    help="Decodifica un WAV en lugar de capturar en vivo")
    ap.add_argument("--simulate", action="store_true",
                    help="Genera señal sintética y verifica el decodificador end-to-end")
    ap.add_argument("--set-time", action="store_true",
                    help="Ajusta el reloj del sistema tras el primer frame válido "
                         "(Linux/macOS: requiere sudo; Windows: requiere Administrador)")
    ap.add_argument("--utc",      type=int,   default=None,
                    metavar="OFFSET",
                    help="UTC offset del usuario para mostrar y sincronizar la hora "
                         "(ej. --utc 2 para UTC+2). Si se omite, se usa la hora de Francia.")
    ap.add_argument("--lang",     choices=['en', 'es'], default='en',
                    help="Output language: 'en' English (default) or 'es' Spanish")
    args = ap.parse_args()

    global _LANG
    _LANG = args.lang

    if args.simulate:
        run_simulate()
        return

    if args.list:
        list_devices()
        return

    if args.record:
        seconds = int(args.record[0])
        path    = args.record[1]
        record_wav(args.device, args.rate, seconds, path)
        return

    if args.play:
        run_offline_wav(args.play, carrier_freq=args.freq, verbose=args.verbose,
                        set_time=args.set_time, utc_offset=args.utc)
        return

    run_live(args.device, args.rate, args.freq, verbose=args.verbose,
             set_time=args.set_time, utc_offset=args.utc)


if __name__ == "__main__":
    main()
