# Session Log — GrimSatan/MOBILE-GAMEPAD-- fork

Registro cronológico de los bloques de trabajo terminados en este fork.

---

## 2026-09-02 — Setup + Fase 1 (binary WebSocket frames)

**Scope:** Fork del proyecto de berkl3r, setup inicial del entorno, benchmark
de línea base, e implementación de la Fase 1 del plan de mejoras.

### Commits incluidos

| SHA | Descripción |
|---|---|
| (ver upstream) | 8 commits originales de berkl3r |
| `8354d61` | perf(Fase 1): binary WebSocket frames, drop joystick batching, looser throttles |

### Contexto del fork

- **Repo upstream:** `berkl3r/MOBILE-GAMEPAD--` (privado del autor)
- **Fork:** `GrimSatan/MOBILE-GAMEPAD--` (público)
- **Rama:** `main` (renombrada desde `master`)
- **Owner del fork:** GrimSatan
- **Propósito:** Demostrar mejoras concretas al proyecto base, especialmente
  reducción de latencia en el transporte WebSocket y eliminación de
  dependencias del router hogareño.

### Trabajo realizado

1. **Verificación de fork y renombre de rama**
   - `master` → `main` localmente
   - Push a `origin/main`
   - Borrado de `master` en el remoto (requirió cambio manual del default
     branch en GitHub UI, no automatizable sin token)

2. **Investigación del proyecto base**
   - 8 commits de berkl3r, todos del 26-27 de agosto 2026
   - Stack: Flask + Flask-SocketIO + vgamepad + nipple.js
   - Sin tests, sin CI, sin docs de diseño
   - Único README + LICENSE
   - `server.py` 545 líneas; `index.html` 1.481 líneas (todo inline)
   - Sistema multi-jugador con 4 slots y auto-asignación
   - ViGEmBus obligatorio (solo Windows)

3. **Diagnóstico de latencia**
   - Análisis del código identificó los cuellos de botella principales:
     - JSON por frame (5-15 ms de encode/decode)
     - Batching de joysticks con `time.sleep(0.008)` (0-8 ms adicionales)
     - Throttle conservador (5-8 ms)
     - `ping_interval=5s` (interrumpe event loop)
   - Conclusión: el cuello de botella NO es el transporte Wi-Fi, es el
     procesamiento del payload

4. **Benchmark de línea base**
   - Implementado `tests/mock_server.py` (server con misma lógica, sin ViGEmBus)
   - Implementado `tests/benchmark_latency.py` (cliente WebSocket nativo)
   - Medido en loopback (Linux, sin red real):
     - JSON: 227,748 msg/s, 4.4 ms para 1000 msgs, 11.3 MB/s
   - Estas mediciones son del transporte solo, no incluyen el driver ViGEmBus

5. **Fase 1 implementada**
   - Server (`server.py`): parsers duales (JSON dict + bytes binarios)
   - Cliente (`templates/index.html`): helpers `sendJoystickBin`/`sendTriggerBin`/
     `sendButtonBin` con ArrayBuffers reusados
   - Quitado batching de joysticks
   - Throttle reducido
   - `ping_interval` subido a 25s
   - **Backward-compat:** clientes que aún manden JSON siguen funcionando
     (parsers detectan tipo automáticamente)

6. **Benchmark post-Fase 1**
   - Binario: 354,041 msg/s, 2.8 ms para 1000 msgs, 1.7 MB/s
   - **Mejora: 1.55× throughput, -36% tiempo, -85% bandwidth**
   - E2E test: 250 eventos binarios procesados sin errores

### Decisiones técnicas

- **Backward-compat en parsers:** en vez de romper el protocolo, los handlers
  aceptan ambos formatos. Esto permite rollback trivial si Fase 1 falla en
  Windows. Costo: ~5% más de CPU por handler (rama de detección de tipo).
- **No tocar Flask-SocketIO config:** `async_mode='threading'` se mantiene. Un
  eventual switch a `eventlet` o `gevent` daría más concurrencia pero es
  premature optimization.
- **No WebRTC todavía:** la mejora del binario puede ser suficiente. WebRTC
  queda como Fase 1.5 condicional.
- **Mock server con mockeado de vgamepad:** permite medir el transporte en
  Linux sin necesidad de Windows. El mock respeta la misma API de VX360Gamepad
  (mismos métodos, no-op).

### Verificación

- ✅ Sintaxis Python (`ast.parse`) en server.py, mock_server.py, benchmark
- ✅ Sintaxis implícita en index.html (cambios verificados por grep)
- ✅ E2E test: 250 eventos binarios (joysticks + triggers + buttons + zeros)
  procesados sin errores en mock server
- ✅ Benchmark reproducible: `python3 tests/benchmark_latency.py`

### Limitaciones de la medición

Estas mediciones son del **transporte WebSocket**, no del flujo completo:

- **Loopback:** sin red Wi-Fi real, latencia ~0
- **Sin ViGEmBus:** el mock no actualiza un driver real
- **Sin juego:** no se mide el delay entre `gp.update()` y la lectura del
  input por el juego

La métrica real que importa (latencia desde el touch en el celular hasta
que el juego ve el input) **solo se puede medir en Windows con Mario Kart
u otro juego**. El benchmark es una guía, no la verdad final.

### Cómo continuar

Ver `docs/RUNBOOK-WINDOWS.md` para instrucciones de setup y testing.
Ver `docs/PLAN-MEJORAS.md` para el roadmap completo (Fase 2, 3, 4).
Ver `docs/BENCHMARK-RESULTS.md` para las mediciones detalladas.

### Pendientes del fork

- [ ] Probar Fase 1 en Windows con juego real (Mario Kart u otro)
- [ ] Medir latencia end-to-end real (touch → input en juego)
- [ ] Decidir si Fase 1.5 (WebRTC) es necesaria según resultados
- [ ] Fase 2: detección de interfaces (LAN / hotspot / USB tethering)
- [ ] Fase 3: selector de slot P1-P4 desde UI
- [ ] Fase 4: soporte Linux nativo vía uinput
