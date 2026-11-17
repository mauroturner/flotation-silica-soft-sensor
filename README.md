# Sílice en el concentrado, sin esperar al laboratorio

Pendiente: este proyecto se construye después del anterior. El plan y el dataset están en el índice del [portafolio](../README.md).

<!-- results:start -->
## Resultados

Criterios fijados antes de construir, evaluados una vez sobre la prueba.

| Criterio | Umbral | Valor | Cumple | Veredicto |
| --- | --- | ---: | --- | --- |
| C01 H0 frente a la persistencia | MAE(modelo) < MAE(persistencia) | 0,597 | no | El modelo no supera a la persistencia en la hora que cerró: MAE 0,60 frente a 0,52. |
| C02 H0 fuera del ruido frente a la base más fuerte | límite superior del intervalo del 95 % de MAE(modelo) − MAE(B*) < 0 | 0,597 | no | El modelo no supera a la base más fuerte en la hora que cerró fuera del ruido: MAE 0,60 frente a 0,52; la diferencia va de 0,05 a 0,11. |
| C03 H1 fuera del ruido frente a la base más fuerte | límite superior del intervalo del 95 % de MAE(modelo) − MAE(B*) < 0 | 0,703 | no | El modelo no supera a la base más fuerte en la hora que empieza fuera del ruido: MAE 0,70 frente a 0,70; la diferencia va de −0,05 a 0,05. |
| C04 H2 fuera del ruido frente a la base más fuerte | límite superior del intervalo del 95 % de MAE(modelo) − MAE(B*) < 0 | 0,753 | no | El modelo no supera a la base más fuerte en la hora siguiente fuera del ruido: MAE 0,75 frente a 0,79; la diferencia va de −0,10 a 0,03. |
| C05 Cobertura del rango de H0 | proporción de horas con el análisis dentro del rango del 80 % entre 0,75 y 0,85 | 0,793 | sí | El rango del 80 % cumple en la hora que cerró: cubre 0,793 de las horas, y se pedía entre 0,75 y 0,85. |
| C06 Sesgo de H0 | \|media(modelo − análisis)\| ≤ 0,10 | 0,148 | no | El sesgo en la hora que cerró no cumple: el modelo estima 0,148 de más en promedio, y se pedía a lo sumo 0,10. |
| C07 Los sensores solos frente a la media | límite superior del intervalo del 95 % de MAE(mejor solo con sensores) − MAE(B0) < 0 | 0,819 | sí | Los sensores solos superan a la media del entrenamiento: MAE 0,82 frente a 0,92; la diferencia va de −0,16 a −0,06. |
| C08 Los sensores agregan a la historia del laboratorio | límite superior del intervalo del 95 % de MAE(mejor con sensores) − MAE(mejor solo con laboratorio) < 0 | 0,597 | no | Con sensores, el modelo no agrega a la historia del laboratorio: MAE 0,60 frente a 0,52; la diferencia va de 0,06 a 0,10. |
| C09 Sensibilidad estable | al menos un sensor pasa la compuerta y conserva el signo de su dependencia parcial en la prueba | 0,000 | no | Ningún sensor pasa la compuerta de estabilidad: sin asociación estable. |
| C10 Por semana y variantes (informativo) | sin umbral: que esté escrito y sea consistente | sin dato | informativo | Informativo, sin umbral: el MAE del modelo, de la persistencia y de la base más fuerte por semana y las variantes de latencia y de reajuste, escritos en el sello (2295 horas evaluadas). |

Validación (V2, no la prueba): MAE de cada método por horizonte.

| Método | H0 | H1 | H2 |
| --- | ---: | ---: | ---: |
| Modelo | 0,542 | 0,651 | 0,673 |
| Base más fuerte (B*) | 0,533 | 0,628 | 0,687 |
| Media del entrenamiento (B0) | 0,914 | 0,914 | 0,914 |
| Persistencia (B1) | 0,533 | 0,669 | 0,724 |
| Media de los últimos análisis (B2) | 0,547 | 0,628 | 0,687 |
| Ridge sobre sensores (B3) | 0,981 | 0,922 | 0,878 |
| Mejor solo con sensores | 0,782 | 0,784 | 0,803 |
| Mejor solo con laboratorio | 0,521 | 0,641 | 0,687 |
| Mejor con sensores y laboratorio | 0,542 | 0,651 | 0,673 |

Estado: sealed. Corrida 20261117T180212267264Z del 2017-09-10 01:00:00.
<!-- results:end -->
