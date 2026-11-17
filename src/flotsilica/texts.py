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


def stability_verdict(passed: bool, passing: list[str], kept: list[str], computed: bool) -> str:
    if not computed:
        return "No se puede calcular: la compuerta de sensibilidades no se calculó en el lanzamiento."
    if not passing:
        return "Ningún sensor pasa la compuerta de estabilidad: sin asociación estable."
    if passed:
        return f"{len(kept)} de {len(passing)} sensores que pasan la compuerta conservan el signo de su dependencia parcial en la prueba: {', '.join(kept)}."
    return f"{len(passing)} sensores pasan la compuerta, pero ninguno conserva el signo de su dependencia parcial en la prueba."


def informative_verdict(hours: int) -> str:
    return f"Informativo, sin umbral: el MAE del modelo, de la persistencia y de la base más fuerte por semana y las variantes de latencia y de reajuste, escritos en el sello ({hours} horas evaluadas)."


def pending_reason(ready: str, as_of: str) -> str:
    return (f"La prueba se evalúa una sola vez, cuando llega el último análisis de la prueba ({ready}); esta corrida es la del {as_of}. "
            "Las cifras que se muestran son de la validación (V1 y V2), no de la prueba.")
