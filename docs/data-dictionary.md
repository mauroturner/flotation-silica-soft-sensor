# Diccionario de datos

Qué significa cada columna del archivo de la fuente y para qué se usa, cómo se calcula cada una de las 67 variables que puede tomar el modelo y qué significa cada columna de cada tabla que el flujo exporta para Power BI, con su unidad. Las dos primeras partes se escribieron a mano a partir de `docs/research.md`, de `docs/requirements.md`, del plan (secciones 6 y 10) y de `src/flotsilica/schema.py`, y una prueba (`tests/docs/test_docs.py`) comprueba que listan exactamente las 24 columnas del archivo y las 67 variables del código, en su orden. La tercera, entre los marcadores `columns`, la escribe `python -m flotsilica docs-sync` desde el modelo semántico (`src/flotsilica/dashboard/semantic_model.py`), la especificación contra la que la exportación verifica cada archivo Parquet; otra prueba comprueba que lo versionado es lo que `docs-sync` escribe y que cada Parquet tiene esas columnas.

## Convenciones

- **La hora y el instante.** La unidad del modelo es la hora (D04): el archivo trae una fila cada 20 segundos y el proyecto las agrega por hora. Un instante de emisión `t` es el cierre de una hora: usa las lecturas hasta la hora `t − 1` y los análisis cuyo `available_at` (la hora de su muestra más la demora del laboratorio, 2 h por supuesto, D06) es `t` o anterior. Una hora se identifica por `hour` (fecha y hora, sin zona) y por `hour_key`, el entero `AAAAMMDDHH`; una fecha, por `date_key`, el entero `AAAAMMDD`.
- **Estado del análisis de una hora (`lab_state`, D05).** `fresh` (hay un análisis nuevo, el único que es objetivo o variable del laboratorio), `interpolated` (la sílice cambia dentro de la hora y la hora anterior también: es una recta entre dos análisis y contiene el siguiente), `held` (repite el valor de la hora anterior observada), `pending` (el análisis todavía no llegó en el instante de la tabla) y `missing` (la hora cae en el hueco de 318 horas, sin datos).
- **Bloques.** `train`, `valid_v1`, `valid_v2` y `test`, con purgas de 24 h entre ellos (D10): entrenamiento del 2017-03-10 al 2017-05-31, V1 del 2017-06-02 al 2017-06-30, V2 del 2017-07-02 al 2017-07-30 y prueba del 2017-08-01 al 2017-09-09. V1 y V2 son de validación, no de la prueba.
- **Horizontes.** `horizon_key` 0 (H0) es la hora que cerró, 1 (H1) la que empieza y 2 (H2) la siguiente (D07).
- **Unidades.** Los porcentajes de laboratorio son puntos de porcentaje de sílice o de hierro; los errores (MAE, RMSE, sesgo, semiancho) están en puntos de porcentaje de sílice. La fuente no declara la unidad de ninguno de los 19 sensores y este diccionario no la inventa: donde dice «sin unidad en la fuente», la columna es la del sensor.
- **Estimación y rango.** `estimate` es la estimación de la sílice de la hora objetivo; `low` y `high` son el rango del 80 % (conformal partido, calibrado en V2, D15); `persistence` es el último análisis fresco llegado (la regla B1) y `b_star` lo que dice la base más fuerte del horizonte.
- **Memoria.** Toda cifra de memoria nombra su contador: `peak_working_set_mb` es el pico del conjunto de trabajo del proceso (`PeakWorkingSetSize` de `GetProcessMemoryInfo` en Windows; `ru_maxrss` de `resource.getrusage` en Linux) y `peak_commit_mb` el pico de memoria comprometida (`PeakPagefileUsage`, solo en Windows), en MB de 1.048.576 bytes (D38).
- **Vacíos.** Un valor que no existe queda nulo, no cero: la sílice de una hora cuyo análisis no llegó, el error de una estimación que no se pudo evaluar, la desviación de una hora con una sola fila (`std` vacía), la dependencia parcial de un sensor que no pasó la compuerta.

## Archivo de origen

`openml-43311-quality-prediction-mining-process.arff`, la copia de OpenML (dataset 43311) de «Quality Prediction in a Mining Process» de Kaggle (CC0): 185.243.565 bytes, SHA-256 `a25122979ba8c5fb9c12e361db61032efc6892a24b5746cc8309da601d9639b2`, que el proyecto fija y exige antes de leer (V01) y que no se comparó byte a byte con el CSV de Kaggle. Es un ARFF de texto con 24 atributos declarados como `STRING`, en este orden, y 737.453 filas de 24 campos; salvo la fecha, todo valor es un número con coma decimal, entre apóstrofos o, si es entero, sin ellos (V04, V05). La tabla da, por atributo, el nombre que usa el código (`schema.ATTRIBUTES`), para qué se usa, su unidad y su significado; las cuatro columnas de laboratorio se miden una vez por hora y el archivo las repite en las 180 filas de la hora (en una hora en rampa se mueven: solo la primera fila es el análisis, D04).

| Atributo del archivo | Nombre en el proyecto | Uso | Unidad | Significado |
| --- | --- | --- | --- | --- |
| `date` | `hour` | Clave de la hora (`hour`, `hour_key`); reparte las horas en los bloques y las purgas; una hora sin filas es una hora sin datos | fecha y hora | Comienzo del intervalo de una hora de la fila, `AAAA-MM-DD HH:00:00`, entre apóstrofos y sin zona. Hay 180 filas por hora (una cada 20 s) en 4.095 de las 4.097 horas; las otras dos tienen 174 y 179 (V07, V20). |
| `%_Iron_Feed` | `feed_iron_pct` | Rasgo del conjunto `fSLF` (`feed_iron_pct`, `feed_iron_age_h`); su primera fila de la hora es el análisis | % de hierro | Hierro de la alimentación a la flotación, medido por el laboratorio una vez por hora: puede quedar igual durante días (la racha más larga, 791 h). |
| `%_Silica_Feed` | `feed_silica_pct` | Rasgo del conjunto `fSLF` (`feed_silica_pct`, `feed_silica_age_h`); su primera fila de la hora es el análisis | % de sílice | Sílice de la alimentación a la flotación, medida por el laboratorio una vez por hora; también puede quedar igual durante días. |
| `Starch_Flow` | `starch_flow` | Sensor: sus tres agregados por hora son rasgos de `fS`, `fSL` y `fSLF` | no declarada en la fuente | Flujo de almidón, una de las dos variables de reactivos. |
| `Amina_Flow` | `amina_flow` | Sensor; es el que el control positivo del accesorio sintético planta y el que la compuerta de sensibilidades debe encontrar ahí | no declarada en la fuente | Flujo de amina, la otra variable de reactivos. |
| `Ore_Pulp_Flow` | `ore_pulp_flow` | Sensor | no declarada en la fuente | Flujo de pulpa de mineral que entra a la flotación. |
| `Ore_Pulp_pH` | `ore_pulp_ph` | Sensor | no declarada en la fuente | pH de la pulpa de mineral. |
| `Ore_Pulp_Density` | `ore_pulp_density` | Sensor | no declarada en la fuente | Densidad de la pulpa de mineral. |
| `Flotation_Column_01_Air_Flow` | `air_flow_01` | Sensor | no declarada en la fuente | Flujo de aire de la columna de flotación 1. |
| `Flotation_Column_02_Air_Flow` | `air_flow_02` | Sensor | no declarada en la fuente | Flujo de aire de la columna de flotación 2. |
| `Flotation_Column_03_Air_Flow` | `air_flow_03` | Sensor | no declarada en la fuente | Flujo de aire de la columna de flotación 3. |
| `Flotation_Column_04_Air_Flow` | `air_flow_04` | Sensor | no declarada en la fuente | Flujo de aire de la columna de flotación 4. Constante dentro de algunas horas (I03). |
| `Flotation_Column_05_Air_Flow` | `air_flow_05` | Sensor | no declarada en la fuente | Flujo de aire de la columna de flotación 5. Constante dentro de algunas horas (I03). |
| `Flotation_Column_06_Air_Flow` | `air_flow_06` | Sensor | no declarada en la fuente | Flujo de aire de la columna de flotación 6. |
| `Flotation_Column_07_Air_Flow` | `air_flow_07` | Sensor | no declarada en la fuente | Flujo de aire de la columna de flotación 7. |
| `Flotation_Column_01_Level` | `level_01` | Sensor | no declarada en la fuente | Nivel de la columna de flotación 1. |
| `Flotation_Column_02_Level` | `level_02` | Sensor | no declarada en la fuente | Nivel de la columna de flotación 2. |
| `Flotation_Column_03_Level` | `level_03` | Sensor | no declarada en la fuente | Nivel de la columna de flotación 3. |
| `Flotation_Column_04_Level` | `level_04` | Sensor | no declarada en la fuente | Nivel de la columna de flotación 4. |
| `Flotation_Column_05_Level` | `level_05` | Sensor | no declarada en la fuente | Nivel de la columna de flotación 5. |
| `Flotation_Column_06_Level` | `level_06` | Sensor | no declarada en la fuente | Nivel de la columna de flotación 6. |
| `Flotation_Column_07_Level` | `level_07` | Sensor | no declarada en la fuente | Nivel de la columna de flotación 7. |
| `%_Iron_Concentrate` | `iron_conc_pct` | **Nunca es un rasgo**: la lista de columnas prohibidas la rechaza por su nombre (D09, `LeakageError`); solo sirve a la demostración de la fuga y a la trampa de fuga como control | % de hierro | Hierro del concentrado, medido por el laboratorio en la misma hora que la sílice: su correlación con ella es de −0,80 (research.md), así que dejarla entrar delataría la respuesta. |
| `%_Silica_Concentrate` | `silica_pct` | El objetivo. Su primera fila de la hora es el análisis (D04); solo una hora con análisis nuevo es objetivo o rasgo de laboratorio (D05); `lab_state` dice si es nueva, interpolada o repetida | % de sílice | Sílice del concentrado, la impureza que define la calidad del producto: medida por el laboratorio una vez por hora, con una demora que el archivo no trae (el proyecto supone 2 h). |

Recuentos de la corrida real (`outputs/site/validation_rules.json`, `totals`, y `outputs/site/data.json`): 737.453 filas; 4.097 horas con filas, de las que 2 son parciales (174 y 179 filas); 318 horas sin datos, del 2017-03-16 06:00 al 2017-03-29 11:00; 42 entregas cargadas y ninguna rechazada. Del análisis de cada hora: 3.361 nuevos, 446 repetidos y 226 interpolados (`outputs/site/data.json`, `states_by_block`, y `summary.json`, `headline`).

## Variables

Las 67 columnas que una matriz del modelo puede tomar en un instante `t` (RF09, D12; plan, sección 10): 57 agregados de la hora `t − 1` (la media, la desviación estándar muestral y el último valor de cada uno de los 19 sensores), 6 del historial del laboratorio y 4 de la alimentación. Se calculan solo con lo que ya llegó en `t`; una prueba de truncamiento y una de perturbación lo comprueban. Los conjuntos son `fS` (los 57 agregados), `fL` (las 6 de laboratorio), `fSL` (63) y `fSLF` (las 67). Una hora se estima si tiene todas las entradas de su conjunto y al menos 24 análisis frescos llegados (`min_fresh_history`); si no, queda `missing_inputs`. **Nunca** son variables el hierro del concentrado, las columnas de laboratorio de otra fila de la hora, las marcas de rampa y de frescura de la hora del objetivo, ni una variable de calendario (D09): la lista de columnas prohibidas (`schema.FORBIDDEN_COLUMNS`) y `LeakageError` las rechazan por su nombre.

| Variable | Nombre | Unidad | Definición |
| --- | --- | --- | --- |
| `starch_flow_mean` | Media · Flujo de almidón | la del sensor (no declarada en la fuente) | Media de `starch_flow` en las filas de la hora `t − 1`. |
| `starch_flow_std` | Desviación · Flujo de almidón | la del sensor (no declarada en la fuente) | Desviación estándar muestral (ddof = 1) de `starch_flow` en las filas de la hora `t − 1`; vacía si la hora tiene una sola fila. |
| `starch_flow_last` | Último valor · Flujo de almidón | la del sensor (no declarada en la fuente) | Último valor de `starch_flow` en las filas de la hora `t − 1`. |
| `amina_flow_mean` | Media · Flujo de amina | la del sensor (no declarada en la fuente) | Media de `amina_flow` en las filas de la hora `t − 1`. |
| `amina_flow_std` | Desviación · Flujo de amina | la del sensor (no declarada en la fuente) | Desviación estándar muestral (ddof = 1) de `amina_flow` en las filas de la hora `t − 1`; vacía si la hora tiene una sola fila. |
| `amina_flow_last` | Último valor · Flujo de amina | la del sensor (no declarada en la fuente) | Último valor de `amina_flow` en las filas de la hora `t − 1`. |
| `ore_pulp_flow_mean` | Media · Flujo de pulpa de mineral | la del sensor (no declarada en la fuente) | Media de `ore_pulp_flow` en las filas de la hora `t − 1`. |
| `ore_pulp_flow_std` | Desviación · Flujo de pulpa de mineral | la del sensor (no declarada en la fuente) | Desviación estándar muestral (ddof = 1) de `ore_pulp_flow` en las filas de la hora `t − 1`; vacía si la hora tiene una sola fila. |
| `ore_pulp_flow_last` | Último valor · Flujo de pulpa de mineral | la del sensor (no declarada en la fuente) | Último valor de `ore_pulp_flow` en las filas de la hora `t − 1`. |
| `ore_pulp_ph_mean` | Media · pH de la pulpa | la del sensor (no declarada en la fuente) | Media de `ore_pulp_ph` en las filas de la hora `t − 1`. |
| `ore_pulp_ph_std` | Desviación · pH de la pulpa | la del sensor (no declarada en la fuente) | Desviación estándar muestral (ddof = 1) de `ore_pulp_ph` en las filas de la hora `t − 1`; vacía si la hora tiene una sola fila. |
| `ore_pulp_ph_last` | Último valor · pH de la pulpa | la del sensor (no declarada en la fuente) | Último valor de `ore_pulp_ph` en las filas de la hora `t − 1`. |
| `ore_pulp_density_mean` | Media · Densidad de la pulpa | la del sensor (no declarada en la fuente) | Media de `ore_pulp_density` en las filas de la hora `t − 1`. |
| `ore_pulp_density_std` | Desviación · Densidad de la pulpa | la del sensor (no declarada en la fuente) | Desviación estándar muestral (ddof = 1) de `ore_pulp_density` en las filas de la hora `t − 1`; vacía si la hora tiene una sola fila. |
| `ore_pulp_density_last` | Último valor · Densidad de la pulpa | la del sensor (no declarada en la fuente) | Último valor de `ore_pulp_density` en las filas de la hora `t − 1`. |
| `air_flow_01_mean` | Media · Flujo de aire de la columna 1 | la del sensor (no declarada en la fuente) | Media de `air_flow_01` en las filas de la hora `t − 1`. |
| `air_flow_01_std` | Desviación · Flujo de aire de la columna 1 | la del sensor (no declarada en la fuente) | Desviación estándar muestral (ddof = 1) de `air_flow_01` en las filas de la hora `t − 1`; vacía si la hora tiene una sola fila. |
| `air_flow_01_last` | Último valor · Flujo de aire de la columna 1 | la del sensor (no declarada en la fuente) | Último valor de `air_flow_01` en las filas de la hora `t − 1`. |
| `air_flow_02_mean` | Media · Flujo de aire de la columna 2 | la del sensor (no declarada en la fuente) | Media de `air_flow_02` en las filas de la hora `t − 1`. |
| `air_flow_02_std` | Desviación · Flujo de aire de la columna 2 | la del sensor (no declarada en la fuente) | Desviación estándar muestral (ddof = 1) de `air_flow_02` en las filas de la hora `t − 1`; vacía si la hora tiene una sola fila. |
| `air_flow_02_last` | Último valor · Flujo de aire de la columna 2 | la del sensor (no declarada en la fuente) | Último valor de `air_flow_02` en las filas de la hora `t − 1`. |
| `air_flow_03_mean` | Media · Flujo de aire de la columna 3 | la del sensor (no declarada en la fuente) | Media de `air_flow_03` en las filas de la hora `t − 1`. |
| `air_flow_03_std` | Desviación · Flujo de aire de la columna 3 | la del sensor (no declarada en la fuente) | Desviación estándar muestral (ddof = 1) de `air_flow_03` en las filas de la hora `t − 1`; vacía si la hora tiene una sola fila. |
| `air_flow_03_last` | Último valor · Flujo de aire de la columna 3 | la del sensor (no declarada en la fuente) | Último valor de `air_flow_03` en las filas de la hora `t − 1`. |
| `air_flow_04_mean` | Media · Flujo de aire de la columna 4 | la del sensor (no declarada en la fuente) | Media de `air_flow_04` en las filas de la hora `t − 1`. |
| `air_flow_04_std` | Desviación · Flujo de aire de la columna 4 | la del sensor (no declarada en la fuente) | Desviación estándar muestral (ddof = 1) de `air_flow_04` en las filas de la hora `t − 1`; vacía si la hora tiene una sola fila. |
| `air_flow_04_last` | Último valor · Flujo de aire de la columna 4 | la del sensor (no declarada en la fuente) | Último valor de `air_flow_04` en las filas de la hora `t − 1`. |
| `air_flow_05_mean` | Media · Flujo de aire de la columna 5 | la del sensor (no declarada en la fuente) | Media de `air_flow_05` en las filas de la hora `t − 1`. |
| `air_flow_05_std` | Desviación · Flujo de aire de la columna 5 | la del sensor (no declarada en la fuente) | Desviación estándar muestral (ddof = 1) de `air_flow_05` en las filas de la hora `t − 1`; vacía si la hora tiene una sola fila. |
| `air_flow_05_last` | Último valor · Flujo de aire de la columna 5 | la del sensor (no declarada en la fuente) | Último valor de `air_flow_05` en las filas de la hora `t − 1`. |
| `air_flow_06_mean` | Media · Flujo de aire de la columna 6 | la del sensor (no declarada en la fuente) | Media de `air_flow_06` en las filas de la hora `t − 1`. |
| `air_flow_06_std` | Desviación · Flujo de aire de la columna 6 | la del sensor (no declarada en la fuente) | Desviación estándar muestral (ddof = 1) de `air_flow_06` en las filas de la hora `t − 1`; vacía si la hora tiene una sola fila. |
| `air_flow_06_last` | Último valor · Flujo de aire de la columna 6 | la del sensor (no declarada en la fuente) | Último valor de `air_flow_06` en las filas de la hora `t − 1`. |
| `air_flow_07_mean` | Media · Flujo de aire de la columna 7 | la del sensor (no declarada en la fuente) | Media de `air_flow_07` en las filas de la hora `t − 1`. |
| `air_flow_07_std` | Desviación · Flujo de aire de la columna 7 | la del sensor (no declarada en la fuente) | Desviación estándar muestral (ddof = 1) de `air_flow_07` en las filas de la hora `t − 1`; vacía si la hora tiene una sola fila. |
| `air_flow_07_last` | Último valor · Flujo de aire de la columna 7 | la del sensor (no declarada en la fuente) | Último valor de `air_flow_07` en las filas de la hora `t − 1`. |
| `level_01_mean` | Media · Nivel de la columna 1 | la del sensor (no declarada en la fuente) | Media de `level_01` en las filas de la hora `t − 1`. |
| `level_01_std` | Desviación · Nivel de la columna 1 | la del sensor (no declarada en la fuente) | Desviación estándar muestral (ddof = 1) de `level_01` en las filas de la hora `t − 1`; vacía si la hora tiene una sola fila. |
| `level_01_last` | Último valor · Nivel de la columna 1 | la del sensor (no declarada en la fuente) | Último valor de `level_01` en las filas de la hora `t − 1`. |
| `level_02_mean` | Media · Nivel de la columna 2 | la del sensor (no declarada en la fuente) | Media de `level_02` en las filas de la hora `t − 1`. |
| `level_02_std` | Desviación · Nivel de la columna 2 | la del sensor (no declarada en la fuente) | Desviación estándar muestral (ddof = 1) de `level_02` en las filas de la hora `t − 1`; vacía si la hora tiene una sola fila. |
| `level_02_last` | Último valor · Nivel de la columna 2 | la del sensor (no declarada en la fuente) | Último valor de `level_02` en las filas de la hora `t − 1`. |
| `level_03_mean` | Media · Nivel de la columna 3 | la del sensor (no declarada en la fuente) | Media de `level_03` en las filas de la hora `t − 1`. |
| `level_03_std` | Desviación · Nivel de la columna 3 | la del sensor (no declarada en la fuente) | Desviación estándar muestral (ddof = 1) de `level_03` en las filas de la hora `t − 1`; vacía si la hora tiene una sola fila. |
| `level_03_last` | Último valor · Nivel de la columna 3 | la del sensor (no declarada en la fuente) | Último valor de `level_03` en las filas de la hora `t − 1`. |
| `level_04_mean` | Media · Nivel de la columna 4 | la del sensor (no declarada en la fuente) | Media de `level_04` en las filas de la hora `t − 1`. |
| `level_04_std` | Desviación · Nivel de la columna 4 | la del sensor (no declarada en la fuente) | Desviación estándar muestral (ddof = 1) de `level_04` en las filas de la hora `t − 1`; vacía si la hora tiene una sola fila. |
| `level_04_last` | Último valor · Nivel de la columna 4 | la del sensor (no declarada en la fuente) | Último valor de `level_04` en las filas de la hora `t − 1`. |
| `level_05_mean` | Media · Nivel de la columna 5 | la del sensor (no declarada en la fuente) | Media de `level_05` en las filas de la hora `t − 1`. |
| `level_05_std` | Desviación · Nivel de la columna 5 | la del sensor (no declarada en la fuente) | Desviación estándar muestral (ddof = 1) de `level_05` en las filas de la hora `t − 1`; vacía si la hora tiene una sola fila. |
| `level_05_last` | Último valor · Nivel de la columna 5 | la del sensor (no declarada en la fuente) | Último valor de `level_05` en las filas de la hora `t − 1`. |
| `level_06_mean` | Media · Nivel de la columna 6 | la del sensor (no declarada en la fuente) | Media de `level_06` en las filas de la hora `t − 1`. |
| `level_06_std` | Desviación · Nivel de la columna 6 | la del sensor (no declarada en la fuente) | Desviación estándar muestral (ddof = 1) de `level_06` en las filas de la hora `t − 1`; vacía si la hora tiene una sola fila. |
| `level_06_last` | Último valor · Nivel de la columna 6 | la del sensor (no declarada en la fuente) | Último valor de `level_06` en las filas de la hora `t − 1`. |
| `level_07_mean` | Media · Nivel de la columna 7 | la del sensor (no declarada en la fuente) | Media de `level_07` en las filas de la hora `t − 1`. |
| `level_07_std` | Desviación · Nivel de la columna 7 | la del sensor (no declarada en la fuente) | Desviación estándar muestral (ddof = 1) de `level_07` en las filas de la hora `t − 1`; vacía si la hora tiene una sola fila. |
| `level_07_last` | Último valor · Nivel de la columna 7 | la del sensor (no declarada en la fuente) | Último valor de `level_07` en las filas de la hora `t − 1`. |
| `lab_last1` | Último análisis fresco | % de sílice | Sílice del análisis fresco más reciente con `available_at ≤ t`. |
| `lab_last2` | Penúltimo análisis fresco | % de sílice | Sílice del análisis fresco anterior a `lab_last1`. |
| `lab_last3` | Antepenúltimo análisis fresco | % de sílice | Sílice del análisis fresco anterior a `lab_last2`. |
| `lab_mean6` | Media de los últimos 6 análisis | % de sílice | Media de los últimos 6 análisis frescos llegados. |
| `lab_mean24` | Media de los últimos 24 análisis | % de sílice | Media de los últimos 24 análisis frescos llegados. |
| `lab_age_h` | Antigüedad del último análisis | horas | Horas entre la muestra del último análisis fresco y `t − latency_hours`. |
| `feed_silica_pct` | Sílice de la alimentación | % de sílice | La de la última hora con análisis llegado (`t − latency_hours`). |
| `feed_iron_pct` | Hierro de la alimentación | % de hierro | La de la última hora con análisis llegado (`t − latency_hours`). |
| `feed_silica_age_h` | Antigüedad de la sílice de la alimentación | horas | Horas desde el último cambio de la sílice de la alimentación, en esa hora. |
| `feed_iron_age_h` | Antigüedad del hierro de la alimentación | horas | Horas desde el último cambio del hierro de la alimentación, en esa hora. |

## Tablas intermedias

No se versionan y nunca salen de la máquina que corre el flujo:

- `data/interim/source_rows.parquet` y `data/interim/source_hours.parquet`: las filas y las horas canónicas que escribe la lectura estricta del ARFF, con las marcas de frescura de cada hora, y un manifiesto de huellas (`interim_manifest.json`).
- `data/raw/deliveries/`: las entregas que publica `deliver` (el lanzamiento, 40 diarias y el cierre), cada una en dos archivos Parquet, las filas y las horas de su período, con un manifiesto (`manifest.json`: período, filas, SHA-256 y estado de cada una).
- `data/warehouse/flotsilica.sqlite`: el almacén, con las filas y las horas cargadas (`raw_rows`, `lab_hours`, `hour_aggregates`), las entregas y las corridas, los resultados de la validación, el registro de modelos (`model_registry`), las estimaciones emitidas y las de cada método (`estimates`, `method_estimates`, de solo inserción: tres disparadores impiden cambiar o repetir una fila), el seguimiento (`tracking`), las tablas de la evaluación (`eval_*`) y los marts del modelo estrella.
- `data/models/v1.pkl`: el modelo congelado del lanzamiento, que solo se carga si su tamaño y su SHA-256 son los del registro (M03, runbook R6).
- `data/interim/runs/<run_key>.json`: el estado de cada corrida, tarea por tarea, con sus tiempos, sus picos de memoria con el contador y, si falló, la traza.

## Tablas exportadas

Las 20 tablas del modelo semántico: 7 dimensiones y 13 hechos, que se escriben en `outputs/powerbi/` con un manifiesto de huellas (`manifest.json`). Las 15 relaciones (todas de uno a varios, en un solo sentido) y las 21 medidas DAX están en el diseño del tablero (`dashboard/powerbi-design.html`). Cada sección dice qué es la tabla, dónde se escribe y su clave (una dimensión) o su grano (un hecho); las columnas están en el orden del Parquet.

<!-- columns:start -->
### `dim_date`

Dimensión. Calendario, del primer al último día que tiene horas. Se versiona en `outputs/powerbi/dim_date.parquet`. Clave: `date_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `date_key` | entero 32 | — | Fecha, como AAAAMMDD. |
| `date` | fecha | — | Fecha. |
| `year` | entero 32 | — | Año. |
| `month` | entero 32 | — | Mes (1-12). |
| `month_name_es` | texto | — | Nombre del mes. |
| `weekday_es` | texto | — | Nombre del día de la semana. |
| `test_week` | entero 32 | — | Semana de la prueba (semanas de 7 días desde su primera hora); vacía fuera de ella. |

### `dim_hour`

Dimensión. Todas las horas, una por una, de la primera hora con datos a la última estimada (también las que no tienen datos). Se versiona en `outputs/powerbi/dim_hour.parquet`. Clave: `hour_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `hour_key` | entero 64 | — | Hora, como AAAAMMDDHH. |
| `hour` | fecha y hora | — | Hora (el comienzo del intervalo de una hora). |
| `date` | fecha | — | Fecha de la hora. |
| `hour_of_day` | entero 32 | — | Hora del día (0-23). |
| `block` | texto | — | Bloque de la partición en el tiempo. |
| `block_es` | texto | — | Bloque de la partición, en español. |
| `lab_state` | texto | — | Análisis de la hora: fresh, interpolated, held, pending (todavía no llegó) o missing (no hay datos). |
| `lab_state_es` | texto | — | Análisis de la hora, en español. |
| `is_partial` | verdadero/falso | — | La hora tiene menos filas que las 180 completas. |
| `rows` | entero 32 | filas | Filas de sensores de la hora. |

### `dim_horizon`

Dimensión. Los horizontes del modelo. Se versiona en `outputs/powerbi/dim_horizon.parquet`. Clave: `horizon_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `horizon_key` | entero 8 | — | Horizonte: 0 la hora que cerró, 1 la siguiente, 2 la de dentro de dos horas. |
| `horizon_es` | texto | — | Qué hora estima el horizonte, en español. |
| `hours_ahead` | entero 32 | horas | Horas después de la hora que cerró. |

### `dim_method`

Dimensión. El modelo, las reglas B0 a B2 y los modelos de comparación. Se versiona en `outputs/powerbi/dim_method.parquet`. Clave: `method_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `method_key` | texto | — | Método: el modelo, una regla o un modelo de comparación. |
| `method_es` | texto | — | Método, en español. |
| `kind_es` | texto | — | Clase: modelo, regla o comparación. |

### `dim_sensor`

Dimensión. Los 19 sensores de la planta. Se versiona en `outputs/powerbi/dim_sensor.parquet`. Clave: `sensor_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `sensor_key` | texto | — | Sensor de la planta. |
| `column` | texto | — | Atributo del archivo fuente. |
| `name_es` | texto | — | Sensor, en español. |
| `group_es` | texto | — | Grupo: reactivos, pulpa, aire o nivel. |
| `unit_es` | texto | — | Unidad: la fuente no la dice. |

### `dim_model`

Dimensión. El modelo congelado del lanzamiento, un renglón por horizonte. Se versiona en `outputs/powerbi/dim_model.parquet`. Clave: `model_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `model_key` | texto | — | Modelo congelado de un horizonte (versión y horizonte, por ejemplo v1-h0). |
| `model_version` | texto | — | Versión del modelo. |
| `horizon_key` | entero 8 | — | Horizonte: 0 la hora que cerró, 1 la siguiente, 2 la de dentro de dos horas. |
| `family` | texto | — | Familia del candidato elegido en V1. |
| `feature_set` | texto | — | Conjunto de rasgos elegido en V1. |
| `target_es` | texto | — | Qué aprende el modelo: el nivel o el cambio. |
| `min_samples_leaf` | entero 32 | — | Muestras mínimas por hoja del candidato elegido. |
| `half_width` | decimal | % de sílice | Semiancho del rango del 80 %, calibrado en V2. |
| `b_star` | texto | — | Base más fuerte de este horizonte (B*). |
| `b2_k` | entero 32 | análisis | Análisis que promedia la regla B2 de este horizonte. |
| `trained_on_es` | texto | — | Con qué se reajustó. |
| `config_sha256` | texto | — | Huella de la configuración sellada del modelo. |
| `seal_state` | texto | — | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |

### `dim_pipeline_run`

Dimensión. Las corridas del flujo. Se versiona en `outputs/powerbi/dim_pipeline_run.parquet`. Clave: `run_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `run_key` | texto | — | Corrida que lo escribió. |
| `started_at` | fecha y hora | — | Inicio. |
| `finished_at` | fecha y hora | — | Fin. |
| `status` | texto | — | Estado: running, ok, failed, rejected o no_delivery. |
| `delivery_id` | texto | — | Entrega que cargó. |
| `as_of` | fecha y hora | — | Instante de cálculo de la corrida. |
| `source_sha256` | texto | — | Huella de la fuente. |
| `rows_delivery` | entero 64 | filas | Filas de la entrega. |
| `estimates_issued` | entero 64 | estimaciones | Estimaciones emitidas. |
| `estimates_missing` | entero 64 | estimaciones | Estimaciones sin las entradas necesarias. |
| `peak_working_set_mb` | decimal | MB | Pico del conjunto de trabajo. |
| `peak_commit_mb` | decimal | MB | Pico de memoria confirmada (informativo). |
| `memory_counter` | texto | — | Contador de memoria que dio las cifras. |
| `message` | texto | — | Mensaje de la corrida. |

### `fact_hour_process`

Hecho. Cada sensor en cada hora cerrada. Se versiona en `outputs/powerbi/fact_hour_process.parquet`. Grano: `hour_key`, `sensor_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `hour_key` | entero 64 | — | Hora, como AAAAMMDDHH. |
| `sensor_key` | texto | — | Sensor de la planta. |
| `mean` | decimal | — | Media del sensor en la hora. |
| `std` | decimal | — | Desviación estándar muestral del sensor en la hora; vacía con una sola fila. |
| `last` | decimal | — | Último valor del sensor en la hora. |

### `fact_hour_lab`

Hecho. El análisis de cada hora cerrada, solo desde que llegó. Se versiona en `outputs/powerbi/fact_hour_lab.parquet`. Grano: `hour_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `hour_key` | entero 64 | — | Hora, como AAAAMMDDHH. |
| `silica_pct` | decimal | % de sílice | Sílice del concentrado; vacía hasta que llega el análisis. |
| `iron_conc_pct` | decimal | % de hierro | Hierro del concentrado; vacío hasta que llega el análisis. |
| `feed_silica_pct` | decimal | % de sílice | Sílice de la alimentación; vacía hasta que llega el análisis. |
| `feed_iron_pct` | decimal | % de hierro | Hierro de la alimentación; vacío hasta que llega el análisis. |
| `lab_state` | texto | — | fresh, interpolated, held o pending (todavía no llegó). |
| `feed_silica_age_h` | decimal | horas | Horas desde el último cambio de la sílice de la alimentación. |
| `feed_iron_age_h` | decimal | horas | Horas desde el último cambio del hierro de la alimentación. |
| `available_at` | fecha y hora | — | Instante en que llega el análisis (la hora más la espera del laboratorio). |

### `fact_estimate`

Hecho. Cada estimación emitida, una vez, con su análisis y sus errores cuando el análisis llegó. Se versiona en `outputs/powerbi/fact_estimate.parquet`. Grano: `hour_key`, `horizon_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `hour_key` | entero 64 | — | Hora, como AAAAMMDDHH. |
| `horizon_key` | entero 8 | — | Horizonte: 0 la hora que cerró, 1 la siguiente, 2 la de dentro de dos horas. |
| `model_key` | texto | — | Modelo congelado de un horizonte (versión y horizonte, por ejemplo v1-h0). |
| `issue_at` | fecha y hora | — | Instante en que se emitió la estimación. |
| `status` | texto | — | ok o missing_inputs (sin las entradas necesarias). |
| `estimate` | decimal | % de sílice | Estimación de la sílice. |
| `low` | decimal | % de sílice | Límite inferior del rango del 80 %. |
| `high` | decimal | % de sílice | Límite superior del rango del 80 %. |
| `persistence` | decimal | % de sílice | Último análisis fresco (la persistencia). |
| `b_star` | decimal | % de sílice | Lo que dice la base más fuerte del horizonte. |
| `actual` | decimal | % de sílice | Análisis fresco de la hora; vacío hasta que llega o si no es fresco. |
| `abs_error` | decimal | % de sílice | Error absoluto del modelo; vacío hasta que llega el análisis. |
| `abs_error_persistence` | decimal | % de sílice | Error absoluto de la persistencia. |
| `abs_error_b_star` | decimal | % de sílice | Error absoluto de la base más fuerte. |
| `covered` | verdadero/falso | — | El análisis cayó dentro del rango. |
| `is_censored` | verdadero/falso | — | La hora estimada está fuera de los datos: nunca se evalúa. |
| `run_key` | texto | — | Corrida que lo escribió. |

### `fact_method_metrics`

Hecho. Las cifras de cada método por horizonte; las de V1 y V2 son de validación, no de la prueba. Se versiona en `outputs/powerbi/fact_method_metrics.parquet`. Grano: `scope`, `horizon_key`, `method_key`, `seal_state`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `scope` | texto | — | Bloque evaluado: valid_v1, valid_v2 (validación) o test (la prueba). |
| `horizon_key` | entero 8 | — | Horizonte: 0 la hora que cerró, 1 la siguiente, 2 la de dentro de dos horas. |
| `method_key` | texto | — | Método: el modelo, una regla o un modelo de comparación. |
| `mae` | decimal | % de sílice | Error absoluto medio. |
| `rmse` | decimal | % de sílice | Raíz del error cuadrático medio. |
| `bias` | decimal | % de sílice | Sesgo: media de estimación menos análisis. |
| `hours` | entero 32 | horas | Horas evaluadas. |
| `coverage` | decimal | proporción | Parte de las horas con el análisis dentro del rango (solo el modelo). |
| `is_b_star` | verdadero/falso | — | Es la base más fuerte de su horizonte (B*). |
| `ci_low_vs_b_star` | decimal | % de sílice | Límite inferior del intervalo del 95 % de MAE(modelo) − MAE(B*). |
| `ci_high_vs_b_star` | decimal | % de sílice | Límite superior del intervalo del 95 % de MAE(modelo) − MAE(B*). |
| `seal_state` | texto | — | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |

### `fact_weekly_mae`

Hecho. El error del modelo, de la persistencia y de la base más fuerte por semana de la prueba. Se versiona en `outputs/powerbi/fact_weekly_mae.parquet`. Grano: `test_week`, `horizon_key`, `method_key`, `seal_state`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `test_week` | entero 32 | — | Semana de la prueba (1 en adelante). |
| `horizon_key` | entero 8 | — | Horizonte: 0 la hora que cerró, 1 la siguiente, 2 la de dentro de dos horas. |
| `method_key` | texto | — | Método: el modelo, una regla o un modelo de comparación. |
| `mae` | decimal | % de sílice | Error absoluto medio de la semana. |
| `hours` | entero 32 | horas | Horas de la semana. |
| `seal_state` | texto | — | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |

### `fact_evaluation_summary`

Hecho. Los criterios de la prueba y su veredicto. Se versiona en `outputs/powerbi/fact_evaluation_summary.parquet`. Grano: `criterion_id`, `seal_state`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `criterion_id` | texto | — | Criterio, de C01 a C10. |
| `name_es` | texto | — | Nombre del criterio. |
| `value` | decimal | — | Valor medido. |
| `baseline_value` | decimal | — | Valor de la base con que se compara. |
| `ci_low` | decimal | — | Límite inferior del intervalo. |
| `ci_high` | decimal | — | Límite superior del intervalo. |
| `threshold_es` | texto | — | Umbral, en español. |
| `passed` | verdadero/falso | — | Cumple; vacío en el informativo. |
| `seen_by_research` | texto | — | Si la investigación lo vio antes. |
| `seen_by_planner` | texto | — | Si el plan lo vio antes. |
| `verdict_es` | texto | — | Veredicto, en español. |
| `seal_state` | texto | — | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |

### `fact_selection`

Hecho. Los candidatos de cada horizonte con su error en V1. Se versiona en `outputs/powerbi/fact_selection.parquet`. Grano: `horizon_key`, `family`, `feature_set`, `target`, `min_samples_leaf`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `horizon_key` | entero 8 | — | Horizonte: 0 la hora que cerró, 1 la siguiente, 2 la de dentro de dos horas. |
| `family` | texto | — | Familia del candidato. |
| `feature_set` | texto | — | Conjunto de rasgos. |
| `target` | texto | — | Objetivo: level o change. |
| `min_samples_leaf` | entero 32 | — | Muestras mínimas por hoja. |
| `mae_v1` | decimal | % de sílice | Error absoluto medio en V1. |
| `chosen` | verdadero/falso | — | Es el elegido. |

### `fact_sensitivity`

Hecho. Las sensibilidades de los sensores, como asociación del modelo. Se versiona en `outputs/powerbi/fact_sensitivity.parquet`. Grano: `sensor_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `sensor_key` | texto | — | Sensor de la planta. |
| `importance_v1` | decimal | % de sílice | Importancia por permutación en V1. |
| `importance_v2` | decimal | % de sílice | Importancia por permutación en V2. |
| `rho_min` | decimal | — | Menor correlación de Spearman de la dependencia parcial. |
| `rho_max` | decimal | — | Mayor correlación de Spearman de la dependencia parcial. |
| `sign_stable` | verdadero/falso | — | El signo de la dependencia parcial no cambia. |
| `pd_range` | decimal | % de sílice | Recorrido de la estimación en la curva de dependencia parcial. |
| `passes` | verdadero/falso | — | Pasa la compuerta de estabilidad. |
| `test_sign_kept` | verdadero/falso | — | Conserva el signo en la prueba; vacío si no pasó la compuerta o la prueba no se evaluó. |
| `label_es` | texto | — | Asociación del modelo o sin asociación estable: nunca una causa. |

### `fact_pd_curve`

Hecho. Las curvas de dependencia parcial de los sensores que pasaron la compuerta. Se versiona en `outputs/powerbi/fact_pd_curve.parquet`. Grano: `sensor_key`, `point`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `sensor_key` | texto | — | Sensor de la planta. |
| `point` | entero 32 | — | Punto de la grilla. |
| `grid_value` | decimal | — | Valor del sensor en el punto. |
| `mean_estimate` | decimal | % de sílice | Estimación media del modelo con ese valor. |

### `fact_variants`

Hecho. Qué dice la prueba si se cambia un supuesto; informativo, nunca se usa para elegir. Se versiona en `outputs/powerbi/fact_variants.parquet`. Grano: `variant`, `horizon_key`, `method_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `variant` | texto | — | Variante: latency_3, latency_4, refit_all o all_hours. |
| `variant_es` | texto | — | Variante, en español. |
| `horizon_key` | entero 8 | — | Horizonte: 0 la hora que cerró, 1 la siguiente, 2 la de dentro de dos horas. |
| `method_key` | texto | — | Método: el modelo, una regla o un modelo de comparación. |
| `mae` | decimal | % de sílice | Error absoluto medio. |
| `hours` | entero 32 | horas | Horas evaluadas. |
| `ci_low` | decimal | — | Límite inferior del intervalo del 95 % de MAE(modelo) − MAE(persistencia). |
| `ci_high` | decimal | — | Límite superior del intervalo del 95 % de MAE(modelo) − MAE(persistencia). |

### `fact_leakage`

Hecho. La demostración de la fuga: la partición aleatoria y el hierro del concentrado. Se versiona en `outputs/powerbi/fact_leakage.parquet`. Grano: `check`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `check` | texto | — | Comprobación. |
| `check_es` | texto | — | Qué se hizo, en español. |
| `mae` | decimal | % de sílice | Error absoluto medio. |
| `r2` | decimal | — | Coeficiente de determinación. |
| `note_es` | texto | — | Lo que enseña. |

### `fact_data_quality`

Hecho. La calidad de los datos, día por día. Se versiona en `outputs/powerbi/fact_data_quality.parquet`. Grano: `date_key`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `date_key` | entero 32 | — | Fecha, como AAAAMMDD. |
| `hours` | entero 32 | horas | Horas con datos. |
| `missing_hours` | entero 32 | horas | Horas sin datos dentro del período de los datos. |
| `partial_hours` | entero 32 | horas | Horas con menos filas que las completas. |
| `fresh` | entero 32 | horas | Análisis nuevos que ya llegaron. |
| `interpolated` | entero 32 | horas | Análisis interpolados que ya llegaron. |
| `held` | entero 32 | horas | Análisis repetidos que ya llegaron. |
| `stuck_sensor_hours` | entero 32 | horas | Horas en que algún sensor no se movió. |
| `feed_unchanged_24h` | entero 32 | horas | Horas con la alimentación sin cambio desde hace 24 horas o más. |

### `fact_validation`

Hecho. El resultado de cada regla en cada corrida. Se versiona en `outputs/powerbi/fact_validation.parquet`. Grano: `run_key`, `rule_id`.

| Columna | Tipo | Unidad | Significado |
| --- | --- | --- | --- |
| `run_key` | texto | — | Corrida que lo escribió. |
| `rule_id` | texto | — | Regla de validación. |
| `name_es` | texto | — | Nombre de la regla. |
| `severity` | texto | — | bloqueante, advertencia o informativa. |
| `scope` | texto | — | Alcance: source, delivery, hours o model. |
| `aggregation` | texto | — | Cómo se agrega entre corridas: source, per_run o latest. |
| `status` | texto | — | pasa, falla o advierte. |
| `rows_affected` | entero 64 | filas | Filas afectadas. |
| `hours_affected` | entero 64 | horas | Horas afectadas. |
<!-- columns:end -->
