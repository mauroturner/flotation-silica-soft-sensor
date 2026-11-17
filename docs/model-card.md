# Ficha del modelo

Qué hace el modelo, con qué datos, cómo se validó, qué resultados dio y hasta dónde se puede confiar en él. Las cifras de resultados salen de `reports/evaluation_summary.json` y del sello `reports/model_seal.json`, que escribió la corrida real del 2026-11-17 (D47), la misma fuente del README; las de la partición, las horas por estado, los métodos, el rango y las sensibilidades, de los archivos del sitio (`outputs/site/*.json`) de esa corrida; las de la investigación, de `research.md`. Los criterios y sus umbrales se fijaron antes de escribir el código (`docs/requirements.md`, sección 8.1; D16). Todas las cifras de error están en puntos de sílice del concentrado (% de sílice) y son el error absoluto medio (MAE), salvo donde se diga otra cosa.

## Uso previsto y no previsto

**Para qué sirve.** Estimar, al cierre de cada hora y con lo que se sabe en ese instante, la sílice del concentrado de la hora que cerró (H0) y de las dos siguientes (H1 y H2), con un rango del 80 %, antes de que llegue el análisis del laboratorio; pensado para una sala de control que quiere una estimación con rango entre un análisis y el siguiente. En este archivo, además, sirve como medición: compara el modelo con las reglas que usaría cualquiera (repetir el último análisis, promediar los últimos) y dice que no las supera.

**Para qué no sirve.**

- No estima mejor que repetir el último análisis conocido: en la prueba, el modelo no supera a la persistencia en H0 ni en H1 (ver «Criterios y resultados»).
- No sirve para decidir acciones de control con las sensibilidades: ningún sensor pasó la compuerta de estabilidad, y las que se publican son asociaciones del modelo, nunca causas ni acciones.
- No mide cuánto tarda el laboratorio: la latencia es un supuesto de 2 horas.
- No cubre otra planta ni otros meses que los de este archivo: seis meses de una sola planta.
- No es un servicio publicado: la API es local, de solo lectura y escucha solo en `127.0.0.1`; publicarla queda pendiente del dueño (D27).
- No se reentrena en cada entrega: se entrena una vez, en el lanzamiento, y queda congelado.

## Datos

«Quality Prediction in a Mining Process» (Kaggle, Eduardo Magalhães Oliveira, CC0), en la copia que publica OpenML (dataset 43311): un archivo ARFF de 185.243.565 bytes y SHA-256 `a25122979ba8c5fb9c12e361db61032efc6892a24b5746cc8309da601d9639b2`, con 24 atributos declarados como texto y 737.453 filas, una cada 20 segundos, en 4.097 horas del 2017-03-10 01:00 al 2017-09-09 23:00. OpenML convirtió el archivo: el proyecto fija su tamaño y su SHA-256, y no se comparó byte a byte con el CSV de Kaggle. Los valores, salvo la fecha, se escriben con coma decimal; el lector acepta los enteros con o sin apóstrofos (28.124 de las 560.333 filas anteriores al 2017-07-31 los traen sin ellos). Cada hora tiene 180 filas en 4.095 de las 4.097 (las otras dos, 174 y 179), y hay un hueco de 318 horas, del 2017-03-16 06:00 al 2017-03-29 11:00, que no se rellena.

Las 24 columnas son la fecha, el hierro y la sílice de la alimentación, 19 variables de proceso (los flujos de almidón, amina y pulpa de mineral, el pH y la densidad de la pulpa, siete flujos de aire y siete niveles de columna) y el hierro y la sílice del concentrado. Las unidades de los sensores no están declaradas en la fuente. Las cuatro columnas de laboratorio se miden una vez por hora; la unidad del modelo es la hora y su análisis es el de su primera fila (D04). El proceso queda guardado como media, desviación y último valor de cada sensor por hora.

La validación de la corrida real aceptó las 42 entregas (el lanzamiento, 40 entregas diarias y el cierre) y no rechazó ninguna, con las 29 reglas de `reports/validation/latest.md` y `outputs/site/validation_rules.json`. El hierro del concentrado no entra en ningún modelo: su correlación con la sílice de la misma hora es de −0,80 (research.md) y las guardas lo rechazan por su nombre (D09).

## La frescura y por qué las cifras difieren de research.md

El archivo trae un valor de sílice por hora, pero no siempre es un análisis nuevo. El proyecto clasifica cada hora (D05):

- **nueva**: hay un análisis; es la única que es objetivo o variable del laboratorio;
- **interpolada**: la hora está en una rampa (su sílice cambia dentro de la hora) y la hora anterior también; el valor es una recta entre dos análisis, y contiene el siguiente;
- **repetida**: su valor es igual al de la hora anterior observada y no es interpolada;
- **faltante**: está en el hueco de 318 horas.

| Bloque | Horas con filas | Nuevas | Repetidas | Interpoladas | Faltantes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Entrenamiento | 1.673 | 1.369 | 165 | 139 | 318 |
| Validación V1 | 696 | 630 | 58 | 8 | 0 |
| Validación V2 | 696 | 597 | 87 | 12 | 0 |
| Prueba | 960 | 765 | 130 | 65 | 0 |

El planificador midió, solo con las horas anteriores al 2017-07-31, que el 15,3 % de ellas no trae un análisis nuevo: 66 tramos en rampa y horas repetidas del 9,9 % de los pares de entrenamiento, el 8,3 % de V1 y el 12,5 % de V2 (L61). Por eso las cifras de `research.md` y las de este proyecto no son las mismas: la persistencia de la investigación, que cuenta todas las horas del bloque de validación del 2017-06-02 al 2017-07-30 (1.416 horas), da un MAE de 0,452; sobre las horas nuevas de ese bloque, el planificador la midió en 0,505 (L60, L61). Una hora repetida o interpolada se parece a su vecina, y una persistencia que se mide también sobre ellas se ve mejor de lo que es. En la prueba, de 960 horas, 765 son nuevas, 130 repetidas y 65 interpoladas; el criterio y las tablas de abajo se calculan sobre las 765. La parte nueva de todo el archivo es 0,836.

La primera mirada de la investigación, un `HistGradientBoostingRegressor` con sensores y los análisis rezagados, dio 0,531 en el bloque de validación y no superó a la persistencia (research.md): lo que ese modelo hace con una partición en el tiempo, este proyecto lo mide de nuevo con tres horizontes, una elección en V1 y una prueba aparte.

## Latencia supuesta

El archivo no dice cuánto tarda el laboratorio. El proyecto supone 2 horas (D06), tomadas de otra planta (Moraes et al., 2018, https://doi.org/10.5151/2237-0234-31915): el análisis de la hora `k` llega en `k + 2`, de modo que al cierre de la hora `h` se conoce hasta el análisis de la hora `h − 1`. Es una latencia supuesta: la real es un pendiente del dueño. Con 3 y 4 horas, la evaluación recalcula el modelo y la persistencia (informativo, C10):

| Espera del laboratorio | MAE del modelo en H0 | MAE de la persistencia | Diferencia (intervalo del 95 %) |
| ---: | ---: | ---: | --- |
| 2 horas (la del sello) | 0,597 | 0,519 | de 0,048 a 0,109 |
| 3 horas | 0,696 | 0,675 | de −0,022 a 0,063 |
| 4 horas | 0,744 | 0,780 | de −0,094 a 0,025 |

Con 4 horas el MAE del modelo es menor que el de la persistencia, pero el intervalo de la diferencia incluye el cero. La figura `docs/figures/latency.png` lo dibuja.

## Horizontes

En el instante de emisión `t` (el cierre de la hora `t − 1`), H0 estima la hora `t − 1`, H1 la hora `t` y H2 la hora `t + 1`, con las lecturas hasta la hora `t − 1` y los análisis llegados hasta `t` (D07). Hay un modelo por horizonte, elegido en V1. Cada criterio de comparación nombra su horizonte: C01 y C02 para H0, C03 para H1 y C04 para H2. Una estimación de una hora fuera de los datos (H1 y H2 del último instante) se guarda censurada.

La base más fuerte (B*) de cada horizonte se eligió en V1 entre la persistencia y la media de los últimos 3 análisis frescos: la persistencia en H0 y la media de los últimos análisis en H1 y H2.

## Partición

En el tiempo, por la hora del objetivo, con 24 horas de purga entre bloques (D10); las variables pueden leer horas anteriores de otro bloque, que son pasado.

| Bloque | Horas del objetivo | Horas con filas | Nuevas | Para qué |
| --- | --- | ---: | ---: | --- |
| Entrenamiento | 2017-03-10 01:00 a 2017-05-31 23:00 | 1.673 | 1.369 | Ajustar los modelos y las líneas base |
| Purga | 2017-06-01 | | | Ninguno |
| V1 | 2017-06-02 a 2017-06-30 | 696 | 630 | Elegir el modelo, la base más fuerte y los parámetros de las líneas base |
| Purga | 2017-07-01 | | | Ninguno |
| V2 | 2017-07-02 a 2017-07-30 | 696 | 597 | Calibrar el rango del 80 % |
| Purga | 2017-07-31 | | | Ninguno |
| Prueba | 2017-08-01 a 2017-09-09 | 960 | 765 | Evaluar una sola vez, bajo el sello |

No hay validación cruzada por bloques para elegir: un solo corte en el tiempo por bloque, para que ninguna hora de un bloque vea el futuro de otro (D10). La prueba nunca se usó para modelar, elegir ni calibrar; la evaluación la lee una sola vez, de lo que el flujo ya había emitido.

## Métodos

- **Líneas base** (D13). B0, la media de los análisis frescos del entrenamiento; B1, la persistencia (el último análisis llegado); B2, la media de los últimos `k` análisis frescos, con `k` elegido en V1 entre 3, 6, 12 y 24 (salió 3 en los tres horizontes); B3, una regresión ridge estandarizada (`alpha = 1`) sobre los 57 agregados de los sensores.
- **Variables** (D12). En el instante `t`: la media, la desviación y el último valor de cada uno de los 19 sensores en la hora `t − 1` (57 columnas); los tres últimos análisis frescos llegados, las medias de los últimos 6 y 24, y la edad en horas del último (6); y la alimentación, con sus horas desde el último cambio (4). Cuatro conjuntos: solo sensores (57), solo laboratorio (6), sensores y laboratorio (63) y esos más la alimentación (67). Una hora se estima si tiene todas las entradas de su conjunto y al menos 24 análisis frescos llegados.
- **Candidatos** (D14). `HistGradientBoostingRegressor` (tasa de aprendizaje 0,05, 300 iteraciones, 15 hojas como máximo, regularización L2 de 1,0, sin parada temprana, con 20 o 50 muestras por hoja) y `RandomForestRegressor` (300 árboles, `max_features` de 0,33, con 5 o 20 muestras por hoja), con el objetivo en nivel o en cambio desde el último análisis, sobre los conjuntos de variables: 28 candidatos por horizonte, con `random_state = 0`.
- **Guardas de fuga** (D09). Una lista de columnas prohibidas y un error propio (`LeakageError`) impiden que el hierro del concentrado, las columnas de laboratorio por fila, las marcas de rampa y de frescura de la hora del objetivo o una variable de calendario lleguen a la matriz, y pruebas de truncamiento y de perturbación comprueban que las variables de un instante no cambian con nada posterior. Una trampa detiene el lanzamiento si el MAE en V1 del modelo elegido es menor que 0,5 veces el de la persistencia.
- **La fuga, mostrada a propósito.** En V2, el mismo candidato que eligió el lanzamiento da un MAE de 0,557 y un R² de 0,229 cuando se ajusta en el entrenamiento, es decir, cortado en el tiempo; con una partición al azar (80 % de las horas de entrenamiento, V1 y V2 para ajustar y 20 % para medir) da 0,533 y 0,514, una medida que parece mejor porque las horas vecinas están de los dos lados; y con el hierro del concentrado de la misma hora agregado, 0,445, contra 0,542 del modelo sellado.
- **Intervalos de las diferencias** (D17). Remuestreo de días enteros con reposición (2.000 remuestras, semilla 0): en cada remuestra entran todas las horas de los días sorteados, los mismos días para los dos métodos, y el intervalo del 95 % son los percentiles 2,5 y 97,5 de la diferencia de MAE.

MAE de cada método en V1, V2 y la prueba (los métodos de aprendizaje, solo con sensores, solo con laboratorio y con los dos, de V1 no se muestran: se miden después del reajuste, que usa V1 para ajustar, y no son una medida fuera de muestra).

V1:

| Método | H0 | H1 | H2 |
| --- | ---: | ---: | ---: |
| Media del entrenamiento (B0) | 0,810 | 0,810 | 0,810 |
| Persistencia (B1) | 0,474 | 0,556 | 0,619 |
| Media de los últimos análisis (B2) | 0,488 | 0,553 | 0,606 |
| Ridge sobre sensores (B3) | 0,717 | 0,701 | 0,703 |

V2:

| Método | H0 | H1 | H2 |
| --- | ---: | ---: | ---: |
| Modelo | 0,542 | 0,651 | 0,673 |
| Media del entrenamiento (B0) | 0,914 | 0,914 | 0,914 |
| Persistencia (B1) | 0,533 | 0,669 | 0,724 |
| Media de los últimos análisis (B2) | 0,547 | 0,628 | 0,687 |
| Ridge sobre sensores (B3) | 0,981 | 0,922 | 0,878 |
| Mejor solo con sensores | 0,782 | 0,784 | 0,803 |
| Mejor solo con laboratorio | 0,521 | 0,641 | 0,687 |
| Mejor con sensores y laboratorio | 0,542 | 0,651 | 0,673 |

La prueba (765 horas con análisis nuevo):

| Método | H0 | H1 | H2 |
| --- | ---: | ---: | ---: |
| Modelo | 0,597 | 0,703 | 0,753 |
| Media del entrenamiento (B0) | 0,924 | 0,924 | 0,924 |
| Persistencia (B1) | 0,519 | 0,675 | 0,780 |
| Media de los últimos análisis (B2) | 0,573 | 0,703 | 0,788 |
| Ridge sobre sensores (B3) | 1,183 | 1,171 | 1,049 |
| Mejor solo con sensores | 0,819 | 0,860 | 0,889 |
| Mejor solo con laboratorio | 0,518 | 0,644 | 0,713 |
| Mejor con sensores y laboratorio | 0,597 | 0,703 | 0,753 |

## Selección y reajuste

Para cada horizonte, el candidato de menor MAE en V1 (D14), con el desempate fijado de antemano. Salieron tres bosques aleatorios:

| Horizonte | Familia | Variables | Objetivo | Muestras por hoja | MAE en V1 en la elección |
| --- | --- | --- | --- | ---: | ---: |
| H0, la hora que cerró | bosque aleatorio | sensores y laboratorio (63) | en cambio | 5 | 0,4725 |
| H1, la hora que empieza | bosque aleatorio | sensores, laboratorio y alimentación (67) | en nivel | 20 | 0,5596 |
| H2, la hora siguiente | bosque aleatorio | sensores y laboratorio (63) | en nivel | 20 | 0,6016 |

Las 84 cifras de la elección (28 por horizonte) están en `outputs/site/algorithms.json`. El elegido se reajusta con el entrenamiento y V1 antes de calibrar el rango en V2 (D11), por el cambio de nivel de la sílice: la investigación midió una media de 2,56 en el entrenamiento y de 2,04 en la validación. La variante que reajusta con V2 también se calcula, solo para informar (C10). El artefacto del modelo se guarda en el registro y se carga solo si su tamaño y su SHA-256 coinciden con los registrados (D39); el sello guarda la huella de cada clave de la configuración que cambia un valor sellado (D18), y la evaluación de la prueba con otra configuración se rechaza antes de escribir.

## Rango del 80 %

Conformal partido (D15): el semiancho de cada horizonte es el cuantil de orden `ceil((n + 1) · 0,8) / n` de los residuos absolutos del modelo reajustado sobre las horas de V2, y el rango es la estimación más y menos ese semiancho, recortado a 0-100. Los semianchos son 0,854, 0,970 y 0,973 puntos de sílice para H0, H1 y H2. En la prueba, la cobertura (la proporción de horas con el análisis dentro del rango) es 0,793 en H0, 0,767 en H1 y 0,729 en H2; solo la de H0 es un criterio (C05), con el objetivo de 0,80 entre 0,75 y 0,85. El sesgo del modelo en la prueba (la media de estimación menos análisis) es +0,148 en H0, +0,051 en H1 y +0,013 en H2; solo el de H0 es un criterio (C06).

## Criterios y resultados

Los diez criterios se fijaron antes del primer código, junto con lo esperable: que el modelo no cumpliera C01-C04, C08 ni C09, que C06 quedara en el borde, que C07 se cumpliera y que C05 fuera incierto (D16). El resultado, con el veredicto como lo escribe el flujo (`reports/evaluation_summary.md`):

| Criterio | Cumple | Veredicto |
| --- | --- | --- |
| C01 H0 frente a la persistencia | no | El modelo no supera a la persistencia en la hora que cerró: MAE 0,60 frente a 0,52. |
| C02 H0 fuera del ruido frente a la base más fuerte | no | El modelo no supera a la base más fuerte en la hora que cerró fuera del ruido: MAE 0,60 frente a 0,52; la diferencia va de 0,05 a 0,11. |
| C03 H1 fuera del ruido frente a la base más fuerte | no | El modelo no supera a la base más fuerte en la hora que empieza fuera del ruido: MAE 0,70 frente a 0,70; la diferencia va de −0,05 a 0,05. |
| C04 H2 fuera del ruido frente a la base más fuerte | no | El modelo no supera a la base más fuerte en la hora siguiente fuera del ruido: MAE 0,75 frente a 0,79; la diferencia va de −0,10 a 0,03. |
| C05 Cobertura del rango de H0 | sí | El rango del 80 % cumple en la hora que cerró: cubre 0,793 de las horas, y se pedía entre 0,75 y 0,85. |
| C06 Sesgo de H0 | no | El sesgo en la hora que cerró no cumple: el modelo estima 0,148 de más en promedio, y se pedía a lo sumo 0,10. |
| C07 Los sensores solos frente a la media | sí | Los sensores solos superan a la media del entrenamiento: MAE 0,82 frente a 0,92; la diferencia va de −0,16 a −0,06. |
| C08 Los sensores agregan a la historia del laboratorio | no | Con sensores, el modelo no agrega a la historia del laboratorio: MAE 0,60 frente a 0,52; la diferencia va de 0,06 a 0,10. |
| C09 Sensibilidad estable | no | Ningún sensor pasa la compuerta de estabilidad: sin asociación estable. |
| C10 Por semana y variantes (informativo) | informativo | Informativo, sin umbral: el MAE del modelo, de la persistencia y de la base más fuerte por semana y las variantes de latencia y de reajuste, escritos en el sello (2295 horas evaluadas). |

**C01-C04, C06, C08 y C09 no se cumplen; C05 y C07 se cumplen; C10 es informativo.** Los seis que se esperaban no cumplidos (C01-C04, C08 y C09) no se cumplieron, y C06, que quedaba en el borde, tampoco. El modelo no supera a la persistencia en H0 ni en H1; en H2 su MAE (0,753) es menor que el de la persistencia (0,780) y el de B* (0,788), pero el intervalo de la diferencia con B* va de −0,10 a 0,03 y C04 pide que el límite superior sea negativo. Los criterios se evalúan sobre las 765 horas nuevas de la prueba, en 2.295 pares de hora y horizonte (C10). Lo que el modelo sí cumple es que sus sensores solos estiman mejor que la media del entrenamiento (C07) y que el rango del 80 % cubre lo que dice en H0 (C05).

## Sensibilidades y su compuerta

Cada sensibilidad es una asociación del modelo, no una causa ni una acción, y se publica solo si pasa una compuerta fijada de antemano (D20). Se calculan sobre el mejor candidato con sensores de H0, aunque el elegido no los use, y para cada uno de los 19 sensores: (1) el aumento del MAE al permutar sus tres columnas, en la media de 5 repeticiones, debe ser de al menos 0,01 en V1 y en V2; (2) la dependencia parcial de su media horaria, en una rejilla de 15 puntos del percentil 5 al 95, debe tener una correlación de Spearman del mismo signo y de al menos 0,5 en valor absoluto en el modelo sellado y en 5 reajustes con días del entrenamiento remuestreados (semilla 0). Pasa si cumple las dos en las dos validaciones; en la prueba se informa si conserva el signo (C09).

Ningún sensor pasó. El aumento del MAE al permutar un sensor va de 0,0135 a 0,0251 en V1 y de −0,0003 a 0,0029 en V2: ninguno llega a 0,01 en las dos. El texto de cada sensor es «sin asociación estable», y una prueba comprueba que ningún texto generado llame causa o acción a una sensibilidad. La compuerta se probó con un control positivo y uno negativo sobre datos sintéticos (L63): con una señal de la amina plantada, encuentra exactamente `amina_flow` con signo positivo en V1 y en V2, y con sensores que son ruido no encuentra ninguno.

## Limitaciones

- **Seis meses de una sola planta.** El archivo cubre del 2017-03-10 al 2017-09-09; no hay otra planta ni otra estación, y la prueba son 960 horas, 765 con análisis nuevo.
- **Una latencia supuesta.** El archivo no trae cuánto tarda el laboratorio: las 2 horas vienen de otra planta (Moraes et al., 2018), y con 3 y 4 horas las cifras cambian (ver «Latencia supuesta»).
- **Un archivo convertido por OpenML y no comparado con el CSV de Kaggle.** El proyecto fija su tamaño y su SHA-256; no hay prueba de que sea idéntico, valor por valor, al de Kaggle.
- **Unidades de los sensores no declaradas.** La fuente no dice las unidades de los 19 sensores; ninguna cifra de una sensibilidad se lee en una unidad física.
- **Horas sin análisis nuevo.** El 15,3 % de las horas anteriores a la prueba y el 20,3 % de las de la prueba (195 de 960) son interpoladas o repetidas, y quedan fuera de los objetivos. La regla para las horas repetidas (D05) es un pendiente del dueño.
- **Evaluación única.** La prueba se evalúa una sola vez, bajo el sello (D18); una corrida con otra configuración queda aparte, como posterior al sello, y no reemplaza al resultado sellado.
- **El modelo no supera a la persistencia.** Con estos datos y esta latencia supuesta, repetir el último análisis conocido es el punto de partida honesto; ninguna cifra de este documento dice lo contrario.
- **Sin efecto de las acciones.** Los datos no traen qué se cambió en la planta ni qué pasó después: ninguna sensibilidad mide el efecto de mover un sensor.
- **Un tablero sin ejecutar.** El diseño del tablero está en HTML; las medidas DAX no se ejecutaron nunca y el `.pbix` no está hecho.
- **Sin evaluación independiente todavía.** Un agente que no construyó el proyecto tiene que recalcular estas cifras con su propio lector (plan, sección 28); hasta entonces, son las del flujo.

## Tiempos y memoria

Medidos en la corrida real (U21, D47), en el equipo de desarrollo y en un solo proceso, con el archivo ya en su lugar:

| Qué | Medido | Tope | Contador |
| --- | --- | --- | --- |
| Repetición completa (`replay`, 42 corridas) | 444,0 s (7 min 24 s) | 15 min | reloj; 442 s entre el inicio de la primera corrida y el fin de la última |
| Lectura del ARFF y lanzamiento | 131 s | 6 min | reloj; el ajuste del modelo, 109,9 s |
| Una corrida diaria | de 6 a 8 s | 30 s | reloj |
| El cierre | 25 s | | reloj |
| Pico de memoria | 1.346,3 MB | 2.048 MB | `PeakWorkingSetSize` de `GetProcessMemoryInfo` (conjunto de trabajo del proceso) |
| Memoria comprometida | 3.224,0 MB | sin tope, informativa | `PeakPagefileUsage` del mismo proceso |
| Modo rápido (`make-fixture` y 6 corridas) | 1,2 s y 39,9 s | 1 min | reloj |

El modo rápido, corrido desde otra carpeta, deja el mismo listado de archivos del proyecto fuera de `data/quick/` (nombre, tamaño y fecha) antes y después, con el mismo SHA-256. La prueba de Docker (`-m docker`) pasó una vez: 2 pasaron en 99,95 s. Toda cifra de memoria de este documento nombra su contador (D38).

## La suite rápida

La suite rápida (sin `real_data` ni `docker`) tardó 81,85 s antes de la corrida real, con 965 pruebas pasadas y 1 omitida (D47), contra el límite de 120 s (D33) y el presupuesto de trabajo de 90 s; no se usa `pytest-xdist` (D34). Dos tandas de velocidad la bajaron de 61,4 s a 44,6-46,2 s (`c8d9c3c`) y de 81,4 s a 72,6-73,1 s (`36fe9d2`) sin quitar pruebas (L63, L64); las pruebas de U18 a U21 la subieron otra vez, a 81,85 s. Las pruebas de la documentación (`tests/docs/test_docs.py`) leen Markdown y reportes y no corren nada: cuestan menos de 1 s. La cifra de la suite y la de memoria se vuelven a medir en la última corrección (plan, sección 28).
