"""The semantic model of the Power BI report: the single source of its tables and relationships (RF21, AC25; D25; plan, section 19). Adapted from project 04's
``dashboard/semantic_model.py`` without the privacy layer (D43).

Tables with their columns (type, description, unit) and relationships (all one to many, single direction, active) live here; the Arrow schema of every Parquet file
and, later, the data dictionary and the HTML design come from this module. Names of tables, columns and files are in English; descriptions and labels in Spanish
(RNF13). The measures (DAX) and the five pages of the report (a 12 x 9 grid of visuals) live here too (U14, plan section 20); ``validate_model`` checks that every DAX reference
and every field of a visual is a column or a measure of the model, because no measure runs in the project.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import pyarrow as pa

ARROW_TYPES = {"int8": pa.int8(), "int32": pa.int32(), "int64": pa.int64(), "float64": pa.float64(), "string": pa.string(), "bool": pa.bool_(), "date": pa.date32(),
               "datetime": pa.timestamp("us")}


@dataclass(frozen=True)
class Column:
    name: str
    dtype: str    # a key of ARROW_TYPES
    description_es: str
    unit: str | None = None


@dataclass(frozen=True)
class Table:
    name: str
    kind: Literal["dimension", "fact"]
    key: tuple[str, ...]          # a dimension's unique key or a fact's grain
    columns: tuple[Column, ...]
    description_es: str = ""

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)


@dataclass(frozen=True)
class Relationship:
    rel_id: str
    dim_table: str
    dim_column: str
    fact_table: str
    fact_column: str
    cardinality: str = "one_to_many"
    cross_filter: str = "single"
    active: bool = True


@dataclass(frozen=True)
class Measure:
    name_es: str
    dax: str
    format_string: str
    description_es: str


@dataclass(frozen=True)
class Visual:
    kind: str                     # slicer, card, table, barChart, lineChart
    title_es: str
    fields: tuple[str, ...]       # "table[column]" or "[Measure]"
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class Page:
    name_es: str
    visuals: tuple[Visual, ...]


@dataclass(frozen=True)
class SemanticModel:
    tables: tuple[Table, ...]
    relationships: tuple[Relationship, ...]
    measures: tuple[Measure, ...] = ()
    pages: tuple[Page, ...] = ()

    def table(self, name: str) -> Table:
        return next(t for t in self.tables if t.name == name)

    def measure(self, name: str) -> Measure:
        return next(m for m in self.measures if m.name_es == name)


PCT = "% de sílice"


def _c(name: str, dtype: str, description_es: str, unit: str | None = None) -> Column:
    return Column(name, dtype, description_es, unit)


HOUR_KEY = _c("hour_key", "int64", "Hora, como AAAAMMDDHH.")
HORIZON_KEY = _c("horizon_key", "int8", "Horizonte: 0 la hora que cerró, 1 la siguiente, 2 la de dentro de dos horas.")
METHOD_KEY = _c("method_key", "string", "Método: el modelo, una regla o un modelo de comparación.")
SENSOR_KEY = _c("sensor_key", "string", "Sensor de la planta.")
MODEL_KEY = _c("model_key", "string", "Modelo congelado de un horizonte (versión y horizonte, por ejemplo v1-h0).")
SEAL_STATE = _c("seal_state", "string", "sealed (la configuración sellada) o post_seal (otra, posterior al sello).")
SCOPE = _c("scope", "string", "Bloque evaluado: valid_v1, valid_v2 (validación) o test (la prueba).")
DATE_KEY = _c("date_key", "int32", "Fecha, como AAAAMMDD.")
RUN_KEY = _c("run_key", "string", "Corrida que lo escribió.")

DIM_DATE = Table("dim_date", "dimension", ("date_key",), (
    DATE_KEY, _c("date", "date", "Fecha."), _c("year", "int32", "Año."), _c("month", "int32", "Mes (1-12)."), _c("month_name_es", "string", "Nombre del mes."),
    _c("weekday_es", "string", "Nombre del día de la semana."), _c("test_week", "int32", "Semana de la prueba (semanas de 7 días desde su primera hora); vacía fuera de ella."),
), "Calendario, del primer al último día que tiene horas.")
DIM_HOUR = Table("dim_hour", "dimension", ("hour_key",), (
    HOUR_KEY, _c("hour", "datetime", "Hora (el comienzo del intervalo de una hora)."), _c("date", "date", "Fecha de la hora."), _c("hour_of_day", "int32", "Hora del día (0-23)."),
    _c("block", "string", "Bloque de la partición en el tiempo."), _c("block_es", "string", "Bloque de la partición, en español."),
    _c("lab_state", "string", "Análisis de la hora: fresh, interpolated, held, pending (todavía no llegó) o missing (no hay datos)."),
    _c("lab_state_es", "string", "Análisis de la hora, en español."), _c("is_partial", "bool", "La hora tiene menos filas que las 180 completas."),
    _c("rows", "int32", "Filas de sensores de la hora.", "filas"),
), "Todas las horas, una por una, de la primera hora con datos a la última estimada (también las que no tienen datos).")
DIM_HORIZON = Table("dim_horizon", "dimension", ("horizon_key",), (
    HORIZON_KEY, _c("horizon_es", "string", "Qué hora estima el horizonte, en español."), _c("hours_ahead", "int32", "Horas después de la hora que cerró.", "horas"),
), "Los horizontes del modelo.")
DIM_METHOD = Table("dim_method", "dimension", ("method_key",), (
    METHOD_KEY, _c("method_es", "string", "Método, en español."), _c("kind_es", "string", "Clase: modelo, regla o comparación."),
), "El modelo, las reglas B0 a B2 y los modelos de comparación.")
DIM_SENSOR = Table("dim_sensor", "dimension", ("sensor_key",), (
    SENSOR_KEY, _c("column", "string", "Atributo del archivo fuente."), _c("name_es", "string", "Sensor, en español."),
    _c("group_es", "string", "Grupo: reactivos, pulpa, aire o nivel."), _c("unit_es", "string", "Unidad: la fuente no la dice."),
), "Los 19 sensores de la planta.")
DIM_MODEL = Table("dim_model", "dimension", ("model_key",), (
    MODEL_KEY, _c("model_version", "string", "Versión del modelo."), HORIZON_KEY, _c("family", "string", "Familia del candidato elegido en V1."),
    _c("feature_set", "string", "Conjunto de rasgos elegido en V1."), _c("target_es", "string", "Qué aprende el modelo: el nivel o el cambio."),
    _c("min_samples_leaf", "int32", "Muestras mínimas por hoja del candidato elegido."), _c("half_width", "float64", "Semiancho del rango del 80 %, calibrado en V2.", PCT),
    _c("b_star", "string", "Base más fuerte de este horizonte (B*)."), _c("b2_k", "int32", "Análisis que promedia la regla B2 de este horizonte.", "análisis"),
    _c("trained_on_es", "string", "Con qué se reajustó."), _c("config_sha256", "string", "Huella de la configuración sellada del modelo."), SEAL_STATE,
), "El modelo congelado del lanzamiento, un renglón por horizonte.")
DIM_PIPELINE_RUN = Table("dim_pipeline_run", "dimension", ("run_key",), (
    RUN_KEY, _c("started_at", "datetime", "Inicio."), _c("finished_at", "datetime", "Fin."), _c("status", "string", "Estado: running, ok, failed, rejected o no_delivery."),
    _c("delivery_id", "string", "Entrega que cargó."), _c("as_of", "datetime", "Instante de cálculo de la corrida."), _c("source_sha256", "string", "Huella de la fuente."),
    _c("rows_delivery", "int64", "Filas de la entrega.", "filas"), _c("estimates_issued", "int64", "Estimaciones emitidas.", "estimaciones"),
    _c("estimates_missing", "int64", "Estimaciones sin las entradas necesarias.", "estimaciones"), _c("peak_working_set_mb", "float64", "Pico del conjunto de trabajo.", "MB"),
    _c("peak_commit_mb", "float64", "Pico de memoria confirmada (informativo).", "MB"), _c("memory_counter", "string", "Contador de memoria que dio las cifras."),
    _c("message", "string", "Mensaje de la corrida."),
), "Las corridas del flujo.")

FACT_HOUR_PROCESS = Table("fact_hour_process", "fact", ("hour_key", "sensor_key"), (
    HOUR_KEY, SENSOR_KEY, _c("mean", "float64", "Media del sensor en la hora."), _c("std", "float64", "Desviación estándar muestral del sensor en la hora; vacía con una sola fila."),
    _c("last", "float64", "Último valor del sensor en la hora."),
), "Cada sensor en cada hora cerrada.")
FACT_HOUR_LAB = Table("fact_hour_lab", "fact", ("hour_key",), (
    HOUR_KEY, _c("silica_pct", "float64", "Sílice del concentrado; vacía hasta que llega el análisis.", PCT),
    _c("iron_conc_pct", "float64", "Hierro del concentrado; vacío hasta que llega el análisis.", "% de hierro"),
    _c("feed_silica_pct", "float64", "Sílice de la alimentación; vacía hasta que llega el análisis.", PCT),
    _c("feed_iron_pct", "float64", "Hierro de la alimentación; vacío hasta que llega el análisis.", "% de hierro"),
    _c("lab_state", "string", "fresh, interpolated, held o pending (todavía no llegó)."),
    _c("feed_silica_age_h", "float64", "Horas desde el último cambio de la sílice de la alimentación.", "horas"),
    _c("feed_iron_age_h", "float64", "Horas desde el último cambio del hierro de la alimentación.", "horas"),
    _c("available_at", "datetime", "Instante en que llega el análisis (la hora más la espera del laboratorio)."),
), "El análisis de cada hora cerrada, solo desde que llegó.")
FACT_ESTIMATE = Table("fact_estimate", "fact", ("hour_key", "horizon_key"), (
    HOUR_KEY, HORIZON_KEY, MODEL_KEY, _c("issue_at", "datetime", "Instante en que se emitió la estimación."), _c("status", "string", "ok o missing_inputs (sin las entradas necesarias)."),
    _c("estimate", "float64", "Estimación de la sílice.", PCT), _c("low", "float64", "Límite inferior del rango del 80 %.", PCT),
    _c("high", "float64", "Límite superior del rango del 80 %.", PCT), _c("persistence", "float64", "Último análisis fresco (la persistencia).", PCT),
    _c("b_star", "float64", "Lo que dice la base más fuerte del horizonte.", PCT), _c("actual", "float64", "Análisis fresco de la hora; vacío hasta que llega o si no es fresco.", PCT),
    _c("abs_error", "float64", "Error absoluto del modelo; vacío hasta que llega el análisis.", PCT),
    _c("abs_error_persistence", "float64", "Error absoluto de la persistencia.", PCT), _c("abs_error_b_star", "float64", "Error absoluto de la base más fuerte.", PCT),
    _c("covered", "bool", "El análisis cayó dentro del rango."), _c("is_censored", "bool", "La hora estimada está fuera de los datos: nunca se evalúa."), RUN_KEY,
), "Cada estimación emitida, una vez, con su análisis y sus errores cuando el análisis llegó.")
FACT_METHOD_METRICS = Table("fact_method_metrics", "fact", ("scope", "horizon_key", "method_key", "seal_state"), (
    SCOPE, HORIZON_KEY, METHOD_KEY, _c("mae", "float64", "Error absoluto medio.", PCT), _c("rmse", "float64", "Raíz del error cuadrático medio.", PCT),
    _c("bias", "float64", "Sesgo: media de estimación menos análisis.", PCT), _c("hours", "int32", "Horas evaluadas.", "horas"),
    _c("coverage", "float64", "Parte de las horas con el análisis dentro del rango (solo el modelo).", "proporción"),
    _c("is_b_star", "bool", "Es la base más fuerte de su horizonte (B*)."), _c("ci_low_vs_b_star", "float64", "Límite inferior del intervalo del 95 % de MAE(modelo) − MAE(B*).", PCT),
    _c("ci_high_vs_b_star", "float64", "Límite superior del intervalo del 95 % de MAE(modelo) − MAE(B*).", PCT), SEAL_STATE,
), "Las cifras de cada método por horizonte; las de V1 y V2 son de validación, no de la prueba.")
FACT_WEEKLY_MAE = Table("fact_weekly_mae", "fact", ("test_week", "horizon_key", "method_key", "seal_state"), (
    _c("test_week", "int32", "Semana de la prueba (1 en adelante)."), HORIZON_KEY, METHOD_KEY, _c("mae", "float64", "Error absoluto medio de la semana.", PCT),
    _c("hours", "int32", "Horas de la semana.", "horas"), SEAL_STATE,
), "El error del modelo, de la persistencia y de la base más fuerte por semana de la prueba.")
FACT_EVALUATION_SUMMARY = Table("fact_evaluation_summary", "fact", ("criterion_id", "seal_state"), (
    _c("criterion_id", "string", "Criterio, de C01 a C10."), _c("name_es", "string", "Nombre del criterio."), _c("value", "float64", "Valor medido."),
    _c("baseline_value", "float64", "Valor de la base con que se compara."), _c("ci_low", "float64", "Límite inferior del intervalo."), _c("ci_high", "float64", "Límite superior del intervalo."),
    _c("threshold_es", "string", "Umbral, en español."), _c("passed", "bool", "Cumple; vacío en el informativo."), _c("seen_by_research", "string", "Si la investigación lo vio antes."),
    _c("seen_by_planner", "string", "Si el plan lo vio antes."), _c("verdict_es", "string", "Veredicto, en español."), SEAL_STATE,
), "Los criterios de la prueba y su veredicto.")
FACT_SELECTION = Table("fact_selection", "fact", ("horizon_key", "family", "feature_set", "target", "min_samples_leaf"), (
    HORIZON_KEY, _c("family", "string", "Familia del candidato."), _c("feature_set", "string", "Conjunto de rasgos."), _c("target", "string", "Objetivo: level o change."),
    _c("min_samples_leaf", "int32", "Muestras mínimas por hoja."), _c("mae_v1", "float64", "Error absoluto medio en V1.", PCT), _c("chosen", "bool", "Es el elegido."),
), "Los candidatos de cada horizonte con su error en V1.")
FACT_SENSITIVITY = Table("fact_sensitivity", "fact", ("sensor_key",), (
    SENSOR_KEY, _c("importance_v1", "float64", "Importancia por permutación en V1.", "% de sílice"), _c("importance_v2", "float64", "Importancia por permutación en V2.", PCT),
    _c("rho_min", "float64", "Menor correlación de Spearman de la dependencia parcial."), _c("rho_max", "float64", "Mayor correlación de Spearman de la dependencia parcial."),
    _c("sign_stable", "bool", "El signo de la dependencia parcial no cambia."), _c("pd_range", "float64", "Recorrido de la estimación en la curva de dependencia parcial.", PCT),
    _c("passes", "bool", "Pasa la compuerta de estabilidad."), _c("test_sign_kept", "bool", "Conserva el signo en la prueba; vacío si no pasó la compuerta o la prueba no se evaluó."),
    _c("label_es", "string", "Asociación del modelo o sin asociación estable: nunca una causa."),
), "Las sensibilidades de los sensores, como asociación del modelo.")
FACT_PD_CURVE = Table("fact_pd_curve", "fact", ("sensor_key", "point"), (
    SENSOR_KEY, _c("point", "int32", "Punto de la grilla."), _c("grid_value", "float64", "Valor del sensor en el punto."),
    _c("mean_estimate", "float64", "Estimación media del modelo con ese valor.", PCT),
), "Las curvas de dependencia parcial de los sensores que pasaron la compuerta.")
FACT_VARIANTS = Table("fact_variants", "fact", ("variant", "horizon_key", "method_key"), (
    _c("variant", "string", "Variante: latency_3, latency_4, refit_all o all_hours."), _c("variant_es", "string", "Variante, en español."), HORIZON_KEY, METHOD_KEY,
    _c("mae", "float64", "Error absoluto medio.", PCT), _c("hours", "int32", "Horas evaluadas.", "horas"),
    _c("ci_low", "float64", "Límite inferior del intervalo del 95 % de MAE(modelo) − MAE(persistencia)."),
    _c("ci_high", "float64", "Límite superior del intervalo del 95 % de MAE(modelo) − MAE(persistencia)."),
), "Qué dice la prueba si se cambia un supuesto; informativo, nunca se usa para elegir.")
FACT_LEAKAGE = Table("fact_leakage", "fact", ("check",), (
    _c("check", "string", "Comprobación."), _c("check_es", "string", "Qué se hizo, en español."), _c("mae", "float64", "Error absoluto medio.", PCT),
    _c("r2", "float64", "Coeficiente de determinación."), _c("note_es", "string", "Lo que enseña."),
), "La demostración de la fuga: la partición aleatoria y el hierro del concentrado.")
FACT_DATA_QUALITY = Table("fact_data_quality", "fact", ("date_key",), (
    DATE_KEY, _c("hours", "int32", "Horas con datos.", "horas"), _c("missing_hours", "int32", "Horas sin datos dentro del período de los datos.", "horas"),
    _c("partial_hours", "int32", "Horas con menos filas que las completas.", "horas"), _c("fresh", "int32", "Análisis nuevos que ya llegaron.", "horas"),
    _c("interpolated", "int32", "Análisis interpolados que ya llegaron.", "horas"), _c("held", "int32", "Análisis repetidos que ya llegaron.", "horas"),
    _c("stuck_sensor_hours", "int32", "Horas en que algún sensor no se movió.", "horas"),
    _c("feed_unchanged_24h", "int32", "Horas con la alimentación sin cambio desde hace 24 horas o más.", "horas"),
), "La calidad de los datos, día por día.")
FACT_VALIDATION = Table("fact_validation", "fact", ("run_key", "rule_id"), (
    RUN_KEY, _c("rule_id", "string", "Regla de validación."), _c("name_es", "string", "Nombre de la regla."), _c("severity", "string", "bloqueante, advertencia o informativa."),
    _c("scope", "string", "Alcance: source, delivery, hours o model."), _c("aggregation", "string", "Cómo se agrega entre corridas: source, per_run o latest."),
    _c("status", "string", "pasa, falla o advierte."), _c("rows_affected", "int64", "Filas afectadas.", "filas"), _c("hours_affected", "int64", "Horas afectadas.", "horas"),
), "El resultado de cada regla en cada corrida.")

TABLES: tuple[Table, ...] = (DIM_DATE, DIM_HOUR, DIM_HORIZON, DIM_METHOD, DIM_SENSOR, DIM_MODEL, DIM_PIPELINE_RUN, FACT_HOUR_PROCESS, FACT_HOUR_LAB, FACT_ESTIMATE,
                             FACT_METHOD_METRICS, FACT_WEEKLY_MAE, FACT_EVALUATION_SUMMARY, FACT_SELECTION, FACT_SENSITIVITY, FACT_PD_CURVE, FACT_VARIANTS, FACT_LEAKAGE,
                             FACT_DATA_QUALITY, FACT_VALIDATION)
# (dimension, its key, the facts it filters): every relationship is one to many, of single direction (from the dimension to the fact) and active
_RELATIONSHIPS = (
    ("dim_hour", "hour_key", ("fact_hour_process", "fact_hour_lab", "fact_estimate")), ("dim_date", "date_key", ("fact_data_quality",)),
    ("dim_horizon", "horizon_key", ("fact_estimate", "fact_method_metrics", "fact_weekly_mae", "fact_selection")),
    ("dim_method", "method_key", ("fact_method_metrics", "fact_weekly_mae")), ("dim_sensor", "sensor_key", ("fact_hour_process", "fact_sensitivity", "fact_pd_curve")),
    ("dim_model", "model_key", ("fact_estimate",)), ("dim_pipeline_run", "run_key", ("fact_validation",)),
)
RELATIONSHIPS: tuple[Relationship, ...] = tuple(
    Relationship(f"R{number:02d}", dim, key, fact, key) for number, (dim, key, fact) in enumerate(
        ((dim, key, fact) for dim, key, facts in _RELATIONSHIPS for fact in facts), start=1))
PAGE_COLUMNS, PAGE_ROWS = 12, 9
# --- the measures and the pages (plan, section 20; U14) ------------------------------------------------------------------------------------------------------------------

INTEGER, PERCENT, DECIMAL_2, DECIMAL_3, DATETIME_FORMAT, TEXT_FORMAT = "#,0", "0.0%", "0.00", "0.000", "yyyy-mm-dd hh:mm", "@"
_ARRIVED = "NOT ISBLANK ( fact_estimate[actual] )"
_LAB_FRESH = 'fact_hour_lab[lab_state] = "fresh"'
_SEALED_TEST = 'fact_method_metrics[scope] = "test", fact_method_metrics[seal_state] = "sealed"'

MEASURES: tuple[Measure, ...] = (
    Measure("Horas con análisis", f"CALCULATE ( COUNTROWS ( fact_estimate ), {_ARRIVED} )", INTEGER,
            "Estimaciones (una por hora y horizonte) cuyo análisis fresco ya llegó; con el segmentador de horizonte, las de ese horizonte."),
    Measure("MAE del modelo", f"CALCULATE ( AVERAGE ( fact_estimate[abs_error] ), {_ARRIVED} )", DECIMAL_3, "Error absoluto medio del modelo en las estimaciones cuyo análisis llegó (% de sílice)."),
    Measure("MAE de la persistencia", f"CALCULATE ( AVERAGE ( fact_estimate[abs_error_persistence] ), {_ARRIVED} )", DECIMAL_3,
            "Error absoluto medio de la persistencia (el último análisis fresco) en las mismas estimaciones."),
    Measure("MAE de la base más fuerte", f"CALCULATE ( AVERAGE ( fact_estimate[abs_error_b_star] ), {_ARRIVED} )", DECIMAL_3,
            "Error absoluto medio de B*, la base más fuerte de cada horizonte, en las mismas estimaciones."),
    Measure("Modelo menos persistencia", "[MAE del modelo] - [MAE de la persistencia]", DECIMAL_3, "Diferencia de los dos errores: negativa si el modelo se equivoca menos que la persistencia."),
    Measure("Sesgo del modelo", f"CALCULATE ( AVERAGEX ( fact_estimate, fact_estimate[estimate] - fact_estimate[actual] ), {_ARRIVED} )", DECIMAL_3,
            "Media de la estimación menos el análisis: positiva si el modelo estima de más."),
    Measure("Cobertura del rango", "DIVIDE ( CALCULATE ( COUNTROWS ( fact_estimate ), fact_estimate[covered] = TRUE () ), [Horas con análisis] )", PERCENT,
            "Parte de las estimaciones con análisis llegado cuyo análisis cayó dentro del rango del 80 %."),
    Measure("Última estimación", 'VAR h = CALCULATE ( MAX ( fact_estimate[hour_key] ), fact_estimate[status] = "ok", fact_estimate[horizon_key] = 0 )\n'
                                 "    RETURN CALCULATE ( SELECTEDVALUE ( fact_estimate[estimate] ), fact_estimate[hour_key] = h, fact_estimate[horizon_key] = 0 )", DECIMAL_2,
            "Estimación de la hora que cerró (horizonte 0) en la última hora estimada de las fechas elegidas; vacía si el segmentador de horizonte no incluye el 0."),
    Measure("Último análisis llegado", f"VAR h = CALCULATE ( MAX ( fact_hour_lab[hour_key] ), NOT ISBLANK ( fact_hour_lab[silica_pct] ), {_LAB_FRESH} )\n"
                                       "    RETURN CALCULATE ( SELECTEDVALUE ( fact_hour_lab[silica_pct] ), fact_hour_lab[hour_key] = h )", DECIMAL_2,
            "Sílice del último análisis nuevo que llegó dentro de las fechas elegidas; el segmentador de horizonte no lo filtra."),
    Measure("Horas sin estimación", 'CALCULATE ( COUNTROWS ( fact_estimate ), fact_estimate[status] = "missing_inputs" )', INTEGER, "Estimaciones que no se pudieron emitir por falta de entradas."),
    Measure("Análisis frescos (%)", f"DIVIDE ( CALCULATE ( COUNTROWS ( fact_hour_lab ), {_LAB_FRESH} ), CALCULATE ( COUNTROWS ( fact_hour_lab ), NOT ISBLANK ( fact_hour_lab[silica_pct] ) ) )",
            PERCENT, "Parte de los análisis llegados que son nuevos (no repetidos ni interpolados)."),
    Measure("Horas interpoladas", "SUM ( fact_data_quality[interpolated] )", INTEGER, "Análisis interpolados que ya llegaron, en los días elegidos."),
    Measure("Horas repetidas", "SUM ( fact_data_quality[held] )", INTEGER, "Análisis repetidos (sin análisis nuevo) que ya llegaron, en los días elegidos."),
    Measure("Media del sensor", "AVERAGE ( fact_hour_process[mean] )", DECIMAL_2, "Media del sensor en las horas y los sensores elegidos; la fuente no dice la unidad."),
    Measure("MAE en la prueba", f"CALCULATE ( SELECTEDVALUE ( fact_method_metrics[mae] ), {_SEALED_TEST} )", DECIMAL_3,
            "Error absoluto medio de un método en un horizonte, en la prueba y con la configuración sellada (si no, una fila posterior al sello vaciaría la cifra)."),
    Measure("Es la base más fuerte", f"CALCULATE ( SELECTEDVALUE ( fact_method_metrics[is_b_star] ), {_SEALED_TEST} )", TEXT_FORMAT,
            "Verdadero si el método es B*, la base más fuerte de su horizonte (se elige en V1)."),
    Measure("Sensores con asociación estable", "CALCULATE ( COUNTROWS ( fact_sensitivity ), fact_sensitivity[passes] = TRUE () )", INTEGER,
            "Sensores que pasan la compuerta de estabilidad: una asociación del modelo, no una receta."),
    Measure("Veredicto", 'CALCULATE ( SELECTEDVALUE ( fact_evaluation_summary[verdict_es] ), fact_evaluation_summary[seal_state] = "sealed" )', TEXT_FORMAT,
            "Veredicto de un criterio con la configuración sellada."),
    Measure("Semiancho del rango", "SELECTEDVALUE ( dim_model[half_width] )", DECIMAL_3, "Semiancho del rango del 80 % del modelo de un horizonte, calibrado en V2 (% de sílice)."),
    Measure("Última fecha de cálculo", 'CALCULATE ( MAX ( dim_pipeline_run[as_of] ), dim_pipeline_run[status] = "ok" )', DATETIME_FORMAT, "Instante de cálculo de la última corrida terminada bien."),
    Measure("Reglas bloqueantes fallidas", 'CALCULATE ( COUNTROWS ( fact_validation ), fact_validation[severity] = "bloqueante", fact_validation[status] = "falla" )', INTEGER,
            "Resultados de reglas bloqueantes que fallaron, en las corridas cargadas."),
)

NOT_FILTERED_BY_HORIZON = " (no lo filtra el horizonte)"
NOT_FILTERED_BY_DATE = " (no lo filtra la fecha)"
_HOUR = "dim_hour[hour]"
_OUR_ESTIMATE = ("fact_estimate[estimate]", "fact_estimate[low]", "fact_estimate[high]", "fact_hour_lab[silica_pct]", "fact_hour_lab[lab_state]", "fact_estimate[persistence]")
PAGES: tuple[Page, ...] = (
    Page("Sílice estimada y laboratorio", (
        Visual("slicer", "Fecha", ("dim_hour[date]",), 0, 0, 6, 1),
        Visual("slicer", "Horizonte", ("dim_horizon[horizon_es]",), 6, 0, 6, 1),
        Visual("card", "Última estimación", ("[Última estimación]",), 0, 1, 2, 1),
        Visual("card", "Último análisis llegado" + NOT_FILTERED_BY_HORIZON, ("[Último análisis llegado]",), 2, 1, 2, 1),
        Visual("card", "MAE del modelo", ("[MAE del modelo]",), 4, 1, 2, 1),
        Visual("card", "MAE de la persistencia", ("[MAE de la persistencia]",), 6, 1, 2, 1),
        Visual("card", "Cobertura del rango", ("[Cobertura del rango]",), 8, 1, 2, 1),
        Visual("card", "Horas sin estimación", ("[Horas sin estimación]",), 10, 1, 2, 1),
        Visual("lineChart", "Sílice estimada con su rango, análisis y persistencia", (_HOUR, *_OUR_ESTIMATE), 0, 2, 12, 7),
    )),
    Page("Horizontes y reglas", (
        Visual("card", "MAE de la base más fuerte (seguimiento)", ("[MAE de la base más fuerte]",), 0, 0, 4, 1),
        Visual("card", "Modelo menos persistencia (seguimiento)", ("[Modelo menos persistencia]",), 4, 0, 4, 1),
        Visual("card", "Sesgo del modelo (seguimiento)", ("[Sesgo del modelo]",), 8, 0, 4, 1),
        Visual("barChart", "MAE por horizonte", ("dim_horizon[horizon_es]", "dim_method[method_es]", "fact_method_metrics[mae]"), 0, 1, 6, 4),
        Visual("table", "MAE en V1, V2 y la prueba", ("fact_method_metrics[scope]", "dim_horizon[horizon_es]", "dim_method[method_es]", "fact_method_metrics[mae]"), 6, 1, 6, 4),
        Visual("table", "En la prueba: el intervalo de la diferencia con B*", ("dim_horizon[horizon_es]", "dim_method[method_es]", "[MAE en la prueba]", "[Es la base más fuerte]",
                                                                           "fact_method_metrics[ci_low_vs_b_star]", "fact_method_metrics[ci_high_vs_b_star]"), 0, 5, 7, 4),
        Visual("lineChart", "MAE por semana de la prueba", ("fact_weekly_mae[test_week]", "fact_weekly_mae[mae]", "dim_method[method_es]"), 7, 5, 5, 4),
    )),
    Page("Variables de la planta", (
        Visual("slicer", "Fecha", ("dim_hour[date]",), 0, 0, 6, 1),
        Visual("slicer", "Sensor", ("dim_sensor[name_es]",), 6, 0, 6, 1),
        Visual("lineChart", "Medias horarias de cada sensor en el día elegido", (_HOUR, "dim_sensor[name_es]", "[Media del sensor]"), 0, 1, 6, 8),
        Visual("card", "Sensores con asociación estable" + NOT_FILTERED_BY_DATE, ("[Sensores con asociación estable]",), 6, 1, 6, 1),
        Visual("table", "Compuerta de estabilidad: importancias, signo y asociación" + NOT_FILTERED_BY_DATE,
               ("dim_sensor[name_es]", "fact_sensitivity[importance_v1]", "fact_sensitivity[importance_v2]", "fact_sensitivity[sign_stable]", "fact_sensitivity[passes]",
                "fact_sensitivity[label_es]"), 6, 2, 6, 3),
        Visual("lineChart", "Asociación del modelo, no una receta: dependencia parcial" + NOT_FILTERED_BY_DATE,
               ("fact_pd_curve[grid_value]", "fact_pd_curve[mean_estimate]", "dim_sensor[name_es]"), 6, 5, 6, 4),
    )),
    Page("Validación del modelo", (
        Visual("table", "Criterios C01-C10", ("fact_evaluation_summary[criterion_id]", "fact_evaluation_summary[name_es]", "fact_evaluation_summary[value]",
                                              "fact_evaluation_summary[threshold_es]", "fact_evaluation_summary[seen_by_research]", "fact_evaluation_summary[seen_by_planner]",
                                              "[Veredicto]"), 0, 0, 7, 3),
        Visual("table", "Semiancho del rango del 80 % por horizonte", ("dim_model[model_key]", "dim_model[horizon_key]", "[Semiancho del rango]", "dim_model[b_star]", "dim_model[seal_state]"),
               7, 0, 5, 3),
        Visual("table", "Candidatos de cada horizonte, con su error en V1", ("dim_horizon[horizon_es]", "fact_selection[family]", "fact_selection[feature_set]", "fact_selection[target]",
                                                                             "fact_selection[min_samples_leaf]", "fact_selection[mae_v1]", "fact_selection[chosen]"), 0, 3, 6, 3),
        Visual("table", "Latencias, reajuste y todas las horas (informativo)", ("fact_variants[variant_es]", "fact_variants[horizon_key]", "fact_variants[method_key]", "fact_variants[mae]",
                                                                               "fact_variants[hours]", "fact_variants[ci_low]", "fact_variants[ci_high]"), 6, 3, 6, 3),
        Visual("table", "Demostración de la fuga: bloques, partición aleatoria y hierro del concentrado", ("fact_leakage[check_es]", "fact_leakage[mae]", "fact_leakage[r2]",
                                                                                                          "fact_leakage[note_es]"), 0, 6, 12, 3),
    )),
    Page("Calidad de datos y corridas", (
        Visual("card", "Análisis frescos (%)", ("[Análisis frescos (%)]",), 0, 0, 2, 1),
        Visual("card", "Horas interpoladas", ("[Horas interpoladas]",), 2, 0, 2, 1),
        Visual("card", "Horas repetidas", ("[Horas repetidas]",), 4, 0, 2, 1),
        Visual("card", "Reglas bloqueantes fallidas", ("[Reglas bloqueantes fallidas]",), 6, 0, 3, 1),
        Visual("card", "Última fecha de cálculo", ("[Última fecha de cálculo]",), 9, 0, 3, 1),
        Visual("barChart", "Análisis llegados por día: nuevos, repetidos e interpolados", ("dim_date[date]", "fact_data_quality[fresh]", "fact_data_quality[held]", "fact_data_quality[interpolated]"),
               0, 1, 8, 4),
        Visual("table", "Horas sin datos por día (el hueco de marzo)", ("dim_date[date]", "fact_data_quality[missing_hours]", "fact_data_quality[partial_hours]",
                                                                      "fact_data_quality[stuck_sensor_hours]"), 8, 1, 4, 4),
        Visual("table", "Reglas de validación", ("fact_validation[rule_id]", "fact_validation[name_es]", "fact_validation[severity]", "fact_validation[rows_affected]",
                                                 "fact_validation[hours_affected]", "fact_validation[status]"), 0, 5, 6, 4),
        Visual("table", "Corridas", ("dim_pipeline_run[run_key]", "dim_pipeline_run[delivery_id]", "dim_pipeline_run[as_of]", "dim_pipeline_run[status]", "dim_pipeline_run[estimates_issued]",
                                     "dim_pipeline_run[message]"), 6, 5, 6, 4),
    )),
)
MODEL = SemanticModel(TABLES, RELATIONSHIPS, MEASURES, PAGES)


def arrow_schema(table: Table) -> pa.Schema:
    """The Arrow schema of a table: its columns in order with their types."""
    return pa.schema([pa.field(c.name, ARROW_TYPES[c.dtype]) for c in table.columns])


# --- the static checks that stand in for running the measures (item 6 of the risks: no DAX runs anywhere in the project) -------------------------------------------------------------------

_COLUMN_REF = re.compile(r"(?<![\w'])([A-Za-z_]\w*)\[(\w+)\]")
_MEASURE_REF = re.compile(r"(?<![\w\]'])\[([^\[\]]+)\]")
_FUNCTION_CALL = re.compile(r"\b([A-Z][A-Z0-9.]*)(?=\s*\()")
_LITERAL_COMPARISON = re.compile(r'\b([a-z_]\w*)\[(\w+)\]\s*=\s*"([^"]*)"')
_REMOVES_FILTERS = re.compile(r"\b(ALL|ALLEXCEPT|ALLSELECTED|REMOVEFILTERS|CROSSFILTER|USERELATIONSHIP|KEEPFILTERS)\b")
DAX_FUNCTIONS = frozenset({"CALCULATE", "COUNTROWS", "AVERAGE", "AVERAGEX", "DIVIDE", "MAX", "SELECTEDVALUE", "SUM", "NOT", "ISBLANK", "TRUE"})


def dax_column_refs(dax: str) -> set[tuple[str, str]]:
    """The ``table[column]`` references of a DAX expression."""
    return set(_COLUMN_REF.findall(dax))


def dax_measure_refs(dax: str) -> set[str]:
    """The ``[Measure]`` references of a DAX expression: a bracket not attached to a table."""
    return set(_MEASURE_REF.findall(dax))


def visual_tables(model: SemanticModel, visual: Visual) -> set[str]:
    """The tables a visual reads: those of its columns and, through the DAX of its measures and of the measures they name, those the measures name by a column or whole."""
    found: set[str] = set()
    pending, seen = list(visual.fields), set()
    while pending:
        field = pending.pop()
        if field.startswith("["):
            name = field[1:-1]
            measure = next((m for m in model.measures if m.name_es == name), None)
            if measure is not None and name not in seen:
                seen.add(name)
                found |= {t.name for t in model.tables if re.search(rf"\b{t.name}\b", measure.dax)}
                pending += [f"[{n}]" for n in dax_measure_refs(measure.dax)]
        else:
            found.add(field.split("[")[0])
    return {t for t in found if any(table.name == t for table in model.tables)}


def _field_problem(model: SemanticModel, field: str) -> str | None:
    """Why the field of a visual does not resolve, or None."""
    if field.startswith("["):
        return None if any(f"[{m.name_es}]" == field for m in model.measures) else f"la medida {field} no existe"
    match = re.fullmatch(r"([A-Za-z_]\w*)\[(\w+)\]", field)
    if match is None:
        return f"el campo {field!r} no es una columna ni una medida"
    table, column = match.groups()
    return None if any(t.name == table and column in t.column_names for t in model.tables) else f"la columna {field} no existe"


def _measure_problems(model: SemanticModel) -> list[str]:
    problems: list[str] = []
    names = [m.name_es for m in model.measures]
    problems += [f"la medida [{n}] está repetida" for n in sorted({n for n in names if names.count(n) > 1})]
    columns = {t.name: {c.name: c for c in t.columns} for t in model.tables}
    uses: dict[str, set[str]] = {}
    for m in model.measures:
        label = f"[{m.name_es}]"
        if m.dax.count("(") != m.dax.count(")"):
            problems.append(f"{label}: paréntesis sin cerrar en el DAX")
        if m.dax.count('"') % 2:
            problems.append(f"{label}: comillas sin cerrar en el DAX")
        problems += [f"{label}: {t}[{c}] no existe" for t, c in sorted(dax_column_refs(m.dax)) if c not in columns.get(t, {})]
        problems += [f"{label}: {w} no es una tabla" for w in sorted(set(re.findall(r"\b(?:dim|fact)_\w+", m.dax)) - set(columns))]
        problems += [f"{label}: la función {f} no es de las que usa el plan" for f in sorted(set(_FUNCTION_CALL.findall(m.dax)) - DAX_FUNCTIONS)]
        uses[m.name_es] = dax_measure_refs(m.dax)
        problems += [f"{label}: la medida [{r}] no existe o es ella misma" for r in sorted(uses[m.name_es]) if r not in names or r == m.name_es]
        for table, column, literal in _LITERAL_COMPARISON.findall(m.dax):
            if column in columns.get(table, {}) and literal not in columns[table][column].description_es:
                problems.append(f"{label}: compara {table}[{column}] con '{literal}', que la columna no toma")
        problems += [f"{label}: {w} quita los filtros de los segmentadores" for w in sorted(set(_REMOVES_FILTERS.findall(m.dax)))]
        if not m.format_string or not m.description_es:
            problems.append(f"{label}: necesita un formato y una descripción")

    def circle(name: str, path: tuple[str, ...]) -> bool:
        return name in path or any(circle(n, (*path, name)) for n in uses.get(name, ()) if n in uses and n != name)

    problems += [f"las medidas [{n}] se llaman en círculo" for n in sorted(uses) if any(circle(r, (n,)) for r in uses[n] if r in uses and r != n)]
    return problems


def _page_problems(model: SemanticModel) -> list[str]:
    problems: list[str] = []
    titles = [p.name_es for p in model.pages]
    problems += [f"página repetida: {t}" for t in sorted({t for t in titles if titles.count(t) > 1})]
    related = {(r.dim_table, r.fact_table) for r in model.relationships}
    kinds = {t.name: t.kind for t in model.tables}
    for page in model.pages:
        if not page.visuals:
            problems.append(f"{page.name_es}: sin visuales")
        taken: dict[tuple[int, int], str] = {}
        for v in page.visuals:
            label = f"{page.name_es}: {v.title_es}"
            problems += [f"{label}: {why}" for field in v.fields if (why := _field_problem(model, field)) is not None]
            if v.kind == "slicer" and (len(v.fields) != 1 or v.fields[0].startswith("[")):
                problems.append(f"{label}: un segmentador usa una sola columna")
            tables = visual_tables(model, v)
            dims, facts = sorted(t for t in tables if kinds[t] == "dimension"), sorted(t for t in tables if kinds[t] == "fact")
            if len(facts) >= 2 and not dims:
                problems.append(f"{label}: dos hechos sin una dimensión que los una")
            if len(dims) >= 2 and not facts:
                problems.append(f"{label}: dos dimensiones sin un hecho que las una")
            problems += [f"{label}: {d} y {f} no se unen por ninguna relación" for d in dims for f in facts if (d, f) not in related]
            if v.w < 1 or v.h < 1 or v.x < 0 or v.y < 0 or v.x + v.w > PAGE_COLUMNS or v.y + v.h > PAGE_ROWS:
                problems.append(f"{label}: sale de la grilla de {PAGE_COLUMNS} x {PAGE_ROWS}")
                continue
            cells = [(cx, cy) for cx in range(v.x, v.x + v.w) for cy in range(v.y, v.y + v.h)]
            clash = next((taken[c] for c in cells if c in taken), None)
            if clash is not None:
                problems.append(f"{label}: se superpone con {clash}")
            taken.update({c: v.title_es for c in cells})
    return problems


def validate_model(model: SemanticModel) -> list[str]:
    """What is incoherent in `model` (empty when nothing is): unique table names, known types, keys among the columns, relationships between a dimension's whole key
    and a fact's column of the same type, one to many, single direction and active; then the measures (``_measure_problems``) and the pages (``_page_problems``)."""
    problems: list[str] = []
    names = [t.name for t in model.tables]
    if len(set(names)) != len(names):
        problems.append("hay tablas repetidas")
    by_name = {t.name: t for t in model.tables}
    for table in model.tables:
        columns = {c.name: c for c in table.columns}
        if len(columns) != len(table.columns):
            problems.append(f"{table.name} repite una columna")
        problems += [f"{table.name}[{c.name}] tiene un tipo desconocido {c.dtype}" for c in table.columns if c.dtype not in ARROW_TYPES]
        problems += [f"la clave {k} de {table.name} no es una columna" for k in table.key if k not in columns]
    for r in model.relationships:
        dim, fact = by_name.get(r.dim_table), by_name.get(r.fact_table)
        if dim is None or fact is None or dim.kind != "dimension" or fact.kind != "fact":
            problems.append(f"{r.rel_id} no une una dimensión con un hecho")
            continue
        if dim.key != (r.dim_column,):
            problems.append(f"{r.rel_id} no usa la clave entera de {dim.name}")
        dim_col = next((c for c in dim.columns if c.name == r.dim_column), None)
        fact_col = next((c for c in fact.columns if c.name == r.fact_column), None)
        if dim_col is None or fact_col is None or dim_col.dtype != fact_col.dtype:
            problems.append(f"{r.rel_id}: {r.fact_table}[{r.fact_column}] no es una columna del tipo de {r.dim_table}[{r.dim_column}]")
        if (r.cardinality, r.cross_filter, r.active) != ("one_to_many", "single", True):
            problems.append(f"{r.rel_id} no es uno a varios, de filtro unidireccional y activa")
    return problems + _measure_problems(model) + _page_problems(model)
