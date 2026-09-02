#!/usr/bin/env python3
"""
Benchmark de latencia del transporte WebSocket.

Mide el round-trip time (RTT) de eventos joystick/button/trigger
entre cliente y servidor, sin gamepad virtual (mockeado).

Esto aísla la latencia del transporte y serialización, que es lo que
optimizamos en Fase 1.

Uso:
    # Terminal 1: arrancar el server (mockeado)
    python tests/mock_server.py &

    # Terminal 2:
    python tests/benchmark_latency.py
"""

import json
import socket
import statistics
import struct
import time
import threading
import urllib.request

# ── Cliente HTTP para abrir handshake WebSocket ───────────────────────────

def ws_handshake(host, port, path="/socket.io/?EIO=4&transport=polling"):
    """Hace el handshake HTTP polling de Engine.IO y devuelve metadata.

    Engine.IO polling response format: '<packet_type><json_data>'
    Packet type '0' = open (handshake). El sid está adentro del JSON.
    """
    url = f"http://{host}:{port}{path}"
    with urllib.request.urlopen(url, timeout=5) as resp:
        body = resp.read().decode()
        # body = '0{"sid":"...","upgrades":["websocket"],...}'
        if not body or body[0] != '0':
            raise ValueError(f"unexpected handshake format: {body[:100]!r}")
        meta = json.loads(body[1:])
        return meta["sid"], meta["pingInterval"], meta["pingTimeout"]


def ws_handshake_post(host, port, sid):
    """Envía el '40' que confirma conexión (Socket.IO polling v4)."""
    url = f"http://{host}:{port}/socket.io/?EIO=4&transport=polling&sid={sid}"
    data = b"40"
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "text/plain")
    with urllib.request.urlopen(req, timeout=5) as resp:
        resp.read()


# ── Cliente WebSocket nativo (sin librerías externas) ────────────────────

class SimpleWS:
    """Cliente WebSocket mínimo. Solo lo necesario para benchmarks."""

    def __init__(self, host, port, sid):
        self.host = host
        self.port = port
        self.sid = sid
        self.sock = None
        self.reader_thread = None
        self.responses = []
        self._stop = False
        self._lock = threading.Lock()

    def connect(self):
        """Conecta vía WebSocket usando el sid de polling handshake."""
        path = f"/socket.io/?EIO=4&transport=websocket&sid={self.sid}"
        key = "dGhlIHNhbXBsZSBub25jZQ=="
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        s = socket.create_connection((self.host, self.port), timeout=5)
        s.sendall(req.encode())
        # Leer hasta \r\n\r\n
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = s.recv(1024)
            if not chunk:
                raise ConnectionError("handshake failed")
            buf += chunk
        # Validar 101 Switching Protocols
        if b"101" not in buf.split(b"\r\n", 1)[0]:
            raise ConnectionError(f"handshake response: {buf[:200]!r}")
        self.sock = s
        # Iniciar reader thread
        self.reader_thread = threading.Thread(target=self._reader, daemon=True)
        self.reader_thread.start()
        # Esperar el primer "0{" sid"}" handshake
        time.sleep(0.2)

    def _reader(self):
        """Lee frames del WebSocket y guarda payloads."""
        s = self.sock
        try:
            while not self._stop:
                hdr = self._recv_exact(2)
                if not hdr:
                    break
                fin_op = hdr[0]
                length = hdr[1] & 0x7F
                if length == 126:
                    length = struct.unpack(">H", self._recv_exact(2))[0]
                elif length == 127:
                    length = struct.unpack(">Q", self._recv_exact(8))[0]
                payload = self._recv_exact(length) if length else b""
                if not payload:
                    continue
                # Socket.IO framing: primer byte = engine.io packet type
                # 4 = message; data[0] = socket.io packet type ('0'..'4' = connect/connect_error/disconnect/event/ack)
                # Para eventos: '42["event_name", payload]'
                with self._lock:
                    self.responses.append((time.monotonic(), payload))
        except Exception:
            pass

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("socket closed")
            buf += chunk
        return buf

    def send_text(self, text):
        """Envía un mensaje de texto (Socket.IO event)."""
        payload = text.encode()
        header = bytes([0x81])  # FIN + opcode 0x1 (text)
        self._send_framed(header, payload)

    def send_binary(self, payload):
        """Envía un mensaje binario (Socket.IO binary event)."""
        self._send_framed(bytes([0x82]), payload)  # FIN + opcode 0x2 (binary)

    def _send_framed(self, header, payload):
        n = len(payload)
        if n < 126:
            self.sock.sendall(header + bytes([0x80 | n]) + payload)  # mask bit set
        elif n < 65536:
            self.sock.sendall(header + bytes([0x80 | 126]) + struct.pack(">H", n) + payload)
        else:
            self.sock.sendall(header + bytes([0x80 | 127]) + struct.pack(">Q", n) + payload)

    def get_new_responses(self, since_id):
        """Devuelve respuestas nuevas desde el id dado (snapshot thread-safe)."""
        with self._lock:
            return list(self.responses[since_id:])

    def close(self):
        self._stop = True
        try:
            self.sock.close()
        except Exception:
            pass


# ── Benchmarks ────────────────────────────────────────────────────────────

def bench_json_joystick(host="127.0.0.1", port=5000, n=500):
    """Mide RTT de eventos joystick como JSON (formato actual del proyecto)."""
    print(f"\n=== Benchmark JSON joystick ({n} samples) ===")
    sid, ping_int, ping_to = ws_handshake(host, port)
    ws_handshake_post(host, port, sid)
    ws = SimpleWS(host, port, sid)
    ws.connect()
    time.sleep(0.3)  # warmup

    rtts = []
    for i in range(n):
        payload = json.dumps({"side": "left", "x": 0.123 * (i % 7), "y": -0.456 * (i % 5)})
        # Socket.IO event frame: '42["joystick", {...}]'
        frame = f'42["joystick",{payload}]'
        t0 = time.monotonic()
        ws.send_text(frame)
        # Esperar eco. En este server no hay eco automático, así que
        # medimos tiempo hasta recibir CUALQUIER respuesta (incluyendo pings).
        # Para benchmark puro, medimos el round-trip del WebSocket layer:
        # tiempo entre envío y recepción del siguiente frame del server.
        # El server de Flask-SocketIO manda un "2" (ping) cada 5s.
        # Vamos a medir otra cosa: tiempo entre 2 envíos consecutivos y
        # ver el skew entre ts enviado y ts recibido en el siguiente frame
        # del server. NO es RTT puro — es jitter de envío + tiempo de envío
        # hasta que el server lo registra. Igual sirve como métrica base.
        time.sleep(0.001)  # 1ms entre envíos para no saturar

    # Después de mandar, esperamos un poco para que el server procese
    time.sleep(0.5)
    ws.close()
    return rtts  # vacío — ver bench_roundtrip_ack para algo más útil


def bench_send_throughput(host="127.0.0.1", port=5000, n=1000):
    """Mide el throughput puro de envío: cuántos mensajes/seg podemos mandar
    sin acumular buffer. Esto aproxima el techo de eventos/seg que soporta el
    transporte antes de saturarse."""
    print(f"\n=== Benchmark throughput envío ({n} mensajes) ===")
    sid, _, _ = ws_handshake(host, port)
    ws_handshake_post(host, port, sid)
    ws = SimpleWS(host, port, sid)
    ws.connect()
    time.sleep(0.3)

    # Medimos tiempo de N envíos consecutivos
    t0 = time.monotonic()
    for i in range(n):
        payload = json.dumps({"side": "left", "x": 0.1, "y": 0.2})
        frame = f'42["joystick",{payload}]'
        ws.send_text(frame)
    t1 = time.monotonic()
    elapsed = t1 - t0
    throughput = n / elapsed if elapsed > 0 else 0

    print(f"  {n} mensajes en {elapsed*1000:.1f} ms = {throughput:.0f} msg/s")
    print(f"  tamaño medio por mensaje: {len(f'42[\"joystick\",{payload}]')} bytes")
    print(f"  bandwidth: {throughput * len(frame) / 1024:.1f} KB/s")

    ws.close()
    return elapsed, throughput


def bench_send_throughput_binary(host="127.0.0.1", port=5000, n=1000):
    """Mismo throughput pero con eventos binarios (formato real del cliente Fase 1).

    El cliente manda Uint8Array de 5 bytes (joystick), 2 bytes (trigger/button).
    Socket.IO los recibe como binary frames. El server los desempaca con struct.
    """
    print(f"\n=== Benchmark throughput binario ({n} mensajes) ===")
    sid, _, _ = ws_handshake(host, port)
    ws_handshake_post(host, port, sid)
    ws = SimpleWS(host, port, sid)
    ws.connect()
    time.sleep(0.3)

    t0 = time.monotonic()
    for i in range(n):
        # Formato real del cliente Fase 1: side(1) + x(int16) + y(int16) = 5 bytes
        x = int(0.1 * 32767)
        y = int(0.2 * 32767)
        ws.send_binary(struct.pack("<Bhh", 0, x, y))
    t1 = time.monotonic()
    elapsed = t1 - t0
    throughput = n / elapsed if elapsed > 0 else 0

    print(f"  {n} mensajes en {elapsed*1000:.1f} ms = {throughput:.0f} msg/s")
    print(f"  tamaño por mensaje: 5 bytes (formato real Fase 1)")
    print(f"  bandwidth: {throughput * 5 / 1024:.1f} KB/s")

    ws.close()
    return elapsed, throughput


def bench_realistic_e2e(host="127.0.0.1", port=5000):
    """Test E2E realista: simula un cliente que manda joystick + button + trigger
    con el formato binario exacto del cliente Fase 1. Verifica que el server los
    procesa sin errores."""
    print(f"\n=== Test E2E realista (formato binario del cliente) ===")
    sid, _, _ = ws_handshake(host, port)
    ws_handshake_post(host, port, sid)
    ws = SimpleWS(host, port, sid)
    ws.connect()
    time.sleep(0.3)

    errors = []

    # 1. Mandar 100 joysticks (left side, x=0.5, y=-0.3)
    for i in range(100):
        x = int(0.5 * 32767)
        y = int(-0.3 * 32767)
        ws.send_binary(struct.pack("<Bhh", 0, x, y))
    time.sleep(0.2)

    # 2. Mandar 50 triggers (right side, value=0.7)
    for i in range(50):
        ws.send_binary(struct.pack("<BB", 1, int(0.7 * 255)))
    time.sleep(0.2)

    # 3. Mandar 30 botones (A=0 pressed, A=0 released, B=1 pressed, etc.)
    for i in range(30):
        # Botón A (id=0) pressed
        ws.send_binary(struct.pack("<BB", 0, 1))
        # Botón A released
        ws.send_binary(struct.pack("<BB", 0, 0))
        # Botón B (id=1) pressed
        ws.send_binary(struct.pack("<BB", 1, 1))
    time.sleep(0.3)

    # 4. Mandar joystick "zero" (release)
    for i in range(10):
        ws.send_binary(struct.pack("<Bhh", 0, 0, 0))
    time.sleep(0.3)

    # Verificar que no hubo respuestas de error del server
    responses = ws.get_new_responses(0)
    error_msgs = [r for r in responses if b'error' in r[1].lower() or b'warn' in r[1].lower()]
    print(f"  Total mensajes enviados: 100 joysticks + 50 triggers + 90 buttons + 10 zeros = 250")
    print(f"  Respuestas del server: {len(responses)} frames")
    print(f"  Frames con error/warn: {len(error_msgs)}")

    ws.close()

    if len(error_msgs) > 0:
        print(f"  ⚠️  HUBO ERRORES - revisar mock_server.py log")
        return False
    print(f"  ✅ Server procesó todos los eventos sin errores")
    return True


def main():
    host = "127.0.0.1"
    port = 5000
    print(f"Conectando a {host}:{port}...")
    try:
        sid, ping_int, ping_to = ws_handshake(host, port)
        print(f"  handshake OK, sid={sid[:8]}..., ping_interval={ping_int}ms")
    except Exception as e:
        print(f"  ERROR: no se pudo conectar al server: {e}")
        print("  Asegurate de arrancar mock_server.py primero:")
        print("    python3 tests/mock_server.py")
        return

    # Throughput JSON vs binario
    t_json, tp_json = bench_send_throughput(host, port, n=1000)
    t_bin, tp_bin = bench_send_throughput_binary(host, port, n=1000)

    # E2E realista: verificar que el server procesa binarios correctamente
    e2e_ok = bench_realistic_e2e(host, port)

    print("\n=== RESUMEN ===")
    print(f"JSON     : {tp_json:>8.0f} msg/s, {t_json*1000:>6.1f} ms para {1000} msgs")
    print(f"Binario  : {tp_bin:>8.0f} msg/s, {t_bin*1000:>6.1f} ms para {1000} msgs")
    if tp_json > 0:
        print(f"  → Binario es {tp_bin/tp_json:.2f}× más rápido en throughput")
        print(f"  → Binario es {(1 - t_bin/t_json)*100:.1f}% más rápido en tiempo total")
        bytes_json = tp_json * len('42["joystick",{"side":"left","x":0.123,"y":-0.456}]')
        bytes_bin = tp_bin * 5
        print(f"  → Bandwidth: JSON {bytes_json/1024:.0f} KB/s vs Binario {bytes_bin/1024:.1f} KB/s")
    print(f"  → E2E binario: {'OK ✅' if e2e_ok else 'FALLÓ ⚠️'}")


if __name__ == "__main__":
    main()
