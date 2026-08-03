# Acciones Windows de Room OS

## Configurar aplicaciones

Las aplicaciones se identifican por claves fijas (`browser`, `vscode`,
`terminal`, `spotify`, `discord`, `codex` y `claude`). Nunca se acepta una ruta
desde `action.execute`.

Las aplicaciones de Microsoft Store que no exponen un `.exe` público pueden
usar un identificador fijo declarado en `APP_LAUNCH_IDS`. Ese valor también es
configuración local de confianza y nunca se toma de un evento.

Para definir una ruta explícita, edita `APP_PATHS` en `config.py`:

```python
APP_PATHS = {
    "vscode": [r"C:\Program Files\Microsoft VS Code\Code.exe"],
    "spotify": [r"C:\Users\TU_USUARIO\AppData\Roaming\Spotify\Spotify.exe"],
}
```

Primero se prueban ubicaciones comunes y después las rutas configuradas. Solo se
aceptan archivos `.exe` existentes. Para añadir una aplicación permitida:

1. Añade su clave a `ALLOWED_APPS`.
2. Añade sus rutas a `APP_PATHS`.
3. Declara sus nombres de proceso y ubicaciones comunes en
   `platforms/windows/app_control.py`.
4. Crea una acción con un `app_key` fijo en `core/actions/app_actions.py`.

## Habilitar y deshabilitar acciones

Los diccionarios `SYSTEM_ACTIONS_ENABLED`, `MEDIA_ACTIONS_ENABLED` y
`APP_ACTIONS_ENABLED` controlan cada acción. `ACTIONS_ENABLED=False` deshabilita
todo el motor y `WINDOWS_ENABLED=False` evita registrar acciones Windows.

`PREVENT_DUPLICATE_APPS=True` enfoca una instancia existente en vez de abrir
otra. Si no se encuentra la aplicación, la ejecución devuelve
`AppNotInstalledError` sin detener Room OS.

## Acciones peligrosas

Estas acciones se marcan con `dangerous=True`:

- `system.sleep`
- `system.shutdown`
- `system.restart`

Están bloqueadas inicialmente mediante `ALLOW_SLEEP`, `ALLOW_SHUTDOWN` y
`ALLOW_RESTART`. Apagado y reinicio requieren además confirmación explícita:

```python
event_bus.publish(
    "action.execute",
    {
        "action_id": "system.shutdown",
        "context": {"confirmed": True},
    },
)
```

El retraso se toma exclusivamente de `SHUTDOWN_DELAY_SECONDS`. No puede enviarse
un comando ni una ruta desde el evento. `system.cancel_power` cancela un apagado
o reinicio pendiente.

## Probar acciones seguras

Lista las acciones permitidas por el script manual:

```powershell
python scripts\test_windows_actions.py --list
```

Ejecuta una de ellas explícitamente:

```powershell
python scripts\test_windows_actions.py media.play_pause
```

El script no incluye bloqueo, suspensión, apagado ni reinicio.

## Crear futuras acciones Windows

1. Añade la operación nativa a un controlador dentro de `platforms/windows/`.
2. No aceptes comandos, argumentos de terminal o rutas provenientes de eventos.
3. Crea una clase sin argumentos obligatorios que herede de `BaseAction`.
4. Delega toda lógica específica de Windows al controlador de plataforma.
5. Marca `dangerous=True` cuando corresponda y valida confirmaciones antes de
   ejecutar.
6. Añade el ID al diccionario de configuración apropiado.
7. Crea pruebas con mocks para impedir efectos reales.

El `ActionRegistry` descubre la clase automáticamente; `ActionEngine` no debe
modificarse para añadir acciones nuevas.
