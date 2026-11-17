# Advertencias de las revisiones nativas

Las advertencias que dejaron las revisiones nativas de Gentle AI de este proyecto, de U01 a U23, una sección por revisión, con su estado. Salen de lo que consta en el registro del documento de seguimiento (`odd/tasks/portfolio-projects.md`, L61 a L66), que dice qué advertencia devolvió cada revisión, cuáles se corrigieron y con qué commit, cuáles refutó quien orquestaba leyendo el código y cuáles quedaron para este documento, y del código y los commits que cada una nombra. **Los archivos de los hallazgos de cada revisión no se conservaron en el repositorio:** el texto de cada advertencia resume lo que dice el registro y lo que muestran el código y el commit de su corrección, y la severidad es la que el registro anota («advertencia» o «sugerencia»); donde no la anota, dice «no consta». Los hallazgos que el registro lista juntos, sin decir de qué revisión salieron (los de U11 a U17), se ubican por el archivo que nombran y la sección lo dice.

Estados: **corregida** (con el commit que la corrige), **refutada** (el hallazgo no es un defecto: se leyó el código y la evidencia está en la entrada), **dejada con evidencia** (cierta, cubierta de otro modo) y **abierta** (cierta o posible, sin corregir). Lentes: riesgo (R1), legibilidad (R2), confiabilidad (R3) y resiliencia (R4), por el prefijo del identificador. Las ubicaciones son relativas a la carpeta del proyecto y, donde se dan líneas, a la versión actual del archivo.

Las revisiones que no dejaron hallazgos: la investigación (`8ff5bca`), U05 (`ed3c66e`), U06 (`611b213`), U10 (`5656408`, ítem 1, sola), U17 (`24eda95`, ítem 4, sola), U20 (`8033325`, ítems 5 y 2, sola), la corrección `48a741e` y la corrección `352b915` (revisada, sin hallazgos). U13 (`a1096bd`) y U15 (`cf64427`) superaron el presupuesto de contexto de una revisión aun solas y se revisaron como cadenas de dos partes; U14 (`6a4ea19`), U16 (`e2a6dfa`) y U17 se revisaron solas (el registro no atribuye hallazgos a U13 ni a U16). No se revisaron de forma nativa: el plan (`8adbbbd`), que superó el presupuesto de una revisión solo y con U01 y no se puede partir sin reescribir la historia (se evaluó como riesgo medio, no debido); la parte generada de U21 (`d469a5b`), que la evaluación de riesgo no pidió revisar; y la documentación de U22 y U23, de la que el registro no anota una revisión. Todas las revisiones que se hicieron se aprobaron y se reconocieron.

## U01 (`c80d4b4`; riesgo, ítem 5; aprobada; 2 sugerencias)

- **R3-pip-check-stdout-substring** (`tests/unit/test_dependencies.py`; confiabilidad; sugerencia): la prueba de `pip check` buscaba en la salida las palabras que `pip` imprime en lugar de mirar su código de salida, y una versión de `pip` que las cambie la rompería sin que nada esté roto.
  - Estado: **corregida** en `c8d9c3c`: la prueba afirma el código de salida (`test_pip_check_reports_no_broken_requirements`, línea 356).
- **R3-live-env-coupled-tests** (`tests/unit/test_dependencies.py`, líneas 341 y 356; confiabilidad; sugerencia): las pruebas de las versiones instaladas y de `pip check` leen el intérprete que corre pytest, no un entorno armado desde `requirements.txt`: una `.venv` distinta de la fijada las hace fallar sin que cambie nada del código.
  - Estado: **abierta**: por diseño, la suite corre en el entorno del proyecto y detecta que ese entorno se aparte de lo fijado, que es lo que se quiere; una prueba en un entorno aparte armado desde los requisitos sería otra prueba, más lenta, que no se escribió.

## U02-U03 (`e1854bb..7be52f7`; riesgo y confiabilidad; aprobada; 3 advertencias)

- **R2-latency-offset-cancels** (`src/flotsilica/config.py`; legibilidad; advertencia): la comprobación de cierre del calendario comparaba `test_last + latencia` con `last_hour + latencia`, y la latencia se cancela: la expresión decía más de lo que hacía.
  - Estado: **corregida** en `48a741e`: compara las dos horas del calendario y dice por qué la latencia no importa; una prueba por latencia y el borde (`tests/unit/test_config.py`).
- **R3-lf-guard-wrong-attr** (`tests/fixtures/suite_budget.py`, línea 36; confiabilidad; advertencia): el guarda que reconoce una sesión con `--lf` como parcial leería un atributo equivocado de las opciones de pytest, y la sesión parcial pasaría por la suite completa.
  - Estado: **refutada**: pytest 9.2.0 declara `--lf` con `dest="lf"` (quien orquestaba leyó su código fuente), así que `getattr(option, "lf", False)` es el atributo correcto; `48a741e` agregó la prueba que lo fija (`tests/unit/test_suite_budget.py`, «`--lf` (stored by pytest under `lf`…)», con `--lf` y `--last-failed`), para que una versión de pytest que lo cambie la rompa.
- **R2-dead-age-variable** (`tests/unit/test_fixture.py`; legibilidad; no consta): una variable asignada y nunca leída en una prueba del accesorio.
  - Estado: **corregida** en `48a741e`: se quitó.

## U04 (`0cde78d`; riesgo, ítem 2; aprobada; 1 advertencia)

- **R4-atomic-write-no-fsync** (`src/flotsilica/files.py`; resiliencia; advertencia): la escritura atómica renombraba el archivo temporal sin haberlo volcado a disco (sin `fsync`), de modo que tras un corte el nombre definitivo podía quedar con el contenido incompleto.
  - Estado: **corregida** en `48a741e`: `os.fsync` del archivo temporal antes de `os.replace`, y el docstring del módulo dice lo que se garantiza y lo que no (no hay `fsync` del directorio en Windows); `tests/unit/test_files.py` suma 79 líneas de pruebas.

## U07-U08 (`e356b28..e42aaf2`; confiabilidad y resiliencia; aprobada; 2 sugerencias)

- **R2-dead-methods-constant** (`src/flotsilica/baselines.py`; legibilidad; sugerencia): la constante `METHODS` de las líneas base no la usaba nadie, y el módulo que emite las estimaciones repetía la lista a mano.
  - Estado: **corregida** en `c8d9c3c`: `scoring.py` usa la constante.
- **R3-fit-baselines-guard-untested** (`src/flotsilica/baselines.py`; confiabilidad; sugerencia): el guarda de `fit_baselines` sobre `min_fresh_history` frente al mayor `k` no tenía una prueba que lo hiciera fallar.
  - Estado: **corregida** en `c8d9c3c`: `tests/unit/test_baselines.py` suma el caso.

## U09 (`a7be0e2`; riesgo, ítem 2; aprobada; 1 advertencia)

- **R3-bundle-of-uncovered** (`src/flotsilica/registry.py`, `ModelBundle`; confiabilidad; advertencia): el paquete del modelo que se arma en memoria y el que se carga del registro no tenían una prueba que mostrara que estiman lo mismo.
  - Estado: **corregida** en `5656408` (U10): `tests/integration/test_scoring.py::test_the_model_that_scores_is_the_one_the_launch_fitted_and_the_registry_holds_with_its_hash` arma el modelo en memoria, lo guarda, lo carga desde el registro con su huella y comprueba que estiman lo mismo.

## U11-U12 (`c8d9c3c`, `c1c37b4` y `a995add`; riesgo, resiliencia y confiabilidad; aprobadas; 3 advertencias)

El registro (L64) lista estos tres hallazgos junto con los de las revisiones de U13 a U17 sin decir de cuál salió cada uno; se ubican aquí por el archivo que nombran, que cada commit introdujo.

- **R3-masters-id-key** (`tests/contract/test_validate.py`; confiabilidad; no consta): la prueba de contrato guardaba cada almacén maestro con una clave que lleva el `id()` del plan publicado, y un `id()` se puede reusar cuando el objeto muere: otro plan con el mismo `id()` habría recibido el almacén del anterior.
  - Estado: **corregida** en `027471c`: cada entrada guarda su plan, que la mantiene vivo, y la prueba afirma que el almacén que toma es el de ese objeto.
- **R3-method-names-coupling** (`src/flotsilica/scoring.py`; confiabilidad; no consta): `METHOD_NAMES` se arma con `*baselines.METHODS` y su orden es el orden publicado de los ocho métodos: reordenar la constante de las líneas base cambiaría las salidas sin que ninguna prueba lo notara.
  - Estado: **corregida** en `027471c`: `tests/unit/test_scoring.py::test_the_method_names_keep_their_published_order`.
- **R2-evaluation-unused-es-import** (`src/flotsilica/evaluation.py`; legibilidad; no consta): `es` se importaba de `texts` y no se usaba.
  - Estado: **corregida** en `027471c`: se quitó de la importación.

## U14 (`6a4ea19`; riesgo, ítem 6; aprobada; 1 advertencia)

El registro (L64) nombra esta advertencia entre las de U13 a U17; se ubica en U14 por el archivo que cita, `dashboard/render.py`, que es de esa unidad.

- **R3-gate-bool-identity** (`src/flotsilica/dashboard/render.py`, líneas 223, 316-317 y 347; confiabilidad; no consta): el tablero decide `sí` o `no` con `== True` (línea 223) y con `is True` (316-317 y 347) sobre las columnas booleanas del modelo estrella (`passes`, `sign_stable`, `chosen`), y una columna que llegara con otro tipo de booleano (el de NumPy, el anulable de pandas o el de objeto) no daría `True` por identidad y se mostraría como `no`.
  - Estado: **refutada**: `itertuples` entrega un `bool` de Python para las columnas de NumPy, para `BooleanDtype` y para las de objeto, también después de ida y vuelta por Parquet (lo dice el registro, L64), así que la comparación por identidad se cumple con lo que el modelo estrella escribe. Lo que sí faltaba es una prueba de esas celdas: ver `R3-gate-bool-cells-untested`.
- **R3-gate-bool-cells-untested** (`tests/unit/test_render.py`; confiabilidad; derivada de la anterior, no es un hallazgo de la revisión): ninguna prueba recorre las celdas booleanas de la tabla de sensibilidades, de los candidatos y de la compuerta con los tres tipos de booleano, y la refutación de arriba depende de cómo `itertuples` los entrega.
  - Estado: **abierta**: no se escribió; el registro (L64) la dejó para este documento.

## U15 (`cf64427`; riesgo, ítem 3; aprobada; 1 advertencia)

Como la anterior, el registro la nombra sin decir de qué revisión salió; se ubica en U15 por su archivo, `src/flotsilica/site_export.py`.

- **R4-001** (`src/flotsilica/site_export.py`, `_write`, líneas 459-462; resiliencia; no consta): la ventana del manifiesto. `_write` calcula el manifiesto nuevo, borra el viejo (línea 460), reemplaza los archivos que cambian (461) y escribe el nuevo al final (462). Entre el borrado y la escritura la carpeta del sitio no tiene manifiesto: quien la lee en esa ventana (`read_site`, `verify_site`) la rechaza como «los archivos no son de una misma exportación», y si el proceso muere ahí, la carpeta queda sin manifiesto hasta que la tarea `export` vuelva a correr.
  - Estado: **abierta**: es el diseño que el docstring del módulo dice (líneas 13-14: el manifiesto viejo se quita antes de reemplazar el primer archivo, para que una falla entre dos reemplazos deje una carpeta que `verify_site` rechaza en lugar de una mezcla que parezca buena); la consecuencia es una ventana en que la carpeta no verifica, y el runbook (R11) dice qué hacer. Una forma de cerrarla sería escribir los archivos en una carpeta de preparación y renombrar la carpeta entera; no se hizo.

## U18 (`36fe9d2..8b92a18`; la confirmación de velocidad y U18, como un tramo; aprobada; 2 hallazgos)

- **R2-known-arrays-shape-mismatch** (`src/flotsilica/features.py`, `_known_arrays`; legibilidad; no consta): la forma de lo que devolvía dependía de la rama: una devolvía todas las horas de muestra de los análisis llegados y la otra solo la última, en una lista de un elemento, y quien la llama tomaba `known_hours[-1]` de las dos.
  - Estado: **corregida** en `352b915`: las dos ramas devuelven la hora de muestra más nueva (`pd.Timestamp`, o `None` si no llegó nada) y `tests/unit/test_features.py` cambió con ella; esa corrección se revisó sin hallazgos.
- **R3-arff-cache-mtime-staleness** (`tests/fixtures/arff_reader.py`, líneas 30-35; confiabilidad; sugerencia): el lector del ARFF de las pruebas guarda sus resultados con `functools.lru_cache(maxsize=4)` por ruta, tamaño y fecha de modificación; un archivo reescrito con el mismo tamaño dentro de la resolución del reloj del sistema de archivos devolvería el análisis viejo.
  - Estado: **abierta**: la clave ya incluye el tamaño y la fecha de modificación en nanosegundos (`st_size`, `st_mtime_ns`) y la caché guarda solo los cuatro últimos archivos; el riesgo es un archivo reescrito con el mismo tamaño dentro de la resolución del reloj. Cerrarla sería agregar la huella del contenido a la clave, con el costo de leer el archivo de nuevo cada vez.

## U19 (`7ee1103`; riesgo, ítems 2 y 5; aprobada; 1 advertencia)

- **R3-persistence-body-order** (`src/flotsilica/api.py`; confiabilidad; no consta): el identificador dice que la persistencia que devuelve `POST /estimate` dependería del orden en que el cuerpo trae los análisis: un cliente que los mande desordenados recibiría otra respuesta que la del flujo.
  - Estado: **refutada**: la API arma las entradas con `features.lab_known_at`, que ordena por `sample_hour` (`src/flotsilica/features.py`, línea 77), así que el orden del cuerpo no cuenta; `bdd4e14` lo fija con una prueba (`tests/integration/test_api.py`) que manda el historial en cualquier orden y exige la respuesta del ordenado, y una mutación que devuelve el historial sin ordenar la hace fallar (L65).

## U21 (`b27f244`, `d469a5b` y `7bdc11e`; riesgo, ítem 1; la parte escrita a mano, aprobada; 1 advertencia)

Revisada en dos partes (L65): la escrita a mano (la prueba de la corrida real, D47 y los marcadores del README) y la generada (las salidas de `d469a5b`, que la evaluación de riesgo no pidió revisar).

- **R3-conn-leak-on-setup-failure** (`tests/e2e/test_real.py`; confiabilidad; no consta): la prueba abría la conexión del almacén y después leía el sello, el resumen y los archivos del sitio: si alguna de esas lecturas fallaba, la conexión quedaba abierta.
  - Estado: **corregida** en `7bdc11e`: se leen antes de abrir el almacén y la conexión se cierra siempre (`try … finally`).

## U22-U23 (`d469a5b..70e1b73` y `362bcee`; U22 en un tramo, U23 sola por el ítem 3; aprobadas; 3 sugerencias)

Revisadas después de U23 (L66): el tramo `d469a5b..70e1b73` (U22, la edición del README que cuenta U18-U21, L65 y la corrección de U21) y U23 sola, porque `docs-sync` cambia `cli.py` y `reporting.py`, que comparten otros comandos. La evaluación independiente las encontró sin corregir y explicó la de `docs.py` (L66).

- **R2-section-helper-sentinel-hack** (`tests/docs/test_docs.py`, la función `section`; legibilidad; sugerencia): para leer «Los resultados» hasta el bloque, las pruebas le agregaban al texto un `\n## ` de centinela.
  - Estado: **corregida** en `8d0d36c`: `section` recibe un final explícito (`end=RESULTS_START`) y, sin él, lee hasta el título siguiente o el final del texto.
- **R2-docs-sync-readme-double-read** (`src/flotsilica/cli.py`, `_docs_sync`; legibilidad; sugerencia): el README se leía dos veces, una para comprobar los marcadores y otra para escribirlo, y el contrato de comprobar todo antes de escribir quedaba implícito.
  - Estado: **corregida** en `8d0d36c`: cada archivo se lee una vez, se comprueban sus marcadores y se arma su texto nuevo con `reporting.replace_block`, y solo después se escribe; la salida no cambió.
- **R3-dtype-lookup-uncaught-keyerror** (`src/flotsilica/docs.py`, `render_dictionary_tables`; confiabilidad; sugerencia): `DTYPE_ES[c.dtype]` sin protección: un tipo que faltara salía con 1 y, como el README se escribía antes, lo dejaba escrito.
  - Estado: **corregida** en `8d0d36c`: un tipo que `DTYPE_ES` no nombra es un `ValueError` con la columna, que `docs-sync` convierte en la salida 2 sin escribir ningún archivo (`tests/docs/test_docs.py::test_docs_sync_with_a_column_type_the_dictionary_cannot_name_exits_2_and_writes_nothing`).

## Nota para la evaluación

Una nota que no es un hallazgo de ninguna revisión, sino una limitación de lo publicado que se vio al escribir esta documentación (U23). Queda abierta para la evaluación independiente.

- **N1-v1-mae-after-refit** (`outputs/site/algorithms.json`, `horizons[].methods[].mae_v1`, y `src/flotsilica/site_export.py`, `_algorithms`; confiabilidad): el MAE del modelo en V1 que el archivo del sitio publica (0,268 en H0) se mide **después del reajuste con entrenamiento y V1**, es decir, con un modelo que ya vio las horas de V1; no es una medida fuera de muestra. El que se midió en la elección, antes del reajuste, es 0,4725 (`docs/model-card.md`, sección «Selección y reajuste»). La ficha del modelo ya lo dice y no muestra de V1 las cifras de los métodos de aprendizaje; el JSON no lo rotula: la clave se llama `mae_v1`, igual que la de las líneas base, que sí son de V1 con el ajuste de su propio bloque, y la etiqueta de la fila es solo «Modelo». Quien arme la página del sitio desde ese archivo no debe presentar 0,268 como el error del modelo en validación.
  - Estado: **dejada con evidencia**: la evaluación independiente la confirmó (`mae_v1` del modelo de H0, 0,268, igual a su propio reajuste en V1; L66). No se cambió ninguna salida generada: el README, la ficha del modelo y el plan (sección 21) dicen que esa cifra se mide después del reajuste y no es fuera de muestra, y `SITE-UPDATES.md` pide que la página del sitio no la presente como el error de validación.
