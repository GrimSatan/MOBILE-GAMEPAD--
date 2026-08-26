# Mobile Gamepad

Un servidor local para Windows que te permite convertir tu teléfono celular en un control de Xbox 360 usando tu red Wi-Fi y tu navegador web (no requiere instalar apps en el celular).

## Características
* **Virtualización de Mando**: Crea un control virtual de Xbox 360 en tu PC usando el driver ViGEmBus.
* **Control Web**: Escanea el código QR en tu pantalla y juega desde el navegador del teléfono.
* **Semi-Automático**: Descarga e instala dependencias automáticamente (si falta el driver de ViGEmBus, lanzará el instalador gráfico).
* **Portátil**: Se puede compilar a `.exe` usando PyInstaller.

## Requisitos
- Windows 10 u 11 (64-bits).
- Python 3.10+ (si vas a usar el código fuente).
- Driver **ViGEmBus** (El script intentará instalarlo si no lo tienes).

## Uso rápido

### Desde Código Fuente
1. Clona este repositorio.
2. Instala los requerimientos:
   ```bash
   pip install -r requirements.txt
   ```
3. Ejecuta el servidor:
   ```bash
   python server.py
   ```
4. Abre la URL (o escanea el código QR) que aparece en tu terminal usando tu celular conectado al mismo Wi-Fi.

## Creador / Autor
Creado por **B3rkler**.

## Licencia
Este proyecto está bajo la Licencia **MIT**. Consulta el archivo `LICENSE` para más detalles. Puedes usarlo, modificarlo y distribuirlo libremente siempre que me des el crédito correspondiente.
