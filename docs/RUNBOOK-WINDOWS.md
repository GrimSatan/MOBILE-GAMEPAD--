# Runbook — Testing Fase 1 en Windows

> **Para:** Cualquiera que quiera probar este fork en una PC con Windows.
> **Tiempo estimado:** 15-30 minutos para setup, 5 minutos para probar.

## Prerequisitos

### Hardware

- PC con Windows 10 u 11 (64 bits)
- Celular con navegador moderno (Chrome Android recomendado, Safari iOS no testeado)
- Misma red Wi-Fi entre PC y celular (o ver Fase 2 para hotspot/USB)

### Software en la PC

1. **Python 3.10 o 3.11** (3.12+ también debería andar, 3.13+ no testeado)
   - Descargar de https://www.python.org/downloads/
   - Marcar **"Add Python to PATH"** en el instalador

2. **ViGEmBus driver 1.22.0**
   - El server lo instala automáticamente al arrancar si no está
   - O descargarlo manualmente de: https://github.com/nefarius/ViGEmBus/releases/tag/v1.22.0
   - Es un driver de kernel, requiere ejecutar el instalador como Administrador

3. **Git** (opcional, para clonar)
   - https://git-scm.com/download/win

## Setup paso a paso

### 1. Clonar el fork

```powershell
git clone https://github.com/GrimSatan/MOBILE-GAMEPAD--.git
cd MOBILE-GAMEPAD--
```

### 2. Crear entorno virtual (recomendado)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

Si da error de "running scripts is disabled", abrir PowerShell como admin y correr:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 3. Instalar dependencias

```powershell
pip install -r requirements.txt
```

### 4. Probar el server (modo standalone)

```powershell
python server.py
```

**Output esperado (primer arranque sin ViGEmBus):**

```
Werkzeug appears to be used in a production deployment...
[*] Verificando driver Virtual Xbox 360...

======================================================
  INSTALACIÓN DEL DRIVER VIGEMBUS (XBOX 360 VIRTUAL)
======================================================
[*] ViGEmBus no está instalado en este sistema.
[*] Descargando instalador desde:
    https://github.com/nefarius/ViGEmBus/releases/download/v1.22.0/...
[OK] Descargado correctamente

[*] Abriendo el instalador de ViGEmBus...
    -> Por favor completa la instalación en la ventana que aparecerá.
```

**Si esto pasa:**
- Se abre el instalador de ViGEmBus en una ventana GUI
- Click "Install" (puede requerir UAC/Admin)
- Esperar a que termine
- Volver a la consola y correr `python server.py` otra vez

**Output esperado (segundo arranque con ViGEmBus):**

```
[*] Verificando driver Virtual Xbox 360...
[OK] Módulo vgamepad cargado — listo para crear mandos virtuales

==================================================
   MOBILE GAMEPAD SERVER
==================================================
  Abre esta URL en tu celular (misma red Wi-Fi):

     >>  http://192.168.X.Y:5000

  [QR ASCII art aquí]

  Presiona  Ctrl + C  para detener el servidor
==================================================
```

### 5. Conectar el celular

- **Opción A:** Escaneá el QR con la cámara del celular (se abre el navegador)
- **Opción B:** Abrí manualmente `http://192.168.X.Y:5000` en el navegador del celular

La página debería cargar con el gamepad virtual. Si ves los joysticks y botones, está OK.

**Si no carga:**
- Verificá que el celular esté en la misma red Wi-Fi que la PC
- Verificá que el firewall de Windows no esté bloqueando el puerto 5000:
  ```powershell
  # Permitir el puerto (ejecutar como admin):
  netsh advfirewall firewall add rule name="Mobile Gamepad" dir=in action=allow protocol=TCP localport=5000
  ```
- Probá acceder desde la misma PC: `http://localhost:5000` debería funcionar

### 6. Probar en un juego

1. Abrí Mario Kart (u otro juego) en la PC
2. Configurá el control: debería detectar "Xbox 360 Controller" automáticamente
3. Tocá botones / mové joysticks desde el celular
4. **Sentí la latencia:** si fue exitosa la Fase 1, debería ser notablemente
   más responsivo que el proyecto base

## Comparar contra el proyecto base (opcional)

Para tener un A/B test real:

```powershell
# Terminal 1: clonar el upstream
git clone https://github.com/berkl3r/MOBILE-GAMEPAD--.git mobile-gamepad-base
cd mobile-gamepad-base
git checkout master  # o el SHA del último commit de berkl3r
pip install -r requirements.txt
python server.py

# Jugar un rato y anotar latencia subjetiva

# Terminal 2: probar el fork
cd ..\MOBILE-GAMEPAD--
python server.py

# Jugar el mismo tramo y comparar
```

## Benchmarks automatizados (loopback)

Si querés las mediciones de throughput (sin juego real), en Linux/macOS:

```bash
python3 tests/mock_server.py &
# en otra terminal
python3 tests/benchmark_latency.py
```

Ver `docs/BENCHMARK-RESULTS.md` para los números.

## Debugging común

### El server arranca pero el QR no aparece

Probable: error en `print_banner()`. Fijate si hay traceback arriba.

### ViGEmBus instalado pero `is_vigembus_installed()` retorna False

```powershell
sc query ViGEmBus
```

Debería decir `STATE: RUNNING` o `STOPPED`. Si dice `STATE: 1 STOPPED`,
iniciarlo manualmente:
```powershell
sc start ViGEmBus
```

### El gamepad virtual no aparece en el juego

1. Verificá que `vgamepad` instaló correctamente:
   ```powershell
   python -c "import vgamepad; print('OK')"
   ```
2. Verificá que ViGEmBus está corriendo (ver arriba)
3. Reiniciá el server y mirá los logs

### Latencia sigue siendo alta

Posibles causas:
- **Wi-Fi congestionado:** probá con hotspot del celular o USB tethering
- **Driver ViGEmBus viejo:** actualizá a 1.22.0+
- **Juego con su propio input lag:** Mario Kart no es el mejor test, probá algo
  que muestre el input directamente (un emulador, un test de input, etc.)

## Medición subjetiva de latencia

Para tener un número concreto (no solo "se siente mejor"):

### Opción A: Cámara lenta

1. Poné el celular con la pantalla visible y la PC con un juego abierto
2. Filmá ambos con cámara a 240fps (celular moderno)
3. Tocá un botón en el celular y mirá cuándo aparece en el juego
4. Contá frames entre el touch y la reacción del juego
5. A 240fps: 1 frame = 4.17 ms. 30 frames de delay = ~125 ms

### Opción B: Latencia del driver

ViGEmBus expone el tiempo desde `gp.update()` hasta el reporte al kernel:

```python
import time
from vgamepad import VX360Gamepad

gp = VX360Gamepad()
t0 = time.perf_counter_ns()
gp.press_button(button=vgamepad.XUSB_BUTTON.XUSB_GAMEPAD_A)
gp.update()
t1 = time.perf_counter_ns()
print(f"ViGEmBus update: {(t1-t0)/1e6:.2f} ms")
```

Output esperado: <1 ms en una PC moderna.

### Opción C: Timestamp en el cliente

Modificar el cliente para que mande timestamp en cada evento y comparar con
timestamp en el server. Requiere agregar `time.time()` al payload y un log
en el handler. Ver `docs/PLAN-MEJORAS.md` Fase 1.5.

## Próximos pasos

Si después de probar querés seguir:

- **Fase 2** (auto-detectar conexión sin router): ver `docs/PLAN-MEJORAS.md`
- **Fase 3** (selector P1-P4): ver `docs/PLAN-MEJORAS.md`
- **Fase 4** (Linux nativo): ver `docs/PLAN-MEJORAS.md`

Si encontrás bugs o tenés mediciones para compartir, abrí un issue en
https://github.com/GrimSatan/MOBILE-GAMEPAD--/issues
