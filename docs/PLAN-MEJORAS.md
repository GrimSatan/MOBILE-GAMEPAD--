# Plan de Mejoras — Mobile Gamepad

> **Estado:** Fase 1 implementada y medida (loopback). Pendiente validación en Windows.
> **Autor:** GrimSatan (fork de berkl3r/MOBILE-GAMEPAD--)
> **Rama:** `main`
> **Fecha de inicio:** 2026-09-02
> **Última actualización:** 2026-09-02

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
- [x] Benchmark de latencia del proyecto base (JSON sobre WS, throttle 8ms)
- [x] Mock server para tests sin ViGEmBus (`tests/mock_server.py`)
- [x] Cliente WS nativo para benchmarks (`tests/benchmark_latency.py`)

### Resultado

Ver `docs/BENCHMARK-RESULTS.md` para los números completos.

| Métrica base | Valor |
|---|---|
| Throughput JSON | 227,748 msg/s |
| Tiempo 1000 msgs | 4.4 ms |
| Bandwidth | 11.3 MB/s |
| Ping interval | 5s |

⚠️ Estas son mediciones de **transporte en loopback**, no latencia end-to-end
real. La validación real requiere Windows + juego.

---

## Fase 1 — Reducción de latencia (sin tocar arquitectura) ✅

### Estado: implementada, medida en loopback, pendiente validación Windows

### Problemas identificados y soluciones aplicadas

#### 1.1 — Serialización JSON por frame ✅

**Síntoma:** Cliente envía cada joystick como JSON (~33 bytes). A 60 Hz × 2
joysticks = 120 msg/seg, encode/decode JSON cuesta ~5-15 ms por frame.

**Solución:** Cambiar a eventos binarios en Socket.IO.

- `joystick`: 5 bytes (`<side:1><x:int16><y:int16>`)
- `trigger`: 2 bytes (`<side:1><value:uint8>`)
- `button`: 2 bytes (`<btn_id:1><pressed:uint8>`)

**Implementado en:** `server.py:_parse_joystick/trigger/button`,
`templates/index.html:sendJoystickBin/TriggerBin/ButtonBin`

**Backward-compat:** los parsers aceptan tanto bytes como dict. Rollback
trivial si Fase 1 falla en Windows.

#### 1.2 — Batching de joysticks con `time.sleep(0.008)` ✅

**Síntoma:** Server agrupa updates de joystick y los flushea al driver cada 8 ms.
Eso suma 0-8 ms de latencia por frame.

**Solución:** Eliminado el batching. `gamepad.update()` se llama directamente
después de `gamepad.left_joystick()`. El throttle per-side de 3 ms sigue
evitando spam.

**Implementado en:** `server.py:on_joystick()` — eliminado `_mark_dirty(sid)`
y la espera al flush thread.

#### 1.3 — Touch event listeners ⚠️ NO aplicado

**Razón:** Los handlers actuales usan `{passive: false}` porque llaman
`e.preventDefault()` para evitar scroll/zoom durante el juego. Convertir
a `passive: true` rompería esa prevención. **No hay ganancia posible aquí
sin cambiar el comportamiento de scroll.**

#### 1.4 — `requestAnimationFrame` para muestrear joystick ⏸️ Diferido

**Razón:** Mejora marginal en este contexto. Nipple.js ya emite eventos
throttleados por su propio loop interno. Queda como optimización futura
si se mide necesario en Windows.

#### 1.5 — Ping/pong de Socket.IO muy frecuente ✅

**Síntoma:** `ping_interval=5` pausaba el event loop momentáneamente.

**Solución:** Subido a 25s. Sigue detectando desconexiones razonablemente
(<60s).

**Implementado en:** `server.py:SocketIO(ping_interval=25, ...)`

### Métricas Fase 1

Ver `docs/BENCHMARK-RESULTS.md` para detalle. Resumen:

| Métrica | Base JSON | Fase 1 Binario | Mejora |
|---|---|---|---|
| Throughput | 227,748 msg/s | 354,041 msg/s | **+55%** |
| Tiempo 1000 msgs | 4.4 ms | 2.8 ms | **−36%** |
| Bandwidth | 11.3 MB/s | 1.7 MB/s | **−85%** |
| E2E funcional | n/a | 250/250 OK | ✅ |

⚠️ Estas son mediciones del **transporte**. No incluyen driver ViGEmBus,
juego, ni latencia de red real.

### Pendiente validación

- [ ] Probar en Windows con Mario Kart u otro juego
- [ ] Medir latencia end-to-end real (touch → input en juego)
- [ ] Decidir si Fase 1.5 (WebRTC) es necesaria según resultados

Si Fase 1 en Windows resulta insuficiente, ver Fase 1.5 (WebRTC data channels).

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
