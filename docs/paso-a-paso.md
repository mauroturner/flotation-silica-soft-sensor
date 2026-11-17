# Paso a paso: cómo se construyó

La cronología real del proyecto, desde el registro del documento de seguimiento (`odd/tasks/portfolio-projects.md`, L58 a L65) y `git log`, con cada commit del proyecto en orden y lo que hizo. Los commits `docs(odd)` registran cada paso en el documento de seguimiento, fuera de esta carpeta; se nombran donde cierran una tanda. Quién escribió cada parte es lo que consta en el registro: un agente con Haiku investigó, uno con Opus escribió el plan, agentes con Sonnet escribieron las unidades U01 a U21 (y U22 y U23, esta documentación), y la revisión nativa de Gentle AI revisó cada unidad de riesgo alto sola, con el consentimiento aceptado de forma automática por pedido del dueño (S11). La evaluación independiente, sus correcciones y la página del sitio todavía no están hechas: este documento llega hasta U23 y se completa cuando existan. Las cifras de la suite son las que el registro anotó después de cada tanda, medidas en el equipo de desarrollo, y no se vuelven a medir aquí.

## Los datos (2026-11-09 a 2026-11-17)

- `1d5d1e3` **Andamio.** Las ocho carpetas de los proyectos y el emblema, antes de empezar ninguno.
- El dueño no tenía los datos de Kaggle ni una cuenta para bajarlos (L58). Eligió la copia de OpenML (dataset 43311, convertida) y la bajó a mano; el agente comprobó que es un ARFF válido, de 185.243.565 bytes, con 24 atributos declarados como texto y 737.453 filas de 24 campos, le calculó el SHA-256, lo movió a `data/raw/` (que no se versiona) y dejó escrito que es una conversión no comparada byte a byte con el CSV de Kaggle (L59). `fa44c77` lo registra en el documento de seguimiento.

## Investigación y plan (2026-11-17)

- `8ff5bca` **Investigación** (Haiku, L60). `docs/research.md` con sus diez scripts en `research/`: 4.095 de 4.097 horas con 180 filas, la alimentación que se mantiene días (la racha más larga, 792 h), 310 horas de sílice en rampa, el hueco de 318 h, la fuga de la partición al azar (R² 0,565 con ella contra −0,511 en un bloque del tiempo con el mismo modelo), las líneas base y una primera mirada que no supera a la persistencia. Nada calculado sobre la prueba. Su revisión nativa (riesgo alto por el `pickle.load` que los scripts hacen de sus propios intermedios) lo aprobó sin hallazgos.
- `8adbbbd` **Requerimientos, plan y decisiones** (Opus, L61), confirmados antes de la primera línea de código: `docs/requirements.md` (RF01-RF26, RNF01-RNF16, AC01-AC40), `docs/plan.md` (23 unidades) y `docs/decisions.md` (D01-D43). Con una medición propia leyendo el archivo solo hasta antes del 2017-07-31: el 15,3 % de las horas no trae un análisis nuevo (rampas interpoladas y horas repetidas), así que la persistencia de la investigación estaba ayudada (0,505 sobre las horas nuevas, no 0,452); los criterios C01-C10 y lo esperado, escritos antes de medir (que el modelo probablemente no supere a la persistencia). Este commit superó el presupuesto de contexto de una revisión, solo y con U01, y no se revisó de forma nativa: se evaluó como riesgo medio y no debido.

## U01-U06: entorno, configuración, accesorio, lectura, entregas y almacén (L62)

- `c80d4b4` **U01** Las versiones fijadas (las del proyecto 04 menos `openpyxl`, `shap` y sus dependencias) y la prueba de que cada importación directa es una dependencia fijada (ítem 5 de riesgo alto, revisada sola: dos sugerencias).
- `e1854bb` **U02** La configuración tipada, con cada clave clasificada como sellada o no sellada, y las rutas contra la carpeta del proyecto.
- `7be52f7` **U03** El ARFF sintético con su tabla de verdad, los casos a mano, los accesorios de sesión y el límite de 120 s de la suite (U02 y U03 se revisaron como un tramo: tres advertencias).
- `0cde78d` **U04** La lectura estricta del ARFF no confiable (V01-V07), las filas y las horas canónicas con la frescura de cada análisis (ítem 2, sola: una advertencia). Con el archivo real apareció un hecho que el plan no tenía: el ARFF escribe los enteros sin apóstrofos en 28.124 de las 560.333 filas anteriores a la prueba, y V04 los acepta.
- `48a741e` Las correcciones de esas revisiones: fsync antes de renombrar, la comprobación de calendario sin la latencia que se cancelaba, la variable muerta, y la documentación de los enteros sin apóstrofos.
- `ed3c66e` **U05** El plan de entregas y 29 reglas de validación.
- `611b213` **U06** La carga en SQLite en una sola transacción, con seis controles en SQL y la hora de llegada de cada análisis.

Suite rápida: 37 pruebas en 1,1 s (U01), 189 en 2,2 s, 237 en 12,4 s, 373 en 17,7 s, 383 en 18,4 s, 466 en 30,0 s y 495 en 41,0 s (U06). `c862455` lo registra.

## U07-U12: rasgos, partición, modelo, sello, evaluación y sensibilidades (L63)

- `e356b28` **U07** Los rasgos de un instante, construidos solo con lo que había llegado, con la guarda de fuga sobre la matriz y las pruebas de truncamiento y de perturbación.
- `e42aaf2` **U08** La partición en el tiempo con sus purgas, las líneas base ajustadas en sus propios bloques y el remuestreo por días enteros. U07 y U08 se revisaron como un tramo: dos sugerencias.
- `a7be0e2` **U09** La grilla en el entrenamiento, la elección en V1, el reajuste con entrenamiento y V1, el rango del 80 % calibrado en V2 y el artefacto que solo se carga si coincide su tamaño y su huella (ítem 2, sola: una advertencia, corregida en U10).
- `5656408` **U10** El modelo congelado y sellado en el lanzamiento con la huella de cada clave de la configuración, cada estimación emitida una sola vez en tablas de solo inserción (los disparadores de SQLite impiden también `INSERT OR REPLACE` y `ON CONFLICT DO UPDATE`) y la prueba rechazada con otra configuración antes de escribir (ítem 1, sola: sin hallazgos).
- `c8d9c3c` **Velocidad.** La suite bajó de 61,4 s a 44,6-46,2 s con las mismas pruebas (la colección difiere en una, la prueba de la guarda nueva); además cerró tres sugerencias de las revisiones.
- `c1c37b4` **U11** La prueba evaluada una vez desde lo emitido, los criterios C01-C10 desde los límites sellados (un empate nunca pasa y un criterio que no se puede calcular no pasa y dice por qué), el resumen reconstruido desde el sello y el bloque del README.
- `a995add` **U12** La importancia por permutación, la dependencia parcial y la compuerta de estabilidad calculada antes del sello del lanzamiento; cada texto de un sensor dice «asociación del modelo» o «sin asociación estable». Los controles encuentran exactamente `amina_flow` en el positivo y ningún sensor en el negativo.

Suite rápida: 495 a 629 pruebas en U10 (63,1 s), 630 en 44,6 s, 665 en 50,5 s y 675 en 60,4 s (`a995add`; en la repetición del orquestador, 61,5 s). En U09 y en parte de U10 el código existió antes que sus pruebas y la RED se recuperó con variantes ingenuas, y el registro lo dice; a la escritora se le volvió a pedir la prueba primero. Las mutaciones de U11 (35, con 12 sobrevivientes al principio) y de U12 (27, con 7) las atraparon casos nuevos. `daf308a` lo registra.

## U13-U17: modelo estrella, tablero, sitio, bloqueo y tareas (L64)

- `a1096bd` **U13** El seguimiento de cada estimación contra su análisis, el modelo estrella de 20 tablas con las reglas R01-R15 y la exportación a Parquet (ítem 3, revisada en dos partes).
- `027471c` Las correcciones de las revisiones: el orden publicado de los métodos con su prueba, las copias de almacén de las pruebas con su plan vivo y una importación que sobraba.
- `6a4ea19` **U14** Las medidas, las cinco páginas y el diseño del tablero en HTML, que se comprueba de forma estática porque ningún DAX se ejecuta (ítem 6, sola).
- `cf64427` **U15** La exportación de los cinco archivos del sitio con su manifiesto, escrito último, el límite de bytes y las siete figuras dibujadas solo desde los archivos verificados (ítem 3, revisada en dos partes).
- `e2a6dfa` **U16** El bloqueo de un solo escritor: un segundo escritor sale con 2 y soltarlo nunca levanta una excepción (ítem 4, sola).
- `24eda95` **U17** Las once tareas de la corrida con su estado, el cierre en orden y los rechazos antes de escribir, con la medición de memoria y su contador (ítem 4, sola: sin hallazgos).
- `36fe9d2` **Velocidad.** Las filas de rasgos de un bloque se arman por rebanadas de arreglos y no con dos tablas y un orden por hora; los rasgos son idénticos en los tres horizontes y una prueba lo fija; la suite bajó de 81,4 s a 72,6-73,1 s. No se llegó a los 60 s que se buscaban y se aceptó así: queda dentro del presupuesto de trabajo de 90 s (D33).

Suite rápida: 837 pruebas pasadas (parent, 73,2 s tras `36fe9d2`; 82,5 s antes). `31a943d` lo registra.

## U18-U21: línea de comandos, API, Airflow y la corrida real (L65)

- `8b92a18` **U18** La línea de comandos (`run`, `replay`, `task`, `make-fixture`, `figures` y `docs-sync`) sobre las mismas tareas que Airflow, con una prueba por opción y 14 combinaciones incompatibles que salen con 2 antes de escribir, y el modo rápido que solo escribe bajo `data/quick/`.
- `352b915` La corrección de una revisión: `_known_arrays` devuelve la hora de muestra más nueva en las dos ramas.
- `7ee1103` **U19** La API local de estimación con FastAPI, de solo lectura y solo en `127.0.0.1`, que se niega a servir sin sello o con otro artefacto y que da lo mismo que el flujo, con igualdad exacta de `float`, para las 72 estimaciones de prueba (ítems 2 y 5, sola: una advertencia refutada).
- `bdd4e14` Una prueba que fija que la API responde igual a un historial de análisis en cualquier orden (la advertencia refutada decía lo contrario; `lab_known_at` ordena por hora de muestra).
- `8033325` **U20** El DAG `flotsilica_daily` de Airflow sobre la imagen `apache/airflow:3.4.0` fijada por su resumen, un compose con todos los secretos del entorno y la prueba de Docker que corre `airflow dags test` dos veces y deja Docker como estaba (ítems 5 y 2, sola: sin hallazgos; 2 pasaron en 148 s).
- `b27f244` **U21** La corrida real, una sola vez: `replay` terminó con 0 en 444,0 s con las 42 corridas `ok` y el sello de la prueba escrito; los criterios salieron como salieron, sin reinterpretar ni repetir nada (ítem 1).
- `d469a5b` Las salidas generadas de esa corrida: el modelo estrella, los archivos del sitio y las figuras, que el orquestador agregó después de que la verificación de los archivos del sitio no encontró problemas.
- `7bdc11e` La corrección de la última revisión: la prueba de la corrida real cierra siempre la conexión.

Suite rápida: 78,6 s tras `352b915` y unos 82 s tras U19-U21 (965 pasaron y 1 se omitió). Resultado de la prueba, escrito como salió: C01-C04, C06, C08 y C09 no se cumplen, C05 y C07 se cumplen y C10 es informativo (D47). `ee1e9e7` lo registra.

## U22: README y ficha del modelo

- `011af97` **U22** El README con sus trece títulos y su bloque de resultados copiado del resumen sellado, y la ficha del modelo, con la prueba primero (`tests/docs/test_docs.py`): los títulos en orden, el bloque igual al resumen, los veredictos «no supera» dichos en los tres lugares que los cuentan y los contadores de memoria.
- `70e1b73` El README cuenta U18 a U21 y sus revisiones desde el registro (L65).

## U23: diccionario, runbook, paso a paso, advertencias y filas de la raíz

- **U23** Este documento y sus compañeros: `docs/data-dictionary.md` con las 24 columnas del archivo, las 67 variables y una tabla por Parquet que `docs-sync` escribe desde el modelo semántico; `docs/runbook.md` con R1 a R12, corrido en una copia del proyecto; `docs/review-advisories.md` con las advertencias de las revisiones nativas de U01 a U21 y su estado; y las filas del proyecto 05 en `SITE-UPDATES.md`. Se agregaron a `tests/docs/test_docs.py` las pruebas de las decisiones con sus siete campos, del número de pruebas que dicen los documentos contra la colección de la sesión, de las cifras de memoria con su contador, de cada prueba que nombra el plan, del diccionario contra el código y los Parquet, del runbook, de este documento y de los vínculos, y se extendió `docs-sync` para que escriba las tablas del diccionario (D49). El commit de U23 lo nombra `git log`; este documento no puede citar su propia huella.
- Después de U23: la evaluación final independiente (un agente con Opus que no construyó el proyecto), sus correcciones, la comprobación, la sincronización de la documentación con la última corrección y la página del sitio (plan, sección 28). Hasta entonces, el número de pruebas, los tiempos de la suite y las advertencias abiertas son los del commit de U23.
