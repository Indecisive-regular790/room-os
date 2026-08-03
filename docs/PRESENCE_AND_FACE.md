# Presencia y reconocimiento facial local

Room OS usa MediaPipe para detectar rostros y un descriptor LBP generado con
OpenCV/NumPy para compararlos. Todo se procesa localmente. No se utilizan APIs,
servidores ni modelos en la nube.

## Registrar el primer perfil

Detén Room OS y ejecuta:

```powershell
cd C:\ruta\a\room_os
.\.venv\Scripts\python.exe scripts\register_face.py
```

El nombre técnico recomendado es `authorized_user`. El script toma 15 capturas:
tres de frente y tres mirando ligeramente a cada dirección. Solo guarda una
captura cuando hay exactamente un rostro, tiene tamaño suficiente y no está
borrosa. Estas imágenes y `embeddings.npy` quedan dentro de
`data/faces/<perfil>/`.

## Borrar un perfil

```powershell
.\.venv\Scripts\python.exe scripts\delete_face_profile.py
```

El script exige el nombre exacto y la confirmación `BORRAR`.

## Privacidad

Room OS no guarda frames durante el funcionamiento normal, no guarda rostros
desconocidos y no incluye imágenes ni embeddings en los logs. Las imágenes del
registro solo se guardan porque el usuario ejecuta explícitamente el script.

## Configuración

- `FACE_RECOGNITION_ENABLED = False` conserva presencia y desactiva identidad.
- `PRESENCE_DETECTION_ENABLED = False` desactiva también presencia.
- `FACE_MATCH_THRESHOLD` más alto reduce falsos positivos; más bajo tolera más
  cambios de luz, gafas o ángulo. Ajusta en pasos de `0.03`.
- Aumenta `PRESENCE_PROCESS_EVERY_N_FRAMES` y
  `FACE_PROCESS_EVERY_N_FRAMES` para reducir CPU, a cambio de mayor latencia.

## Prueba manual

```powershell
.\.venv\Scripts\python.exe scripts\test_presence_face.py
.\.venv\Scripts\python.exe scripts\test_presence_face.py --presence-only
```

Prueba el cuarto vacío, entrada y salida, una pérdida breve, rostro parcialmente
cubierto, dos personas, una persona no registrada y diferentes condiciones de
luz. Pulsa `Q` para cerrar.
