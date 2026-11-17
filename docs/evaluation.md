# Evaluación final independiente

Qué se evaluó, quién lo evaluó, qué encontró y cómo se resolvió cada hallazgo. Es el control que el proyecto dejó para el final (plan, sección 28): lo hizo un agente que no escribió el código, sobre una copia aparte del commit `362bcee` (U23), y sus cuatro bloqueantes y sus ocho advertencias se corrigieron o se dejaron dichos después (L67). Otro agente comprobó esas correcciones («Comprobación»). Lo que dice este documento de quién hizo qué, con qué modelo, con qué commit y con qué cifras es lo que consta en el registro del documento de seguimiento (`odd/tasks/portfolio-projects.md`, L66 y L67) y en `git log`; el detalle de cada sonda y de cada cifra recalculada es el del informe del evaluador y el del comprobador, copiado aquí con las rutas del equipo quitadas. Está al día con `79ed5cc`, el último commit de código, y con el registro hasta L67.

## Quién evaluó y cómo

Un agente de Claude Code con el modelo Opus, **distinto de los agentes que construyeron el proyecto** y sin su contexto de trabajo. No escribió nada en el repositorio original. Clonó el repositorio con `git clone --no-hardlinks` en una carpeta de trabajo aparte, fuera del repositorio, se paró en el commit evaluado `362bcee` con `git checkout --detach` y copió desde el original solo el ARFF de `data/raw/` (185.243.565 bytes, SHA-256 `a25122979ba8c5fb9c12e361db61032efc6892a24b5746cc8309da601d9639b2`, el fijado). Armó su propio entorno en el clon con `py -3.11 -m venv .venv` y `pip install -r requirements-dev.txt` (`pip check` limpio). Equipo: Windows 10 Pro 10.0.19045, Python 3.11, Docker Engine 28.5.1.

Recalculó las cifras con código propio, sin importar `flotsilica`: un lector del ARFF con el módulo `csv` (737.453 filas, 5,4 s), su propia tabla de horas (primera fila de laboratorio, rampa, media, desviación y último valor de los 19 sensores), su propia frescura (D04, D05: interpolada si la hora y la anterior contigua están en rampa; repetida si su valor es igual al de la anterior contigua y no es interpolada; fresca lo demás), sus propios rasgos en cada instante con la latencia supuesta de 2 h (los 67 de la sección 10), la persistencia, las medias de los últimos k, B0, el ridge B3, la elección de k y de B*, la grilla completa de 28 candidatos por horizonte con scikit-learn, la elección en V1 con el desempate de D14, el reajuste con entrenamiento y V1, el semiancho conformal en V2, las estimaciones de la prueba, MAE, sesgo, RMSE, cobertura, el MAE por semana, las variantes de latencia y de todas las horas, la demostración de la fuga y el remuestreo por días. Sus guiones (`indep_reader.py`, `indep_figures.py`, `indep_model.py`, `indep_latency.py`, `indep_leak.py`, `indep_site_data.py` y `offgrid_impact.py`) quedaron en la carpeta temporal de su sesión, fuera del repositorio, y no se versionan; las sondas que sí usan el paquete (para comparar contra el flujo) son `probe_perturb.py`, `probe_api.py`, `probe_summary_from_seal.py` y `cmp_outputs.py`.

Corrió en el clon la suite por defecto dos veces en reposo, `pytest -m real_data`, `pytest -m docker` una vez y una repetición real completa (`replay`), y en cinco copias del proyecto en una carpeta temporal las sondas del modo rápido.

## Las cifras recalculadas

Sobre las 765 horas frescas de la prueba con entradas (las mismas 765 en los tres horizontes; el recuento propio coincide). «Coincide» quiere decir igual en todos los decimales que el resumen guarda, salvo donde se dice otra cosa.

| Cifra | Publicada (resumen, sello, sitio, README, D47, ficha) | Recalculada | Resultado |
| --- | --- | --- | --- |
| Filas, horas, horas faltantes, horas incompletas | 737.453; 4.097; 318; 2 (174 y 179 filas) | 737.453; 4.097; 318; 2 (174 y 179) | Coincide |
| Estados por bloque (frescas, repetidas, interpoladas) | entrenamiento 1.369/165/139; V1 630/58/8; V2 597/87/12; prueba 765/130/65 | iguales, y el estado de cada una de las 4.097 horas es el de `lab_hours` | Coincide |
| Parte fresca del archivo; horas sin análisis nuevo | 0,836; 672 (446 repetidas y 226 interpoladas), 16,4 % | 0,8360; 446 y 226 | Coincide |
| Llegada de cada análisis | `available_at = hora + 2 h` | 4.097 de 4.097 | Coincide |
| B0 (media de los frescos del entrenamiento) | prueba 0,924 | 2,44509 como estimación; MAE 0,924100 | Coincide |
| B1 persistencia, prueba H0/H1/H2 | 0,519020; 0,675425; 0,780097 | 0,519020; 0,675425; 0,780097 | Coincide |
| k de B2 y B* por horizonte | k = 3 en los tres; B* = B1, B2, B2 | k = 3; B1 (0,47397 contra 0,48820 en V1), B2, B2 | Coincide |
| B2, prueba | 0,573004; 0,702722; 0,787995 | iguales | Coincide |
| B3 ridge, prueba | 1,183036; 1,170840; 1,049222 | iguales | Coincide |
| Líneas base en V1 y V2 (tablas de la ficha y del resumen) | por ejemplo V2: B1 0,533/0,669/0,724, B3 0,981/0,922/0,878 | iguales en los 24 valores | Coincide |
| Elegidos y MAE en V1 de la elección | `rf-fSL-change-5` 0,47252023; `rf-fSLF-level-20` 0,55958996; `rf-fSL-level-20` 0,60160428 | iguales, al último decimal | Coincide |
| Las 84 cifras de la elección (`fact_selection`, `algorithms.json`) | | 70 iguales al último decimal (los 42 bosques y los `hgb` solo con laboratorio); 14 `hgb` con sensores difieren hasta 0,017 | Coincide en lo que decide; ver nota 1 |
| Semianchos del rango (V2, n = 597) | 0,8540319; 0,9704149; 0,9730858 | iguales al último decimal | Coincide |
| Estimaciones de la prueba (960 por horizonte) | `estimates` del almacén | las 2.880 estimaciones propias, el rango y los tres modelos de comparación son iguales bit a bit | Coincide |
| MAE del modelo, prueba | 0,597193; 0,703442; 0,752904 | iguales | Coincide |
| Sesgo del modelo, prueba | +0,147973; +0,050524; +0,013060 | iguales | Coincide |
| Cobertura del rango, prueba | 0,793464; 0,767320; 0,729412 | iguales | Coincide |
| Mejor solo sensores, solo laboratorio, con sensores (prueba H0) | 0,819276; 0,517759; 0,597193 | iguales | Coincide |
| Modelo y comparaciones en V2 (resumen) | 0,542/0,651/0,673; sensores 0,782/0,784/0,803; laboratorio 0,521/0,641/0,687 | iguales | Coincide |
| Intervalos de C02-C04, C07 y C08 (2.000 remuestras, semilla 0) | C02 0,048126 a 0,109487; C03 −0,052811 a 0,054559; C04 −0,096656 a 0,034925; C07 −0,156763 a −0,057305; C08 0,056466 a 0,104453 | iguales, con 37 días de la prueba con horas frescas | Coincide en el resumen, el sello y el sitio; **difería en D47 y en `SITE-UPDATES.md`** (B3, corregido) |
| MAE por semana, H0 (seis semanas) | 0,59974, 0,52589, 0,63431, 0,55168, 0,73693, 0,52318; persistencia 0,49068, 0,39704, … | iguales, con 88, 159, 113, 162, 151 y 92 horas | Coincide |
| Variantes de latencia (H0, modelo y persistencia) | L = 3: 0,696451 y 0,675425; L = 4: 0,744287 y 0,780097 | iguales | Coincide |
| Variante de todas las horas (H0) | modelo 0,592189 y persistencia 0,455988, 960 horas | iguales | Coincide |
| Demostración de la fuga | bloques 0,557 y R² 0,229; partición al azar 0,533 y 0,514; con el hierro 0,445 | 0,5570 y 0,229; 0,5332 y 0,514; 0,4450 | Coincide |
| `data.json` | tramo interpolado del 2017-04-19 12:00 (16 h, 3,65 a 3,57, −0,0047 por hora); repetidas: 22 tramos de 3 h o más, 220 horas, el mayor de 38; alimentación sin cambio: mediana 7 h, máximo 791 h; objetivo del entrenamiento 2,45, 1,15, 1,07, 2,13, 4,80; las 24 autocorrelaciones | iguales | Coincide |
| `validation_rules.json` | V20 2 horas y 353 filas; V22 226 y 40.680; V23 446 y 80.279; I01 318; I02 1.344 y 241.920 (la última corrida); I03 482 y 86.753; I04 2.886 | iguales (I03 con desviación nula exacta de pandas; con la de numpy son 8: nota 2) | Coincide |
| C10, pares evaluados | 2.295 | 3 × 765 | Coincide |
| Sensibilidades (sello y `algorithms.json`) | V1 de 0,0135 a 0,0251; V2 de −0,0003 a 0,0029; ninguno pasa | no se recalcularon con código propio; se leyeron del sello y coinciden con la ficha | No recalculada (ver A2) |

Notas. (1) Los agregados de los sensores calculados por el lector propio son iguales a los del almacén en el 73,7 % de los valores y difieren en el resto a lo sumo en 1,7·10⁻¹¹ (el orden de la suma); con las desviaciones calculadas con `groupby().std()` de pandas, los bosques son iguales bit a bit, y los `HistGradientBoostingRegressor` con sensores, que agrupan los valores en intervalos, cambian algo. Ninguno de esos 14 queda cerca del elegido: el mejor `hgb` de H0 está a más de 0,015 del elegido. (2) La desviación de numpy de una hora constante no es exactamente 0 y la de pandas sí; la regla I03 dice «exactamente 0», y con la de pandas los recuentos coinciden.

## Especificaciones y criterios de aceptación

Los veredictos son los del evaluador sobre `362bcee`; la última columna dice qué cambió después.

| Especificación | Veredicto | Evidencia | Después |
| --- | --- | --- | --- |
| S1 | Cumple | Existe `05-Mining-Flotation-Silica/` | |
| S2 | Cumple | Investigación (L60), requerimientos y plan (L61), código (L62-L65), diseño del tablero en HTML, pruebas y documentación; esta evaluación es la fase de pruebas final | |
| S3 | Cumple | El README tiene los 13 títulos del plan en orden (`tests/docs/test_docs.py` pasa) | |
| S4 | Cumple | `dashboard/powerbi-design.html`, 129.655 bytes, sin recursos externos | |
| S5 | Cumple | pydantic, uvicorn y httpx tienen su fila con el 05 en `LANDING-EXPANSION.md`; numpy, SQLite, pyarrow, matplotlib, pytest y PostgreSQL también | |
| S6 | No aplica | | |
| S7 | Cumple | | |
| S8 | En parte | Haiku investigó (L60), Opus planificó (L61), Sonnet programó U01-U21 (L62-L65); quién escribió U22 y U23 no constaba en el registro (B4) | Cumple: L66 registra a los escritores con Sonnet de U22 y U23 |
| S9 | Cumple | `SITE-UPDATES.md`, filas 1 a 17 del 05, con dos cifras mal redondeadas (B3) | Las cifras se corrigieron en `616773b` |
| S10 | En parte | La estructura del proyecto 01 está; faltaban `docs/evaluation.md` y la página del sitio (plan, sección 28), como se esperaba | `docs/evaluation.md` está; la página del sitio sigue pendiente |
| S11 | Cumple | L61-L65 registran cada consentimiento como concedido | L66 y L67 también |
| S12 | En parte | T6 sigue en curso, como se esperaba | Sigue en curso: falta la página del sitio |

**Criterios de aceptación.** Cumplen AC02 a AC29 y AC31 a AC38 y AC40; en parte, AC01, AC30 y AC39.

- **Recalculados o sondeados aparte de la suite:** AC03 y AC04 (lector propio; los estados de las 4.097 horas iguales a los del almacén), AC05 (42 entregas, una por corrida), AC06 (recuentos de las reglas, arriba), AC08 (la llegada de cada análisis), AC10 (siete columnas prohibidas rechazadas por `build_matrix`), AC11 (perturbación en el almacén real y rasgos propios que reproducen las estimaciones bit a bit), AC12 (entregas de 24 h y de 240 h en el modo rápido: 2.886 estimaciones y 23.088 de los métodos, idénticas), AC13 (la trampa: 0,236 contra 0,474 detiene, 0,237 pasa, un valor no finito detiene), AC14, AC16, AC17, AC22 y AC23 (las cifras de la tabla), AC18 (79 claves clasificadas, ninguna en las dos listas; la evaluación con otra configuración antes del sello se rechaza con 2 y no escribe), AC19 (el resumen rehecho desde el sello en un almacén sin filas selladas), AC20 (el artefacto de la repetición tiene la huella sellada `f2bf1526…`), AC21 (2.886 estimaciones, una por hora y horizonte), AC27 (129.670 bytes del sitio sin el manifiesto; ninguna ruta local en lo publicado), AC28 (la API con cuerpos armados por el evaluador), AC31 (dos escritores), AC32 (las opciones), AC33 (tres copias desde otra carpeta), AC34 y AC35 (Docker), AC36 y AC37 (la repetición real), AC38 (`pip check`), AC40 (las dos sesiones).
- **En parte, AC01:** un archivo con otra huella sale con 3 y nombra el runbook, pero escribe el estado de la corrida, el informe de la historia y reescribe `reports/validation/latest.json` y `.md` (la advertencia ya registrada; ver «Los puntos ya registrados»). Después: el plan, el runbook y D51 dicen lo que un rechazo de V01 deja, con una prueba (`616773b`).
- **En parte, AC30:** una tarea posterior a `load` de una corrida que nunca entregó salía con 1 y dejaba un estado `failed` (B2). Después: corregido en `0816da8`.
- **En parte, AC39:** la documentación citaba hechos de U22 y U23 que el registro no tenía y dos cifras de intervalos mal redondeadas (B3, B4). Después: corregido (L66, `616773b`).
- **RNF06 (b), en parte:** 84 horas marcadas frescas no son un análisis nuevo (B1). Después: documentado como análisis posterior al sello (D50); la regla no se cambió.

| Requisito | Medido | Límite o nota |
| --- | --- | --- |
| RNF01 | La repetición en el clon da el mismo contenido en los 20 Parquet, los 6 JSON del sitio, los 4 reportes y el HTML que lo versionado, salvo las columnas y las claves de la corrida | |
| RNF02 | `replay` 443,7 s (442 s del inicio de la primera corrida al fin de la última); el lanzamiento 133 s (`fit_model` 111,3 s); las diarias de 6 a 8 s; el cierre 25 s; la corrida sin entrega 2,2 a 2,6 s; la repetición rápida 49 s (en paralelo con otra); la prueba de Docker 104,2 s | Dentro de todos los topes |
| RNF03 | `PeakWorkingSetSize` 1.442,5 MB en la repetición del evaluador (la ficha dice 1.346,3 MB, también `PeakWorkingSetSize`, de la corrida real de U21); `PeakPagefileUsage` 3.212,8 MB en la repetición del evaluador (la ficha dice 3.224,0 MB de la corrida de U21) | Dentro de 2.048 MB para `PeakWorkingSetSize`; el contador está nombrado |
| RNF10 | 20 Parquet, el mayor 2.062.171 bytes; el sitio 129.670 bytes | Dentro |
| RNF15 | Suite rápida 90,86 s y 80,52 s | Dentro de 120 s; la primera pasa el presupuesto de trabajo de 90 s (A3) |

## Los criterios C01 a C10

Las cifras y los veredictos del resumen son los que el evaluador obtuvo con su propio código: C01 no (0,597 frente a 0,519), C02 no (de 0,048 a 0,109), C03 no (de −0,053 a 0,055), C04 no (de −0,097 a 0,035), C05 sí (0,793), C06 no (+0,148), C07 sí (de −0,157 a −0,057), C08 no (de 0,056 a 0,104), C09 no (ningún sensor pasa: todos tienen importancia menor que 0,01 en V2), C10 informativo (2.295 pares). Cada texto de veredicto dice lo que dice su número. Con el hallazgo B1 corregido de la forma más simple (quitar las 16 horas afectadas de la prueba), la persistencia de H0 pasa de 0,519 a 0,530 y el modelo se queda en 0,597: ningún veredicto cambia (lo confirmó la comprobación para los diez, con los intervalos; ver «Comprobación»).

## Lo que el evaluador sondeó

| Clase de defecto (plan, sección 24.2, y sección 28.1) | Sonda | Resultado |
| --- | --- | --- |
| Información posterior al instante | Rasgos propios, construidos solo con lecturas de horas `< t` y análisis con llegada `≤ t`, reentrenados con scikit-learn: las 2.880 estimaciones de la prueba iguales bit a bit a las del almacén. En una copia del almacén real, en cinco instantes, se multiplicaron por 1,7 y se corrieron en 3 los 57 agregados de toda hora `≥ t` y se cambiaron la sílice y la alimentación de todo análisis con llegada `> t`: los 67 rasgos y las estimaciones, el rango y B* emitidos en `t` no cambiaron (diferencia máxima 0) | Sin defecto |
| Un análisis usado antes de su llegada | Se adelantó la llegada del análisis de `t − 1` a `t`: `inputs_at` lo toma solo si es fresco (en los dos instantes en que no lo era, la historia no cambió); sin adelantarlo, nunca está | Sin defecto: la llegada es lo que filtra |
| Una hora interpolada o repetida como objetivo o rasgo | Frescura propia igual a la del almacén en las 4.097 horas. Además: 84 horas que la regla marca frescas tienen un primer valor que es el análisis anterior más 1/181 del salto hasta el siguiente (16 en la prueba) | **B1** |
| El tamaño de la entrega | Modo rápido con entregas de 240 h y de 24 h | Sin defecto (idénticas) |
| La trampa M01 | `check_tripwire` en el borde y con NaN; el elegido de H0 da 0,4725 contra 0,4740 de la persistencia (razón 0,997) | Sin defecto |
| El rango calibrado fuera de V2 | Semianchos propios con los residuos del reajuste en las 597 horas de V2: iguales al último decimal | Sin defecto |
| Variantes fuera de la elección | `model.py`, `baselines.py`, `intervals.py` y `sensitivity.py` no nombran `variants` ni `eval_variants`; las variantes recalculadas coinciden | Sin defecto |
| La compuerta y los textos de sensibilidades | Ningún texto generado (los seis JSON del sitio, el resumen, el HTML, el README, la ficha) llama causa o acción a una sensibilidad: las seis apariciones de «causa» o «acción» son negaciones. La importancia en V1 se mide sobre el modelo reajustado con V1 | **A2** |
| La API contra el flujo y con entradas del futuro | `POST /estimate` con cuerpos armados por el lector propio (las 180 lecturas de la hora, la historia fresca propia y la alimentación) en 8 instantes: 24 estimaciones iguales a las guardadas (diferencia 0). Un análisis cuya muestra más 2 h pasa el instante: 422 `analysis_after_issue`; 181 lecturas: 422; instante fuera de la hora en punto: 422; un número como texto: 422; historia corta: 422 `short_lab_history`; sin alimentación, H1 (que la usa) queda `missing_inputs`; el árbol del proyecto no cambió | Sin defecto |
| Cada opción de la CLI | `serve --host 0.0.0.0`, `--port 0` y `70000` salen con 2 antes de cargar; `replay --until X` con una entrega que no existe sale con 2; `run --only … --from …`, `--run-key` sin selección y `--from`/`--only` sin `--run-key` salen con 2 sin escribir; `make-fixture` fuera de la carpeta del proyecto y `--weeks 0` salen con 2; `replay --until` sin nada pendiente sale con 0 | A4 |
| Cada clave de la configuración contra la huella | Las 79 hojas de `pipeline.toml` están en `FINGERPRINT_KEYS` (58) o en `UNSEALED_KEYS` (21), ninguna en las dos; la huella es la de toda la vista sellada | Sin defecto |
| El resumen después del sello | Copia del almacén sin las filas selladas de las `eval_*`: el resumen sale `sealed` desde el sello, con los diez criterios iguales al versionado | Sin defecto |
| La evaluación con otra configuración antes del sello de la prueba | Modo rápido hasta la última diaria y `run` y `task evaluate` con `bootstrap_resamples` cambiado: salida 2, nombra la clave, no escribe | Sin defecto |
| Tareas de una corrida que no cargó su entrega | `task score`, `load`, `track`, `evaluate` y `report` sin `--run-key` (una corrida nueva) | **B2** |
| La carga sin validación | La suite la cubre para una corrida que entregó; para una que no entregó, B2 | B2 |
| El bloqueo | Una repetición rápida y, mientras corre, `run` y `task deliver`: los dos salen con 2 y no escriben; la primera termina con 0 | Sin defecto |
| El modo rápido en varias copias | Tres copias del proyecto, la repetición rápida desde otra carpeta, dos de ellas a la vez: fuera de `data/quick/` solo cambian los `__pycache__` (ignorados); las tres dan las mismas estimaciones | Sin defecto |
| Las corridas cerradas | `task fetch_source`, `load`, `score` y `report` de una corrida `ok`: salida 2, el árbol igual | Sin defecto |
| El manejador de fallas | La prueba con nombre pasa; no se sondeó aparte | Sin defecto observado |
| El compose sin sus claves | `docker compose config` sin las cuatro claves: falla nombrando la que falta; interfaz en `127.0.0.1`; montajes de solo lectura; imagen de PostgreSQL con resumen | Sin defecto |
| Las reglas acumuladas del sitio | I02 (`latest`) da 1.344 horas, igual al recuento propio del archivo entero, sin sumar corridas; V20-V23 e I03 (`per_run`) suman lo mismo que el archivo | Sin defecto |
| Rutas locales en lo publicado | `outputs/`, `reports/`, `dashboard/` y `docs/figures/` del commit, y los archivos versionados del proyecto, sin rutas del equipo ni nombre de usuario | Sin defecto |
| Cifras de memoria y su contador | Cada cifra de memoria de la ficha, el README y D47 nombra su contador; el flujo registra `PeakWorkingSetSize` | Sin defecto |
| El tiempo de la suite en reposo, dos veces | 90,86 s y 80,52 s | A3 |
| La documentación contra el registro y el último commit | El registro terminaba en L65 («Next: U22 (README and model card), U23»); la ficha, el README, el paso a paso y `SITE-UPDATES.md` contaban U22 y U23 y sus tiempos de suite | **B4**; además B3 |

## Las corridas

- **Suite por defecto**, dos veces seguidas en reposo en el clon: 983 pasaron y 1 se omitió (la del identificador de arranque de Linux), 4 deseleccionadas, en **90,86 s** y **80,52 s**. La ficha y el README decían 984 pruebas (983 y 1), que coincide, y 83,30 s y 84,04 s.
- **`pytest -m real_data`**: 1 pasó y 1 falló. Falló `tests/e2e/test_real.py::test_real_counts_seal_and_summary_consistency` en la línea 102, porque la repetición en el clon tiene sus propias claves de corrida y el sello guarda las de U21 (A1). Con solo esa comparación quitada, en una copia de la prueba que se borró después, la prueba pasa entera (recuentos, estados, sello, criterios, tiempos y memoria).
- **`pytest -m docker`**: 2 pasaron en 104,19 s. Antes no había ningún proyecto `flotsilica-airflow`; después, los listados de contenedores, imágenes, volúmenes y redes de Docker son iguales a los de antes.
- **Repetición real completa** en el clon, con el sello versionado en su lugar y el almacén vacío: salida 0, 42 corridas `ok`, el lanzamiento `seal=unchanged`, el cierre `test=unchanged`, el artefacto con la huella sellada y `reports/model_seal.json` igual byte a byte. Comparada con lo versionado: el HTML, los seis JSON del sitio y los cuatro reportes difieren solo en la clave de la corrida; los 20 Parquet tienen las mismas columnas y filas, y difieren solo en el metadato `flotsilica.run_key`, en la columna `run_key` de `fact_estimate` y `fact_validation`, y en `dim_pipeline_run` (claves, inicios, fines y picos de memoria de cada corrida); los dos manifiestos difieren en las huellas y los tamaños de esos archivos. No hay otra diferencia.

## Los bloqueantes

Las ubicaciones con número de línea son las de `362bcee`, el commit evaluado. Cada hallazgo termina con su **Estado**.

### B1. 84 horas marcadas frescas no son un análisis nuevo: su valor es el análisis anterior más 1/181 del salto hasta el siguiente

- **Qué pasa.** D05 dice que «la primera hora de un tramo en rampa es fresca (su primer valor es el análisis del principio)». En 84 de las horas en rampa que la regla marca `fresh` (51 del entrenamiento, 6 de V1, 9 de V2, 18 desde el 2017-07-31, 16 de ellas en la cohorte de la prueba), el primer valor no tiene dos decimales y está exactamente a 1/181 del camino entre el análisis de la hora anterior y el de la siguiente: (valor − anterior) / (siguiente − anterior) = 0,005525 en las 84, con desviación 1,2·10⁻⁹. Es decir, la interpolación ya empezó y la hora no trae un análisis propio; su valor es, a efectos prácticos, el anterior repetido, con el signo y el tamaño del análisis siguiente adentro. Entran como objetivo y como historia del laboratorio (RNF06 b). En la prueba, la persistencia de H0 se equivoca 0,0036 en promedio en esas 16 horas, que es lo que D05 quería quitar; sin ellas, la persistencia de H0 da 0,530 en lugar de 0,519, y el modelo 0,597. Ningún veredicto cambia, pero las cifras publicadas de la persistencia y de las horas frescas las incluyen.
- **Reproducción.** Con los guiones del evaluador (`indep_reader.py <arff>` y después `offgrid_impact.py <almacén>`): «offgrid by block {'train': 51, 'test': 18, 'v2': 9, 'v1': 6}» y «0 without_offgrid 749 model 0.5966 b1 0.53»; la razón 0,005525 de las 84 sale del bloque de la tabla de arriba (ejemplo: 2017-04-19 11:00, anterior 3,65, valor 3,649974, siguiente 3,645270).
- **Dónde.** `src/flotsilica/hours.py:58-60` (`lab_states`) implementa la regla del plan tal como está escrita; la premisa está en `docs/decisions.md` D05 y en el plan, sección 8.
- **Dirección del evaluador.** Es una regla sellada: cambiarla es un análisis posterior al sello (D18) o una decisión del dueño (plan, sección 29, ítem 3). Una regla que se puede decidir en el momento con la hora y la anterior: una hora en rampa cuyo primer valor difiere del de la hora anterior contigua en exactamente un paso de su propia rampa es interpolada. Como mínimo, la ficha y el README tienen que decir el hallazgo y su efecto sobre la persistencia.
- **Estado: documentado como análisis posterior al sello; la regla no se cambió.** El orquestador lo decidió en L66: la prueba se leyó una vez y se selló (D18), y cambiar la regla de frescura ahora sería una segunda evaluación sobre datos ya vistos. `616773b` lo dice con su efecto medido en D50, el README y la ficha, y pone el cambio de la regla en los pendientes del dueño (plan, sección 29, ítems 14 y 15). La comprobación lo recalculó (ver «Comprobación»). Sigue abierto como decisión del dueño, no como defecto de lo sellado.

### B2. Una tarea posterior a `load` de una corrida que nunca entregó sale con 1 y deja un estado `failed`

- **Qué pasa.** AC30 pide que toda tarea posterior a `load` se rechace (salida 2) antes de escribir si la corrida no cargó su propia entrega, y que `load` se rechace sin una validación aprobada. Las guardas `_refuse_a_delivery_this_run_did_not_load` y `_refuse_a_load_its_validation_did_not_pass` vuelven sin rechazar cuando la corrida todavía no tiene `deliver`; después `_open` crea el archivo de estado, la tarea levanta `RunStateError` y `_record_failure` lo marca `failed`. `task <tarea>` sin `--run-key` (documentado: «una nueva si se omite») es exactamente esa corrida.
- **Reproducción.** En una copia con la repetición rápida terminada: `python -m flotsilica task score --config config/pipeline.quick.toml` sale con 1 («falló: RunStateError: la corrida … no tiene el resultado de la tarea deliver»), y lo mismo `load`, `track`, `evaluate` y `report`; cada una deja `data/quick/interim/runs/<clave>.json` con `"status": "failed"` y la traza (el SHA-256 del árbol cambia).
- **Dónde.** `src/flotsilica/pipeline.py:645-650` y `665-667` (las guardas vuelven en las líneas 649 y 666 si la corrida no entregó), `766-775` (`_open` antes de la tarea, y `RunStateError` tratado como falla), `164-169` (`_task_result`).
- **Dirección del evaluador.** Que una tarea posterior a `deliver` de una corrida sin entrega sea un `RunRefusedError` con salida 2 antes de `_open`, y una prueba con nombre para ese caso.
- **Estado: corregido en `0816da8`** (D52; ítem 4 de riesgo alto, solo en su commit). Una tarea desde `load` de una corrida que no tiene entrega sale con 2 antes de escribir el estado; `task deliver` y `task validate` sin `--run-key` siguen saliendo con 1, como antes (D52). La comprobación lo cerró (ver «Comprobación»).

### B3. Dos documentos publican tres límites de intervalo mal redondeados

- **Qué pasa.** El resumen, el sello y el sitio dicen C02 de 0,048126 a 0,109487 y C08 de 0,056466 a 0,104453 (recalculados igual). `docs/decisions.md` D47 decía «C02 no (diferencia de 0,048 a 0,110)» y «C08 no (de 0,057 a 0,105)», y `SITE-UPDATES.md` decía «C08 … la diferencia va de 0,057 a 0,105»; a tres decimales son 0,109, 0,056 y 0,104 (la ficha y la misma fila C02 de `SITE-UPDATES.md` decían 0,109).
- **Reproducción.** `python -c "print(round(0.10948726054438435,3), round(0.05646648373377021,3), round(0.10445316555905898,3))"` da `0.109 0.056 0.104`; `grep -n '0,110\|0,057 a 0,105' docs/decisions.md ../SITE-UPDATES.md`.
- **Dónde.** `docs/decisions.md:476`; `SITE-UPDATES.md:289`.
- **Dirección del evaluador.** Escribir esas cifras desde el resumen (como la ficha), no a mano.
- **Estado: corregido en `616773b`**, con una prueba que compara cada límite citado en D47, el README, la ficha y las filas del 05 con el resumen, redondeado a los decimales que escribe cada documento (`test_every_interval_bound_the_documents_quote_is_the_summary_s`). La comprobación comparó 18 citas con un guion propio y la de C04 de la fila 7 a mano: ninguna mal.

### B4. La documentación cuenta U22 y U23, y sus tiempos de suite, que el registro no tenía

- **Qué pasa.** El registro terminaba en L65, que dice «Next: U22 (README and model card), U23, then the independent evaluation». La ficha (`docs/model-card.md:198`), el README (`README.md:269`), `SITE-UPDATES.md` (línea 297) y el paso a paso (`docs/paso-a-paso.md:64-72`) decían que la suite «tardó 83,30 s y 84,04 s, medida dos veces seguidas en reposo en el commit de U23 con 984 pruebas» y contaban lo que hicieron U22 y U23; ni el registro ni `git log` tenían esas cifras, ni quién escribió esas unidades, ni si se revisaron. Es la clase B1 del proyecto 04 (RNF14; plan, sección 28.4: el registro se escribe antes que los documentos que lo citan). La suite medida por el evaluador dio 90,86 s y 80,52 s.
- **Reproducción.** `git log --all --format=%B | grep -c '83.30\|83,30'` en el clon da 0; `grep -n 'L66' odd/tasks/portfolio-projects.md` no encuentra nada (en `362bcee`).
- **Dónde.** `odd/tasks/portfolio-projects.md:101` (L65, la última entrada) frente a las cuatro ubicaciones de arriba.
- **Dirección del evaluador.** Escribir en el registro la entrada de U22 y U23 (commits, modelo de quien escribió, revisiones, suite medida) y después sincronizar los documentos con el último commit de corrección, como pide la sección 28.4.
- **Estado: corregido.** L66 registra U22 y U23 (escritores con Sonnet, commits, revisiones, 83,30 s y 84,04 s con 984 pruebas) y la evaluación; `616773b` hizo que los documentos digan lo que L66 dice. L67 registra las correcciones, la comprobación y la tanda de velocidad, y esta sincronización dice lo que L66 y L67 dicen (la comprobación encontró dos restos: N1 y N2).

## Las advertencias

Cada una, con su estado: **corregida** (con el commit), **documentada** (dicha en los documentos como lo decidió el registro) o **abierta**.

### A1. `pytest -m real_data` falla después de una reconstrucción legítima con el sello

`tests/e2e/test_real.py:102` exige que las claves de corrida del almacén sean las del sello. Una reconstrucción desde cero con el sello en su lugar (runbook R11; el README dice que repetir la corrida «reescribe las salidas versionadas con sus propias claves de corrida») produce otras claves, y la prueba falla aunque todo lo demás coincide. Reproducción: la repetición en el clon y `pytest -m real_data` («AssertionError: assert ('20261117T190523978635Z' == '20261117T175515120901Z'»); sin esa línea, pasa. Dirección: comparar las claves de corrida entre el almacén, el resumen y el sitio, y con el sello solo si el almacén es el que lo escribió.

**Estado: corregida en `8d0d36c`.** La prueba compara las claves del almacén, el resumen y el sitio, y las del sello solo si el almacén es el que lo escribió; además exige que los criterios del resumen sean la evaluación sellada del propio almacén. Se vio fallar contra lo que dejó la repetición del evaluador y pasar después (D52). La comprobación corrió `-m real_data` en la copia de la repetición: 2 pasaron.

### A2. La importancia de la compuerta en V1 se mide sobre el modelo reajustado con V1

`src/flotsilica/sensitivity.py:110-116`: el modelo de la compuerta es `best_with_sensors`, reajustado con entrenamiento y V1, y la permutación se mide en V1 y V2; en V1 es una medida dentro de la muestra. Por eso los 19 sensores pasan 0,01 en V1 (de 0,0135 a 0,0251) cuando el planificador midió a lo sumo 0,0012 con un modelo ajustado solo en el entrenamiento (D20), y la condición de V1 deja de filtrar: con un V2 favorable, todo pasaría V1. El plan dice «reajustado» y el resultado (ninguno pasa) no cambia. Es la misma clase que `N1-v1-mae-after-refit`, y `algorithms.json` publica esas importancias de V1 sin decirlo. Dirección: medir la importancia de V1 con el candidato ajustado en el entrenamiento, o rotularla, y decirlo en la ficha.

**Estado: documentada como análisis posterior al sello; abierta como decisión del dueño.** El orquestador la trató como B1 (L66): `616773b` la dice en D50, la ficha y el README, y el cambio de la compuerta (medir la condición de V1 con el candidato ajustado solo en el entrenamiento) queda en los pendientes del dueño (plan, sección 29, ítem 15). No cambia ningún resultado, porque la condición de V2 rechaza a los 19 sensores.

### A3. La primera sesión de la suite pasó el presupuesto de trabajo de 90 s

90,86 s y 80,52 s, dentro del límite de 120 s (AC40 se cumple), con la primera sobre el presupuesto de 90 s de la sección 24.1, que pide una unidad de velocidad. La diferencia entre las dos es de 10 s en reposo; la cifra que diga la documentación tiene que ser la del último commit de corrección.

**Estado: respondida por `79ed5cc`**, la tanda de velocidad (Sonnet; D33): la suite pasó de 86,5 s a 76,3-77,4 s en reposo con las mismas 990 pruebas. La cifra que dicen los documentos es la medida en el último commit (ver «La medición de esta sincronización»).

### A4. `replay --until` sin nada pendiente sale con 0

`src/flotsilica/pipeline.py:842-843`: con todo cargado, `replay --until L2017-07-31` sale con 0 («No hay entregas pendientes») antes de comprobar `--until`; con algo pendiente y un `--until` anterior, la misma opción sale con 2. El mensaje es honesto y nada se escribe; solo la salida es inconsistente. Dirección: aplicar la misma comprobación en los dos casos.

**Estado: corregida en `8d0d36c`** (D52): un `--until` sale con 2 sin escribir, haya o no entregas pendientes; `replay` sin `--until` y sin pendientes sigue saliendo con 0.

### A5. La regla de las repeticiones está escrita de dos maneras

El plan, sección 8, y el código (`hours.py:59`) comparan los valores exactos; el plan, sección 29, ítem 3, y los requerimientos, sección 4, hablan de «una hora igual a la anterior a dos decimales». Con dos decimales cambiarían 65 horas del archivo (la prueba tendría 142 repetidas en lugar de 130). Los recuentos del planificador son los de la comparación exacta, así que el código hace lo medido; falta decir en D05 cuál de las dos es la regla.

**Estado: corregida en `616773b`** (documentación): los documentos dicen la regla como la aplica el código, la igualdad exacta.

### A6. La repetición completa de RNF02 no incluye la corrida sin entrega

RNF02 cuenta «lanzamiento, 40 diarias, cierre y la corrida sin entrega» y `replay` se detiene sin la última (`pipeline.py:833-851`); D47 y la ficha dan 42 corridas. Aquí la corrida sin entrega (`run`) tardó de 2,2 a 2,6 s, así que el tope no está en juego; falta decirlo o medirla.

**Estado: corregida en `616773b`** (documentación): el README, la ficha y `SITE-UPDATES.md` dicen que `replay` no corre la corrida sin entrega y que la evaluación la midió aparte en 2,2 a 2,6 s.

### A7. El README atribuye a C03 una comparación con la persistencia

`README.md:72`: «No supera a la persistencia en H0 ni en H1 (C01 y C03)». C03 compara con B* (la media de los últimos 3), no con la persistencia; que el modelo no supere a la persistencia en H1 (0,703 frente a 0,675) es cierto pero no es C03. Dirección: «(C01; en H1, 0,703 frente a 0,675)».

**Estado: corregida en `616773b`** (documentación).

### A8. L65 llama «config sha256» a la huella del archivo

L65 dice «config sha256 `7fe6fefc…`», que es el SHA-256 de `config/pipeline.toml`; el `config_sha256` del sello es `3897c741…` (D47 distingue los dos). Dirección: decir «SHA-256 de `config/pipeline.toml`» en la próxima entrada del registro.

**Estado: corregida en L67**, que dice que el valor que L65 llama «config sha256 `7fe6fefc…`» es el SHA-256 del archivo `config/pipeline.toml` y que el `config_sha256` del sello es `3897c741…`. La comprobación la dejó como N4 mientras L67 no existía.

## Los puntos ya registrados

- **`N1-v1-mae-after-refit`**: confirmado. `algorithms.json`, `horizons[0].methods[model].mae_v1` = 0,268, igual a lo que da el reajuste propio en V1 (0,26830), sin rótulo. A2 es el mismo problema en la compuerta. **Estado:** `616773b` rotuló la cifra en la documentación como medida después del reajuste con entrenamiento y V1; el JSON generado no cambió (sellado).
- **El rechazo de V01 escribe**: confirmado y algo más amplio. Con un byte agregado al archivo del modo rápido, `run` sale con 3 y escribe el estado de la corrida, `reports/validation/history/<clave>.json` y `.md`, y **reescribe `reports/validation/latest.json` y `.md`**, que en la configuración real son archivos versionados; el plan, sección 6, decía «nada cambia» (el README sí lo decía). **Estado: corregida en `616773b`** (D51): el plan y el runbook dicen lo que un rechazo deja, con una prueba que fija que el almacén, el modelo, el sello y `outputs/` no cambian.
- **La prueba de AC33 corre una configuración chica superpuesta (D44)**: la sonda de este evaluador corrió la `pipeline.quick.toml` del commit desde otra carpeta en tres copias, dos a la vez, y fuera de `data/quick/` no cambió nada salvo los `__pycache__`: la evidencia de AC33 se sostiene.
- **`R2-section-helper-sentinel-hack` (`tests/docs/test_docs.py:58`), `R2-docs-sync-readme-double-read` (`cli.py:191-197`) y `R3-dtype-lookup-uncaught-keyerror` (`docs.py:39`)**: seguían como estaban; `docs.py:39` busca `DTYPE_ES[c.dtype]` sin protección, y `cli.py:198-199` escribe el README antes de esa búsqueda, así que un tipo que falte en `DTYPE_ES` sale con 1 con el README ya escrito, fuera del camino de salida 2. No se provocó. **Estado: corregidas las tres en `8d0d36c`** (D52): un tipo que `DTYPE_ES` no nombra es un `ValueError` que nombra la columna (salida 2, sin escribir), `docs-sync` lee cada archivo una vez y comprueba todo antes de escribir, y `section` recibe un final explícito.

## Las correcciones

Las decidió el registro (L66) y las escribió un agente con Opus, cada una con la prueba primero salvo lo que la propia entrada dice (L67): la prueba nueva se vio fallar antes de su corrección, salvo la de V01, que describe un comportamiento existente. Corrió además un diferencial de la línea de comandos contra `ffb8297` en el que solo B2 y A4 difieren.

- `0816da8` **B2** (ítem 4, sola; D52).
- `8d0d36c` **A4, A1 y las tres sugerencias de las revisiones de U22 y U23** (ítem 3; D52).
- `616773b` **La documentación**: B3, B4, B1 y A2 como análisis posteriores al sello (D50), el MAE de V1 de `algorithms.json` rotulado, V01 (D51), A5-A7 y los desvíos (D52).
- `79ed5cc` **La tanda de velocidad**, aparte del conjunto de la evaluación (la escribió un agente con Sonnet): la suite rápida pasó de 86,5 s a 76,3-77,4 s en reposo con las mismas 990 pruebas, con salidas idénticas (D33).
- **A8** en la entrada L67 del registro.

Las revisiones nativas de L67 (consentimiento aceptado, S11), cada una en un árbol de trabajo aparte: `0816da8`, escalada al ítem 4, aprobada con una sugerencia; `8d0d36c`, escalada al ítem 3, aprobada con una sugerencia; `616773b`, aprobada sin hallazgos; `79ed5cc`, escalada al ítem 6, aprobada con una sugerencia. Sus tres sugerencias están abiertas en [review-advisories.md](review-advisories.md).

**Ninguna corrección cambió una salida versionada.** La comprobación halló iguales, entre `362bcee` y `616773b`, los árboles de git de `reports/`, `outputs/`, `dashboard/`, `docs/figures/` y `config/` (`reports` `e8a5d4d…`, `outputs` `d06baa7…`), y una repetición real completa en `616773b` dejó `reports/model_seal.json` igual byte a byte. `79ed5cc` no toca ninguna salida: el orquestador comprobó que los nueve bosques del `v1.pkl` sellado predicen los mismos bytes por el camino nuevo que por scikit-learn, fila por fila y en un bloque, y esta sincronización volvió a comprobar con `git rev-parse` que los árboles de `reports`, `outputs`, `dashboard` y `docs/figures` de `362bcee` y del commit actual tienen el mismo hash, y `git diff --stat` entre los dos no muestra nada en esas carpetas ni en `config/`.

## Lo que se dejó, y por qué

- **B1 y A2** quedan como decisiones del dueño (D50, plan, sección 29, ítems 14 y 15): la prueba se leyó una vez y se selló (D18); cambiar la regla de frescura o la compuerta ahora sería una segunda evaluación sobre datos ya vistos. Las cifras selladas quedan y la documentación dice cada hallazgo con su efecto medido.
- **Las tres sugerencias de L67** (`R3-001-0816da8`, `R3-001-8d0d36c` y `R4-store-validation-commit-on-error`) quedan abiertas en `docs/review-advisories.md`; ninguna es un defecto de un resultado.
- **Las advertencias ya abiertas de las revisiones** (README, «La documentación») siguen como estaban.

## Comprobación

Otro agente de Claude Code con Opus, que no construyó ni corrigió el proyecto, rehízo los bloqueantes de la evaluación (plan, sección 28, ítem 3) en copias del commit evaluado `362bcee` y del corregido `616773b`, y comprobó con un diferencial de la línea de comandos y de la API que las correcciones no rompen nada. Trabajó en el clon de la evaluación (con su propio entorno de Python 3.11 y el ARFF fijado, SHA-256 `a2512297…`), al que le trajo `616773b` con `git fetch` desde el repositorio original; armó dos copias de trabajo sueltas de ese clon, una por commit, con `PYTHONPATH=src` y el ARFF copiado, y las borró al terminar. Corrió la suite rápida dos veces y `-m real_data` en `616773b`, una repetición real completa en la copia de `616773b`, el diferencial en el modo rápido (102 pasos en estados nuevos armados igual para los dos commits) y el de la API en el mismo proceso. No escribió nada en el repositorio original. Sus guiones y resultados están en una carpeta temporal de su sesión, fuera del repositorio. La comprobación llegó hasta `616773b`: `79ed5cc` es posterior (ver «Las correcciones» para lo que se comprobó de él).

**Veredicto: B1, B2 y B3 están cerrados; B4 está cerrado en lo que la evaluación nombró, pero `SITE-UPDATES.md` seguía diciendo en tres lugares que la evaluación independiente no se hizo y marcaba cinco filas «Pendiente de la evaluación», contra L66 (bloqueante nuevo, N1). El diferencial no muestra ninguna diferencia que nadie haya pedido.**

| Bloqueante | `362bcee` | `616773b` | Veredicto |
| --- | --- | --- | --- |
| B1 | Las 84 horas en rampa que la regla marca frescas (51 del entrenamiento, 6 de V1, 9 de V2, 18 desde el 2017-07-31, 16 en la cohorte de la prueba) se reproducen con el lector propio del evaluador: su primer valor está a 0,0055248617 del camino entre el análisis anterior y el siguiente (1/181 = 0,0055248619; desviación 1,2·10⁻⁹) | Lo sellado no cambió: los árboles de `reports/`, `outputs/`, `dashboard/`, `docs/figures/` y `config/` tienen el mismo hash de git en los dos commits (`reports` `e8a5d4d…`, `outputs` `d06baa7…`), y la repetición real en la copia de `616773b` dejó `reports/model_seal.json` igual byte a byte (SHA-256 `ed62cb53…` antes y después, `seal=unchanged` y `test=unchanged`). Las cifras de D50, del README y de la ficha se recalcularon con los guiones del evaluador (`indep_reader.py`, `indep_figures.py`, `offgrid_impact.py`) y uno propio que usa su remuestreo (`b1_verdicts.py`), contra el almacén de la evaluación y contra el de esta repetición (iguales): sin las 16 horas (749 de 765), H0 persistencia 0,530 (0,530030) y modelo 0,597 (0,596577); H1 modelo 0,682, persistencia 0,664 (0,663505) y B* 0,688; H2 modelo 0,727 y B* 0,771. Todas coinciden con D50. Además, sin esas horas ningún veredicto cambia: C02 de 0,035 a 0,099, C03 de −0,059 a 0,048, C04 de −0,105 a 0,024, C05 0,790, C06 +0,164, C07 de −0,160 a −0,059, C08 de 0,054 a 0,102. D50 decía que los intervalos no se recalcularon y atribuía a L66 que ningún veredicto cambia: ahora está medido | Documentado como se decidió (análisis posterior al sello), con su efecto correcto |
| B2 | `task load`, `fit_model`, `score`, `track`, `evaluate`, `export`, `render_dashboard` y `report` sin `--run-key` salen con 1 («falló: RunStateError…») y dejan un estado `failed` en `interim/runs/`; `fit_model`, `track`, `evaluate` y `report` sobre una copia limpia crean además el almacén. Igual en una copia con entregas pendientes, en una cerrada y con la configuración real (`task evaluate` crea `data/warehouse/flotsilica.sqlite`) | Las ocho salen con 2 («la corrida … no tiene una entrega… No se escribió nada.»), la salida estándar vacía y ningún archivo escrito, en los cuatro estados. También `task load --run-key T3` de una corrida que solo corrió `fetch_source` sale con 2 y deja su estado como estaba | Cerrado |
| B3 | D47 dice C02 «de 0,048 a 0,110» y C08 «de 0,057 a 0,105», y `SITE-UPDATES.md:289`, C08 «de 0,057 a 0,105» | Cada límite de C02-C04, C07 y C08 que citan D47, el README, la ficha y las filas del 05 en `SITE-UPDATES.md` es el del resumen redondeado a los decimales que escribe el documento (18 citas comparadas por un guion propio y la de C04 de la fila 7 de `SITE-UPDATES.md` a mano; ninguna mal; en `362bcee` el mismo guion encuentra las tres de la evaluación) | Cerrado |
| B4 | El registro terminaba en L65 | L66 registra U22 y U23 (escritores con Sonnet, commits, revisiones, 83,30 s y 84,04 s con 984 pruebas) y la evaluación; el mensaje de `616773b` registra la suite de las correcciones (990 pruebas, 83,71 s y 84,50 s); cada afirmación de U22, U23 y la evaluación en el README, la ficha, el paso a paso, `review-advisories.md` y D50-D52 la tiene L66 o `git log`, salvo las de la advertencia N2. Pero `SITE-UPDATES.md` dice lo contrario de L66 (N1) | Cerrado en lo nombrado; queda N1 |

**El diferencial de la línea de comandos.** Los mismos 102 pasos, cada uno en una copia nueva de su estado: cada ayuda; el uso sin orden y con una orden desconocida; `run` con cada combinación rechazada, con `--only`, `--from`, `--run-key`, `-v`, con `FLOTSILICA_CONFIG` y con un `--config` que no existe; `task` con cada una de las once tareas sin `--run-key` en una copia limpia, en una con entregas pendientes (el lanzamiento y la primera diaria) y en una cerrada, con `--run-key` de una corrida que validó, de una que no validó, de una sin entrega y de una cerrada, y con una tarea desconocida; `replay` hasta una entrega que no existe, anterior a la pendiente, ya cargada, la siguiente y todas, con y sin pendientes; `make-fixture` con cada opción y sus rechazos; `serve` con `--host 0.0.0.0`, `--port 0` y `70000`, sin sello y sin artefacto; `figures` y `docs-sync` en modo rápido y en la configuración real (también con los dos bloques viejos, que los dos commits reescriben igual, dejando el diccionario byte a byte como el versionado); y `run`, `replay` y `task` con la configuración real sin el ARFF (salida 3). Se compararon el código de salida, la salida estándar, el error y los archivos escritos, normalizando claves de corrida, horas, segundos, números de línea de las trazas, la carpeta de cada copia y las huellas de los manifiestos (que dependen de las claves de corrida). Las únicas diferencias:

- La ayuda de `task --run-key` y de `replay --until` (pedidas).
- Las ocho tareas desde `load` sin `--run-key` en los cuatro estados (35 pasos) y `task load --run-key` de una corrida sin entrega: 1 con un estado `failed` antes, 2 sin escribir ahora (B2, pedido).
- `replay --until` con todo cargado, hasta el lanzamiento y hasta el cierre: 0 («No hay entregas pendientes») antes, 2 sin escribir ahora (A4, pedido). Con entregas pendientes, `--until` anterior o ya cargada sale con 2 en los dos.

`task deliver` y `task validate` sin `--run-key` siguen saliendo con 1 y dejando un estado `failed`, igual en los dos commits, como dice D52.

**El diferencial de la API.** Con el cliente de FastAPI en el mismo proceso, el código de cada commit y el modelo sellado de la repetición real: `GET /health`, 10 cuerpos válidos (8 instantes de la prueba y 2 anteriores) armados con el lector propio, 22 variantes inválidas o al borde (un análisis posterior al instante, 181, 10 y 0 lecturas, instante fuera de la hora en punto, con zona horaria o ilegible, números como texto, sensores de menos y de más, historia corta, vacía, duplicada, desordenada, sílice negativa, sin alimentación, con alimentación incompleta o nula, campos desconocidos, sin `issue_at`, un instante de 2030), un objeto vacío, una lista, JSON roto, y `GET /estimate`, `POST /health` y una ruta que no existe. Las respuestas (código y cuerpo) son idénticas byte a byte en los dos commits; las 24 estimaciones de la prueba son iguales a las guardadas (diferencia 0), y el árbol del proyecto no cambió.

**Las suites y la repetición real en `616773b`.**

| | Resultado | Tiempo |
| --- | --- | --- |
| Suite rápida, dos corridas seguidas (sin otra corrida de Python; en la primera, dos lecturas de menos de un segundo) | 989 pasaron y 1 se omitió (990 recogidas, 4 deseleccionadas), las dos | 90,77 s y 85,64 s |
| `replay` real en la copia, con el sello versionado | Salida 0, 42 corridas; el sello igual byte a byte; contra lo versionado, el HTML, los seis JSON del sitio y los cuatro reportes difieren solo en las claves de corrida, los 20 Parquet solo en `flotsilica.run_key`, las columnas `run_key` de `fact_estimate` y `fact_validation` y `dim_pipeline_run`, y los manifiestos en sus huellas | 476 s (con el diferencial corriendo a la vez) |
| `-m real_data` después de esa repetición | 2 pasaron (`test_real.py` ya no exige las claves de corrida del sello después de una reconstrucción: A1) | 13,19 s |

**Lo que encontró nuevo.** Un bloqueante y tres advertencias, con su estado:

- **N1. `SITE-UPDATES.md` decía que la evaluación no se hizo.** La línea 244 decía «**La evaluación final independiente todavía no se hizo** (plan, sección 28): las cifras de estas filas son las del resumen sellado y del registro, no las que un evaluador recalculó; cuando se haga, las filas 2, 7, 8, 12, 13 y 15… quedan pendientes de su confirmación»; la 268, «…antes de la evaluación independiente»; la 303, «la evaluación independiente todavía no se hizo»; y las filas 2, 7, 12, 13 y 15 (líneas 249, 254, 259, 260 y 262) terminaban «**Pendiente** de la evaluación». L66 registra que la evaluación reprodujo cada cifra publicada, el sitio incluido, y la línea 295 del mismo archivo ya citaba sus hallazgos. Bloqueante (una afirmación que el registro contradice). **Estado: corregido en esta sincronización:** `SITE-UPDATES.md` dice lo que la evaluación encontró y cómo queda la cifra de cada fila, y una prueba (`test_the_root_rows_of_project_05_do_not_say_the_evaluation_is_pending`) falla si vuelve una de esas frases.
- **N2. Afirmaciones de las correcciones que el registro todavía no tenía (RNF14; plan, sección 28.4).** El registro terminaba en L66, que tiene la decisión («the corrections (opus, test first)») pero no las correcciones. No lo tenían ni L66 ni `git log`: que las escribió «otro agente con Opus» (README, D52 «Quién»), que cada prueba nueva «se vio fallar» y el diferencial contra `ffb8297` (D52), las cifras de H1 y H2 de D50 (la comprobación las midió y coinciden) y que la evaluación «explicó la de `docs.py`» (`review-advisories.md`). Ninguna estaba contradicha. **Estado: corregida:** L67 las registra (el modelo, la prueba vista fallar, el diferencial contra `ffb8297`, las cifras recalculadas sin las 16 horas); la frase sobre `docs.py` se quitó de `review-advisories.md`, porque ni L66 ni L67 la tienen.
- **N3. La suite volvió a pasar el presupuesto de trabajo de 90 s.** 90,77 s y 85,64 s aquí, 90,86 s y 80,52 s en la evaluación (A3), contra los 83,71 s y 84,50 s de los documentos; siempre dentro del límite de 120 s. La sección 28.2 pide una unidad de velocidad si la suite pasa los 90 s; decidirlo es del orquestador. **Estado: respondida por `79ed5cc`** (ver A3).
- **N4. A8 sigue pendiente.** La próxima entrada del registro tiene que llamar «SHA-256 de `config/pipeline.toml`» a lo que L65 llamó «config sha256 `7fe6fefc…`». **Estado: corregida en L67.**

## La medición de esta sincronización

Estas cifras las midió la sincronización de la documentación, no el registro: el registro todavía no las tiene y las tendrá cuando registre esta sincronización.

- **Pruebas recogidas por la selección por defecto:** 993 (992 pasaron y 1 se omitió en las corridas de abajo).
- **Suite rápida, dos corridas seguidas en reposo (ningún otro proceso de Python), en el árbol de esta sincronización, que tiene el código de `79ed5cc`:** 76,29 s y 76,39 s.
- **Memoria.** Las cifras de memoria de los documentos son las medidas en la corrida real de U21 (1.346,3 MB de `PeakWorkingSetSize` y 3.224,0 MB de `PeakPagefileUsage`, D47) y las de la repetición del evaluador (1.442,5 MB de `PeakWorkingSetSize` y 3.212,8 MB de `PeakPagefileUsage`); esta sincronización no repitió la corrida real y no midió memoria.

## Lo que queda

La página del sitio, el `.pbix` y lo que el plan deja al dueño (sección 29): entre otros, cambiar la regla de las horas que abren una rampa y medir la condición de V1 de la compuerta fuera de la muestra (ítems 14 y 15), la latencia real del laboratorio, el texto del sitio, la estrategia de entrega y el `push`. Las advertencias abiertas están en [review-advisories.md](review-advisories.md); ninguna es bloqueante.
