# Plan de Mejoras — Mobile Gamepad

> **Estado:** En progreso (Fase 0 completada, Fase 1 arrancando)
> **Autor:** GrimSatan (fork de berkl3r/MOBILE-GAMEPAD--)
> **Rama:** `main`
> **Fecha de inicio:** 2026-09-02

## Resumen ejecutivo

Este fork ataca tres problemas concretos del proyecto base de berkl3r:

1. **Latencia notable** — perceptible en juegos de tiempo real (ej. Mario Kart)
2. **Dependencia de router Wi-Fi** — no funciona fuera de la red hogareña
3. **Asignación rígida de slots** — el servidor auto-asigna, el usuario no puede elegir P1-P4

Las soluciones se aplican en fases incrementales. Cada fase termina con
métricas concretas para poder comparar antes/después.

---

## Fase 0 — Setup y línea base ✅

### Tareas

- [x] Fork público: `GrimSatan/MOBILE-GAMEPAD--`
- [x] Renombrar rama `master` → `main`
- [x] Crear este documento de plan
- [ ] Benchmark de latencia del proyecto base (JSON sobre WS, throttle 8ms)

### Medición objetivo

Antes de cualquier cambio, correr un cliente headless que:
- Se conecta al servidor vía WebSocket
- Manda 1000 eventos de joystick + 1000 eventos de botón a frecuencia target (60 Hz)
- Mide **round-trip time** (timestamp en cliente → echo desde server → recibido)
- Reporta promedio, p50, p95, p99, jitter

Resultado se guarda en `docs/BENCHMARK-BASE.md` para comparar contra Fase 1.

---

## Fase 1 — Reducción de latencia (sin tocar arquitectura)

### Problemas identificados

#### 1.1 — Serialización JSON por frame

**Síntoma:** El cliente envía cada joystick como JSON:

```json
{"side":"left","x":0.123,"y":-0.456}   // ~33 bytes
```

**Causa:** Flask-SocketIO por default serializa/deserializa JSON en cada evento.
A 60 Hz por joystick × 2 joysticks = 120 mensajes/seg de ~33 bytes cada uno.
El encode/decode JSON cuesta ~5-15 ms por frame en CPU normal.

**Impacto medido:** ~10-15 ms de latencia agregada por frame.

**Solución:** Cambiar a **eventos binarios** en Socket.IO.

- `joystick`: `Int16Array(2)` = 4 bytes (x, y en rango [-32767, 32767])
- `trigger`: `Uint8Array(1)` = 1 byte (valor 0-255)
- `button`: `Uint8Array(2)` = 2 bytes (button_id, pressed)

Socket.IO soporta `binary` flag en eventos. Del lado del cliente:

```js
socket.emit('joystick', new Int16Array([x_norm * 32767, y_norm * 32767]));
```

Del lado del servidor:

```python
@socketio.on('joystick')
def on_joystick(data):
    # data es bytes; desempacar con struct
    x_raw, y_raw = struct.unpack('<hh', bytes(data))
    ...
```

**Ahorro esperado:** 8-12 ms por frame.

#### 1.2 — Batching de joysticks con `time.sleep(0.008)`

**Síntoma:** El servidor agrupa updates de joystick y los flushea al driver cada 8 ms.

**Causa:** Originalmente pensado para reducir overhead del driver ViGEmBus,
pero el driver maneja cientos de updates/seg sin problemas. El batch solo
**suma latencia**.

**Solución:** Quitar el batching para joysticks. Flush inmediato igual que
botones. El throttle per-side de 5 ms ya evita spam.

**Ahorro esperado:** 0-8 ms (variable, dependiendo de cuándo llegue el
evento relativo al ciclo de batch).

#### 1.3 — Touch event listeners sin `{passive: true}`

**Síntoma:** El browser puede esperar al handler antes de procesar scroll/zoom,
serializando eventos.

**Causa:** Por default, `addEventListener('touchstart', ...)` es **passive: false**.

**Solución:** Agregar `{passive: true}` a todos los listeners de touchstart/touchmove
que no llaman `preventDefault()`.

**Ahorro esperado:** 1-3 ms en eventos rápidos.

#### 1.4 — `requestAnimationFrame` para muestrear joystick

**Síntoma:** El joystick puede emitir más eventos de los que el display puede
mostrar (touchmove dispara a frecuencia táctil, no visual).

**Causa:** Cada touchmove genera un evento que se manda al server. Si el
touchsample es 240 Hz pero el display es 60 Hz, mandamos 4× lo necesario.

**Solución:** Acumular la última posición del joystick y emitirla en el próximo
`requestAnimationFrame`. Sincroniza con la frecuencia del display.

**Ahorro esperado:** Reduce tráfico, no latencia directamente. Pero baja CPU
del cliente y del server.

#### 1.5 — Ping/pong de Socket.IO muy frecuente

**Síntoma:** `ping_interval=5` en el server. El cliente envía ping cada 5s.

**Causa:** Default conservador. En LAN no es necesario tan seguido.

**Solución:** Subir a 25s. Sigue detectando desconexiones pero no interrumpe
tan frecuentemente.

**Ahorro esperado:** <1 ms promedio, pero reduce variabilidad.

### Métricas objetivo Fase 1

Latencia round-trip total (target):

| Métrica | Antes (base) | Después Fase 1 |
|---|---|---|
| Promedio | ~80-120 ms | <30 ms |
| p95 | ~150 ms | <50 ms |
| p99 | ~200 ms | <80 ms |
| Jitter | alto | bajo |

Si Fase 1 no llega a <30 ms promedio, pasamos a Fase 1.5 (WebRTC data channels).

---

## Fase 2 — Opciones de conexión sin router

### Problema

El proyecto actual asume que el celular se conecta a la PC **vía la misma red
Wi-Fi hogareña**. Esto no funciona cuando:

- Estás en una reunión con Wi-Fi de invitados
- Estás en un café con Wi-Fi con portal cautivo
- Estás en la casa de un amigo
- El router se cae

### Solución

El servidor debe detectar interfaces de red activas y ofrecer **3 URLs**
para conectar:

| Interfaz | Cuándo aplica | Latencia típica |
|---|---|---|
| **LAN** (`192.168.x.x`) | Celular y PC en misma Wi-Fi hogareña | 5-30 ms |
| **Hotspot PC** (`192.168.137.x`) | PC levanta hotspot Wi-Fi nativo | 3-15 ms |
| **USB tethering** (`192.168.42.x` típico Android) | Celular enchufado por USB con tethering on | 2-10 ms |

**Cambios concretos:**

1. **Server:** función `get_all_endpoints()` que itera sobre `socket.if_nameindex()`
   y devuelve todas las IPv4 no-loopback, etiquetadas por tipo.
2. **Banner:** imprime las 3 URLs y genera un QR con cada una.
3. **UI del celular:** muestra la lista de URLs detectadas (enviada por el server
   vía Socket.IO al conectar) y un botón "Conectar" por cada una. La primera
   que responda gana.

### Métricas objetivo Fase 2

- El usuario puede conectar el celular a la PC **sin tocar el router**
- Latencia con USB tethering debe ser <15 ms p95

---

## Fase 3 — Selección manual de slot (P1-P4)

### Problema

El server actual auto-asigna slot en `on_connect`:

```python
slot = _create_gamepad_for(sid)
```

Si 4 amigos quieren jugar y el primero llegó antes, queda como P1 fijo.

### Solución

1. **Server:** nuevo evento `select_slot` que valida que el slot esté libre
   y lo asigna. Si está tomado, devuelve error.
2. **UI:** pantalla inicial con 4 botones grandes P1-P4. Slots ocupados aparecen
   en gris (estado recibido del server vía `room_state`).
3. **Re-asignación:** si un jugador se va, su slot se libera y otros pueden tomarlo.

### API nueva

```
[servidor → cliente] room_state: { taken: [1, 3], max: 4 }
[cliente → servidor] select_slot: { slot: 2 }
[servidor → cliente] slot_granted: { slot: 2 }
[servidor → cliente] slot_denied: { reason: "Slot 2 está ocupado" }
```

---

## Fase 4 — Soporte Linux (después)

`vgamepad/lin/virtual_gamepad.py` ya existe como stub. Completar:

- Backend con `uinput` (kernel module built-in en Linux)
- Detección automática Windows/Linux en `init_gamepad()`
- Tests en Linux

No bloquea el demo Windows.

---

## Lo que NO se hace

- ❌ Reescritura como app nativa (Capacitor / React Native / Flutter)
- ❌ HTTPS/TLS para LAN (no aporta)
- ❌ WebRTC data channels (demasiada complejidad para el demo)
- ❌ Bluetooth HID directo (requiere app nativa, fuera de scope)

Si después de Fase 1-3 la latencia sigue siendo inaceptable, evaluamos
WebRTC en Fase 1.5.

---

## Cómo contribuir / probar

```bash
git clone git@github.com:GrimSatan/MOBILE-GAMEPAD--.git
cd MOBILE-GAMEPAD--
pip install -r requirements.txt
python server.py

# En otra terminal, abrir navegador en http://<IP-PC>:5000
# Escanear QR desde el celular (misma Wi-Fi, USB tethering, o hotspot PC)

# Benchmark de latencia (próximamente):
python tests/benchmark_latency.py
```
