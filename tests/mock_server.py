#!/usr/bin/env python3
"""
Mock server para benchmark — replica server.py de berkl3r SIN ViGEmBus.

Versión Fase 1: acepta payloads binarios, sin batching de joysticks,
throttle reducido, ping_interval 25s. Mantiene todo lo demás idéntico
al server.py real para que las mediciones sean comparables.

Uso:
    python3 tests/mock_server.py
"""

import os
import sys
import threading
import time
import struct

from flask import Flask, request
from flask_socketio import SocketIO, emit

# ── Mock de vgamepad (no toca driver, solo registra) ────────────────────
class MockGamepad:
    """Stub de VX360Gamepad. Acepta todas las llamadas, no hace nada."""
    def __init__(self):
        self.last_update = time.monotonic()
        self.updates = 0

    def press_button(self, button): pass
    def release_button(self, button): pass
    def left_joystick(self, x_value, y_value): pass
    def right_joystick(self, x_value, y_value): pass
    def left_trigger(self, value): pass
    def right_trigger(self, value): pass
    def reset(self): pass
    def update(self):
        self.last_update = time.monotonic()
        self.updates += 1


class MockVgModule:
    VX360Gamepad = MockGamepad

import types
sys.modules['vgamepad'] = MockVgModule()


# ── App setup (Fase 1: ping_interval 25s) ─────────────────────────────────
app = Flask(__name__)
app.config['SECRET_KEY'] = 'mgp-secret-key-2025'
socketio = SocketIO(
    app,
    cors_allowed_origins='*',
    async_mode='threading',
    ping_timeout=10,
    ping_interval=25,  # Fase 1
)

# ── Multi-gamepad state ─────────────────────────────────────────────────
MAX_PLAYERS = 4
slot_to_sid = {i: None for i in range(1, MAX_PLAYERS + 1)}
sid_to_slot = {}
sid_to_gamepad = {}
_rejected_sids = set()
_last_joy_time_map = {}
_last_trigger_time_map = {}
_last_button_time_map = {}

# ── Batching state (Fase 1: legado, no se usa) ───────────────────────────
_dirty = {}
_dirty_lock = threading.Lock()
_BATCH_INTERVAL = 0.008

# ── Throttle constants (Fase 1: reducidos) ───────────────────────────────
_JOY_MIN_INTERVAL = 0.003
_BTN_MIN_INTERVAL = 0.005
_TRIG_MIN_INTERVAL = 0.005

# ── Mock button maps ─────────────────────────────────────────────────────
BUTTON_MAP = {f'BTN_{i}': i for i in range(16)}
_BTN_BIN_MAP = {i: f'BTN_{i}' for i in range(16)}

# ── Parsers (idénticos a server.py Fase 1) ───────────────────────────────

def _parse_joystick(data):
    if isinstance(data, (bytes, bytearray, memoryview)):
        if len(data) < 5:
            return None
        side_byte, x_raw, y_raw = struct.unpack_from('<Bhh', bytes(data[:5]))
        side = 'left' if side_byte == 0 else 'right'
        return side, x_raw / 32767.0, y_raw / 32767.0
    if isinstance(data, dict):
        side = str(data.get('side', 'left'))
        x = max(-1.0, min(1.0, float(data.get('x', 0))))
        y = max(-1.0, min(1.0, float(data.get('y', 0))))
        return side, x, y
    return None


def _parse_trigger(data):
    if isinstance(data, (bytes, bytearray, memoryview)):
        if len(data) < 2:
            return None
        side_byte, value = struct.unpack_from('<BB', bytes(data[:2]))
        side = 'left' if side_byte == 0 else 'right'
        return side, value / 255.0
    if isinstance(data, dict):
        side = str(data.get('side', 'left'))
        value = max(0.0, min(1.0, float(data.get('value', 0))))
        return side, value
    return None


def _parse_button(data):
    if isinstance(data, (bytes, bytearray, memoryview)):
        if len(data) < 2:
            return None
        btn_id, pressed = struct.unpack_from('<BB', bytes(data[:2]))
        name = _BTN_BIN_MAP.get(btn_id)
        if name is None:
            return None
        return name, bool(pressed)
    if isinstance(data, dict):
        name = str(data.get('name', '')).upper()
        pressed = bool(data.get('pressed', False))
        return name, pressed
    return None


# ── Funciones helper ────────────────────────────────────────────────────

def _free_slot():
    for slot in range(1, MAX_PLAYERS + 1):
        if slot_to_sid[slot] is None:
            return slot
    return None


def _create_gamepad_for(sid):
    slot = _free_slot()
    if slot is None:
        return None
    gp = MockGamepad()
    sid_to_gamepad[sid] = gp
    sid_to_slot[sid] = slot
    slot_to_sid[slot] = sid
    return slot


def _release_gamepad_for(sid):
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
        _last_joy_time_map.pop(sid, None)
        _last_trigger_time_map.pop(sid, None)
        _last_button_time_map.pop(sid, None)
        with _dirty_lock:
            _dirty.pop(sid, None)


# ── Eventos Socket.IO (Fase 1) ──────────────────────────────────────────

@socketio.on('connect')
def on_connect():
    sid = request.sid
    slot = _create_gamepad_for(sid)
    if slot is None:
        _rejected_sids.add(sid)
        emit('room_full', {'max': MAX_PLAYERS})
        return False
    emit('assigned_player', {'player': slot, 'max': MAX_PLAYERS})


@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    if sid in _rejected_sids:
        _rejected_sids.discard(sid)
        return
    _release_gamepad_for(sid)


@socketio.on('button')
def on_button(data):
    sid = request.sid
    gamepad = sid_to_gamepad.get(sid)
    if not gamepad:
        return

    parsed = _parse_button(data)
    if parsed is None:
        return
    name, pressed = parsed

    btn = BUTTON_MAP.get(name)
    if btn is None:
        return

    if pressed:
        now = time.monotonic()
        btn_times = _last_button_time_map.setdefault(sid, {})
        if now - btn_times.get(name, 0.0) < _BTN_MIN_INTERVAL:
            return
        btn_times[name] = now
    else:
        btn_times = _last_button_time_map.get(sid)
        if btn_times is not None:
            btn_times[name] = 0.0

    try:
        if pressed:
            gamepad.press_button(button=btn)
        else:
            gamepad.release_button(button=btn)
        gamepad.update()
    except Exception:
        pass


@socketio.on('joystick')
def on_joystick(data):
    """Fase 1: sin batching, flush inmediato."""
    sid = request.sid
    gamepad = sid_to_gamepad.get(sid)
    if not gamepad:
        return

    parsed = _parse_joystick(data)
    if parsed is None:
        return
    side, x, y = parsed

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
        # Fase 1: flush inmediato (sin batching)
        gamepad.update()
    except Exception:
        pass


@socketio.on('trigger')
def on_trigger(data):
    sid = request.sid
    gamepad = sid_to_gamepad.get(sid)
    if not gamepad:
        return

    parsed = _parse_trigger(data)
    if parsed is None:
        return
    side, value = parsed

    byte_val = int(value * 255)

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
        gamepad.update()
    except Exception:
        pass


# ── Health check ─────────────────────────────────────────────────────────
@app.route('/health')
def health():
    return {'status': 'ok', 'players': sum(1 for s in slot_to_sid.values() if s is not None)}


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"[mock_server] arrancando en 0.0.0.0:{port}")
    print(f"[mock_server] FASE 1: binario OK, sin batching de joystick, throttle 3-5ms, ping 25s")
    socketio.run(app, host='0.0.0.0', port=port, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)
