# Room OS

Room OS es una aplicación modular para Windows que reúne cámara en tiempo real,
seguimiento y reconocimiento de gestos, mouse virtual, presencia, reconocimiento
facial local, acciones del sistema e inteligencia visual opcional con Gemini.

> Proyecto en desarrollo. Las funciones que controlan Windows deben probarse con
> precaución y pueden desactivarse desde la configuración de la aplicación.

## Características

- Interfaz de escritorio con PySide6 y asistente de configuración inicial.
- Captura de cámara desacoplada mediante un `EventBus`.
- Seguimiento de hasta dos manos con MediaPipe.
- Gestos configurables y perfiles de calibración por mano.
- Mouse virtual con calibración guiada y filtros de movimiento.
- Detección de presencia y reconocimiento facial ejecutados localmente.
- Registro central de acciones para sistema, multimedia y aplicaciones.
- Análisis visual bajo demanda mediante Gemini, sin bloquear la cámara.
- Rate limiting, validación de entradas y escape de texto enriquecido.

## Requisitos

- Windows 10 u 11.
- Python 3.11 recomendado.
- Webcam compatible con OpenCV.
- Una clave de Gemini solo si se utilizará la IA visual.

## Instalación para desarrollo

```powershell
git clone https://github.com/diegomoren-lgtm/room-os.git
cd room-os
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Ejecuta la aplicación:

```powershell
python main.py
```

También puedes iniciar con `Room OS.cmd`, que comprueba el entorno y registra el
arranque de forma controlada.

## Gemini opcional

Room OS nunca guarda la clave en el código. Configúrala como variable de entorno
de usuario y reinicia la aplicación:

```powershell
[Environment]::SetEnvironmentVariable(
    "GEMINI_API_KEY",
    (Read-Host "Clave de Gemini"),
    "User"
)
```

Las imágenes analizadas con Gemini salen de la computadora y son procesadas por
Google. Consulta [la documentación de IA visual](docs/VISUAL_AI_GEMINI.md) y
[la política de seguridad](docs/SECURITY.md).

## Pruebas

```powershell
python -m unittest discover -s tests -v
```

Las pruebas no necesitan una webcam ni realizan solicitudes reales a Gemini.

## Compilar e instalar en Windows

```powershell
python -m pip install -r requirements-dev.txt
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1
```

El ejecutable se instala en `%LOCALAPPDATA%\Programs\Room OS`. Los perfiles,
calibraciones y logs permanecen en `%LOCALAPPDATA%\Room OS\data`.

## Arquitectura

```text
room_os/
├── core/       # EventBus, acciones, configuración persistente y seguridad
├── modules/    # Cámara, manos, gestos, mouse, presencia e IA visual
├── platforms/  # Integraciones específicas de Windows
├── services/   # Gemini, embeddings y almacenamiento facial
├── ui/         # Ventanas, páginas, tema y asistente inicial
├── scripts/    # Inicio, diagnóstico, compilación e instalación
├── tests/      # Pruebas unitarias y de integración local
└── docs/       # Seguridad y documentación de módulos
```

Los módulos se comunican mediante eventos y no dependen directamente de la
cámara. Las acciones se descubren a través del registro central, de modo que es
posible ampliarlas sin modificar el motor.

## Privacidad

- `data/` no se publica: puede contener perfiles faciales, imágenes y calibraciones.
- Las claves API solo se leen desde variables de entorno.
- El reconocimiento facial y de manos es local.
- Gemini solo recibe una imagen cuando el usuario solicita un análisis.

## Documentación

- [Seguridad](docs/SECURITY.md)
- [Presencia y reconocimiento facial](docs/PRESENCE_AND_FACE.md)
- [Inteligencia visual con Gemini](docs/VISUAL_AI_GEMINI.md)
- [Crear acciones](core/actions/README.md)
