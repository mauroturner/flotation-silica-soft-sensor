# Registro de decisiones

Una entrada por decisión, con sus siete campos: Contexto, Opciones, Decisión, Motivo, Afecta, Quién y Estado. Donde había un solo camino razonable, «Opciones» lo dice y explica por qué. Las propuestas del agente de planificación (Opus) quedan para revisión del dueño; las del dueño citan el registro del documento de seguimiento (`odd/tasks/portfolio-projects.md`). Las cifras salen de `research.md`, de los documentos del proyecto 04 y de la comprobación del agente de planificación (`requirements.md`, sección 4), que leyó el ARFF fila por fila y **se detuvo en la primera fila con fecha 2017-07-31 o posterior**, de modo que ninguna fila del día de purga ni de la prueba entró en memoria; ninguna métrica se calculó sobre la prueba. Sus scripts y salidas se versionan en `research/plan/` (cada script recibe la ruta del ARFF y un directorio de trabajo fuera del repositorio como argumentos) (`p01_load.py` lectura detenida antes de la prueba y huella; `p02_structure.py` bloques, rampas, tramos y repeticiones; `p03_precision.py` decimales del objetivo; `p04_models.py` frescura, líneas base, candidatos por horizonte, rango, latencia y compuerta de sensibilidades; `p05_refit.py` el reajuste con entrenamiento y V1; salidas `p01.out` a `p05.out`).

Estados: **vigente**, **pendiente del dueño**, **reemplazada por Dxx**.

---

## D01 Enfoque: un sensor virtual frente a repetir el último análisis, con criterios que pueden no cumplirse y el resultado esperado dicho antes

- **Contexto**: el sitio promete un sensor virtual que estima la sílice antes de que llegue el laboratorio (S9). La primera mirada de research.md no superó a la persistencia (MAE 0,531 frente a 0,452; diferencia de 0,055 a 0,101). La comprobación del planificador, sobre las horas con análisis fresco (D05), encontró que ningún candidato supera a su base fuera del ruido en V2 en ningún horizonte. Los proyectos 03 y 04 tampoco superaron a su regla simple, y lo dijeron.
- **Opciones**: (a) solo el modelo, con su R²; (b) el modelo frente a lo que haría un operador (repetir el último análisis, promediar los últimos), con criterios fijados antes de construir que pueden no cumplirse y lo esperable escrito antes; (c) solo la persistencia, sin modelo.
- **Decisión**: (b). Candidatos de scikit-learn frente a B0-B3 (D13), con C01-C10 de `requirements.md`, sección 8.1 (D16). Lo esperable queda escrito: el modelo probablemente no cumpla C01-C04 ni C08.
- **Motivo**: un R² sin la persistencia al lado no dice nada en una serie con autocorrelación de 0,76 a una hora; la partición aleatoria da R² 0,565 donde los bloques de tiempo dan −0,511 (research.md). (a) repetiría ese error; (c) dejaría afuera lo que el sitio promete, incluido el rango y la estimación de las horas siguientes.
- **Afecta**: todo el proyecto; `requirements.md`, sección 8.1; `fact_evaluation_summary`; el README; el sitio.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D02 Fuente: el ARFF de OpenML 43311 fijado por tamaño y SHA-256, colocado por el dueño; el flujo no descarga nada

- **Contexto**: el conjunto de Kaggle pide una cuenta para descargarse; no hay credenciales en este equipo (L58). El dueño eligió la copia de OpenML (L59) y la bajó a mano; el archivo pesa 185.243.565 bytes, su SHA-256 es `a25122979ba8c5fb9c12e361db61032efc6892a24b5746cc8309da601d9639b2` y su MD5 es el que publica OpenML (research.md). La página de OpenML no devolvió contenido útil a la investigación, y la URL de descarga directa de su API no se comprobó byte a byte contra este archivo.
- **Opciones**: (a) descargar desde Kaggle con credenciales; (b) descargar desde la API de OpenML con la descarga endurecida del proyecto 04; (c) solo el modo local: el archivo lo coloca el dueño y el flujo comprueba tamaño y huella antes de leer un byte del contenido.
- **Decisión**: (c). `[source] path`, `accepted_bytes` y `accepted_sha256` fijados; si el archivo falta o no coincide, `fetch_source` termina con `SourceError` (salida 3) sin escribir nada y nombra el runbook R1, que dice de dónde bajarlo (la página de OpenML 43311 y el nombre del archivo) y dónde ponerlo. Una descarga por programa queda como pendiente del dueño (plan, sección 29).
- **Motivo**: hay un valor de confianza medido dos veces (el SHA-256 de L59 y el de la comprobación del planificador, `p01_load.py`); sin descarga desaparece toda la superficie de red (hosts, redirecciones, topes de tiempo: la unidad U04 del proyecto 04) y el riesgo queda en la lectura del archivo (D03). (a) necesita una cuenta; (b) agrega una fuente cuyos bytes no se comprobaron.
- **Afecta**: `ingest.py`; `config/pipeline.toml [source]`; V01; runbook R1; README «Cómo correrlo».
- **Quién**: dueño (la copia de OpenML, L59); agente de planificación (sin descarga).
- **Estado**: vigente.

## D03 Lectura del ARFF como archivo no confiable, con un lector propio y topes

- **Contexto**: el ARFF declara 24 atributos `STRING`, los números van entre apóstrofos con coma decimal, salvo los que no tienen parte decimal, que el archivo escribe sin apóstrofos (por ejemplo `390`), y las filas están en orden de fecha (research.md; la comprobación lo confirmó hasta el 2017-07-30). Un lector genérico de ARFF interpretaría los tipos declarados y no ayudaría; `pandas.read_csv` con el motor de Python tardaría más que el módulo `csv` (1,90 s para 560.333 filas, `p01_load.py`).
- **Opciones**: (a) `scipy.io.arff` (no admite atributos `STRING`); (b) `pandas.read_csv` con `quotechar="'"`; (c) un lector propio con el módulo `csv` de la biblioteca estándar, que valida la cabecera exacta y cada fila.
- **Decisión**: (c). Cabecera: `@RELATION` igual a `source.relation` y los 24 `@ATTRIBUTE` de `source.attributes`, en orden, todos `STRING`, comentarios `%` permitidos solo antes de `@RELATION`; `@DATA` una vez. Filas: UTF-8 estricto, sin byte nulo, ≤ `max_line_bytes`, 24 campos, cada uno entre apóstrofos o un entero sin apóstrofos (`-?[0-9]+`) y nada más, fecha `YYYY-MM-DD HH:00:00`, números `^-?\d+(,\d+)?$`, ningún campo vacío, fechas no decrecientes, ≤ `hours.rows_per_hour` filas por hora; el archivo ≤ `max_bytes` y ≤ `max_rows` filas. Cada falla es su regla (V02-V07) y no se escribe nada.
- **Motivo**: el formato es simple y su contrato es exacto; un lector propio con reglas nombradas da mensajes que dicen qué falló y permite probar cada variante malformada (AC02). Con el tamaño y la huella fijados (D02), las reglas protegen sobre todo al modo rápido y a una versión nueva del archivo.
- **Afecta**: `ingest.py`, `schema.py`; V02-V07; AC02.
- **Quién**: agente de planificación.
- **Estado**: vigente. Nota del 2026-11-17 (U05, corrección de la lectura): al leer el archivo real, 28.124 de las 560.333 filas anteriores a la prueba (verificado por el orquestador) escriben algún campo como entero sin apóstrofos (por ejemplo `390`), y la regla «cada campo entre apóstrofos» las habría rechazado. La regla vigente es: cada campo va entre apóstrofos o es un entero `-?[0-9]+` sin apóstrofos, y nada más; un campo vacío, con espacios, con signo `+`, con punto decimal o con una coma sin apóstrofos sigue siendo V04 o V05. Alcanzan a V04 (plan, sección 6), RF02 y AC02, ya actualizados.

## D04 La hora como unidad; el análisis de la hora es su primera fila y las demás filas del laboratorio no se guardan

- **Contexto**: los minutos y segundos son cero en todas las filas; casi todas las horas tienen 180 filas, una cada 20 s; los cuatro valores de laboratorio son horarios; en 310 horas el objetivo sigue dentro de la hora una rampa lineal que termina en el valor de la hora siguiente (research.md). Las filas 2 a 180 de una hora en rampa contienen, por lo tanto, el análisis de la hora siguiente.
- **Opciones**: (a) un modelo por fila de 20 s, como los tutoriales; (b) la hora, con su primera fila como análisis; (c) la hora, con la media de la hora como análisis.
- **Decisión**: (b). La unidad es la hora del objetivo; su análisis es la primera fila; los sensores se agregan por hora (media, desviación y último valor de las 19 variables de proceso). La lectura canónica guarda las cuatro columnas de laboratorio solo de la primera fila de cada hora; las filas 2 a n no llegan al almacén. El orden de las filas dentro de la hora (`row_in_hour`) se conserva para «último valor».
- **Motivo**: el laboratorio mide una vez por hora; un modelo por fila repetiría 180 veces el mismo objetivo y, en las horas en rampa, usaría el futuro. (c) mezclaría en la media de una hora en rampa el análisis de la siguiente.
- **Afecta**: `ingest.py`, `schema.py`; `source_hours.parquet`; AC03, AC10.
- **Quién**: agente de planificación (research.md lo proponía).
- **Estado**: vigente.

## D05 Solo los análisis frescos son objetivo o rasgo: los interpolados y los repetidos no son una medición

- **Contexto**: la comprobación del planificador (`p02_structure.py`) encontró que, antes de la prueba, los 159 pares de horas en rampa consecutivas tienen la misma pendiente por fila y las 159 horas interiores de los 66 tramos tienen su primer valor exactamente sobre la recta entre el análisis del principio y el del final: son una interpolación lineal, hecha después, que contiene el análisis futuro. Además, el 92,8 % de los valores tiene a lo sumo dos decimales (`p03_precision.py`) y una hora es igual a la anterior en el 9,9 % de los pares del entrenamiento, el 8,3 % de V1 y el 12,5 % de V2, con tramos idénticos de hasta 39 h; por azar se esperaría del orden del 0,5 % **[Inferido]**. Con esas horas, la persistencia de la validación da MAE 0,452 (la de research.md); sin ellas, 0,505 (`p04_models.py`).
- **Opciones**: (a) usar todas las horas, como research.md; (b) quitar solo las interpoladas; (c) marcar cada hora como `fresh`, `interpolated` o `held` y usar solo las frescas como objetivo y como historia del laboratorio; (d) quitar las horas en rampa enteras.
- **Decisión**: (c). `interpolated`: la hora está en rampa (su objetivo cambia dentro de la hora) y la hora anterior también. `held`: el valor es igual al de la hora anterior observada y la hora no es interpolada. `fresh`: lo demás con valor. La primera hora de un tramo en rampa es fresca (su primer valor es el análisis del principio). La marca de una hora sale solo de sus filas y de las de la hora anterior. La persistencia, las medias y los rasgos del laboratorio usan la secuencia de análisis frescos; la edad del último análisis fresco es un rasgo. El criterio de frescura se fija aquí, sin mirar la prueba; el resumen informa además las cifras sobre todas las horas (C10). Un análisis fresco que por azar repite el anterior se pierde: se acepta (unos 8 de 1.671 pares en el entrenamiento, por la estimación de arriba).
- **Motivo**: en tiempo real, un valor interpolado no existe (necesita el análisis siguiente) y un valor repetido no es un análisis nuevo; evaluarlos premia a la persistencia por error cero en las repeticiones y usar los interpolados como rasgo es una fuga. Que la marca dependa de la hora y de la anterior equivale a lo que la planta sabía cuando llegaba (o no llegaba) el resultado: si hubo análisis nuevo. (b) dejaría las repeticiones, que hacen ganar a la persistencia sin medir nada; (d) quitaría también el análisis fresco del principio de cada tramo.
- **Afecta**: `hours.py` (frescura), `features.py`, `baselines.py`, `evaluation.py`; V20-V22; RF04; AC04, AC14; C01-C10; el sitio («1 h» de la sílice).
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D06 Latencia del laboratorio: 2 horas como supuesto, con 3 y 4 horas como sensibilidad

- **Contexto**: el archivo no tiene columna de retraso. La única cifra encontrada es la de otra planta de mineral de hierro: un análisis «que tomaba 2 horas mínimo en estar disponible» (Moraes y otros, 2018, DOI 10.5151/2237-0234-31915; research.md). Con las horas frescas, la persistencia de V1 y V2 da 0,503, 0,611 y 0,670 con L = 2, 3 y 4 h, y el candidato elegido de H0 reajustado a cada latencia 0,505, 0,617 y 0,666 (`p04_models.py`).
- **Opciones**: (a) suponer que el análisis llega al cierre de su hora (L = 1); (b) L = 2 h, con 3 y 4 h como sensibilidad; (c) pedir la latencia real.
- **Decisión**: (b). `[lab] latency_hours = 2`: el análisis de la hora `k` (muestra al inicio de la hora, primera fila) llega en `k + 2`; al cierre de la hora `h` (instante `h + 1`) se conoce hasta el análisis de `h − 1`. Las variantes `latency_3` y `latency_4` se calculan en la evaluación, después del sello, y se informan en C10. La latencia real es un pendiente del dueño.
- **Motivo**: es la única cifra con fuente, y la sensibilidad muestra cuánto depende el resultado del supuesto. (a) no tiene fuente y haría la persistencia más fuerte; (c) no está disponible.
- **Afecta**: `config/pipeline.toml [lab]`; `features.py`; `deliveries.py` (el cierre espera la llegada del último análisis); C10; el sitio («antes de que llegue el laboratorio»).
- **Quién**: agente de planificación.
- **Estado**: vigente; la latencia real, pendiente del dueño.

## D07 Horizontes: la hora que cerró y las dos siguientes

- **Contexto**: el sitio dice que el modelo «devuelve la sílice estimada de las próximas horas»; research.md midió solo la hora en curso. La cabecera del ARFF pregunta «How many steps (hours) ahead can we predict % Silica in Concentrate». Con L = 2 h, la persistencia de los horizontes 0, 1 y 2 es la persistencia con 1, 2 y 3 h de retraso (0,452, 0,574 y 0,645 en todas las horas de la validación; research.md). En V1, la media de los últimos 3 análisis frescos supera a la persistencia en H1 (0,553 frente a 0,556) y en H2 (0,606 frente a 0,619) (`p04_models.py`).
- **Opciones**: (a) solo H0, y corregir el sitio; (b) H0, H1 y H2, cada uno con su modelo, su base más fuerte y su criterio; (c) hasta 6 horas.
- **Decisión**: (b). En el instante de emisión `t` (cierre de la hora `t − 1`), H0 estima la hora `t − 1`, H1 la hora `t` y H2 la hora `t + 1`, con las lecturas hasta la hora `t − 1` y los análisis llegados hasta `t`. Un modelo por horizonte, elegido en V1; C01-C02 para H0, C03 para H1 y C04 para H2. El texto del sitio pasa a «la sílice de la hora que cerró y la de las dos siguientes» (D41).
- **Motivo**: cumple lo que el sitio promete con un horizonte medido y responde la pregunta del autor del conjunto; cada horizonte cuesta 28 ajustes chicos. (c) llevaría la autocorrelación a 0,36 o menos, donde la estimación se acerca a la media y el resultado ya se ve en H2.
- **Afecta**: `features.py`, `model.py`, `scoring.py`; `[evaluation] horizons`; C01-C04; `dim_horizon`; la API; el sitio.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D08 El hueco de 318 h, las horas incompletas, la alimentación congelada y los sensores fijos se marcan; nada se rellena

- **Contexto**: un hueco de 318 h en marzo; dos horas con 174 y 179 filas; el laboratorio de alimentación sin cambios durante tramos de hasta 792 h (mediana 9 h); `air_flow_04` y `air_flow_05` constantes dentro de la hora en 460 horas del entrenamiento y 4 de V2 (research.md; `p02_structure.py`).
- **Opciones**: (a) rellenar el hueco y las horas incompletas; (b) marcar y no estimar lo que no tiene entradas; (c) quitar la alimentación y los dos sensores.
- **Decisión**: (b). Una hora sin filas no existe en la grilla de horas observadas y no se estima; una hora con menos de `hours.min_rows_per_hour` (90) filas tampoco; una con menos de `rows_per_hour` se marca `partial` y se usa. La historia del laboratorio es una secuencia de análisis frescos, no un reloj: después del hueco, los rasgos usan los análisis anteriores al hueco con su edad en horas. La alimentación entra solo en el conjunto `fSLF`, con sus horas desde el último cambio. Un sensor constante dentro de la hora se cuenta (I03) y se usa.
- **Motivo**: el sitio ya promete «los huecos se marcan en lugar de rellenarse»; un relleno inventaría mediciones. La edad del análisis y de la alimentación deja que el modelo sepa cuán viejo es lo que sabe. Quitar la alimentación lo decide la selección en V1, no una regla.
- **Afecta**: `hours.py`, `features.py`, `validate.py`; V23, I02, I03; `fact_data_quality`.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D09 `% Iron Concentrate` fuera, la trampa de fuga M01 y la demostración de la fuga

- **Contexto**: `% Iron Concentrate` se mide en la misma hora que el objetivo y tiene correlación −0,80 con él (research.md); la cabecera del ARFF pregunta si se puede predecir sin esa columna. La partición aleatoria da R² 0,565 contra −0,511 en bloques de tiempo con el mismo modelo (research.md). El proyecto 04 detuvo su lanzamiento con una trampa de fuga (su D41).
- **Opciones**: (a) solo dejarla fuera; (b) dejarla fuera con una guarda que la rechaza en la matriz, una trampa que detiene el lanzamiento si el elegido es sospechosamente bueno y una demostración de la fuga publicada.
- **Decisión**: (b). `schema.FORBIDDEN_COLUMNS` (`pct_iron_conc`, las columnas de laboratorio por fila, las marcas de rampa y de frescura de la hora del objetivo, `row_id`, `row_in_hour` y cualquier variable de calendario) nunca llega a `build_matrix` (`LeakageError`). **M01**: si el MAE en V1 del candidato elegido es menor que `leak_tripwire_ratio` (0,5) × el de la persistencia, el lanzamiento se detiene («posible fuga», runbook R5). `leakage_demo.py` publica dos cifras de validación: la de una partición aleatoria frente a la de bloques del mismo candidato, y la de un candidato con `% Iron Concentrate` frente al sellado; su módulo no puede escribir en el registro ni en las estimaciones.
- **Motivo**: la fuga es el error más común con este conjunto (research.md, Pural 2023 sin partición declarada); mostrarla con números del propio archivo es parte de la historia de Algoritmos. Un candidato honesto queda cerca de la persistencia (cociente 0,99 en V1); 0,5 deja margen y una fuga del objetivo lo cruza.
- **Afecta**: `schema.py`, `features.py`, `model.py`, `leakage_demo.py`; M01, M02; AC10, AC13; `fact_leakage`; el sitio.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D10 Partición: entrenamiento, V1, V2 y prueba, con purgas de 24 h; sin validación cruzada por bloques para elegir

- **Contexto**: research.md propuso entrenamiento hasta el 2017-05-31, validación del 2017-06-02 al 2017-07-30 y prueba del 2017-08-01 al 2017-09-09, con purgas de 24 h. El modelo necesita dónde elegir y dónde calibrar el rango sin usar lo mismo dos veces. El entrenamiento tiene 1.369 horas frescas, 1.345 con todas las entradas, en unos 63 días después del hueco.
- **Opciones**: (a) un solo bloque de validación; (b) V1 para elegir y V2 para calibrar el rango, separados por una purga; (c) validación cruzada por orígenes móviles dentro del entrenamiento.
- **Decisión**: (b). Entrenamiento 2017-03-10 01:00 a 2017-05-31 23:00; purga 2017-06-01; V1 2017-06-02 a 2017-06-30 (696 h, 630 frescas); purga 2017-07-01; V2 2017-07-02 a 2017-07-30 (696 h, 597 frescas); purga 2017-07-31; prueba 2017-08-01 a 2017-09-09 (960 h). Los bloques se asignan por la hora del objetivo; los rasgos pueden leer horas anteriores de otro bloque (son pasado). `check_split` exige `split.purge_hours` (24) en cada borde y que el último análisis de la prueba llegue dentro del cierre.
- **Motivo**: con 1.345 filas, cada pliegue de (c) entrenaría con menos de 700 horas y mezclaría el nivel de marzo con el de mayo; dos bloques de validación separados dan una elección y una calibración independientes. La purga evita que las horas vecinas, con autocorrelación 0,76, hagan optimista el comienzo de cada bloque.
- **Afecta**: `split.py`; `config [split]`; AC09; `dim_block`.
- **Quién**: agente de planificación (research.md proponía la ventana).
- **Estado**: vigente.

## D11 El cambio de nivel: sin calendario, el objetivo en cambio como candidato y el reajuste con entrenamiento y V1

- **Contexto**: la media del objetivo es 2,56 en el entrenamiento y 2,04 en la validación (research.md). En V2, el candidato elegido de H0 estima 0,110 de más en promedio y la persistencia 0,000; reajustado con entrenamiento y V1, 0,104 (`p05_refit.py`). El archivo no dice por qué cambia el nivel.
- **Opciones**: (a) variables de calendario o una tendencia; (b) normalizar el objetivo por período; (c) ofrecer el objetivo como cambio desde el último análisis fresco y reajustar el elegido con los datos más recientes antes de congelarlo.
- **Decisión**: (c). Cada conjunto con historia del laboratorio se prueba con el objetivo en nivel y en cambio; el elegido en V1 se reajusta con entrenamiento y V1 (de 1.345 a 1.975 filas en H0) antes de calibrar el rango en V2 y congelarlo. La variante `refit_all` (reajuste con entrenamiento, V1 y V2) se informa en C10 y no se usa para elegir. C06 mide el sesgo en la prueba.
- **Motivo**: seis meses no dan una estacionalidad que aprender y un calendario extrapolaría; el cambio desde el último análisis no depende del nivel; el reajuste usa junio, más cerca de la prueba. La mejora medida es chica (de 0,542 a 0,537 en V2), y se dice.
- **Afecta**: `model.py`, `registry.py`; `[model] refit_on`; C06, C10.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D12 Rasgos: lo conocido en el instante de emisión, en cuatro conjuntos

- **Contexto**: la primera mirada usó 57 agregados de sensores de la hora y rezagos de reloj del laboratorio (research.md). Con las horas interpoladas y repetidas fuera (D05), un rezago de reloj apunta muchas veces a una hora sin análisis. Los sensores solos dicen algo (en V2, de −0,242 a −0,042 frente a la media), pero no agregan sobre el laboratorio (de −0,001 a 0,021) (`p04_models.py`).
- **Opciones**: (a) rezagos de reloj con huecos; (b) la secuencia de los últimos análisis frescos conocidos, con su edad; (c) además, sensores de varias horas anteriores.
- **Decisión**: (b). En el instante `t`: `<sensor>_mean`, `_std`, `_last` de los 19 sensores en la hora `t − 1` (57); `lab_last1`, `lab_last2`, `lab_last3` (los tres últimos análisis frescos llegados), `lab_mean6`, `lab_mean24` y `lab_age_h` (horas entre la muestra del último y `t − L`) (6); `feed_silica_pct`, `feed_iron_pct`, `feed_silica_age_h` y `feed_iron_age_h` (4). Conjuntos: `fS` (57), `fL` (6), `fSL` (63), `fSLF` (67). Una hora se estima si tiene todas las entradas de su conjunto y al menos `features.min_fresh_history` (24) análisis frescos llegados.
- **Motivo**: es lo que un operador sabría al cierre de la hora; la secuencia de frescos no depende de cuántas horas faltaron. (c) suma columnas a 1.345 filas sin evidencia de que ayuden; queda como pendiente si un sensor pasara la compuerta.
- **Afecta**: `features.py`, `schema.FEATURE_COLUMNS`; AC10, AC11; el diccionario.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D13 Líneas base B0-B3 y la base más fuerte de cada horizonte, elegida en V1

- **Contexto**: research.md midió la media de entrenamiento, la persistencia, medias móviles de 3 a 24 valores y un ridge sobre sensores. Con las horas frescas, en V1, B*_0 sería la persistencia (0,474 frente a 0,488 de la media de 3) y B*_1 y B*_2 la media de 3 (`p04_models.py`).
- **Opciones**: (a) solo la persistencia; (b) B0-B3, con B* elegida en V1 entre las reglas de un operador; (c) incluir un modelo lineal con la historia del laboratorio entre las candidatas a B*.
- **Decisión**: (b). B0 media de los análisis frescos del entrenamiento; B1 persistencia (`lab_last1`); B2 media de los últimos k análisis frescos, con k elegido en V1 entre `[3, 6, 12, 24]` por horizonte; B3 ridge (`alpha = 1`, estandarizado) sobre los 57 agregados de sensores. B*_H es la de menor MAE en V1 entre B1 y B2; empate a 10⁻⁶, B1. Se elige en el lanzamiento y se sella.
- **Motivo**: B1 y B2 son lo que hace un operador sin modelo; B0 y B3 dan el piso y la referencia de «sensores sin laboratorio» (C07). (c) sería otro modelo, no una regla.
- **Afecta**: `baselines.py`; RF11, RF12; C01-C04, C07; `dim_method`.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D14 Modelos: gradient boosting y bosque aleatorio de scikit-learn, en nivel o en cambio, con una grilla fija y la elección en V1

- **Contexto**: el sitio dice «gradient boosting o random forest» y research.md midió solo el primero. En la comprobación, el bosque aleatorio fue el mejor en V1 en los tres horizontes; `HistGradientBoostingRegressor` tarda 0,29 s por ajuste y `RandomForestRegressor` con 300 árboles 1,43 s (`p04_models.py`). El landing declara scikit-learn y TensorFlow.
- **Opciones**: (a) solo `HistGradientBoostingRegressor`; (b) los dos, en una grilla fija, con la elección en V1; (c) LightGBM, XGBoost o una red.
- **Decisión**: (b). Por horizonte: familias `hgb` (`learning_rate = 0.05`, `max_iter = 300`, `max_leaf_nodes = 15`, `min_samples_leaf` en 20 y 50, `l2_regularization = 1.0`, sin parada temprana) y `rf` (`n_estimators = 300`, `max_features = 0.33`, `min_samples_leaf` en 5 y 20, `n_jobs = 1`); conjuntos `fS` (solo en nivel), `fL`, `fSL` y `fSLF` (en nivel y en cambio): 28 candidatos, `random_state = 0`. Se elige el de menor MAE en V1; empate a 10⁻⁶: `fL` < `fSL` < `fSLF` < `fS`, cambio antes que nivel, `hgb` antes que `rf`, más muestras por hoja. Se guardan las 28 cifras. El elegido se reajusta con entrenamiento y V1 (D11).
- **Motivo**: medir lo que el sitio nombra es S9; las dos familias están en scikit-learn, sin dependencias nuevas. (c) sumaría librerías fuera de S5 o de su necesidad con 1.345 filas.
- **Afecta**: `model.py`; `[model]`; RF13; `fact_selection`; el sitio (Algoritmos 1).
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D15 Rango del 80 %: conformal partido con los residuos de V2

- **Contexto**: una estimación sin su error engaña a quien opera; el MAE de cualquier método está entre 0,47 y 0,72. En la comprobación, el rango del 80 % calibrado en V1 cubrió en V2 el 76,2 %, el 74,4 % y el 76,7 % (semianchos 0,704, 0,820 y 0,904) (`p04_models.py`).
- **Opciones**: (a) sin rango; (b) regresión por cuantiles; (c) conformal partido con un bloque que no se usó para elegir ni para ajustar.
- **Decisión**: (c). Semiancho del horizonte H: el cuantil de orden `ceil((n + 1) · 0,8) / n` (método `higher`) de los residuos absolutos del modelo reajustado (entrenamiento y V1) sobre las horas de V2; el rango es `[estimación − q, estimación + q]`, recortado a `[0, 100]`. C05 mide la cobertura en la prueba.
- **Motivo**: es simple, no supone una distribución y sus residuos vienen de un bloque independiente de la elección; (b) duplicaría los ajustes y no tiene garantía de cobertura. El cambio de nivel puede bajar la cobertura, y C05 lo dice.
- **Afecta**: `intervals.py`; `[intervals]`; RF14; C05; AC16; la API; el tablero.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D16 Criterios C01-C10 y lo que se vio antes de fijarlos

- **Contexto**: los criterios se fijan antes de escribir código para que el resultado no los acomode (proyectos 01 a 04). Esta vez el planificador midió V1 y V2 sobre las horas frescas y la investigación la validación entera, así que casi todo lo que compara un criterio ya se vio en validación; la prueba no la vio nadie.
- **Opciones**: (a) criterios sin decir qué se vio; (b) criterios con dos columnas de lo visto y lo esperable escrito antes de medir.
- **Decisión**: (b). C01-C10 de `requirements.md`, sección 8.1. Lo esperable: no cumple C01-C04, C08 ni C09; C06 en el borde; C07 se cumple; C05 incierto. Si se confirma, el resultado es que repetir el último análisis (o promediar los tres últimos, en las horas siguientes) estima tan bien como el modelo y que los sensores no agregan nada que el laboratorio no diga.
- **Motivo**: decir lo visto permite leer cada veredicto con su contexto; un criterio que se cumple porque ya se miró en validación no es un hallazgo de la prueba.
- **Afecta**: `evaluation.py`, `reporting.py`; `fact_evaluation_summary`; README; sitio.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D17 Intervalos por remuestreo de días enteros

- **Contexto**: las horas vecinas están correlacionadas (0,76 a una hora); research.md remuestreó días (B = 2.000). La prueba tiene 40 días.
- **Opciones**: (a) remuestreo de horas; (b) remuestreo pareado de días; (c) bloques móviles de longitud fija.
- **Decisión**: (b). `day_bootstrap(errors_a, errors_b, days, n = 2000, seed = 0)`: en cada remuestra se sortean días con reposición y entran todas sus horas; los mismos días para los dos métodos; percentiles 2,5 y 97,5 de la diferencia de MAE (cociente de sumas, no media de medias diarias).
- **Motivo**: el día es una unidad natural de la operación y conserva la dependencia dentro del día; (a) daría intervalos falsamente angostos. (c) suma un parámetro sin evidencia de que cambie la lectura.
- **Afecta**: `evaluation.py`; C02-C04, C07, C08, C10; AC22.
- **Quién**: agente de planificación (research.md lo usó).
- **Estado**: vigente.

## D18 La prueba se toca una vez: modelo congelado y sello con una huella que cubre cada clave que cambia un valor sellado

- **Contexto**: la lección de los proyectos 02 a 04: un resultado se repite hasta que sale bien si nada lo impide, y una huella que no cubre una clave deja cambiar un valor sellado (proyecto 03, B4; proyecto 04, D19 y D89).
- **Opciones**: (a) evaluar la prueba cada vez que se corre; (b) sellar el lanzamiento y la primera evaluación, con la huella de la vista sellada completa, y rechazar una evaluación con otra configuración mientras el sello no tiene la prueba.
- **Decisión**: (b), como el proyecto 04 con su corrección D89 desde el diseño. `config.py` declara `FINGERPRINT_KEYS` y `UNSEALED_KEYS`; cada hoja de la configuración en exactamente una; los cálculos sellados reciben solo `SealedConfig`. Sin sello, el lanzamiento escribe `launch`; con sello y la misma huella, comprueba el elegido, los semianchos, B* y `valid_predictions_sha256`; con otra huella, todo es `post_seal` (M05), salvo la evaluación de la prueba mientras el sello no tiene `test`, que se rechaza antes de escribir (salida 2). La parte `test` se escribe una vez, con creación exclusiva. Borrar el sello es empezar un análisis nuevo y se registra aquí (runbook R9).
- **Motivo**: es el diseño que la evaluación del proyecto 04 probó con 55 claves; empezar con su corrección evita repetir su advertencia A1.
- **Afecta**: `config.py`, `registry.py`, `evaluation.py`; M05; AC18; `reports/model_seal.json`.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D19 Después del sello, el resumen toma del sello lo que el almacén no tiene

- **Contexto**: el proyecto 03 publicó un resumen «pendiente» después de sellar (su B3); el proyecto 04 lo resolvió con criterios reconstruidos desde el sello (su D20).
- **Opciones**: un solo camino razonable: el del proyecto 04.
- **Decisión**: `load_summary` lee el sello; si tiene `test` y el almacén no tiene C01 sellado, los criterios C01-C09 y las cifras de la prueba salen de `criteria_from_seal`, cada uno debe reproducir su entrada a 6 decimales o el sello no se toma (`SealError`), y el análisis de la corrida se muestra debajo como posterior al sello.
- **Motivo**: una reconstrucción desde cero o una corrida con otra configuración no puede borrar ni reemplazar lo sellado.
- **Afecta**: `reporting.py`; AC19.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D20 Sensibilidades: asociaciones del modelo, publicadas solo si pasan una compuerta de estabilidad

- **Contexto**: el sitio promete mostrar «cuánto se mueve la estimación cuando cambian el aire o los reactivos» y marcar «las que más la mueven». research.md encontró importancias por permutación menores que 0,007 y signos de la dependencia parcial que cambian entre modelos. La comprobación del planificador, sobre el mejor candidato con sensores de H0: aumentos de MAE de a lo sumo 0,0012 en V1 y V2 para los 19 sensores; signo que cambia entre el modelo y cinco reajustes en 11 de 19; ninguno pasaría la compuerta de abajo (`p04_models.py`).
- **Opciones**: (a) publicar el ranking como venga; (b) retirar las sensibilidades del sitio; (c) calcularlas siempre y publicar como «asociación estable» solo lo que pasa una compuerta fijada antes; el resto, como «sin asociación estable».
- **Decisión**: (c). Modelo: el mejor candidato con sensores de H0 (aunque el elegido no use sensores) y, para comparar, el mejor solo con sensores. Para cada sensor: (1) aumento del MAE al permutar sus tres columnas, media de 5 repeticiones, ≥ `min_importance_mae` (0,01) en V1 y en V2; (2) la dependencia parcial de su media horaria en una rejilla de 15 puntos del percentil 5 al 95, con correlación de Spearman del mismo signo y |ρ| ≥ 0,5 en el modelo sellado y en 5 reajustes con días del entrenamiento remuestreados (semilla 0). Pasa si cumple las dos en las dos validaciones. En la prueba se informa si conserva el signo (C09). Todo texto dice «asociación del modelo», nunca «causa» ni «acción»; una prueba lo comprueba en los textos generados.
- **Motivo**: cumple lo que el sitio promete sin afirmar lo que los datos no sostienen; una compuerta fija evita elegir la historia después de ver los números. 0,01 es el 2 % del MAE de la persistencia: por debajo, la variable no cambia la estimación de forma que un operador pueda notar.
- **Afecta**: `sensitivity.py`; `[sensitivity]`; RF20; C09; AC24; `fact_sensitivity`, `fact_pd_curve`; el sitio (Algoritmos 3, Tablero).
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D21 Operación simulada: lanzamiento, 40 entregas diarias y un cierre; emisión hora por hora con la llegada del laboratorio

- **Contexto**: el archivo es estático; el proyecto 04 lo convirtió en entregas mensuales (su D11). Una planta trabaja por hora; correr 960 corridas sería caro y no cambiaría nada si cada estimación usa solo lo que se sabía en su instante.
- **Opciones**: (a) una corrida por hora; (b) una corrida por día con una emisión por hora adentro; (c) una corrida por semana.
- **Decisión**: (b). Plan fijo de entregas: `L2017-07-31` (filas de todas las horas hasta el 2017-07-31 23:00; `as_of` 2017-08-01 00:00), `D2017-08-01` a `D2017-09-09` (las 24 horas de cada día; `as_of` 00:00 del día siguiente) y `C2017-09-10` (sin filas; `as_of` = la última hora + L = 2017-09-10 01:00, la llegada del último análisis; no emite). Cada corrida emite una estimación por horizonte en cada instante de emisión de `(as_of anterior, as_of]`, con lo cargado y con los análisis llegados en ese instante; el lanzamiento emite en los instantes de `split.test_first − (H máximo − 1) h` a su `as_of` (2017-07-31 23:00 y 2017-08-01 00:00), para que cada hora de la prueba tenga sus tres horizontes. Las variantes de la evaluación (D06, D11) se calculan después, con todo lo cargado, como un análisis retrospectivo. Una estimación de una hora fuera de los datos (H1 y H2 del último instante) se guarda censurada. `deliveries.cadence_hours` (24; 240 en el modo rápido) cambia solo el tamaño de las entregas: AC12 exige que las estimaciones sean idénticas con 24 y con 240.
- **Motivo**: una corrida por día es lo que vería un supervisor de turno y deja 42 corridas reales baratas; la igualdad entre tamaños de entrega prueba que ninguna estimación ve el resto de su lote.
- **Afecta**: `deliveries.py`, `scoring.py`, `pipeline.py`; RF05, RF16; AC05, AC12, AC21; el DAG.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D22 Seguimiento hora por hora durante la prueba, sin elegir nada después del sello

- **Contexto**: el tablero de una planta muestra la estimación junto al análisis cuando llega. En este proyecto ese error es la métrica de la prueba; verlo durante la repetición podría tentar a cambiar algo.
- **Opciones**: (a) ocultar el error de la prueba hasta el cierre; (b) mostrarlo hora por hora, con todo lo elegible ya sellado antes de la primera entrega de la prueba.
- **Decisión**: (b). `track` une cada estimación con su análisis fresco cuando `available_at ≤ as_of` y guarda el error del modelo, de la persistencia y de B*; los criterios se calculan solo en el cierre. Cualquier lanzamiento nuevo con otra configuración es `post_seal` (D18).
- **Motivo**: es lo que vería la planta y no cambia nada sellado: el modelo, el rango, B* y la compuerta se congelan en el lanzamiento.
- **Afecta**: `tracking.py`; RF17; `fact_estimate`; la página 1 del tablero.
- **Quién**: agente de planificación.
- **Estado**: vigente. Nota de U13 (2026-11-17): `tracking_at` une solo las estimaciones con números cuyo análisis llegó (`available_at ≤ as_of`, la llegada inclusiva) y, si el análisis es repetido o interpolado, deja la fila con su estado y sin error (D05); `track` reconstruye la tabla entera en cada corrida. No filtra por `issue_at` porque con una espera de al menos una hora la estimación siempre se emite antes de que llegue su análisis. Pregunta abierta para quien planifica: ninguna.

## D23 Validación: qué bloquea, qué se marca y qué se informa; las reglas acumuladas se leen una vez

- **Contexto**: los proyectos 02 a 04 separaron reglas bloqueantes, advertencias e informativas, y el 03 sumó en el sitio una regla acumulada sobre las corridas (su D94).
- **Opciones**: un solo camino razonable: la tabla del plan (sección 6), cada regla con su agregación (`source`, `per_run`, `latest`).
- **Decisión**: V01-V07 de la fuente, V10-V15 de la entrega, V20-V24 de las horas, M01-M06 del modelo, I01-I05 informativas; cada una con severidad, alcance, agregación, filas y horas afectadas, y hasta 5 ejemplos por hora (nunca por fila de la fuente completa).
- **Motivo**: cada regla con nombre se prueba sola y se publica igual en el tablero y en el sitio.
- **Afecta**: `validate.py`; `validation_rules.json`; AC06.
- **Quién**: agente de planificación.
- **Estado**: vigente. Nota de U05 (2026-11-17): V24 no se puede evaluar sobre una entrega cuyas filas no traen laboratorio (V15), así que la lectura canónica guarda por hora `feed_changes_in_hour` en `source_hours.parquet` (manifiesto del interim, versión 2); el cambio no toca el producto: V24 sigue siendo la advertencia «Alimentación que cambia dentro de la hora» y la hora usa su primera fila. Pregunta abierta para quien planifica: si prefiere otra forma de dar ese dato a la validación.

## D24 Almacén: SQLite en capas, con la llegada de cada análisis como dato

- **Contexto**: los proyectos 01 a 04 usaron SQLite con SQL versionado y controles en SQL; aquí la pieza nueva es cuándo se conoce cada análisis.
- **Opciones**: (a) archivos Parquet por día; (b) SQLite con `available_at` en cada análisis y vistas que filtran por instante.
- **Decisión**: (b). `raw_rows` (sensores por fila), `lab_hours` (los cuatro valores de la primera fila, `lab_state`, las horas desde el último cambio de cada alimentación, `available_at`) y `hour_aggregates`; las tablas de estimaciones de solo inserción con disparadores; los rasgos se leen con `lab_known_at(t)` y `sensors_of_hour(h)`, que filtran en SQL; el runner del proyecto 04 (autocommit, `BEGIN IMMEDIATE`, nunca `executescript`).
- **Motivo**: un filtro por instante en una sola función es lo que permite probar la perturbación (AC11); la tabla es chica (unas 4.100 horas).
- **Afecta**: `warehouse.py`, `sql/`; RF08; AC08.
- **Quién**: agente de planificación.
- **Estado**: vigente. Nota de U06 (2026-11-17): `stg_hours` toma las horas anteriores a `:as_of` (no `<=`: la hora `h` cubre `[h, h + 1 h)` y no había cerrado), `hour_blocks` se reconstruye en SQL con los bordes de la configuración que recibe y `chk_lab_state_rules` solo comprueba lo que dicen los valores guardados, porque la marca de rampa no llega al almacén (D04). Pregunta abierta para quien planifica: si quiere guardar esa marca para comprobar «la anterior está en rampa» tal cual lo dice la sección 7 del plan.

## D25 Salidas para Power BI y diseño del tablero en HTML

- **Contexto**: S4 pide un HTML con el diseño cuando el tablero no se puede armar sin la interfaz; los proyectos 01 a 04 lo generaron desde una especificación del modelo semántico.
- **Opciones**: un solo camino razonable: el del proyecto 04 sin la capa de privacidad.
- **Decisión**: el modelo estrella de la sección 19 del plan en Parquet versionado; `dashboard/semantic_model.py` como única fuente de tablas, relaciones, medidas y páginas; cinco páginas con vistas previas reales; el HTML autocontenido, sin scripts ni recursos externos.
- **Motivo**: una sola especificación alimenta el esquema, el diccionario y el HTML, y las pruebas lo comparan.
- **Afecta**: `export.py`, `dashboard/`; RF21, RF22; AC25, AC26.
- **Quién**: agente de planificación.
- **Estado**: vigente. Nota de U13 (2026-11-17): el modelo estrella sale **como estaba en el instante de la corrida** (una hora que no había cerrado, una estimación no emitida y un análisis que no había llegado no están en las tablas: `dim_hour` suma los estados `pending` y `missing` a los tres del plan, y `fact_hour_lab` no trae ningún valor del laboratorio hasta su llegada); B* no es una fila de las tablas de métricas, es la regla que es con `is_b_star`; las tablas de evaluación son las de la corrida que las escribió. `export_star_schema` recibe además la vista sellada y la ruta del sello, y el conjunto lleva `manifest.json` (RNF05). `fact_hour_process`, el hecho más grande, pesa 1,88 MB con el accesorio sintético completo. Pregunta abierta para quien planifica: si B3 (ridge sobre sensores) es una «regla» o una «comparación»; se la clasificó como comparación.
  Nota de U14 (2026-11-17): las medidas, las páginas y el HTML llegaron adaptados del proyecto 04 sin el enmascarado; como ninguna medida DAX corre en el proyecto (ítem 6), `validate_model` hace estático lo que puede (cada tabla, columna, medida y función existe; cada texto con que se compara una columna es un valor de esa columna; ningún filtro de un segmentador se quita; ningún visual junta tablas que ninguna relación une) y una prueba exige que cada segmentador llegue, por las relaciones, a los visuales de su página o que el título del visual diga que no lo filtra. Tres medidas leen solo las filas `sealed` (D71 del proyecto 04) y la curva de las asociaciones se titula «no una receta»: la revisión de D20 marca «causa» cerca de «dependencia parcial» aunque se niegue.

## D26 Exportación para el sitio, con manifiesto

- **Contexto**: marca-personal copia los archivos del sitio con un script que verifica el manifiesto (`scripts/export-churn-risk.py` para el 04).
- **Opciones**: un solo camino razonable: cinco JSON y un manifiesto escrito al final, leídos a través de `read_site`.
- **Decisión**: `summary.json`, `data.json`, `algorithms.json`, `operation.json` y `validation_rules.json` con el contrato del plan (sección 21) y `manifest.json`; ≤ 200 KB. El sitio tendrá `scripts/export-flotation-silica.py`, que se niega a escribir si el manifiesto no verifica o si la prueba no está sellada.
- **Motivo**: un conjunto mezclado tras una falla es la advertencia de U20 del proyecto 03; el manifiesto escrito al final la evita.
- **Afecta**: `site_export.py`; RF23; AC27; marca-personal.
- **Quién**: agente de planificación.
- **Estado**: vigente. Nota de U15 (2026-11-17): `export_site(conn, out_dir, run, view, *, seal_path, max_total_bytes)` toma la corrida y la vista sellada como `export_star_schema` (el tope de `[site]` lo pasa quien llama); lo que ve la prueba sale del resumen y del sello de la misma corrida y, antes del sello, va `null` o vacío aunque las horas de la prueba ya tengan estimación; el manifiesto se borra antes del primer archivo y se escribe al final, así que un corte a mitad deja un conjunto sin manifiesto que `verify_site` nombra y `read_site` rechaza, y `verify_site` pide además el mismo envoltorio en los cinco. El contrato suma `pending` en `states_by_block` y `gate` en `algorithms.json`, y `pd_curves` trae solo los sensores con curva (los que pasaron la compuerta): el detalle está en el plan, sección 21. Pregunta abierta para quien planifica: si el sitio prefiere ver la prueba parcial de una corrida anterior al cierre (hoy `test_hours` queda vacía hasta el sello, como dice el plan).

## D27 Una API de estimación con FastAPI, local, de solo lectura y con la misma función que el flujo

- **Contexto**: el sitio dice que «una API recibe las variables del momento y devuelve la sílice estimada» con FastAPI (`flotation-silica.ts`). El proyecto 04 no hizo API porque su lista era mensual (su D43); un sensor virtual, en cambio, se consulta cada hora. FastAPI está en el landing (S5). Airflow 3 trae su propia versión de FastAPI en la imagen.
- **Opciones**: (a) sin API, corrigiendo el sitio; (b) una API local con FastAPI que envuelve `score_issue`, en su propio archivo de requisitos; (c) una API publicada.
- **Decisión**: (b). `flotsilica.api:app` con `GET /health` (versión del modelo, `config_sha256`, estado del sello) y `POST /estimate` (cuerpo: `issue_at`, hasta `rows_per_hour` lecturas de los 19 sensores de la hora `issue_at − 1`, hasta 48 análisis `{sample_hour, silica_pct}` y, opcional, la alimentación); responde las tres estimaciones con su rango, la persistencia y qué entradas usó. Valida con pydantic: topes de cada lista, números finitos, horas en punto, ninguna lectura ni análisis posterior a lo que se sabría en `issue_at` (422). Carga el artefacto con su huella al arrancar; no escribe. `python -m flotsilica serve` usa uvicorn solo en `127.0.0.1`; otra interfaz sale con 2. Sus dependencias van en `requirements-api.txt`, fuera de la imagen de Airflow.
- **Motivo**: es lo que el sitio promete y la única forma natural de usar un sensor virtual; reutilizar `score_issue` hace que la API y el flujo no puedan diferir (AC28). Separar los requisitos evita un conflicto con la FastAPI de Airflow. (c) sumaría autenticación, despliegue y costo sin pedido.
- **Afecta**: `api.py`, `cli.py`; `requirements-api.txt`; RF24; AC28; `LANDING-EXPANSION.md` (pydantic, uvicorn, httpx); el sitio.
- **Quién**: agente de planificación.
- **Estado**: vigente; publicarla, pendiente del dueño.

## D28 Orquestación: Airflow 3.4.0 en Docker con todos los secretos del entorno, y la CLI

- **Contexto**: los proyectos 01 a 04 usaron `apache/airflow:3.4.0` con un compose endurecido; el 04 pasó `airflow dags test` en Docker (L55, L56).
- **Opciones**: un solo camino razonable: el DAG y el compose corregidos del proyecto 04.
- **Decisión**: DAG `flotsilica_daily` (`schedule = "0 1 * * *"`, sin catchup, `max_active_runs = 1`, `max_active_tasks = 1`), una tarea por `TaskSpec`, sin reintentos ante un rechazo; compose con interfaz en `127.0.0.1`, cada secreto con `${VAR:?}`, montajes de solo lectura, imagen con resumen, `init.sh` con `set -e`, proyecto `flotsilica-airflow`; la imagen instala solo `requirements.txt`.
- **Motivo**: reutiliza lo que ya pasó una evaluación; la API no entra en la imagen (D27).
- **Afecta**: `airflow/`; RF25; AC34, AC35.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D29 Estado de la corrida, cierre en orden y rechazos

- **Contexto**: los proyectos 03 y 04 corrigieron el cierre de la corrida, el manejador de fallas que tapaba el error y las tareas de corridas que no cargaron su entrega (03, D72, D79, D86, D93; 04, D30).
- **Opciones**: un solo camino razonable: el del proyecto 04 desde el diseño.
- **Decisión**: estado por corrida en `data/interim/runs/<run_key>.json`; la corrida queda `running` hasta `report`; rechazos antes de escribir (`RunRefusedError`, salida 2) para una corrida cerrada, una entrega cargada por otra corrida, `load` sin validación aprobada y toda tarea posterior a `load` sin su propia entrega; el manejador de fallas intenta cada escritura por separado y relanza el error de la tarea.
- **Motivo**: cada una de esas reglas salió de un defecto real de un proyecto anterior.
- **Afecta**: `pipeline.py`; AC29, AC30.
- **Quién**: agente de planificación.
- **Estado**: vigente. Nota de U17 (2026-11-17): `pipeline.py` y `sysinfo.py` son los del proyecto 04 (su D77 y D80, con las correcciones de su evaluación) adaptados: once tareas sin `build_cuts`; cada tarea lee lo que dejaron las anteriores en el archivo de estado, arma el `RunMeta` (de lo que guarda `deliver`, que suma el instante de la entrega anterior) y la vista sellada y llama a `launch.fit_model`, `scoring.score_run`, `tracking.track`, `reporting.evaluate`, `export_star_schema`, `export_site` y `render_design` sin cambiar ninguna; `run_task`, `run_all` y `replay` toman `lock.sole_writer` con `paths.interim_dir` y un `replay` sin pendientes no lo toma. Decisiones propias: (a) `EvaluationRefusedError` es un `RunRefusedError` (salida 2) y el rechazo corre antes de **toda** tarea de una corrida cuyo instante alcanza la llegada del último análisis de la prueba, no solo de `evaluate` (la clase A1 de P4: rechazar solo `evaluate` dejaría cargado y emitido lo anterior), con `registry.check_test_evaluation` como única regla y la misma conversión dentro de `evaluate`; (b) un `RunRefusedError` o un `ValidationError` que sale de una tarea no la marca `failed`; (c) el mensaje de la fila de una corrida, que se publica en `dim_pipeline_run`, pasa por `_without_paths` (cada ruta que empieza en la carpeta del proyecto, la del usuario o la temporal, o que parece absoluta, es `<path>`); el archivo de estado, que no se publica, guarda el error y la traza completos; (d) `export.export_run_table(conn, out_dir, model, run, view)` reescribe sola `dim_pipeline_run.parquet` y su línea del manifiesto y, sobre una carpeta que no verifica, no escribe nada y avisa (R4-001 de P4); (e) una regla del modelo ya agregada al reporte de la corrida (una tarea repetida) se reemplaza: `add_results` la rechazaba y P4 fallaba al repetir `fit_model`; (f) `report` vuelve a escribir el reporte de validación de su corrida como `latest.*` antes de cerrar, porque otra corrida que tenga la misma entrega pendiente también lo escribe al validar. Pruebas: 27 nuevas (21 de integración en `test_pipeline.py`, 4 de `sysinfo` y 2 de `export_run_table`), con los estados de sesión `pipeline_launched` y `pipeline_replayed` sobre un plan propio del accesorio chico (lanzamiento, una entrega de 25 horas y el cierre) que cada prueba copia con `copytree`. REDs: contra un `pipeline.py`, un `sysinfo.py` y un `export_run_table` que lanzan `NotImplementedError("U17")`, las 24 pruebas de entonces dejaron de pasar (23 por `NotImplementedError`, una por un nombre que el esqueleto no tenía); las cuatro del plan, en la preparación de la sesión. 23 mutaciones hacen fallar su prueba con nombre (cada regla de rechazo, cada escritura del manejador, el orden del cierre en dos formas, la fila creada al cerrar, el bloqueo en los tres comandos y el de `replay` sin pendientes, la entrega no cuarentenada, el mensaje con rutas, la corrida fallida sin reabrir, el refresco de una corrida sin entrega, la regla repetida y las dos de `export_run_table`); dos sobrevivieron a la primera ronda (`replay` sin su propio bloqueo, porque el `run_all` anidado lo pide, y el `latest.*` de `report`) y llevaron la comprobación del bloqueo entre dos corridas y `test_report_leaves_the_validation_report_of_its_own_run_as_the_latest`. Diferencial: ninguna función cambió su firma ni su salida (`export.py` solo suma una función y un nombre al `import`); `test_the_flow_issues_and_evaluates_what_calling_the_functions_directly_does` compara las estimaciones, los otros métodos, las cifras y los criterios sellados del flujo con los de las mismas horas llamando a las funciones (`small_history_one_batch`): son iguales salvo la censura (el calendario del flujo termina donde terminan los datos). AC37 queda probado con el lanzamiento repetido desde cero (el ajuste, la compuerta, el sello y las exportaciones); las dos repeticiones completas del plan, que cuestan unos 4,7 s cada una, son las reales de U21. La suite rápida midió 834 pruebas en 82,47 s (antes, 807 en 68,32 s): la unidad suma 14,2 s, más de los 8 s de D33, porque el estado de sesión es una repetición real del plan chico (unos 5,2 s una vez) y el resto son las pruebas que corren tareas de verdad; quedan 7,5 s al presupuesto de trabajo de 90 s, así que U18 debe reusar `pipeline_replayed` o ir precedida de una unidad de velocidad.

## D30 Un solo escritor: el bloqueo del proyecto 04

- **Contexto**: el bloqueo del proyecto 03 (D82, D87) con sus correcciones pasó la evaluación del proyecto 04 (U24; advertencia A12 abierta: un bloqueo que quedó por una liberación fallida rechaza a su propio proceso vivo).
- **Opciones**: (a) copiarlo; (b) copiarlo y resolver A12 reconociendo la ficha del dueño.
- **Decisión**: (a), adaptado a `FLOTSILICA_*`, con A12 documentada en el runbook (R8) como en el proyecto 04.
- **Motivo**: A12 no apareció en uso; cambiar un bloqueo probado es riesgo sin pedido.
- **Afecta**: `lock.py`; RNF16; AC31.
- **Quién**: agente de planificación.
- **Estado**: vigente. Nota de U16 (2026-11-17): `lock.py` es el del proyecto 04 (su D76 con las correcciones de U24 y F1: ficha del dueño, hora de inicio y arranque del equipo, toma anidada, otro hilo, espera del que suelta) con dos cambios. La reescritura del archivo (la toma anidada y su liberación) es `files.write_atomic` (RNF05) dentro de los mismos reintentos de la remoción, en lugar de una copia propia del archivo temporal y el reemplazo; por eso el módulo importa la biblioteca estándar y `flotsilica.files` (que solo importa la estándar), y una prueba lo comprueba. Los textos son de este proyecto: `python -m flotsilica run --run-key <corrida> --from <tarea>` y el runbook R8 (el de P4 decía R9), y el aviso de una remoción o reescritura fallida dice cuántos intentos hizo y solo habla de otro proceso con el archivo abierto si el error fue `PermissionError`. `sole_writer` entrega el `Holding` (la sección 23 decía `None`; quien llama puede ignorarlo). El módulo no lee ninguna variable `FLOTSILICA_*`: la carpeta la pasa quien llama (`paths.interim_dir`, U17). Pruebas: las 20 de P4 adaptadas (se agregó el aviso con R8 y se cambió la de las importaciones) más dos nuevas (la reescritura pasa por `files.write_atomic` y no deja archivo temporal; cada rechazo nombra `flotsilica` y R8); REDs contra un `lock.py` que lanza `NotImplementedError`; 9 mutaciones (salida 1, la reescritura sin `files`, la toma interrumpida que conserva su registro, el número reusado tomado por dueño, otro hilo aceptado, el aviso sin la excepción, soltar sin mirar la ficha, R9, sin reintentos) hacen fallar su prueba. La advertencia A12 de P4 sigue abierta y va al runbook R8 (U23).

## D31 Rutas contra la carpeta del proyecto y modo rápido aislado

- **Contexto**: una ruta relativa resuelta contra el directorio de trabajo fue un defecto de los proyectos 01 y 03; el modo rápido que escribía en salidas versionadas, del 01.
- **Opciones**: un solo camino razonable.
- **Decisión**: toda ruta relativa de la configuración, de `--config` y de `FLOTSILICA_CONFIG` se resuelve contra `FLOTSILICA_HOME` o la carpeta del proyecto; `config/pipeline.quick.toml` pone todo bajo `data/quick/`, incluidos el sello, el README, las figuras y la exportación del sitio.
- **Motivo**: lecciones de 01 B3, 01 L14 y 03 A2.
- **Afecta**: `config.py`; AC33.
- **Quién**: agente de planificación.
- **Estado**: vigente. Nota de U18 (2026-11-17): la prueba del modo rápido (`tests/e2e/test_quick_mode.py::test_quick_replay_from_other_cwd_touches_only_data_quick`) corre `make-fixture --weeks 3` y `replay --until L2017-03-29` desde un clon limpio (solo `config/` y `config/pipeline.small.toml`, que escribe la prueba: la configuración rápida con las ventanas del accesorio chico) y desde una carpeta vacía que no es el proyecto, con `FLOTSILICA_HOME` en el clon; compara tamaño y hora de modificación de todo el clon, de la carpeta de trabajo y de este proyecto antes y después. **Se desvía del plan** (sección 24.1: «una repetición propia: unos 12 s» con el accesorio completo): el accesorio completo y el calendario completo costarían unos 12 s que la suite no tiene; con tres semanas la repetición del lanzamiento mide 1,5 s y la entrega de 25 horas que sigue (`quick_closed`, con `run --only` y `run --from`) 1,4 s, y las dos se comprueban igual. El archivo `pipeline.small.toml` lleva `purge_hours = 0` porque `load_config` comprueba la partición y las ventanas de `small_view` (hechas en código, sin pasar por esa comprobación) se tocan; por eso las pruebas de la CLI no reutilizan los estados `pipeline_launched` y `pipeline_replayed` (su huella lleva `purge_hours = 24`) y construyen los suyos con los propios comandos; solo la prueba de «sin entregas pendientes» copia `pipeline_replayed`, que lee el plan y el manifiesto y no la huella. `make-fixture` crea las carpetas que faltan de su destino (un clon limpio no tiene `data/quick/`) y las quita si el generador rechaza sus argumentos; una ruta relativa que sale de la carpeta del proyecto se rechaza con 2, como en la configuración.

## D32 Lecciones de los proyectos 01 a 04 que pasan a ser requisitos

- **Contexto**: cada evaluación independiente encontró clases de defecto (plan del proyecto 04, sección 24.2; su `evaluation.md`: B1 documentación sin el registro, A1 evaluación con otra configuración, A4 una barra sin escapar en el resumen, A5 un veredicto que se lee al revés, A10 un segmentador sin relación, A11 una prueba del plan que no existía, A13 una imagen de Docker que quedaba, A14 una función auxiliar contada como prueba, A18 la suite sobre el presupuesto).
- **Opciones**: un solo camino razonable: cada clase con su prueba con nombre desde el plan.
- **Decisión**: la tabla del plan, sección 24.2, con las clases que aplican aquí (sin las de privacidad, descarga, neteo y SHAP) y las nuevas de este proyecto: valor interpolado o repetido tomado como medición, análisis usado antes de su llegada, estimación que depende del tamaño de la entrega, API que difiere del flujo, sensibilidad publicada como causa.
- **Motivo**: la clase B5 del proyecto 03 fue una prueba nombrada en el plan que nunca se escribió; nombrarlas y comprobar que existen la evita.
- **Afecta**: `tests/`; plan, sección 24.2; AC39.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D33 La suite rápida: límite de 120 s, presupuesto de trabajo de 90 s y accesorios livianos desde el principio

- **Contexto**: el proyecto 03 terminó a menos de 3 s de su límite de 150 s; el proyecto 04 pasó su límite de 120 s después de las correcciones y necesitó una unidad de velocidad (L56). Aquí un bosque de 300 árboles tarda 1,43 s por ajuste.
- **Opciones**: (a) el límite y el presupuesto del proyecto 04 (120 s y 100 s); (b) el mismo límite con un presupuesto de 90 s y un accesorio pensado para la suite.
- **Decisión**: (b). Límite de 120 s, presupuesto de 90 s medido después de cada unidad; `tests/conftest.py` falla una sesión completa que pasa el límite. El accesorio usa 12 filas por hora; el modo rápido, 5 candidatos por horizonte (solo `rf`, 20 árboles, sin `fSLF`) y entregas de 10 días; los estados caros (accesorio leído, almacén cargado, lanzamiento, repetición hasta el sello) se construyen una vez por sesión. Las pruebas lentas con nombre quedan en el plan, sección 24.1.
- **Motivo**: con 10 s menos de presupuesto que el proyecto 04 queda margen para las correcciones de la evaluación, que en el 04 sumaron unos 13 s.
- **Afecta**: `tests/conftest.py`; RNF15; AC40.
- **Quién**: agente de planificación.
- **Estado**: vigente. Nota de la segunda unidad de velocidad (2026-11-17): con las unidades hasta U17 la suite medía 81,4 s y 81,2 s (dos corridas seguidas) y ahora mide 73 s (73,1 y 72,6), con las mismas pruebas y tres más que fijan lo nuevo. `HourTables.row_values` arma las 67 columnas de una hora sin los marcos de `inputs` y `design` la llama (4047 horas de un horizonte: de 2,9 s a 0,25 s, con los mismos bytes), `_row_values` toma el historial del laboratorio como arreglos en vez de por `lab_known_at`, `write_atomic` escribe, sincroniza y cierra con el descriptor que creó el temporal y el lector simple de ARFF de las pruebas guarda los últimos archivos leídos. Lo que queda no es repetición sino trabajo que las pruebas piden: ajustes y predicciones de scikit-learn (alrededor de una quinta parte), los controles SQL de la carga sobre el almacén del accesorio estándar (unos 6 s, solo en `test_load.py`), la lectura y la escritura de archivos recién creados en Windows (alrededor de una sexta parte) y las corridas reales del flujo (`pipeline_launched` y `pipeline_replayed`, unos 4,5 s). Quedan 18 s al presupuesto de trabajo de 90 s para U18 a U23; bajar de los 60 s de la meta pide trabajo en paralelo (procesos que construyan a la vez los estados de sesión independientes) o un cambio de los controles SQL, y ambos son decisiones del dueño (D34).
  Nota de U18 (2026-11-17): la unidad suma unos 6 s a la suite (de 73,1 s a unos 79 s; sección 24.1 pide decir por qué si pasa de 8 s: no pasa, pero deja menos margen que el previsto de 4 s). Lo que cuesta: el lanzamiento rápido desde un clon limpio, 1,5 s (la prueba con nombre; el plan estimaba 12 s con el accesorio completo); la entrega de 25 horas que sigue, hecha con `run --only` y `run --from`, 1,4 s; las siete figuras de `figures`, 1,1 s (matplotlib); y unas 40 pruebas de menos de 0,25 s cada una (opciones, rechazos, códigos de salida). Los estados caros se construyen una vez por sesión (`quick_replay`, `quick_closed`) y cada prueba que escribe trabaja sobre una copia de 3,7 MB; los archivos que prueban opciones de `make-fixture` usan una semana y 4 filas por hora. No se pudo reutilizar `pipeline_launched` (ver D31).
## D34 `pytest-xdist`: no se fija

- **Contexto**: el proyecto 04 lo dejó como pendiente del dueño (su D35); una dependencia de desarrollo más requiere autorización.
- **Opciones**: (a) fijarlo; (b) no fijarlo y diseñar la suite para un proceso.
- **Decisión**: (b).
- **Motivo**: los accesorios de sesión ya son el ahorro principal; paralelizar duplicaría estados caros por proceso.
- **Afecta**: `requirements-dev.txt`.
- **Quién**: agente de planificación.
- **Estado**: vigente; pendiente del dueño si la suite se acerca al límite.

## D35 Idioma y nombres: paquete `flotsilica`, alcance de commit `flotation`

- **Contexto**: los proyectos usan un paquete corto y un alcance de commit propio.
- **Opciones**: (a) `flotation`; (b) `flotsilica`; (c) `silica`.
- **Decisión**: (b) para el paquete (`FLOTSILICA_*`, DAG `flotsilica_daily`, compose `flotsilica-airflow`) y `flotation` como alcance de los commits (`feat(flotation): …`), como pidió el orquestador.
- **Motivo**: `flotation` sola nombra el proceso y no el producto; `silica` es ambiguo con la columna. Documentación en español neutro; código e identificadores en inglés; medidas y textos del sitio en español.
- **Afecta**: todo el código; RNF13.
- **Quién**: agente de planificación (el alcance, el orquestador).
- **Estado**: vigente.

## D36 Tecnologías fuera del landing

- **Contexto**: S5 pide anotar en `LANDING-EXPANSION.md` lo que el landing no declara. Este proyecto no usa openpyxl, SHAP, numba ni lifetimes; usa NumPy, SQLite, Parquet con pyarrow, matplotlib, pytest y PostgreSQL (ya anotados) y suma lo de la API.
- **Opciones**: un solo camino razonable.
- **Decisión**: U19 agrega filas para pydantic (validación de la API, importada directamente), uvicorn (el servidor de la API) y httpx (solo en las pruebas, para el cliente de FastAPI), y suma el 05 a las filas de NumPy, SQLite, Parquet, matplotlib, pytest y PostgreSQL. SciPy no se importa: la correlación de Spearman sale de rangos de pandas.
- **Motivo**: cada módulo que el código importa es una dependencia directa documentada (lección del proyecto 03, B6).
- **Afecta**: `LANDING-EXPANSION.md`; AC38.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D37 Entorno y versiones

- **Contexto**: el `.venv` del proyecto 04 tiene Python 3.11.1, NumPy 2.4.6, pandas 2.3.3, scikit-learn 1.9.1, pyarrow 26.0.1 y matplotlib 3.11.2, y la imagen de Airflow trae Python 3.13.18 (requirements.txt del proyecto 04).
- **Opciones**: un solo camino razonable: las mismas versiones, sin lo que no se usa.
- **Decisión**: `requirements.txt` con las directas del proyecto 04 menos openpyxl y shap, y sus transitivas menos las de esos dos (`et_xmlfile`, `cloudpickle`, `numba`, `llvmlite`, `slicer`, `tqdm` si nada más las pide **[Verificar en U01 con `pip check`]**); `python-dateutil` sigue en 2.9.0.post0. `requirements-api.txt` con `-r requirements.txt`, fastapi, pydantic y uvicorn en la versión estable más reciente al construir U19 **[Verificar en U19]**, fijadas con `==`. `requirements-dev.txt` con `-r requirements-api.txt`, pytest 9.2.0 y httpx **[Verificar en U19]**.
- **Motivo**: las versiones del proyecto 04 ya pasaron `pip check` en Windows y en la imagen.
- **Afecta**: `requirements*.txt`; RNF01; AC38.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D38 Memoria: medida y con el contador nombrado

- **Contexto**: una cifra de memoria sin su contador fue una advertencia de los proyectos 02 y 03.
- **Opciones**: un solo camino razonable: `sysinfo.peak_memory` del proyecto 04.
- **Decisión**: `PeakWorkingSetSize` (y `PeakPagefileUsage`, informativo) en Windows, `ru_maxrss` en Linux; toda cifra de memoria de la documentación nombra su contador; tope de 2 GB.
- **Motivo**: el archivo pesa 185 MB y las filas canónicas, unas 737.453 × 19; el tope deja margen sin pedir más que el proyecto 04 (2,5 GB).
- **Afecta**: `sysinfo.py`; RNF03.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D39 Artefacto del modelo con huella verificada antes de cargarlo

- **Contexto**: deserializar un `pickle` sin comprobarlo ejecuta lo que traiga; el proyecto 04 lo resolvió con M03 (su D40). Aquí también lo carga la API.
- **Opciones**: un solo camino razonable.
- **Decisión**: `data/models/<model_version>.pkl` con los tres modelos, los semianchos, B*, las columnas y los modelos de comparación; su SHA-256 en `model_registry` y en el sello; `load_artifact` lee los bytes una vez, compara y recién entonces los deserializa (M03); la API y el flujo usan la misma función.
- **Motivo**: lección del proyecto 03 (D30) y del 04.
- **Afecta**: `registry.py`, `api.py`; AC20, AC28.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D40 Accesorio sintético con controles positivo y negativo y la verdad de cada marca

- **Contexto**: las pruebas no pueden leer el ARFF real en la suite rápida (D33), y un modelo que no supera a la persistencia en los datos reales podría ser un modelo roto.
- **Opciones**: un solo camino razonable: un generador con la cabecera real, el mismo calendario y una verdad conocida, como el del proyecto 04 (su D42).
- **Decisión**: `make_fixture(path, rows_per_hour = 12, seed = 0, signal = "none", weeks = None) -> FixtureTruth`: objetivo horario de proceso conocido; tramos interpolados con su rampa, repeticiones, rampas de una hora, alimentación congelada, un sensor fijo, el hueco y las horas incompletas en sus fechas reales; `% Iron Concentrate` correlacionado. `sensor_signal`: la sílice sigue a `amina_flow` de la hora con un efecto conocido (control positivo: el modelo con sensores supera a la persistencia fuera del ruido y la compuerta encuentra `amina_flow` con su signo); `lab_only`: la sílice es autorregresiva y no depende de los sensores (control negativo). `make_malformed(base, kind, out)` con una variante por regla bloqueante.
- **Motivo**: los controles prueban que el modelo puede superar a la persistencia cuando hay señal, y que la compuerta no inventa una sensibilidad cuando no la hay. Medido en U09: con `sensor_signal` (β = 0,7) un modelo honesto llega a un MAE en V1 de 0,386 contra 0,824 de la persistencia, por debajo de `leak_tripwire_ratio` × 0,824 = 0,412, así que M01 (D09) detendría el control positivo; ese control se lanza con `leak_tripwire_ratio = 0,2` (en la configuración de la prueba, no en `pipeline.toml`) y el negativo (0,276 contra 0,286) corre con el 0,5 por defecto. La trampa está calibrada para el archivo real, donde un modelo honesto queda cerca de la persistencia (cociente 0,99 en V1, D09).
- **Afecta**: `tests/fixtures/`; AC15, AC24.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D41 Contradicciones con el sitio

- **Contexto**: research.md listó las diferencias entre `marca-personal/src/i18n/projects/flotation-silica.ts` y los datos; este plan suma las suyas (horizontes, frescura, API, compuerta).
- **Opciones**: un solo camino razonable: proponer cada cambio con su motivo en `SITE-UPDATES.md` y decidir el texto del dueño.
- **Decisión**: las filas del plan, sección 30; U23 las escribe con las cifras de la corrida real; las que dependen del resultado lo dicen.
- **Motivo**: el sitio debe decir lo que el proyecto hizo y encontró (S9), incluidos los «no supera».
- **Afecta**: `SITE-UPDATES.md`; la página del sitio.
- **Quién**: agente de planificación; el texto, el dueño.
- **Estado**: pendiente del dueño (el texto).

## D42 Unidades de trabajo, commits y estrategia de entrega

- **Contexto**: el proyecto 04 tuvo 31 unidades y unas 12.400 líneas planificadas; este tiene un archivo, ninguna descarga, ningún cliente ni capa de privacidad.
- **Opciones**: (a) la estructura del proyecto 04; (b) menos unidades, sin las de descarga, neteo, BG/NBD, SHAP, costos y privacidad, y con las de frescura, horizontes, rango, compuerta y API.
- **Decisión**: (b). 23 unidades y unas 9.100 líneas escritas a mano (plan, sección 27); cada unidad de riesgo alto en su propio commit (U01, U04, U09, U10, U13, U14, U15, U16, U17, U19, U20, U21); alcance `flotation`; estrategia `ask-on-risk` heredada del documento de seguimiento.
- **Motivo**: unas 400 líneas por unidad como guía, no como tope; menos unidades porque hay menos superficie, no porque se recorte una prueba.
- **Afecta**: plan, sección 27; el documento de seguimiento.
- **Quién**: agente de planificación.
- **Estado**: vigente; la estrategia de PR, pendiente del dueño.

## D43 Sin datos personales; lo que igual se comprueba en lo publicado

- **Contexto**: el archivo tiene solo lecturas de una planta y análisis de laboratorio, sin personas ni clientes; el proyecto 04 necesitó una capa de privacidad (sus D26 y D27) que aquí no aplica.
- **Opciones**: (a) copiar la capa de privacidad; (b) no copiarla y comprobar solo que lo publicado no lleve rutas del equipo ni el nombre del usuario.
- **Decisión**: (b). Ningún tamaño mínimo de celda ni enmascarado; `test_published_files_carry_no_local_path` busca en los bytes versionados (`outputs/`, `reports/`, `dashboard/`, `docs/figures/`) rutas absolutas y el directorio de usuario.
- **Motivo**: no hay a quién proteger en los datos; una ruta local en un archivo publicado sí expone el equipo.
- **Afecta**: `tests/integration/test_published_bytes.py`; RNF12.
- **Quién**: agente de planificación.
- **Estado**: vigente. Nota de U15 (2026-11-17): la prueba recorre los Parquet, los JSON del sitio, el sello y el resumen, el HTML y las figuras de una corrida; en lo comprimido (un Parquet, un PNG) busca solo el directorio de usuario, su nombre, la carpeta temporal y las carpetas de la corrida, y en lo que es texto suma las letras de unidad y las carpetas de usuario de cualquier equipo, porque un patrón corto aparece por azar en bytes comprimidos; otra prueba comprueba la búsqueda sobre archivos que sí tienen una ruta.

## D44 La línea de comandos: la misma lista de tareas, sin escribir ningún paso aparte

- **Contexto**: RF25 pide una CLI que ejecute las mismas tareas, en el mismo orden y con las mismas funciones que el DAG; AC32 pide códigos de salida 0, 1, 2 y 3, una combinación incompatible que sale con 2 antes de escribir y una prueba por opción documentada. El proyecto 04 ya resolvió esto (su D82) y su evaluación encontró opciones ignoradas en silencio (01 B2, 02 B1).
- **Opciones**: (a) la CLI del proyecto 04 con sus dos correcciones; (b) una CLI nueva con otro reparto de órdenes.
- **Decisión**: (a). `cli.py` llama a `pipeline.run_all`, `run_task` y `replay`, a `figures.write_figures` y a `reporting.sync_block`; no escribe ningún paso. Códigos: 0 (también sin entregas pendientes), 1 una tarea falló (también un `RunStateError` que no es un rechazo), 2 uso, configuración, `RunRefusedError` (corrida cerrada, bloqueo tomado) o una ruta que sale del proyecto, 3 `ValidationError` (la fuente y la entrega rechazadas llegan como esa). Los textos de cada rechazo están en `texts.py`. `docs-sync` copia el Markdown del resumen tal como está, con su propio `## Resultados`, entre `<!-- results:start -->` y `<!-- results:end -->` del README; sin README (el modo rápido no tiene), sin resumen o sin los dos marcadores sale con 2 sin escribir; las tablas del diccionario de datos que menciona el plan, sección 25, son de U23. `make-fixture` importa el generador de `tests/fixtures/make_fixture.py` al correr (como el proyecto 04) y, si la carpeta `tests` no está, sale con 2 y dice dónde está el generador. Una prueba por opción (`test_every_documented_option_changes_the_result[<opción>]`) y una prueba que compara las opciones que declara el analizador con las que tienen caso, para que una opción nueva (las de `serve`, en U19) no quede sin prueba. `serve` no está: queda como un subcomando más de `build_parser` y una rama de `_execute`.
- **Motivo**: un solo camino razonable; una opción que cambia nada en silencio fue un defecto de dos proyectos.
- **Afecta**: `cli.py`, `__main__.py`, `texts.py`; RF25; AC32, AC33.
- **Quién**: agente de construcción (U18).
- **Estado**: vigente.

## D45 La API de estimación (U19): versiones fijadas, lo que valida, lo que rehúsa servir y lo que cambia del plan

- **Contexto**: U19 cierra D27 y los **[Verificar]** de D37. Las versiones se eligieron el 2026-11-17 con `https://pypi.org/pypi/<nombre>/json` (fecha de subida del primer archivo de cada versión): para cada directa, la última estable (sin versiones previas) con al menos 14 días de antigüedad. FastAPI 0.163.1 (2026-11-15) y pydantic 2.14.3 (2026-11-05) son más nuevas y quedan fuera por esa regla.
- **Opciones**: (a) la última versión del día; (b) la última con 14 días o más; (c) `httpx2` en lugar de `httpx` para el cliente de prueba.
- **Decisión**: (b), en `requirements-api.txt`: `fastapi` 0.162.0 (2026-10-23, 24 días), `pydantic` 2.14.2 (2026-10-29, 18 días) y `uvicorn` 0.54.0 (2026-09-25, 52 días); en `requirements-dev.txt`: `httpx` 0.28.1 (2024-12-06, 710 días; es la última). Transitivas, las más nuevas con 14 días o más que lo que piden las directas permite: `starlette` 1.10.0 (2026-10-24), `pydantic_core` 2.50.2 (la que exige pydantic 2.14.2, `==`), `typing_extensions` 4.16.0 (la exigen pydantic y anyio), `typing-inspection` 0.4.4 (2026-08-12; la 0.4.5 tiene 12 días), `annotated-types` 0.8.0, `annotated-doc` 0.0.5 (2026-07-28; la 0.0.6 tiene 6 días), `anyio` 4.16.0 (2026-11-01), `idna` 3.20, `click` 8.5.0 (2026-08-26; la 8.5.1 tiene 10 días), `h11` 0.16.0, `colorama` 0.4.6 y `opentelemetry-api` 1.45.2 (FastAPI 0.162.0 la pide como dependencia base, no como extra); en el archivo de desarrollo, `certifi` 2026.10.23 y `httpcore` 1.0.9. `colorama` pasa del archivo de desarrollo al de la API porque `click` la pide en Windows. `pip check` no encuentra requisitos rotos. **Desvío**: Starlette 1.10 prefiere `httpx2` para su cliente de prueba y, si solo está `httpx`, avisa una vez al importar que usar `httpx` está en desuso; se mantiene `httpx` (el plan y la tarea lo fijan, y no se suma una dependencia sin pedido) y `pyproject.toml` deja fuera de los avisos solo ese mensaje. Cuando una versión nueva de Starlette quite el `httpx`, las pruebas de la API fallarán al importar el cliente: el cambio es fijar `httpx2` en su lugar. `api.py` tiene `create_app(cfg)`: lee el sello, se niega a servir (`ApiStartError`) si no hay sello o si la configuración no es la sellada (las estimaciones no serían las del flujo), abre el almacén solo para leer el registro (`mode=ro`) y carga el artefacto con `registry.load_registered_bundle` (huella antes de deserializar, M03); no toma rutas de salida y no escribe. `GET /health` da `model_version`, `config_sha256`, el estado del sello (`launch` o `launch_and_test`, según tenga o no la parte de la prueba) y el semiancho de cada horizonte. `POST /estimate` arma `IssueInputs` con `hours.aggregate_rows` (lecturas), `features.lab_known_at` (la regla de llegada: `sample_hour + latency_hours <= issue_at`, el instante de llegada incluido) y `features.missing_inputs` (historia corta), y llama a `scoring.score_issue`: cada hora cerrada da lo mismo que el flujo guardó, con igualdad exacta de `float` (AC28). Responde `estimates` (horizonte, hora objetivo, estado y motivo, estimación, rango, B*, bloque), la persistencia (el último análisis llegado) y las entradas que usó. Una hora con pocas lecturas no es un 422: cada horizonte vuelve `missing_inputs` con su motivo y sin número, como en el flujo. Rechaza con 422, sin estimar y con un código: `invalid_request` (formato: números finitos y no texto ni booleanos, ningún campo de más, estado solo `fresh`, sílice y alimentación de 0 a 100, listas dentro de sus topes `rows_per_hour` y `[api] max_lab_history`, instantes como texto ISO y sin zona, con su tipo y su campo pero nunca el valor recibido), `not_on_the_hour`, `duplicate_sample_hour`, `analysis_after_issue` y `short_lab_history`; una estimación no finita (M04) es `estimate_refused`; un fallo inesperado es un 500 de cuerpo fijo, sin traza ni ruta. Las páginas de documentación y el esquema OpenAPI no se sirven (`docs_url`, `redoc_url` y `openapi_url` en `None`). `python -m flotsilica serve [--config RUTA] [--host DIRECCIÓN] [--port N] [-v]` corre `uvicorn.run(app, host=cfg.api.host, port=...)`; `--host` existe solo para ser rechazado: otro valor que `127.0.0.1`, o un puerto fuera de 1 a 65535, sale con 2 antes de leer la configuración, de importar la API o de cargar nada; sin sello, con otra configuración o con un artefacto que no es el registrado también sale con 2 y no levanta el servidor. Los textos están en `texts.py`.
- **Motivo**: la API y el flujo comparten `score_issue` y las reglas de llegada y de frescura, de modo que no pueden diferir (AC28); servir solo el modelo sellado y rehusar otra configuración evita una API que diga lo que el flujo nunca diría. Las listas y los instantes se validan antes de estimar porque el servicio recibe datos de quien lo llame, aunque sea en el mismo equipo (RNF11).
- **Afecta**: `api.py`, `cli.py`, `texts.py`, `pyproject.toml`; `requirements-api.txt`, `requirements-dev.txt`; `LANDING-EXPANSION.md` (filas de pydantic, uvicorn y httpx, y el 05 en las de NumPy, SQLite, Parquet, matplotlib, pytest y PostgreSQL; FastAPI ya está en el landing); RF24; AC28, AC38; D27, D36, D37.
- **Desvíos del plan**: (1) el plan dice «`sealed_history`»; ese accesorio no existe y la paridad corre sobre `small_history` (el lanzamiento y tres entregas del accesorio chico, con su sello y la parte de la prueba, hecho con las mismas funciones): compara las 72 estimaciones de las 24 horas de su bloque de prueba, en 26 instantes. (2) Los topes de las listas salen de la configuración y no de constantes del módulo, así que los modelos de pydantic se arman dentro de `create_app` y `api.py` no usa `from __future__ import annotations`. (3) Las decisiones de este archivo llegan a D44: este es D45 (el plan nombra D36 y D37). (4) `openapi_url=None` además de `docs_url` y `redoc_url`. (5) La persistencia va en la raíz de la respuesta, como en el plan, y B* por horizonte.
- **Quién**: agente de construcción (U19).
- **Estado**: vigente; publicar la API, pendiente del dueño (D27).
