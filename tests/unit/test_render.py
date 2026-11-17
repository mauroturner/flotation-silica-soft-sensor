"""The HTML design of the report (U14, AC26; RF22; D25): every page, visual, measure, relationship and Power Query of the specification; nothing loaded from outside and no script; under
2 MB; every text that comes from the data escaped; previews drawn from the exported tables and honest about what they show. No measure ran: the document says so."""

from __future__ import annotations

import dataclasses
import html as html_lib
import re
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from flotsilica.dashboard import render
from flotsilica.dashboard.render import render_design
from flotsilica.dashboard.semantic_model import MODEL, Page, Visual
from flotsilica.ingest import ATTRIBUTION

EVIL = "<script>alert(1)</script>"
EVIL_ATTRIBUTE = '"><img src=x onerror=alert(2)>'


def text_of(html: str) -> str:
    return html_lib.unescape(re.sub(r"<[^>]+>", " ", html))


def _changed(star_files, folder: Path, edits: dict[str, dict[str, object]]) -> Path:
    """A copy of the exported folder in which each table of `edits` has the given columns set to a value in every row."""
    shutil.copytree(star_files.out_dir, folder)
    for table, columns in edits.items():
        frame = pd.read_parquet(folder / f"{table}.parquet")
        for column, value in columns.items():
            frame[column] = value
        frame.to_parquet(folder / f"{table}.parquet", index=False)
    return folder


@pytest.fixture(scope="module")
def evil(star_files, tmp_path_factory) -> str:
    """The same files with text that would run if a page took it as it is, in every column that a preview or a slicer shows."""
    folder = _changed(star_files, tmp_path_factory.mktemp("evil") / "powerbi", {
        "dim_method": {"method_es": EVIL}, "dim_sensor": {"name_es": EVIL_ATTRIBUTE}, "dim_horizon": {"horizon_es": EVIL}, "fact_validation": {"name_es": EVIL},
        "fact_evaluation_summary": {"name_es": EVIL, "threshold_es": EVIL, "verdict_es": EVIL}, "fact_leakage": {"check_es": EVIL, "note_es": EVIL_ATTRIBUTE},
        "fact_sensitivity": {"label_es": EVIL}, "fact_variants": {"variant_es": EVIL}, "dim_pipeline_run": {"message": EVIL, "run_key": EVIL_ATTRIBUTE},
        "dim_model": {"family": EVIL}, "fact_selection": {"feature_set": EVIL}})
    return render_design(MODEL, folder, folder.parent / "evil.html", star_files.run).read_text(encoding="utf-8")


# --- the RED of U14 -----------------------------------------------------------------------------------------------------------


def test_html_has_every_page_and_escapes_data_text(rendered_html, evil, star_files):
    """AC26: every page, visual, measure and relationship is in the document and each table has its query; a method, a sensor, a rule, a criterion or a message that holds markup is
    shown as text, never as markup, in the text of a cell and in an attribute."""
    html = rendered_html.html
    text = text_of(html)
    for number, page in enumerate(MODEL.pages, start=1):
        assert f"Página {number}: {page.name_es}" in text
        for v in page.visuals:
            assert f'aria-label="{html_lib.escape(v.title_es)}"' in html, v.title_es
            assert html_lib.escape(", ".join(v.fields)) in html, v.title_es
    for m in MODEL.measures:
        assert f"{m.name_es} =\n" in text and m.dax in text, m.name_es
    for r in MODEL.relationships:
        assert r.rel_id in text and f"{r.dim_table}[{r.dim_column}]" in text and f"{r.fact_table}[{r.fact_column}]" in text, r.rel_id
    for table in MODEL.tables:
        assert f'Parquet.Document(File.Contents(CarpetaSalidas & "\\{table.name}.parquet"))' in text, table.name
    for markup in ("<script", "<img", '"><img'):
        assert markup not in evil, markup
    assert html_lib.escape(EVIL) in evil and html_lib.escape(EVIL_ATTRIBUTE) in evil
    assert len(re.findall(re.escape(html_lib.escape(EVIL)), evil)) >= 8, "the evil text reaches the page in many previews"
    # every visual has a preview of its own, never the placeholder that says what to do in Power BI
    assert text.count("Se calcula en Power BI") == 0 and html.count('class="visual"') == sum(len(p.visuals) for p in MODEL.pages)


# --- the document ---------------------------------------------------------------------------------------------------------------


def test_nothing_is_loaded_from_outside_there_is_no_script_and_it_weighs_under_2_mb(rendered_html):
    html = rendered_html.html
    assert rendered_html.path.stat().st_size < 2 * 1024 * 1024
    assert "<script" not in html.lower() and "javascript:" not in html.lower() and not re.search(r"\bon[a-z]+=", html)
    for attribute in re.findall(r'(?:src|href)="([^"]+)"', html):
        assert attribute.startswith("#"), attribute
    assert not re.search(r"@import|url\((?!#)|https?://", html), "no stylesheet, font, image or link from outside"
    assert html.startswith('<!doctype html>\n<html lang="es">') and html.count("<html") == 1
    assert b"\r" not in rendered_html.path.read_bytes(), "LF line endings"


def test_it_states_the_run_the_attribution_and_that_no_measure_ran(rendered_html, star_files):
    text = text_of(rendered_html.html)
    assert star_files.run.run_key in text and star_files.run.as_of.isoformat(sep=" ") in text and ATTRIBUTION in text
    assert "Ninguna medida se ejecutó" in text and "Power BI" in text
    assert "Una sensibilidad es una asociación del modelo" in text
    assert re.search(r"SHA-256 de la fuente <code>[0-9a-f]{12}</code>", rendered_html.html)


def test_rendering_twice_gives_the_same_bytes_and_writes_through_the_atomic_write(rendered_html, star_files, tmp_path, monkeypatch):
    again = render_design(MODEL, star_files.out_dir, tmp_path / "again.html", star_files.run)
    assert again.read_bytes() == rendered_html.path.read_bytes()
    written = []
    real = render.write_atomic
    monkeypatch.setattr(render, "write_atomic", lambda path, data: written.append((Path(path), data)) or real(path, data))
    target = render_design(MODEL, star_files.out_dir, tmp_path / "sub" / "third.html", star_files.run)
    assert [p for p, _ in written] == [target] and isinstance(written[0][1], str) and not list(target.parent.glob("*.tmp"))


def test_an_incoherent_model_and_a_missing_folder_write_nothing(star_files, tmp_path):
    broken = dataclasses.replace(MODEL, pages=(*MODEL.pages, Page("Mala", (Visual("card", "x", ("[No existe]",), 0, 0, 1, 1),))))
    with pytest.raises(ValueError, match="incoherente"):
        render_design(broken, star_files.out_dir, tmp_path / "x.html", star_files.run)
    assert not (tmp_path / "x.html").exists()


def test_without_exported_files_the_whole_document_is_still_written_with_empty_previews(star_files, tmp_path):
    path = render_design(MODEL, tmp_path / "nothing", tmp_path / "empty.html", star_files.run)
    html = path.read_text(encoding="utf-8")
    assert html.count('class="visual"') == sum(len(p.visuals) for p in MODEL.pages) and "Sin datos" in html and "<svg" in html


# --- the previews are the exported figures -----------------------------------------------------------------------------------------


def _card(html: str, title: str) -> tuple[str, str]:
    block = html.split(f'aria-label="{html_lib.escape(title)}', 1)[1].split("</section>", 1)[0]       # a title may go on with «(no lo filtra …)»
    return html_lib.unescape(re.search(r'<div class="big">([^<]*)</div>', block).group(1)), html_lib.unescape(re.search(r'<div class="sub">([^<]*)</div>', block).group(1))


def test_the_cards_of_page_1_are_the_figures_of_the_exported_tables(rendered_html, star_files):
    estimates = pd.read_parquet(star_files.out_dir / "fact_estimate.parquet")
    lab = pd.read_parquet(star_files.out_dir / "fact_hour_lab.parquet")
    arrived = estimates[estimates["actual"].notna()]
    assert len(arrived) > 5
    html = rendered_html.html

    def es(value: float, digits: int = 3) -> str:
        return f"{value:.{digits}f}".replace(".", ",")

    assert _card(html, "MAE del modelo")[0] == es(arrived["abs_error"].mean())
    assert _card(html, "MAE de la persistencia")[0] == es(arrived["abs_error_persistence"].mean())
    assert _card(html, "Cobertura del rango")[0] == f"{arrived['covered'].astype(bool).mean() * 100:.1f} %".replace(".", ",")
    assert _card(html, "Horas sin estimación")[0] == str((estimates["status"] == "missing_inputs").sum())
    last = estimates[(estimates["status"] == "ok") & (estimates["horizon_key"] == 0)].sort_values("hour_key").iloc[-1]
    assert _card(html, "Última estimación")[0] == es(last["estimate"], 2) and str(last["hour_key"])[:8] in _card(html, "Última estimación")[1].replace("-", "")
    fresh = lab[(lab["lab_state"] == "fresh") & lab["silica_pct"].notna()].sort_values("hour_key").iloc[-1]
    assert _card(html, "Último análisis llegado")[0] == es(fresh["silica_pct"], 2)


def test_the_quality_cards_of_page_5_are_the_figures_of_the_exported_tables(rendered_html, star_files):
    quality = pd.read_parquet(star_files.out_dir / "fact_data_quality.parquet")
    rules = pd.read_parquet(star_files.out_dir / "fact_validation.parquet")
    runs = pd.read_parquet(star_files.out_dir / "dim_pipeline_run.parquet")
    html = rendered_html.html
    assert _card(html, "Horas interpoladas")[0] == str(int(quality["interpolated"].sum())) and _card(html, "Horas repetidas")[0] == str(int(quality["held"].sum()))
    assert _card(html, "Reglas bloqueantes fallidas")[0] == str(int(((rules["severity"] == "bloqueante") & (rules["status"] == "falla")).sum())) == "1"
    assert _card(html, "Última fecha de cálculo")[0] == pd.Timestamp(runs[runs["status"] == "ok"]["as_of"].max()).strftime("%Y-%m-%d %H:%M")
    lab = pd.read_parquet(star_files.out_dir / "fact_hour_lab.parquet")
    arrived = lab[lab["silica_pct"].notna()]
    assert _card(html, "Análisis frescos (%)")[0] == f"{(arrived['lab_state'] == 'fresh').mean() * 100:.1f} %".replace(".", ",")


def test_the_evaluation_previews_show_the_test_and_say_when_it_is_not_the_test(rendered_html, star_files, tmp_path):
    assert "prueba" in text_of(rendered_html.html.split('aria-label="MAE por horizonte"', 1)[1].split("</section>", 1)[0])
    folder = _changed(star_files, tmp_path / "v2", {})
    metrics = pd.read_parquet(folder / "fact_method_metrics.parquet")
    metrics[metrics["scope"] != "test"].to_parquet(folder / "fact_method_metrics.parquet", index=False)
    only_validation = render_design(MODEL, folder, tmp_path / "v2.html", star_files.run).read_text(encoding="utf-8")
    block = text_of(only_validation.split('aria-label="MAE por horizonte"', 1)[1].split("</section>", 1)[0])
    assert "no es la prueba" in block or "sin evaluar" in block


def test_the_sensitivity_previews_say_association_of_the_model_and_the_empty_curves_say_why(rendered_html):
    text = text_of(rendered_html.html)
    assert "sin asociación estable" in text and "Asociación del modelo, no una receta" in text
    assert re.search(r"Ningún sensor pasó la compuerta|sin curvas", text), "no sensor passes in the fixture, so there is no curve to draw, and the page says so"


def test_a_visual_of_a_page_has_its_own_position_on_the_grid(rendered_html):
    for page in MODEL.pages:
        for v in page.visuals:
            style = f"grid-column:{v.x + 1} / span {v.w};grid-row:{v.y + 1} / span {v.h}"
            assert style in rendered_html.html, (page.name_es, v.title_es)


def test_the_dates_a_preview_shows_are_the_instant_of_the_run(rendered_html, star_files):
    assert isinstance(star_files.run.as_of, datetime)
    assert rendered_html.html.count(html_lib.escape(star_files.run.run_key)) >= 2


def test_the_curves_of_the_sensors_that_passed_the_gate_are_drawn_and_a_post_seal_row_never_replaces_a_sealed_one(star_files, tmp_path):
    folder = _changed(star_files, tmp_path / "passed", {})
    sensitivity = pd.read_parquet(folder / "fact_sensitivity.parquet")
    sensitivity.loc[sensitivity.index[:2], ["passes", "sign_stable"]] = True
    sensitivity.loc[sensitivity.index[:2], "label_es"] = "asociación del modelo"
    sensitivity.to_parquet(folder / "fact_sensitivity.parquet", index=False)
    curve = pd.DataFrame([{"sensor_key": key, "point": point, "grid_value": 1.0 + point, "mean_estimate": 3.0 + 0.1 * point * sign}
                          for key, sign in zip(sensitivity["sensor_key"].iloc[:2], (1, -1), strict=True) for point in range(5)])
    curve.assign(point=curve["point"].astype("int32")).to_parquet(folder / "fact_pd_curve.parquet", index=False)
    metrics = pd.read_parquet(folder / "fact_method_metrics.parquet")
    pd.concat([metrics, metrics.assign(seal_state="post_seal", mae=9.999)]).to_parquet(folder / "fact_method_metrics.parquet", index=False)
    html = render_design(MODEL, folder, tmp_path / "passed.html", star_files.run).read_text(encoding="utf-8")
    block = html.split('aria-label="Asociación del modelo, no una receta', 1)[1].split("</section>", 1)[0]
    assert block.count("<polyline") == 2 and "Ningún sensor pasó" not in block
    assert _card(html, "Sensores con asociación estable")[0] == "2"
    assert "9,999" not in html, "the sealed rows are shown while there are any"
