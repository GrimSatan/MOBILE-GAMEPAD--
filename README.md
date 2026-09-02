# Mobile Gamepad (Fork GrimSatan)

> **Fork de [`berkl3r/MOBILE-GAMEPAD--`](https://github.com/berkl3r/MOBILE-GAMEPAD--)** con mejoras de latencia.
>
> ⚠️ **Estado actual:** Fase 1 implementada (binario WebSocket + optimizaciones).
> Pendiente validación en Windows con juego real.

## Qué es esto

Un servidor local para Windows que convierte tu celular en un control de
Xbox 360 virtual, usando tu red Wi-Fi y el navegador del celular (no
requiere instalar apps). Fork del proyecto original de **B3rkler** con
mejoras de rendimiento.

## Qué cambia este fork vs el original

| Aspecto | Original | Fork Fase 1 |
|---|---|---|
| Eventos joystick | JSON ~33 bytes | Binario 5 bytes |
| Eventos button | JSON ~30 bytes | Binario 2 bytes |
| Eventos trigger | JSON ~25 bytes | Binario 2 bytes |
| Batching de joysticks | 8 ms flush delay | Inmediato |
| Throttle | 5-8 ms | 3-5 ms |
| Ping interval | 5 s | 25 s |
| Throughput medido (loopback) | 227k msg/s | **354k msg/s** (+55%) |
| Bandwidth | 11.3 MB/s | **1.7 MB/s** (−85%) |

Ver `docs/BENCHMARK-RESULTS.md` para los detalles.

## Quick start

### En Windows (uso real)

```powershell
git clone https://github.com/GrimSatan/MOBILE-GAMEPAD--.git
cd MOBILE-GAMEPAD--
pip install -r requirements.txt
python server.py
```

El QR aparece en consola → escaneá desde el celular.

Ver `docs/RUNBOOK-WINDOWS.md` para instrucciones detalladas, troubleshooting
y métodos de medición.

### En Linux/macOS (solo tests)

```bash
git clone https://github.com/GrimSatan/MOBILE-GAMEPAD--.git
cd MOBILE-GAMEPAD--
pip install flask flask-socketio python-socketio

# Terminal 1
python3 tests/mock_server.py

# Terminal 2
python3 tests/benchmark_latency.py
```

Sin ViGEmBus no se puede jugar, pero podés medir el transporte.

## Documentación

| Doc | Para qué |
|---|---|
| `docs/PLAN-MEJORAS.md` | Roadmap completo de las 4 fases planeadas |
| `docs/RUNBOOK-WINDOWS.md` | Cómo probar en Windows paso a paso |
| `docs/BENCHMARK-RESULTS.md` | Mediciones detalladas Fase 1 vs base |
| `docs/SESSION-LOG.md` | Qué se hizo en cada sesión, decisiones, pendientes |

## Roadmap

- ✅ **Fase 0** — Setup + benchmark de línea base
- ✅ **Fase 1** — Reducción de latencia (binario + sin batching + throttle)
- ⏳ **Fase 2** — Conexión sin router (LAN / hotspot PC / USB tethering)
- ⏳ **Fase 3** — Selector de slot P1-P4 desde UI
- ⏳ **Fase 4** — Soporte Linux nativo vía uinput
- 🔀 **Fase 1.5** (condicional) — WebRTC data channels si Fase 1 no alcanza

## Cómo contribuir / reportar

- Issues: https://github.com/GrimSatan/MOBILE-GAMEPAD--/issues
- PRs bienvenidos

## Créditos

- **Proyecto original:** [berkl3r/MOBILE-GAMEPAD--](https://github.com/berkl3r/MOBILE-GAMEPAD--) por B3rkler (MIT)
- **Mejoras Fase 1:** GrimSatan
- **Driver:** [ViGEmBus](https://github.com/nefarius/ViGEmBus) por Benjamin Höglinger-Stelzer (BSD-2)

## Licencia

MIT (igual que el upstream). Ver `LICENSE`.
