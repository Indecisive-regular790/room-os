# Inteligencia visual con Gemini

Room OS utiliza `gemini-3-flash-preview` mediante el SDK oficial `google-genai`.
El analisis solo ocurre bajo solicitud y nunca ejecuta acciones, comandos o
movimientos del mouse.

## Privacidad importante

Gemini no es local. Cada frame, imagen o captura solicitada se comprime como
JPEG y se envia a la API de Google. Room OS no guarda esas imagenes en disco ni
las incluye en eventos o logs, pero los datos salen de la computadora para ser
procesados por Google. No uses esta funcion con informacion sensible.

## Crear y configurar la clave

1. Crea una clave en <https://aistudio.google.com/apikey>.
2. Abre PowerShell. Para configurarla solo durante esa ventana:

   ```powershell
   $env:GEMINI_API_KEY = Read-Host "Pega tu clave de Gemini"
   ```

   La clave no se escribe en `config.py` ni se guarda en Room OS.

3. Instala las dependencias:

   ```powershell
   cd C:\ruta\a\room_os
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

4. Comprueba credenciales y acceso al modelo:

   ```powershell
   .\.venv\Scripts\python.exe scripts\test_gemini_vision.py --health
   ```

## Hacer preguntas

Cierra Room OS con `Q` antes de usar la camara desde el script.

```powershell
.\.venv\Scripts\python.exe scripts\test_gemini_vision.py --camera --question "Que hay encima del escritorio?"
```

Para analizar una imagen:

```powershell
.\.venv\Scripts\python.exe scripts\test_gemini_vision.py --image "C:\ruta\foto.jpg" --question "Que objetos aparecen?"
```

Para analizar la pantalla:

```powershell
.\.venv\Scripts\python.exe scripts\test_gemini_vision.py --screen --question "Que error aparece?"
```

El menu interactivo se abre con:

```powershell
.\.venv\Scripts\python.exe scripts\test_gemini_vision.py
```

## Room OS

Inicia normalmente:

```powershell
.\.venv\Scripts\python.exe main.py
```

La ventana muestra `AI: READY`, `AI: ANALYZING`, `AI: UNAVAILABLE` o
`AI: ERROR`. Si la variable `GEMINI_API_KEY` no existe o la API falla, el resto
de Room OS sigue funcionando.

El modelo se cambia mediante `GEMINI_MODEL` en `config.py`. El timeout se
controla con `GEMINI_TIMEOUT_SECONDS`. Para desactivar la integracion usa
`GEMINI_ENABLED = False` o `VISION_AI_ENABLED = False`.

Se conserva unicamente un historial textual corto en memoria por `session_id`.
No se guardan claves, imagenes, capturas, respuestas ni conversaciones en disco.
