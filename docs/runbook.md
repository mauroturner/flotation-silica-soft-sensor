# Runbook: qué hacer cuando algo no sale como se esperaba

Todos los comandos son para Windows (PowerShell), dentro de la carpeta `05-Mining-Flotation-Silica/` y con el entorno del proyecto. El paquete no está instalado en el entorno: una vez por sesión,

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python -m flotsilica --help
```

Los comandos que dicen «corrido» se corrieron al escribir este documento (U23), en una copia del proyecto en una carpeta temporal fuera del repositorio, en modo rápido (`--config config\pipeline.quick.toml`, que lee y escribe solo en `data\quick\`) salvo donde se dice otra cosa, y el código de salida que se indica es el que dio. Los mensajes se citan tal como salen, con las rutas, las claves de corrida y el nombre del equipo abreviados. Lo que no se pudo provocar en una copia (una entrega rechazada de verdad, la trampa de fuga, Airflow en Docker) se describe desde lo que dicen el código y sus pruebas, y cada entrada lo marca.

Códigos de salida de la CLI (`src/flotsilica/cli.py`): `0` terminó bien (también una corrida sin entrega pendiente y un `replay` sin pendientes), `1` falló una tarea, `2` uso o configuración incorrectos (también una tarea rechazada por el estado de su corrida o porque otro proceso tiene la carpeta de datos), `3` la fuente o la entrega fueron rechazadas por la validación. Cada corrida deja su estado en `data\interim\runs\<clave>.json`, tarea por tarea, con sus tiempos, sus picos de memoria con el contador y, si falló, la traza (con `-v` también sale por la pantalla).

Tres principios valen para todo el documento:

- **Un rechazo de la fuente no deja nada a medias.** Una fuente que no pasa V01-V07 escribe su informe de validación (`reports\validation\latest.md` y `latest.json`, con una copia en `history\`) y el estado de la corrida (`data\interim\runs\<clave>.json`) y nada más: ni almacén, ni Parquet, ni sello. Si algo falla después de `load`, la corrida queda `failed` y se retoma con su misma clave: `python -m flotsilica run --run-key <clave> --from <tarea>`.
- **Una corrida cerrada no se vuelve a abrir.** Cualquier tarea de una corrida `ok` o `no_delivery` se rechaza con código `2` antes de escribir nada: la entrega siguiente es otra corrida. Corrido, con una corrida que cerró sin entrega:

  ```powershell
  .venv\Scripts\python -m flotsilica task report --config config\pipeline.quick.toml --run-key <corrida cerrada>
  # error: la corrida <corrida cerrada> está cerrada (estado no_delivery): no se vuelve a abrir para correr report; otra entrega es otra corrida (python -m flotsilica run)
  ```

- **El sello no se toca.** `reports\model_seal.json` guarda la configuración del lanzamiento y el primer resultado de la prueba; ninguna tarea lo reescribe con otros valores, y una evaluación con otra configuración se guarda aparte, como posterior al sello (D18, D19). Nada de este documento pide editarlo a mano.

## R1 El archivo ARFF falta, o no tiene el tamaño o la huella fijados

**Síntoma.** Cualquier corrida con la configuración por defecto sale con código `3`: «rechazada: la validación de <corrida> rechazó la corrida: fallan las reglas bloqueantes V01». En `reports\validation\latest.md`, bajo «Ejemplos», la regla V01 dice el motivo: `{"rule_id": "V01", "reason": "missing"}` (no existe el archivo), `{"rule_id": "V01", "reason": "size", "expected": 185243565, "actual": <bytes>}` o `{"rule_id": "V01", "reason": "sha256", "expected": "a2512297…39b2", "actual": "<huella>"}`.

**Qué significa.** El proyecto no descarga nada (D02): exige que `[source] path` (`data\raw\openml-43311-quality-prediction-mining-process.arff`) exista y sea el archivo que se evaluó, de 185.243.565 bytes y SHA-256 `a25122979ba8c5fb9c12e361db61032efc6892a24b5746cc8309da601d9639b2`. El archivo no se versiona (`data/raw/` está ignorado), así que un clon nuevo no lo tiene. No se cambió nada: el informe de validación y el estado de la corrida son lo único que se escribió. Corrido, con la copia sin el archivo (código `3`), con uno de 12 bytes (`"reason": "size"`) y con uno de 185.243.565 bytes de ceros (`"reason": "sha256"`, código `3`).

**Qué hacer.**

1. Bajar el conjunto de OpenML, dataset 43311 (https://www.openml.org/search?type=data&id=43311): el archivo que baja no trae extensión; es un ARFF de texto (empieza con `@RELATION Quality-Prediction-in-a-Mining-Process`). Copiarlo a `data\raw\` con el nombre de arriba.
2. Comprobar la huella contra la fijada:

   ```powershell
   (Get-FileHash -Algorithm SHA256 data\raw\openml-43311-quality-prediction-mining-process.arff).Hash
   # A25122979BA8C5FB9C12E361DB61032EFC6892A24B5746CC8309DA601D9639B2
   ```

3. Si el archivo está cortado o dañado, volver a bajarlo. Si es otra versión legítima del conjunto, **no se cambia la huella sin más**: los criterios, los recuentos y el sello son de este archivo. Es un análisis nuevo (R9): se registra una decisión en `docs/decisions.md`, se cambian `accepted_bytes` y `accepted_sha256` y se empieza con otro sello.
4. En modo rápido no hay huella fijada: la primera que ve la guarda `data\quick\source.lock.json` (junto al archivo) y las siguientes deben coincidir. El mismo mensaje en modo rápido quiere decir que se cambió el accesorio; se vuelve a escribir con `make-fixture` y la misma semilla.

## R2 Una regla de lectura falló

**Síntoma.** La corrida sale con código `3` y V01 pasa, pero otra regla de la fuente falla: en `reports\validation\latest.md`, la tabla de reglas marca «falla» (V02 a V07) y bajo «Ejemplos» dice dónde: la línea, la columna y el motivo. Corrido, con una copia del accesorio donde un número tiene punto decimal en lugar de coma (código `3`): V05 falla y el ejemplo es `{"rule_id": "V05", "line": 39, "column": "Starch_Flow", "reason": "número", "value": "3110.86"}`; las reglas siguientes quedan «no evaluadas».

**Qué significa.** El lector es estricto (D03): trata el archivo como no confiable y rechaza, sin corregir, lo que no cumple la cabecera (V02), la codificación y los topes (V03), la forma de cada fila (V04: 24 campos, cada uno entre apóstrofos o un entero sin ellos, ninguno vacío), la fecha y los números (V05: `AAAA-MM-DD HH:00:00` y coma decimal), el orden (V06) o más de 180 filas en una hora (V07). Con la huella de R1 correcta el archivo real las cumple todas; si una falla con ese archivo, algo lo cambió en el camino, o se está usando otra copia.

**Qué hacer.** No editar el archivo para que pase. Comprobar que es el de R1 (misma huella); si lo es y la regla igual falla, es un defecto del lector: guardar el informe y abrir una decisión nueva. Con otro archivo, es R1 o R9.

## R3 Entrega rechazada, o `load` rechazado por la validación

**Síntoma.** La tarea `validate` de una corrida sale con código `3` («rechazada: … fallan las reglas bloqueantes V10») o `load` se niega con código `2`: «la validación de la corrida <clave> rechazó su entrega (V12): load no carga una entrega rechazada (docs/runbook.md, R3)», o «la corrida <clave> no validó su entrega: load carga solo una entrega que la validación de su corrida aprobó (python -m flotsilica run --run-key <clave> --from validate)».

**Qué significa.** Una entrega solo se carga si la validación de su misma corrida aprobó sus reglas bloqueantes (V10-V15: plan, sección 6). La rechazada queda en el manifiesto de entregas (`data\raw\deliveries\manifest.json`) como pendiente, no se carga, y la próxima corrida la repite. No se pudo provocar una entrega rechazada de verdad en la copia (las entregas salen del mismo archivo que ya pasó V01-V07); lo cubren `tests/contract/test_validate.py` y `tests/integration/test_pipeline.py`.

**Qué hacer.**

1. Leer `reports\validation\latest.md`: dice qué regla falló y con qué ejemplos (horas e identificadores de fila, nunca una fila entera).
2. V10 (entrega fuera de orden), V12 (la hora o la fila ya está en el almacén) y V13 (las filas, las horas o la huella no son las del manifiesto) son estados del almacén o del manifiesto: R4. V14 y V15 dicen que la entrega no es la que se publicó: borrar la carpeta `data\raw\deliveries\` solo si ninguna entrega está cargada, y volver a correr `deliver`.
3. Corregida la causa, retomar la misma corrida: `python -m flotsilica run --run-key <clave> --from validate`.

## R4 Entregas fuera de orden o faltantes

**Síntoma.** `deliver` o `load` salen con un error que nombra una entrega: «una corrida nueva empieza por fetch_source, no por load: indique con --run-key la corrida que continúa (…). No se escribió nada» (código `2`); «la corrida <clave> no tiene el resultado de la tarea deliver: corra esa tarea antes (python -m flotsilica task deliver --run-key <clave>)» (código `1`); «la entrega X está cargada pero la anterior, Y, no lo está (runbook R4)»; «el manifiesto trae la entrega X, que no está en el plan (runbook R4)»; «la entrega X ya está cargada por la corrida <clave> y el manifiesto no la marca cargada: retome esa corrida»; o «la entrega X ya está cargada en el almacén y sus filas cambiaron en la fuente; no se publica de nuevo».

**Qué significa.** El plan de entregas sale de la configuración (el lanzamiento hasta `launch_last_hour`, entregas diarias, el cierre) y nunca se salta: la siguiente es siempre la primera que no está cargada (`deliveries.next_pending`). Una entrega publicada o rechazada sigue siendo la pendiente; una cargada no se publica de nuevo con otras filas, porque sus filas ya están en el almacén. Corrido: `run --only load` sin clave sale con código `2` y el primer mensaje; con una clave que no corrió `deliver` (`--run-key ZZ`), código `1` y el segundo. Los otros mensajes los provocan un manifiesto editado a mano o una fuente cambiada, y los cubren las pruebas de `tests/unit/test_deliveries.py`.

**Qué hacer.**

1. Para una corrida que falló, retomarla con su clave desde la tarea que no terminó: `python -m flotsilica run --run-key <clave> --from <tarea>`. La clave está en el nombre de `data\interim\runs\<clave>.json`.
2. Para una entrega «ya cargada por otra corrida», retomar esa corrida, no abrir otra.
3. Para un manifiesto que no coincide con el plan (otro período, una entrega que no está), no se edita a mano: el manifiesto es una consecuencia de lo cargado. Si el almacén y el manifiesto no coinciden, se reconstruye desde cero (R11).

## R5 La trampa de fuga detuvo el lanzamiento

**Síntoma.** El lanzamiento (`fit_model`) falla con «M01: el MAE en V1 del candidato elegido (<x>) es menor que <r> × el de la persistencia (<y>): posible fuga de información. El lanzamiento se detiene (docs/runbook.md, R5)».

**Qué significa.** Un modelo honesto queda cerca de repetir el último análisis; uno que lo supera por mucho es sospechoso (D09). La razón `leak_tripwire_ratio` (0,5 en `config\pipeline.toml`) compara, en V1, el candidato elegido con la persistencia; un valor no finito también la dispara. Es la defensa de último recurso: antes de ella, una lista de columnas prohibidas y `LeakageError` impiden que el hierro del concentrado o una columna de laboratorio de la hora del objetivo llegue a la matriz. No se provocó en la copia: la cubre `tests/unit/test_model.py::test_the_tripwire_stops_a_candidate_below_the_ratio_of_the_persistence`.

**Qué hacer.** No subir el umbral ni quitar la trampa para que pase. Buscar la columna: correr las pruebas de fuga (`.venv\Scripts\python -m pytest tests/unit/test_features.py tests/integration/test_no_leak.py -q`), mirar si un cambio reciente en `features.py` o en la configuración dejó entrar una variable del objetivo, y corregirlo con una prueba. El lanzamiento no escribió sello ni artefacto: no hay nada que deshacer.

## R6 El artefacto del modelo no coincide con su huella

**Síntoma.** Una tarea que usa el modelo (`score`, `evaluate`) o `serve` se niega: «M03: el artefacto v1.pkl tiene la huella <x> y la registrada es <y>: no se deserializó. Se restaura el archivo registrado o se vuelve a entrenar desde el lanzamiento (docs/runbook.md, R6)»; o «M03: el artefacto v1.pkl pesa <n> bytes y no es el registrado de <m> bytes»; o «M03: no hay un artefacto legible en v1.pkl»; o «M03: la versión v1 del modelo no está registrada; el lanzamiento no la ajustó».

**Qué significa.** El modelo es un archivo `pickle` (`data\models\v1.pkl`) y un `pickle` ejecuta código al cargarse: por eso solo se deserializa si su tamaño y su SHA-256 son los que el registro del almacén guardó al lanzar (M03, D39). Si no lo son, no se lee. Corrido, con un byte agregado al archivo del modo rápido: `serve --config config\pipeline.quick.toml` sale con código `2` y el mensaje de la huella; con el archivo original restaurado, sirve.

**Qué hacer.**

1. Restaurar el archivo registrado (una copia de seguridad, o el que dejó el lanzamiento). Se comprueba su huella contra la registrada, que el mensaje dice.
2. Si no hay copia, se reconstruye desde cero con el sello (R11): el lanzamiento vuelve a entrenar con la configuración sellada y debe reproducir lo sellado.
3. Un archivo que no es el registrado nunca se carga «para ver»: es el caso de la regla M03.

## R7 La evaluación no reproduce el sello, o no hay sello

**Síntoma.** Una tarea sale con código `2` o `1` diciendo una de estas cosas: «no hay sello: el lanzamiento lo escribe y esta corrida no es el lanzamiento (docs/runbook.md, R7)»; «no hay sello: el lanzamiento lo escribe antes de que se evalúe la prueba, y no se evalúa sin él»; «la prueba no se evalúa con otra configuración que la sellada mientras el sello no tiene su parte de la prueba … las claves que difieren: …»; «M05: la configuración es la sellada pero el lanzamiento no la reproduce: <clave>: <x> sellado, <y> en esta corrida»; «la evaluación de la prueba con la configuración sellada no reproduce los valores sellados, redondeados a 6 decimales: …»; o «el criterio C0x del sello no se reconstruye desde sus cifras: lo sellado no se toma».

**Qué significa.** La prueba se evalúa una vez (D18): el sello (`reports\model_seal.json`) guarda la configuración del lanzamiento con su huella (`config_sha256`, que cubre cada clave que puede cambiar un valor sellado) y, después, el primer resultado de la prueba. Con la misma huella una repetición debe dar lo mismo a 6 decimales; si no, algo cambió el cálculo y el sello no se toma. Con otra huella, todo lo calculado es `post_seal` y se guarda aparte; la prueba sin sello de prueba se rechaza antes de escribir. Corrido, el caso feliz: se borró todo menos el sello y el accesorio (R11) y `replay --config config\pipeline.quick.toml` terminó con código `0` y el mismo sello. Los rechazos los cubren `tests/unit/test_seal.py`, `tests/integration/test_seal.py` y `tests/integration/test_evaluation.py`.

**Qué hacer.**

1. «No hay sello» en una corrida que no es el lanzamiento: el lanzamiento no corrió o se borró el sello. Con el almacén intacto, restaurar `reports\model_seal.json` desde Git (`git checkout -- reports/model_seal.json`); sin almacén, R11.
2. «Otra configuración que la sellada»: se editó una clave sellada de `config\pipeline.toml`. Volver a la sellada (`git diff config\pipeline.toml` muestra el cambio) o, si se quiere otro análisis, R9. Nunca se edita el sello.
3. «No reproduce lo sellado» con la misma configuración: es un defecto o un cambio de versiones (`pip check` y las versiones de `requirements.txt`); comparar con el informe del mensaje y no tocar el sello.

## R8 El bloqueo de un solo escritor, y `database is locked`

**Síntoma.** Una corrida o una tarea se rechaza con código `2` antes de escribir nada: «Otro proceso escribe esta carpeta de datos: `run` (sin corrida todavía), proceso <pid> en <equipo>, desde <fecha>. Espere a que termine y vuelva a correr; con Airflow, detenga el planificador antes de usar `airflow dags test` (docs/runbook.md, R8). No se escribió nada.» O, si el proceso que lo tenía ya no está: «El bloqueo …\data\quick\interim\pipeline.lock quedó de un proceso que ya no está en marcha: `run` (…), proceso <pid> en <equipo>, desde <fecha>. Ningún proceso lo borra solo: compruebe que nada más escribe esta carpeta (tampoco un contenedor que la monte), borre el archivo y, si esa corrida quedó a medias, retómela con `python -m flotsilica run --run-key <corrida> --from <tarea>` (docs/runbook.md, R8). No se escribió nada.» Otros dos: «Un proceso de otro equipo o contenedor tiene esta carpeta de datos…» (no se puede saber desde aquí si sigue en marcha) y «Otro hilo de este mismo proceso escribe esta carpeta…».

**Qué significa.** Un solo proceso escribe una carpeta de datos a la vez (D30): cada tarea toma `data\interim\pipeline.lock`, con el comando, la corrida, el proceso, el equipo y su arranque. Un bloqueo de un proceso vivo se respeta; uno de un proceso que ya no está se informa y no se borra solo, porque dos contenedores, o un contenedor y la máquina, comparten la carpeta pero no sus procesos, y desde uno no se sabe si el número de proceso del otro sigue vivo. `database is locked` es SQLite: otro escritor tuvo la escritura más de 30 s (`BUSY_TIMEOUT_MS` en `warehouse.py`), lo que con el bloqueo no debería pasar salvo con `airflow dags test` y el planificador a la vez (el compose lo dice).

**Advertencia A12 del proyecto 04 (abierta allí, y este módulo es el suyo).** El `lock.py` de este proyecto es el del 04 (D30) y hereda su advertencia A12 (`04-Ecommerce-Churn-Risk/docs/review-advisories.md`; `src/flotsilica/lock.py`, líneas 12-14): un bloqueo que quedó porque su liberación falló, por ejemplo porque en Windows otro proceso (un antivirus, un lector, un operador) tenía el archivo abierto más tiempo que los reintentos de la remoción, **rechaza incluso al proceso vivo que lo dejó**, y uno viejo hay que borrarlo a mano. Un fallo al soltar nunca levanta una excepción: queda el aviso en el registro y el resultado de la tarea vale. No se reprodujo aquí; el 04 lo midió con un archivo abierto 1 s (se libera) y 4 s (queda). Mientras la advertencia siga abierta, el paso 2 de abajo es el procedimiento.

**Qué hacer.**

1. Si el proceso está vivo, esperar a que termine.
2. Si no lo está, comprobar que nada más escribe la carpeta y borrar el archivo. Corrido en modo rápido: un proceso propio tomó el bloqueo y otra corrida se rechazó con código `2` y el primer mensaje; terminado ese proceso de golpe (`taskkill /F /PID <pid>`), la corrida siguiente dio el segundo mensaje, también con código `2`; después de

   ```powershell
   Remove-Item data\quick\interim\pipeline.lock
   ```

   `run --config config\pipeline.quick.toml` siguió y terminó con código `0` («no hay entregas pendientes: las 6 del plan ya están cargadas»).

3. Si la corrida del proceso muerto quedó `running` o `failed`, retomarla desde la tarea que no terminó, con su clave. Con Airflow, detener el planificador antes de `airflow dags test` (`docker compose stop airflow-scheduler`, y `docker compose start airflow-scheduler` después).

## R9 Empezar un análisis nuevo: otra latencia, otros horizontes, otro archivo

**Síntoma.** Se quiere medir con otra latencia del laboratorio, otros horizontes o un archivo nuevo, y la configuración sellada lo impide: R7 («otra configuración que la sellada»), o el lanzamiento dice «el artefacto v1.pkl ya existe con otra huella: una versión registrada tiene un solo artefacto; cambie [model] model_version para otro modelo (docs/runbook.md, R9)».

**Qué significa.** Una clave sellada cambia la huella del sello, y la prueba ya se evaluó una vez con la sellada (D18): un resultado nuevo no reemplaza el sellado. Es un análisis nuevo y se trata como tal: otra versión de modelo, otro sello y otras carpetas. Borrar el sello es lo mismo, y se registra en `docs/decisions.md`.

**Qué hacer.** Sin tocar lo versionado del análisis actual:

1. Copiar `config\pipeline.toml` a otro archivo, cambiar la clave (por ejemplo `[lab] latency_hours = 3`; las latencias de 3 y 4 h ya se informan como variantes del análisis actual) y apuntar **todas** las rutas de `[paths]` (el almacén, la carpeta de modelos, los Parquet, los archivos del sitio, el sello, el HTML, el README, las figuras) a una carpeta nueva. Si se comparte la carpeta de modelos, hace falta además otro `[model] model_version`: un artefacto registrado tiene un solo archivo.
2. Correr `python -m flotsilica replay --config <el archivo nuevo>`: lanza, congela y sella con su propia huella y evalúa la prueba una vez. Corrido en modo rápido (una configuración que extiende a `pipeline.quick.toml` con `latency_hours = 3` y las rutas bajo `data\quick3\`): terminó con código `0` y su sello tiene otra `config_sha256` (`f8de390d5b36…` contra `f87f3045ecc4…` del análisis de la latencia de 2 h) sin tocar el primero.
3. Si es un archivo nuevo, antes R1: otra huella en `[source]`.
4. Registrar la decisión y, si el resultado cambia lo que dicen el README o la ficha del modelo, decirlo como análisis posterior al sello, no como su reemplazo.

## R10 Airflow no arranca

**Síntoma.** `docker compose up airflow-init` o `docker compose up -d` se detienen diciendo que falta una variable («set FLOTSILICA_DB_PASSWORD in airflow/.env (see .env.example)»), el servicio de PostgreSQL no queda sano, la interfaz no responde en `http://localhost:8080`, o una tarea del DAG `flotsilica_daily` se rechaza con código `2` porque otro proceso tiene la carpeta de datos (R8).

**Qué significa.** El compose (`airflow/docker-compose.yaml`) no tiene ningún secreto con valor por defecto: `FLOTSILICA_DB_PASSWORD`, `FLOTSILICA_FERNET_KEY`, `FLOTSILICA_JWT_SECRET` y `FLOTSILICA_ADMIN_PASSWORD` se leen del entorno con `${VAR:?}` (D46). La interfaz queda solo en `127.0.0.1:8080`. PostgreSQL aplica su contraseña solo al crear su carpeta de datos: cambiarla después en `.env` no la cambia en la base. `data\raw\` se monta de solo lectura (el ARFF es del dueño y ninguna tarea lo escribe). En Linux hace falta `AIRFLOW_UID` con el id propio; Docker Desktop en Windows no lo necesita. El modo rápido corre también dentro del contenedor, con `FLOTSILICA_CONFIG=/opt/flotsilica/config/pipeline.quick.toml`, y una ruta relativa de una configuración se resuelve contra `/opt/flotsilica`.

**Qué hacer.** La prueba de Docker (`tests/e2e/test_airflow_docker.py`, marca `docker`: construye la imagen, corre `pip check` y `airflow dags test` dos veces en modo rápido y al final deja Docker como estaba) pasó al escribir U20 en 148 s (D46) y se midió de nuevo en la corrida real: 2 pasaron en 99,95 s (`.venv\Scripts\python -m pytest -m docker`, código `0`). Los pasos de abajo con el archivo real no se corrieron: lo que dicen el compose y sus pruebas estáticas (`tests/unit/test_compose.py` y `tests/unit/test_dag.py`, que pasan en la suite rápida):

1. Copiar `airflow\.env.example` a `airflow\.env` y completar las cuatro claves; `docker compose up airflow-init` y después `docker compose up -d`, desde `airflow\`.
2. Si se cambió la contraseña de la base después de crearla, cambiarla también dentro de PostgreSQL o borrar la carpeta de datos de PostgreSQL (solo guarda los metadatos de Airflow, no el almacén del proyecto).
3. `docker compose ps` y `docker compose logs airflow-init` dicen qué servicio no quedó sano.

## R11 Reconstruir desde cero con el sello, y una carpeta del sitio que no verifica

**Síntoma.** Dos casos con el mismo remedio. (a) Una tarea se niega con «La tabla <t> no coincide con su definición en sql/schema/<archivo>: faltan las columnas […]. El almacén lo creó una versión anterior: se reconstruye desde cero (docs/runbook.md, R11)». (b) `figures`, `export` o una lectura de los archivos del sitio dicen: «data.json no es el que nombra manifest.json (otro tamaño o SHA-256): los archivos no son de una misma exportación. Corra el flujo (python -m flotsilica run) antes de dibujar las figuras. No se escribió ninguna figura.» (código `2`).

**Qué significa.** (a) El esquema del almacén cambió entre versiones del código y las tablas no se migran. (b) Los cinco archivos de `outputs\site\` son una sola exportación: `manifest.json`, que se escribe último, nombra cada uno con su tamaño y su SHA-256, y quien los lee los verifica antes; un archivo editado a mano, o una exportación interrumpida entre dos archivos, no verifica. Corrido: con un espacio agregado a `data.json`, `figures --config config\pipeline.quick.toml` salió con código `2` y el mensaje de arriba sin escribir ninguna figura; con el archivo restaurado, escribió las siete.

**Qué hacer.**

1. Para (b), si el cambio fue accidental, restaurar los cinco archivos desde Git (`git checkout -- outputs/site`) o volver a correr la tarea `export` (`python -m flotsilica run --run-key <clave> --from export`).
2. Para (a), o si no hay nada que restaurar, reconstruir **conservando el sello** (`reports\model_seal.json`, versionado) y la fuente: borrar el almacén (`data\warehouse\`), `data\interim\`, `data\models\` y `data\raw\deliveries\`, y volver a correr `python -m flotsilica replay`. La reconstrucción debe reproducir lo sellado (R7). Corrido en modo rápido, borrando todo lo de `data\quick\` salvo el accesorio, `source.lock.json` y `reports\`: `replay` terminó con código `0` en unos 45 s, con el sello y el resumen como estaban.
3. La corrida real tarda unos 7 minutos y medio (D47). Hacerla en una copia de la carpeta, no en la que se versiona: reescribe las salidas versionadas con sus propias claves de corrida.

## R12 La API no arranca, o rechaza la interfaz o el pedido

**Síntoma.** `python -m flotsilica serve` sale con código `2` y una de estas frases: «serve solo escucha en 127.0.0.1 (D27), no en '0.0.0.0': el servicio no se publica fuera del equipo. No se escribió nada.»; «--port: se esperaba un puerto de 1 a 65535, se recibió 70000. No se escribió nada.»; «no hay sello del lanzamiento: la API solo sirve el modelo sellado, y sin lanzamiento no hay modelo (python -m flotsilica run). No se escribió nada.»; «la configuración actual no es la sellada (otra configuración): la API daría estimaciones distintas de las del flujo. Se vuelve a la configuración sellada o se vuelve a lanzar. No se escribió nada.»; o el error M03 de R6. Una vez en marcha, un `POST /estimate` responde `422`.

**Qué significa.** La API (D27, D45) es local y de solo lectura: solo escucha en `127.0.0.1`, no escribe nada, y se niega a servir sin el sello, con otra configuración que la sellada o con un artefacto que no es el registrado, porque daría estimaciones distintas de las del flujo. Todo eso se rechaza antes de abrir el puerto. Un `422` es un cuerpo que el servicio no puede creer, y se rechaza antes de estimar, con un código y el campo, sin rutas ni trazas: `invalid_request` (el cuerpo no cumple el formato: la lista `fields` dice cuáles), `not_on_the_hour` (el instante no está en punto), `duplicate_sample_hour` (dos análisis de la misma hora), `analysis_after_issue` (un análisis que llega después del instante de emisión: en ese momento no se conocía) y `short_lab_history` (hay menos de 24 análisis nuevos llegados), `estimate_refused` (el modelo no pudo dar una estimación finita con estas entradas). Corrido, con código `2` cada uno: `--host 0.0.0.0`, `--port 70000`, sin el sello, con otra latencia (`latency_hours = 3`) y con el artefacto alterado (R6). Con el cliente de FastAPI en el mismo proceso, `GET /health` dio `200` con la versión del modelo y la huella de la configuración sellada y `POST /estimate` con un cuerpo vacío dio `422` con `{"error": "invalid_request", "fields": [{"field": "issue_at", "type": "missing"}, …]}`.

**Qué hacer.**

1. Para el arranque, volver a la configuración sellada (R7), restaurar el artefacto (R6) o lanzar (`python -m flotsilica replay`). Un puerto ocupado lo dice uvicorn al abrirlo (no se provocó en la copia); se elige otro con `--port`.
2. Para un `422`, corregir el cuerpo según su código: el instante en punto, la hora de la muestra de cada análisis única y con su llegada (la hora de la muestra más la latencia de 2 h) no posterior al instante de emisión, al menos 24 análisis nuevos, las 19 lecturas finitas de las filas de la hora anterior al instante. El contrato está en `docs/plan.md`, sección 18, y las pruebas de `tests/integration/test_api.py` muestran cuerpos válidos.
3. Publicar la API fuera del equipo no está hecho: necesitaría autenticación y un despliegue que nadie pidió (pendiente del dueño).
