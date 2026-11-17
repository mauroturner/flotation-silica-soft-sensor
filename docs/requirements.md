# Requerimientos: sílice en el concentrado, sin esperar al laboratorio

Fecha: 2026-11-17. Base: `docs/research.md` y una comprobación del agente de planificación que leyó **solo las filas anteriores al 2017-07-31** (sección 4). Las suposiciones se marcan como **[Supuesto]**; lo que hay que comprobar al programar, como **[Verificar]**; lo deducido sin fuente, como **[Inferido]**. Las decisiones citadas (Dxx) están en `decisions.md`; el diseño, en `plan.md`.

## 1. Problema

En una planta de flotación de mineral de hierro, la sílice del concentrado (la impureza que define la calidad del producto) se mide en el laboratorio una vez por hora, y el resultado llega horas después de tomada la muestra. Mientras tanto, el aire, la pulpa y los reactivos cambian cada pocos segundos: cuando el análisis llega, el proceso ya es otro.

Quién lo sufre:

- **Operación de la planta**: ajusta aire y reactivos mirando un análisis viejo, sin saber si la calidad ya se movió.
- **Calidad**: se entera tarde de un concentrado fuera de especificación.
- **Ingeniería de procesos**: no sabe si los sensores de la planta dicen algo sobre la sílice que el último análisis no diga ya.

Qué cuesta hoy:

- Con un análisis que tarda 2 horas **[Supuesto: el archivo no trae la latencia; D06]**, repetir el último análisis conocido se equivoca en 0,50 puntos de sílice por hora en promedio sobre las horas con análisis nuevo de la validación (sección 4), con un objetivo de media 2,32 y desviación 1,13 (research.md).
- El 15,3 % de las horas de entrenamiento y validación no trae un análisis nuevo: el valor está repetido de la hora anterior o interpolado entre dos análisis (sección 4). Quien mira el archivo cree tener una medición por hora y no la tiene.

## 2. Objetivo

Un flujo que carga cada día de lecturas de la planta, las valida, reconstruye qué análisis de laboratorio había llegado en cada instante y, al cierre de cada hora, estima la sílice del concentrado de la hora que acaba de cerrar y de las dos siguientes, con un rango del 80 %, antes de que llegue su análisis; sigue el error de cada estimación cuando el análisis llega y deja las tablas de un tablero de Power BI en modelo estrella, el diseño del tablero en HTML, una exportación pequeña para el sitio y una API local que da la misma estimación. El modelo se compara con lo que haría un operador (repetir el último análisis o promediar los últimos) con criterios fijados antes de construir (sección 8.1), y la prueba se evalúa una sola vez, bajo un sello (D18).

## 3. Alcance

Incluido:

- Fuente: el archivo ARFF de OpenML 43311, espejo del conjunto «Quality Prediction in a Mining Process» de Kaggle (Eduardo Magalhães Oliveira, CC0), fijado por su SHA-256; lo coloca el dueño en `data/raw/`; el flujo no lo descarga (D02).
- Unidad: la hora del objetivo, con su análisis de laboratorio tomado de la primera fila de la hora (D04). Solo los **análisis frescos** son objetivo o rasgo; los valores interpolados entre dos análisis y los repetidos de la hora anterior no son una medición (D05).
- Latencia del laboratorio L = 2 h (supuesto, d = 1), con L = 3 y L = 4 como sensibilidad (D06). Horizontes: la hora que cerró (H0) y las dos siguientes (H1, H2) (D07).
- Partición en el tiempo: entrenamiento, V1, V2 y prueba, con purgas de 24 h; la prueba (2017-08-01 a 2017-09-09) nunca se usó para modelar (D10).
- Líneas base B0-B3 y la base más fuerte B* de cada horizonte, elegida en V1 (D13); candidatos de scikit-learn (`HistGradientBoostingRegressor` y `RandomForestRegressor`), con objetivo en nivel o en cambio desde el último análisis, elegidos en V1 y reajustados con entrenamiento y V1 (D14); rango del 80 % por conformal partido en V2 (D15).
- Criterios C01-C10 fijados antes de construir, con lo esperable dicho (D16); intervalos por remuestreo de días (D17).
- Sensibilidades del modelo como asociaciones exploratorias, publicadas solo si pasan una compuerta de estabilidad fijada antes (D20).
- Operación simulada: un lanzamiento con todo lo anterior a la prueba, 40 entregas diarias y un cierre que deja llegar los dos últimos análisis; dentro de cada entrega, una emisión por hora con lo que se sabía en ese instante (D21).
- Modelo congelado en el lanzamiento y sello con una huella que cubre cada clave que cambia un valor sellado (D18, D19).
- Orquestación en Apache Airflow sobre Docker Compose y una CLI equivalente para Windows, con un solo escritor por carpeta de datos (D28-D30).
- Una API local de estimación con FastAPI, de solo lectura, que usa la misma función que el flujo (D27).
- Tablas para Power BI en Parquet, diseño del tablero en HTML, exportación para el sitio en JSON con manifiesto, documentación con la estructura del proyecto 01 (S10).

Fuera de alcance:

- Descargar el archivo desde OpenML o Kaggle por programa: Kaggle pide una cuenta y la descarga de OpenML no se verificó byte a byte (D02).
- Comparar el ARFF byte a byte con el CSV de Kaggle (research.md).
- Una latencia real del laboratorio de esta planta: no está en el archivo ni en una fuente pública (D06).
- Acciones de control: las sensibilidades son asociaciones del modelo, nunca una receta para mover el aire o los reactivos (D20).
- Reentrenar dentro del flujo diario: el modelo se ajusta una vez y se congela (D18).
- Publicar la API fuera del equipo (D27).
- Construir el `.pbix` en Power BI Desktop (interfaz gráfica; S4) y publicarlo.
- Redes neuronales o librerías fuera de S5 (TensorFlow está en el landing, pero nada lo pide aquí; D14).

## 4. Datos medidos

Fuente (research.md): `05-Mining-Flotation-Silica/data/raw/openml-43311-quality-prediction-mining-process.arff`, 185.243.565 bytes, SHA-256 `a25122979ba8c5fb9c12e361db61032efc6892a24b5746cc8309da601d9639b2`, MD5 `c1091ada99b288fb881077dbd43ff562` (el que publica OpenML). `@RELATION Quality-Prediction-in-a-Mining-Process`; 24 atributos `STRING` (la fecha y las 23 columnas de Kaggle); números con coma decimal; 737.453 filas; 4.097 horas del 2017-03-10 01:00 al 2017-09-09 23:00; un hueco de 318 h (2017-03-16 06:00 a 2017-03-29 11:00); 4.095 horas con 180 filas y dos con 174 y 179. La cabecera del archivo pregunta, entre otras cosas, «How many steps (hours) ahead can we predict % Silica in Concentrate» y si se puede predecir «whitout using % Iron Concentrate column» (comentarios de la cabecera, líneas 11 y 12).

De research.md (sin la prueba salvo conteos): objetivo previo a la prueba con media 2,32, desviación 1,13 y asimetría 0,99; autocorrelación 0,76, 0,66, 0,58, 0,36, 0,22 y 0,19 a 1, 2, 3, 6, 12 y 24 h; `% Iron Concentrate` con correlación −0,80 con el objetivo en la misma hora; la partición aleatoria da R² 0,565 contra −0,511 en bloques de tiempo con el mismo modelo; media del objetivo 2,56 en el entrenamiento y 2,04 en la validación; laboratorio de alimentación constante dentro de cada hora y con tramos sin cambio de hasta 792 h; 310 horas del archivo con el objetivo en rampa lineal dentro de la hora; en la validación (todas las horas), persistencia con un rezago MAE 0,452, primera mirada de `HistGradientBoostingRegressor` 0,531.

**Comprobación del agente de planificación, solo antes de la prueba.** Se leyó el ARFF fila por fila y la lectura **se detuvo en la primera fila con fecha 2017-07-31 o posterior**: ninguna fila del día de purga 2017-07-31 ni de la prueba entró en memoria (las filas están en orden de fecha hasta ese punto: comprobado). 560.333 filas y 3.113 horas, igual que research.md; la lectura con el módulo `csv` tardó 1,90 s y con la conversión de los números 5,66 s; la huella de todo el archivo, 0,12 s. Intérprete del `.venv` del proyecto 04 (Python 3.11.1, pandas 2.3.3, scikit-learn 1.9.1), con `-I`; los scripts (`p01_load.py` a `p05_refit.py`) y sus salidas quedaron fuera del repositorio (`decisions.md`, encabezado).

Bloques, por hora del objetivo (D10):

| Bloque | Ventana | Horas con valor | Rampa | Interpoladas | Repetidas | Frescas |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Entrenamiento | 2017-03-10 01:00 a 2017-05-31 23:00 | 1.673 | 190 | 139 | 165 | 1.369 |
| Purga | 2017-06-01 | 24 | | | | |
| V1 | 2017-06-02 a 2017-06-30 | 696 | 14 | 8 | 58 | 630 |
| Purga | 2017-07-01 | 24 | | | | |
| V2 | 2017-07-02 a 2017-07-30 | 696 | 21 | 12 | 87 | 597 |
| Purga | 2017-07-31 | 24 | | | | (no leída) |
| Prueba | 2017-08-01 a 2017-09-09 | 960 (research.md, solo conteo) | | | | (no calculada) |

- **Los valores interpolados no son mediciones.** Antes de la prueba hay 66 tramos de horas en rampa (mediana 2 h, máximo 17 h; 32 de una sola hora). En los 159 pares de horas en rampa consecutivas, la pendiente por fila es la misma, y las 159 horas interiores de los tramos tienen su primer valor exactamente sobre la recta que va del análisis del principio del tramo al del final: son una interpolación lineal entre dos análisis, que además contiene el análisis futuro (D05).
- **Los valores repetidos tampoco.** El 92,8 % de los valores horarios tiene a lo sumo dos decimales (el 99,9 % de las horas sin rampa). Una hora exactamente igual a la anterior (la comparación que aplica el código, `hours.py`, y con la que se midieron estos recuentos; comparar a dos decimales es una opción del dueño, plan, sección 29, ítem 3) ocurre en el 9,9 % de los pares del entrenamiento, el 8,3 % de V1 y el 12,5 % de V2, con tramos de valores idénticos de hasta 39 h (38 tramos de 3 h o más, 290 horas). Con dos decimales, la desviación del objetivo y su autocorrelación, dos análisis distintos iguales por azar serían del orden del 0,5 % de los pares **[Inferido]** (D05).
- **La persistencia de research.md está ayudada por esas horas.** Sobre 2017-06-02 a 2017-07-30, repetir el valor de la hora anterior da MAE 0,4517 en las 1.416 horas (la cifra de research.md) y 0,5049 en las 1.250 horas con un análisis fresco.
- `air_flow_04` y `air_flow_05` quedan constantes dentro de la hora en 460 horas del entrenamiento y 4 de V2 (research.md: «no investigado»).

Líneas base y candidatos (MAE sobre las horas con análisis fresco y con 24 análisis frescos de historia; rasgos conocidos al cierre de la hora de emisión con L = 2 h; candidatos ajustados en el entrenamiento; ninguna cifra de la prueba). Filas: entrenamiento 1.345, V1 630, V2 597 en H0.

| Método | H0 V1 | H0 V2 | H1 V1 | H1 V2 | H2 V1 | H2 V2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| B0 media del entrenamiento | 0,819 | 0,923 | 0,819 | 0,923 | 0,819 | 0,923 |
| B1 persistencia (último análisis fresco) | 0,474 | 0,533 | 0,556 | 0,669 | 0,619 | 0,724 |
| B2 media de los últimos 3 análisis frescos | 0,488 | 0,547 | **0,553** | 0,628 | **0,606** | 0,687 |
| B2 media de los últimos 6 | 0,535 | 0,590 | 0,586 | 0,645 | 0,628 | 0,682 |
| B3 ridge sobre sensores | 0,717 | 0,981 | 0,701 | 0,923 | 0,703 | 0,878 |
| Mejor candidato en V1 | **0,471** (`rf`, sensores + laboratorio + alimentación, cambio) | 0,542 | 0,558 (`rf`, sensores + laboratorio, nivel) | 0,633 | **0,599** (`rf`, sensores + laboratorio + alimentación, nivel) | 0,694 |
| El mismo, reajustado con entrenamiento y V1 | | 0,537 | | 0,622 | | 0,690 |
| Mejor solo laboratorio (`rf`, cambio) | 0,480 | 0,532 | 0,579 | 0,664 | 0,627 | 0,715 |
| Mejor solo sensores (`rf`, nivel) | 0,639 | 0,783 | 0,652 | 0,800 | 0,660 | 0,792 |

- **En V2, ningún candidato supera a su base fuera del ruido** (remuestreo de 2.000 días, intervalo del 95 % de la diferencia de MAE): H0, el elegido menos la persistencia, de −0,009 a 0,028 (reajustado: −0,019 a 0,029); H1, el reajustado menos la media de 3, de −0,065 a 0,052; H2, de −0,087 a 0,091. Frente a la persistencia, H1 y H2 quedan cerca (de −0,103 a 0,007 y de −0,111 a 0,044, reajustados).
- **Los sensores no agregan sobre la historia del laboratorio**: en H0, el mejor con sensores menos el mejor solo con laboratorio, de −0,001 a 0,021 en V2. **Los sensores solos sí dicen algo**: el mejor solo con sensores menos la media del entrenamiento, de −0,242 a −0,042 en V2.
- **Sesgo**: en V2, el elegido de H0 estima en promedio 0,110 de más (reajustado, 0,104); el de H1, 0,154 (0,127); el de H2, 0,231 (0,216); la persistencia, 0,000 en H0. Es el cambio de nivel entre bloques (D11).
- **Rango del 80 %** (conformal con los residuos de V1, cubriendo V2): semianchos 0,704, 0,820 y 0,904; cobertura en V2 de 0,762, 0,744 y 0,767.
- **Latencia** (V1 y V2, 1.227 horas): persistencia 0,503, 0,611 y 0,670 con L = 2, 3 y 4 h; el elegido de H0 reajustado a cada L, 0,505, 0,617 y 0,666.
- **Sensibilidades** (D20): sobre el mejor candidato con sensores de H0, el aumento del MAE al permutar las tres columnas de cada sensor no pasa de 0,0012 en V1 ni en V2 para ninguno de los 19; el signo de la dependencia parcial cambia entre el modelo y cinco reajustes con días remuestreados en 11 de los 19 sensores, y los 8 que lo conservan no llegan a la importancia mínima. Con la compuerta de D20, **ninguno pasa**.
- **Tiempo de ajuste** (este equipo): `HistGradientBoostingRegressor` 0,29 s de mediana; `RandomForestRegressor` con 300 árboles, 1,43 s (máximo 2,40 s), sobre unas 1.345 filas y hasta 65 columnas.

Entorno: Python 3.11.1 en Windows (el único instalado); la imagen `apache/airflow:3.4.0` trae Python 3.13.18 (proyectos 01 a 04).

## 5. Requerimientos funcionales

- **RF01 Fuente fijada.** `fetch_source` lee `source.path` solo si su tamaño es `source.accepted_bytes` y su SHA-256 es `source.accepted_sha256`; si falta, dice cómo obtenerlo (runbook R1) y la corrida termina rechazada sin escribir; si la huella difiere, también (V01).
- **RF02 Lectura estricta.** El ARFF se lee como texto no confiable: UTF-8, cabecera exacta (`@RELATION` y los 24 `@ATTRIBUTE` configurados, en orden, todos `STRING`), `@DATA`, cada fila con 24 campos, cada uno entre apóstrofos o un entero sin apóstrofos (`-?[0-9]+`; 28.124 de las 560.333 filas anteriores a la prueba del archivo real lo traen así), fecha `YYYY-MM-DD HH:00:00`, números con coma decimal, sin campos vacíos; topes de bytes, de filas y de largo de línea; filas en orden de fecha; ninguna hora con más de `hours.rows_per_hour` filas (V02-V07).
- **RF03 Filas y horas canónicas.** Se escribe `data/interim/source_rows.parquet` (`row_id`, `hour`, `row_in_hour` y los 19 sensores) y `data/interim/source_hours.parquet` (una fila por hora con los cuatro valores de laboratorio de la primera fila, las filas de la hora, las marcas de D05 y si la alimentación cambia dentro de la hora, para V24), con un manifiesto de huellas escrito al final. Las filas 2 a n de las cuatro columnas de laboratorio no se guardan.
- **RF04 Frescura del laboratorio.** Cada hora del objetivo es `fresh`, `interpolated` (hora en rampa cuya hora anterior también está en rampa) o `held` (igual a la hora anterior, sin ser interpolada); cada hora de alimentación lleva las horas desde su último cambio. Solo un análisis fresco es objetivo o rasgo (D05).
- **RF05 Entregas.** `deliver` publica la siguiente entrega pendiente con su manifiesto: el lanzamiento `L2017-07-31` (todas las horas hasta el 2017-07-31 23:00), las diarias `D2017-08-01` a `D2017-09-09` y el cierre `C2017-09-10`, sin filas, que lleva el reloj hasta la llegada del último análisis (2017-09-10 01:00) y no emite. Sin pendientes, `no_delivery` (D21).
- **RF06 Validación de la entrega.** Reglas del plan (sección 6), con filas y horas afectadas y la forma en que cada regla se agrega entre corridas; reporte JSON y Markdown por corrida.
- **RF07 Rechazo sin daño.** Con una regla bloqueante, la entrega pasa a cuarentena, la corrida termina `rejected` y el almacén, los Parquet, el HTML, la exportación del sitio y el sello quedan como estaban, byte a byte.
- **RF08 Carga y disponibilidad.** Las filas de la entrega se agregan a SQLite en una transacción; cada análisis queda con su hora de muestra y su hora de llegada (`available_at = hora + L`); `staging` y los marts se reconstruyen con SQL versionado y controles en SQL. `load` se niega sin una validación aprobada de esa corrida y si la entrega la cargó otra corrida.
- **RF09 Rasgos en el instante de emisión.** Para un instante de emisión `t` (el cierre de una hora) y un horizonte H, los rasgos usan solo las lecturas de la hora `t − 1` y los análisis frescos con `available_at ≤ t`; nunca la hora del objetivo de H1 o H2, `% Iron Concentrate`, una fila de laboratorio que no sea la primera, una marca de rampa, el número de fila, una variable de calendario ni nada con hora posterior a `t` (D12).
- **RF10 Partición en el tiempo.** Los bloques de D10 por hora del objetivo; cada borde entre bloques con una purga de al menos `split.purge_hours`; las horas de las purgas no entran en ningún bloque.
- **RF11 Líneas base.** B0 (media de los análisis frescos del entrenamiento), B1 (persistencia: el último análisis fresco conocido), B2 (media de los últimos k análisis frescos, k elegido en V1 entre 3, 6, 12 y 24) y B3 (ridge sobre los agregados de sensores de la hora de emisión), por horizonte (D13).
- **RF12 Base más fuerte.** B*_H es la de menor MAE en V1 entre B1 y B2 para cada horizonte; en un empate a 10⁻⁶, B1. Se elige en el lanzamiento y se sella.
- **RF13 Modelo.** Para cada horizonte, los candidatos de la grilla (dos familias, cuatro conjuntos de rasgos, dos formas del objetivo) se ajustan en el entrenamiento; se elige el de menor MAE en V1; se reajusta con entrenamiento y V1; el artefacto se guarda con su SHA-256 y solo se carga si la huella coincide (D14, D39).
- **RF14 Rango del 80 %.** El semiancho de cada horizonte es el cuantil conformal de los residuos absolutos del modelo reajustado en V2 (`ceil((n + 1) · 0,8) / n`); la estimación se publica con su rango (D15).
- **RF15 Lanzamiento congelado y sello.** El lanzamiento elige, reajusta, calibra el rango, elige B* y corre la compuerta de sensibilidades, registra el artefacto y escribe la parte del lanzamiento del sello (`reports/model_seal.json`) con un `config_sha256` que cubre cada clave que cambia un valor sellado; las corridas siguientes reusan el artefacto sin cambios (D18).
- **RF16 Emisión hora por hora.** Cada corrida emite, para cada instante de emisión de su entrega, una estimación por horizonte con su rango, la persistencia y B*, con la versión del modelo y la corrida; una estimación nunca cambia; una hora sin las entradas necesarias queda registrada como `missing_inputs` con el motivo (D21).
- **RF17 Seguimiento.** Cada corrida une cada estimación con su análisis cuando este llegó (`available_at ≤ as_of`) y guarda el error del modelo, de la persistencia y de B*; las estimaciones de horas fuera de los datos quedan marcadas como censuradas (D22).
- **RF18 Evaluación una sola vez.** Cuando el reloj alcanza la llegada del último análisis de la prueba (el cierre `C2017-09-10`), se calculan C01-C10 y las variantes de D16 y se escriben en el sello. Con otra configuración que la sellada, el resultado se guarda como posterior al sello y no reemplaza el sellado; mientras el sello no tiene la parte de la prueba, una evaluación con otra configuración se rechaza antes de escribir (lección D89 del proyecto 04).
- **RF19 Resumen honesto.** `reports/evaluation_summary.json` y `.md` dicen el veredicto de cada criterio según su número, incluido «no supera»; después del sello, un almacén sin las filas selladas toma los criterios del sello, cada uno comprobado contra su entrada; el bloque de resultados del README se copia del resumen entre marcadores.
- **RF20 Sensibilidades con compuerta.** En el lanzamiento, para cada uno de los 19 sensores, la importancia por permutación agrupada en V1 y en V2 y la dirección de la dependencia parcial en el modelo y en cinco reajustes con días remuestreados; un sensor se publica como «asociación estable» solo si pasa la compuerta de D20; en la evaluación, se informa si conserva el signo en la prueba (C09). Todo se rotula como asociación del modelo, no como causa.
- **RF21 Modelo estrella.** Se exportan a `outputs/powerbi/` las dimensiones y los hechos del plan en Parquet, con claves únicas e integridad referencial.
- **RF22 Diseño del tablero.** Se genera `dashboard/powerbi-design.html` desde una especificación del modelo semántico: tablas, relaciones, medidas DAX, carga en Power Query y cinco páginas con vistas previas de datos reales.
- **RF23 Exportación para el sitio.** Se escriben en `outputs/site/` cinco JSON pequeños con el contrato del plan (sección 21) y al final `manifest.json` con el tamaño y la huella de cada uno; las reglas acumuladas se leen una vez, de la última corrida cargada.
- **RF24 API de estimación.** `python -m flotsilica serve` levanta en `127.0.0.1` una API con `GET /health` y `POST /estimate`, que recibe las lecturas de una hora y los últimos análisis y devuelve las tres estimaciones con su rango usando la misma función que el flujo y el artefacto sellado; no escribe nada (D27).
- **RF25 Orquestación.** Un DAG de Airflow (`flotsilica_daily`) en Docker Compose y una CLI (`python -m flotsilica run`, `replay`, `task`) ejecutan la misma lista de tareas, en el mismo orden, con las mismas funciones; un solo proceso escribe una carpeta de datos a la vez (D28-D30).
- **RF26 Documentación.** README con la narrativa del proyecto 01, diccionario de datos, ficha del modelo, registro de decisiones, runbook, paso a paso, advertencias de las revisiones y evaluación independiente, con figuras generadas desde los archivos del sitio.

## 6. Requerimientos no funcionales

- **RNF01 Reproducibilidad.** Versiones fijadas con `==` (D37), semillas fijas, `n_jobs = 1`, ajustes sin parada temprana. Dos repeticiones completas dan Parquet y JSON con el mismo contenido, salvo las columnas de la corrida.
- **RNF02 Rendimiento** (este equipo, medido en U21). Repetición completa (lanzamiento, 40 diarias, cierre y la corrida sin entrega) ≤ 15 min; lectura del ARFF y lanzamiento ≤ 6 min; corrida diaria ≤ 30 s; repetición completa en modo rápido ≤ 1 min; prueba de Docker ≤ 10 min. **[Supuesto]**: lectura de unos 8 s (sección 4: 5,66 s para el 76 % de las filas), unas 84 fits del lanzamiento (42 bosques de 1,4 s y 42 de 0,3 s), los reajustes de la compuerta y unos 2 s por corrida diaria.
- **RNF03 Memoria, con el contador nombrado.** Pico del conjunto de trabajo ≤ 2 GB: en Windows, `PeakWorkingSetSize` de `GetProcessMemoryInfo`; en Linux, `ru_maxrss` (KiB); `PeakPagefileUsage` informativo. Toda cifra de memoria nombra su contador (D38).
- **RNF04 Portabilidad.** La CLI y la API corren en Windows 10 con Python 3.11; el DAG, en `apache/airflow:3.4.0` (Python 3.13.18). Toda ruta relativa de la configuración, de `--config` y de `FLOTSILICA_CONFIG` se resuelve contra `FLOTSILICA_HOME` o la carpeta del proyecto, nunca contra el directorio de trabajo (D31).
- **RNF05 Idempotencia y atomicidad.** Repetir una tarea con la misma entrada no cambia el resultado; cada escritura de tablas es transaccional; cada archivo se escribe a un temporal y se renombra con `os.replace`; los conjuntos de archivos llevan un manifiesto escrito al final.
- **RNF06 Sin fuga de información.** (a) Los rasgos de un instante de emisión usan solo lecturas de horas anteriores al instante y análisis frescos ya llegados; (b) ningún valor interpolado ni repetido entra como objetivo o rasgo; (c) `% Iron Concentrate` y las filas 2 a n del laboratorio no llegan a ningún rasgo; (d) toda decisión (candidato, reajuste, rango, B*, compuerta) usa solo entrenamiento y validación; (e) la prueba se evalúa una vez, con la configuración sellada (D18); (f) ninguna variante se lee para elegir; (g) el tamaño de las entregas no cambia ninguna estimación (D21).
- **RNF07 Trazabilidad.** Cada fila de hechos y cada archivo de salida llevan el `run_key`, el instante de cálculo y la huella de la fuente; cada estimación, la versión del modelo y su instante de emisión. Cada tarea registra inicio, fin, filas, duración, picos de memoria con su contador y, si falla, la traza completa.
- **RNF08 Tecnologías.** Las del landing (S5) y las ya anotadas en `LANDING-EXPANSION.md`; este proyecto suma a esa lista las que use la API y no declare el landing (pydantic, uvicorn; httpx solo en las pruebas) (D36). Cada módulo de terceros que el código importe es una dependencia directa fijada.
- **RNF09 Licencia y atribución.** La cita «Eduardo Magalhães Oliveira, Quality Prediction in a Mining Process, Kaggle, CC0; copia de OpenML, dataset 43311» aparece en el README, el diseño del tablero, los metadatos de cada Parquet y la exportación del sitio.
- **RNF10 Versionado.** Nunca se versionan la fuente, las entregas, el almacén, los intermedios, el artefacto ni `data/quick/`; cada Parquet versionado pesa ≤ 25 MB; la exportación del sitio, ≤ 200 KB sin el manifiesto. El sello sí se versiona.
- **RNF11 Seguridad.** Fuente: tamaño y huella fijados antes de leer; lectura con topes (RF02). Artefacto: solo se deserializa si su SHA-256 coincide (D39). API: solo `127.0.0.1`, sin escrituras, entradas acotadas y validadas (D27). Compose: interfaz solo en `127.0.0.1`; cada secreto con `${VAR:?}` y sin valor por defecto, incluida la contraseña de la base de metadatos en el servicio de PostgreSQL y en la cadena de conexión; `src/`, `sql/`, `config/` y `dags/` en solo lectura; imágenes con versión y resumen; el script de inicialización con `set -e`; un rechazo no se reintenta (D28). Sin credenciales en el proyecto.
- **RNF12 Sin datos personales.** El archivo no tiene personas ni identificadores de clientes; ningún archivo publicado lleva rutas absolutas del equipo ni el nombre del usuario (D43).
- **RNF13 Idioma.** Documentación en español neutro; código, identificadores, tablas y columnas en inglés; medidas, títulos de visuales y textos del sitio en español (D35).
- **RNF14 Honestidad.** La documentación dice solo lo que consta en el registro del documento de seguimiento y en `git log`, y se sincroniza después de la última corrección: el número de pruebas, los tiempos, las cifras de memoria y las advertencias abiertas coinciden con lo medido en el último commit (lecciones de los proyectos 02, 03 y 04).
- **RNF15 Suite rápida con presupuesto.** La suite por defecto termina en ≤ 120 s en este equipo, con un presupuesto de trabajo de 90 s que se mide después de cada unidad (D33).
- **RNF16 Un solo escritor.** Un solo proceso escribe una carpeta de datos a la vez, con un bloqueo cuya liberación nunca levanta y que solo su dueño borra (D30).

## 7. Requerimientos de datos

- **Clave de la fila**: `row_id`, entero, asignado en la lectura canónica (orden del archivo). **Clave de la hora**: `hour` (fecha y hora local del archivo, sin zona) y `hour_key` int64 `AAAAMMDDHH`. **Clave de la estimación**: (`target_hour`, `horizon`).
- **Instantes**: `issue_at`, el cierre de una hora (la hora siguiente en punto); `available_at = hour + latency_hours`; `as_of`, el instante hasta el que llegó la corrida.
- **Objetivo**: `silica_pct`, el primer valor de la hora de `%_Silica_Concentrate`, en % (puntos porcentuales); objetivo solo si `lab_state = 'fresh'`.
- **Sensores**: 19 columnas de proceso cada 20 s; la fuente no declara sus unidades (el diccionario lo dice). El laboratorio de alimentación (`%_Iron_Feed`, `%_Silica_Feed`) es horario.
- **Contrato del ARFF**: `@RELATION Quality-Prediction-in-a-Mining-Process` y los 24 `@ATTRIBUTE` en el orden de `source.attributes`, todos `STRING`.
- **Licencia**: CC0, con la cita de RNF09.

## 8. Criterios de aceptación

«Sintético» quiere decir el accesorio que generan las pruebas; «real», el ARFF de OpenML (marca `real_data`). Los nombres de las pruebas están en el plan, sección 24.

| ID | Criterio | Umbral | Verificación |
| --- | --- | --- | --- |
| AC01 | Fuente fijada | Un archivo con otro tamaño u otra huella, o ausente, rechaza la corrida sin escribir nada y nombra el runbook R1 | Unitaria |
| AC02 | Lectura estricta | Cada variante malformada (cabecera distinta, atributo de más, de menos, renombrado o no `STRING`, campo de más o de menos, campo que no está entre apóstrofos ni es un entero sin apóstrofos, fecha o número que no convierte, campo vacío, fila desordenada, hora con más filas que el tope, línea más larga que el tope, byte nulo, UTF-8 inválido, archivo más grande que el tope) da su regla y no escribe nada en `data/interim/`; un entero sin apóstrofos, como lo escribe el archivo real, se acepta | Contrato |
| AC03 | Filas y horas canónicas | Real: 737.453 filas, 4.097 horas, 318 horas faltantes, dos horas incompletas; sintético: los recuentos de la verdad del accesorio; ninguna columna de laboratorio por fila en `source_rows.parquet` | Real y contrato |
| AC04 | Frescura | En el accesorio, cada hora interpolada, repetida y fresca plantada se marca como tal; real: los conteos de la sección 4 en el entrenamiento, V1 y V2; la marca de una hora depende solo de su hora y de la anterior | Unitaria, contrato y real |
| AC05 | Entregas | El lanzamiento, las 40 diarias y el cierre con sus períodos; la siguiente es siempre la contigua; cada fila en la entrega de su hora; republicar no duplica; sin pendientes, `no_delivery` | Unitaria e integración |
| AC06 | Validación | Cada variante malformada da al menos su regla; el accesorio válido, 0 bloqueantes; los recuentos de advertencias e informativas son los de la verdad; cada regla declara cómo se agrega entre corridas | Contrato |
| AC07 | Sin daño tras un rechazo | El SHA-256 del SQLite, de cada Parquet, del HTML, de cada JSON del sitio y del sello es idéntico antes y después de una corrida rechazada | Integración |
| AC08 | Carga y llegada | Filas cargadas = filas de la entrega; todos los controles en 0; cada análisis con `available_at = hora + L`; un control que falla deja el almacén como estaba | Integración |
| AC09 | Partición y purgas | Cada borde entre bloques tiene su purga; las horas de las purgas no están en ningún bloque; una configuración que lo viola se rechaza con el nombre del borde | Unitaria |
| AC10 | Sin fuga I: columnas | `build_matrix` lanza `LeakageError` si recibe o produce `% Iron Concentrate`, una fila de laboratorio que no sea la primera, una marca de rampa o de frescura de la hora del objetivo, el número de fila, una variable de calendario o cualquier columna fuera de la lista permitida | Unitaria y estática |
| AC11 | Sin fuga II: truncamiento y perturbación | Los rasgos de un instante son idénticos a los calculados con los datos truncados en ese instante; cambiar cualquier lectura de una hora ≥ t, o cualquier análisis con `available_at > t`, no cambia ningún rasgo, estimación ni rango emitido en t (igualdad exacta) | Integración |
| AC12 | Sin fuga III: tamaño de la entrega | Las estimaciones emitidas con entregas de 1 día y de 10 días son idénticas byte a byte | Integración |
| AC13 | Trampa de fuga | Un rasgo de control que mira el objetivo de la misma hora da un MAE en V1 menor que `leak_tripwire_ratio` × el de la persistencia y detiene el lanzamiento (M01) | Integración |
| AC14 | Líneas base | Persistencia y medias exactas en un caso a mano con horas repetidas e interpoladas; cambiar valores de la validación o de la prueba no cambia ningún parámetro de B0 ni de B3; B2 elige k solo en V1 | Unitaria |
| AC15 | Modelo y controles | Con una señal plantada en un sensor (control positivo), el límite superior del intervalo de MAE(modelo) − MAE(persistencia) es < 0 y la compuerta encuentra ese sensor con su signo; con una serie que no depende de los sensores (control negativo), el intervalo de los sensores sobre el laboratorio contiene el 0 y ningún sensor pasa la compuerta; dos corridas eligen lo mismo y dan estimaciones idénticas | Integración (sintético) |
| AC16 | Rango | El cuantil conformal exacto en un caso a mano; se calibra solo con V2; la cobertura en V2 del rango ajustado allí es ≥ 0,80 | Unitaria |
| AC17 | Base más fuerte | B* sale solo de V1 (cambiar la prueba o V2 no la cambia); el desempate es el de RF12; queda en el sello | Unitaria e integración |
| AC18 | Sello y huella | El lanzamiento escribe su parte y la primera evaluación de la prueba la suya; ninguna se reescribe; cada clave está en la huella o declarada fuera; cambiar una clave de la huella cambia `config_sha256`; los cálculos sellados solo reciben la vista sellada; con otra configuración, `post_seal`; mientras el sello no tiene la prueba, una evaluación con otra configuración se rechaza (M05) | Unitaria e integración |
| AC19 | Resumen después del sello | Un almacén sin las filas selladas toma C01-C09 del sello, cada uno reconstruido y comparado con su entrada a 6 decimales | Integración |
| AC20 | Lanzamiento congelado | Las corridas siguientes reusan el artefacto sin cambios; uno con otra huella se rechaza antes de deserializarlo (M03) | Integración |
| AC21 | Emisión y seguimiento | Cada instante de emisión de la entrega da exactamente una estimación por horizonte o una fila `missing_inputs`; ninguna estimación cambia después; el error se une solo cuando el análisis llegó; los conteos del seguimiento son exactos en un caso a mano | Unitaria e integración |
| AC22 | Evaluación y criterios | Métricas exactas en un caso a mano de doce horas; el remuestreo toma días enteros y da lo mismo con la misma semilla; el texto de cada veredicto coincide con su número; con un resumen desfavorable, el README dice «no supera» | Unitaria y consistencia real |
| AC23 | Variantes | La latencia de 3 y 4 h y el reajuste con toda la validación se calculan después de la parte del lanzamiento del sello, se escriben en la parte de la prueba y ninguna función que elige lee sus tablas | Integración y estática |
| AC24 | Sensibilidades | Importancia y dependencia parcial exactas sobre un modelo lineal conocido; la compuerta aplica sus tres condiciones; un sensor que no pasa se publica como «sin asociación estable»; ningún texto las llama causa o acción | Unitaria |
| AC25 | Modelo estrella | Claves únicas y no nulas; 100 % de las claves foráneas en su dimensión; relaciones 1:* de filtro unidireccional y activas; esquema de cada Parquet = especificación | Contrato |
| AC26 | Diseño del tablero | El HTML tiene todas las páginas, visuales, medidas y relaciones de la especificación; no carga recursos externos; pesa < 2 MB; todo texto de los datos está escapado | Unitaria |
| AC27 | Exportación para el sitio | Los cinco JSON cumplen su esquema y suman ≤ 200 KB; el manifiesto se escribe al final y un conjunto mezclado se rechaza; las reglas acumuladas se leen una vez; las cifras son las de los Parquet y del resumen de la misma corrida; ninguna ruta absoluta en sus bytes | Contrato |
| AC28 | API | `POST /estimate` da, para una hora de la prueba, exactamente las estimaciones guardadas por el flujo; una entrada fuera de sus topes o con una lectura posterior al instante de emisión da 422 sin estimar; el servicio se niega a escuchar en otra interfaz que `127.0.0.1`; no escribe ningún archivo | Integración |
| AC29 | Estado y cierre | La corrida queda `running` hasta que `report` la cierra en orden; una falla después de `load` deja `failed` y refresca lo exportado; si las escrituras del manejador de fallas fallan, quien llama sigue viendo el error de la tarea | Integración |
| AC30 | Corridas cerradas y entregas ajenas | Cualquier tarea de una corrida `ok` o `no_delivery` se rechaza antes de escribir (salida 2); toda tarea posterior a `load` se rechaza si la corrida no cargó su propia entrega; `load` se rechaza sin una validación aprobada | Integración y punta a punta |
| AC31 | Un solo escritor | Un segundo escritor se rechaza (salida 2) sin escribir; soltar el bloqueo mientras otro proceso tiene el archivo abierto nunca levanta; una toma anidada cuya reescritura falla nunca deja el bloqueo; un número de proceso reusado no se toma por el dueño; otro hilo se rechaza | Unitaria e integración |
| AC32 | CLI | Códigos de salida 0, 1, 2 y 3; una combinación incompatible sale con 2 antes de escribir; cada opción documentada cambia el resultado (una prueba por opción) | Punta a punta |
| AC33 | Modo rápido aislado | Desde un clon limpio y desde otro directorio de trabajo, la repetición rápida termina y nada fuera de `data/quick/` cambia | Punta a punta |
| AC34 | DAG y Docker | Identificadores y orden de tareas iguales a los de la CLI; programación diaria, sin catchup, una corrida y una tarea activas; `pip check` limpio en la imagen; `airflow dags test` dos veces seguidas en modo rápido (lanzamiento y la primera diaria) con el modelo congelado idéntico; un rechazo falla sin reintentos; la prueba no deja imágenes, volúmenes ni contenedores | Estática y Docker |
| AC35 | Compose endurecido | Interfaz en `127.0.0.1`; cada secreto con `${VAR:?}`, incluida la contraseña de PostgreSQL y la de la cadena de conexión; ningún valor literal de secreto; montajes de solo lectura; imágenes con versión y resumen; `set -e` en la inicialización | Estática |
| AC36 | Punta a punta real | La repetición completa cumple RNF02 y RNF03 con tiempos y memoria medidos y el contador nombrado; cada Parquet versionado ≤ 25 MB | Real |
| AC37 | Reproducibilidad | Dos repeticiones completas seguidas dan el mismo contenido en cada Parquet y JSON, sin las columnas de la corrida | Integración (sintético) |
| AC38 | Dependencias | Cada módulo de terceros que importa `src/` es una dependencia directa fijada en el archivo de requisitos que le corresponde; las que el landing no declara tienen su fila en `LANDING-EXPANSION.md` con el 05 | Estática |
| AC39 | Documentación | README con los títulos del plan en orden; diccionario de cada columna de cada Parquet; cada decisión con sus siete campos; runbook R1-R12; el número de pruebas que dicen los documentos es el de la colección de la sesión; cada cifra de memoria nombra su contador; el bloque de resultados es el del resumen; cada prueba nombrada en el plan, sección 24, existe; todo en el último commit de corrección | Unitaria sobre los Markdown |
| AC40 | Suite rápida | La suite por defecto termina en ≤ 120 s, medida dos veces en reposo; una sesión completa que pasa el límite termina con falla y dice por cuánto | Medición y unitaria |

### 8.1 Criterios del modelo, fijados antes de construir

Se fijan aquí, antes de escribir código, y se confirman en Git con este plan. **Prueba**: las horas del 2017-08-01 00:00 al 2017-09-09 23:00 cuyo análisis es fresco (D05), con al menos 24 análisis frescos de historia y todas las entradas; la regla de frescura es la de RF04, fijada sin mirar la prueba. **Unidad**: la hora del objetivo; los intervalos remuestrean días enteros. Se evalúa el modelo congelado del lanzamiento de cada horizonte (elegido en V1, reajustado con entrenamiento y V1, rango calibrado en V2) con L = 2 h. **B*_H** es la base más fuerte de cada horizonte entre B1 y B2, elegida en V1 y sellada (RF12). Con lo medido antes (sección 4), B*_0 sería la persistencia y B*_1 y B*_2, la media de los últimos 3 análisis.

Dos columnas dicen qué se vio antes de fijarlos (D16): lo que vio la investigación (la validación entera, con todas las horas) y lo que vio el agente de planificación (V1 y V2, solo las horas frescas).

| ID | Criterio | Umbral | Visto por la investigación | Visto por el planificador |
| --- | --- | --- | --- | --- |
| C01 | H0 frente a la persistencia | MAE(M_0) < MAE(B1_0) | Sí: 0,531 frente a 0,452 (todas las horas, otro modelo) | Sí: 0,537 frente a 0,533 en V2 |
| C02 | H0 fuera del ruido frente a la base más fuerte | Límite superior del intervalo del 95 % de MAE(M_0) − MAE(B*_0) < 0 | Sí: de 0,055 a 0,101 frente a la persistencia | Sí: de −0,019 a 0,029 en V2 |
| C03 | H1 fuera del ruido frente a la base más fuerte | Límite superior del intervalo de MAE(M_1) − MAE(B*_1) < 0 | No (solo la persistencia con dos rezagos) | Sí: de −0,065 a 0,052 en V2 |
| C04 | H2 fuera del ruido frente a la base más fuerte | Límite superior del intervalo de MAE(M_2) − MAE(B*_2) < 0 | No | Sí: de −0,087 a 0,091 en V2 |
| C05 | Cobertura del rango de H0 | Proporción de horas con el análisis dentro del rango del 80 % entre 0,75 y 0,85 | No | En parte: 0,762 en V2 con un rango calibrado en V1 |
| C06 | Sesgo de H0 | \|media(M_0 − análisis)\| ≤ 0,10 | No | Sí: +0,104 en V2 |
| C07 | Los sensores solos frente a la media | Límite superior del intervalo de MAE(mejor solo sensores en H0) − MAE(B0) < 0 | En parte: 0,816 frente a 0,958 | Sí: de −0,242 a −0,042 en V2 |
| C08 | Los sensores agregan a la historia del laboratorio | Límite superior del intervalo de MAE(mejor con sensores en H0) − MAE(mejor solo laboratorio en H0) < 0 | En parte: sensores solos 0,816, con rezagos 0,531 | Sí: de −0,001 a 0,021 en V2 |
| C09 | Sensibilidad estable | Al menos un sensor pasa la compuerta de D20 en el lanzamiento y conserva el signo de su dependencia parcial en la prueba | Sí: todas las importancias < 0,007 y signos que cambian | Sí: ninguno pasa en V1 y V2 |
| C10 | Por semana y variantes (informativo) | Sin umbral: MAE de M_H, B1_H y B*_H por semana de la prueba; con L = 3 h y L = 4 h, MAE de M_0 reajustado a esa latencia y de la persistencia, con el intervalo de la diferencia; M_H reajustado con entrenamiento, V1 y V2; MAE de M_0 y de la persistencia sobre todas las horas de la prueba, frescas o no. El criterio es que esté escrito y sea consistente | No | Sí, en V1 y V2: latencias (sección 4) |

Definiciones que fijan los criterios:

- **MAE**: media de `|estimación − análisis|` sobre las horas de la prueba del horizonte, en puntos de sílice. **Sesgo**: media de `estimación − análisis`.
- **Intervalo del 95 %**: remuestreo pareado de **días** de la prueba con reposición (cada día remuestreado aporta todas sus horas), 2.000 remuestras, semilla 0, los mismos días para los dos métodos; percentiles 2,5 y 97,5 de la diferencia de MAE (D17).
- **Mejor solo sensores** y **mejor solo laboratorio**: el candidato de menor MAE en V1 con el conjunto `fS` y con `fL`, reajustado con entrenamiento y V1 como el modelo; **mejor con sensores**: el de menor MAE en V1 entre `fSL` y `fSLF`. Si el modelo elegido es uno de ellos, es el mismo.
- **Cobertura**: proporción de horas de la prueba con `bajo ≤ análisis ≤ alto`.
- Un criterio que no se puede calcular queda `passed = false` con el motivo, nunca aprobado. Un empate no supera: los criterios con «<» se cumplen solo con una diferencia a favor. Un criterio que no se cumple se informa con su número en el resumen, el README, la ficha del modelo, el tablero y el sitio.

**Lo esperable, dicho antes de medir.** La primera mirada de la investigación no superó a la persistencia, y en la comprobación del planificador, sobre las horas frescas, ningún candidato supera a su base fuera del ruido en ningún horizonte, ni los sensores agregan nada a la historia del laboratorio. Con eso: el modelo probablemente **no cumpla C01, C02, C03, C04 ni C08**; C06 queda en el borde (+0,104 en V2) y probablemente no se cumpla, porque la prueba sigue el cambio de nivel de la validación (D11); **C09 no se cumple** (ningún sensor pasa la compuerta); C07 debería cumplirse (los sensores solos sí dicen algo de la sílice, aunque menos que el último análisis); C05 es incierto (0,762 en V2, cerca del borde de 0,75). Si es así, el resultado del proyecto es que **repetir el último análisis estima la sílice de la hora que cerró tan bien como el modelo, y promediar los últimos tres, la de las dos horas siguientes; los sensores de la planta dicen algo de la sílice, pero nada que la historia del laboratorio no diga ya, y ninguna variable mueve la estimación de forma estable**; el modelo agrega un rango y una estimación disponible antes del análisis, no una estimación mejor. El README, la ficha, el tablero y el sitio lo dicen con esos números (D16).

## 9. Plan de pruebas

Cinco niveles con pytest en el `.venv` del proyecto, con la prueba primero en cada unidad (plan, sección 24). Marcas: `real_data` (necesita el ARFF real en `data/raw/`), `docker` (necesita Docker). Por defecto: `-m "not real_data and not docker"`.

| Nivel | Qué prueba | Requerimientos | Criterios |
| --- | --- | --- | --- |
| Unitarias | Configuración y rutas, huella y claves, frescura, partición, líneas base, rasgos y guardas, candidatos, rango, sello, evaluación, criterios, sensibilidades, bloqueo, especificación del modelo semántico, HTML, compose y DAG estáticos, dependencias, presupuesto de la suite | RF01, RF04, RF09-RF15, RF20, RF22, RF25 | AC01, AC04, AC09, AC10, AC14, AC16-AC18, AC22, AC24, AC26, AC31, AC35, AC38, AC40 |
| Contrato de datos | Contrato del ARFF, reglas sobre accesorios válidos y malformados, esquema de cada Parquet y de cada JSON, integridad referencial, referencias de DAX | RF02, RF03, RF06, RF21, RF23 | AC02, AC03, AC06, AC25, AC27 |
| Integración | Entregas, carga y llegada, rechazo sin daño, sin fuga por truncamiento, perturbación y tamaño de entrega, trampa de fuga, controles positivo y negativo, sello, resumen después del sello, lanzamiento congelado, emisión, seguimiento, variantes, API, estado y cierre, corridas cerradas, reproducibilidad | RF05, RF07, RF08, RF13, RF15-RF19, RF24, RF25 | AC05, AC07, AC08, AC11-AC13, AC15, AC17-AC21, AC23, AC28-AC30, AC37 |
| Punta a punta | CLI en modo rápido y aislada; repetición real (`real_data`); `airflow dags test` en Docker (`docker`) | RF25 | AC32-AC34, AC36, AC40 |
| Documentación | Títulos del README, diccionario, siete campos, runbook, número de pruebas de la sesión, contadores de memoria, bloque de resultados, advertencias abiertas, pruebas nombradas en el plan | RF26 | AC39 |

Accesorio (plan, sección 24): un generador escribe un ARFF con la cabecera real, el mismo calendario (con el hueco de marzo y las dos horas incompletas) y `rows_per_hour` filas por hora (12 en el accesorio), con un objetivo horario de proceso conocido, tramos interpolados con su rampa, tramos repetidos, rampas de una hora, alimentación congelada durante días, un sensor fijo dentro de la hora y `% Iron Concentrate` correlacionado con el objetivo. Variantes de señal: `none`, `sensor_signal` (control positivo: la sílice sigue a un sensor con un retardo conocido) y `lab_only` (control negativo: la sílice es una serie autorregresiva que no depende de los sensores). Una variante malformada por regla bloqueante. Dos tamaños: el estándar y uno chico (las primeras semanas) para las pruebas de una fila. Ninguna prueba ni ninguna persona calcula una métrica sobre la prueba real antes de la corrida de U21, y ninguna prueba `real_data` pasa del lanzamiento antes de U21 (D18).
