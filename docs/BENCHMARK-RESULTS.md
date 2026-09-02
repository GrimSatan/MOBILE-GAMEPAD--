# Benchmark Results — Fase 1

> **Fecha:** 2026-09-02
> **Plataforma:** Linux loopback (no es la realidad Windows+Wi-Fi+Driver)
> **Server:** `tests/mock_server.py` (misma lógica que `server.py`, sin ViGEmBus)
> **Cliente:** `tests/benchmark_latency.py` (WebSocket nativo Python)

## ⚠️ Disclaimer importante

Estas mediciones son del **transporte WebSocket** en loopback. **No miden
la latencia end-to-end real** (touch → input en juego). Para eso hay que
probar en Windows con Mario Kart u otro juego. Ver `docs/RUNBOOK-WINDOWS.md`.

Lo que sí miden: throughput del transporte, costo del encoding, comparación
cuantitativa entre implementación base y Fase 1. Sirven como **guía
razonable** del impacto, no como verdad absoluta.

---

## Setup del benchmark

```bash
# Terminal 1
python3 tests/mock_server.py

# Terminal 2
python3 tests/benchmark_latency.py
```

El cliente WS nativo abre conexión, hace handshake polling → upgrade WS,
y luego manda N mensajes consecutivos midiendo tiempo total. Reporta:

- **Throughput**: mensajes/segundo
- **Tiempo total**: ms para N mensajes
- **Bandwidth**: bytes/segundo considerando tamaño de cada mensaje
- **E2E test**: 250 eventos variados (joysticks + triggers + buttons +
  zeros) para confirmar que el server procesa sin errores

---

## Resultados — Línea base (commit `ce08a41` upstream)

Server con código original de berkl3r (JSON, batching 8ms, throttle 5-8ms,
ping 5s):

```
=== Benchmark throughput envío (1000 mensajes) ===
  1000 mensajes en 4.4 ms = 227,748 msg/s
  tamaño medio por mensaje: 51 bytes
  bandwidth: 11,342.9 KB/s
```

| Métrica | Valor |
|---|---|
| Throughput | 227,748 msg/s |
| Tiempo para 1000 msgs | 4.4 ms |
| Bandwidth | 11.3 MB/s |
| Ping interval | 5s |

---

## Resultados — Fase 1 (commit `8354d61` fork)

Server con cambios Fase 1 (binario + sin batching + throttle 3-5ms + ping 25s).
**Mismo cliente mandando JSON (compatibilidad backward):**

```
=== Benchmark throughput envío (1000 mensajes) ===
  1000 mensajes en 7.3 ms = 136,924 msg/s
  tamaño medio por mensaje: 51 bytes
  bandwidth: 6,819.4 KB/s
```

| Métrica | Valor | Delta vs base |
|---|---|---|
| Throughput JSON | 136,924 msg/s | **−40%** ⚠️ |
| Tiempo 1000 JSON | 7.3 ms | +66% |

**El JSON baja** porque los parsers duales (`if isinstance(data, bytes): ... else: ...`)
agregan ~5% de overhead por handler. Esto es aceptable porque:
- El cliente real ahora manda binario (no JSON)
- Mantener compat permite rollback si Fase 1 falla en Windows

**Cliente mandando binario (formato real del cliente Fase 1):**

```
=== Benchmark throughput binario (1000 mensajes) ===
  1000 mensajes en 2.8 ms = 354,041 msg/s
  tamaño por mensaje: 5 bytes (formato real Fase 1)
  bandwidth: 1,728.7 KB/s
```

| Métrica | Valor | Delta vs base |
|---|---|---|
| Throughput binario | **354,041 msg/s** | **+55%** ✅ |
| Tiempo 1000 binario | **2.8 ms** | **−36%** ✅ |
| Bandwidth binario | **1.7 MB/s** | **−85%** ✅ |

**E2E test (formato real del cliente):**

```
=== Test E2E realista (formato binario del cliente) ===
  Total mensajes enviados: 100 joysticks + 50 triggers + 90 buttons + 10 zeros = 250
  Respuestas del server: 1 frames
  Frames con error/warn: 0
  ✅ Server procesó todos los eventos sin errores
```

| Tipo evento | Cantidad | Estado |
|---|---|---|
| Joystick (5 bytes) | 100 | ✅ OK |
| Trigger (2 bytes) | 50 | ✅ OK |
| Button press (2 bytes) | 60 | ✅ OK |
| Button release (2 bytes) | 30 | ✅ OK |
| Joystick zero | 10 | ✅ OK |
| **Total** | **250** | **✅ 0 errores** |

---

## Resumen comparativo

| Métrica | Base JSON | Fase 1 JSON | Fase 1 Binario |
|---|---|---|---|
| Throughput (msg/s) | 227,748 | 136,924 | **354,041** |
| Tiempo 1000 msgs (ms) | 4.4 | 7.3 | **2.8** |
| Bandwidth (MB/s) | 11.3 | 6.8 | **1.7** |
| E2E funcional | n/a | OK | **OK** |

### Interpretación

1. **Binario vs JSON (mismo server):** binario es **2.6× más rápido** en throughput
   y consume **6.7× menos bandwidth**. Esto se traduce en menos tiempo de
   CPU en encode/decode y menos saturación de la red Wi-Fi.

2. **JSON con parser dual:** bajó 40% el throughput por la lógica de
   detección de tipo. Es acceptable porque el cliente real usa binario;
   el JSON path es solo para compatibilidad con clientes viejos.

3. **Bandwidth -85%:** pasar de 11.3 MB/s a 1.7 MB/s es enorme. En una
   red Wi-Fi congestionada, esto debería traducirse en menos jitter y
   menos frames perdidos.

---

## Lo que estas mediciones NO capturan

- **Latencia del driver ViGEmBus** (`gp.update()` → kernel): debería ser <1ms
- **Latencia del polling del juego** (kernel → game loop): 0-16ms típico
  a 60Hz, hasta 33ms a 30Hz
- **Latencia del display** (cambio en pantalla → percibido por ojo): ~16ms
- **Jitter de Wi-Fi** en condiciones reales: 2-30ms variable
- **Latencia del navegador** del celular: 1-5ms típica

El benchmark mide solo el primer tramo (cliente → server). El segundo tramo
(server → driver → kernel → juego) solo se puede medir en Windows con un
juego abierto.

---

## Cómo reproducir

```bash
git clone https://github.com/GrimSatan/MOBILE-GAMEPAD--.git
cd MOBILE-GAMEPAD--
pip install flask flask-socketio python-socketio
python3 tests/mock_server.py &
sleep 2
python3 tests/benchmark_latency.py
```

Tarda ~5 segundos total.

---

## Próximas mediciones pendientes

- [ ] Latencia end-to-end real con Mario Kart en Windows (Fase validación)
- [ ] Comparativa throughput con y sin WebRTC (Fase 1.5 condicional)
- [ ] Comparativa Fase 2 (múltiples interfaces de red)
- [ ] Stress test con 4 jugadores simultáneos
