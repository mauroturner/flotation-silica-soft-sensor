"""The words of the results (RF19, D16; plan, section 16): the one place that has the text of a criterion, of a method and of a verdict, so that the summary,
the README, the model card, the dashboard and the site say the same thing in the same way.

A verdict is a sentence made from the numbers of its criterion: it says whether the model beats the baseline, loses to it or ties with it (a tie never
passes), and where. ``es`` writes a number as the Spanish text shows it: a comma for the decimals, a point for the thousands and the minus sign of
typography. The texts of the sensitivities (U12) come here too.
"""

from __future__ import annotations

import math
from typing import NamedTuple


class CriterionText(NamedTuple):
    name_es: str
    threshold_es: str
    seen_by_research: str
    seen_by_planner: str


# id: name, threshold, what the research saw, what the planner saw (requirements.md, 8.1; D16)
CRITERIA: dict[str, CriterionText] = {
    "C01": CriterionText("H0 frente a la persistencia", "MAE(modelo) < MAE(persistencia)", "sí", "sí"),
    "C02": CriterionText("H0 fuera del ruido frente a la base más fuerte", "límite superior del intervalo del 95 % de MAE(modelo) − MAE(B*) < 0", "sí", "sí"),
    "C03": CriterionText("H1 fuera del ruido frente a la base más fuerte", "límite superior del intervalo del 95 % de MAE(modelo) − MAE(B*) < 0", "no", "sí"),
    "C04": CriterionText("H2 fuera del ruido frente a la base más fuerte", "límite superior del intervalo del 95 % de MAE(modelo) − MAE(B*) < 0", "no", "sí"),
    "C05": CriterionText("Cobertura del rango de H0", "proporción de horas con el análisis dentro del rango del 80 % entre {low} y {high}", "no", "en parte"),
    "C06": CriterionText("Sesgo de H0", "|media(modelo − análisis)| ≤ {max_bias}", "no", "sí"),
    "C07": CriterionText("Los sensores solos frente a la media", "límite superior del intervalo del 95 % de MAE(mejor solo con sensores) − MAE(B0) < 0", "en parte", "sí"),
    "C08": CriterionText("Los sensores agregan a la historia del laboratorio",
                         "límite superior del intervalo del 95 % de MAE(mejor con sensores) − MAE(mejor solo con laboratorio) < 0", "en parte", "sí"),
    "C09": CriterionText("Sensibilidad estable", "al menos un sensor pasa la compuerta y conserva el signo de su dependencia parcial en la prueba", "sí", "sí"),
    "C10": CriterionText("Por semana y variantes (informativo)", "sin umbral: que esté escrito y sea consistente", "no", "sí, en V1 y V2"),
}

METHODS_ES: dict[str, str] = {
    "model": "Modelo", "b_star": "Base más fuerte (B*)", "b0_train_mean": "Media del entrenamiento (B0)", "b1_persistence": "Persistencia (B1)",
    "b2_rolling": "Media de los últimos análisis (B2)", "b3_ridge_sensors": "Ridge sobre sensores (B3)", "best_sensors_only": "Mejor solo con sensores",
    "best_lab_only": "Mejor solo con laboratorio", "best_with_sensors": "Mejor con sensores y laboratorio",
}
# The labels of the star model (U13, plan section 19): the names that the tables of ``outputs/powerbi`` and the report show, in Spanish.
HORIZON_LABELS_ES = {0: "La hora que cerró", 1: "La hora siguiente", 2: "Dentro de dos horas"}      # from the hour that closed: H1 is its next hour, H2 two hours after
METHOD_KINDS_ES = {"model": "modelo", "b0_train_mean": "regla", "b1_persistence": "regla", "b2_rolling": "regla", "b3_ridge_sensors": "comparación",
                   "best_sensors_only": "comparación", "best_lab_only": "comparación", "best_with_sensors": "comparación"}
BLOCKS_ES = {"train": "Entrenamiento", "purge_1": "Purga entre entrenamiento y V1", "valid_v1": "Validación V1", "purge_v": "Purga entre V1 y V2", "valid_v2": "Validación V2",
             "purge_2": "Purga entre V2 y la prueba", "test": "Prueba", "outside": "Fuera de los bloques"}
LAB_STATES_ES = {"fresh": "Análisis nuevo", "interpolated": "Interpolado", "held": "Repetido", "pending": "Llega más tarde", "missing": "Sin datos"}
TARGETS_ES = {"level": "El nivel de la sílice", "change": "El cambio respecto del último análisis"}
TRAINED_ON_ES = "Entrenamiento y V1"
VARIANTS_ES = {"latency_3": "Con 3 horas de espera del laboratorio", "latency_4": "Con 4 horas de espera del laboratorio", "refit_all": "Reajuste con toda la validación",
               "all_hours": "Todas las horas con análisis, nuevo o no"}
SENSOR_UNIT_ES = "sin unidad en la fuente"
SENSOR_GROUPS_ES = {"reactivos": ("starch_flow", "amina_flow"), "pulpa": ("ore_pulp_flow", "ore_pulp_ph", "ore_pulp_density"),
                    "aire": tuple(f"air_flow_0{k}" for k in range(1, 8)), "nivel": tuple(f"level_0{k}" for k in range(1, 8))}
SENSORS_ES = {"starch_flow": "Flujo de almidón", "amina_flow": "Flujo de amina", "ore_pulp_flow": "Flujo de pulpa de mineral", "ore_pulp_ph": "pH de la pulpa",
              "ore_pulp_density": "Densidad de la pulpa", **{f"air_flow_0{k}": f"Flujo de aire de la columna {k}" for k in range(1, 8)},
              **{f"level_0{k}": f"Nivel de la columna {k}" for k in range(1, 8)}}
MONTHS_ES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")
WEEKDAYS_ES = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")      # ISO order: Monday is 1

# What the site says about the API of the estimate (plan, sections 18 and 21): the endpoint and, in a sentence each, what it takes and what it gives. The API itself comes with its unit.
API_ENDPOINT = "POST /estimate"
API_INPUTS_ES = ("Las lecturas de las 19 variables de la planta de la hora que cerró, los últimos análisis frescos del laboratorio con la hora de su muestra "
                 "y el instante de emisión, en punto.")
API_OUTPUTS_ES = ("La estimación de la hora que cerró y de las dos siguientes, cada una con su rango del 80 %, la persistencia, la versión del modelo "
                  "y la huella de la configuración sellada.")


HORIZONS_ES = {0: "la hora que cerró (H0)", 1: "la hora que empieza (H1)", 2: "la hora siguiente (H2)"}
WHERE_ES = {0: "en la hora que cerró", 1: "en la hora que empieza", 2: "en la hora siguiente"}


def es(value: float | None, digits: int = 3) -> str:
    """A number as the Spanish text shows it: a comma for the decimals, a point for the thousands and «−» for the minus sign; «sin dato» if there is none."""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "sin dato"
    text = f"{value:,.{digits}f}"
    if text.startswith("-") and not any(ch in "123456789" for ch in text):
        text = text[1:]                         # -0.001 at two decimals is 0,00, not −0,00
    return text.replace(",", "§").replace(".", ",").replace("§", ".").replace("-", "−")


def threshold_of(criterion_id: str, **numbers: float) -> str:
    """The threshold of a criterion as the summary shows it (C05 and C06 carry the sealed limits)."""
    return CRITERIA[criterion_id].threshold_es.format(**{k: es(v, 2) for k, v in numbers.items()})


def interval_es(low: float | None, high: float | None) -> str:
    return f"la diferencia va de {es(low, 2)} a {es(high, 2)}"


def versus(criterion_id: str, passed: bool, *, a: float | None, b: float | None, low: float | None = None, high: float | None = None,
           who: str = "", horizon: int = 0) -> str:
    """The verdict of C01 to C04, C07 and C08: the model against another method, with the means of both and, if it has one, the interval of the 95 % of the
    difference of MAE. A tie does not pass."""
    where = WHERE_ES.get(horizon, "")
    verb = "supera" if passed else "no supera"
    if criterion_id == "C01":
        return f"El modelo {verb} a la persistencia {where}: MAE {es(a, 2)} frente a {es(b, 2)}."
    if criterion_id in ("C02", "C03", "C04"):
        return (f"El modelo {verb} a {who} {where} fuera del ruido: MAE {es(a, 2)} frente a {es(b, 2)}; {interval_es(low, high)}.")
    if criterion_id == "C07":
        return (f"Los sensores solos {'superan' if passed else 'no superan'} a la media del entrenamiento: MAE {es(a, 2)} frente a {es(b, 2)}; "
                f"{interval_es(low, high)}.")
    return (f"Con sensores, el modelo {'agrega' if passed else 'no agrega'} a la historia del laboratorio: MAE {es(a, 2)} frente a {es(b, 2)}; "
            f"{interval_es(low, high)}.")


def coverage_verdict(passed: bool, coverage: float | None, low: float, high: float) -> str:
    return (f"El rango del 80 % {'cumple' if passed else 'no cumple'} {WHERE_ES[0]}: cubre {es(coverage)} de las horas, y se pedía entre {es(low, 2)} y {es(high, 2)}.")


def bias_verdict(passed: bool, bias: float | None, max_bias: float) -> str:
    direction = "de más" if (bias or 0) > 0 else "de menos"
    return (f"El sesgo {WHERE_ES[0]} {'cumple' if passed else 'no cumple'}: el modelo estima {es(abs(bias) if bias is not None else None)} {direction} en promedio, "
            f"y se pedía a lo sumo {es(max_bias, 2)}.")


ASSOCIATION_ES = "asociación del modelo"
NO_ASSOCIATION_ES = "sin asociación estable"
# what no text about a sensitivity may say (D20): that a sensor is the cause of the silica or what someone should do with the air or the reagents
FORBIDDEN_ES = ("causa", "provoca", "controla", "ajustar el", "subir el", "bajar el", "acción", "acciones")
NEAR_CHARACTERS = 70


def sensor_line(sensor: str, *, passes: bool, sign: int, kept: bool | None) -> str:
    """The sentence about one sensor: a stable association of the model (with its direction and, after the test, whether it keeps it) or no stable association."""
    if not passes:
        return f"{sensor}: {NO_ASSOCIATION_ES}."
    tail = {True: " y conserva el signo en la prueba", False: " pero no conserva el signo en la prueba", None: ""}[kept]
    return f"{sensor}: {ASSOCIATION_ES}; la estimación {'sube' if sign > 0 else 'baja'} cuando el valor del sensor sube{tail}."


def gate_summary(passing: list[str], computed: bool) -> str:
    """What the gate of the launch found, in one sentence."""
    if not computed:
        return "La compuerta de sensibilidades no se calculó."
    if not passing:
        return f"Ningún sensor pasa la compuerta de estabilidad: {NO_ASSOCIATION_ES}. Las sensibilidades son {ASSOCIATION_ES}, no una receta."
    return f"Pasan la compuerta de estabilidad como {ASSOCIATION_ES}: {', '.join(passing)}."


def stability_verdict(passed: bool, passing: list[str], kept: list[str], computed: bool) -> str:
    if not computed:
        return "No se puede calcular: la compuerta de sensibilidades no se calculó en el lanzamiento."
    if not passing:
        return f"Ningún sensor pasa la compuerta de estabilidad: {NO_ASSOCIATION_ES}."
    if passed:
        return f"{len(kept)} de {len(passing)} sensores que pasan la compuerta conservan el signo de su dependencia parcial en la prueba: {', '.join(kept)}."
    return f"{len(passing)} sensores pasan la compuerta, pero ninguno conserva el signo de su dependencia parcial en la prueba."


def sensitivity_problems(text: str) -> list[str]:
    """What is wrong in `text` if it is about a sensor or a sensitivity: each forbidden word (``FORBIDDEN_ES``) that is within ``NEAR_CHARACTERS`` of the name of a sensor or
    of the words «sensor», «sensibilidad» or «dependencia parcial». A text that has none of those near is not about a sensitivity, and is not judged."""
    import re

    from flotsilica.schema import SENSORS

    lowered, problems = text.lower(), []
    anchors = [(m.start(), m.group()) for pattern in (*(re.escape(sensor) for sensor in SENSORS), r"sensor\w*", r"sensibilidad\w*", r"dependencia parcial")
               for m in re.finditer(pattern, lowered)]
    for word in FORBIDDEN_ES:
        for found in re.finditer(r"\b" + re.escape(word), lowered):
            near = [name for position, name in anchors if abs(position - found.start()) <= NEAR_CHARACTERS]
            if near:
                problems.append(f"«{word}» cerca de «{near[0]}»")
    return problems


def informative_verdict(hours: int) -> str:
    return f"Informativo, sin umbral: el MAE del modelo, de la persistencia y de la base más fuerte por semana y las variantes de latencia y de reajuste, escritos en el sello ({hours} horas evaluadas)."


def pending_reason(ready: str, as_of: str) -> str:
    return (f"La prueba se evalúa una sola vez, cuando llega el último análisis de la prueba ({ready}); esta corrida es la del {as_of}. "
            "Las cifras que se muestran son de la validación (V1 y V2), no de la prueba.")


# --- the command line (U18, plan section 22): what ``python -m flotsilica`` says when a command is refused before anything is written ----------------------------------

NOTHING_WRITTEN = "No se escribió nada."
NO_PENDING_DELIVERIES = "No hay entregas pendientes: nada que correr."


def only_with_from() -> str:
    return f"--only y --from no se combinan: elija las tareas o desde cuál seguir. {NOTHING_WRITTEN}"


def run_key_needs_a_selection() -> str:
    return f"--run-key necesita --only o --from: una corrida completa nueva elige su propia clave. {NOTHING_WRITTEN}"


def a_new_run_starts_at(first: str, got: str) -> str:
    return (f"una corrida nueva empieza por {first}, no por {got}: indique con --run-key la corrida que continúa (sin ella no hay resultado de las tareas anteriores). "
            f"{NOTHING_WRITTEN}")


def runs_count(count: int) -> str:
    return "1 corrida" if count == 1 else f"{count} corridas"


def docs_sync_without_readme(readme: object, summary: object) -> str:
    return (f"docs-sync copia el resumen de resultados en el README de la configuración, {readme}, y ese archivo no existe: el modo rápido no tiene README, "
            f"y su resumen queda en {summary}. {NOTHING_WRITTEN}")


def docs_sync_without_summary(summary: object) -> str:
    return f"no existe {summary}: corra la tarea report antes de docs-sync (python -m flotsilica task report). {NOTHING_WRITTEN}"


def figures_refused(problem: object) -> str:
    return f"{problem}. No se escribió ninguna figura."


def fixture_outside_the_project(path: object, root: object) -> str:
    return (f"{path} sale de la carpeta del proyecto ({root}); use una ruta absoluta si el destino está fuera a propósito (una relativa se toma de la carpeta del proyecto, "
            f"no del directorio de trabajo). {NOTHING_WRITTEN}")


def fixture_without_tests_tree(root: object) -> str:
    return (f"make-fixture usa el generador de tests/fixtures/make_fixture.py, y {root} no tiene la carpeta tests (por ejemplo, la imagen de Airflow solo trae las "
            f"dependencias): córralo desde un clon completo del proyecto. {NOTHING_WRITTEN}")


def fixture_written(path: object, rows: int, hours: int, seed: int, signal: str) -> str:
    return f"escribí {path}: {rows} filas en {hours} horas (semilla {seed}, señal {signal})"


# --- the estimation API and ``serve`` (U19, plan section 18): what a refusal says, in the body of a 422 and on the terminal ------------------------------------------

NOTHING_ESTIMATED = "No se estimó nada."


def api_refusal(code: str, *, field: str | None = None, issue_at: object = None, found: int = 0, minimum: int = 0) -> str:
    """The message of a 422 of ``POST /estimate`` by its code (``api.py``): it names the field and the instants of the request and never a path of this machine."""
    where = "el cuerpo" if field is None else field
    messages = {
        "invalid_request": f"el cuerpo no cumple el formato de la solicitud: los campos que fallan van en la lista «fields». {NOTHING_ESTIMATED}",
        "not_on_the_hour": f"{where} debe ser un instante en punto, sin minutos, segundos ni fracciones. {NOTHING_ESTIMATED}",
        "duplicate_sample_hour": f"{where} repite la hora de la muestra de otro análisis: cada hora tiene un solo análisis. {NOTHING_ESTIMATED}",
        "analysis_after_issue": f"{where} llega después del instante de emisión, {issue_at}: en ese instante todavía no se conocía. {NOTHING_ESTIMATED}",
        "short_lab_history": f"a {issue_at} habían llegado {found} análisis nuevos y hacen falta al menos {minimum}. {NOTHING_ESTIMATED}",
        "estimate_refused": f"el modelo no pudo dar una estimación finita con estas entradas. {NOTHING_ESTIMATED}",
    }
    return messages[code]


def api_without_seal() -> str:
    return f"no hay sello del lanzamiento: la API solo sirve el modelo sellado, y sin lanzamiento no hay modelo (python -m flotsilica run). {NOTHING_WRITTEN}"


def api_other_configuration() -> str:
    return (f"la configuración actual no es la sellada (otra configuración): la API daría estimaciones distintas de las del flujo. Se vuelve a la configuración sellada o se "
            f"vuelve a lanzar. {NOTHING_WRITTEN}")


def api_warehouse_unreadable(name: str) -> str:
    return f"no se puede abrir el almacén {name} para leerlo: la API lo abre solo para leer el registro del modelo. {NOTHING_WRITTEN}"


def serve_host_refused(host: str, allowed: str) -> str:
    return f"serve solo escucha en {allowed} (D27), no en {host!r}: el servicio no se publica fuera del equipo. {NOTHING_WRITTEN}"


def serve_port_refused(port: int) -> str:
    return f"--port: se esperaba un puerto de 1 a 65535, se recibió {port}. {NOTHING_WRITTEN}"
