# -*- coding: utf-8 -*-
"""
Mobile Gamepad Server
=====================
Servidor que crea un control virtual de Xbox 360 en Windows
y lo controla desde la app web del celular via WebSockets.

Requisitos: pip install -r requirements.txt
Uso:        python server.py
"""

import os
import sys
import signal
import socket
import subprocess
import time
import urllib.request


def _base_path():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _base_path()

VIGEMBUS_VERSION = "1.22.0"
VIGEMBUS_URL = f"https://github.com/nefarius/ViGEmBus/releases/download/v{VIGEMBUS_VERSION}/ViGEmBus_{VIGEMBUS_VERSION}_x64_x86_arm64.exe"


def is_vigembus_installed():
    """Verifica si el driver ViGEmBus esta instalado consultando el servicio de Windows."""
    try:
        result = subprocess.run(
            ['sc', 'query', 'ViGEmBus'],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0 and ('RUNNING' in result.stdout or 'STOPPED' in result.stdout)
    except Exception:
        return False


def install_vigembus():
    """Ejecuta el instalador de ViGEmBus (o lo descarga si no existe)."""
    print("\n" + "=" * 54)
    print("  INSTALACIÓN DEL DRIVER VIGEMBUS (XBOX 360 VIRTUAL)")
    print("=" * 54)
    print("[*] ViGEmBus no está instalado en este sistema.")
    print("    Se requiere este driver de Windows para emular el control.")

    exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else BASE_DIR

    possible_paths = [
        os.path.join(exe_dir, "ViGEmBus_Setup.exe"),
        os.path.join(BASE_DIR, "ViGEmBus_Setup.exe"),
        os.path.join(exe_dir, "_internal", "ViGEmBus_Setup.exe"),
        os.path.join(BASE_DIR, "vgamepad", "win", "vigem", "install", "x64", "ViGEmBusSetup_x64.msi")
    ]

    installer_path = None
    for p in possible_paths:
        if os.path.exists(p):
            installer_path = p
            print(f"[*] Usando instalador local: {os.path.basename(installer_path)}")
            break

    is_temp_download = False
    if not installer_path:
        installer_path = os.path.join(exe_dir, "ViGEmBus_Setup.exe")
        try:
            print(f"[*] Descargando instalador desde:\n    {VIGEMBUS_URL}")
            urllib.request.urlretrieve(VIGEMBUS_URL, installer_path)
            print("[OK] Descargado correctamente")
            is_temp_download = True
        except Exception as e:
            print(f"\n[ERROR] No se pudo descargar automáticamente: {e}")
            print(f"Por favor descárgalo e instálalo manualmente desde:\n{VIGEMBUS_URL}")
            return False

    print("\n[*] Abriendo el instalador de ViGEmBus...")
    print("    -> Por favor completa la instalacion en la ventana que aparecera.")
    try:
        if installer_path.endswith('.msi'):
            result = subprocess.run(['msiexec', '/i', installer_path], timeout=300)
        else:
            result = subprocess.run([installer_path], timeout=300)

        if result.returncode == 0:
            print("[OK] Instalador completado.")
        else:
            print(f"[WARN] El instalador finalizó con código: {result.returncode}")
    except subprocess.TimeoutExpired:
        print("[WARN] El proceso de instalación tardó demasiado.")
    except Exception as e:
        print(f"[ERROR] Error al ejecutar el instalador: {e}")
    finally:
        if is_temp_download and os.path.exists(installer_path):
            try:
                os.remove(installer_path)
            except Exception:
                pass

    if is_vigembus_installed():
        print("[OK] ¡Driver ViGEmBus detectado y listo!\n")
        return True
    else:
        print("\n[WARN] ViGEmBus aún no se detecta activo en el sistema.")
        print("Si acabas de instalarlo, puede que necesites reiniciar el equipo o el servidor.")
        return False


import threading

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

try:
    import qrcode
    HAS_QR = True
except ImportError:
    HAS_QR = False


# ── App setup ─────────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'), static_folder=os.path.join(BASE_DIR, 'static'))
app.config['SECRET_KEY'] = 'mgp-secret-key-2025'
socketio = SocketIO(
    app,
    cors_allowed_origins='*',
    async_mode='threading',
    ping_timeout=10,
    ping_interval=5,
)

vg = None

# ── Multi-gamepad state ───────────────────────────────────────────────────────
MAX_PLAYERS   = 4
# slot_to_sid[slot] = sid | None   (slots are 1-indexed: 1..4)
slot_to_sid   = {i: None for i in range(1, MAX_PLAYERS + 1)}
# sid_to_slot[sid] = slot number
sid_to_slot   = {}
# sid_to_gamepad[sid] = VX360Gamepad instance
sid_to_gamepad = {}
# sids that were rejected because the room was full — used to suppress
# misleading "desconectado" logs in on_disconnect.
_rejected_sids = set()
# sid -> { 'left': float, 'right': float }  joystick throttle timestamps
_last_joy_time_map = {}
# sid -> { 'left': float, 'right': float }  trigger throttle timestamps
_last_trigger_time_map = {}
# sid -> { btn_name: float }  per-button throttle timestamp (cada botón independiente)
_last_button_time_map = {}

BUTTON_MAP = {}

# ── Batching state ────────────────────────────────────────────────────────────
# sid -> bool  whether this gamepad has pending changes to flush
_dirty = {}
_dirty_lock = threading.Lock()
_BATCH_INTERVAL = 0.008  # 8ms = ~125 flushes/sec (~120fps cap)


def init_gamepad():
    """Verifica el driver y carga el módulo vgamepad (no crea instancias todavía)."""
    global vg, BUTTON_MAP
    print("[*] Verificando driver Virtual Xbox 360...")
    if not is_vigembus_installed():
        if not install_vigembus():
            print("\n[!] ViGEmBus es indispensable para emular el control de Xbox.")
            print(f"    Puedes instalarlo manualmente desde:\n    {VIGEMBUS_URL}")
            input("\nPresiona Enter para salir...")
            sys.exit(1)

    try:
        import vgamepad as _vg
        vg = _vg
        BUTTON_MAP = {
            'A':          vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
            'B':          vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
            'X':          vg.XUSB_GAMEPAD_X if hasattr(vg, 'XUSB_GAMEPAD_X') else vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
            'Y':          vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
            'LB':         vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
            'RB':         vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
            'START':      vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
            'SELECT':     vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
            'GUIDE':      vg.XUSB_BUTTON.XUSB_GAMEPAD_GUIDE,
            'LS':         vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
            'RS':         vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
            'DPAD_UP':    vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
            'DPAD_DOWN':  vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
            'DPAD_LEFT':  vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
            'DPAD_RIGHT': vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
        }
        print("[OK] Módulo vgamepad cargado — listo para crear mandos virtuales")
    except Exception as e:
        print(f"\n[ERROR] No se pudo cargar vgamepad: {e}")
        print("Asegúrate de haber completado la instalación del driver ViGEmBus.")
        input("\nPresiona Enter para salir...")
        sys.exit(1)


def _free_slot():
    """Devuelve el primer slot libre (1-4) o None si todos están ocupados."""
    for slot in range(1, MAX_PLAYERS + 1):
        if slot_to_sid[slot] is None:
            return slot
    return None


def _mark_dirty(sid):
    """Marca un gamepad como teniendo cambios pendientes para flush."""
    with _dirty_lock:
        _dirty[sid] = True


def _flush_gamepad(sid):
    """Envía el reporte acumulado al driver para un gamepad específico."""
    gp = sid_to_gamepad.get(sid)
    if gp:
        try:
            gp.update()
        except Exception:
            pass


def _flush_worker():
    """Background thread que hace flush de todos los gamepads sucios cada _BATCH_INTERVAL."""
    while True:
        time.sleep(_BATCH_INTERVAL)
        with _dirty_lock:
            dirty_sids = list(_dirty.keys())
            _dirty.clear()
        for sid in dirty_sids:
            _flush_gamepad(sid)


_flush_thread = threading.Thread(target=_flush_worker, daemon=True)
_flush_thread.start()


def _create_gamepad_for(sid):
    """Crea un VX360Gamepad para el sid dado y lo registra."""
    slot = _free_slot()
    if slot is None:
        return None
    gp = vg.VX360Gamepad()
    sid_to_gamepad[sid] = gp
    sid_to_slot[sid]    = slot
    slot_to_sid[slot]   = sid
    print(f"[+] Mando virtual creado → Jugador {slot} (sid={sid[:8]}...)")
    return slot


def _release_gamepad_for(sid):
    """Resetea y libera el gamepad del sid dado."""
    gp = sid_to_gamepad.pop(sid, None)
    if gp:
        try:
            gp.reset()
            gp.update()
        except Exception:
            pass
    slot = sid_to_slot.pop(sid, None)
    if slot:
        slot_to_sid[slot] = None
        # Liberar throttle maps de este sid
        _last_joy_time_map.pop(sid, None)
        _last_trigger_time_map.pop(sid, None)
        _last_button_time_map.pop(sid, None)
        with _dirty_lock:
            _dirty.pop(sid, None)
        print(f"[-] Mando virtual liberado ← Jugador {slot} (sid={sid[:8]}...)")


def reset_all_gamepads():
    """Resetea todos los mandos activos (usado al cerrar el servidor)."""
    for gp in list(sid_to_gamepad.values()):
        try:
            gp.reset()
            gp.update()
        except Exception as e:
            print(f"[WARN] Error al resetear gamepad: {e}")
    with _dirty_lock:
        _dirty.clear()


def get_local_ip() -> str:
    """Obtiene la IP local del PC en la red Wi-Fi."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def ensure_static_assets():
    """Descarga nipple.js y socket.io.min.js si no existen en la carpeta static/."""
    static_dir = os.path.join(BASE_DIR, 'static')
    if getattr(sys, 'frozen', False):
        static_dir = os.path.join(os.path.dirname(sys.executable), 'static')
    os.makedirs(static_dir, exist_ok=True)
    
    files = {
        'nipplejs.min.js': 'https://cdnjs.cloudflare.com/ajax/libs/nipplejs/0.10.1/nipplejs.min.js',
        'socket.io.min.js': 'https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.min.js'
    }
    
    for filename, url in files.items():
        file_path = os.path.join(static_dir, filename)
        if not os.path.exists(file_path):
            print(f"[*] Descargando {filename}...")
            try:
                urllib.request.urlretrieve(url, file_path)
                print(f"[OK] {filename} descargado correctamente")
            except Exception as e:
                print(f"[WARN] No se pudo descargar {filename}: {e}")


def print_banner(url: str):
    sep = '=' * 54
    print(f'\n{sep}')
    print('   MOBILE GAMEPAD SERVER')
    print(sep)
    print(f'  Abre esta URL en tu celular (misma red Wi-Fi):')
    print(f'\n     >>  {url}\n')
    if HAS_QR:
        try:
            import io
            buf = io.StringIO()
            qr = qrcode.QRCode(border=2)
            qr.add_data(url)
            qr.make(fit=True)
            qr.print_ascii(invert=True, out=buf)
            qr_text = buf.getvalue()
            for line in qr_text.splitlines():
                try:
                    print(line)
                except UnicodeEncodeError:
                    pass
        except Exception:
            pass
    print(f'\n  Presiona  Ctrl + C  para detener el servidor')
    print(f'{sep}\n')


# ── Flask routes ──────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/pc')
def pc_gamepad():
    """Página del Modo PC: permite usar el gamepad con el teclado del PC."""
    return render_template('pc_gamepad.html')


# ── Socket.IO events ──────────────────────────────────────────────────────────
@socketio.on('connect')
def on_connect():
    sid       = request.sid
    client_ip = request.remote_addr or '?'

    slot = _create_gamepad_for(sid)
    if slot is None:
        print(f'[!] Sala llena — rechazando conexión [{client_ip}]')
        _rejected_sids.add(sid)
        emit('room_full', {'max': MAX_PLAYERS})
        return False

    active = sum(1 for s in slot_to_sid.values() if s is not None)
    print(f'[+] Celular conectado  [{client_ip}]  → Jugador {slot}  ({active}/{MAX_PLAYERS} slots)')
    emit('assigned_player', {'player': slot, 'max': MAX_PLAYERS})


@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    if sid in _rejected_sids:
        _rejected_sids.discard(sid)
        return
    _release_gamepad_for(sid)
    active = sum(1 for s in slot_to_sid.values() if s is not None)
    print(f'[-] Celular desconectado  ({active}/{MAX_PLAYERS} slots activos)')


# ── Throttle constants ────────────────────────────────────────────────────────
_JOY_MIN_INTERVAL   = 0.005   # 5ms between joystick updates per side per player
_BTN_MIN_INTERVAL   = 0.008   # 8ms between button updates per player (shared)
_TRIG_MIN_INTERVAL  = 0.008   # 8ms between trigger updates per side per player


@socketio.on('button')
def on_button(data):
    """Recibe: { name: 'A', pressed: true/false }
    Botones: flush INMEDIATO (sin batching) para latencia 0ms en eventos críticos.
    Throttle por botón individual (no compartido) para no perder inputs rápidos
    en juegos de pelea donde se presionan 2-3 botones en <16ms.
    """
    sid     = request.sid
    gamepad = sid_to_gamepad.get(sid)
    if not gamepad:
        return
    name    = str(data.get('name', '')).upper()
    pressed = bool(data.get('pressed', False))
    btn     = BUTTON_MAP.get(name)
    if btn is None:
        return

    # Throttle per-button: cada botón tiene su propio timestamp independiente.
    # - press: throttle normal (anti-spam)
    # - release: SIEMPRE pasa y resetea el timestamp del botón → garantiza que
    #   tapping rítmico (release + press rápido) nunca pierda el siguiente press.
    # Esto resuelve el bug donde tras un release el primer press del mismo botón
    # se bloqueaba por 8ms — perceptible en juegos de ritmo/lucha.
    if pressed:
        now = time.monotonic()
        btn_times = _last_button_time_map.setdefault(sid, {})
        if now - btn_times.get(name, 0.0) < _BTN_MIN_INTERVAL:
            return
        btn_times[name] = now
    else:
        # Release: reset timestamp para que el próximo press de ESE botón
        # pase inmediatamente sin tener que esperar el cooldown.
        btn_times = _last_button_time_map.get(sid)
        if btn_times is not None:
            btn_times[name] = 0.0

    try:
        if pressed:
            gamepad.press_button(button=btn)
        else:
            gamepad.release_button(button=btn)
        # Flush inmediato para botones: latencia crítica de input.
        # No usamos batching aquí porque agregar 8ms a un press de botón
        # es regresión perceptible. El driver maneja cientos de updates/seg OK.
        gamepad.update()
    except Exception as e:
        print(f'[WARN] Button error ({name}): {e}')


@socketio.on('joystick')
def on_joystick(data):
    """Recibe: { side: 'left'/'right', x: float, y: float }  (-1.0 a 1.0)"""
    sid     = request.sid
    gamepad = sid_to_gamepad.get(sid)
    if not gamepad:
        return
    side = str(data.get('side', 'left'))
    x    = max(-1.0, min(1.0, float(data.get('x', 0))))
    y    = max(-1.0, min(1.0, float(data.get('y', 0))))

    joy_times = _last_joy_time_map.setdefault(sid, {'left': 0.0, 'right': 0.0})
    is_zero = (abs(x) < 0.001 and abs(y) < 0.001)

    if not is_zero:
        now = time.monotonic()
        if now - joy_times.get(side, 0) < _JOY_MIN_INTERVAL:
            return
        joy_times[side] = now
    else:
        joy_times[side] = 0.0
        x = 0.0
        y = 0.0

    ix = int(x * 32767)
    iy = int(y * 32767)

    try:
        if side == 'left':
            gamepad.left_joystick(x_value=ix, y_value=iy)
        else:
            gamepad.right_joystick(x_value=ix, y_value=iy)
        _mark_dirty(sid)
    except Exception as e:
        print(f'[WARN] Joystick error [{side}]: {e}')


@socketio.on('trigger')
def on_trigger(data):
    """Recibe: { side: 'left'/'right', value: float }  (0.0 a 1.0)
    Triggers: flush INMEDIATO. El throttle es POR LADO por jugador
    (left y right son independientes — no se interfieren entre sí).
    El reset (value=0) siempre pasa sin throttle para garantizar liberación.
    """
    sid     = request.sid
    gamepad = sid_to_gamepad.get(sid)
    if not gamepad:
        return
    side     = str(data.get('side', 'left'))
    value    = max(0.0, min(1.0, float(data.get('value', 0))))
    byte_val = int(value * 255)

    # Reset (value=0) bypass total: garantizar que el trigger se libere
    # aunque venga muy rápido. Sin esto, throttle puede tragarse el release.
    if byte_val > 0:
        now = time.monotonic()
        trig_times = _last_trigger_time_map.setdefault(sid, {'left': 0.0, 'right': 0.0})
        if now - trig_times.get(side, 0) < _TRIG_MIN_INTERVAL:
            return
        trig_times[side] = now

    try:
        if side == 'left':
            gamepad.left_trigger(value=byte_val)
        else:
            gamepad.right_trigger(value=byte_val)
        # Flush inmediato: triggers son eventos críticos (disparar = respuesta inmediata).
        gamepad.update()
    except Exception as e:
        print(f'[WARN] Trigger error [{side}]: {e}')


# ── Helpers ───────────────────────────────────────────────────────────────────
def signal_handler(sig, frame):
    print('\n[*] Deteniendo servidor...')
    reset_all_gamepads()
    sys.exit(0)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    try:
        signal.signal(signal.SIGINT, signal_handler)
        init_gamepad()
        ensure_static_assets()
        ip   = get_local_ip()
        port = 5000
        print_banner(f'http://{ip}:{port}')
        socketio.run(app, host='0.0.0.0', port=port, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:
        print("\n[*] Servidor detenido.")
    except Exception as e:
        import traceback
        print(f"\n[ERROR CRÍTICO]: {e}")
        traceback.print_exc()
        input("\nPresiona Enter para salir...")
        sys.exit(1)

