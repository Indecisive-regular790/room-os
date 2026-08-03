# Seguridad de Room OS

## Credenciales

Las claves de API se leen exclusivamente desde variables de entorno. Room OS no
acepta claves en `config.py`, argumentos del constructor, archivos `.env` ni logs.
Para Gemini se usa `GEMINI_API_KEY` en el entorno de usuario de Windows.

## Limites y validacion

Las solicitudes de IA tienen cooldown, cola acotada y una ventana de cinco
solicitudes por minuto y sesion. Las preguntas se normalizan, tienen un maximo de
1,000 caracteres y rechazan caracteres de control. Los identificadores de eventos
solo admiten letras, numeros, guiones y guiones bajos.

Todo texto no confiable se escapa antes de insertarse en widgets de texto
enriquecido. Los detalles tecnicos se muestran como texto plano.

## SQL

Room OS no contiene actualmente una base de datos ni ejecuta SQL, por lo que no
existe hoy una superficie de inyeccion SQL. Si se agrega persistencia en el futuro,
toda consulta debe usar parametros del controlador (`execute(sql, parametros)`) o
un ORM. Nunca se deben concatenar entradas del usuario para construir SQL. Filtrar
palabras como `SELECT` o apostrofes no sustituye las consultas parametrizadas.
