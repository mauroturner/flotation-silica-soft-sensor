"""The semantic model of the Power BI report: the single source of its tables and relationships (RF21, AC25; D25; plan, section 19). Adapted from project 04's
``dashboard/semantic_model.py`` without the privacy layer (D43).

Tables with their columns (type, description, unit) and relationships (all one to many, single direction, active) live here; the Arrow schema of every Parquet file
and, later, the data dictionary and the HTML design come from this module. Names of tables, columns and files are in English; descriptions and labels in Spanish
(RNF13). The measures (DAX) and the five pages of the report come with U14.
"""

from __future__ import annotations

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
class SemanticModel:
    tables: tuple[Table, ...]
    relationships: tuple[Relationship, ...]

    def table(self, name: str) -> Table:
        return next(t for t in self.tables if t.name == name)


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
MODEL = SemanticModel(TABLES, RELATIONSHIPS)


def arrow_schema(table: Table) -> pa.Schema:
    """The Arrow schema of a table: its columns in order with their types."""
    return pa.schema([pa.field(c.name, ARROW_TYPES[c.dtype]) for c in table.columns])


def validate_model(model: SemanticModel) -> list[str]:
    """What is incoherent in `model` (empty when nothing is): unique table names, known types, keys among the columns, relationships between a dimension's whole key
    and a fact's column of the same type, one to many, single direction and active."""
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
    return problems
