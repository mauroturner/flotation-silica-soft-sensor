# Investigación previa: sílice en el concentrado, sin esperar al laboratorio

Fecha de la investigación: 2026-11-17.

**Leyenda de etiquetas**

- **[Verificado]**: medido directamente sobre el archivo real descargado, o comprobado en la página de la fuente. Se indica el script o la URL.
- **[Documentación]**: tomado de una página oficial o de un registro bibliográfico que se abrió. Se indica la URL.
- **[Fuente secundaria]**: tomado de un fragmento de búsqueda o de un texto que no se pudo leer completo. Conviene confirmarlo antes de citarlo.
- **[Inferido]**: deducción propia a partir de datos observados. No está confirmada por una fuente.

Esta investigación es una primera mirada: no es el resultado del proyecto. Las cifras de la sección "Primera mirada del modelo" salen de una sola configuración, sin búsqueda de hiperparámetros, evaluada en un único bloque de validación.

**Aviso sobre el periodo de prueba.** El plan fija la prueba en agosto y septiembre de 2017 (2017-08-01 a 2017-09-09). La primera pasada de descripción (estructura de las horas, huecos, rampas del laboratorio y perfil del objetivo: scripts `s02` a `s06`) se calculó sobre el archivo completo, incluidos esos meses. Esas cifras solo describen el archivo y no intervienen en ninguna decisión de modelo. Las cifras del perfil del objetivo y de autocorrelación que aparecen en este documento se recalcularon sobre el periodo previo a la prueba (`s08`). Los modelos, las líneas base y las sensibilidades usan solo el periodo previo a la prueba (`s07` a `s10`). En ningún paso se calcularon métricas sobre la prueba; solo se contaron sus filas y horas (`s09`).

---

## Hallazgos principales

1. **Fuente y licencia.** El conjunto es "Quality Prediction in a Mining Process", de Eduardo Magalhães Oliveira, en Kaggle, con licencia CC0. El archivo usado es el de OpenML 43311 (ARFF). Su MD5, `c1091ada99b288fb881077dbd43ff562`, coincide con el que OpenML publica en sus metadatos. El archivo no se comparó byte a byte con el CSV de Kaggle. [Verificado]
2. **Muestreo.** Hay 4.097 horas distintas y 737.453 filas. Casi todas las horas (4.095 de 4.097) tienen 180 filas, una cada 20 segundos. Las variables de proceso (aire, pulpa, reactivos, niveles) varían dentro de la hora. Las cuatro variables de laboratorio se miden una vez por hora. [Verificado: `s01`, `s02`]
3. **Laboratorio dentro de la hora.** Las dos variables de alimentación (`% Iron Feed`, `% Silica Feed`) son constantes dentro de cada hora en el 100 % de las horas. En cambio, `% Silica Concentrate` (el objetivo) cambia dentro de la hora en 310 horas (7,6 %). En esas horas las 180 filas siguen una rampa lineal exacta que termina en el valor de la hora siguiente. Este detalle no está en la descripción del conjunto y debe tratarse en el plan. [Verificado: `s03`, `s04`, `s05`]
4. **Huecos.** Hay un único hueco de 318 horas, de 2017-03-16 06:00 a 2017-03-29 11:00. No hay otros huecos de más de una hora. [Verificado: `s02`]
5. **Objetivo.** En el periodo previo a la prueba, `% Silica Concentrate` tiene media 2,32, desviación 1,13 y asimetría 0,99 (cola a la derecha). Su autocorrelación en horas es alta: 0,76 con un rezago de una hora, 0,66 con dos, 0,58 con tres, 0,36 con seis, 0,22 con doce y 0,19 con veinticuatro. [Verificado: `s08`]
6. **Fuga de información con `% Iron Concentrate`.** Esa variable se mide en la misma hora que el objetivo. Su correlación con la sílice es -0,80 (r² lineal de 0,64). No puede entrar como rasgo. [Verificado: `s08`]
7. **Fuga por partición aleatoria.** Con el mismo modelo (HistGradientBoosting con 19 sensores por fila), la partición aleatoria da R² 0,565 y MAE 0,555. La partición por bloques de tiempo da R² -0,511 y MAE 0,906. En la partición aleatoria, el 100 % de las horas de prueba aparecen en entrenamiento; en la de bloques, el 0 %. [Verificado: `s07`]
8. **Retraso del laboratorio.** El archivo no tiene columna de retraso. El único dato encontrado es el de un análisis de laboratorio de 2 horas mínimo en otra planta, en un artículo de 2018 (Moraes y otros, ABM). Se toma como supuesto de trabajo, con sensibilidad a 1 y 2 horas adicionales. La persistencia empeora de MAE 0,452 (un rezago) a 0,574 (dos) y 0,645 (tres). [Verificado en la cifra del artículo; Inferido en la aplicación]
9. **Líneas base en validación (2017-06-02 a 2017-07-30, 1.416 horas, 59 días).** La persistencia del último valor conocido (un rezago) da MAE 0,452 con intervalo al 95 % por bloques de días de [0,409; 0,499]. La media de la fase de entrenamiento da MAE 0,958. La media móvil de los últimos seis valores de laboratorio da MAE 0,563. Un modelo lineal sobre agregados de sensores da MAE 0,839. [Verificado: `s08`]
10. **Primera mirada.** `HistGradientBoostingRegressor` con agregados por hora de los sensores y rezagos de laboratorio da MAE 0,531. **No supera a la persistencia**: la diferencia es +0,078, con IC 95 % de [0,055; 0,101]. Frente a una media móvil de seis valores, la diferencia es -0,032 con IC [-0,067; 0,003], que cruza cero. Sin rezagos de laboratorio, el mismo modelo da MAE 0,816 y R² -0,23. [Verificado: `s08`]
11. **Sensibilidades débiles.** La importancia por permutación de cada sensor es menor que 0,007 en MAE, sobre una base de 0,53 a 0,82. La dirección de la dependencia parcial de los caudales de reactivos cambia entre el modelo de sensores solos y el modelo completo. Con estos datos no se puede afirmar qué variable mueve la estimación con un signo estable. [Verificado: `s09`]
12. **Partición propuesta.** Entrenamiento de 2017-03-10 a 2017-05-31 (1.673 horas con objetivo); purga de 24 h; validación de 2017-06-02 a 2017-07-30 (1.416 horas); purga de 24 h; prueba de 2017-08-01 a 2017-09-09 (960 horas, 172.800 filas, sin usar). [Inferido en la elección; conteos verificados: `s08`, `s09`]

---

## Objetivo

Verificar la fuente, la licencia, el muestreo, los huecos, el comportamiento del objetivo dentro de la hora, el riesgo de fuga, el retraso del laboratorio, las líneas base, una primera mirada a un modelo de árboles con rezagos de laboratorio, las sensibilidades que el sitio promete y una partición en el tiempo, para que el planificador escriba requisitos y un plan del proyecto 05 (`05-Mining-Flotation-Silica`, tarea T6 en `odd/tasks/portfolio-projects.md`).

El proyecto predice el porcentaje de sílice en el concentrado de una planta de flotación de mineral de hierro antes de que llegue el resultado horario del laboratorio. Se usan las variables de proceso de cada hora.

---

## Fuentes

**Datos**

- Página del conjunto en Kaggle: https://www.kaggle.com/datasets/edumagalhaes/quality-prediction-in-a-mining-process. La página es una aplicación de JavaScript y no devolvió su texto. Los metadatos se leyeron de su API: https://www.kaggle.com/api/v1/datasets/view/edumagalhaes/quality-prediction-in-a-mining-process. [Verificado: API leída]
  - Autor (campo `ownerName`): Eduardo Magalhães Oliveira. Licencia: CC0 (Public Domain). Última actualización (`lastUpdated`): 2017-12-06. Tamaño declarado: 183.766.261 bytes. [Verificado]
  - Descripción del conjunto, en su texto citado: "The main goal is to use this data to predict how much impurity is in the ore concentrate." y "Target is to predict the last column, which is the % of silica in the iron ore concentrate." [Verificado]
  - Las advertencias de la sección de discusión de Kaggle no se pudieron leer. Queda abierto. [Hueco declarado]
- Página de OpenML 43311: https://www.openml.org/search?type=data&sort=runs&id=43311&status=active. No devolvió contenido útil. Los metadatos se leyeron de la API JSON: https://www.openml.org/api/v1/json/data/43311. [Verificado: API leída]
  - Nombre: "Quality-Prediction-in-a-Mining-Process", versión 1. Licencia: CC0. Subida: 2022-03-23. Formato: ARFF, idioma inglés. Fecha de recolección indicada: 06122017 (6 de diciembre de 2017). MD5: `c1091ada99b288fb881077dbd43ff562`. [Verificado]
  - OpenML no declara autor, número de filas, número de variables ni cita original. [Verificado]
  - Cambios de OpenML frente al original: todas las variables están declaradas como `STRING` en el ARFF, y los números conservan la coma decimal (por ejemplo `'55,2'`). [Verificado: cabecera del archivo, líneas 1-40 y 41 de datos]
  - Encabezado del ARFF (comentarios): "Some columns were sampled every 20 second. Others were sampled on a hourly base." y "from march of 2017 until september of 2017". [Verificado]
- Archivo local: `05-Mining-Flotation-Silica/data/raw/openml-43311-quality-prediction-mining-process.arff`, 185.243.565 bytes. SHA-256 indicado por el padre: `a25122979ba8c5fb9c12e361db61032efc6892a24b5746cc8309da601d9639b2`. MD5 calculado en esta investigación: `c1091ada99b288fb881077dbd43ff562`, igual al de OpenML. [Verificado]
- Lo que no se verificó: que el archivo sea idéntico al CSV de Kaggle. Los tamaños no son comparables (el ARFF tiene cabecera y comillas). [Verificado en el tamaño; hueco declarado]

**Literatura**

- Pural, Y. E. (2023). "Developing a data-driven soft sensor to predict silicate impurity in iron ore flotation concentrate". *Physicochemical Problems of Mineral Processing* 59(5). DOI 10.37190/PPMP/169823. Página abierta: https://research.itu.edu.tr/en/publications/developing-a-data-driven-soft-sensor-to-predict-silicate-impurity/ [Verificado: página; el artículo completo no se abrió]
- Moraes, C., Drumond, P., Teixeira, M., Kappes, D., Magalhães, E. (2018). "Soft sensor: machine learning tradicional ou deep learning?". *Proceedings of the Automation & IT Seminar* (ABM) 22, pp. 231-242. DOI 10.5151/2237-0234-31915. Página abierta: https://abmproceedings.com.br/en/article/download-pdf/soft-sensor-machine-learning-tradicional-ou-deep-learning [Verificado: resumen]
- Basilio y otros, SBC (sbsi_estendido, artículo 42009): https://sol.sbc.org.br/index.php/sbsi_estendido/article/download/42009/41778/. El PDF no se pudo leer con la herramienta. Solo hay un fragmento de búsqueda. [Fuente secundaria; no citable como resultado]
- Ahmed y Pourrahimian (2024), Universidad de Alberta: https://sites.ualberta.ca/MOL/DataFiles/2024_Papers/501_Ahmed.pdf. El PDF no se pudo leer. Un fragmento de búsqueda describe datos de otra planta con muestreo de dos minutos; no está verificado. [Fuente secundaria; no citable]
- Blog de un proyecto con este conjunto: https://reidglaze.github.io/posts/Mining-Intelligence. Protegido con contraseña. [Hueco declarado]
- Tesis de maestría de Uppsala (https://www.uppsatser.se/uppsats/7cc038d8e2/): aparece en la búsqueda; no se abrió. [Fuente secundaria]

**Librerías**

- pandas 2.3.3, NumPy 2.4.6, scikit-learn 1.9.1, SciPy 1.17.1 (entorno de `04-Ecommerce-Churn-Risk/.venv`, usado con `-I`). Sin instalaciones. [Verificado]
- scikit-learn `HistGradientBoostingRegressor`, `Ridge`, `permutation_importance` y `partial_dependence`: versión instalada 1.9.1. La documentación en línea no se abrió. [Documentación en la versión instalada; hueco de lectura]

---

## Metodología de verificación

- **Entorno**: Windows 10 Pro. Intérprete del `.venv` del proyecto 04, con `-I` (sin instalar paquetes). Scripts y datos intermedios en el directorio temporal de la investigación, fuera de todos los repositorios (ruta en "Scripts y salidas").
- **Análisis de la fila**: el archivo se lee desde `@DATA` con `quotechar="'"`; las comas decimales se sustituyen por punto y se convierten a flotante. No hubo valores vacíos ni cadenas no numéricas en las 23 variables numéricas. [Verificado: `s01`]
- **Regla de la hora**: una hora es la marca `YYYY-MM-DD HH:00:00`. Los minutos y segundos son cero en todas las filas. [Verificado: `s02`]
- **Valor de laboratorio de la hora**: la primera fila de cada hora. La rampa lineal de las horas con variación termina exactamente en la primera fila de la hora siguiente (`s04`, `s05`). Por eso la primera fila es el valor de la hora (inicio de la muestra). [Verificado en la forma de la rampa; Inferido en la interpretación]
- **Partición**: periodo previo a la prueba = todo lo anterior a 2017-07-31 00:00. Los modelos se entrenan en `train` y se evalúan en `validation`. `test` no se carga (`s07`, `s08`, `s09`, `s10` filtran antes de leer valores). [Verificado]
- **Incertidumbre**: bootstrap por bloques de días (B = 2.000) para la diferencia de MAE entre dos modelos sobre la misma validación. El día es la unidad de remuestreo porque las horas vecinas están correlacionadas. [Inferido en la elección]
- **Límites**: la validación tiene 59 días y 1.416 horas. Un solo bloque. La diferencia de MAE de 0,03 está en el rango del error de muestreo. Las cifras son de un solo corte. [Verificado en el diseño]

---

## Estructura de las horas

### Filas por hora

- Filas totales: 737.453. Horas distintas: 4.097. Primera: 2017-03-10 01:00. Última: 2017-09-09 23:00. [Verificado: `s01`, `s02`]
- Horas con 180 filas: 4.095 (99,95 %). Dos horas incompletas: 2017-03-10 01:00 con 174 filas y 2017-04-10 00:00 con 179. [Verificado: `s02`, `s09`]
- Una cadena de 180 filas por hora equivale a 3.600 s / 20 s. [Verificado]

### Variables constantes dentro de la hora

| Variable | Horas en que es constante (una sola cifra) | Lectura |
|---|---:|---|
| `% Iron Feed` | 100,00 % | Lab de alimentación, una cifra por hora |
| `% Silica Feed` | 100,00 % | Lab de alimentación, una cifra por hora |
| `% Iron Concentrate` | 94,73 % | 216 horas con rampa |
| `% Silica Concentrate` (objetivo) | 92,43 % | 310 horas con rampa |
| `air_flow_04` y `air_flow_05` | 11,35 % | Sensor que se repite o se queda fijo; no investigado |
| Resto de sensores de proceso | 0,1 % a 0,4 % | Varían dentro de la hora |

[Verificado: `s02`]

### Rampa lineal del laboratorio

- En las 310 horas con variación, la sílice del concentrado sigue una recta: el residuo máximo frente a la recta es de 6,4·10⁻¹¹. Lo mismo para el hierro del concentrado en 216 horas (residuo máximo de 5,7·10⁻¹¹). [Verificado: `s04`]
- El último valor de la rampa, más un paso, es igual al primer valor de la hora siguiente. La mediana y el percentil 90 de la diferencia son 0,0000. [Verificado: `s04`]
- Las horas con rampa forman 84 tramos consecutivos. La mediana es 2 horas y el máximo 27. Abril tiene 115 horas y mayo 73. [Verificado: `s05`]
- Consecuencia: en esas horas, las filas 2 a 180 del objetivo contienen información de la hora siguiente. Un modelo a nivel de fila que use el objetivo de cada fila tendría una fuga. [Inferido]

### Variables de alimentación

- `% Silica Feed` no cambia entre horas consecutivas en el 92,6 % de los pares (archivo completo). Cambia unas 300 veces en todo el archivo. [Verificado: `s06`]
- Periodo previo a la prueba: 227 tramos de valor constante. Mediana: 9 horas. Tramos de 24 horas o más: 9. [Verificado: `s09`]
- Tramos más largos (periodo previo a la prueba):
  - 792 horas de 2017-05-13 01:00 a 2017-06-15 00:00, con sílice de alimentación 6,26 (cruza el corte entre entrenamiento y validación).
  - 167 horas de 2017-07-24 01:00 a 2017-07-30 23:00, con 10,8.
  - 81 horas de 2017-05-09 16:00 a 2017-05-13 00:00, con 20,24.
  [Verificado: `s09`]
- Consecuencia: el laboratorio de alimentación queda "congelado" durante días. Un rezago de esa variable no es una medición nueva. El plan debe decidir cómo tratar un valor que no cambia. [Inferido]

---

## Huecos

- El archivo tiene 4.415 horas entre la primera y la última. Hay 4.097 con datos. Faltan 318 horas. [Verificado: `s02`]
- Hueco único: 2017-03-16 06:00 a 2017-03-29 11:00, 318 horas. No hay otros huecos de más de una hora, ni horas aisladas faltantes. [Verificado: `s02`]
- Lo que el sitio dice ("318 h sin datos, en marzo de 2017") es correcto. [Verificado]
- Consecuencia para las particiones: el entrenamiento tiene 1.673 horas con objetivo, de 1.991 horas en la rejilla. [Verificado: `s08`]

---

## Objetivo: perfil y autocorrelación

Periodo previo a la prueba, valor de la primera fila de cada hora (3.113 horas con objetivo). [Verificado: `s08`]

| Medida | Valor |
|---|---:|
| Media | 2,32 |
| Desviación estándar | 1,13 |
| Mínimo / máximo | 0,77 / 5,53 |
| Percentiles 1, 5, 25, 50, 75, 95, 99 | 1,00; 1,08; 1,44; 1,95; 3,02; 4,73; 5,28 |
| Asimetría | 0,99 |

- **Forma**: unimodal, con una cola larga a la derecha. La mitad de las horas está por debajo de 1,95 (percentil 50), y el 1 % más bajo está en 1,00. En el histograma de 12 intervalos del archivo completo, el intervalo con más horas es de 1,01 a 1,42 (903 horas). [Verificado; la forma se midió sobre el archivo completo, `s06`]
- **Autocorrelación** (pares con ambas horas observadas), periodo previo a la prueba:

| Rezago (horas) | 1 | 2 | 3 | 6 | 12 | 24 |
|---|---:|---:|---:|---:|---:|---:|
| r | 0,760 | 0,656 | 0,577 | 0,363 | 0,220 | 0,192 |

  [Verificado: `s08`]
- Lectura: la serie es muy persistente en las primeras horas y su memoria decae a la mitad hacia las 6 a 12 horas. El rezago de 24 horas no vuelve a cero. Esto sostiene la persistencia como línea base fuerte. [Inferido]
- Con el archivo completo, los valores son 0,774, 0,671, 0,590, 0,378, 0,210 y 0,198. La diferencia es menor de 0,02 y no cambia la lectura. [Verificado: `s06`; cifras del archivo completo]

### Fuga con `% Iron Concentrate`

- Correlación de Pearson con la sílice del concentrado: -0,801 en el periodo previo a la prueba (-0,802 en el archivo completo; Spearman -0,777). [Verificado: `s08`, `s06`]
- Ambas variables se miden en la misma hora que el objetivo. Su uso como rasgo es fuga. Con una relación lineal, esta variable explica el 64 % de la varianza de la sílice (r² = 0,64). [Verificado en r; Inferido en la interpretación]
- El sitio ya la deja fuera. [Verificado: `flotation-silica.ts`]

---

## Laboratorio: retraso y retención

- **No hay columna de retraso en el archivo.** [Verificado]
- **Supuesto de trabajo**: la muestra de la hora k se toma al inicio de la hora (primera fila). El resultado llega L horas después. La predicción de la hora h se emite al cierre de esa hora (instante h+1), con todos sus sensores. El último resultado conocido en ese momento es el de la hora h − d, con d = L − 1. [Inferido]
- **Cifra de referencia**: en un artículo de 2018 sobre una planta de mineral de hierro, la decisión se basaba en un análisis de laboratorio "que tomaba 2 horas mínimo en estar disponible" (Moraes y otros, 2018; resumen en inglés y portugués). Con L = 2 horas, d = 1. Es una cifra de otra planta y otro muestreo. [Verificado en el texto del resumen; Inferido en su uso]
- **Sensibilidad de la persistencia** (validación):

| Retraso d (horas) | MAE | RMSE | R² |
|---:|---:|---:|---:|
| 1 (L = 2 h, supuesto) | 0,452 | 0,760 | 0,369 |
| 2 (L = 3 h) | 0,574 | 0,911 | 0,094 |
| 3 (L = 4 h) | 0,645 | 0,981 | -0,051 |

  [Verificado: `s08`]
- Cada hora adicional de retraso cuesta entre 0,07 y 0,12 unidades de MAE en persistencia. El modelo de la primera mirada se entrenó solo con d = 1 (ver la siguiente sección). No se midió con d = 2 o d = 3. [Verificado en el alcance]

---

## Fuga de información: partición aleatoria frente a bloques de tiempo

Periodo previo a la prueba. Mismo modelo en todos los casos: `HistGradientBoostingRegressor(max_iter=200, learning_rate=0.1, random_state=0)`. Por fila (no por hora). [Verificado: `s07`, `s10`]

| Variables | Partición | Filas de entrenamiento | Filas de prueba | R² | MAE | Horas de prueba que también están en entrenamiento |
|---|---|---:|---:|---:|---:|---:|
| 19 sensores | Aleatoria 80/20 (semilla 0) | 448.664 | 111.849 | 0,565 | 0,555 | 100,00 % |
| 19 sensores | Bloques: entrenamiento hasta 2017-05-31; purga 06-01; prueba 06-02 a 07-30 | 301.133 | 254.880 | -0,511 | 0,906 | 0,00 % |
| 19 sensores + 2 variables de alimentación | Aleatoria 80/20 | 448.664 | 111.849 | 0,698 | 0,457 | — |
| 19 sensores + 2 variables de alimentación | Bloques | 301.133 | 254.880 | -0,837 | 1,068 | — |

**Lectura**

- La partición aleatoria infla el R² en 1,08 unidades para los sensores solos y en 1,53 con las variables de alimentación. El modelo "aprende" la hora que ya vio. [Verificado]
- La partición por bloques de tiempo da un R² negativo: los sensores de una hora no predicen la sílice de un periodo posterior con este modelo. El cambio de nivel del objetivo (ver "Líneas base") explica parte de la caída. [Verificado; la causa es Inferida]
- La cifra de R² 0,965 que reporta Pural (2023) con un "dataset obtenido de Kaggle" no se pudo reproducir con esta configuración (aleatoria con dos variables de alimentación: 0,698). Su partición no está descrita en el texto abierto. [Verificado: el artículo se abrió; la partición es Desconocida]

**Control de fuga que el plan debe escribir**: una prueba que use una variable del mismo instante que el objetivo (por ejemplo `% Iron Concentrate`) debe dar un R² muy alto y bloquear la ejecución. [Inferido]

---

## Partición propuesta

Datos: 2017-03-10 01:00 a 2017-09-09 23:00, con el hueco de marzo.

| Bloque | Ventana | Horas en la rejilla | Horas con objetivo | Estado en esta investigación |
|---|---|---:|---:|---|
| Entrenamiento | 2017-03-10 01:00 a 2017-05-31 23:00 | 1.991 | 1.673 | Usado |
| Purga | 2017-06-01 (24 h) | 24 | — | — |
| Validación | 2017-06-02 00:00 a 2017-07-30 23:00 | 1.416 | 1.416 | Usado (primera mirada) |
| Purga | 2017-07-31 (24 h) | 24 | — | — |
| Prueba | 2017-08-01 00:00 a 2017-09-09 23:00 | 960 | 960 (sin leer valores) | **No usada.** Solo conteo: 172.800 filas. |

- Justificación [Inferido]: la purga de 24 horas separa los bloques para que ninguna ventana de rezagos de 24 horas cruce la frontera. La validación cae después de abril y mayo, los meses con más horas de rampa (115 y 73), y la prueba queda como bloque final sin uso previo.
- Consecuencia: la validación tiene una media del objetivo (2,04) más baja que la de entrenamiento (2,56). Un modelo que aprendió el nivel de entrenamiento se equivoca en el nivel. El planificador debe decidir cómo tratar esto (ver preguntas). [Verificado: `s09`]
- Cada bloque tiene una sola ventana. Con 59 días de validación, la incertidumbre de la diferencia de MAE es del orden de ±0,03 (`s08`). Un segundo bloque de validación no se midió.

---

## Líneas base

Validación 2017-06-02 a 2017-07-30 (1.416 horas, 59 días). Todas las líneas base usan las mismas horas y el mismo objetivo. Los parámetros se fijan con el entrenamiento. [Verificado: `s08`]

| Línea base | MAE | RMSE | R² | IC 95 % del MAE (bootstrap por día) |
|---|---:|---:|---:|---|
| (a) Media de entrenamiento | 0,958 | 1,091 | -0,299 | — |
| (b) Persistencia, d = 1 | 0,452 | 0,760 | 0,369 | [0,409; 0,499] |
| (b) Persistencia, d = 2 | 0,574 | 0,911 | 0,094 | — |
| (b) Persistencia, d = 3 | 0,645 | 0,981 | -0,051 | — |
| (c) Media móvil de 3 últimos valores, d = 1 | 0,492 | 0,755 | 0,378 | — |
| (c) Media móvil de 6 últimos valores, d = 1 | 0,563 | 0,828 | 0,252 | [0,503; 0,627] |
| (c) Media móvil de 12 últimos valores, d = 1 | 0,630 | 0,889 | 0,137 | — |
| (c) Media móvil de 24 últimos valores, d = 1 | 0,675 | 0,939 | 0,038 | — |
| (d) Lineal (Ridge, alfa = 1) sobre 57 agregados de sensores | 0,839 | 1,074 | -0,260 | [0,763; 0,917] |

**Lectura**

- La persistencia con un rezago es la línea base que hay que superar. Ninguna media móvil la supera. [Verificado]
- La media de entrenamiento está lejos de la validación (2,56 frente a 2,04). Ese desplazamiento hace que el R² sea negativo. [Verificado]
- El modelo lineal sobre sensores solos no mejora la media. [Verificado]

---

## Primera mirada del modelo

Primera mirada con una sola configuración de `HistGradientBoostingRegressor` de scikit-learn (`max_iter=300`, `learning_rate=0.05`, `max_leaf_nodes=31`, `min_samples_leaf=50`, `random_state=0`). **No es el resultado del proyecto.** [Verificado: `s08`]

- **Entrada**: 57 agregados por hora de los 19 sensores de proceso (media, desviación estándar y último valor de la hora) más 6 rezagos de laboratorio del objetivo (1, 2, 3, 6, 12 y 24 horas) y 6 rezagos de las variables de alimentación (1, 2 y 3 horas). Total: 69 columnas. Ninguna columna del mismo instante que el objetivo. Ningún identificador. [Verificado]
- **Entrenamiento**: 1.625 horas con todas las entradas, de 1.673 horas con objetivo. Validación: 1.416 horas.
- **Resultado** (validación, 1.416 horas):

| Modelo | MAE | RMSE | R² |
|---|---:|---:|---:|
| HGB, sensores solos (57 columnas) | 0,816 | 1,060 | -0,227 |
| HGB, sensores + rezagos de laboratorio (69 columnas) | **0,531** | 0,750 | 0,386 |
| Persistencia, d = 1 | 0,452 | 0,760 | 0,369 |

- **Diferencia con la persistencia (d = 1)**: HGB − persistencia = +0,078 de MAE, IC 95 % [0,055; 0,101]. **El modelo no supera a la persistencia**. [Verificado]
- Frente a la media móvil de 6 valores (d = 1): HGB − media = -0,032, IC 95 % [-0,067; 0,003]. El intervalo cruza cero: no hay diferencia demostrada. [Verificado]
- Frente a la persistencia con d = 2: HGB − persistencia = -0,043, IC 95 % [-0,073; -0,012]. Esta comparación no es justa: el modelo usa el laboratorio de la hora anterior (d = 1), y la persistencia usa el de dos horas antes. [Verificado en el cálculo; Inferido en la lectura]
- **Hipótesis que el plan debe probar** (no medida aquí): un modelo que predice el cambio respecto al último valor conocido, y no el nivel, podría superar a la persistencia. Un árbol aproxima mal la identidad con pocos datos. [Inferido]

---

## Sensibilidades

Las cifras son asociaciones del modelo en validación, no efectos causales de una acción de control. [Verificado: `s09`]

**Importancia por permutación agrupada** (aumento del MAE al permutar las tres columnas de un sensor, promedio de 5 repeticiones):

| Sensor | Modelo solo sensores (base 0,816) | Modelo completo (base 0,531) |
|---|---:|---:|
| `amina_flow` | 0,0067 | — |
| `level_01` | 0,0063 | — |
| `air_flow_04` | 0,0042 | — |
| `ore_pulp_ph` | 0,0041 | 0,0012 |
| `starch_flow` | 0,0037 | -0,0002 |
| `air_flow_01` | 0,0033 | 0,0003 |
| `ore_pulp_density` | 0,0032 | 0,0005 |
| `air_flow_06` | 0,0005 | 0,0037 |
| `air_flow_03` | — | 0,0024 |
| `air_flow_02` | — | 0,0022 |

Lectura: todas las cifras son menores de 0,007. En varios sensores, la desviación entre repeticiones es del mismo orden que el efecto. El ranking no es estable entre modelos. "—" significa que el sensor no aparece entre los 12 primeros de esa tabla. [Verificado]

**Dependencia parcial** (rango del promedio de la predicción en la rejilla del 5 % al 95 % de cada sensor, y correlación de Spearman entre la rejilla y la predicción):

| Sensor | Solo sensores: rango / Spearman | Completo: rango / Spearman |
|---|---|---|
| `air_flow_01` | 0,244 / -0,52 | 0,025 / +0,52 |
| `starch_flow` | 0,161 / -0,51 | 0,102 / +0,48 |
| `ore_pulp_ph` | 0,157 / -0,84 | 0,073 / -0,89 |
| `ore_pulp_density` | 0,133 / -0,86 | 0,038 / +0,07 |
| `ore_pulp_flow` | 0,133 / -0,96 | — |
| `level_01` | 0,089 / -0,61 | 0,096 / -0,46 |
| `amina_flow` | 0,084 / +0,39 | 0,079 / -0,86 |
| `level_04` | 0,028 / +0,10 | 0,015 / -0,91 |

Lectura: el signo de la dependencia cambia entre los dos modelos para `air_flow_01`, `starch_flow` y `amina_flow`. Con estos datos no se puede afirmar qué variable sube o baja la sílice estimada. [Verificado]

**Conclusión para el sitio**: "Las sensibilidades del modelo" puede publicarse solo como análisis exploratorio, con la advertencia de que las variables no son causas probadas. La frase "las que más la mueven marcadas" no está respaldada todavía. [Inferido]

---

## Literatura

| Trabajo | Qué reporta | Partición o fuga | Estado |
|---|---|---|---|
| Pural (2023), PPMP 59(5), DOI 10.37190/PPMP/169823 | Soft sensor con regresión ridge, MLP y bosque aleatorio sobre "un dataset obtenido de Kaggle". Mejor: bosque aleatorio sobre datos sin reducir, R² 96,5 %, MAE 0,089. Variables: hierro y sílice de alimentación, dosis de reactivos, peso de pulpa, pH, aire y niveles | No dice si la partición fue aleatoria o temporal | [Verificado: página abierta] Probable partición aleatoria; no confirmado |
| Moraes y otros (2018), ABM 22, DOI 10.5151/2237-0234-31915 | Laboratorio con latencia mínima de 2 horas. Bosque aleatorio, gradient boosting y MLP. Mejor en prueba: el MLP | Un trimestre de datos industriales de una planta de mineral de hierro; no es este conjunto | [Verificado: resumen abierto] |
| Basilio y otros, SBC (artículo 42009) | Pronóstico de sílice a un paso; árboles frente a persistencia; sobre el conjunto público, el bosque aleatorio fue el más consistente | No verificable: el PDF no se pudo leer | [Fuente secundaria; no citable] |
| Ahmed y Pourrahimian (2024), Alberta | Predicción de hierro y sílice con gradient boosting frente a LSTM | No verificable: el PDF no se pudo leer. Un fragmento sugiere datos de otra planta | [Fuente secundaria; no citable] |
| Notebooks de Kaggle con este conjunto | Ninguno con partición documentada pudo abrirse | — | [Hueco declarado] |

**Conclusión**: no se encontró un artículo verificado que use este conjunto con partición temporal. El único artículo abierto que lo usa (Pural, 2023) no describe su partición, y su R² no se reproduce con una partición aleatoria (0,698 en esta configuración). Hasta que se lea la partición de Pural, no puede afirmarse que su cifra esté inflada. [Verificado en la búsqueda; Inferido en la lectura]

---

## Contradicciones con el sitio

Texto de `marca-personal/src/i18n/projects/flotation-silica.ts` (es y en), leído sin modificar. Cada fila compara el texto con los datos.

| Texto del sitio | Lo que muestran los datos | Redacción sugerida |
|---|---|---|
| "seis meses de datos reales... de marzo a septiembre de 2017" | Correcto: 2017-03-10 a 2017-09-09, con el hueco de marzo | Mantener |
| "con aire, pulpa y reactivos cada 20 segundos" | Parcialmente correcto: los sensores de proceso sí; el laboratorio de alimentación y del concentrado es horario | "con aire, pulpa y reactivos cada 20 segundos; el laboratorio, una vez por hora" |
| Dato "20 s: la mayoría de las variables" | 19 de 23 variables numéricas son de 20 segundos | Mantener |
| Dato "1 h: la sílice del concentrado" | El objetivo es horario, pero en 310 horas (7,6 %) sus filas siguen una rampa hasta la hora siguiente | Mantener y documentar la rampa |
| Dato "318 h sin datos, en marzo de 2017" | Correcto: 2017-03-16 06:00 a 2017-03-29 11:00 | Mantener |
| Fuente: Kaggle, Eduardo Magalhães Oliveira, CC0 | Correcto según la API de Kaggle. El archivo local es el de OpenML 43311 (MD5 igual al de OpenML) | Citar Kaggle y OpenML |
| "% de hierro del concentrado, fuera del modelo" | Correcto: correlación de -0,80 con la sílice medida en la misma hora | Mantener |
| Algoritmo 1: "entrenados sin el % de hierro del concentrado, que sale del mismo análisis" | Correcto en la práctica (fuga). La afirmación "sale del mismo análisis" no está en el archivo; solo la comparte la hora de medición | "que se mide en la misma hora que el objetivo" |
| Algoritmo 2: "compara cada bloque con repetir el último análisis, una referencia difícil de superar" | Correcto: la persistencia (d = 1) tiene MAE 0,452 y ningún modelo la supera en la primera mirada | Mantener |
| Algoritmo 3: "Muestra cuánto se mueve la estimación cuando cambian el aire o los reactivos" | Las sensibilidades son débiles y su signo no es estable | "Muestra la sensibilidad exploratoria del modelo; no son causas probadas" |
| Producto, automatización: "los huecos se marcan en lugar de rellenarse" | Hay un hueco de 318 horas y horas incompletas (174 y 179 filas). El laboratorio de alimentación se mantiene durante días | Decir que el laboratorio de alimentación puede quedar sin cambio durante días |
| Producto, modelo: "devuelve la sílice estimada de las próximas horas" | No medido. La primera mirada predice la hora en curso, con el laboratorio de la hora anterior. Ningún horizonte futuro se midió | "devuelve la sílice estimada de la hora en curso, antes de que llegue el análisis" (o medir un horizonte) |
| Resumen: "antes de que llegue el laboratorio" | Sin retraso en el archivo. Con el supuesto L = 2 h, la estimación llega antes del resultado | Declarar el supuesto de latencia |
| Tablero: "con las que más la mueven marcadas" | No hay un ranking estable (ver "Sensibilidades") | Marcar como exploratorio |
| Sitio: "Gradient boosting o random forest" | Se midió HistGradientBoosting; no se midió random forest | Decir "gradient boosting" o medir ambos |

---

## Riesgos y huecos

1. **Fuga en filas de rampa**: en 310 horas, las filas de la hora siguen una recta hasta el valor de la hora siguiente. Cualquier modelo a nivel de fila que use el objetivo de la fila tendría fuga. [Verificado]
2. **Variables de alimentación congeladas**: tramos de hasta 792 horas sin cambio. Un rezago de esa variable no es una medición nueva. [Verificado]
3. **Cambio de nivel**: la media del objetivo cambia de 2,56 (entrenamiento) a 2,04 (validación). Un modelo puede aprender el nivel del periodo de entrenamiento y perder precisión. El archivo no dice por qué. [Verificado en la cifra; causa Inferida]
4. **Un solo bloque de validación**: 59 días. La diferencia entre el modelo y la persistencia tiene un IC de ±0,02 a ±0,03. [Verificado]
5. **Latencia del laboratorio**: no está en el archivo. El supuesto de 2 horas viene de otra planta. [Verificado en la cifra; Inferido en el uso]
6. **Sensibilidades débiles**: el signo de la dependencia cambia entre modelos. [Verificado]
7. **Muestra de tiempo**: el archivo tiene solo seis meses. No puede decirse nada del comportamiento en otros meses o años. [Inferido]
8. **Dos horas incompletas**: 174 y 179 filas. Se usan tal cual; el plan decide si se marcan. [Verificado]
9. **Sensores `air_flow_04` y `air_flow_05`**: constantes dentro de la hora en 11,35 % de las horas. Pueden ser un sensor fijo o un valor de respaldo. No se investigó. [Verificado en la frecuencia; causa no investigada]
10. **Literatura**: la partición de las fuentes que usan este conjunto no está verificada. [Hueco declarado]

---

## Preguntas abiertas para el plan

1. **Retraso del laboratorio**: ¿se toma L = 2 horas (d = 1) como supuesto de base, con d = 2 y d = 3 como sensibilidad? ¿O se pide la latencia real a la planta?
2. **Horizonte**: el sitio dice "las próximas horas". ¿Se mide el horizonte 0 (hora en curso) o se miden horizontes de 1 a 3 horas?
3. **Modelo**: ¿HistGradientBoosting (medido) o random forest (no medido)? ¿Se prueba un modelo que predice el cambio respecto al último valor?
4. **Línea base a superar**: la persistencia con d = 1 (propuesta).
5. **Tratamiento del objetivo en rampa**: ¿se usa la primera fila de la hora (propuesto) o la media de la hora? ¿Se excluyen las 310 horas con rampa?
6. **Variables de alimentación**: ¿se usan sus rezagos, dado que pueden quedar congeladas durante días?
7. **Cambio de nivel**: ¿se incluyen variables de calendario o se normaliza el objetivo por periodo?
8. **Partición**: ¿se acepta la partición propuesta (entrenamiento hasta 2017-05-31, validación de junio y julio, prueba de agosto y septiembre), o se usa validación cruzada por bloques?
9. **Sensibilidades**: ¿se publican como exploratorias, o se retiran del sitio hasta tener estabilidad?
10. **Hueco de Pural**: ¿se intenta leer la partición de Pural (PDF completo) antes de citar su cifra?
11. **Kaggle**: ¿se revisan las advertencias de la sección de discusión del conjunto?
12. **Sitio**: ¿se cita también OpenML como fuente del archivo? ¿Se corrige la frase sobre la "próxima horas"?

---

## Scripts y salidas

Los scripts se versionan en `research/` (rutas relativas a la carpeta del proyecto); los datos intermedios se escriben en `data/interim/research/`, que no se versiona. Se ejecutan en orden, desde cualquier directorio, con `python -I research/<script>.py`. El 2026-11-17 se volvieron a ejecutar los diez desde `research/` y reprodujeron las cifras de este documento.

- Scripts: `research/`
  - `common.py` (lectura del ARFF, sin ejecutar nada del archivo)
  - `s01_parse.py` (estructura, valores vacíos, rango de horas)
  - `s02_structure.py` (filas por hora, constancia dentro de la hora, huecos)
  - `s03_lab_within_hour.py` (variación del laboratorio dentro de la hora)
  - `s04_ramp.py` (prueba de la rampa; el último bloque del script falla por no tener horas de alimentación variables, después de imprimir los resultados)
  - `s05_ramp_timing.py` (ubicación de las horas con rampa)
  - `s06_target.py` (perfil del objetivo y autocorrelación sobre el archivo completo)
  - `s07_leak_random_vs_block.py` (partición aleatoria frente a bloques, antes de la prueba)
  - `s08_hourly_models.py` (líneas base, primera mirada, bootstrap por día, antes de la prueba)
  - `s09_sensitivity_and_feeds.py` (permutación, dependencia parcial, rachas de alimentación, conteo de la prueba)
  - `s10_feed_leak_variant.py` (partición aleatoria con variables de alimentación)
- Datos intermedios: `data/interim/research/` (`df.pkl`, `df2.pkl`, `hourly_first.pkl`, `X_full.pkl`, `y_pre.pkl`, `val_preds.pkl`, `models.pkl`, `gaps.csv`).
- Las salidas de consola no se guardaron como archivos; se reproducen ejecutando los scripts en orden con `python -I`.

**Preguntas que no se pudieron responder**

- Advertencias de la discusión de Kaggle: la página no es legible sin JavaScript.
- Partición y resultados de los trabajos de Basilio y de Ahmed y Pourrahimian: los PDF no se pudieron leer.
- Partición de Pural (2023): el texto abierto no la describe.
- Notebooks de Kaggle con partición documentada: no se localizaron.
- Latencia real del laboratorio de esta planta: no está en el archivo ni en una fuente pública.
- Efecto de los sensores `air_flow_04` y `air_flow_05`: no investigado.
- Cifras del horizonte de predicción mayor que cero: no se midieron.
