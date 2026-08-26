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
            capture_output=True, text=True, timeout=10
        )
        return 'RUNNING' in result.stdout or 'STOPPED' in result.stdout or 'OPEN_SERVICE' not in result.stderr
    except Exception:
        return False


def install_vigembus():
    """Descarga e instala ViGEmBus silenciosamente. Requiere permisos de administrador."""
    print("[*] ViGEmBus no esta instalado. Descargando e instalando...")

    exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else BASE_DIR
    installer_path = os.path.join(exe_dir, "ViGEmBus_Setup.exe")

    try:
        print(f"[*] Descargando desde: {VIGEMBUS_URL}")
        urllib.request.urlretrieve(VIGEMBUS_URL, installer_path)
        print("[OK] Descargado correctamente")
    except Exception as e:
        print(f"[ERROR] No se pudo descargar ViGEmBus: {e}")
        print("   Descargalo manualmente desde:")
        print(f"   {VIGEMBUS_URL}")
        return False

    print("[*] Instalando ViGEmBus (se abrira una ventana de permisos de Windows)...")
    try:
        result = subprocess.run(
            [installer_path],
            timeout=300
        )
        if result.returncode == 0:
            print("[OK] ViGEmBus instalado correctamente")
        else:
            print(f"[WARN] El instalador termino con codigo: {result.returncode}")
            print("   Intenta instalarlo manualmente ejecutando el .exe descargado.")
            return False
    except subprocess.TimeoutExpired:
        print("[WARN] La instalacion tardo demasiado. Verifica manualmente.")
        return False
    except Exception as e:
        print(f"[ERROR] Error durante la instalacion: {e}")
        return False
    finally:
        if os.path.exists(installer_path):
            try:
                os.remove(installer_path)
            except Exception:
                pass

    return is_vigembus_installed()


from flask import Flask, render_template
from flask_socketio import SocketIO, emit

try:
    import vgamepad as vg
except ImportError:
    print("❌ 'vgamepad' no está instalado. Ejecuta: pip install vgamepad")
    input("\nPresiona Enter para salir...")
    sys.exit(1)

try:
    import qrcode
    HAS_QR = True
except ImportError:
    HAS_QR = False


# ── App setup ─────────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'), static_folder=os.path.join(BASE_DIR, 'static'))
app.config['SECRET_KEY'] = 'mgp-secret-key-2025'
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')


# ── Virtual gamepad ───────────────────────────────────────────────────────────
print("[*] Iniciando control virtual Xbox 360...")
if not is_vigembus_installed():
    if not install_vigembus():
        print("   ViGEmBus es necesario para crear el control virtual.")
        print("   Descargalo manualmente desde:")
        print(f"   {VIGEMBUS_URL}")
        input("\nPresiona Enter para salir...")
        sys.exit(1)
try:
    gamepad = vg.VX360Gamepad()
    print("[OK] Control virtual creado correctamente")
except Exception as e:
    print(f"[ERROR] Error al crear el control virtual: {e}")
    print("   Asegurate de que el driver ViGEmBus este instalado y activo.")
    input("\nPresiona Enter para salir...")
    sys.exit(1)

# Mapeo de nombres de botones a constantes de XInput
BUTTON_MAP = {
    'A':          vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
    'B':          vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
    'X':          vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
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


def reset_gamepad():
    """Release all inputs."""
    try:
        gamepad.reset()
        gamepad.update()
    except Exception as e:
        print(f"[WARN] Error al resetear gamepad: {e}")


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
            # Print safely, skipping lines with unencodable chars
            for line in qr_text.splitlines():
                try:
                    print(line)
                except UnicodeEncodeError:
                    pass
        except Exception:
            pass  # QR printing is optional
    print(f'\n  Presiona  Ctrl + C  para detener el servidor')
    print(f'{sep}\n')


# ── Flask routes ──────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')


# ── Socket.IO events ──────────────────────────────────────────────────────────
@socketio.on('connect')
def on_connect():
    client_ip = flask_request_remote_addr()
    print(f'[+] Celular conectado  [{client_ip}]')
    emit('status', {'connected': True})


@socketio.on('disconnect')
def on_disconnect():
    print('[-] Celular desconectado -- reseteando gamepad')
    reset_gamepad()


@socketio.on('button')
def on_button(data):
    """Recibe: { name: 'A', pressed: true/false }"""
    name    = str(data.get('name', '')).upper()
    pressed = bool(data.get('pressed', False))
    btn     = BUTTON_MAP.get(name)
    if btn is None:
        return
    try:
        if pressed:
            gamepad.press_button(button=btn)
        else:
            gamepad.release_button(button=btn)
        gamepad.update()
    except Exception as e:
        print(f'[WARN] Button error ({name}): {e}')


_last_joy_time = {'left': 0.0, 'right': 0.0}
_JOY_MIN_INTERVAL = 0.005  # 5ms throttle for continuous streaming

@socketio.on('joystick')
def on_joystick(data):
    """Recibe: { side: 'left'/'right', x: float, y: float }  (-1.0 a 1.0)"""
    side = str(data.get('side', 'left'))
    x    = max(-1.0, min(1.0, float(data.get('x', 0))))
    y    = max(-1.0, min(1.0, float(data.get('y', 0))))
    
    is_zero = (abs(x) < 0.001 and abs(y) < 0.001)
    
    # Do NOT throttle release/zero events so stick never gets stuck
    if not is_zero:
        now = time.monotonic()
        if now - _last_joy_time.get(side, 0) < _JOY_MIN_INTERVAL:
            return
        _last_joy_time[side] = now
    else:
        _last_joy_time[side] = 0  # reset throttle timer
        x = 0.0
        y = 0.0

    # XInput: positive X is Right, positive Y is Up (+32767)
    ix = int(x * 32767)
    iy = int(y * 32767)
    
    try:
        if side == 'left':
            gamepad.left_joystick(x_value=ix, y_value=iy)
        else:
            gamepad.right_joystick(x_value=ix, y_value=iy)
        gamepad.update()
    except Exception as e:
        print(f'[WARN] Joystick error [{side}]: {e}')


@socketio.on('trigger')
def on_trigger(data):
    """Recibe: { side: 'left'/'right', value: float }  (0.0 a 1.0)"""
    side     = str(data.get('side', 'left'))
    value    = max(0.0, min(1.0, float(data.get('value', 0))))
    byte_val = int(value * 255)
    try:
        if side == 'left':
            gamepad.left_trigger(value=byte_val)
        else:
            gamepad.right_trigger(value=byte_val)
        gamepad.update()
    except Exception as e:
        print(f'[WARN] Trigger error [{side}]: {e}')


# ── Helpers ───────────────────────────────────────────────────────────────────
def flask_request_remote_addr():
    from flask import request
    return request.remote_addr or '?'


def signal_handler(sig, frame):
    print('\n[*] Deteniendo servidor...')
    reset_gamepad()
    sys.exit(0)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    ensure_static_assets()
    ip   = get_local_ip()
    port = 5000
    print_banner(f'http://{ip}:{port}')
    socketio.run(app, host='0.0.0.0', port=port, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)
