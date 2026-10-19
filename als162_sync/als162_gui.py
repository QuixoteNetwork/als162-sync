#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ALS162 GUI — Graphic Interface PyQt5
====================================
Require file als162_decoder.py in the same folder

"""

import sys
import os
import time
import threading
from datetime import datetime

import numpy as np

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QTextEdit, QFrame,
    QSystemTrayIcon, QMenu, QAction, QSizePolicy, QGroupBox,
    QCheckBox, QProgressBar, QSpinBox,
)
from PyQt5.QtCore  import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui   import QFont, QIcon, QPixmap, QColor, QPainter, QPen

# ── Importar decoder ──────────────────────────────────────────────────────────
_here = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
if _here not in sys.path:
    sys.path.insert(0, _here)

try:
    import als162_decoder as dec
except ImportError:
    print("ERROR: als162_decoder.py: not found in the same folder / No encontrado en el mismo directorio")
    sys.exit(1)

try:
    import pyaudio
except ImportError:
    print("ERROR: pip install pyaudio")
    sys.exit(1)


# ── Traducciones ──────────────────────────────────────────────────────────────
T = {
    'es': {
        'title':         'ALS162 SYNC por Quixote Network v0.2',
        'device':        'Dispositivo:',
        'refresh':       'Actualizar Lista',
        'start':         '▶  Iniciar',
        'stop':          '⏹  Detener',
        'set_time_chk':  'Ajustar hora del SO',
        'set_time_ok':   '✔  Hora del sistema ajustada',
        'detecting':     'Midiendo portadora (5 s)…',
        'waiting':       'Esperando primer frame (~70 s)…',
        'running':       'Decodificando',
        'stopped':       'Detenido',
        'carrier':       'Portadora',
        'log_title':     'Historial de frames',
        'clear':         'Limpiar',
        'tray_show':     'Mostrar',
        'tray_hide':     'Ocultar',
        'tray_quit':     'Salir',
        'lang':          'EN',
        'lang_lbl':      'Idioma:',
        'today':         'Hoy',
        'hol_ann_lbl':   'Festivo próximo',
        'holiday':       '🎉 Festivo',
        'no_holiday':    '✓ No festivo',
        'hol_ann_yes':   '⚠ Anunciado esta semana',
        'hol_ann_no':    '✓ No anunciado',
        'dst_change':    '⚠ Cambio de hora próximo',
        'leap':          '⚠ Leap second anunciado',
        'invalid':       'Frame inválido',
        # Panel señal
        'sig_title':     'Señal / Ajuste SDR',
        'sig_level':     'Nivel:',
        'sig_carrier':   'Portadora:',
        'sig_snr':       'SNR:',
        'sig_clip':      'Clipping:',
        'sig_peaks':     'Top picos:',
        'sig_none':      '—',
        'tip_low':        '🔴  Señal débil — sube la ganancia RF/IF del SDR o el volumen de línea',
        'tip_ok':         '🟢  Nivel correcto — la decodificación debería funcionar bien',
        'tip_high':       '🟡  Señal saturada — baja la ganancia para evitar distorsión de fase',
        'tip_snr_primary':'🟡  Nivel en rango pero SNR bajo — revisa modo USB del SDR, ganancia RF o antena',
        'tip_none':       'Inicia el decodificador para ver el nivel de señal',
        'tip_snr_warn':   ' · SNR bajo (<15 dB): revisa modo USB del SDR o antena',
        'tip_clip_warn':  ' · Saturación digital detectada: reduce la ganancia',
        'log_synced':    '✔ PC Sync',
        'err_admin':     '⛔ Error al ajustar hora: ejecuta el programa como Administrador',
        'tz_offset_lbl': 'Zona UTC (Por Defecto: Hora Francia):',
        'tz_offset_tip': 'Tu desplazamiento UTC\n(ej. UTC+2 para Europa del Este en invierno,\nUTC+3 en verano)',
        # Panel estadísticas
        'stats_title':   'Estadísticas de decodificación',
        'stats_frames':  'Frames totales:',
        'stats_valid':   'Válidos:',
        'stats_invalid': 'Inválidos:',
        'stats_bits':    'Bits emitidos:',
        'stats_last':    'Último frame:',
        'stats_never':   'ninguno aún',
        'stats_ago':     'hace {n} s',
        'DOW': ["","Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"],
        'MON': ["","Enero","Febrero","Marzo","Abril","Mayo","Junio",
                "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"],
    },
    'en': {
        'title':         'ALS162 SYNC by Quixote Network v0.2',
        'device':        'Device:',
        'refresh':       'Update List',
        'start':         '▶  Start',
        'stop':          '⏹  Stop',
        'set_time_chk':  'Set OS time on first sync',
        'set_time_ok':   '✔  System time set',
        'detecting':     'Measuring carrier (5 s)…',
        'waiting':       'Waiting for first frame (~70 s)…',
        'running':       'Decoding',
        'stopped':       'Stopped',
        'carrier':       'Carrier',
        'log_title':     'Frame history',
        'clear':         'Clear',
        'tray_show':     'Show',
        'tray_hide':     'Hide',
        'tray_quit':     'Quit',
        'lang':          'ES',
        'lang_lbl':      'Language:',
        'today':         'Today',
        'hol_ann_lbl':   'Upcoming holiday',
        'holiday':       '🎉 Holiday',
        'no_holiday':    '✓ Not a holiday',
        'hol_ann_yes':   '⚠ Announced this week',
        'hol_ann_no':    '✓ Not announced',
        'dst_change':    '⚠ DST change upcoming',
        'leap':          '⚠ Leap second announced',
        'invalid':       'Invalid frame',
        # Signal panel
        'sig_title':     'Signal / SDR Setup',
        'sig_level':     'Level:',
        'sig_carrier':   'Carrier:',
        'sig_snr':       'SNR:',
        'sig_clip':      'Clipping:',
        'sig_peaks':     'Top peaks:',
        'sig_none':      '—',
        'tip_low':        '🔴  Signal too weak — increase SDR RF/IF gain or line volume',
        'tip_ok':         '🟢  Level OK — decoding should work correctly',
        'tip_high':       '🟡  Signal clipping — reduce gain to avoid phase distortion',
        'tip_snr_primary':'🟡  Level in range but SNR too low — check SDR USB mode, RF gain or antenna',
        'tip_none':       'Start the decoder to see signal level',
        'tip_snr_warn':   ' · Low SNR (<15 dB): check SDR USB mode or antenna',
        'tip_clip_warn':  ' · Digital clipping detected: reduce gain',
        'log_synced':    '✔ PC Sync',
        'err_admin':     '⛔ Time sync failed: run the program as Administrator',
        'tz_offset_lbl': 'UTC zone (Default France Time):',
        'tz_offset_tip': 'Your UTC offset\n(e.g. UTC+2 for Eastern Europe in winter,\nUTC+3 in summer)',
        # Stats panel
        'stats_title':   'Decode Statistics',
        'stats_frames':  'Total frames:',
        'stats_valid':   'Valid:',
        'stats_invalid': 'Invalid:',
        'stats_bits':    'Bits emitted:',
        'stats_last':    'Last frame:',
        'stats_never':   'none yet',
        'stats_ago':     '{n} s ago',
        'DOW': ["","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"],
        'MON': ["","January","February","March","April","May","June",
                "July","August","September","October","November","December"],
    },
}

# ── Utils ─────────────────────────────────────────────────────────────────────
def resource_path(relative_path):
    """Funciona en desarrollo y también con PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

# ── Widget de espectro ────────────────────────────────────────────────────────
class SpectrumWidget(QWidget):
    F_LO, F_HI = 300, 800

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(70)
        self.setMinimumWidth(200)
        self._freqs = self._amps = self._carrier = None
        self.setStyleSheet('background:#1a1a2e; border-radius:4px;')

    def update_data(self, freqs, amps, carrier):
        self._freqs = freqs; self._amps = amps; self._carrier = carrier
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h, pad_b = self.width(), self.height(), 18
        p.fillRect(0, 0, w, h, QColor('#1a1a2e'))

        # grid
        p.setPen(QPen(QColor('#333355'), 1, Qt.DotLine))
        for f in range(350, 801, 50):
            x = int((f - self.F_LO) / (self.F_HI - self.F_LO) * w)
            p.drawLine(x, 0, x, h - pad_b)

        if self._freqs is None or len(self._freqs) == 0:
            p.setPen(QColor('#5566aa'))
            p.setFont(QFont('Courier New', 8))
            p.drawText(0, 0, w, h - pad_b, Qt.AlignCenter, '— sin señal —')
        else:
            amps = self._amps / (self._amps.max() or 1)
            bar_h = h - pad_b
            bar_w = max(1, w / len(self._freqs))
            for i, (f, a) in enumerate(zip(self._freqs, amps)):
                x  = int((f - self.F_LO) / (self.F_HI - self.F_LO) * w)
                bh = int(a * bar_h)
                if self._carrier and abs(f - self._carrier) < 15:
                    color = QColor('#00e5ff')
                else:
                    color = QColor(int(30+a*60), int(100+a*80), int(200+a*55))
                p.fillRect(int(x - bar_w/2), bar_h - bh, max(1, int(bar_w)), bh, color)

        if self._carrier and self.F_LO <= self._carrier <= self.F_HI:
            xc = int((self._carrier - self.F_LO) / (self.F_HI - self.F_LO) * w)
            p.setPen(QPen(QColor('#ff4444'), 2))
            p.drawLine(xc, 0, xc, h - pad_b)
            p.setPen(QColor('#ff8888'))
            p.setFont(QFont('Courier New', 7))
            lx = max(2, min(xc - 16, w - 44))
            p.drawText(lx, 0, 50, 12, Qt.AlignLeft, f'{self._carrier:.0f}Hz')

        p.setPen(QColor('#8888bb'))
        p.setFont(QFont('Courier New', 7))
        for f in [350, 400, 450, 500, 550, 600, 650, 700, 750]:
            x = int((f - self.F_LO) / (self.F_HI - self.F_LO) * w)
            p.drawText(x - 12, h - pad_b + 2, 30, pad_b - 2, Qt.AlignCenter, str(f))
        p.end()


# ── SpinBox con signo explicito (+0, +1, -3…) ────────────────────────────────
class SignedSpinBox(QSpinBox):
    def textFromValue(self, value):
        return f'+{value}' if value >= 0 else str(value)


# ── Hilo decodificador ────────────────────────────────────────────────────────
class DecoderThread(QThread):
    frame_signal    = pyqtSignal(object)   # ALS162Frame
    status_signal   = pyqtSignal(str)
    carrier_signal  = pyqtSignal(float)
    level_signal    = pyqtSignal(float)    # dBFS
    spectrum_signal = pyqtSignal(object)   # dict

    _SPECTRUM_INTERVAL = 0.25

    def __init__(self, device_index):
        super().__init__()
        self.device_index = device_index
        self._stop      = threading.Event()
        self._carrier   = None
        self._last_spec = 0.0

    def stop(self):
        self._stop.set()

    def run(self):
        self._stop.clear()
        self.status_signal.emit('detecting')
        try:
            fc = dec.detect_carrier_live(
                self.device_index, dec.SAMPLE_RATE, silent=True)
        except Exception as e:
            self.status_signal.emit(f'error:{e}')
            return

        self._carrier = fc
        self.carrier_signal.emit(fc)
        self.status_signal.emit('running')

        proc = dec.ALS162Processor(
            dec.SAMPLE_RATE, fc,
            lambda frame: self.frame_signal.emit(frame),
            verbose=False,
        )

        rolling = np.zeros(0, dtype=np.float64)
        rolling_start = 0
        last_proc = 0
        lock = threading.Lock()

        def on_chunk(samples, abs_start):
            nonlocal rolling, rolling_start, last_proc
            if self._stop.is_set():
                return

            # Nivel RMS en dBFS (referencia = full-scale int16 = 32768)
            rms = np.sqrt(np.mean(samples ** 2))
            self.level_signal.emit(20.0 * np.log10(max(rms, 1.0) / 32768.0))

            # Espectro + SNR + clipping + top picos (throttled)
            now = time.monotonic()
            if now - self._last_spec >= self._SPECTRUM_INTERVAL:
                self._last_spec = now
                n     = min(len(samples), 8192)
                win   = np.hanning(n)
                spec  = np.abs(np.fft.rfft(samples[:n] * win))
                freqs = np.fft.rfftfreq(n, 1.0 / dec.SAMPLE_RATE)
                mask  = (freqs >= SpectrumWidget.F_LO) & (freqs <= SpectrumWidget.F_HI)
                fm, sm = freqs[mask], spec[mask]

                # SNR
                fc_now = self._carrier
                if fc_now and len(sm) and sm.max() > 0:
                    sig_m = np.abs(fm - fc_now) <= 12
                    n_med = np.median(sm[~sig_m]) if (~sig_m).any() else 1e-9
                    snr   = 20.0 * np.log10(sm[sig_m].max() / max(n_med, 1e-9)) \
                            if sig_m.any() else 0.0
                else:
                    n_med = np.median(sm) if len(sm) else 1e-9
                    snr   = 20.0 * np.log10(sm.max() / max(n_med, 1e-9)) if len(sm) else 0.0

                # Clipping (int16 scale)
                clip_pct = 100.0 * float(np.mean(np.abs(samples) >= 32000))

                # Top 5
                top5 = []
                if len(sm):
                    t_max = sm.max()
                    top5 = [(float(fm[i]), 100.0 * float(sm[i]) / t_max)
                            for i in np.argsort(sm)[-5:][::-1]]

                self.spectrum_signal.emit({
                    'freqs': fm, 'amps': sm, 'carrier': fc_now,
                    'snr_db': snr, 'clip_pct': clip_pct, 'top5': top5,
                })

            # Buffer rolling
            with lock:
                if len(rolling) == 0:
                    rolling = samples.copy(); rolling_start = abs_start
                else:
                    rolling = np.concatenate([rolling, samples])
                win_s = dec.PROCESS_WINDOW_S * dec.SAMPLE_RATE
                hop_s = dec.PROCESS_HOP_S   * dec.SAMPLE_RATE
                while True:
                    ns = max(last_proc, rolling_start)
                    if ns + win_s > rolling_start + len(rolling):
                        break
                    proc.process_window(
                        rolling[ns - rolling_start: ns - rolling_start + win_s], ns)
                    last_proc = ns + hop_s
                kf = max(0, last_proc - rolling_start - win_s)
                if kf > 0:
                    rolling = rolling[kf:]; rolling_start += kf

        cap = dec.LiveAudioCapture(self.device_index, dec.SAMPLE_RATE, on_chunk)
        cap.start()
        self._stop.wait()
        cap.stop()
        self.status_signal.emit('stopped')


# ── Ventana principal ─────────────────────────────────────────────────────────
class MainWindow(QMainWindow):

    _DB_LOW  = -45.0
    _DB_HIGH = -10.0

    def __init__(self):
        super().__init__()
        self.lang        = 'en'
        self.thread      = None
        self.last_frame  = None
        self._fc         = None
        self._user_utc   = 0    # UTC offset del usuario; se auto-ajusta al recibir el primer frame
        self._tz_user_set = False  # True cuando el usuario lo ha cambiado manualmente
        # estadísticas
        self._stat_total   = 0
        self._stat_valid   = 0
        self._stat_invalid = 0
        self._stat_bits    = 0
        self._last_frame_ts: float = None   # time.monotonic()

        self._build_ui()
        self._build_tray()
        self._refresh_devices()

        # Timer para "hace N s"
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick_last_frame)
        self._timer.start(1000)

        self._center_on_screen()

    def t(self, key):
        return T[self.lang].get(key, key)

    def _center_on_screen(self):
        """Centra la ventana en la pantalla principal sin salirse de los bordes."""
        self.adjustSize()
        screen = QApplication.primaryScreen().availableGeometry()
        w, h = self.width(), self.height()
        x = screen.x() + (screen.width()  - w) // 2
        y = screen.y() + (screen.height() - h) // 2
        # Asegurar que no quede recortada por arriba ni por abajo
        y = max(screen.y(), min(y, screen.y() + screen.height() - h))
        self.move(x, y)

    # ── UI ───────────────────────────────────────────────────────────────────
    def _build_ui(self):
        self.setWindowTitle(self.t('title'))
        self.setMinimumWidth(660)

        root_w = QWidget()
        self.setCentralWidget(root_w)
        root = QVBoxLayout(root_w)
        root.setSpacing(7)
        root.setContentsMargins(14, 10, 14, 8)

        # ── Fila dispositivo ─────────────────────────────────────────────
        row_dev = QHBoxLayout()
        self.lbl_device = QLabel(self.t('device'))
        self.lbl_device.setStyleSheet('font-size: 9pt; color: #555;')
        row_dev.addWidget(self.lbl_device)
        self.combo = QComboBox()
        self.combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo.setMaximumWidth(300)
        row_dev.addWidget(self.combo)
        self.btn_ref = QPushButton(self.t('refresh'))
        self.btn_ref.clicked.connect(self._refresh_devices)
        row_dev.addWidget(self.btn_ref)
        row_dev.addStretch()
        self.lbl_lang = QLabel(self.t('lang_lbl'))
        self.lbl_lang.setStyleSheet('font-size: 9pt; color: #555;')
        row_dev.addWidget(self.lbl_lang)
        self.btn_lang = QPushButton(self.t('lang')); self.btn_lang.setFixedWidth(36)
        self.btn_lang.clicked.connect(self._toggle_lang)
        row_dev.addWidget(self.btn_lang)
        root.addLayout(row_dev)
        root.addWidget(self._sep())

        # ── Panel reloj ──────────────────────────────────────────────────
        panel = QWidget()
        panel.setStyleSheet('background:#f5f5f5; border-radius:8px;')
        pv = QVBoxLayout(panel); pv.setSpacing(3); pv.setContentsMargins(10,10,10,8)

        self.lbl_time = QLabel('--:--')
        self.lbl_time.setAlignment(Qt.AlignCenter)
        self.lbl_time.setFont(QFont('Courier New', 68, QFont.Bold))
        pv.addWidget(self.lbl_time)

        self.lbl_tz = QLabel('')
        self.lbl_tz.setAlignment(Qt.AlignCenter)
        f11 = QFont(); f11.setPointSize(11)
        self.lbl_tz.setFont(f11); self.lbl_tz.setStyleSheet('color:#555;')
        pv.addWidget(self.lbl_tz)

        self.lbl_date = QLabel('')
        self.lbl_date.setAlignment(Qt.AlignCenter)
        f14b = QFont(); f14b.setPointSize(14); f14b.setBold(True)
        self.lbl_date.setFont(f14b)
        pv.addWidget(self.lbl_date)

        row_hol = QHBoxLayout(); row_hol.setAlignment(Qt.AlignCenter); row_hol.setSpacing(16)
        f9b = QFont(); f9b.setPointSize(9); f9b.setBold(True)
        f10 = QFont(); f10.setPointSize(10)
        for at, av in [('lbl_hoy_title','lbl_hoy'), ('lbl_man_title','lbl_man')]:
            grp = QGroupBox(); gv = QVBoxLayout(grp)
            gv.setContentsMargins(8,4,8,4); gv.setSpacing(2)
            lt = QLabel(); lt.setAlignment(Qt.AlignCenter); lt.setFont(f9b)
            lv = QLabel('—'); lv.setAlignment(Qt.AlignCenter); lv.setFont(f10)
            gv.addWidget(lt); gv.addWidget(lv)
            setattr(self, at, lt); setattr(self, av, lv)
            row_hol.addWidget(grp)
        pv.addLayout(row_hol)

        self.lbl_ann = QLabel('')
        self.lbl_ann.setAlignment(Qt.AlignCenter)
        self.lbl_ann.setStyleSheet('color:#c80; font-style:italic;')
        pv.addWidget(self.lbl_ann)
        root.addWidget(panel)
        root.addWidget(self._sep())

        # ── Panel señal SDR ──────────────────────────────────────────────
        sig_box = QGroupBox()
        sv = QVBoxLayout(sig_box); sv.setSpacing(4); sv.setContentsMargins(8,6,8,6)

        self.lbl_sig_title = QLabel(self.t('sig_title'))
        fb = QFont(); fb.setBold(True); fb.setPointSize(9)
        self.lbl_sig_title.setFont(fb)
        sv.addWidget(self.lbl_sig_title)

        # Fila 1: nivel
        r1 = QHBoxLayout()
        self.lbl_sig_level_lbl = QLabel(self.t('sig_level')); self.lbl_sig_level_lbl.setFixedWidth(52)
        r1.addWidget(self.lbl_sig_level_lbl)
        self.bar_level = QProgressBar()
        self.bar_level.setRange(0,100); self.bar_level.setValue(0)
        self.bar_level.setFixedHeight(14); self.bar_level.setTextVisible(False)
        self.bar_level.setStyleSheet(self._bar_css('gray'))
        r1.addWidget(self.bar_level)
        self.lbl_db = QLabel('—'); self.lbl_db.setFixedWidth(52)
        self.lbl_db.setAlignment(Qt.AlignRight|Qt.AlignVCenter)
        self.lbl_db.setFont(QFont('Courier New', 9))
        r1.addWidget(self.lbl_db)
        sv.addLayout(r1)

        # Fila 2: portadora | SNR | clipping
        r2 = QGridLayout(); r2.setHorizontalSpacing(12); r2.setVerticalSpacing(2)
        f9 = QFont(); f9.setPointSize(9)
        fmono = QFont('Courier New', 9)

        self.lbl_fc_lbl   = QLabel(self.t('sig_carrier')); self.lbl_fc_lbl.setFont(f9)
        self.lbl_fc_val   = QLabel(self.t('sig_none'));     self.lbl_fc_val.setFont(fmono)
        self.lbl_snr_lbl  = QLabel(self.t('sig_snr'));      self.lbl_snr_lbl.setFont(f9)
        self.lbl_snr_val  = QLabel(self.t('sig_none'));     self.lbl_snr_val.setFont(fmono)
        self.lbl_clip_lbl = QLabel(self.t('sig_clip'));     self.lbl_clip_lbl.setFont(f9)
        self.lbl_clip_val = QLabel(self.t('sig_none'));     self.lbl_clip_val.setFont(fmono)

        r2.addWidget(self.lbl_fc_lbl,   0, 0); r2.addWidget(self.lbl_fc_val,   0, 1)
        r2.addWidget(self.lbl_snr_lbl,  0, 2); r2.addWidget(self.lbl_snr_val,  0, 3)
        r2.addWidget(self.lbl_clip_lbl, 0, 4); r2.addWidget(self.lbl_clip_val, 0, 5)
        sv.addLayout(r2)

        # Espectro
        self.spectrum = SpectrumWidget()
        sv.addWidget(self.spectrum)

        # Top picos
        r3 = QHBoxLayout()
        self.lbl_peaks_lbl = QLabel(self.t('sig_peaks')); self.lbl_peaks_lbl.setFont(f9)
        self.lbl_peaks_lbl.setFixedWidth(64)
        r3.addWidget(self.lbl_peaks_lbl)
        self.lbl_peaks_val = QLabel(self.t('sig_none'))
        self.lbl_peaks_val.setFont(QFont('Courier New', 8))
        self.lbl_peaks_val.setWordWrap(True)
        r3.addWidget(self.lbl_peaks_val)
        sv.addLayout(r3)

        # Consejo
        self.lbl_tip = QLabel(self.t('tip_none'))
        self.lbl_tip.setWordWrap(True)
        ft = QFont(); ft.setPointSize(8)
        self.lbl_tip.setFont(ft)
        sv.addWidget(self.lbl_tip)
        root.addWidget(sig_box)
        root.addWidget(self._sep())

        # ── Panel estadísticas ────────────────────────────────────────────
        stat_box = QGroupBox()
        stv = QVBoxLayout(stat_box); stv.setSpacing(3); stv.setContentsMargins(8,6,8,6)

        self.lbl_stats_title = QLabel(self.t('stats_title'))
        self.lbl_stats_title.setFont(fb)
        stv.addWidget(self.lbl_stats_title)

        rg = QGridLayout(); rg.setHorizontalSpacing(14); rg.setVerticalSpacing(2)
        vals = [
            ('lbl_st_frames_lbl', 'stats_frames', 'lbl_st_frames_val'),
            ('lbl_st_valid_lbl',  'stats_valid',  'lbl_st_valid_val'),
            ('lbl_st_inv_lbl',    'stats_invalid','lbl_st_inv_val'),
            ('lbl_st_bits_lbl',   'stats_bits',   'lbl_st_bits_val'),
        ]
        for col, (al, tk, av) in enumerate(vals):
            lbl = QLabel(self.t(tk)); lbl.setFont(f9)
            val = QLabel('0');        val.setFont(fmono)
            rg.addWidget(lbl, 0, col*2); rg.addWidget(val, 0, col*2+1)
            setattr(self, al, lbl); setattr(self, av, val)
        stv.addLayout(rg)

        r_last = QHBoxLayout()
        self.lbl_last_lbl = QLabel(self.t('stats_last')); self.lbl_last_lbl.setFont(f9)
        self.lbl_last_val = QLabel(self.t('stats_never')); self.lbl_last_val.setFont(fmono)
        r_last.addWidget(self.lbl_last_lbl); r_last.addWidget(self.lbl_last_val)
        r_last.addStretch()
        stv.addLayout(r_last)
        root.addWidget(stat_box)
        root.addWidget(self._sep())

        # ── Botones ───────────────────────────────────────────────────────
        row_btn = QHBoxLayout()
        f11b = QFont(); f11b.setPointSize(11)
        self.btn_start = QPushButton(self.t('start'))
        self.btn_start.setFixedHeight(36); self.btn_start.setFont(f11b)
        self.btn_start.clicked.connect(self._toggle_decoder)
        row_btn.addWidget(self.btn_start)
        self.chk_settime = QCheckBox(self.t('set_time_chk'))
        self.chk_settime.setStyleSheet('font-size: 10pt; color: #555;')
        row_btn.addWidget(self.chk_settime)
        row_btn.addStretch()

        # Offset de zona horaria respecto a Francia
        self.lbl_tz_offset = QLabel(self.t('tz_offset_lbl'))
        self.lbl_tz_offset.setStyleSheet('font-size: 9pt; color: #555;')
        self.lbl_tz_offset.setToolTip(self.t('tz_offset_tip'))
        row_btn.addWidget(self.lbl_tz_offset)
        self.spin_tz = SignedSpinBox()
        self.spin_tz.setRange(-12, 14)
        self.spin_tz.setValue(0)
        self.spin_tz.setFixedWidth(52)
        self.spin_tz.setToolTip(self.t('tz_offset_tip'))
        self.spin_tz.valueChanged.connect(self._on_tz_offset_changed)
        row_btn.addWidget(self.spin_tz)
        root.addLayout(row_btn)

        # ── Historial ─────────────────────────────────────────────────────
        rh = QHBoxLayout()
        self.lbl_log_title = QLabel(self.t('log_title'))
        fbl = QFont(); fbl.setBold(True)
        self.lbl_log_title.setFont(fbl)
        rh.addWidget(self.lbl_log_title); rh.addStretch()
        self.btn_clear = QPushButton(self.t('clear')); self.btn_clear.setFixedHeight(22)
        self.btn_clear.clicked.connect(lambda: self.log.clear())
        rh.addWidget(self.btn_clear)
        root.addLayout(rh)

        self.log = QTextEdit()
        self.log.setReadOnly(True); self.log.setFixedHeight(88)
        self.log.setFont(QFont('Courier New', 9))
        root.addWidget(self.log)

        self.statusBar().showMessage(self.t('stopped'))
        self._update_holiday_labels()

    @staticmethod
    def _sep():
        s = QFrame(); s.setFrameShape(QFrame.HLine); s.setFrameShadow(QFrame.Sunken)
        return s

    @staticmethod
    def _bar_css(color):
        c = {'green':'#4caf50','yellow':'#ffc107','red':'#f44336','gray':'#888888'}.get(color,'#888888')
        return (f'QProgressBar::chunk{{background:{c};border-radius:3px;}}'
                f'QProgressBar{{border:1px solid #bbb;border-radius:3px;background:#eee;}}')

    # ── Tray ─────────────────────────────────────────────────────────────────
    def _build_tray(self):
        pix = QPixmap(16,16); pix.fill(Qt.transparent)
        p = QPainter(pix); p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor('#1976D2')); p.setPen(Qt.NoPen); p.drawEllipse(1,1,14,14); p.end()
        self.tray = QSystemTrayIcon(QIcon(pix), self)
        menu = QMenu()
        self.act_show = QAction(self.t('tray_show'), self)
        self.act_show.triggered.connect(self._tray_toggle)
        menu.addAction(self.act_show); menu.addSeparator()
        act_quit = QAction(self.t('tray_quit'), self)
        act_quit.triggered.connect(QApplication.quit)
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self._tray_toggle() if r == QSystemTrayIcon.DoubleClick else None)
        self.tray.setToolTip('ALS162'); self.tray.show()

    def _tray_toggle(self):
        if self.isVisible():
            self.hide(); self.act_show.setText(self.t('tray_show'))
        else:
            self.show(); self.raise_(); self.activateWindow()
            self.act_show.setText(self.t('tray_hide'))

    def closeEvent(self, event):
        event.accept(); QApplication.quit()

    # ── Dispositivos ─────────────────────────────────────────────────────────
    def _refresh_devices(self):
        self.combo.clear()
        try:
            pa = pyaudio.PyAudio()
            seen_names = set()
            for i in range(pa.get_device_count()):
                d = pa.get_device_info_by_index(i)
                if d['maxInputChannels'] > 0:
                    name = d['name']
                    if name in seen_names:
                        continue          # omitir duplicado (misma API distinta)
                    seen_names.add(name)
                    self.combo.addItem(f"{i}: {name[:52]}", userData=i)
            pa.terminate()
        except Exception as e:
            self.statusBar().showMessage(f'Error: {e}')

    # ── Idioma ────────────────────────────────────────────────────────────────
    def _toggle_lang(self):
        self.lang = 'en' if self.lang == 'es' else 'es'
        self._retranslate()

    def _retranslate(self):
        running = self.thread is not None and self.thread.isRunning()
        self.setWindowTitle(self.t('title'))
        self.lbl_device.setText(self.t('device'))
        self.btn_ref.setText(self.t('refresh'))
        self.lbl_lang.setText(self.t('lang_lbl'))
        self.btn_lang.setText(self.t('lang'))
        self.btn_start.setText(self.t('stop') if running else self.t('start'))
        self.chk_settime.setText(self.t('set_time_chk'))
        self.lbl_tz_offset.setText(self.t('tz_offset_lbl'))
        self.lbl_tz_offset.setToolTip(self.t('tz_offset_tip'))
        self.spin_tz.setToolTip(self.t('tz_offset_tip'))
        self.btn_clear.setText(self.t('clear'))
        self.lbl_log_title.setText(self.t('log_title'))
        self.lbl_sig_title.setText(self.t('sig_title'))
        self.lbl_sig_level_lbl.setText(self.t('sig_level'))
        self.lbl_fc_lbl.setText(self.t('sig_carrier'))
        self.lbl_snr_lbl.setText(self.t('sig_snr'))
        self.lbl_clip_lbl.setText(self.t('sig_clip'))
        self.lbl_peaks_lbl.setText(self.t('sig_peaks'))
        self.lbl_stats_title.setText(self.t('stats_title'))
        self.lbl_st_frames_lbl.setText(self.t('stats_frames'))
        self.lbl_st_valid_lbl.setText(self.t('stats_valid'))
        self.lbl_st_inv_lbl.setText(self.t('stats_invalid'))
        self.lbl_st_bits_lbl.setText(self.t('stats_bits'))
        self.lbl_last_lbl.setText(self.t('stats_last'))
        self.act_show.setText(self.t('tray_show'))
        self._update_holiday_labels()
        if not running:
            self.statusBar().showMessage(self.t('stopped'))
        if self.last_frame and self.last_frame.valid:
            self._apply_frame_to_ui(self.last_frame)

    # ── Festivos ──────────────────────────────────────────────────────────────
    def _update_holiday_labels(self, frame=None):
        """Muestra directamente los bits de festivo del frame actual (igual que el TUI).
        Bit 14 = festivo hoy (específico al día).
        Bit 13 = festivo próximo esta semana (el transmisor lo activa toda la semana
                 que contiene el festivo, no solo el día anterior)."""
        f = frame or (self.last_frame if self.last_frame and self.last_frame.valid else None)

        if f:
            today_date = f"{f.day:02d}/{f.month:02d}"
            self.lbl_hoy_title.setText(f"{self.t('today')} ({today_date})")
            self.lbl_man_title.setText(self.t('hol_ann_lbl'))
            self.lbl_hoy.setText(self.t('holiday')     if f.holiday_today else self.t('no_holiday'))
            self.lbl_man.setText(self.t('hol_ann_yes') if f.holiday_eve   else self.t('hol_ann_no'))
        else:
            self.lbl_hoy_title.setText(self.t('today'))
            self.lbl_man_title.setText(self.t('hol_ann_lbl'))
            self.lbl_hoy.setText('—')
            self.lbl_man.setText('—')

    # ── Nivel ─────────────────────────────────────────────────────────────────
    def _on_level(self, db):
        pct = int(max(0, min(100, (db - (-60.0)) / 55.0 * 100)))
        self.bar_level.setValue(pct)
        self.lbl_db.setText(f'{db:+.1f} dB')
        if db < self._DB_LOW:
            self.bar_level.setStyleSheet(self._bar_css('red'))
        elif db > self._DB_HIGH:
            self.bar_level.setStyleSheet(self._bar_css('yellow'))
        else:
            self.bar_level.setStyleSheet(self._bar_css('green'))

    # ── Espectro ──────────────────────────────────────────────────────────────
    def _on_spectrum(self, data):
        self.spectrum.update_data(data['freqs'], data['amps'], data['carrier'])

        snr  = data.get('snr_db', 0.0)
        clip = data.get('clip_pct', 0.0)
        top5 = data.get('top5', [])

        # SNR
        snr_ok = snr >= 20.0
        self.lbl_snr_val.setText(f'{snr:+.1f} dB  {"✓" if snr_ok else "⚠"}')
        self.lbl_snr_val.setStyleSheet('' if snr_ok else 'color:#c00;')

        # Clipping
        clip_ok = clip < 1.0
        self.lbl_clip_val.setText(f'{clip:.1f}%  {"✓" if clip_ok else "⚠"}')
        self.lbl_clip_val.setStyleSheet('' if clip_ok else 'color:#c80;')

        # Top picos
        if top5:
            parts = [f'#{i+1} {f:.1f}Hz {p:.0f}%' for i, (f, p) in enumerate(top5[:4])]
            self.lbl_peaks_val.setText('   '.join(parts))
        else:
            self.lbl_peaks_val.setText(self.t('sig_none'))

        # Consejo actualizado — un único estado coherente
        db = float(self.lbl_db.text().split()[0]) if self.lbl_db.text() != '—' else -99
        if db < self._DB_LOW:
            tip = self.t('tip_low')
            if snr < 15.0:
                tip += '\n' + self.t('tip_snr_warn')
        elif db > self._DB_HIGH:
            tip = self.t('tip_high')
            if snr < 15.0:
                tip += '\n' + self.t('tip_snr_warn')
        elif snr < 15.0:
            # Nivel en rango pero SNR bajo → advertencia, no 🟢 contradictorio
            tip = self.t('tip_snr_primary')
        else:
            tip = self.t('tip_ok')
        if clip >= 1.0:
            tip += '\n' + self.t('tip_clip_warn')
        self.lbl_tip.setText(tip)

    # ── Control decoder ──────────────────────────────────────────────────────
    def _toggle_decoder(self):
        if self.thread and self.thread.isRunning():
            self.btn_start.setEnabled(False)
            self.thread.stop()
        else:
            idx = self.combo.currentData()
            if idx is None:
                return
            self._fc = None
            self._reset_stats()
            self.thread = DecoderThread(idx)
            self.thread.frame_signal.connect(self._on_frame)
            self.thread.status_signal.connect(self._on_status)
            self.thread.carrier_signal.connect(self._on_carrier)
            self.thread.level_signal.connect(self._on_level)
            self.thread.spectrum_signal.connect(self._on_spectrum)
            self.thread.start()
            self.btn_start.setText(self.t('stop'))
            self.lbl_time.setText('--:--')
            self.lbl_tz.setText(''); self.lbl_date.setText(''); self.lbl_ann.setText('')
            self.lbl_fc_val.setText(self.t('sig_none'))
            self.lbl_snr_val.setText(self.t('sig_none'))
            self.lbl_clip_val.setText(self.t('sig_none'))
            self.lbl_peaks_val.setText(self.t('sig_none'))
            self.spectrum.update_data(None, None, None)
            self.bar_level.setValue(0); self.lbl_db.setText('—')
            self.bar_level.setStyleSheet(self._bar_css('gray'))
            self.lbl_tip.setText(self.t('tip_none'))
            self._update_holiday_labels()
            self.statusBar().showMessage(self.t('detecting'))

    def _on_status(self, s):
        if s == 'detecting':
            self.statusBar().showMessage(self.t('detecting'))
        elif s == 'running':
            self.statusBar().showMessage(self.t('waiting'))
        elif s == 'stopped':
            self.btn_start.setText(self.t('start'))
            self.btn_start.setEnabled(True)
            self.bar_level.setValue(0); self.lbl_db.setText('—')
            self.bar_level.setStyleSheet(self._bar_css('gray'))
            self.lbl_tip.setText(self.t('tip_none'))
            self.statusBar().showMessage(self.t('stopped'))
            # Limpiar frame cacheado para no mostrar datos obsoletos
            self.last_frame = None
            self.lbl_hoy.setText('—'); self.lbl_man.setText('—')
        elif s.startswith('error:'):
            self.btn_start.setText(self.t('start'))
            self.btn_start.setEnabled(True)
            self.statusBar().showMessage(f'Error: {s[6:]}')

    def _on_tz_offset_changed(self, value):
        self._user_utc    = value
        self._tz_user_set = True
        # Redibujar el reloj si ya tenemos un frame válido
        if self.last_frame and self.last_frame.valid:
            self._apply_frame_to_ui(self.last_frame)

    def _on_carrier(self, fc):
        self._fc = fc
        self.lbl_fc_val.setText(f'{fc:.3f} Hz')
        self.statusBar().showMessage(
            f"{self.t('waiting')}  —  {self.t('carrier')}: {fc:.3f} Hz")

    # ── Frame recibido ────────────────────────────────────────────────────────
    def _on_frame(self, frame):
        from datetime import datetime, timedelta
        ts = datetime.now().strftime('%H:%M:%S')
        self._stat_total += 1

        if not frame.valid:
            self._stat_invalid += 1
            self._update_stats_labels()
            self.log.append(f"[{ts}]  {self.t('invalid')}: {frame.error}")
            self._scroll_log()
            return

        self._stat_valid += 1
        self._stat_bits  += 59   # cada frame válido = 59 bits
        self._last_frame_ts = time.monotonic()
        self._update_stats_labels()
        self.last_frame = frame
        self._apply_frame_to_ui(frame)
        fr_dt   = datetime(frame.year, frame.month, frame.day, frame.hour, frame.minute)
        utc_dt  = fr_dt - timedelta(hours=frame.utc_offset())
        disp_dt = utc_dt + timedelta(hours=self._user_utc)

        synced_now = False
        if self.chk_settime.isChecked():
            try:
                extra = self._user_utc - frame.utc_offset()
                dec.set_system_time(frame, extra_hours=extra)
                synced_now = True
                self.statusBar().showMessage(self.t('set_time_ok'))
            except (PermissionError, RuntimeError):
                self._log_error(self.t('err_admin'))
                self.statusBar().showMessage(self.t('err_admin'))

        sign     = '+' if self._user_utc >= 0 else ''
        tz       = f'UTC{sign}{self._user_utc}'
        fc_tag   = f'  {self._fc:.1f}Hz' if self._fc else ''
        sync_tag = f'  {self.t("log_synced")}' if synced_now else ''
        self.log.append(
            f"[{ts}]  {disp_dt.hour:02d}:{disp_dt.minute:02d} {tz}  "
            f"{disp_dt.day:02d}/{disp_dt.month:02d}/{disp_dt.year}{fc_tag}{sync_tag}"
        )
        self._scroll_log()
        self.tray.setToolTip(
            f"ALS162  {frame.hour:02d}:{frame.minute:02d} {tz}  "
            f"{self.t('DOW')[frame.weekday]}")

    def _apply_frame_to_ui(self, frame):
        from datetime import datetime, timedelta

        # Auto-ajustar spinbox al UTC de Francia en el primer frame (si usuario no lo tocó)
        if not self._tz_user_set:
            self._user_utc = frame.utc_offset()
            self.spin_tz.blockSignals(True)
            self.spin_tz.setValue(self._user_utc)
            self.spin_tz.blockSignals(False)

        # UTC real = hora Francia − utc_offset Francia
        fr_dt  = datetime(frame.year, frame.month, frame.day, frame.hour, frame.minute)
        utc_dt = fr_dt - timedelta(hours=frame.utc_offset())
        # Hora local del usuario = UTC + su offset
        disp_dt = utc_dt + timedelta(hours=self._user_utc)

        sign   = '+' if self._user_utc >= 0 else ''
        tz_str = f'UTC{sign}{self._user_utc}'

        self.lbl_time.setText(f"{disp_dt.hour:02d}:{disp_dt.minute:02d}")
        self.lbl_tz.setText(tz_str)
        dow_idx = disp_dt.weekday() + 1   # Python: 0=Mon → índice 1..7
        self.lbl_date.setText(
            f"{self.t('DOW')[dow_idx]}, "
            f"{disp_dt.day:02d} {self.t('MON')[disp_dt.month]} {disp_dt.year}")
        self._update_holiday_labels(frame)
        anns = []
        if frame.dst_ann:                       anns.append(self.t('dst_change'))
        if frame.leap_pos_ann or frame.leap_neg_ann: anns.append(self.t('leap'))
        self.lbl_ann.setText('   '.join(anns))
        fc_str = f"  —  {self.t('carrier')}: {self._fc:.3f} Hz" if self._fc else ''
        self.statusBar().showMessage(f"{self.t('running')}{fc_str}")

    # ── Estadísticas ──────────────────────────────────────────────────────────
    def _reset_stats(self):
        self._stat_total = self._stat_valid = self._stat_invalid = self._stat_bits = 0
        self._last_frame_ts = None
        self._update_stats_labels()

    def _update_stats_labels(self):
        self.lbl_st_frames_val.setText(str(self._stat_total))
        self.lbl_st_valid_val.setText(str(self._stat_valid))
        self.lbl_st_inv_val.setText(str(self._stat_invalid))
        self.lbl_st_bits_val.setText(str(self._stat_bits))

    def _tick_last_frame(self):
        if self._last_frame_ts is None:
            self.lbl_last_val.setText(self.t('stats_never'))
        else:
            n = int(time.monotonic() - self._last_frame_ts)
            self.lbl_last_val.setText(self.t('stats_ago').format(n=n))

    def _scroll_log(self):
        sb = self.log.verticalScrollBar(); sb.setValue(sb.maximum())

    def _log_error(self, msg):
        """Añade una línea en rojo al historial."""
        from PyQt5.QtGui import QTextCursor, QTextCharFormat, QColor
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor('#cc0000'))
        cursor.insertBlock()
        cursor.setCharFormat(fmt)
        cursor.insertText(msg)
        self.log.setTextCursor(cursor)
        self._scroll_log()


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName('ALS162')
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(QIcon(resource_path("assets/logo.ico")))
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
