# Reporte de validación

- Corrida: `20261117T180212267264Z`
- Resultado: **Aceptado: ninguna regla bloqueante falla.**
- SHA-256 del archivo de origen: `a25122979ba8c5fb9c12e361db61032efc6892a24b5746cc8309da601d9639b2`
- Entrega: C2017-09-10; filas de la entrega: 0; horas: 0

## Reglas

| ID | Regla | Severidad | Agregación | Estado | Filas | Horas |
| --- | --- | --- | --- | --- | ---: | ---: |
| V01 | El archivo existe y tiene el tamaño y la huella aceptados (o la registrada, en modo rápido) | bloqueante | source | pasa | 0 | 0 |
| V02 | Cabecera exacta: @RELATION, los 24 @ATTRIBUTE en orden y todos STRING, @DATA una vez | bloqueante | source | pasa | 0 | 0 |
| V03 | UTF-8 estricto, sin byte nulo, líneas dentro del tope, archivo y filas dentro de sus topes | bloqueante | source | pasa | 0 | 0 |
| V04 | Cada fila con 24 campos, cada uno entre apóstrofos o un entero sin apóstrofos, y ninguno vacío | bloqueante | source | pasa | 0 | 0 |
| V05 | Fecha AAAA-MM-DD HH:00:00 y números con coma decimal | bloqueante | source | pasa | 0 | 0 |
| V06 | Fechas no decrecientes | bloqueante | source | pasa | 0 | 0 |
| V07 | Ninguna hora con más filas que las de una hora completa | bloqueante | source | pasa | 0 | 0 |
| V10 | La entrega es la siguiente del plan y su período empieza en la hora siguiente al fin de la anterior | bloqueante | per_run | pasa | 0 | 0 |
| V11 | Cada hora de la entrega está dentro de su período | bloqueante | per_run | pasa | 0 | 0 |
| V12 | Ninguna hora ni identificador de fila de la entrega está ya en el almacén ni repetido dentro de ella | bloqueante | per_run | pasa | 0 | 0 |
| V13 | Filas, horas y SHA-256 son los del manifiesto; solo el cierre puede no tener filas | bloqueante | per_run | pasa | 0 | 0 |
| V14 | Los agregados de cada hora son los de sus filas | bloqueante | per_run | pasa | 0 | 0 |
| V15 | Las filas de la entrega no traen columnas de laboratorio (solo la hora trae su primera fila) | bloqueante | per_run | pasa | 0 | 0 |
| V20 | Hora incompleta (se marca y se usa) | advertencia | per_run | pasa | 0 | 0 |
| V21 | Hora con menos filas que el mínimo (no se estima) | advertencia | per_run | pasa | 0 | 0 |
| V22 | Análisis interpolado (no es objetivo ni rasgo) | advertencia | per_run | pasa | 0 | 0 |
| V23 | Análisis repetido (no es objetivo ni rasgo) | advertencia | per_run | pasa | 0 | 0 |
| V24 | Alimentación que cambia dentro de la hora (se usa la primera fila) | advertencia | per_run | pasa | 0 | 0 |
| I01 | Horas faltantes en la grilla | informativa | source | pasa | 0 | 318 |
| I02 | Horas con la alimentación sin cambio desde hace 24 h o más | informativa | latest | pasa | 241920 | 1344 |
| I03 | Sensor constante dentro de la hora | informativa | per_run | pasa | 0 | 0 |
| I04 | Estimaciones emitidas | informativa | per_run | pasa | 0 | 0 |
| I05 | Estimaciones sin las entradas necesarias, con el motivo | informativa | per_run | pasa | 0 | 0 |
| M03 | El artefacto del modelo tiene la huella registrada, antes de deserializarlo | bloqueante | per_run | pasa | 0 | 0 |
| M05 | La configuración es la sellada (si no, todo lo calculado es posterior al sello) | advertencia | latest | pasa | 0 | 0 |

## Ejemplos

### I02: Horas con la alimentación sin cambio desde hace 24 h o más

- `{"feed_silica_unchanged_hours": 1344, "feed_iron_unchanged_hours": 1344, "threshold_hours": 24}`
