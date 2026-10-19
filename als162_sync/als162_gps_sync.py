#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ALS162 GPS Sync — GPS Time & Position Utility
==============================================
Quixote Network  |  v1.0
Lee receptores GPS via puerto COM (NMEA) o gpsd.
Muestra posición, hora GPS, satélites, UTM y sincroniza el SO.
"""

import sys
import os
import math
import time
import threading
import datetime
import ctypes
import urllib.request
from collections import deque, defaultdict

# ── PyQt5 ────────────────────────────────────────────────────────────────────
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QTextEdit, QFrame,
    QSystemTrayIcon, QMenu, QAction, QSizePolicy, QGroupBox,
    QCheckBox, QSpinBox, QScrollArea, QTabWidget, QProgressBar,
    QButtonGroup, QRadioButton,
)
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal, QSettings
from PyQt5.QtGui  import (QFont, QIcon, QPixmap, QColor, QPainter, QPen, QBrush)

try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

try:
    import gpsd
    HAS_GPSD = True
except ImportError:
    HAS_GPSD = False

# pyaudio y als162_decoder (que arrastra numpy+scipy) se importan de forma
# lazy para no ralentizar el arranque. Se cargan la primera vez que se
# necesita el tab ALS162.
HAS_PYAUDIO = False
HAS_DECODER = False
dec = None
_pyaudio = None   # modulo pyaudio cargado lazy

def _load_als_libs():
    """Importa pyaudio y als162_decoder la primera vez que se invoca."""
    global HAS_PYAUDIO, HAS_DECODER, dec, _pyaudio
    if _load_als_libs._done:
        return
    _load_als_libs._done = True
    try:
        import pyaudio as _pa
        _pyaudio = _pa
        HAS_PYAUDIO = True
    except ImportError:
        HAS_PYAUDIO = False
    try:
        import als162_decoder as _d
        dec = _d
        HAS_DECODER = True
    except ImportError:
        HAS_DECODER = False
_load_als_libs._done = False

BAUD_AUTO_LIST = [9600, 4800, 19200, 38400, 57600, 115200]


# ─────────────────────────────────────────────────────────────────────────────
# NOMBRES DE DIAS Y MESES  (independiente del locale del SO)
# ─────────────────────────────────────────────────────────────────────────────
DAYS = {
    'es': ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo'],
    'en': ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'],
}
MONTHS = {
    'es': ['enero','febrero','marzo','abril','mayo','junio',
           'julio','agosto','septiembre','octubre','noviembre','diciembre'],
    'en': ['January','February','March','April','May','June',
           'July','August','September','October','November','December'],
}

def fmt_date(dt, lang):
    """Formatea fecha con día/mes en el idioma indicado."""
    day   = DAYS[lang][dt.weekday()]
    month = MONTHS[lang][dt.month - 1]
    return f'{day} {dt.day:02d} {month} {dt.year}'


# ─────────────────────────────────────────────────────────────────────────────
# UTC OFFSET DEL SISTEMA  (DST-aware)
# ─────────────────────────────────────────────────────────────────────────────
def _get_local_utc_offset() -> int:
    now     = datetime.datetime.now(datetime.timezone.utc).astimezone()
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    delta   = now.replace(tzinfo=None) - utc_now.replace(tzinfo=None)
    return max(-12, min(14, round(delta.total_seconds() / 3600)))


# ─────────────────────────────────────────────────────────────────────────────
# TRADUCCIONES
# ─────────────────────────────────────────────────────────────────────────────
T = {
    'es': {
        'title':          'ALS162 GPS Sync por Quixote Network v1.0',
        'tab_gps':        '🛰  GPS',
        'tab_sats':       '📡  Satélites',
        'tab_map':        '🗺  Mapa',
        'port_lbl':       'Puerto:',
        'baud_lbl':       'Baudios:',
        'refresh':        'Actualizar',
        'connect':        '▶  Conectar',
        'disconnect':     '⏹  Desconectar',
        'status_disc':    'Desconectado',
        'status_conn':    'Conectado',
        'status_fix':     'Fix GPS activo',
        'status_search':  'Buscando satélites…',
        'status_error':   'Error de conexión',
        'status_trying':  'Probando baudios…',
        'fix_none':       'Sin fix',
        'fix_2d':         'Fix 2D',
        'fix_3d':         'Fix 3D',
        'fix_dgps':       'DGPS',
        'fix_rtk':        'RTK',
        'fix_tip': (
            'Tipo de fix GPS:\n'
            '  Sin fix  — sin datos de posición\n'
            '  Fix 2D   — latitud/longitud sin altitud (≥3 satélites)\n'
            '  Fix 3D   — posición completa con altitud (≥4 satélites)\n'
            '  DGPS     — corrección diferencial, mayor precisión\n'
            '  RTK      — corrección en tiempo real, precisión centimétrica'
        ),
        'clock_pc':       'Hora del PC',
        'clock_gps':      'Hora GPS',
        'pos_title':      'Posición GPS',
        'lat_lbl':        'Latitud:',
        'lon_lbl':        'Longitud:',
        'fmt_dms_lbl':    'DMS:',
        'fmt_ddm_lbl':    'DDM:',
        'alt_lbl':        'Altitud:',
        'maiden_lbl':     'Maidenhead:',
        'speed_lbl':      'Velocidad:',
        'heading_lbl':    'Rumbo:',
        'utm_lbl':        'UTM:',
        'tip_lat':        'Latitud en tres formatos:\n  DD = Grados decimales\n  DMS = Grados° Minutos\' Segundos"\n  DDM = Grados° Minutos.decimales\'',
        'tip_lon':        'Longitud en tres formatos:\n  DD = Grados decimales\n  DMS = Grados° Minutos\' Segundos"\n  DDM = Grados° Minutos.decimales\'',
        'tip_fmt_dd':     'Grados Decimales (DD)\nEjemplo: +41.1234567°\nFormato más habitual en GPS y mapas digitales.',
        'tip_fmt_dms':    'Grados, Minutos, Segundos (DMS)\nEjemplo: 41° 07\' 24.4" N\nFormato cartográfico clásico.',
        'tip_fmt_ddm':    'Grados, Minutos Decimales (DDM)\nEjemplo: 41° 07.406\' N\nUsado en náutica y en sentencias NMEA.',
        'tip_alt':        'Altitud sobre el elipsoide WGS84\n(referencia GPS, no nivel del mar)',
        'tip_maiden':     'Localizador Maidenhead (Grid Square)\nSistema de cuadrícula usado en radioafición\nFormato: 2 letras + 2 dígitos + 2 letras (ej: IN80ho)',
        'tip_speed':      'Velocidad sobre el suelo\n  km/h = kilómetros por hora\n  kn   = nudos (1 kn ≈ 1.852 km/h)',
        'tip_heading':    'Rumbo verdadero (no magnético)\n  0° = Norte · 90° = Este · 180° = Sur · 270° = Oeste',
        'tip_utm':        'Coordenadas UTM (Universal Transverse Mercator)\nSistema métrico basado en WGS84\nFormato: ZonaLetra  E Easting  N Northing',
        'dop_title':      'Precisión (DOP)',
        'hdop_lbl':       'HDOP:',
        'vdop_lbl':       'VDOP:',
        'pdop_lbl':       'PDOP:',
        'sats_fix_lbl':   'En fix (total):',
        'sats_gsv_lbl':   'Con señal (GSV):',
        'tip_hdop':       'Dilución de Precisión Horizontal\n  < 1.0  Excelente\n  1 – 2  Bueno\n  2 – 5  Moderado\n  5 – 10 Regular\n  > 10   Muy malo',
        'tip_vdop':       'Dilución de Precisión Vertical\nMide la calidad en altitud\n(normalmente peor que HDOP)',
        'tip_pdop':       'Dilución de Precisión de Posición (3D total)\n  PDOP = √(HDOP² + VDOP²)',
        'tip_sats_fix':   'Total de satélites usados en el cálculo del fix.\nIncluye TODAS las constelaciones (GPS+GLONASS+Galileo+BeiDou).\nFuente: sentencia GGA campo 7.',
        'tip_sats_gsv':   'Satélites con datos de señal recibidos (sentencias GSV).\nPuede ser menor que "En fix" si alguna\nconstelación no envía sentencias GSV.',
        'sync_title':     'Sincronización horaria',
        'tz_lbl':         'Zona UTC:',
        'tz_tip':         'Desplazamiento UTC de tu zona\n  UTC+0 → UK / Portugal\n  UTC+1 → España invierno\n  UTC+2 → España verano\n  UTC-5 → Nueva York\nEl sync ajusta el SO a GPS_UTC + este valor.',
        'settime_chk':    'Sincronizar hora del SO al obtener fix',
        'settime_ok':     '✔ Hora del sistema sincronizada',
        'settime_err':    '⛔ Error al sincronizar: ejecuta como Administrador',
        'autosync_lbl':   'Auto-sync cada:',
        'autosync_min':   'min  (0 = solo al primer fix)',
        'last_sync_lbl':  'Último sync:',
        'last_sync_never':'nunca',
        'sync_log_title': 'Eventos de sincronización',
        'skyplot_title':  'Mapa de cielo',
        'snr_title':      'Señal por satélite (SNR dBHz)',
        'const_title':    'Constelaciones',
        'const_hdr_n':    '#',
        'const_hdr_snr':  'SNR med.',
        'nmea_log_title': 'Log NMEA',
        'no_data':        '—',
        'no_gps_lib':     '⚠ pyserial no instalado — pip install pyserial',
        'connecting':     'Conectando…',
        'lang':           'EN',
        'lang_lbl':       'Idioma:',
        'tray_show':      'Mostrar',
        'tray_hide':      'Ocultar',
        'tray_quit':      'Salir',
        'clear':          'Limpiar',
        'tip_baud':       '"auto" prueba 9600→4800→19200→38400→57600→115200\nhasta que el receptor responde con NMEA válido.',
        'tip_port':       'Puerto COM del receptor GPS.\n"auto" prueba todos los puertos disponibles.',
        'map_center':     '📍 Centrar en GPS',
        'map_zoom_in':    '+',
        'map_zoom_out':   '−',
        'map_no_fix':     'Sin fix GPS — el mapa se centrará automáticamente al obtener posición',
        'map_offline':    '📴 Sin internet — usando tiles en caché',
        'map_loading':    '⬇ Descargando tiles…',
        'map_ready':      '✔ Mapa listo',
        'map_zoom_lbl':   'Zoom:',
        'map_attrib':     '© OpenStreetMap contributors',
        'map_mode_online':  'Mapa Online',
        'map_mode_offline': 'Mapa Offline',
        'map_mode_tip':   'Online  🌐 → descarga tiles de OpenStreetMap (requiere internet)\nOffline 📴 → usa solo tiles guardados en disco (sin internet)',
        'map_no_tiles':   'Sin tiles disponibles\nConecta a internet para cargar el mapa\no desplázate con zoom +/−',
        # ── ALS162 ───────────────────────────────────────────────────────────
        'tab_als':           '📻  ALS162',
        'tab_settings':      '⚙  Ajustes',
        'tab_about':         'ℹ  Acerca de',
        'settings_lang_title': 'Idioma de la interfaz',
        'settings_lang_es':  'Español',
        'settings_lang_en':  'English',
        'about_desc':        (
            'ALS162 GPS Sync sincroniza el reloj del sistema usando señales GPS (NMEA) '
            'y la señal de tiempo de radio ALS162 (compatible con DCF77/MSF). '
            'Soporta múltiples constelaciones GNSS (GPS, GLONASS, Galileo, BeiDou, QZSS) '
            'y muestra la posición en tiempo real sobre un mapa OpenStreetMap.'
        ),
        'about_github':      '🐙  Repositorio GitHub',
        'about_web':         '🌐  Sitio web',
        'about_support':     'Si te gusta este proyecto:',
        'als_clock_pc':      'Hora del PC',
        'als_clock_als':     'Hora ALS162',
        'als_device':        'Audio:',
        'als_start':         '▶  Iniciar',
        'als_stop':          '⏹  Detener',
        'als_set_time_chk':  'Sincronizar hora del SO con ALS162',
        'als_set_time_ok':   '✔  Hora del sistema ajustada (ALS162)',
        'als_detecting':     'Midiendo portadora (5 s)…',
        'als_waiting':       'Esperando primer frame (~70 s)…',
        'als_running':       'Decodificando ALS162',
        'als_stopped':       'ALS162 detenido',
        'als_carrier':       'Portadora',
        'als_log_title':     'Historial de frames',
        'als_today':         'Hoy',
        'als_hol_lbl':       'Festivo próximo',
        'als_holiday':       '🎉 Festivo',
        'als_no_holiday':    '✓ No festivo',
        'als_hol_yes':       '⚠ Anunciado esta semana',
        'als_hol_no':        '✓ No anunciado',
        'als_dst':           '⚠ Cambio de hora próximo',
        'als_leap':          '⚠ Leap second anunciado',
        'als_invalid':       'Frame inválido',
        'als_sig_title':     'Señal / Ajuste SDR',
        'als_sig_level':     'Nivel:',
        'als_sig_carrier':   'Portadora:',
        'als_sig_snr':       'SNR:',
        'als_sig_clip':      'Clipping:',
        'als_sig_peaks':     'Top picos:',
        'als_sig_none':      '—',
        'als_tip_low':       '🔴  Señal débil — sube la ganancia RF/IF del SDR o el volumen',
        'als_tip_ok':        '🟢  Nivel correcto — la decodificación debería funcionar bien',
        'als_tip_high':      '🟡  Señal saturada — baja la ganancia para evitar distorsión',
        'als_tip_snr_pri':   '🟡  Nivel en rango pero SNR bajo — revisa modo USB del SDR o antena',
        'als_tip_none':      'Inicia el decodificador para ver el nivel de señal',
        'als_tip_snr_w':     ' · SNR bajo (<15 dB): revisa modo USB del SDR o antena',
        'als_tip_clip_w':    ' · Saturación digital detectada: reduce la ganancia',
        'als_log_synced':    '✔ PC Sync (ALS162)',
        'als_err_admin':     '⛔ Error al ajustar hora: ejecuta como Administrador',
        'als_tz_lbl':        'Zona UTC (ALS162):',
        'als_tz_tip':        'Desplazamiento UTC para la hora ALS162\n(UTC+1 España invierno · UTC+2 verano)',
        'als_stats_title':   'Estadísticas de decodificación',
        'als_stats_frames':  'Frames:',
        'als_stats_valid':   'Válidos:',
        'als_stats_invalid': 'Inválidos:',
        'als_stats_bits':    'Bits:',
        'als_stats_last':    'Último frame:',
        'als_stats_never':   'ninguno aún',
        'als_stats_ago':     'hace {n} s',
        'als_no_lib':        '⚠  pyaudio no instalado\n\npip install pyaudio',
        'als_no_decoder':    '⚠  als162_decoder.py no encontrado\n\nColoca el archivo en la misma carpeta que la app',
        'als_DOW':           ['','Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo'],
        'als_MON':           ['','Enero','Febrero','Marzo','Abril','Mayo','Junio',
                              'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'],
    },
    'en': {
        'title':          'ALS162 GPS Sync by Quixote Network v1.0',
        'tab_gps':        '🛰  GPS',
        'tab_sats':       '📡  Satellites',
        'tab_map':        '🗺  Map',
        'port_lbl':       'Port:',
        'baud_lbl':       'Baud:',
        'refresh':        'Refresh',
        'connect':        '▶  Connect',
        'disconnect':     '⏹  Disconnect',
        'status_disc':    'Disconnected',
        'status_conn':    'Connected',
        'status_fix':     'GPS fix active',
        'status_search':  'Searching satellites…',
        'status_error':   'Connection error',
        'status_trying':  'Trying baud rates…',
        'fix_none':       'No fix',
        'fix_2d':         '2D Fix',
        'fix_3d':         '3D Fix',
        'fix_dgps':       'DGPS',
        'fix_rtk':        'RTK',
        'fix_tip': (
            'GPS fix type:\n'
            '  No fix  — no position data\n'
            '  2D Fix  — lat/lon without altitude (≥3 satellites)\n'
            '  3D Fix  — full position with altitude (≥4 satellites)\n'
            '  DGPS    — differential correction, higher accuracy\n'
            '  RTK     — real-time kinematic, centimeter accuracy'
        ),
        'clock_pc':       'PC Time',
        'clock_gps':      'GPS Time',
        'pos_title':      'GPS Position',
        'lat_lbl':        'Latitude:',
        'lon_lbl':        'Longitude:',
        'fmt_dms_lbl':    'DMS:',
        'fmt_ddm_lbl':    'DDM:',
        'alt_lbl':        'Altitude:',
        'maiden_lbl':     'Maidenhead:',
        'speed_lbl':      'Speed:',
        'heading_lbl':    'Heading:',
        'utm_lbl':        'UTM:',
        'tip_lat':        'Latitude in three formats:\n  DD  = Decimal Degrees\n  DMS = Degrees° Minutes\' Seconds"\n  DDM = Degrees° Minutes.decimals\'',
        'tip_lon':        'Longitude in three formats:\n  DD  = Decimal Degrees\n  DMS = Degrees° Minutes\' Seconds"\n  DDM = Degrees° Minutes.decimals\'',
        'tip_fmt_dd':     'Decimal Degrees (DD)\nExample: +41.1234567°\nMost common format in GPS and digital maps.',
        'tip_fmt_dms':    'Degrees, Minutes, Seconds (DMS)\nExample: 41° 07\' 24.4" N\nClassic cartographic format.',
        'tip_fmt_ddm':    'Degrees, Decimal Minutes (DDM)\nExample: 41° 07.406\' N\nUsed in nautical navigation and NMEA sentences.',
        'tip_alt':        'Altitude above WGS84 ellipsoid\n(GPS reference, not mean sea level)',
        'tip_maiden':     'Maidenhead Grid Locator\nGrid square system used in amateur radio\nFormat: 2 letters + 2 digits + 2 letters (e.g. IN80ho)',
        'tip_speed':      'Speed over ground\n  km/h = kilometres per hour\n  kn   = knots (1 kn ≈ 1.852 km/h)',
        'tip_heading':    'True heading (not magnetic)\n  0° = North · 90° = East · 180° = South · 270° = West',
        'tip_utm':        'UTM Coordinates (Universal Transverse Mercator)\nMetric system based on WGS84\nFormat: ZoneLetter  E Easting  N Northing',
        'dop_title':      'Accuracy (DOP)',
        'hdop_lbl':       'HDOP:',
        'vdop_lbl':       'VDOP:',
        'pdop_lbl':       'PDOP:',
        'sats_fix_lbl':   'In fix (total):',
        'sats_gsv_lbl':   'With signal (GSV):',
        'tip_hdop':       'Horizontal Dilution of Precision\n  < 1.0  Excellent\n  1 – 2  Good\n  2 – 5  Moderate\n  5 – 10 Fair\n  > 10   Poor',
        'tip_vdop':       'Vertical Dilution of Precision\nMeasures quality in the altitude dimension\n(usually worse than HDOP)',
        'tip_pdop':       'Position Dilution of Precision (3D total)\n  PDOP = √(HDOP² + VDOP²)',
        'tip_sats_fix':   'Total satellites used in the fix calculation.\nIncludes ALL constellations (GPS+GLONASS+Galileo+BeiDou).\nSource: NMEA GGA sentence field 7.',
        'tip_sats_gsv':   'Satellites with signal data received (GSV sentences).\nMay be less than "In fix" if some\nconstellation does not send GSV sentences.',
        'sync_title':     'Time Synchronization',
        'tz_lbl':         'UTC zone:',
        'tz_tip':         'Your UTC time offset\n  UTC+0 → UK / Portugal\n  UTC+1 → Spain winter\n  UTC+2 → Spain summer\n  UTC-5 → New York\nSync sets OS time to GPS_UTC + this value.',
        'settime_chk':    'Sync OS time on GPS fix',
        'settime_ok':     '✔ System time synchronized',
        'settime_err':    '⛔ Sync failed: run as Administrator',
        'autosync_lbl':   'Auto-sync every:',
        'autosync_min':   'min  (0 = first fix only)',
        'last_sync_lbl':  'Last sync:',
        'last_sync_never':'never',
        'sync_log_title': 'Sync events',
        'skyplot_title':  'Sky Plot',
        'snr_title':      'Satellite Signal (SNR dBHz)',
        'const_title':    'Constellations',
        'const_hdr_n':    '#',
        'const_hdr_snr':  'Avg SNR',
        'nmea_log_title': 'NMEA Log',
        'no_data':        '—',
        'no_gps_lib':     '⚠ pyserial not installed — pip install pyserial',
        'connecting':     'Connecting…',
        'lang':           'ES',
        'lang_lbl':       'Language:',
        'tray_show':      'Show',
        'tray_hide':      'Hide',
        'tray_quit':      'Quit',
        'clear':          'Clear',
        'tip_baud':       '"auto" tries 9600→4800→19200→38400→57600→115200\nuntil the receiver responds with valid NMEA.',
        'tip_port':       'GPS receiver COM port.\n"auto" tries all available ports.',
        'map_center':     '📍 Center on GPS',
        'map_zoom_in':    '+',
        'map_zoom_out':   '−',
        'map_no_fix':     'No GPS fix — map will center automatically when position is available',
        'map_offline':    '📴 No internet — using cached tiles',
        'map_loading':    '⬇ Downloading tiles…',
        'map_ready':      '✔ Map ready',
        'map_zoom_lbl':   'Zoom:',
        'map_attrib':     '© OpenStreetMap contributors',
        'map_mode_online':  'Map Online',
        'map_mode_offline': 'Map Offline',
        'map_mode_tip':   'Online  🌐 → downloads tiles from OpenStreetMap (requires internet)\nOffline 📴 → uses only cached tiles on disk (no internet)',
        'map_no_tiles':   'No tiles available\nConnect to the internet to load the map\nor pan/zoom with +/−',
        # ── ALS162 ───────────────────────────────────────────────────────────
        'tab_als':           '📻  ALS162',
        'tab_settings':      '⚙  Settings',
        'tab_about':         'ℹ  About',
        'settings_lang_title': 'Interface language',
        'settings_lang_es':  'Español',
        'settings_lang_en':  'English',
        'about_desc':        (
            'ALS162 GPS Sync synchronises the system clock using GPS (NMEA) signals '
            'and the ALS162 radio time signal (DCF77/MSF compatible). '
            'Supports multiple GNSS constellations (GPS, GLONASS, Galileo, BeiDou, QZSS) '
            'and displays your position in real time on an OpenStreetMap map.'
        ),
        'about_github':      '🐙  GitHub Repository',
        'about_web':         '🌐  Website',
        'about_support':     'If you like this project:',
        'als_clock_pc':      'PC Time',
        'als_clock_als':     'ALS162 Time',
        'als_device':        'Audio:',
        'als_start':         '▶  Start',
        'als_stop':          '⏹  Stop',
        'als_set_time_chk':  'Sync OS time with ALS162',
        'als_set_time_ok':   '✔  System time set (ALS162)',
        'als_detecting':     'Measuring carrier (5 s)…',
        'als_waiting':       'Waiting for first frame (~70 s)…',
        'als_running':       'Decoding ALS162',
        'als_stopped':       'ALS162 stopped',
        'als_carrier':       'Carrier',
        'als_log_title':     'Frame history',
        'als_today':         'Today',
        'als_hol_lbl':       'Upcoming holiday',
        'als_holiday':       '🎉 Holiday',
        'als_no_holiday':    '✓ Not a holiday',
        'als_hol_yes':       '⚠ Announced this week',
        'als_hol_no':        '✓ Not announced',
        'als_dst':           '⚠ DST change upcoming',
        'als_leap':          '⚠ Leap second announced',
        'als_invalid':       'Invalid frame',
        'als_sig_title':     'Signal / SDR Setup',
        'als_sig_level':     'Level:',
        'als_sig_carrier':   'Carrier:',
        'als_sig_snr':       'SNR:',
        'als_sig_clip':      'Clipping:',
        'als_sig_peaks':     'Top peaks:',
        'als_sig_none':      '—',
        'als_tip_low':       '🔴  Signal too weak — increase SDR RF/IF gain or line volume',
        'als_tip_ok':        '🟢  Level OK — decoding should work correctly',
        'als_tip_high':      '🟡  Signal clipping — reduce gain to avoid phase distortion',
        'als_tip_snr_pri':   '🟡  Level in range but SNR too low — check SDR USB mode, RF gain or antenna',
        'als_tip_none':      'Start the decoder to see signal level',
        'als_tip_snr_w':     ' · Low SNR (<15 dB): check SDR USB mode or antenna',
        'als_tip_clip_w':    ' · Digital clipping detected: reduce gain',
        'als_log_synced':    '✔ PC Sync (ALS162)',
        'als_err_admin':     '⛔ Time sync failed: run as Administrator',
        'als_tz_lbl':        'UTC zone (ALS162):',
        'als_tz_tip':        'Your UTC offset for ALS162 time\n(UTC+1 Spain winter · UTC+2 summer)',
        'als_stats_title':   'Decode Statistics',
        'als_stats_frames':  'Frames:',
        'als_stats_valid':   'Valid:',
        'als_stats_invalid': 'Invalid:',
        'als_stats_bits':    'Bits:',
        'als_stats_last':    'Last frame:',
        'als_stats_never':   'none yet',
        'als_stats_ago':     '{n} s ago',
        'als_no_lib':        '⚠  pyaudio not installed\n\npip install pyaudio',
        'als_no_decoder':    '⚠  als162_decoder.py not found\n\nPlace the file in the same folder as the app',
        'als_DOW':           ['','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'],
        'als_MON':           ['','January','February','March','April','May','June',
                              'July','August','September','October','November','December'],
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# CONVERSIONES GEOGRAFICAS
# ─────────────────────────────────────────────────────────────────────────────

def dd_to_dms(deg, is_lat):
    neg = deg < 0; deg = abs(deg)
    d = int(deg); m = int((deg-d)*60); s = (deg-d-m/60)*3600
    h = ('S' if neg else 'N') if is_lat else ('W' if neg else 'E')
    return f"{d:03d}°{m:02d}'{s:06.3f}\" {h}"

def dd_to_ddm(deg, is_lat):
    neg = deg < 0; deg = abs(deg)
    d = int(deg); m = (deg-d)*60
    h = ('S' if neg else 'N') if is_lat else ('W' if neg else 'E')
    return f"{d:03d}°{m:09.6f}' {h}"

def dd_to_utm(lat, lon):
    a=6378137.0; f=1/298.257223563; b=a*(1-f); e2=1-(b/a)**2; k0=0.9996
    lr=math.radians(lat); lo=math.radians(lon)
    zn=int((lon+180)/6)+1
    if 56<=lat<64 and 3<=lon<12: zn=32
    if 72<=lat<84:
        if   0<=lon< 9: zn=31
        elif 9<=lon<21: zn=33
        elif 21<=lon<33: zn=35
        elif 33<=lon<42: zn=37
    lor=math.radians((zn-1)*6-180+3)
    N=a/math.sqrt(1-e2*math.sin(lr)**2); T=math.tan(lr)**2
    C=(e2/(1-e2))*math.cos(lr)**2; A=math.cos(lr)*(lo-lor)
    e4=e2**2; e6=e2**3
    M=a*((1-e2/4-3*e4/64-5*e6/256)*lr-(3*e2/8+3*e4/32+45*e6/1024)*math.sin(2*lr)
         +(15*e4/256+45*e6/1024)*math.sin(4*lr)-(35*e6/3072)*math.sin(6*lr))
    E=k0*N*(A+(1-T+C)*A**3/6+(5-18*T+T**2+72*C-58*e2/(1-e2))*A**5/120)+500000
    Nv=k0*(M+N*math.tan(lr)*(A**2/2+(5-T+9*C+4*C**2)*A**4/24+(61-58*T+T**2+600*C-330*e2/(1-e2))*A**6/720))
    if lat<0: Nv+=10_000_000
    letters='CDEFGHJKLMNPQRSTUVWXX'
    zl=letters[int((lat+80)/8)] if -80<=lat<=84 else '?'
    return zn,zl,E,Nv

def format_utm(lat,lon):
    zn,zl,e,n=dd_to_utm(lat,lon)
    return f"{zn}{zl}  E {e:,.0f}  N {n:,.0f}"

def maidenhead(lat, lon):
    """Localizador Maidenhead (Grid Square) de 6 caracteres."""
    lon2 = lon + 180.0
    lat2 = lat + 90.0
    f_lon = int(lon2 / 20);   f_lat = int(lat2 / 10)
    s_lon = int((lon2 % 20) / 2); s_lat = int(lat2 % 10)
    t_lon = int(((lon2 % 20) % 2) * 12)
    t_lat = int(((lat2 % 10) % 1) * 24)
    return (chr(ord('A') + f_lon) + chr(ord('A') + f_lat) +
            str(s_lon) + str(s_lat) +
            chr(ord('a') + t_lon) + chr(ord('a') + t_lat))


# ─────────────────────────────────────────────────────────────────────────────
# PARSER NMEA
# ─────────────────────────────────────────────────────────────────────────────

def _nmea_ok(s):
    try:
        if '*' not in s: return True
        body,cs=s[1:].split('*',1); calc=0
        for c in body: calc^=ord(c)
        return calc==int(cs[:2],16)
    except: return False

def _plat(v,h):
    if not v: return None
    try:
        d=int(float(v)/100); m=float(v)-d*100; deg=d+m/60
        return -deg if h=='S' else deg
    except: return None

def _plon(v,h):
    if not v: return None
    try:
        d=int(float(v)/100); m=float(v)-d*100; deg=d+m/60
        return -deg if h=='W' else deg
    except: return None

class GpsState:
    def __init__(self): self.reset()
    def reset(self):
        self.lat=self.lon=self.alt_m=self.speed_kmh=self.speed_kn=self.heading_true=None
        self.fix_quality=0; self.fix_type=1; self.hdop=self.vdop=self.pdop=None
        self.sats_used=0; self.utc_time=self.utc_date=None
        self.satellites={}; self.timestamp=None

class NmeaParser:
    CONST={'GP':'GPS','GN':'GNSS','GL':'GLONASS','GA':'Galileo','GB':'BeiDou','BD':'BeiDou','GQ':'QZSS'}
    def __init__(self): self.state=GpsState(); self._gsv={}
    def feed(self,line):
        line=line.strip()
        if not line.startswith('$') or not _nmea_ok(line): return
        body=line[1:].split('*')[0]; f=body.split(',')
        if not f: return
        tid=f[0]; talker=tid[:2]; sent=tid[2:]; const=self.CONST.get(talker,talker)
        try:
            if   sent=='GGA': self._gga(f,const)
            elif sent=='RMC': self._rmc(f)
            elif sent=='VTG': self._vtg(f)
            elif sent=='GSA': self._gsa(f)
            elif sent=='GSV': self._gsv_parse(f,talker,const)
        except: pass
        self.state.timestamp=time.monotonic()

    def _gga(self,f,c):
        s=self.state
        if len(f)<10: return
        t=f[1]
        if len(t)>=6:
            try: s.utc_time=datetime.time(int(t[0:2]),int(t[2:4]),int(t[4:6]))
            except: pass
        lat=_plat(f[2],f[3]); lon=_plon(f[4],f[5])
        if lat is not None: s.lat=lat
        if lon is not None: s.lon=lon
        try: s.fix_quality=int(f[6])
        except: pass
        try: s.sats_used=int(f[7])
        except: pass
        try: s.hdop=float(f[8])
        except: pass
        try: s.alt_m=float(f[9])
        except: pass

    def _rmc(self,f):
        s=self.state
        if len(f)<10: return
        t=f[1]
        if len(t)>=6:
            try: s.utc_time=datetime.time(int(t[0:2]),int(t[2:4]),int(t[4:6]))
            except: pass
        lat=_plat(f[3],f[4]); lon=_plon(f[5],f[6])
        if lat is not None: s.lat=lat
        if lon is not None: s.lon=lon
        try: kn=float(f[7]); s.speed_kn=kn; s.speed_kmh=kn*1.852
        except: pass
        try: s.heading_true=float(f[8])
        except: pass
        d=f[9]
        if len(d)==6:
            try: s.utc_date=datetime.date(2000+int(d[4:6]),int(d[2:4]),int(d[0:2]))
            except: pass

    def _vtg(self,f):
        s=self.state
        try: s.heading_true=float(f[1]) if f[1] else s.heading_true
        except: pass
        try: s.speed_kn=float(f[5]) if f[5] else s.speed_kn
        except: pass
        try: s.speed_kmh=float(f[7])
        except: pass

    def _gsa(self,f):
        s=self.state
        try: s.fix_type=int(f[2])
        except: pass
        # Indices fijos: PDOP=15, HDOP=16, VDOP=17
        # Funciona con GSA estándar (18 campos) y NMEA 4.10+ (19 campos con systemID al final)
        # Evita el bug de indices negativos que cogen el systemID en lugar del VDOP
        if len(f) >= 18:
            try: s.pdop = float(f[15]) if f[15] else None
            except: pass
            try: s.hdop = float(f[16]) if f[16] else None
            except: pass
            try: s.vdop = float(f[17]) if f[17] else None
            except: pass

    def _gsv_parse(self,f,talker,const):
        s=self.state
        if len(f)<4: return
        try: mn=int(f[2]); tm=int(f[1])
        except: return
        if mn==1: self._gsv[talker]=[]
        i=4
        while i+3<=len(f):
            try:
                prn=int(f[i]); el=float(f[i+1]) if f[i+1] else 0.0
                az=float(f[i+2]) if f[i+2] else 0.0
                sr=f[i+3].split('*')[0]; snr=float(sr) if sr else 0.0
                self._gsv.setdefault(talker,[]).append({'prn':prn,'el':el,'az':az,'snr':snr,'constellation':const})
            except: pass
            i+=4
        if mn==tm:
            for sat in self._gsv.get(talker,[]):
                s.satellites[f"{talker}{sat['prn']:02d}"]=sat


# ─────────────────────────────────────────────────────────────────────────────
# HILO GPS  (auto-baud con buffer de tiempo)
# ─────────────────────────────────────────────────────────────────────────────

class GpsThread(QThread):
    data_signal   = pyqtSignal(object)
    status_signal = pyqtSignal(str)
    nmea_signal   = pyqtSignal(str)

    def __init__(self, port='auto', baud='auto'):
        super().__init__()
        self.port=port; self.baud=baud; self._stop=threading.Event()

    def stop(self): self._stop.set()

    @staticmethod
    def _probe(port, baud, window=1.5):
        try:
            ser=serial.Serial(port, baud, timeout=0.05)
            ser.reset_input_buffer()
            buf=b''; deadline=time.monotonic()+window
            while time.monotonic()<deadline:
                chunk=ser.read(256)
                if chunk:
                    buf+=chunk
                    while b'\n' in buf:
                        raw,buf=buf.split(b'\n',1)
                        line=raw.decode('ascii',errors='replace').strip()
                        if line.startswith('$') and len(line)>=6 and _nmea_ok(line):
                            return ser
                else: time.sleep(0.02)
            ser.close()
        except: pass
        return None

    def run(self):
        self._stop.clear()
        if HAS_SERIAL:
            ports=([self.port] if self.port and self.port!='auto'
                   else [p.device for p in serial.tools.list_ports.comports()])
            bauds=(BAUD_AUTO_LIST if self.baud=='auto' else [int(self.baud)])
            for port in ports:
                if self._stop.is_set(): break
                for baud in bauds:
                    if self._stop.is_set(): break
                    self.status_signal.emit(f'trying:{port}@{baud}' if self.baud=='auto' else 'connecting')
                    ser=self._probe(port, baud, 1.5 if self.baud=='auto' else 2.0)
                    if ser:
                        self.status_signal.emit('connected')
                        self._run_serial(ser, NmeaParser())
                        try: ser.close()
                        except: pass
                        self.status_signal.emit('disconnected')
                        return
        if HAS_GPSD and not self._stop.is_set():
            try:
                gpsd.connect(); self.status_signal.emit('connected')
                self._run_gpsd(NmeaParser()); self.status_signal.emit('disconnected'); return
            except Exception as e:
                self.status_signal.emit(f'error:{e}'); return
        if not self._stop.is_set():
            msg='No GPS device found' if HAS_SERIAL else 'pyserial not installed'
            self.status_signal.emit(f'error:{msg}')
        self.status_signal.emit('disconnected')

    def _run_serial(self, ser, parser):
        self.status_signal.emit('searching')
        last_emit=0.0
        while not self._stop.is_set():
            try:
                raw=ser.readline()
                line=raw.decode('ascii',errors='replace').strip()
                if line.startswith('$'):
                    self.nmea_signal.emit(line); parser.feed(line)
                    now=time.monotonic()
                    if now-last_emit>=0.25:
                        last_emit=now; snap=self._snap(parser.state)
                        self.data_signal.emit(snap)
                        self.status_signal.emit('fix' if snap.fix_quality>0 and snap.lat is not None else 'searching')
            except: break

    def _run_gpsd(self, parser):
        self.status_signal.emit('searching'); last_emit=0.0
        while not self._stop.is_set():
            try:
                pkt=gpsd.get_current(); s=parser.state
                s.lat=pkt.lat; s.lon=pkt.lon; s.alt_m=getattr(pkt,'alt',None)
                s.fix_type=getattr(pkt,'mode',1); s.fix_quality=1 if s.fix_type>=2 else 0
                s.sats_used=getattr(pkt,'sats_valid',0)
                _u=datetime.datetime.now(datetime.timezone.utc)
                s.utc_time=_u.time().replace(tzinfo=None); s.utc_date=_u.date()
                s.timestamp=time.monotonic()
                now=time.monotonic()
                if now-last_emit>=1.0:
                    last_emit=now; snap=self._snap(s); self.data_signal.emit(snap)
                    self.status_signal.emit('fix' if snap.fix_quality>0 else 'searching')
                time.sleep(0.5)
            except: time.sleep(1.0)

    @staticmethod
    def _snap(state):
        snap=GpsState(); snap.__dict__.update(state.__dict__); snap.satellites=dict(state.satellites); return snap


# ─────────────────────────────────────────────────────────────────────────────
# COLORES DE CONSTELACION
# ─────────────────────────────────────────────────────────────────────────────
CONST_COLORS = {
    'GPS':     '#1565C0',
    'GLONASS': '#C62828',
    'Galileo': '#2E7D32',
    'BeiDou':  '#E65100',
    'GNSS':    '#6A1B9A',
    'QZSS':    '#F9A825',
}


# ─────────────────────────────────────────────────────────────────────────────
# WIDGET SKYPLOT
# ─────────────────────────────────────────────────────────────────────────────
class SkyPlotWidget(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent); self.setMinimumSize(220,220); self._sats={}
    def update_satellites(self,sats): self._sats=dict(sats); self.update()
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        w,h=self.width(),self.height(); cx,cy=w//2,h//2; r=min(cx,cy)-20
        p.fillRect(0,0,w,h,QColor('#f0f4f8'))
        p.setPen(QPen(QColor('#cccccc'),1))
        for frac in [1.0,0.667,0.333]: ri=int(r*frac); p.drawEllipse(cx-ri,cy-ri,ri*2,ri*2)
        p.setPen(QPen(QColor('#cccccc'),1,Qt.DashLine))
        p.drawLine(cx-r,cy,cx+r,cy); p.drawLine(cx,cy-r,cx,cy+r)
        p.setPen(QColor('#555555')); p.setFont(QFont('Arial',8,QFont.Bold))
        p.drawText(cx-4,cy-r-4,'N'); p.drawText(cx-4,cy+r+14,'S')
        p.drawText(cx+r+4,cy+4,'E'); p.drawText(cx-r-14,cy+4,'W')
        p.setFont(QFont('Arial',7)); p.setPen(QColor('#999999'))
        for el,frac in [(0,1.0),(30,0.667),(60,0.333)]:
            ri=int(r*frac); p.drawText(cx+2,cy-ri+10,f'{el}°')
        for key,sat in self._sats.items():
            el=sat.get('el',0); az=sat.get('az',0); snr=sat.get('snr',0)
            const=sat.get('constellation','GPS'); color=QColor(CONST_COLORS.get(const,'#888888'))
            az_r=math.radians(az); ef=1.0-(el/90.0)
            sx=cx+int(r*ef*math.sin(az_r)); sy=cy-int(r*ef*math.cos(az_r))
            dr=max(4,min(10,int(snr/8))); color.setAlpha(255 if snr>0 else 130)
            p.setBrush(QBrush(color)); p.setPen(QPen(color.darker(160),1) if snr>0 else QPen(QColor('#aaaaaa'),1))
            p.drawEllipse(sx-dr,sy-dr,dr*2,dr*2)
            p.setPen(QColor('#333333')); p.setFont(QFont('Arial',6))
            p.drawText(sx+dr+1,sy+4,str(sat.get('prn','')))
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# WIDGET GRAFICA DOP
# ─────────────────────────────────────────────────────────────────────────────
class DopGraphWidget(QWidget):
    MAX_PTS=120
    def __init__(self,parent=None):
        super().__init__(parent); self.setFixedHeight(80); self.setMinimumWidth(200)
        self._hdop=deque(maxlen=self.MAX_PTS); self._nsats=deque(maxlen=self.MAX_PTS)
    def push(self,hdop,nsats):
        self._hdop.append(hdop if hdop is not None else float('nan'))
        self._nsats.append(nsats if nsats is not None else 0); self.update()
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        w,h=self.width(),self.height(); pad=4
        p.fillRect(0,0,w,h,QColor('#f9f9f9'))
        p.setPen(QPen(QColor('#eeeeee'),1))
        for yf in [0.25,0.5,0.75]: y=int(pad+(h-2*pad)*yf); p.drawLine(pad,y,w-pad,y)
        n=len(self._hdop)
        if n<2:
            p.setPen(QColor('#aaaaaa')); p.setFont(QFont('Arial',8))
            p.drawText(0,0,w,h,Qt.AlignCenter,'HDOP / Sats'); p.end(); return
        def xi(i): return pad+int((i/(self.MAX_PTS-1))*(w-2*pad))
        p.setPen(QPen(QColor('#1565C0'),2)); prev=None
        for i,v in enumerate(self._hdop):
            xp=xi(i+self.MAX_PTS-n)
            if not math.isnan(v):
                yp=h-pad-int(min(v,10)/10*(h-2*pad))
                if prev: p.drawLine(prev[0],prev[1],xp,yp)
                prev=(xp,yp)
            else: prev=None
        p.setPen(QPen(QColor('#2E7D32'),1,Qt.DashLine)); prev=None
        for i,v in enumerate(self._nsats):
            xp=xi(i+self.MAX_PTS-n); yp=h-pad-int(min(v,20)/20*(h-2*pad))
            if prev: p.drawLine(prev[0],prev[1],xp,yp)
            prev=(xp,yp)
        p.setFont(QFont('Arial',7))
        p.setPen(QColor('#1565C0')); p.drawText(pad+2,13,'HDOP')
        p.setPen(QColor('#2E7D32')); p.drawText(pad+38,13,'Sats')
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# MAPA OSM CON TILES CACHEADOS
# ─────────────────────────────────────────────────────────────────────────────
TILE_SZ  = 256
TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
TILE_DIR = os.path.join(os.path.expanduser('~'), '.als162gps', 'tiles')

def _resource_path(rel):
    """Ruta a un recurso dentro del ejecutable PyInstaller o del directorio del script."""
    try:
        base = sys._MEIPASS
    except AttributeError:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, rel)

# Tiles bundleados (zoom 0-5) incluidos en la instalacion/ejecutable
BUNDLED_TILE_DIR = _resource_path(os.path.join('assets', 'tiles'))

def _tile_xy(lat, lon, zoom):
    """Devuelve coordenada de tile (fraccionaria) para lat/lon."""
    n   = 2.0 ** zoom
    tx  = (lon + 180.0) / 360.0 * n
    lr  = math.radians(max(-85.05, min(85.05, lat)))
    ty  = (1.0 - math.log(math.tan(lr) + 1.0/math.cos(lr)) / math.pi) / 2.0 * n
    return tx, ty

class TileLoader(QThread):
    ready = pyqtSignal(int, int, int, bytes)
    def __init__(self, z, x, y):
        super().__init__(); self.z=z; self.x=x; self.y=y
    def run(self):
        try:
            url=TILE_URL.format(z=self.z, x=self.x, y=self.y)
            req=urllib.request.Request(url, headers={'User-Agent':'ALS162GPSSync/0.3'})
            with urllib.request.urlopen(req, timeout=8) as r:
                data=r.read()
            self.ready.emit(self.z, self.x, self.y, data)
        except: pass

class NetworkChecker(QThread):
    """Comprueba si hay acceso a tiles OSM (no bloquea el hilo UI)."""
    result = pyqtSignal(bool)
    def run(self):
        try:
            req = urllib.request.Request(
                'https://tile.openstreetmap.org/0/0/0.png',
                headers={'User-Agent': 'ALS162GPSSync/0.3'})
            urllib.request.urlopen(req, timeout=4)
            self.result.emit(True)
        except Exception:
            self.result.emit(False)


class MapWidget(QWidget):
    status_changed = pyqtSignal(str)   # 'online' | 'offline'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self._zoom    = 3
        self._cx      = 0.0    # center lon
        self._cy      = 20.0   # center lat
        self._gps_lat = None
        self._gps_lon = None
        self._drag    = None   # (QPoint, cx0, cy0)
        self._tiles   = {}     # (z,x,y) -> QPixmap
        self._loading = set()
        self._loaders = {}     # (z,x,y) -> TileLoader  ← evita GC prematuro
        self._online  = True   # True = descarga tiles; False = solo caché
        self._net_checker = None
        os.makedirs(TILE_DIR, exist_ok=True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self._check_network()  # comprobacion asincrona de internet al arrancar

    def set_position(self, lat, lon):
        first = (self._gps_lat is None)
        self._gps_lat = lat; self._gps_lon = lon
        if first:
            self._cx = lon; self._cy = lat
        self.update()

    def center_on_gps(self):
        if self._gps_lat is not None:
            self._cx = self._gps_lon; self._cy = self._gps_lat; self.update()

    def zoom_in(self):
        self._zoom = min(18, self._zoom+1); self.update()
    def zoom_out(self):
        self._zoom = max(0, self._zoom-1); self.update()
    def get_zoom(self): return self._zoom

    def wheelEvent(self, e):
        if e.angleDelta().y()>0: self.zoom_in()
        else: self.zoom_out()

    def mousePressEvent(self, e):
        if e.button()==Qt.LeftButton:
            self._drag=(e.pos(), self._cx, self._cy)

    def mouseMoveEvent(self, e):
        if self._drag:
            dp=e.pos()-self._drag[0]; n=2.0**self._zoom
            self._cx=self._drag[1]-dp.x()/TILE_SZ/n*360.0
            ctx,cty=_tile_xy(self._drag[2], self._drag[1], self._zoom)
            nty=max(0.001, min(n-0.001, cty-dp.y()/TILE_SZ))
            lr=math.atan(math.sinh(math.pi*(1-2*nty/n)))
            self._cy=math.degrees(lr); self.update()

    def mouseReleaseEvent(self, e):
        if e.button()==Qt.LeftButton: self._drag=None

    # ── ONLINE / OFFLINE ──────────────────────────────────────────────────────
    def _check_network(self):
        """Lanza comprobacion de internet en segundo plano."""
        self._net_checker = NetworkChecker()
        self._net_checker.result.connect(self._on_network_check)
        self._net_checker.start()

    def _on_network_check(self, ok):
        self._online = ok
        self.status_changed.emit('online' if ok else 'offline')
        self.update()

    def set_online(self, v):
        """Cambia el modo manualmente."""
        self._online = bool(v)
        self.status_changed.emit('online' if v else 'offline')
        self.update()

    def is_online(self): return self._online

    def _get_tile(self, z, x, y):
        key=(z,x,y)
        # 1. Memoria
        if key in self._tiles: return self._tiles[key]
        # 2. Cache del usuario (~/.als162gps/tiles/)
        path=os.path.join(TILE_DIR, str(z), str(x), f'{y}.png')
        if os.path.isfile(path):
            pm=QPixmap(path)
            if not pm.isNull(): self._tiles[key]=pm; return pm
        # 3. Tiles bundleados (assets/tiles/ — incluidos en la app)
        bpath=os.path.join(BUNDLED_TILE_DIR, str(z), str(x), f'{y}.png')
        if os.path.isfile(bpath):
            pm=QPixmap(bpath)
            if not pm.isNull(): self._tiles[key]=pm; return pm
        # 4. Descarga desde OSM (solo en modo online)
        if key not in self._loading and self._online:
            self._loading.add(key)
            ldr=TileLoader(z,x,y)
            ldr.ready.connect(self._on_tile)
            # Guardamos referencia explícita → evita que el GC destruya el hilo
            # antes de que emita la señal ready
            ldr.finished.connect(lambda k=key: self._loader_finished(k))
            self._loaders[key]=ldr
            ldr.start()
        return None

    def _loader_finished(self, key):
        """Limpia el loader cuando termina (exito o fallo de red)."""
        ldr=self._loaders.pop(key, None)
        self._loading.discard(key)
        if ldr: ldr.deleteLater()

    def _on_tile(self, z, x, y, data):
        key=(z,x,y)
        try:
            path=os.path.join(TILE_DIR, str(z), str(x), f'{y}.png')
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path,'wb') as f: f.write(data)
        except Exception: pass
        pm=QPixmap(); pm.loadFromData(data)
        if not pm.isNull(): self._tiles[key]=pm; self.update()

    def paintEvent(self, e):
        w,h=self.width(),self.height()
        if w<2 or h<2: return          # widget aun sin tamanyo, nada que pintar
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(0,0,w,h,QColor('#a8d5e2'))
        z=self._zoom; n=2.0**z
        ctx,cty=_tile_xy(self._cy, self._cx, z)
        ox=w/2-(ctx-int(ctx))*TILE_SZ; oy=h/2-(cty-int(cty))*TILE_SZ
        rx=int(math.ceil(w/TILE_SZ/2))+1; ry=int(math.ceil(h/TILE_SZ/2))+1
        itx,ity=int(ctx),int(cty); any_tile=False
        for dx in range(-rx,rx+1):
            for dy in range(-ry,ry+1):
                tx=itx+dx; ty=ity+dy
                txw=tx%int(n)
                if txw<0: txw+=int(n)
                if ty<0 or ty>=int(n): continue
                px=int(ox+dx*TILE_SZ); py=int(oy+dy*TILE_SZ)
                pm=self._get_tile(z,txw,ty)
                if pm: p.drawPixmap(px,py,pm); any_tile=True
                else:
                    p.fillRect(px,py,TILE_SZ,TILE_SZ,QColor('#c8dde8'))
                    p.setPen(QColor('#bbbbbb')); p.drawRect(px,py,TILE_SZ,TILE_SZ)
        # GPS marker
        if self._gps_lat is not None:
            gx,gy=_tile_xy(self._gps_lat, self._gps_lon, z)
            mx=int(w/2+(gx-ctx)*TILE_SZ); my=int(h/2+(gy-cty)*TILE_SZ)
            p.setBrush(QBrush(QColor(255,255,255,200))); p.setPen(QPen(QColor('#1565C0'),2))
            p.drawEllipse(mx-10,my-10,20,20)
            p.setBrush(QBrush(QColor('#1565C0'))); p.setPen(Qt.NoPen); p.drawEllipse(mx-4,my-4,8,8)
            p.setPen(QPen(QColor('#1565C0'),1))
            p.drawLine(mx-16,my,mx-11,my); p.drawLine(mx+11,my,mx+16,my)
            p.drawLine(mx,my-16,mx,my-11); p.drawLine(mx,my+11,mx,my+16)
        # Attribution
        p.setFont(QFont('Arial',7)); p.setPen(QColor('#444444'))
        p.fillRect(0,h-14,220,14,QColor(255,255,255,170))
        p.drawText(2,h-3,'© OpenStreetMap contributors')
        # Zoom badge
        p.setFont(QFont('Arial',8,QFont.Bold))
        p.fillRect(w-40,4,36,16,QColor(255,255,255,180))
        p.setPen(QColor('#333333')); p.drawText(w-38,16,f'Z{z}')
        if not any_tile:
            # ── Cuadricula UTM cuando no hay tiles ───────────────────────────
            def _ll2px(lat, lon):
                gx,gy = _tile_xy(lat, lon, z)
                return int(w/2+(gx-ctx)*TILE_SZ), int(h/2+(gy-cty)*TILE_SZ)
            # Limites UTM: 80°S – 84°N
            LAT_S, LAT_N = -80, 84
            # Bandas UTM (latitud inferior, letra)
            UTM_BANDS = [
                (-80,'C'),(-72,'D'),(-64,'E'),(-56,'F'),(-48,'G'),(-40,'H'),
                (-32,'J'),(-24,'K'),(-16,'L'),(-8,'M'),(0,'N'),(8,'P'),
                (16,'Q'),(24,'R'),(32,'S'),(40,'T'),(48,'U'),(56,'V'),
                (64,'W'),(72,'X'),
            ]
            BAND_LATS = [b[0] for b in UTM_BANDS] + [84]
            # Lineas de zonas (cada 6° de longitud)
            p.setPen(QPen(QColor(80,130,200,90), 1))
            for zo in range(-180, 181, 6):
                x1,y1 = _ll2px(LAT_N, zo); x2,y2 = _ll2px(LAT_S, zo)
                p.drawLine(x1,y1,x2,y2)
            # Lineas de bandas (latitud)
            for la in BAND_LATS:
                x1,y1 = _ll2px(la,-180); x2,y2 = _ll2px(la,180)
                p.drawLine(x1,y1,x2,y2)
            # Ecuador destacado en blanco discontinuo
            p.setPen(QPen(QColor(255,255,255,140), 1, Qt.DashLine))
            x1,y1=_ll2px(0,-180); x2,y2=_ll2px(0,180); p.drawLine(x1,y1,x2,y2)
            # Meridiano 0 destacado en blanco discontinuo
            x1,y1=_ll2px(LAT_N,0); x2,y2=_ll2px(LAT_S,0); p.drawLine(x1,y1,x2,y2)
            # Numeros de zona (en la parte superior de cada zona)
            p.setFont(QFont('Arial',7)); p.setPen(QColor(255,255,255,210))
            for zi, zo_lo in enumerate(range(-180, 180, 6)):
                mid_lon = zo_lo + 3; zone_num = zi + 1
                x,y = _ll2px(LAT_N, mid_lon)
                if 0 < x < w:
                    p.fillRect(x-8, max(2,y+1), 16, 11, QColor(0,0,0,80))
                    p.drawText(x-8, max(2,y+1), 16, 11, Qt.AlignCenter, str(zone_num))
            # Letras de banda (en el lado izquierdo)
            p.setFont(QFont('Arial',7,QFont.Bold))
            for i, (la_lo, ltr) in enumerate(UTM_BANDS):
                la_hi = BAND_LATS[i+1]; mid_lat = (la_lo + la_hi) / 2
                x,y = _ll2px(mid_lat, -180)
                if 0 < y < h:
                    p.fillRect(2, y-6, 14, 12, QColor(0,0,0,80))
                    p.drawText(2, y-6, 14, 12, Qt.AlignCenter, ltr)
            # Mensaje de modo
            if self._online:
                msg = '⬇  Descargando tiles…'
            else:
                msg = f'📴  No Offline Tiles for Zoom {z}  (Max Zoom: 6)'
            p.setFont(QFont('Arial',9))
            fm_w = len(msg)*6+20
            p.fillRect(w//2-fm_w//2, h//2+14, fm_w, 22, QColor(0,0,0,100))
            p.setPen(QColor(255,255,255,220))
            p.drawText(0, h//2+14, w, 22, Qt.AlignCenter, msg)
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# ALS162 — WIDGET ESPECTRO
# ─────────────────────────────────────────────────────────────────────────────
class SpectrumWidget(QWidget):
    F_LO, F_HI = 300, 800

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(70); self.setMinimumWidth(200)
        self._freqs = self._amps = self._carrier = None
        self.setStyleSheet('background:#1a1a2e;border-radius:4px;')

    def update_data(self, freqs, amps, carrier):
        self._freqs=freqs; self._amps=amps; self._carrier=carrier; self.update()

    def paintEvent(self, event):
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        w,h,pad_b=self.width(),self.height(),18
        p.fillRect(0,0,w,h,QColor('#1a1a2e'))
        p.setPen(QPen(QColor('#333355'),1,Qt.DotLine))
        for f in range(350,801,50):
            x=int((f-self.F_LO)/(self.F_HI-self.F_LO)*w); p.drawLine(x,0,x,h-pad_b)
        if self._freqs is None or len(self._freqs)==0:
            p.setPen(QColor('#5566aa')); p.setFont(QFont('Courier New',8))
            p.drawText(0,0,w,h-pad_b,Qt.AlignCenter,'— sin señal —')
        else:
            import numpy as _np
            amps=self._amps/(self._amps.max() or 1)
            bar_w=max(1,w/len(self._freqs))
            for i,(f,a) in enumerate(zip(self._freqs,amps)):
                x=int((f-self.F_LO)/(self.F_HI-self.F_LO)*w); bh=int(a*(h-pad_b))
                color=(QColor('#00e5ff') if self._carrier and abs(f-self._carrier)<15
                       else QColor(int(30+a*60),int(100+a*80),int(200+a*55)))
                p.fillRect(int(x-bar_w/2),(h-pad_b)-bh,max(1,int(bar_w)),bh,color)
        if self._carrier and self.F_LO<=self._carrier<=self.F_HI:
            xc=int((self._carrier-self.F_LO)/(self.F_HI-self.F_LO)*w)
            p.setPen(QPen(QColor('#ff4444'),2)); p.drawLine(xc,0,xc,h-pad_b)
            p.setPen(QColor('#ff8888')); p.setFont(QFont('Courier New',7))
            p.drawText(max(2,min(xc-16,w-44)),0,50,12,Qt.AlignLeft,f'{self._carrier:.0f}Hz')
        p.setPen(QColor('#8888bb')); p.setFont(QFont('Courier New',7))
        for f in [350,400,450,500,550,600,650,700,750]:
            x=int((f-self.F_LO)/(self.F_HI-self.F_LO)*w)
            p.drawText(x-12,h-pad_b+2,30,pad_b-2,Qt.AlignCenter,str(f))
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# ALS162 — HILO DECODIFICADOR
# ─────────────────────────────────────────────────────────────────────────────
class DecoderThread(QThread):
    frame_signal    = pyqtSignal(object)
    status_signal   = pyqtSignal(str)
    carrier_signal  = pyqtSignal(float)
    level_signal    = pyqtSignal(float)
    spectrum_signal = pyqtSignal(object)

    _SPECTRUM_INTERVAL = 0.25

    def __init__(self, device_index):
        super().__init__()
        self.device_index=device_index
        self._stop=threading.Event(); self._carrier=None; self._last_spec=0.0

    def stop(self): self._stop.set()

    def run(self):
        import numpy as _np
        import sys as _sys
        self._stop.clear()
        # ── Redirigir stdout/stderr del decodificador a log ───────────────────
        _log_dir = os.path.join(os.path.expanduser('~'), '.als162gps')
        os.makedirs(_log_dir, exist_ok=True)
        _log_path = os.path.join(_log_dir, 'decoder.log')
        _orig_out, _orig_err = _sys.stdout, _sys.stderr
        _lf = None
        try:
            _lf = open(_log_path, 'a', encoding='utf-8', errors='replace')
            _sys.stdout = _sys.stderr = _lf
        except Exception:
            pass
        try:
            self._run_inner()
        finally:
            _sys.stdout, _sys.stderr = _orig_out, _orig_err
            if _lf:
                try: _lf.close()
                except Exception: pass

    def _run_inner(self):
        import numpy as _np
        self.status_signal.emit('detecting')
        try:
            fc=dec.detect_carrier_live(self.device_index, dec.SAMPLE_RATE, silent=True)
        except Exception as e:
            self.status_signal.emit(f'error:{e}'); return
        self._carrier=fc; self.carrier_signal.emit(fc); self.status_signal.emit('running')
        def _emit_frame(frame):
            frame._emit_mono = time.monotonic()   # instante exacto de emisión
            self.frame_signal.emit(frame)
        proc=dec.ALS162Processor(dec.SAMPLE_RATE, fc, _emit_frame, verbose=False)
        rolling=_np.zeros(0,dtype=_np.float64); rolling_start=0; last_proc=0
        lock=threading.Lock()

        def on_chunk(samples, abs_start):
            nonlocal rolling,rolling_start,last_proc
            if self._stop.is_set(): return
            rms=_np.sqrt(_np.mean(samples**2))
            self.level_signal.emit(20.0*_np.log10(max(rms,1.0)/32768.0))
            now=time.monotonic()
            if now-self._last_spec>=self._SPECTRUM_INTERVAL:
                self._last_spec=now
                n=min(len(samples),8192); win=_np.hanning(n)
                spec=_np.abs(_np.fft.rfft(samples[:n]*win))
                freqs=_np.fft.rfftfreq(n,1.0/dec.SAMPLE_RATE)
                mask=(freqs>=SpectrumWidget.F_LO)&(freqs<=SpectrumWidget.F_HI)
                fm,sm=freqs[mask],spec[mask]
                fc_now=self._carrier
                if fc_now and len(sm) and sm.max()>0:
                    sig_m=_np.abs(fm-fc_now)<=12
                    n_med=_np.median(sm[~sig_m]) if (~sig_m).any() else 1e-9
                    snr=(20.0*_np.log10(sm[sig_m].max()/max(n_med,1e-9)) if sig_m.any() else 0.0)
                else:
                    n_med=_np.median(sm) if len(sm) else 1e-9
                    snr=20.0*_np.log10(sm.max()/max(n_med,1e-9)) if len(sm) else 0.0
                clip_pct=100.0*float(_np.mean(_np.abs(samples)>=32000))
                top5=[(float(fm[i]),100.0*float(sm[i])/sm.max())
                      for i in _np.argsort(sm)[-5:][::-1]] if len(sm) else []
                self.spectrum_signal.emit({'freqs':fm,'amps':sm,'carrier':fc_now,
                                           'snr_db':snr,'clip_pct':clip_pct,'top5':top5})
            with lock:
                if len(rolling)==0: rolling=samples.copy(); rolling_start=abs_start
                else: rolling=_np.concatenate([rolling,samples])
                win_s=dec.PROCESS_WINDOW_S*dec.SAMPLE_RATE
                hop_s=dec.PROCESS_HOP_S*dec.SAMPLE_RATE
                while True:
                    ns=max(last_proc,rolling_start)
                    if ns+win_s>rolling_start+len(rolling): break
                    proc.process_window(rolling[ns-rolling_start:ns-rolling_start+win_s],ns)
                    last_proc=ns+hop_s
                kf=max(0,last_proc-rolling_start-win_s)
                if kf>0: rolling=rolling[kf:]; rolling_start+=kf

        cap=dec.LiveAudioCapture(self.device_index, dec.SAMPLE_RATE, on_chunk)
        cap.start(); self._stop.wait(); cap.stop()
        self.status_signal.emit('stopped')


# ─────────────────────────────────────────────────────────────────────────────
# SPINBOX CON SIGNO EXPLICITO
# ─────────────────────────────────────────────────────────────────────────────
class SignedSpinBox(QSpinBox):
    def textFromValue(self, value):
        return f'+{value}' if value>=0 else str(value)


# ─────────────────────────────────────────────────────────────────────────────
# SYNC HORA DEL SO (SetLocalTime)
# ─────────────────────────────────────────────────────────────────────────────
def set_local_time(dt):
    if sys.platform!='win32': return False
    try:
        class ST(ctypes.Structure):
            _fields_=[('wYear',ctypes.c_ushort),('wMonth',ctypes.c_ushort),
                      ('wDayOfWeek',ctypes.c_ushort),('wDay',ctypes.c_ushort),
                      ('wHour',ctypes.c_ushort),('wMinute',ctypes.c_ushort),
                      ('wSecond',ctypes.c_ushort),('wMilliseconds',ctypes.c_ushort)]
        st=ST(); st.wYear=dt.year; st.wMonth=dt.month; st.wDayOfWeek=dt.weekday()
        st.wDay=dt.day; st.wHour=dt.hour; st.wMinute=dt.minute
        st.wSecond=dt.second; st.wMilliseconds=dt.microsecond//1000
        return bool(ctypes.windll.kernel32.SetLocalTime(ctypes.byref(st)))
    except: return False


# ─────────────────────────────────────────────────────────────────────────────
# VENTANA PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        # Icono de ventana y barra de tareas
        _ico = _resource_path(os.path.join('assets', 'logo.ico'))
        _png = _resource_path(os.path.join('assets', 'logo.png'))
        icon = QIcon(_ico) if os.path.exists(_ico) else QIcon(_png)
        if not icon.isNull():
            self.setWindowIcon(icon)
        _cfg=QSettings('QuixoteNetwork','ALS162GPSSync')
        self.lang=_cfg.value('language','en')
        self._thread=None; self._last_snap=None
        self._last_sync=None; self._last_sync_mono=None; self._synced_once=False
        # Estado ALS162
        self._als_thread=None; self._als_last_frame=None; self._als_fc=None
        self._als_user_utc=_get_local_utc_offset(); self._als_tz_user_set=False
        self._als_stat_total=0; self._als_stat_valid=0
        self._als_stat_invalid=0; self._als_stat_bits=0
        self._als_last_frame_ts=None
        self._build_ui(); self._build_tray(); self._refresh_ports(); self._center()
        self._clock_timer=QTimer(self); self._clock_timer.timeout.connect(self._tick); self._clock_timer.start(50)
        self._dop_timer=QTimer(self); self._dop_timer.timeout.connect(self._tick_dop); self._dop_timer.start(250)
        self._als_timer=QTimer(self); self._als_timer.timeout.connect(self._als_tick_last); self._als_timer.start(1000)

    def t(self,key): return T[self.lang].get(key,key)

    def _center(self):
        s=QApplication.primaryScreen().availableGeometry()
        # Tamanyo por defecto: ocupa practicamente toda la pantalla disponible
        # pero deja un pequeño margen. El usuario puede reducirlo; el scroll
        # se activa cuando la ventana es más pequeña que el contenido.
        w = min(860, s.width()  - 40)
        h = min(s.height() - 40, max(780, s.height() * 90 // 100))
        self.resize(w, h)
        self.move(s.x()+(s.width()-w)//2, s.y()+(s.height()-h)//2)

    @staticmethod
    def _sep():
        f=QFrame(); f.setFrameShape(QFrame.HLine); f.setFrameShadow(QFrame.Sunken); return f

    # ── BUILD UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        self.setWindowTitle(self.t('title'))
        self.setMinimumWidth(400)          # permite reducir en pantallas pequeñas
        root_w=QWidget(); self.setCentralWidget(root_w)
        root=QVBoxLayout(root_w); root.setSpacing(0); root.setContentsMargins(6,4,6,4)

        # Pestanyas — idioma en la esquina de la barra de tabs
        self.tabs=QTabWidget(); self.tabs.setDocumentMode(True)
        _tf=QFont(); _tf.setPointSize(QApplication.font().pointSize()+1)
        self.tabs.tabBar().setFont(_tf)
        root.addWidget(self.tabs)

        # Helper: contenedor con QScrollArea (GPS, Sats, ALS162)
        def _make_scroll_tab():
            outer=QWidget(); ol=QVBoxLayout(outer); ol.setContentsMargins(0,0,0,0); ol.setSpacing(0)
            sa=QScrollArea(); sa.setWidgetResizable(True); sa.setFrameShape(QFrame.NoFrame)
            inner=QWidget(); sa.setWidget(inner); ol.addWidget(sa)
            return outer, inner

        tab_gps_w,   tab_gps   = _make_scroll_tab()
        tab_sats_w,  tab_sats  = _make_scroll_tab()
        tab_map=QWidget()                            # mapa: sin scroll, ocupa todo
        tab_als_w,   tab_als   = _make_scroll_tab()
        self._tab_als_inner = tab_als   # guardado para build diferido
        tab_sett_w,  tab_sett  = _make_scroll_tab()
        tab_about_w, tab_about = _make_scroll_tab()

        self.tabs.addTab(tab_gps_w,   self.t('tab_gps'))
        self.tabs.addTab(tab_sats_w,  self.t('tab_sats'))
        self.tabs.addTab(tab_map,     self.t('tab_map'))
        self.tabs.addTab(tab_als_w,   self.t('tab_als'))
        self.tabs.addTab(tab_sett_w,  self.t('tab_settings'))
        self.tabs.addTab(tab_about_w, self.t('tab_about'))
        self._build_tab_gps(tab_gps)
        self._build_tab_sats(tab_sats)
        self._build_tab_map(tab_map)
        self._build_tab_settings(tab_sett)
        self._build_tab_about(tab_about)
        # Tab ALS162 se construye de forma diferida (evita cargar numpy/scipy al inicio)
        QTimer.singleShot(200, self._build_tab_als162_deferred)

        self.statusBar().showMessage(self.t('status_disc'))

    # ── TAB GPS ───────────────────────────────────────────────────────────────
    def _build_tab_gps(self, parent):
        v=QVBoxLayout(parent); v.setSpacing(5); v.setContentsMargins(6,6,6,6)
        fb=QFont(); fb.setBold(True); fb.setPointSize(9)
        fmono=QFont('Courier New',10); fmono_sm=QFont('Courier New',9); f_lbl=QFont('Arial',9)

        # Fila de conexion GPS ─────────────────────────────────────────────────
        row_conn=QHBoxLayout(); row_conn.setSpacing(6)
        self.lbl_port=QLabel(self.t('port_lbl')); self.lbl_port.setStyleSheet('font-size:9pt;color:#555;')
        row_conn.addWidget(self.lbl_port)
        self.combo_port=QComboBox(); self.combo_port.setMinimumWidth(130)
        self.combo_port.setToolTip(self.t('tip_port')); row_conn.addWidget(self.combo_port)
        self.lbl_baud=QLabel(self.t('baud_lbl')); self.lbl_baud.setStyleSheet('font-size:9pt;color:#555;')
        row_conn.addWidget(self.lbl_baud)
        self.combo_baud=QComboBox(); self.combo_baud.setFixedWidth(90)
        self.combo_baud.setToolTip(self.t('tip_baud'))
        self.combo_baud.addItem('auto')
        for b in ['4800','9600','19200','38400','57600','115200']: self.combo_baud.addItem(b)
        row_conn.addWidget(self.combo_baud)
        self.btn_refresh=QPushButton(self.t('refresh')); self.btn_refresh.clicked.connect(self._refresh_ports)
        row_conn.addWidget(self.btn_refresh)
        self.btn_connect=QPushButton(self.t('connect')); self.btn_connect.setFixedWidth(120)
        self.btn_connect.clicked.connect(self._toggle_connect)
        row_conn.addWidget(self.btn_connect); row_conn.addStretch()
        v.addLayout(row_conn); v.addWidget(self._sep())

        # Dos relojes
        clocks=QHBoxLayout(); clocks.setSpacing(8)
        def mk_clock(title_a, time_a, date_a, tz_a):
            panel=QWidget(); panel.setStyleSheet('background:#f5f5f5;border-radius:8px;')
            pv=QVBoxLayout(panel); pv.setSpacing(1); pv.setContentsMargins(8,6,8,6)
            lt=QLabel('—'); lt.setAlignment(Qt.AlignCenter)
            ft=QFont(); ft.setPointSize(9); ft.setBold(True)
            lt.setFont(ft); lt.setStyleSheet('color:#777;')
            ltime=QLabel('--:--:--'); ltime.setAlignment(Qt.AlignCenter)
            ltime.setFont(QFont('Courier New',40,QFont.Bold))
            ltz=QLabel(''); ltz.setAlignment(Qt.AlignCenter)
            ftz=QFont(); ftz.setPointSize(9); ltz.setFont(ftz); ltz.setStyleSheet('color:#666;')
            ldate=QLabel('---'); ldate.setAlignment(Qt.AlignCenter)
            fdt=QFont(); fdt.setPointSize(11); fdt.setBold(True); ldate.setFont(fdt)
            pv.addWidget(lt); pv.addWidget(ltime); pv.addWidget(ltz); pv.addWidget(ldate)
            setattr(self,title_a,lt); setattr(self,time_a,ltime)
            setattr(self,tz_a,ltz);   setattr(self,date_a,ldate)
            return panel
        clocks.addWidget(mk_clock('lbl_pc_title','lbl_pc_time','lbl_pc_date','lbl_pc_tz'))
        clocks.addWidget(mk_clock('lbl_gps_title','lbl_gps_time','lbl_gps_date','lbl_gps_tz'))
        v.addLayout(clocks)

        self.lbl_fix_badge=QLabel(self.t('fix_none'))
        self.lbl_fix_badge.setAlignment(Qt.AlignCenter)
        self.lbl_fix_badge.setStyleSheet('background:#e0e0e0;border-radius:6px;padding:3px 14px;color:#555;font-weight:bold;font-size:10pt;')
        self.lbl_fix_badge.setToolTip(self.t('fix_tip'))
        v.addWidget(self.lbl_fix_badge)

        cols=QHBoxLayout(); cols.setSpacing(8)

        # Posicion
        self.pos_box=QGroupBox(self.t('pos_title')); self.pos_box.setFont(fb)
        pg=QGridLayout(self.pos_box); pg.setHorizontalSpacing(8); pg.setVerticalSpacing(4); pg.setContentsMargins(8,6,8,8)

        def add_row(grid, row, la, va, lk, tk=None, colspan=1):
            lbl=QLabel(self.t(lk)); lbl.setFont(f_lbl); lbl.setStyleSheet('color:#555;')
            val=QLabel(self.t('no_data')); val.setFont(fmono)
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            if tk:
                tip=self.t(tk); lbl.setToolTip(tip); val.setToolTip(tip)
            grid.addWidget(lbl,row,0); grid.addWidget(val,row,1,1,colspan)
            setattr(self,la,lbl); setattr(self,va,val)

        add_row(pg,0,'_llat','lbl_lat_dd',  'lat_lbl',    'tip_fmt_dd')
        add_row(pg,1,'_d1',  'lbl_lat_dms', 'fmt_dms_lbl','tip_fmt_dms')
        add_row(pg,2,'_d2',  'lbl_lat_ddm', 'fmt_ddm_lbl','tip_fmt_ddm')
        pg.addWidget(self._sep(),3,0,1,2)
        add_row(pg,4,'_llon','lbl_lon_dd',  'lon_lbl',    'tip_fmt_dd')
        add_row(pg,5,'_d3',  'lbl_lon_dms', 'fmt_dms_lbl','tip_fmt_dms')
        add_row(pg,6,'_d4',  'lbl_lon_ddm', 'fmt_ddm_lbl','tip_fmt_ddm')
        pg.addWidget(self._sep(),7,0,1,2)
        add_row(pg,8, 'lbl_maiden_l','lbl_maiden',  'maiden_lbl', 'tip_maiden')
        add_row(pg,9, 'lbl_alt_l',  'lbl_alt',     'alt_lbl',    'tip_alt')
        add_row(pg,10,'lbl_utm_l',  'lbl_utm',     'utm_lbl',    'tip_utm')
        add_row(pg,11,'lbl_spd_l',  'lbl_speed',   'speed_lbl',  'tip_speed')
        add_row(pg,12,'lbl_hdg_l',  'lbl_heading', 'heading_lbl','tip_heading')
        self.lbl_utm.setFont(fmono_sm)
        cols.addWidget(self.pos_box,3)

        # DOP
        right_col=QVBoxLayout()
        self.dop_box=QGroupBox(self.t('dop_title')); self.dop_box.setFont(fb)
        dg=QGridLayout(self.dop_box); dg.setHorizontalSpacing(8); dg.setVerticalSpacing(4); dg.setContentsMargins(8,6,8,8)
        dop_fields=[
            ('hdop_lbl','lbl_hdop_l','lbl_hdop','tip_hdop'),
            ('vdop_lbl','lbl_vdop_l','lbl_vdop','tip_vdop'),
            ('pdop_lbl','lbl_pdop_l','lbl_pdop','tip_pdop'),
            ('sats_fix_lbl','lbl_sf_l','lbl_sats_fix','tip_sats_fix'),
            ('sats_gsv_lbl','lbl_sg_l','lbl_sats_gsv','tip_sats_gsv'),
        ]
        for row,(lk,la,va,tk) in enumerate(dop_fields):
            lbl=QLabel(self.t(lk)); lbl.setFont(f_lbl); lbl.setStyleSheet('color:#555;')
            val=QLabel('—'); val.setFont(fmono)
            tip=self.t(tk); lbl.setToolTip(tip); val.setToolTip(tip)
            dg.addWidget(lbl,row,0); dg.addWidget(val,row,1)
            setattr(self,la,lbl); setattr(self,va,val)
        right_col.addWidget(self.dop_box)
        self.dop_graph=DopGraphWidget()
        self.dop_graph.setToolTip('HDOP (azul, escala 0–10) · Satélites (verde, escala 0–20) · últimos 2 min')
        right_col.addWidget(self.dop_graph); right_col.addStretch()
        cols.addLayout(right_col,2)
        v.addLayout(cols)

        # Sync
        self.sync_box=QGroupBox(self.t('sync_title')); self.sync_box.setFont(fb)
        sv=QGridLayout(self.sync_box); sv.setHorizontalSpacing(6); sv.setVerticalSpacing(4); sv.setContentsMargins(8,6,8,8)
        sv.setColumnStretch(3,1)   # col 3 vacía absorbe el espacio extra → label+spin juntos
        self.lbl_tz_l=QLabel(self.t('tz_lbl')); self.lbl_tz_l.setStyleSheet('color:#555;'); sv.addWidget(self.lbl_tz_l,0,0)
        self.spin_tz=SignedSpinBox(); self.spin_tz.setRange(-12,14); self.spin_tz.setValue(_get_local_utc_offset())
        self.spin_tz.setFixedWidth(58); self.spin_tz.setToolTip(self.t('tz_tip')); sv.addWidget(self.spin_tz,0,1)
        self.chk_settime=QCheckBox(self.t('settime_chk')); self.chk_settime.setStyleSheet('color:#555;'); sv.addWidget(self.chk_settime,0,2)
        self.lbl_autosync=QLabel(self.t('autosync_lbl')); self.lbl_autosync.setStyleSheet('color:#555;'); sv.addWidget(self.lbl_autosync,1,0)
        self.spin_autosync=QSpinBox(); self.spin_autosync.setRange(0,1440); self.spin_autosync.setValue(0); self.spin_autosync.setFixedWidth(58)
        sv.addWidget(self.spin_autosync,1,1)
        lbl_min=QLabel(self.t('autosync_min')); lbl_min.setStyleSheet('color:#777;font-size:9pt;'); sv.addWidget(lbl_min,1,2)
        self.lbl_last_sync_l=QLabel(self.t('last_sync_lbl')); self.lbl_last_sync_l.setStyleSheet('color:#555;'); sv.addWidget(self.lbl_last_sync_l,2,0)
        self.lbl_last_sync=QLabel(self.t('last_sync_never')); self.lbl_last_sync.setFont(QFont('Courier New',9)); sv.addWidget(self.lbl_last_sync,2,1,1,2)
        v.addWidget(self.sync_box)

        # Log sync
        rh=QHBoxLayout()
        self.lbl_sync_log_title=QLabel(self.t('sync_log_title'))
        fb2=QFont(); fb2.setBold(True); self.lbl_sync_log_title.setFont(fb2)
        rh.addWidget(self.lbl_sync_log_title); rh.addStretch()
        self.btn_clear_sync=QPushButton(self.t('clear')); self.btn_clear_sync.setFixedHeight(20)
        self.btn_clear_sync.clicked.connect(lambda: self.sync_log.clear()); rh.addWidget(self.btn_clear_sync)
        v.addLayout(rh)
        self.sync_log=QTextEdit(); self.sync_log.setReadOnly(True); self.sync_log.setFixedHeight(66)
        self.sync_log.setFont(QFont('Courier New',8)); v.addWidget(self.sync_log)

    # ── TAB SATELITES ─────────────────────────────────────────────────────────
    def _build_tab_sats(self, parent):
        v=QVBoxLayout(parent); v.setSpacing(6); v.setContentsMargins(6,6,6,6)
        fb=QFont(); fb.setBold(True); fb.setPointSize(9)
        top=QHBoxLayout(); top.setSpacing(8)

        # Skyplot
        self.sky_box=QGroupBox(self.t('skyplot_title')); self.sky_box.setFont(fb)
        sky_v=QVBoxLayout(self.sky_box); sky_v.setContentsMargins(6,6,6,6)
        self.skyplot=SkyPlotWidget(); sky_v.addWidget(self.skyplot)
        leg=QHBoxLayout()
        for name,color in CONST_COLORS.items():
            dot=QLabel('●'); dot.setStyleSheet(f'color:{color};font-size:13px;')
            lbl=QLabel(name); lbl.setFont(QFont('Arial',8))
            leg.addWidget(dot); leg.addWidget(lbl)
        leg.addStretch(); sky_v.addLayout(leg)
        top.addWidget(self.sky_box,1)

        # Derecha: SNR + constelaciones
        right_v=QVBoxLayout()
        self.snr_box=QGroupBox(self.t('snr_title')); self.snr_box.setFont(fb)
        snr_inner=QVBoxLayout(self.snr_box); snr_inner.setContentsMargins(4,4,4,4)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.snr_container=QWidget(); self.snr_layout=QVBoxLayout(self.snr_container)
        self.snr_layout.setSpacing(2); self.snr_layout.setContentsMargins(2,2,2,2)
        self.snr_layout.addStretch(); scroll.setWidget(self.snr_container); scroll.setMinimumHeight(160)
        snr_inner.addWidget(scroll); right_v.addWidget(self.snr_box)

        # Constelaciones con cabeceras
        self.const_box=QGroupBox(self.t('const_title')); self.const_box.setFont(fb)
        const_grid=QGridLayout(self.const_box); const_grid.setHorizontalSpacing(12)
        const_grid.setVerticalSpacing(3); const_grid.setContentsMargins(8,6,8,8)
        fmono=QFont('Courier New',9); fh=QFont('Arial',8); fh.setBold(True)
        # Cabeceras de columna
        hdr_n=QLabel(self.t('const_hdr_n'));   hdr_n.setFont(fh); hdr_n.setStyleSheet('color:#555;')
        hdr_s=QLabel(self.t('const_hdr_snr')); hdr_s.setFont(fh); hdr_s.setStyleSheet('color:#555;')
        hdr_n.setAlignment(Qt.AlignCenter); hdr_s.setAlignment(Qt.AlignCenter)
        const_grid.addWidget(hdr_n,0,2); const_grid.addWidget(hdr_s,0,3)
        self._const_labels={}
        for row,(name,color) in enumerate(CONST_COLORS.items(),start=1):
            dot=QLabel('●'); dot.setStyleSheet(f'color:{color};font-size:12px;')
            lbl=QLabel(name); lbl.setFont(QFont('Arial',9))
            val=QLabel('0'); val.setFont(fmono); val.setAlignment(Qt.AlignCenter)
            snr_avg=QLabel('—'); snr_avg.setFont(fmono); snr_avg.setAlignment(Qt.AlignCenter)
            const_grid.addWidget(dot,row,0); const_grid.addWidget(lbl,row,1)
            const_grid.addWidget(val,row,2); const_grid.addWidget(snr_avg,row,3)
            self._const_labels[name]=(val,snr_avg)
        right_v.addWidget(self.const_box); right_v.addStretch()
        top.addLayout(right_v,1); v.addLayout(top,1)

        # Log NMEA
        nmea_hdr=QHBoxLayout()
        self.lbl_nmea_title=QLabel(self.t('nmea_log_title'))
        fb2=QFont(); fb2.setBold(True); self.lbl_nmea_title.setFont(fb2)
        nmea_hdr.addWidget(self.lbl_nmea_title); nmea_hdr.addStretch()
        self.btn_clear_nmea=QPushButton(self.t('clear')); self.btn_clear_nmea.setFixedHeight(20)
        self.btn_clear_nmea.clicked.connect(lambda: self.nmea_log.clear()); nmea_hdr.addWidget(self.btn_clear_nmea)
        v.addLayout(nmea_hdr)
        self.nmea_log=QTextEdit(); self.nmea_log.setReadOnly(True); self.nmea_log.setFixedHeight(80)
        self.nmea_log.setFont(QFont('Courier New',8)); v.addWidget(self.nmea_log)

    # ── TAB MAPA ──────────────────────────────────────────────────────────────
    def _build_tab_map(self, parent):
        v=QVBoxLayout(parent); v.setSpacing(4); v.setContentsMargins(6,6,6,6)

        # Barra de controles
        ctrl=QHBoxLayout()
        self.btn_map_center=QPushButton(self.t('map_center'))
        self.btn_map_center.clicked.connect(self._map_center_gps); ctrl.addWidget(self.btn_map_center)
        ctrl.addStretch()
        self.lbl_map_zoom=QLabel(self.t('map_zoom_lbl'))
        self.lbl_map_zoom.setStyleSheet('color:#555;font-size:9pt;'); ctrl.addWidget(self.lbl_map_zoom)
        self.btn_zoom_out=QPushButton(self.t('map_zoom_out')); self.btn_zoom_out.setFixedWidth(30)
        self.btn_zoom_out.setFont(QFont('Arial',12,QFont.Bold))
        self.btn_zoom_out.clicked.connect(self._map_zoom_out); ctrl.addWidget(self.btn_zoom_out)
        self.lbl_zoom_val=QLabel('3'); self.lbl_zoom_val.setFixedWidth(22)
        self.lbl_zoom_val.setAlignment(Qt.AlignCenter)
        self.lbl_zoom_val.setFont(QFont('Courier New',10,QFont.Bold)); ctrl.addWidget(self.lbl_zoom_val)
        self.btn_zoom_in=QPushButton(self.t('map_zoom_in')); self.btn_zoom_in.setFixedWidth(30)
        self.btn_zoom_in.setFont(QFont('Arial',12,QFont.Bold))
        self.btn_zoom_in.clicked.connect(self._map_zoom_in); ctrl.addWidget(self.btn_zoom_in)
        ctrl.addSpacing(8)
        # Boton Online / Offline + etiqueta de estado
        self.lbl_map_mode_txt=QLabel(self.t('map_mode_online'))
        self.lbl_map_mode_txt.setStyleSheet('font-size:9pt;color:#555;')
        ctrl.addWidget(self.lbl_map_mode_txt)
        self.btn_online_mode=QPushButton('🌐')
        self.btn_online_mode.setFixedWidth(34)
        self.btn_online_mode.setCheckable(True); self.btn_online_mode.setChecked(True)
        self.btn_online_mode.setToolTip(self.t('map_mode_tip'))
        self.btn_online_mode.clicked.connect(self._map_toggle_online)
        ctrl.addWidget(self.btn_online_mode)
        v.addLayout(ctrl)

        # Mapa
        self.map_widget=MapWidget()
        self.map_widget.status_changed.connect(self._on_map_status)
        v.addWidget(self.map_widget,1)

        # Barra de estado mapa
        self.lbl_map_status=QLabel(self.t('map_no_fix'))
        self.lbl_map_status.setStyleSheet('color:#777;font-size:8pt;')
        v.addWidget(self.lbl_map_status)

    # ── TRAY ──────────────────────────────────────────────────────────────────
    def _build_tray(self):
        pix=QPixmap(16,16); pix.fill(Qt.transparent)
        p=QPainter(pix); p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor('#1565C0')); p.setPen(Qt.NoPen); p.drawEllipse(1,1,14,14); p.end()
        self.tray=QSystemTrayIcon(QIcon(pix),self)
        menu=QMenu()
        self.act_show=QAction(self.t('tray_show'),self); self.act_show.triggered.connect(self._tray_toggle)
        menu.addAction(self.act_show); menu.addSeparator()
        act_quit=QAction(self.t('tray_quit'),self); act_quit.triggered.connect(QApplication.instance().quit)
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self._tray_toggle() if r==QSystemTrayIcon.DoubleClick else None)
        self.tray.show()

    def _tray_toggle(self):
        if self.isVisible(): self.hide(); self.act_show.setText(self.t('tray_show'))
        else: self.show(); self.raise_(); self.act_show.setText(self.t('tray_hide'))

    # ── PUERTOS ───────────────────────────────────────────────────────────────
    def _refresh_ports(self):
        self.combo_port.clear(); self.combo_port.addItem('auto')
        if HAS_SERIAL:
            for p in serial.tools.list_ports.comports():
                self.combo_port.addItem(f'{p.device}  {p.description}')
        if HAS_GPSD: self.combo_port.addItem('gpsd')

    # ── CONEXION ──────────────────────────────────────────────────────────────
    def _toggle_connect(self):
        if self._thread and self._thread.isRunning():
            self._thread.stop(); self._thread.wait(3000); self._thread=None
            self.btn_connect.setText(self.t('connect')); self.statusBar().showMessage(self.t('status_disc'))
        else:
            if not HAS_SERIAL and not HAS_GPSD:
                self._log_sync(f'<span style="color:red">{self.t("no_gps_lib")}</span>'); return
            port_text=self.combo_port.currentText().split()[0] if self.combo_port.currentText() else 'auto'
            baud_text=self.combo_baud.currentText()
            baud_val='auto' if baud_text=='auto' else int(baud_text)
            self._thread=GpsThread(port=port_text, baud=baud_val)
            self._thread.data_signal.connect(self._on_gps_data)
            self._thread.status_signal.connect(self._on_status)
            self._thread.nmea_signal.connect(self._on_nmea)
            self._thread.start()
            self.btn_connect.setText(self.t('disconnect')); self.statusBar().showMessage(self.t('connecting'))

    # ── SLOTS GPS ─────────────────────────────────────────────────────────────
    def _on_status(self, status):
        msgs={'connected':self.t('status_conn'),'connecting':self.t('connecting'),
              'searching':self.t('status_search'),'fix':self.t('status_fix'),'disconnected':self.t('status_disc')}
        if status.startswith('trying:'):
            self.statusBar().showMessage(f'{self.t("status_trying")} {status[7:]}')
        elif status.startswith('error:'):
            msg=status[6:]; self.statusBar().showMessage(f'{self.t("status_error")}: {msg}')
            self._log_sync(f'<span style="color:red">⛔ {msg}</span>')
        else:
            self.statusBar().showMessage(msgs.get(status,status))

    def _on_nmea(self, line):
        if any(s in line for s in ('GGA','RMC','GSA','GSV')):
            self.nmea_log.append(f'<span style="color:#444;font-family:Courier New">{line}</span>')
        doc=self.nmea_log.document()
        while doc.blockCount()>300:
            cur=self.nmea_log.textCursor(); cur.movePosition(cur.Start)
            cur.select(cur.BlockUnderCursor); cur.removeSelectedText(); cur.deleteChar()

    def _on_gps_data(self, snap):
        self._last_snap=snap
        self._update_position(snap); self._update_satellites(snap); self._maybe_sync_time(snap)
        if snap.lat is not None and snap.lon is not None:
            self.map_widget.set_position(snap.lat, snap.lon)
            self.lbl_zoom_val.setText(str(self.map_widget.get_zoom()))
            self.lbl_map_status.setText(
                f'{snap.lat:.5f}° , {snap.lon:.5f}°  |  Zoom {self.map_widget.get_zoom()}')

    def _log_sync(self, html):
        ts=datetime.datetime.now().strftime('%H:%M:%S')
        self.sync_log.append(f'<span style="color:#999">[{ts}]</span> {html}')

    # ── ACTUALIZACION POSICION ────────────────────────────────────────────────
    def _update_position(self, snap):
        no=self.t('no_data')
        if snap.utc_time:
            tz_h=self.spin_tz.value()
            base=datetime.datetime.combine(snap.utc_date or datetime.date.today(), snap.utc_time)
            local_gps=base+datetime.timedelta(hours=tz_h)
            self.lbl_gps_time.setText(local_gps.strftime('%H:%M:%S'))
            self.lbl_gps_date.setText(fmt_date(local_gps, self.lang))
            sign='+' if tz_h>=0 else ''
            self.lbl_gps_tz.setText(f'UTC{sign}{tz_h}  ·  GPS')
        else:
            self.lbl_gps_time.setText('--:--:--'); self.lbl_gps_date.setText('---'); self.lbl_gps_tz.setText('GPS')

        fq,ft=snap.fix_quality,snap.fix_type
        if fq==0 or ft==1:          fk,fbg,fclr='fix_none','#e0e0e0','#555'
        elif fq>=5:                  fk,fbg,fclr='fix_rtk', '#E1BEE7','#6A1B9A'
        elif fq>=4:                  fk,fbg,fclr='fix_rtk', '#E1BEE7','#6A1B9A'
        elif fq==2:                  fk,fbg,fclr='fix_dgps','#BBDEFB','#1565C0'
        elif ft==3:                  fk,fbg,fclr='fix_3d',  '#C8E6C9','#2E7D32'
        elif ft==2:                  fk,fbg,fclr='fix_2d',  '#FFF9C4','#F57F17'
        else:                        fk,fbg,fclr='fix_none','#e0e0e0','#555'
        self.lbl_fix_badge.setText(self.t(fk))
        self.lbl_fix_badge.setStyleSheet(f'background:{fbg};border-radius:6px;padding:3px 14px;color:{fclr};font-weight:bold;font-size:10pt;')

        if snap.lat is not None and snap.lon is not None:
            lat,lon=snap.lat,snap.lon
            self.lbl_lat_dd.setText(f'{lat:+.7f}°')
            self.lbl_lat_dms.setText(f'  {dd_to_dms(lat,True)}')
            self.lbl_lat_ddm.setText(f'  {dd_to_ddm(lat,True)}')
            self.lbl_lon_dd.setText(f'{lon:+.7f}°')
            self.lbl_lon_dms.setText(f'  {dd_to_dms(lon,False)}')
            self.lbl_lon_ddm.setText(f'  {dd_to_ddm(lon,False)}')
            self.lbl_utm.setText(format_utm(lat,lon))
            self.lbl_maiden.setText(maidenhead(lat, lon))
        else:
            for w in (self.lbl_lat_dd,self.lbl_lat_dms,self.lbl_lat_ddm,
                      self.lbl_lon_dd,self.lbl_lon_dms,self.lbl_lon_ddm,
                      self.lbl_utm,self.lbl_maiden):
                w.setText(no)

        self.lbl_alt.setText(f'{snap.alt_m:.1f} m  /  {snap.alt_m*3.28084:.1f} ft' if snap.alt_m is not None else no)
        if snap.speed_kmh is not None:
            kn=snap.speed_kn or snap.speed_kmh/1.852
            self.lbl_speed.setText(f'{snap.speed_kmh:.1f} km/h  /  {kn:.1f} kn')
        else: self.lbl_speed.setText(no)
        if snap.heading_true is not None:
            hdg=snap.heading_true
            dirs=['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSO','SO','OSO','O','ONO','NO','NNO']
            self.lbl_heading.setText(f'{hdg:.1f}°  {dirs[int((hdg+11.25)/22.5)%16]}')
        else: self.lbl_heading.setText(no)

        self.lbl_hdop.setText(f'{snap.hdop:.2f}' if snap.hdop is not None else no)
        self.lbl_vdop.setText(f'{snap.vdop:.2f}' if snap.vdop is not None else no)
        self.lbl_pdop.setText(f'{snap.pdop:.2f}' if snap.pdop is not None else no)
        self.lbl_sats_fix.setText(str(snap.sats_used))
        self.lbl_sats_gsv.setText(str(len(snap.satellites)))

    # ── ACTUALIZACION SATELITES ───────────────────────────────────────────────
    def _update_satellites(self, snap):
        self.skyplot.update_satellites(snap.satellites)
        sats_sorted=sorted(snap.satellites.items(), key=lambda kv:(-kv[1].get('snr',0),kv[0]))
        while self.snr_layout.count()>1:
            item=self.snr_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        for key,sat in sats_sorted[:24]:
            snr=sat.get('snr',0); const=sat.get('constellation','GPS')
            color=CONST_COLORS.get(const,'#888888'); prn=sat.get('prn','?')
            row_w=QWidget(); row_h=QHBoxLayout(row_w); row_h.setContentsMargins(0,0,0,0); row_h.setSpacing(4)
            lbl_prn=QLabel(f'{key[:2]}{prn:02d}' if isinstance(prn,int) else str(key))
            lbl_prn.setFont(QFont('Courier New',8)); lbl_prn.setFixedWidth(40); row_h.addWidget(lbl_prn)
            bar_w=QWidget(); bar_w.setFixedHeight(12)
            fill=min(snr/50,1.0); fs=f'{fill:.3f}'; fs2=f'{min(fill+0.001,1.0):.3f}'
            bar_w.setStyleSheet(f'background:qlineargradient(x1:0,y1:0,x2:1,y2:0,'
                                f'stop:0 {color}cc,stop:{fs} {color}cc,'
                                f'stop:{fs2} #dddddd,stop:1 #dddddd);'
                                f'border-radius:3px;border:1px solid #cccccc;')
            row_h.addWidget(bar_w,1)
            lbl_snr=QLabel(f'{snr:.0f}'); lbl_snr.setFont(QFont('Courier New',8))
            lbl_snr.setFixedWidth(28); lbl_snr.setAlignment(Qt.AlignRight|Qt.AlignVCenter); row_h.addWidget(lbl_snr)
            self.snr_layout.insertWidget(self.snr_layout.count()-1, row_w)

        cs=defaultdict(lambda:{'count':0,'snr_sum':0.0})
        for sat in snap.satellites.values():
            c=sat.get('constellation','GPS'); cs[c]['count']+=1; cs[c]['snr_sum']+=sat.get('snr',0)
        for name,(val_lbl,snr_lbl) in self._const_labels.items():
            st=cs.get(name,{'count':0,'snr_sum':0.0}); val_lbl.setText(str(st['count']))
            snr_lbl.setText(f"{st['snr_sum']/st['count']:.0f}" if st['count']>0 else '—')

    # ── SYNC HORARIA ──────────────────────────────────────────────────────────
    def _maybe_sync_time(self, snap):
        if not self.chk_settime.isChecked(): return
        if snap.fix_quality==0 or snap.utc_time is None or snap.utc_date is None: return
        now_mono=time.monotonic(); interval_min=self.spin_autosync.value()
        do_sync=(not self._synced_once or
                 (interval_min>0 and self._last_sync_mono is not None and
                  now_mono-self._last_sync_mono>=interval_min*60))
        if not do_sync: return
        utc_dt=datetime.datetime.combine(snap.utc_date, snap.utc_time)
        # Compensar la latencia desde que se parseo el NMEA hasta ahora
        # (puerto serie + hilo + señal Qt: típicamente 50-300 ms)
        elapsed=time.monotonic()-snap.timestamp
        elapsed=max(0.0, min(elapsed, 1.5))   # clampeado a rango razonable
        utc_dt=utc_dt+datetime.timedelta(seconds=elapsed)
        local_dt=utc_dt+datetime.timedelta(hours=self.spin_tz.value())
        ok=set_local_time(local_dt)
        if ok:
            self._synced_once=True; self._last_sync=datetime.datetime.now(); self._last_sync_mono=now_mono
            self.lbl_last_sync.setText(self._last_sync.strftime('%Y-%m-%d %H:%M:%S'))
            tz=self.spin_tz.value(); sign='+' if tz>=0 else ''
            self._log_sync(f'<span style="color:#2E7D32">{self.t("settime_ok")} → {local_dt.strftime("%H:%M:%S")} (UTC{sign}{tz})</span>')
        else:
            self._log_sync(f'<span style="color:red">{self.t("settime_err")}</span>')

    # ── TIMERS ────────────────────────────────────────────────────────────────
    def _tick(self):
        now=datetime.datetime.now()
        # Actualizar pantalla solo cuando cambia el segundo (tick cada 200ms)
        sec_str = now.strftime('%H:%M:%S')
        if getattr(self, '_last_tick_sec', None) == sec_str:
            return
        self._last_tick_sec = sec_str
        self.lbl_pc_time.setText(now.strftime('%H:%M:%S'))
        self.lbl_pc_date.setText(fmt_date(now, self.lang))
        tz_h=self.spin_tz.value(); sign='+' if tz_h>=0 else ''
        self.lbl_pc_tz.setText(f'UTC{sign}{tz_h}  ·  PC')
        if not self.lbl_pc_title.text() or self.lbl_pc_title.text()=='—':
            self.lbl_pc_title.setText(self.t('clock_pc'))
            self.lbl_gps_title.setText(self.t('clock_gps'))
        if self._last_snap is None or self._last_snap.utc_time is None:
            self.lbl_gps_time.setText('--:--:--'); self.lbl_gps_date.setText('---'); self.lbl_gps_tz.setText('GPS')
        # Reloj PC en la pestanya ALS162
        if hasattr(self, 'als_lbl_pc_time'):
            self.als_lbl_pc_time.setText(now.strftime('%H:%M:%S'))
            self.als_lbl_pc_date.setText(fmt_date(now, self.lang))
            sign2='+' if self._als_user_utc>=0 else ''
            self.als_lbl_pc_tz.setText(f'UTC{sign2}{self._als_user_utc}  ·  PC')
            if not self.als_lbl_pc_title.text() or self.als_lbl_pc_title.text()=='—':
                self.als_lbl_pc_title.setText(self.t('als_clock_pc'))
                self.als_lbl_als_title.setText(self.t('als_clock_als'))

    def _tick_dop(self):
        if self._last_snap:
            self.dop_graph.push(self._last_snap.hdop, len(self._last_snap.satellites))

    # ── CONTROLES MAPA ────────────────────────────────────────────────────────
    def _map_center_gps(self):
        self.map_widget.center_on_gps()
        self.lbl_zoom_val.setText(str(self.map_widget.get_zoom()))

    def _map_zoom_in(self):
        self.map_widget.zoom_in()
        self.lbl_zoom_val.setText(str(self.map_widget.get_zoom()))

    def _map_zoom_out(self):
        self.map_widget.zoom_out()
        self.lbl_zoom_val.setText(str(self.map_widget.get_zoom()))

    def _map_toggle_online(self):
        v = self.btn_online_mode.isChecked()
        self.map_widget.set_online(v)
        self.btn_online_mode.setText('🌐' if v else '📴')
        self.lbl_map_mode_txt.setText(self.t('map_mode_online') if v else self.t('map_mode_offline'))

    def _on_map_status(self, status):
        """Callback cuando el NetworkChecker termina."""
        if status == 'online':
            self.btn_online_mode.setChecked(True)
            self.btn_online_mode.setText('🌐')
            self.lbl_map_mode_txt.setText(self.t('map_mode_online'))
            self.lbl_map_status.setText(self.t('map_loading'))
        elif status == 'offline':
            self.btn_online_mode.setChecked(False)
            self.btn_online_mode.setText('📴')
            self.lbl_map_mode_txt.setText(self.t('map_mode_offline'))
            self.lbl_map_status.setText(self.t('map_offline'))

    # ── IDIOMA ────────────────────────────────────────────────────────────────
    def _set_lang(self, lang):
        """Cambia el idioma, lo persiste en QSettings y reconstruye las etiquetas."""
        self.lang=lang
        QSettings('QuixoteNetwork','ALS162GPSSync').setValue('language', lang)
        # Sincronizar radio buttons en Settings (si ya estan construidos)
        if hasattr(self,'_radio_en'):
            self._radio_en.blockSignals(True); self._radio_es.blockSignals(True)
            (self._radio_en if lang=='en' else self._radio_es).setChecked(True)
            self._radio_en.blockSignals(False); self._radio_es.blockSignals(False)
        self._rebuild_labels()

    def _toggle_lang(self):
        self._set_lang('en' if self.lang=='es' else 'es')

    def _rebuild_labels(self):
        self.setWindowTitle(self.t('title'))
        self.btn_refresh.setText(self.t('refresh'))
        self.btn_connect.setText(self.t('disconnect') if (self._thread and self._thread.isRunning()) else self.t('connect'))
        self.lbl_port.setText(self.t('port_lbl')); self.lbl_baud.setText(self.t('baud_lbl'))
        self.tabs.setTabText(0,self.t('tab_gps'))
        self.tabs.setTabText(1,self.t('tab_sats'))
        self.tabs.setTabText(2,self.t('tab_map'))
        self.tabs.setTabText(3,self.t('tab_als'))
        self.tabs.setTabText(4,self.t('tab_settings'))
        self.tabs.setTabText(5,self.t('tab_about'))
        self.settings_lang_box.setTitle(self.t('settings_lang_title'))
        self.about_lbl_desc.setText(self.t('about_desc'))
        self.about_btn_github.setText(self.t('about_github') + '  →  github.com/QuixoteNetwork/als162-sync')
        self.about_btn_web.setText(self.t('about_web') + '  →  quixote.info')
        self.about_lbl_support.setText(self.t('about_support'))
        # Clocks GPS
        self.lbl_pc_title.setText(self.t('clock_pc')); self.lbl_gps_title.setText(self.t('clock_gps'))
        # Clocks ALS162
        if hasattr(self, 'als_lbl_pc_title'):
            self.als_lbl_pc_title.setText(self.t('als_clock_pc'))
            self.als_lbl_als_title.setText(self.t('als_clock_als'))
        # Fix badge
        self.lbl_fix_badge.setToolTip(self.t('fix_tip'))
        # Group boxes
        self.pos_box.setTitle(self.t('pos_title'))
        self.dop_box.setTitle(self.t('dop_title'))
        self.sync_box.setTitle(self.t('sync_title'))
        self.sky_box.setTitle(self.t('skyplot_title'))
        self.snr_box.setTitle(self.t('snr_title'))
        self.const_box.setTitle(self.t('const_title'))
        # Position row labels
        self._llat.setText(self.t('lat_lbl')); self._llon.setText(self.t('lon_lbl'))
        self._d1.setText(self.t('fmt_dms_lbl')); self._d2.setText(self.t('fmt_ddm_lbl'))
        self._d3.setText(self.t('fmt_dms_lbl')); self._d4.setText(self.t('fmt_ddm_lbl'))
        self.lbl_maiden_l.setText(self.t('maiden_lbl'))
        self.lbl_alt_l.setText(self.t('alt_lbl')); self.lbl_utm_l.setText(self.t('utm_lbl'))
        self.lbl_spd_l.setText(self.t('speed_lbl')); self.lbl_hdg_l.setText(self.t('heading_lbl'))
        # DOP labels
        self.lbl_hdop_l.setText(self.t('hdop_lbl')); self.lbl_vdop_l.setText(self.t('vdop_lbl'))
        self.lbl_pdop_l.setText(self.t('pdop_lbl'))
        self.lbl_sf_l.setText(self.t('sats_fix_lbl')); self.lbl_sg_l.setText(self.t('sats_gsv_lbl'))
        # Sync labels
        self.chk_settime.setText(self.t('settime_chk'))
        self.spin_tz.setToolTip(self.t('tz_tip')); self.lbl_tz_l.setText(self.t('tz_lbl'))
        self.lbl_autosync.setText(self.t('autosync_lbl'))
        self.lbl_last_sync_l.setText(self.t('last_sync_lbl'))
        self.lbl_sync_log_title.setText(self.t('sync_log_title'))
        self.lbl_nmea_title.setText(self.t('nmea_log_title'))
        self.btn_clear_sync.setText(self.t('clear')); self.btn_clear_nmea.setText(self.t('clear'))
        # Map
        self.btn_map_center.setText(self.t('map_center'))
        self.btn_zoom_in.setText(self.t('map_zoom_in')); self.btn_zoom_out.setText(self.t('map_zoom_out'))
        self.lbl_map_zoom.setText(self.t('map_zoom_lbl'))
        is_online = self.btn_online_mode.isChecked()
        self.lbl_map_mode_txt.setText(self.t('map_mode_online') if is_online else self.t('map_mode_offline'))
        self.btn_online_mode.setToolTip(self.t('map_mode_tip'))
        # Actualizar estado del mapa segun situacion actual
        cur_status = self.lbl_map_status.text()
        if not cur_status or cur_status in [
            'Sin fix GPS — el mapa se centrará automáticamente al obtener posición',
            'No GPS fix — map will center automatically when position is available']:
            self.lbl_map_status.setText(self.t('map_no_fix'))
        elif cur_status in ['📴 Sin internet — usando tiles en caché',
                            '📴 No internet — using cached tiles']:
            self.lbl_map_status.setText(self.t('map_offline'))
        elif cur_status in ['⬇ Descargando tiles…', '⬇ Downloading tiles…']:
            self.lbl_map_status.setText(self.t('map_loading'))
        # Tray
        self.act_show.setText(self.t('tray_show') if not self.isVisible() else self.t('tray_hide'))
        # Tooltips
        tip_map={
            'lbl_hdop':'tip_hdop','lbl_hdop_l':'tip_hdop',
            'lbl_vdop':'tip_vdop','lbl_vdop_l':'tip_vdop',
            'lbl_pdop':'tip_pdop','lbl_pdop_l':'tip_pdop',
            'lbl_sats_fix':'tip_sats_fix','lbl_sf_l':'tip_sats_fix',
            'lbl_sats_gsv':'tip_sats_gsv','lbl_sg_l':'tip_sats_gsv',
            'lbl_lat_dd':'tip_fmt_dd','_llat':'tip_fmt_dd',
            'lbl_lat_dms':'tip_fmt_dms','_d1':'tip_fmt_dms',
            'lbl_lat_ddm':'tip_fmt_ddm','_d2':'tip_fmt_ddm',
            'lbl_lon_dd':'tip_fmt_dd','_llon':'tip_fmt_dd',
            'lbl_lon_dms':'tip_fmt_dms','_d3':'tip_fmt_dms',
            'lbl_lon_ddm':'tip_fmt_ddm','_d4':'tip_fmt_ddm',
            'lbl_maiden':'tip_maiden','lbl_maiden_l':'tip_maiden',
            'lbl_alt':'tip_alt','lbl_alt_l':'tip_alt',
            'lbl_utm':'tip_utm','lbl_utm_l':'tip_utm',
            'lbl_speed':'tip_speed','lbl_spd_l':'tip_speed',
            'lbl_heading':'tip_heading','lbl_hdg_l':'tip_heading',
        }
        for attr,tk in tip_map.items():
            w=getattr(self,attr,None)
            if w: w.setToolTip(self.t(tk))
        # Actualizar fechas en nuevo idioma
        now=datetime.datetime.now()
        self.lbl_pc_date.setText(fmt_date(now, self.lang))
        # Refrescar fecha GPS si hay un snap valido con fecha
        if self._last_snap and self._last_snap.utc_time:
            tz_h = self.spin_tz.value()
            base = datetime.datetime.combine(
                self._last_snap.utc_date or datetime.date.today(),
                self._last_snap.utc_time)
            local_gps = base + datetime.timedelta(hours=tz_h)
            self.lbl_gps_date.setText(fmt_date(local_gps, self.lang))
        # ── Pestanya ALS162 ────────────────────────────────────────────────────
        if hasattr(self, 'als_lbl_dev'):
            self.als_lbl_dev.setText(self.t('als_device'))
            self.als_btn_refresh.setText(self.t('refresh'))
            is_als_run = bool(self._als_thread and self._als_thread.isRunning())
            self.als_btn_start.setText(self.t('als_stop') if is_als_run else self.t('als_start'))
            self.als_chk_settime.setText(self.t('als_set_time_chk'))
            self.als_lbl_tz_lbl.setText(self.t('als_tz_lbl'))
            self.als_lbl_tz_lbl.setToolTip(self.t('als_tz_tip'))
            self.als_spin_tz.setToolTip(self.t('als_tz_tip'))
            self.als_sig_box.setTitle(self.t('als_sig_title'))
            self.als_lbl_sig_lbl.setText(self.t('als_sig_level'))
            self.als_lbl_fc_l.setText(self.t('als_sig_carrier'))
            self.als_lbl_snr_l.setText(self.t('als_sig_snr'))
            self.als_lbl_clip_l.setText(self.t('als_sig_clip'))
            self.als_lbl_peaks_l.setText(self.t('als_sig_peaks'))
            if not is_als_run:
                self.als_lbl_tip.setText(self.t('als_tip_none'))
            self.als_sync_box.setTitle(self.t('sync_title'))
            self.als_stat_box.setTitle(self.t('als_stats_title'))
            self.als_st_fr_l.setText(self.t('als_stats_frames'))
            self.als_st_ok_l.setText(self.t('als_stats_valid'))
            self.als_st_nk_l.setText(self.t('als_stats_invalid'))
            self.als_st_bt_l.setText(self.t('als_stats_bits'))
            self.als_lbl_last_l.setText(self.t('als_stats_last'))
            self.als_lbl_log_title.setText(self.t('als_log_title'))
            self.als_btn_clear.setText(self.t('clear'))
            self._als_update_holiday_labels()
            if hasattr(self, 'als_lbl_pc_date'):
                self.als_lbl_pc_date.setText(fmt_date(now, self.lang))
        # ── Barra de estado ───────────────────────────────────────────────────
        if self._thread and self._thread.isRunning():
            snap=self._last_snap
            if snap and snap.fix_quality and snap.fix_quality>0:
                self.statusBar().showMessage(self.t('status_fix'))
            else:
                self.statusBar().showMessage(self.t('status_conn'))
        else:
            self.statusBar().showMessage(self.t('status_disc'))

    # ── TAB SETTINGS ──────────────────────────────────────────────────────────
    def _build_tab_settings(self, parent):
        v=QVBoxLayout(parent); v.setSpacing(16); v.setContentsMargins(20,20,20,20)
        fb=QFont(); fb.setBold(True); fb.setPointSize(9)

        # Idioma
        self.settings_lang_box=QGroupBox(self.t('settings_lang_title')); self.settings_lang_box.setFont(fb)
        lg=QVBoxLayout(self.settings_lang_box); lg.setSpacing(6); lg.setContentsMargins(12,8,12,10)
        self._radio_en=QRadioButton('English')
        self._radio_es=QRadioButton('Español')
        _grp=QButtonGroup(self); _grp.addButton(self._radio_en); _grp.addButton(self._radio_es)
        (self._radio_en if self.lang=='en' else self._radio_es).setChecked(True)
        self._radio_en.toggled.connect(lambda checked: self._set_lang('en') if checked else None)
        self._radio_es.toggled.connect(lambda checked: self._set_lang('es') if checked else None)
        lg.addWidget(self._radio_en); lg.addWidget(self._radio_es)
        v.addWidget(self.settings_lang_box)
        v.addStretch()

    # ── TAB ABOUT ─────────────────────────────────────────────────────────────
    def _build_tab_about(self, parent):
        from PyQt5.QtGui import QDesktopServices
        from PyQt5.QtCore import QUrl
        v=QVBoxLayout(parent); v.setSpacing(14); v.setContentsMargins(24,24,24,24)
        v.addStretch(1)

        # Logo
        logo_path=_resource_path(os.path.join('assets','logo.png'))
        if os.path.exists(logo_path):
            pix=QPixmap(logo_path).scaled(80,80,Qt.KeepAspectRatio,Qt.SmoothTransformation)
            lbl_logo=QLabel(); lbl_logo.setPixmap(pix); lbl_logo.setAlignment(Qt.AlignCenter)
            v.addWidget(lbl_logo)

        # Nombre de la app
        lbl_name=QLabel('ALS162 GPS Sync')
        fn=QFont(); fn.setPointSize(18); fn.setBold(True)
        lbl_name.setFont(fn); lbl_name.setAlignment(Qt.AlignCenter)
        v.addWidget(lbl_name)

        lbl_author=QLabel('by Quixote Network')
        fa=QFont(); fa.setPointSize(10); fa.setItalic(True)
        lbl_author.setFont(fa); lbl_author.setAlignment(Qt.AlignCenter)
        lbl_author.setStyleSheet('color:#666;')
        v.addWidget(lbl_author)

        v.addWidget(self._sep())

        # Descripcion
        self.about_lbl_desc=QLabel(self.t('about_desc'))
        self.about_lbl_desc.setWordWrap(True); self.about_lbl_desc.setAlignment(Qt.AlignCenter)
        fd=QFont(); fd.setPointSize(9); self.about_lbl_desc.setFont(fd)
        self.about_lbl_desc.setStyleSheet('color:#444; padding: 0 8px;')
        v.addWidget(self.about_lbl_desc)

        v.addWidget(self._sep())

        # Botones de enlace
        def _link_btn(text, url):
            btn=QPushButton(text)
            btn.setStyleSheet(
                'QPushButton{border:1px solid #bbb;border-radius:6px;padding:6px 16px;'
                'background:#f5f5f5;font-size:10pt;text-align:left;}'
                'QPushButton:hover{background:#e8e8e8;border-color:#999;}')
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
            return btn

        self.about_btn_github=_link_btn(
            self.t('about_github')+'  →  github.com/QuixoteNetwork/als162-sync',
            'https://github.com/QuixoteNetwork/als162-sync')
        v.addWidget(self.about_btn_github)

        self.about_btn_web=_link_btn(
            self.t('about_web')+'  →  quixote.info',
            'https://quixote.info')
        v.addWidget(self.about_btn_web)

        v.addWidget(self._sep())

        # Ko-fi
        self.about_lbl_support=QLabel(self.t('about_support'))
        fs=QFont(); fs.setPointSize(9); self.about_lbl_support.setFont(fs)
        self.about_lbl_support.setAlignment(Qt.AlignCenter)
        self.about_lbl_support.setStyleSheet('color:#555;')
        v.addWidget(self.about_lbl_support)

        btn_kofi=QPushButton('☕  Ko-fi — ko-fi.com/quixotesystems')
        btn_kofi.setStyleSheet(
            'QPushButton{border:none;border-radius:8px;padding:8px 20px;'
            'background:#FF5E5B;color:white;font-size:11pt;font-weight:bold;}'
            'QPushButton:hover{background:#e54e4b;}')
        btn_kofi.setCursor(Qt.PointingHandCursor)
        btn_kofi.clicked.connect(lambda: QDesktopServices.openUrl(QUrl('https://ko-fi.com/M4M81CV1EX')))
        kofi_row=QHBoxLayout(); kofi_row.addStretch(); kofi_row.addWidget(btn_kofi); kofi_row.addStretch()
        v.addLayout(kofi_row)

        v.addStretch(2)

    # ── TAB ALS162 ────────────────────────────────────────────────────────────
    def _build_tab_als162_deferred(self):
        """Construye el tab ALS162 tras el arranque (lazy load de numpy/scipy)."""
        _load_als_libs()
        self._build_tab_als162(self._tab_als_inner)

    def _build_tab_als162(self, parent):
        v=QVBoxLayout(parent); v.setSpacing(5); v.setContentsMargins(8,8,8,8)
        fb=QFont(); fb.setBold(True); fb.setPointSize(9)
        fmono=QFont('Courier New',9); f9=QFont(); f9.setPointSize(9)

        # ── Mensaje si faltan dependencias ───────────────────────────────────
        if not HAS_PYAUDIO or not HAS_DECODER:
            msg=self.t('als_no_lib') if not HAS_PYAUDIO else self.t('als_no_decoder')
            lbl=QLabel(msg); lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet('font-size:11pt;color:#c00;padding:20px;')
            v.addWidget(lbl); v.addStretch(); return

        # ── Fila dispositivo audio ────────────────────────────────────────────
        row_dev=QHBoxLayout(); row_dev.setSpacing(6)
        self.als_lbl_dev=QLabel(self.t('als_device'))
        self.als_lbl_dev.setStyleSheet('font-size:9pt;color:#555;')
        row_dev.addWidget(self.als_lbl_dev)
        self.als_combo=QComboBox(); self.als_combo.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
        row_dev.addWidget(self.als_combo)
        self.als_btn_refresh=QPushButton(self.t('refresh'))
        self.als_btn_refresh.clicked.connect(self._als_refresh_devices)
        row_dev.addWidget(self.als_btn_refresh)
        self.als_btn_start=QPushButton(self.t('als_start'))
        self.als_btn_start.setFixedWidth(120)
        self.als_btn_start.setFont(QFont('Arial',10)); self.als_btn_start.clicked.connect(self._als_toggle)
        row_dev.addWidget(self.als_btn_start); row_dev.addStretch()
        v.addLayout(row_dev); v.addWidget(self._sep())

        # ── Dos relojes: PC + ALS162 ─────────────────────────────────────────
        def mk_als_clock(title_a, time_a, tz_a, date_a, time_init='--:--'):
            panel=QWidget(); panel.setStyleSheet('background:#f5f5f5;border-radius:8px;')
            pv=QVBoxLayout(panel); pv.setSpacing(1); pv.setContentsMargins(8,6,8,6)
            lt=QLabel('—'); lt.setAlignment(Qt.AlignCenter)
            ft=QFont(); ft.setPointSize(9); ft.setBold(True)
            lt.setFont(ft); lt.setStyleSheet('color:#777;')
            pv.addWidget(lt)
            ltime=QLabel(time_init); ltime.setAlignment(Qt.AlignCenter)
            ltime.setFont(QFont('Courier New',40,QFont.Bold)); pv.addWidget(ltime)
            ltz=QLabel(''); ltz.setAlignment(Qt.AlignCenter)
            ftz=QFont(); ftz.setPointSize(9); ltz.setFont(ftz); ltz.setStyleSheet('color:#666;')
            pv.addWidget(ltz)
            ldate=QLabel(''); ldate.setAlignment(Qt.AlignCenter)
            fd2=QFont(); fd2.setPointSize(11); fd2.setBold(True); ldate.setFont(fd2)
            pv.addWidget(ldate)
            setattr(self,title_a,lt); setattr(self,time_a,ltime)
            setattr(self,tz_a,ltz);   setattr(self,date_a,ldate)
            return panel
        clocks_als=QHBoxLayout(); clocks_als.setSpacing(8)
        clocks_als.addWidget(mk_als_clock('als_lbl_pc_title','als_lbl_pc_time','als_lbl_pc_tz','als_lbl_pc_date','--:--:--'))
        clocks_als.addWidget(mk_als_clock('als_lbl_als_title','als_lbl_time','als_lbl_tz','als_lbl_date','--:--'))
        v.addLayout(clocks_als)
        # Festivos y anotaciones (datos ALS162)
        hol_widget=QWidget(); hol_widget.setStyleSheet('background:#f5f5f5;border-radius:8px;')
        hp=QVBoxLayout(hol_widget); hp.setSpacing(2); hp.setContentsMargins(10,6,10,6)
        row_hol=QHBoxLayout(); row_hol.setAlignment(Qt.AlignCenter); row_hol.setSpacing(16)
        fh=QFont(); fh.setBold(True); fh.setPointSize(9); fv=QFont(); fv.setPointSize(10)
        for at,av in [('als_lbl_hoy_title','als_lbl_hoy'),('als_lbl_man_title','als_lbl_man')]:
            grp=QGroupBox(); gv=QVBoxLayout(grp); gv.setContentsMargins(8,4,8,4); gv.setSpacing(1)
            lt=QLabel(); lt.setAlignment(Qt.AlignCenter); lt.setFont(fh)
            lv=QLabel('—'); lv.setAlignment(Qt.AlignCenter); lv.setFont(fv)
            gv.addWidget(lt); gv.addWidget(lv)
            setattr(self,at,lt); setattr(self,av,lv); row_hol.addWidget(grp)
        hp.addLayout(row_hol)
        self.als_lbl_ann=QLabel(''); self.als_lbl_ann.setAlignment(Qt.AlignCenter)
        self.als_lbl_ann.setStyleSheet('color:#c80;font-style:italic;'); hp.addWidget(self.als_lbl_ann)
        v.addWidget(hol_widget); v.addWidget(self._sep())

        # ── Panel señal SDR ───────────────────────────────────────────────────
        sig_box=QGroupBox(self.t('als_sig_title')); sig_box.setFont(fb); self.als_sig_box=sig_box
        sv=QVBoxLayout(sig_box); sv.setSpacing(3); sv.setContentsMargins(8,6,8,6)
        r1=QHBoxLayout()
        self.als_lbl_sig_lbl=QLabel(self.t('als_sig_level')); self.als_lbl_sig_lbl.setFixedWidth(52)
        r1.addWidget(self.als_lbl_sig_lbl)
        self.als_bar_level=QProgressBar(); self.als_bar_level.setRange(0,100)
        self.als_bar_level.setValue(0); self.als_bar_level.setFixedHeight(14)
        self.als_bar_level.setTextVisible(False)
        self.als_bar_level.setStyleSheet(self._als_bar_css('gray')); r1.addWidget(self.als_bar_level)
        self.als_lbl_db=QLabel('—'); self.als_lbl_db.setFixedWidth(52)
        self.als_lbl_db.setAlignment(Qt.AlignRight|Qt.AlignVCenter); self.als_lbl_db.setFont(fmono)
        r1.addWidget(self.als_lbl_db); sv.addLayout(r1)
        r2=QGridLayout(); r2.setHorizontalSpacing(12); r2.setVerticalSpacing(2)
        for col,(lk,la,vk,va) in enumerate([
            ('als_sig_carrier','als_lbl_fc_l','als_sig_none','als_lbl_fc_v'),
            ('als_sig_snr',    'als_lbl_snr_l','als_sig_none','als_lbl_snr_v'),
            ('als_sig_clip',   'als_lbl_clip_l','als_sig_none','als_lbl_clip_v'),
        ]):
            lw=QLabel(self.t(lk)); lw.setFont(f9)
            vw=QLabel(self.t(vk)); vw.setFont(fmono)
            r2.addWidget(lw,0,col*2); r2.addWidget(vw,0,col*2+1)
            setattr(self,la,lw); setattr(self,va,vw)
        sv.addLayout(r2)
        self.als_spectrum=SpectrumWidget(); sv.addWidget(self.als_spectrum)
        r3=QHBoxLayout()
        self.als_lbl_peaks_l=QLabel(self.t('als_sig_peaks')); self.als_lbl_peaks_l.setFont(f9)
        self.als_lbl_peaks_l.setFixedWidth(64); r3.addWidget(self.als_lbl_peaks_l)
        self.als_lbl_peaks_v=QLabel(self.t('als_sig_none'))
        self.als_lbl_peaks_v.setFont(QFont('Courier New',8)); self.als_lbl_peaks_v.setWordWrap(True)
        r3.addWidget(self.als_lbl_peaks_v); sv.addLayout(r3)
        self.als_lbl_tip=QLabel(self.t('als_tip_none')); self.als_lbl_tip.setWordWrap(True)
        self.als_lbl_tip.setFont(QFont('Arial',8))
        self.als_lbl_tip.setFixedHeight(32)   # reserva 2 líneas fijas → no desplaza el layout
        sv.addWidget(self.als_lbl_tip)
        v.addWidget(sig_box); v.addWidget(self._sep())

        # ── Panel estadisticas ────────────────────────────────────────────────
        stat_box=QGroupBox(self.t('als_stats_title')); stat_box.setFont(fb); self.als_stat_box=stat_box
        stv=QVBoxLayout(stat_box); stv.setSpacing(3); stv.setContentsMargins(8,6,8,6)
        rg=QGridLayout(); rg.setHorizontalSpacing(14); rg.setVerticalSpacing(2)
        for col,(lk,la,va) in enumerate([
            ('als_stats_frames','als_st_fr_l','als_st_fr_v'),
            ('als_stats_valid', 'als_st_ok_l','als_st_ok_v'),
            ('als_stats_invalid','als_st_nk_l','als_st_nk_v'),
            ('als_stats_bits',  'als_st_bt_l','als_st_bt_v'),
        ]):
            lw=QLabel(self.t(lk)); lw.setFont(f9)
            vw=QLabel('0'); vw.setFont(fmono)
            rg.addWidget(lw,0,col*2); rg.addWidget(vw,0,col*2+1)
            setattr(self,la,lw); setattr(self,va,vw)
        stv.addLayout(rg)
        rl=QHBoxLayout()
        self.als_lbl_last_l=QLabel(self.t('als_stats_last')); self.als_lbl_last_l.setFont(f9)
        self.als_lbl_last_v=QLabel(self.t('als_stats_never')); self.als_lbl_last_v.setFont(fmono)
        rl.addWidget(self.als_lbl_last_l); rl.addWidget(self.als_lbl_last_v); rl.addStretch()
        stv.addLayout(rl)
        v.addWidget(stat_box); v.addWidget(self._sep())

        # ── Sincronizacion horaria (GroupBox, mismo estilo que pestanya GPS) ───
        self.als_sync_box=QGroupBox(self.t('sync_title')); self.als_sync_box.setFont(fb)
        asv=QGridLayout(self.als_sync_box); asv.setHorizontalSpacing(6); asv.setVerticalSpacing(4)
        asv.setContentsMargins(8,6,8,8)
        asv.setColumnStretch(3,1)   # col 3 vacia absorbe espacio extra → label+spin juntos
        self.als_lbl_tz_lbl=QLabel(self.t('als_tz_lbl'))
        self.als_lbl_tz_lbl.setStyleSheet('color:#555;')
        self.als_lbl_tz_lbl.setToolTip(self.t('als_tz_tip')); asv.addWidget(self.als_lbl_tz_lbl,0,0)
        self.als_spin_tz=SignedSpinBox(); self.als_spin_tz.setRange(-12,14)
        self.als_spin_tz.setValue(self._als_user_utc); self.als_spin_tz.setFixedWidth(56)
        self.als_spin_tz.setToolTip(self.t('als_tz_tip'))
        self.als_spin_tz.valueChanged.connect(self._als_on_tz_changed)
        asv.addWidget(self.als_spin_tz,0,1)
        self.als_chk_settime=QCheckBox(self.t('als_set_time_chk'))
        self.als_chk_settime.setStyleSheet('color:#555;'); asv.addWidget(self.als_chk_settime,0,2)
        v.addWidget(self.als_sync_box)

        # ── Historial ────────────────────────────────────────────────────────
        rh=QHBoxLayout()
        self.als_lbl_log_title=QLabel(self.t('als_log_title'))
        fbl=QFont(); fbl.setBold(True); self.als_lbl_log_title.setFont(fbl)
        rh.addWidget(self.als_lbl_log_title); rh.addStretch()
        self.als_btn_clear=QPushButton(self.t('clear')); self.als_btn_clear.setFixedHeight(22)
        self.als_btn_clear.clicked.connect(lambda: self.als_log.clear()); rh.addWidget(self.als_btn_clear)
        v.addLayout(rh)
        self.als_log=QTextEdit(); self.als_log.setReadOnly(True); self.als_log.setFixedHeight(90)
        self.als_log.setFont(QFont('Courier New',8)); v.addWidget(self.als_log)

        self._als_refresh_devices()
        self._als_update_holiday_labels()

    @staticmethod
    def _als_bar_css(color):
        c={'green':'#4caf50','yellow':'#ffc107','red':'#f44336','gray':'#888888'}.get(color,'#888888')
        return (f'QProgressBar::chunk{{background:{c};border-radius:3px;}}'
                f'QProgressBar{{border:1px solid #bbb;border-radius:3px;background:#eee;}}')

    # ── ALS162: dispositivos audio ────────────────────────────────────────────
    def _als_refresh_devices(self):
        if not HAS_PYAUDIO: return
        self.als_combo.clear()
        try:
            pa=_pyaudio.PyAudio(); seen=set()
            for i in range(pa.get_device_count()):
                d=pa.get_device_info_by_index(i)
                if d['maxInputChannels']>0 and d['name'] not in seen:
                    seen.add(d['name']); self.als_combo.addItem(f"{i}: {d['name'][:52]}",userData=i)
            pa.terminate()
        except Exception as e:
            self.statusBar().showMessage(f'Audio error: {e}')

    # ── ALS162: festivos ──────────────────────────────────────────────────────
    def _als_update_holiday_labels(self, frame=None):
        f=frame or (self._als_last_frame if self._als_last_frame and self._als_last_frame.valid else None)
        if f:
            self.als_lbl_hoy_title.setText(f"{self.t('als_today')} ({f.day:02d}/{f.month:02d})")
            self.als_lbl_man_title.setText(self.t('als_hol_lbl'))
            self.als_lbl_hoy.setText(self.t('als_holiday') if f.holiday_today else self.t('als_no_holiday'))
            self.als_lbl_man.setText(self.t('als_hol_yes') if f.holiday_eve else self.t('als_hol_no'))
        else:
            self.als_lbl_hoy_title.setText(self.t('als_today'))
            self.als_lbl_man_title.setText(self.t('als_hol_lbl'))
            self.als_lbl_hoy.setText('—'); self.als_lbl_man.setText('—')

    # ── ALS162: control decoder ───────────────────────────────────────────────
    def _als_toggle(self):
        if self._als_thread and self._als_thread.isRunning():
            self.als_btn_start.setEnabled(False); self._als_thread.stop()
        else:
            idx=self.als_combo.currentData()
            if idx is None: return
            self._als_fc=None; self._als_reset_stats()
            self._als_thread=DecoderThread(idx)
            self._als_thread.frame_signal.connect(self._als_on_frame)
            self._als_thread.status_signal.connect(self._als_on_status)
            self._als_thread.carrier_signal.connect(self._als_on_carrier)
            self._als_thread.level_signal.connect(self._als_on_level)
            self._als_thread.spectrum_signal.connect(self._als_on_spectrum)
            self._als_thread.start()
            self.als_btn_start.setText(self.t('als_stop'))
            self.als_lbl_time.setText('--:--'); self.als_lbl_tz.setText('')
            self.als_lbl_date.setText(''); self.als_lbl_ann.setText('')
            self.als_lbl_fc_v.setText(self.t('als_sig_none'))
            self.als_lbl_snr_v.setText(self.t('als_sig_none'))
            self.als_lbl_clip_v.setText(self.t('als_sig_none'))
            self.als_lbl_peaks_v.setText(self.t('als_sig_none'))
            self.als_spectrum.update_data(None,None,None)
            self.als_bar_level.setValue(0); self.als_lbl_db.setText('—')
            self.als_bar_level.setStyleSheet(self._als_bar_css('gray'))
            self.als_lbl_tip.setText(self.t('als_tip_none'))
            self._als_update_holiday_labels()
            self.statusBar().showMessage(self.t('als_detecting'))

    def _als_on_status(self, s):
        if s=='detecting': self.statusBar().showMessage(self.t('als_detecting'))
        elif s=='running': self.statusBar().showMessage(self.t('als_waiting'))
        elif s=='stopped':
            self.als_btn_start.setText(self.t('als_start')); self.als_btn_start.setEnabled(True)
            self.als_bar_level.setValue(0); self.als_lbl_db.setText('—')
            self.als_bar_level.setStyleSheet(self._als_bar_css('gray'))
            self.als_lbl_tip.setText(self.t('als_tip_none'))
            self.statusBar().showMessage(self.t('als_stopped'))
            self._als_last_frame=None; self.als_lbl_hoy.setText('—'); self.als_lbl_man.setText('—')
        elif s.startswith('error:'):
            self.als_btn_start.setText(self.t('als_start')); self.als_btn_start.setEnabled(True)
            self.statusBar().showMessage(f'ALS162 error: {s[6:]}')

    def _als_on_tz_changed(self, value):
        self._als_user_utc=value; self._als_tz_user_set=True
        if self._als_last_frame and self._als_last_frame.valid:
            self._als_apply_frame_ui(self._als_last_frame)

    def _als_on_carrier(self, fc):
        self._als_fc=fc; self.als_lbl_fc_v.setText(f'{fc:.3f} Hz')

    def _als_on_level(self, db):
        _DB_LOW,_DB_HIGH=-45.0,-10.0
        pct=int(max(0,min(100,(db-(-60.0))/55.0*100)))
        self.als_bar_level.setValue(pct); self.als_lbl_db.setText(f'{db:+.1f} dB')
        color=('red' if db<_DB_LOW else 'yellow' if db>_DB_HIGH else 'green')
        self.als_bar_level.setStyleSheet(self._als_bar_css(color))

    def _als_on_spectrum(self, data):
        self.als_spectrum.update_data(data['freqs'],data['amps'],data['carrier'])
        snr=data.get('snr_db',0.0); clip=data.get('clip_pct',0.0); top5=data.get('top5',[])
        snr_ok=snr>=20.0
        self.als_lbl_snr_v.setText(f'{snr:+.1f} dB  {"✓" if snr_ok else "⚠"}')
        self.als_lbl_snr_v.setStyleSheet('' if snr_ok else 'color:#c00;')
        clip_ok=clip<1.0
        self.als_lbl_clip_v.setText(f'{clip:.1f}%  {"✓" if clip_ok else "⚠"}')
        self.als_lbl_clip_v.setStyleSheet('' if clip_ok else 'color:#c80;')
        if top5:
            self.als_lbl_peaks_v.setText('   '.join(f'#{i+1} {f:.1f}Hz {p:.0f}%' for i,(f,p) in enumerate(top5[:4])))
        else: self.als_lbl_peaks_v.setText(self.t('als_sig_none'))
        db_txt=self.als_lbl_db.text(); db=float(db_txt.split()[0]) if db_txt!='—' else -99
        _DB_LOW,_DB_HIGH=-45.0,-10.0
        if db<_DB_LOW:
            tip=self.t('als_tip_low')+(('\n'+self.t('als_tip_snr_w')) if snr<15 else '')
        elif db>_DB_HIGH:
            tip=self.t('als_tip_high')+(('\n'+self.t('als_tip_snr_w')) if snr<15 else '')
        elif snr<15: tip=self.t('als_tip_snr_pri')
        else: tip=self.t('als_tip_ok')
        if clip>=1.0: tip+='\n'+self.t('als_tip_clip_w')
        self.als_lbl_tip.setText(tip)

    def _als_on_frame(self, frame):
        import datetime as _dt
        ts=_dt.datetime.now().strftime('%H:%M:%S')
        self._als_stat_total+=1
        if not frame.valid:
            self._als_stat_invalid+=1; self._als_update_stats()
            self.als_log.append(f"[{ts}]  {self.t('als_invalid')}: {frame.error}")
            self.als_log.verticalScrollBar().setValue(self.als_log.verticalScrollBar().maximum())
            return
        self._als_stat_valid+=1; self._als_stat_bits+=59
        self._als_last_frame_ts=time.monotonic(); self._als_update_stats()
        self._als_last_frame=frame

        # Tiempo transcurrido desde que el decoder emitio el frame.
        # Usamos time.monotonic() — independiente del reloj de pared (que puede
        # estar equivocado). Esto nos da los segundos de latencia de audio+señal.
        _emit_mono = getattr(frame, '_emit_mono', time.monotonic())
        _elapsed_at_recv = time.monotonic() - _emit_mono   # s desde emisión

        # El frame ALS162 codifica el minuto siguiente (igual que DCF77).
        # Esperamos al próximo limite de segundo solo si estamos en el segundo 59;
        # si ya cruzamos el minuto, aplicamos enseguida.
        _now = _dt.datetime.now()
        if _now.second == 59:
            _frac = _now.microsecond / 1_000_000
            _delay_ms = int((1.0 - _frac) * 1000)
            _delay_ms = max(20, min(980, _delay_ms))
        else:
            _delay_ms = 20

        # Preparar datos del log (con la hora que mostrara el frame)
        fr_dt=_dt.datetime(frame.year,frame.month,frame.day,frame.hour,frame.minute)
        utc_dt=fr_dt-_dt.timedelta(hours=frame.utc_offset())
        disp_dt=utc_dt+_dt.timedelta(hours=self._als_user_utc)
        sign='+' if self._als_user_utc>=0 else ''
        tz=f'UTC{sign}{self._als_user_utc}'
        fc_tag=f'  {self._als_fc:.1f}Hz' if self._als_fc else ''
        do_sync=self.als_chk_settime.isChecked()
        extra_h=self._als_user_utc-frame.utc_offset()

        def _apply(f=frame, disp=disp_dt, tz_s=tz, fc=fc_tag, sync=do_sync, eh=extra_h,
                   log_ts=ts, mono0=_emit_mono):
            # ── Sincronizacion del SO ─────────────────────────────────────────
            synced=False
            if sync:
                try:
                    _frame_local=datetime.datetime(f.year,f.month,f.day,f.hour,f.minute,0)
                    _user_local=_frame_local+datetime.timedelta(hours=eh)
                    # Elapsed total desde que el decoder emitio el frame hasta ahora
                    # (monotonic → no depende del reloj de pared, correcto incluso
                    # si el PC lleva N segundos de retraso).
                    _total_elapsed = time.monotonic() - mono0
                    # Solo corregimos si el elapsed es razonable (< 30 s)
                    if 0.0 < _total_elapsed < 30.0:
                        _user_local += datetime.timedelta(seconds=_total_elapsed)
                    if not set_local_time(_user_local):
                        raise RuntimeError('set_local_time failed')
                    synced=True
                    self.statusBar().showMessage(self.t('als_set_time_ok'))
                except (PermissionError,RuntimeError):
                    self.als_log.append(
                        f'<span style="color:red">[{log_ts}] {self.t("als_err_admin")}</span>')
            # ── Actualizacion de pantalla ─────────────────────────────────────
            self._als_apply_frame_ui(f)
            # ── Entrada en el log ─────────────────────────────────────────────
            sync_tag=f'  {self.t("als_log_synced")}' if synced else ''
            self.als_log.append(
                f"[{log_ts}]  {disp.hour:02d}:{disp.minute:02d} {tz_s}"
                f"  {disp.day:02d}/{disp.month:02d}/{disp.year}{fc}{sync_tag}")
            self.als_log.verticalScrollBar().setValue(
                self.als_log.verticalScrollBar().maximum())

        QTimer.singleShot(_delay_ms, _apply)

    def _als_apply_frame_ui(self, frame):
        import datetime as _dt
        if not self._als_tz_user_set:
            self._als_user_utc=frame.utc_offset()
            self.als_spin_tz.blockSignals(True); self.als_spin_tz.setValue(self._als_user_utc)
            self.als_spin_tz.blockSignals(False)
        fr_dt=_dt.datetime(frame.year,frame.month,frame.day,frame.hour,frame.minute)
        utc_dt=fr_dt-_dt.timedelta(hours=frame.utc_offset())
        disp_dt=utc_dt+_dt.timedelta(hours=self._als_user_utc)
        sign='+' if self._als_user_utc>=0 else ''
        self.als_lbl_time.setText(f"{disp_dt.hour:02d}:{disp_dt.minute:02d}")
        self.als_lbl_tz.setText(f'UTC{sign}{self._als_user_utc}')
        dow=disp_dt.weekday()+1
        self.als_lbl_date.setText(
            f"{self.t('als_DOW')[dow]}, {disp_dt.day:02d} "
            f"{self.t('als_MON')[disp_dt.month]} {disp_dt.year}")
        self._als_update_holiday_labels(frame)
        ann=[]
        if getattr(frame,'dst_change',False): ann.append(self.t('als_dst'))
        if getattr(frame,'leap_second',False): ann.append(self.t('als_leap'))
        self.als_lbl_ann.setText('  '.join(ann))

    # ── ALS162: estadisticas ──────────────────────────────────────────────────
    def _als_reset_stats(self):
        self._als_stat_total=0; self._als_stat_valid=0
        self._als_stat_invalid=0; self._als_stat_bits=0
        self._als_last_frame_ts=None; self._als_last_frame=None
        self._als_update_stats()

    def _als_update_stats(self):
        if not hasattr(self,'als_st_fr_v'): return
        self.als_st_fr_v.setText(str(self._als_stat_total))
        self.als_st_ok_v.setText(str(self._als_stat_valid))
        self.als_st_nk_v.setText(str(self._als_stat_invalid))
        self.als_st_bt_v.setText(str(self._als_stat_bits))

    def _als_tick_last(self):
        if not (HAS_PYAUDIO and HAS_DECODER): return
        if not (self._als_thread and self._als_thread.isRunning()): return
        if self._als_last_frame_ts is None: return
        elapsed=int(time.monotonic()-self._als_last_frame_ts)
        self.als_lbl_last_v.setText(self.t('als_stats_ago').format(n=elapsed))

    # ── Cierre ────────────────────────────────────────────────────────────────
    def closeEvent(self, event):
        if self._thread and self._thread.isRunning():
            self._thread.stop(); self._thread.wait(2000)
        if self._als_thread and self._als_thread.isRunning():
            self._als_thread.stop(); self._als_thread.wait(2000)
        if hasattr(self,'_tray'): self._tray.hide()
        event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setApplicationName('ALS162 GPS Sync')

    # -- Icono de aplicacion (barra de titulo + barra de tareas) -------------
    _ico_path = _resource_path(os.path.join('assets', 'logo.ico'))
    _png_path = _resource_path(os.path.join('assets', 'logo.png'))
    _app_icon = QIcon(_ico_path) if os.path.exists(_ico_path) else QIcon(_png_path)
    if not _app_icon.isNull():
        app.setWindowIcon(_app_icon)

    win = MainWindow()
    win.show()

    try:
        import pyi_splash
        pyi_splash.close()
    except ImportError:
        pass

    sys.exit(app.exec_())
