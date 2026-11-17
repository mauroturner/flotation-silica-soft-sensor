"""The documentation is checked like code (AC22, AC39; RF28; RNF14; plan, sections 25 and 26).

U22: the README has the headings of plan section 25 in their order, its results block is the sealed summary that ``docs-sync`` copies (never one written
by hand), and it says the unfavourable verdicts («no supera») in «El problema», «La solución» and «Los resultados»; the model card has the contents the plan
lists, every verdict as the summary writes it, the memory counters and the suite's limit. These tests read the versioned Markdown and the versioned reports
and run nothing.

U23 (AC39; RF26; RNF14; plan, sections 24.1, 25 and 30): every decision has its seven fields; the test count the documents give is the one of the session's collection
(only when that session collected the default selection in full); every memory figure names its counter; every test the plan names exists; the dictionary covers the
24 source columns and the 67 features and its tables are the ones ``docs-sync`` writes from the semantic model; the runbook has R1 to R12; the step by step names every
unit and cites commits that exist; the relative links resolve; every advisory of the native reviews has its status and the README's open ones are the review file's;
and the root rows of project 05 carry the real figures. The ``docs-sync`` tests work on a copy of the configuration in a temporary folder.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from flotsilica.reporting import RESULTS_END, RESULTS_START

README_TITLE = "# Sílice en el concentrado, sin esperar al laboratorio"
README_HEADINGS = [   # plan, section 25, in this order (AC39)
    "El problema", "La solución", "Los resultados", "En qué consiste", "Los datos", "Los algoritmos", "El producto", "La documentación",
    "Con IA, de punta a punta", "Para qué sirve", "Cómo correrlo de punta a punta", "Paso a paso", "Fuente y licencia",
]
MODEL_CARD_HEADINGS = [   # what plan section 25 lists for the model card, in this order
    "Uso previsto y no previsto", "Datos", "La frescura y por qué las cifras difieren de research.md", "Latencia supuesta", "Horizontes", "Partición",
    "Métodos", "Selección y reajuste", "Rango del 80 %", "Criterios y resultados", "Sensibilidades y su compuerta", "Limitaciones", "Tiempos y memoria",
    "La suite rápida",
]
FAILED = ["C01", "C02", "C03", "C04", "C06", "C08", "C09"]   # D47: what the sealed run says
PASSED = ["C05", "C07"]
RESULTS_HEADING = "## Resultados"   # the first line of the summary, copied as it is (D44, D48)


@pytest.fixture(scope="module")
def readme(project_root: Path) -> str:
    return (project_root / "README.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def model_card(project_root: Path) -> str:
    return (project_root / "docs" / "model-card.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def summary(project_root: Path) -> dict:
    return json.loads((project_root / "reports" / "evaluation_summary.json").read_text(encoding="utf-8"))


def section(text: str, title: str, end: str | None = None) -> str:
    """The body of the second-level section `title`: up to `end` (its first appearance after the heading) when it is given, otherwise up to the next second-level
    heading or the end of the text (R2-section-helper-sentinel-hack, L66: the boundary is said, not appended to the text)."""
    body = text.split(f"\n## {title}\n", 1)[1]
    if end is not None:
        assert end in body, f"{end!r} does not follow the heading {title!r}"
        return body.split(end, 1)[0]
    return re.split(r"^## ", body, flags=re.MULTILINE)[0]


def test_readme_headings_in_order_and_results_block_matches_summary(project_root: Path, readme: str, summary: dict) -> None:
    assert readme.startswith(README_TITLE + "\n")
    assert readme.count(RESULTS_START) == 1 and readme.count(RESULTS_END) == 1
    head, rest = readme.split(RESULTS_START)
    block, tail = rest.split(RESULTS_END)
    block = block.strip("\n")
    # the block carries its own «## Resultados» (D44): the headings of the plan are those outside it, in order (D48)
    assert re.findall(r"^## (.+)$", head + tail, flags=re.MULTILINE) == README_HEADINGS
    written = (project_root / "reports" / "evaluation_summary.md").read_text(encoding="utf-8")
    assert block == written.strip("\n")   # what docs-sync copies, byte for byte
    assert block.startswith(RESULTS_HEADING + "\n") and re.findall(r"^## (.+)$", block, flags=re.MULTILINE) == ["Resultados"]
    framing = section(readme, "Los resultados", end=RESULTS_START)   # «Los resultados» frames the block before it and reads it after it (D48)
    assert len(framing.strip()) > 400 and "\n## En qué consiste\n" in tail
    # AC22: the sealed summary is unfavourable, and the README says «no supera» outside the block too, in the three sections that tell it
    assert summary["evaluation_status"] == "sealed" and summary["post_seal"] is None
    assert [c["criterion_id"] for c in summary["criteria"] if c["passed"] is False] == FAILED
    assert [c["criterion_id"] for c in summary["criteria"] if c["passed"] is True] == PASSED
    assert [c["criterion_id"] for c in summary["criteria"] if c["passed"] is None] == ["C10"]
    for criterion in summary["criteria"]:
        assert criterion["verdict_es"] in block, criterion["criterion_id"]
    reading = framing + tail.split("\n## En qué consiste\n")[0]
    for title, text in (("El problema", section(readme, "El problema")), ("La solución", section(readme, "La solución")), ("Los resultados", reading)):
        assert "no supera" in text, title
    for criterion in FAILED + PASSED:
        assert re.search(rf"\b{criterion}\b", reading), criterion
    assert re.search(r"persistencia", reading) and "H0" in reading and "H1" in reading


def test_the_model_card_has_the_contents_of_the_plan_and_says_the_unfavourable_verdicts(model_card: str, summary: dict) -> None:
    assert re.findall(r"^## (.+)$", model_card, flags=re.MULTILINE) == MODEL_CARD_HEADINGS
    for criterion in summary["criteria"]:
        assert criterion["verdict_es"] in model_card, criterion["criterion_id"]   # every verdict as the summary writes it, «no supera» included
    for limit in (
        "OpenML", "no se comparó byte a byte", "una latencia supuesta", "unidades de los sensores", "una sola vez", "seis meses", "una sola planta",
        "PeakWorkingSetSize", "PeakPagefileUsage", "120 s", "90 s", "asociación del modelo", "sin asociación estable",
    ):
        assert limit.lower() in model_card.lower(), limit
    assert re.search(r"suite rápida[^\n]*\d{2,3},\d+ s", model_card)   # AC40: measured and written down


def test_the_readme_says_what_is_pending_and_gives_the_attribution(readme: str, model_card: str) -> None:
    """RNF14: the independent evaluation and the ``.pbix`` are not done and the README says so; the credit of the source is complete; nothing local is published."""
    text = readme.lower()
    assert "evaluación independiente" in text and "todavía no" in text and ".pbix" in text
    tail = section(readme, "Fuente y licencia")
    for piece in ("Quality Prediction in a Mining Process", "Eduardo Magalhães Oliveira", "CC0", "OpenML", "43311", "a25122979ba8c5fb9c12e361db61032efc6892a24b5746cc8309da601d9639b2"):
        assert piece in tail, piece
    for document in (readme, model_card):
        assert not re.search(r"[A-Za-z]:[\\/]+(Users|Documents and Settings)", document) and "mauro" not in document.lower() and "@gmail" not in document


# --- U23: the decisions, the stated test count, the memory figures, the tests the plan names, the dictionary, the runbook, the step by step, the advisories, the
# links and the root rows (AC39) ----------------------------------------------------------------------------------------------------------------------------

NAMED_TEST = re.compile(r"(tests/[\w/]+\.py)?::(test_\w+)")
DECISION_FIELDS = ("Contexto", "Opciones", "Decisión", "Motivo", "Afecta", "Quién", "Estado")   # AC39: every decision, D01 to the last
COUNTERS = ("PeakWorkingSetSize", "PeakPagefileUsage", "ru_maxrss", "conjunto de trabajo", "memoria comprometida")   # by API name or by what it counts
MEMORY_FIGURE = re.compile(r"\d[\d.]*(?:,\d+)?\s?(?:MB|GB|MiB|GiB)\b")
MEMORY_WORDS = re.compile(r"pico|peak_|conjunto de trabajo|comprometid|memoria", re.IGNORECASE)   # the size of a file or a folder is not a memory figure
SENTENCE_END = re.compile(r"(?<=\.)\s+")
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)#\s]+)(?:#[^)]*)?\)")
IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
UNITS = [f"U{n:02d}" for n in range(1, 24)]
STATUSES = ("corregida", "refutada", "dejada con evidencia", "abierta")
DOCS = ("data-dictionary.md", "runbook.md", "paso-a-paso.md", "review-advisories.md", "decisions.md")
ROW_CELLS = r"^\| `([^`]+)` \| ([^|]+?) \| ([^|]+?) \| ([^|]+?) \|$"


def read(project_root: Path, name: str) -> str:
    return (project_root / "docs" / name).read_text(encoding="utf-8")


def root_rows(project_root: Path) -> str:
    """The section of project 05 in the root ``SITE-UPDATES.md``, up to the next project or the end."""
    text = (project_root.parent / "SITE-UPDATES.md").read_text(encoding="utf-8")
    assert text.count("\n## 05 ") == 1, "SITE-UPDATES.md has no section for project 05"
    return re.split(r"\n## 0[6-9] ", text.split("\n## 05 ")[1])[0]


def stated_count(request: pytest.FixtureRequest) -> str:
    """The test count as the documents write it, from the collection of this session; skipped when the session did not collect the default selection in full
    (a count taken from a part of the suite would be another number, and collecting the rest in another process costs seconds: plan, section 24.1)."""
    from tests.fixtures.suite_budget import is_full_default_selection

    if not is_full_default_selection(request.config):
        pytest.skip("the session did not collect the default selection in full: its collection is not the suite's count")
    return f"{len(request.session.items):,}".replace(",", ".") + " pruebas"


def named_in_plan(plan: str) -> list[tuple[str, str]]:
    """Every test the plan names, as (file, function): a bare ``::name`` belongs to the file named last before it."""
    found, last = [], None
    for match in NAMED_TEST.finditer(plan):
        last = match.group(1) or last
        assert last is not None, match.group(0)
        found.append((last, match.group(2)))
    return found


def test_every_test_named_in_the_plan_exists(project_root: Path) -> None:
    """AC39: every test plan sections 24 and 27 name (the RED of each unit and the named defect classes) is a test function of that file."""
    named = named_in_plan((project_root / "docs" / "plan.md").read_text(encoding="utf-8"))
    assert len(named) >= 100   # the plan does name its tests: the check is not vacuous
    defined: dict[str, set[str]] = {}
    missing = []
    for path, name in named:
        if path not in defined:
            file = project_root / path
            tree = ast.parse(file.read_text(encoding="utf-8")) if file.is_file() else ast.Module(body=[], type_ignores=[])
            defined[path] = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if name not in defined[path]:
            missing.append(f"{path}::{name}")
    assert sorted(set(missing)) == []


def test_every_decision_has_seven_fields(project_root: Path) -> None:
    text = read(project_root, "decisions.md")
    entries = re.split(r"^## (?=D\d+ )", text, flags=re.MULTILINE)[1:]
    numbers = [int(re.match(r"D(\d+)", e).group(1)) for e in entries]
    assert numbers == list(range(1, len(numbers) + 1)) and len(numbers) >= 49   # no gap and no repeat, up to U23's own
    missing = [f"D{n:02d}: {field}" for n, entry in zip(numbers, entries, strict=True) for field in DECISION_FIELDS if f"- **{field}**: " not in entry]
    assert missing == []
    states = {f"D{n:02d}": re.search(r"^- \*\*Estado\*\*: (.+)$", e, flags=re.MULTILINE).group(1) for n, e in zip(numbers, entries, strict=True)}
    assert [d for d, s in states.items() if not re.match(r"(vigente|pendiente del dueño|reemplazada por D\d+)", s)] == []


def test_stated_test_count_matches_the_session_collection(request: pytest.FixtureRequest, project_root: Path, readme: str, model_card: str) -> None:
    """B3 of project 02, B5 of project 03 and B1 of project 04 (RNF14): the documents said one test count after a change had moved it. The count is that of the
    collection, in the README, the model card and the root rows; the seconds next to it are measured and written by hand (AC40)."""
    stated = stated_count(request)
    assert re.findall(r"\b\d{1,3}(?:\.\d{3})* pruebas\b", readme) == [stated]   # the README states one count: this one
    assert re.findall(r"\b\d{1,3}(?:\.\d{3})* pruebas\b", section(model_card, "La suite rápida")) == [stated]
    assert stated in root_rows(project_root)


def test_every_memory_figure_names_its_counter(project_root: Path, readme: str, model_card: str) -> None:
    """RNF03 and D38 (lesson A3 of project 02): a memory figure without its counter cannot be compared with another. Every sentence of the documents that gives a
    memory figure in MB or GB names the counter, by its API name or by what it counts."""
    absent = [f"docs/{name}" for name in DOCS if not (project_root / "docs" / name).is_file()]
    assert absent == [], "every document of AC39 exists"
    documents = {"README.md": readme, "docs/model-card.md": model_card, "SITE-UPDATES.md (05)": root_rows(project_root)}
    documents |= {f"docs/{name}": read(project_root, name) for name in DOCS}
    figures, unnamed = 0, []
    for name, text in documents.items():
        for line in text.splitlines():
            for sentence in SENTENCE_END.split(line):
                if MEMORY_FIGURE.search(sentence) and MEMORY_WORDS.search(sentence):
                    figures += 1
                    if not any(counter in sentence for counter in COUNTERS):
                        unnamed.append(f"{name}: {sentence.strip()[:160]}")
    assert unnamed == []
    assert figures >= 6   # the documents do state memory figures: the check is not vacuous


def test_results_block_matches_summary(project_root: Path, readme: str, summary: dict) -> None:
    """Plan 24.2, the class «documentación sin sincronizar»: the block is the summary of the sealed run, its run and its date included."""
    block = readme.split(RESULTS_START)[1].split(RESULTS_END)[0].strip("\n")
    assert block == (project_root / "reports" / "evaluation_summary.md").read_text(encoding="utf-8").strip("\n")
    assert f"Corrida {summary['run_key']} del {summary['as_of']}." in block and "Estado: sealed." in block


def test_the_dictionary_covers_the_source_and_the_features_and_its_tables_are_the_generated_ones(project_root: Path) -> None:
    import pyarrow.parquet as pq

    from flotsilica.dashboard.semantic_model import MODEL, arrow_schema
    from flotsilica.docs import COLUMNS_END, COLUMNS_START, render_dictionary_tables
    from flotsilica.schema import ATTRIBUTES, FEATURE_COLUMNS

    text = read(project_root, "data-dictionary.md")
    source = text.split("\n## Archivo de origen\n")[1].split("\n## ")[0]
    rows = re.findall(r"^\| `([^`]+)` \| `([^`]+)` \| ([^|]+?) \| ([^|]+?) \| ([^|]+?) \|$", source, flags=re.MULTILINE)
    assert [(a, n) for a, n, *_rest in rows] == list(ATTRIBUTES.items())   # the 24 attributes of the ARFF, in file order, with the name the code gives them
    assert all(cell.strip() for row in rows for cell in row)
    features = text.split("\n## Variables\n")[1].split("\n## ")[0]
    documented = re.findall(r"^\| `([a-z_0-9]+)` \| ([^|]+?) \| ([^|]+?) \| ([^|]+?) \|$", features, flags=re.MULTILINE)
    assert [name for name, *_rest in documented] == list(FEATURE_COLUMNS) and len(documented) == 67   # the 67, in the order of the matrix, each with its unit and definition
    assert all(cell.strip() for row in documented for cell in row)
    assert text.count(COLUMNS_START) == 1 and text.count(COLUMNS_END) == 1
    block = text.split(COLUMNS_START)[1].split(COLUMNS_END)[0]
    assert block.strip() == render_dictionary_tables(MODEL).strip()   # what docs-sync writes
    assert [name for name in re.findall(r"^### `([a-z_]+)`$", block, flags=re.MULTILINE)] == [t.name for t in MODEL.tables] and len(MODEL.tables) == 20
    for table in MODEL.tables:
        part = block.split(f"### `{table.name}`\n")[1].split("\n### ")[0]
        listed = re.findall(r"^\| `([a-z_0-9]+)` \| [^|]+ \| ([^|]+) \| ", part, flags=re.MULTILINE)
        assert tuple(name for name, _unit in listed) == table.column_names and all(unit.strip() for _name, unit in listed), table.name
        assert pq.read_schema(project_root / "outputs" / "powerbi" / f"{table.name}.parquet").names == list(table.column_names) == arrow_schema(table).names, table.name


def _sync_project(project_root: Path, tmp_path: Path, dictionary: str | None) -> str:
    (tmp_path / "config").mkdir()
    shutil.copyfile(project_root / "config" / "pipeline.toml", tmp_path / "config" / "pipeline.toml")
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "evaluation_summary.md").write_text("## Resultados\n\n| C01 | no supera |\n", encoding="utf-8", newline="\n")
    (tmp_path / "README.md").write_text(f"# P\n\n{RESULTS_START}\nviejo\n{RESULTS_END}\n", encoding="utf-8", newline="\n")
    if dictionary is not None:   # next to the figures folder of the configuration (docs/figures), as docs/ is in the project
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "data-dictionary.md").write_text(dictionary, encoding="utf-8", newline="\n")
    return str(tmp_path / "config" / "pipeline.toml")


def test_docs_sync_writes_the_dictionary_tables_and_a_second_run_changes_nothing(project_root: Path, tmp_path: Path, capsys) -> None:
    from flotsilica import cli
    from flotsilica.dashboard.semantic_model import MODEL
    from flotsilica.docs import COLUMNS_END, COLUMNS_START, render_dictionary_tables

    config = _sync_project(project_root, tmp_path, f"# D\n\n{COLUMNS_START}\nviejo\n{COLUMNS_END}\n\nal final\n")
    assert cli.main(["docs-sync", "--config", config]) == 0
    assert capsys.readouterr().out.splitlines() == ["README.md actualizado", "data-dictionary.md actualizado"]
    text = (tmp_path / "docs" / "data-dictionary.md").read_text(encoding="utf-8")
    assert text == f"# D\n\n{COLUMNS_START}\n{render_dictionary_tables(MODEL).strip()}\n{COLUMNS_END}\n\nal final\n" and "viejo" not in text
    assert "| C01 | no supera |" in (tmp_path / "README.md").read_text(encoding="utf-8")
    assert cli.main(["docs-sync", "--config", config]) == 0
    assert capsys.readouterr().out.splitlines() == ["README.md ya estaba al día", "data-dictionary.md ya estaba al día"]


def test_docs_sync_without_a_dictionary_still_syncs_only_the_readme(project_root: Path, tmp_path: Path, capsys) -> None:
    """The command as it was before U23: with no dictionary next to the figures folder, it writes the README block and says only that."""
    from flotsilica import cli

    config = _sync_project(project_root, tmp_path, None)
    assert cli.main(["docs-sync", "--config", config]) == 0
    assert capsys.readouterr().out.splitlines() == ["README.md actualizado"]
    assert not (tmp_path / "docs").exists()


def test_docs_sync_with_a_dictionary_without_its_markers_exits_2_and_writes_nothing(project_root: Path, tmp_path: Path, capsys) -> None:
    from flotsilica import cli

    config = _sync_project(project_root, tmp_path, "# D\n\nsin marcadores\n")
    before = {path: path.read_bytes() for path in sorted(tmp_path.rglob("*")) if path.is_file()}
    assert cli.main(["docs-sync", "--config", config]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "data-dictionary.md" in captured.err and "debe tener una vez" in captured.err and "No se escribió nada" in captured.err
    assert {path: path.read_bytes() for path in sorted(tmp_path.rglob("*")) if path.is_file()} == before   # the README was not written either


def test_docs_sync_with_a_column_type_the_dictionary_cannot_name_exits_2_and_writes_nothing(project_root: Path, tmp_path: Path, capsys, monkeypatch) -> None:
    """R3-dtype-lookup-uncaught-keyerror (U23's review, L66): a type of the semantic model that ``DTYPE_ES`` does not name is a ``ValueError`` that names the column, which
    ``docs-sync`` turns into exit 2; the tables are rendered before any file is written, so neither the README nor the dictionary changes."""
    from flotsilica import cli, docs

    monkeypatch.setattr(docs, "DTYPE_ES", {k: v for k, v in docs.DTYPE_ES.items() if k != "date"})
    config = _sync_project(project_root, tmp_path, f"# D\n\n{docs.COLUMNS_START}\nviejo\n{docs.COLUMNS_END}\n")
    before = {path: path.read_bytes() for path in sorted(tmp_path.rglob("*")) if path.is_file()}
    assert cli.main(["docs-sync", "--config", config]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "'date'" in captured.err and "DTYPE_ES" in captured.err and "No se escribió nada" in captured.err, captured.err
    assert {path: path.read_bytes() for path in sorted(tmp_path.rglob("*")) if path.is_file()} == before


def test_the_help_of_docs_sync_names_both_blocks(capsys) -> None:
    from flotsilica import cli

    assert cli.main(["docs-sync", "--help"]) == 0
    help_text = " ".join(capsys.readouterr().out.split())
    assert "README" in help_text and "diccionario de datos" in help_text and "tablas" in help_text


def test_the_runbook_has_r1_to_r12_and_every_reference_of_the_code_points_to_one(project_root: Path) -> None:
    text = read(project_root, "runbook.md")
    entries = re.split(r"^## (?=R\d+ )", text, flags=re.MULTILINE)[1:]
    assert [entry.split()[0] for entry in entries] == [f"R{n}" for n in range(1, 13)]   # plan, section 25
    for entry in entries:
        assert "**Síntoma.**" in entry and "**Qué hacer.**" in entry, entry.splitlines()[0]
    r8 = next(entry for entry in entries if entry.startswith("R8 "))
    assert "A12" in r8   # the advisory of project 04's lock that this project's lock also has (plan, section 25)
    sources = [*sorted((project_root / "src" / "flotsilica").rglob("*.py")), *sorted((project_root / "airflow").rglob("*.py")), project_root / "airflow" / "docker-compose.yaml"]
    cited = {int(n) for path in sources for n in re.findall(r"runbook(?:\.md)?,? R(\d+)", path.read_text(encoding="utf-8"))}
    assert cited and cited <= set(range(1, 13)), cited


def test_the_step_by_step_names_every_unit_and_cites_commits_that_exist(project_root: Path) -> None:
    text = read(project_root, "paso-a-paso.md")
    assert [unit for unit in UNITS if not re.search(rf"\b{unit}\b", text)] == []
    hashes = sorted(set(re.findall(r"`([0-9a-f]{7})`", text)))
    assert len(hashes) >= 30
    if shutil.which("git") is None or not (project_root.parent / ".git").exists():
        pytest.skip("there is no Git history to check the commits against")
    done = subprocess.run(["git", "cat-file", "--batch-check"], cwd=project_root, input="".join(f"{h}^{{commit}}\n" for h in hashes), capture_output=True, text=True)
    assert [line for line in done.stdout.splitlines() if line.endswith("missing")] == []


def test_relative_links_and_images_point_to_files_that_exist(project_root: Path, readme: str) -> None:
    """Every relative link and image of the README and of the documents resolves, and the README links to every document of ``docs/`` that exists."""
    broken = []
    for document in [project_root / "README.md", *sorted((project_root / "docs").glob("*.md"))]:
        text = document.read_text(encoding="utf-8")
        for target in [*LINK.findall(text), *IMAGE.findall(text)]:
            if not re.match(r"^(https?:|mailto:)", target) and not (document.parent / target).resolve().exists():
                broken.append(f"{document.name}: {target}")
    assert broken == []
    unlinked = [f"docs/{name}" for name in ("research.md", "requirements.md", "plan.md", "decisions.md", "model-card.md", *DOCS) if f"](docs/{name})" not in readme]
    assert unlinked == []


def advisories(text: str) -> dict[tuple[str, str], str]:
    """Every advisory of the review file by (section key, id), with its status: the bold words after «Estado:», or an empty string."""
    found: dict[tuple[str, str], str] = {}
    for part in re.split(r"^## ", text, flags=re.MULTILINE)[1:]:
        key = part.split()[0]
        for block in re.split(r"^(?=- \*\*)", part, flags=re.MULTILINE)[1:]:
            ident = re.match(r"- \*\*([^*]+)\*\*", block).group(1)
            status = re.search(r"^  - Estado: \*\*([^*]+)\*\*", block, flags=re.MULTILINE)
            assert (key, ident) not in found, (key, ident)
            found[(key, ident)] = status.group(1) if status else ""
    return found


def test_open_advisories_match_review_file(project_root: Path, readme: str) -> None:
    """AC39 and B5 of project 03's evaluation: every advisory of every native review has its status in ``docs/review-advisories.md`` (corrected, with its commit;
    refuted or left with evidence; or open), and the advisories the README calls open are the ones that file calls open."""
    text = read(project_root, "review-advisories.md")
    found = advisories(text)
    assert len(found) >= 20 and [key for key, status in found.items() if status not in STATUSES] == []
    fixed = [block for block in re.split(r"^(?=- \*\*)", text, flags=re.MULTILINE) if "Estado: **corregida**" in block]
    assert len(fixed) == 12 and all(re.search(r"`[0-9a-f]{7}`", block.split("Estado: **corregida**")[1].splitlines()[0]) for block in fixed)
    opened = sorted(f"{key}/{ident}" for (key, ident), status in found.items() if status == "abierta")
    [stated] = re.findall(r"^Advertencias abiertas: (.+)$", readme, flags=re.MULTILINE)
    assert sorted(re.findall(r"`([^`]+)`", stated)) == opened and len(opened) == 5, stated


def test_the_root_rows_of_project_05_carry_the_real_figures(project_root: Path) -> None:
    rows = root_rows(project_root)
    table = [line for line in rows.split("### ")[0].splitlines() if re.match(r"^\| \d+ \|", line)]
    assert [int(line.split("|")[1]) for line in table] == list(range(1, 18))   # plan, section 30: the seventeen rows
    for figure in ("0,597", "0,519", "0,703", "0,675", "0,753", "0,780", "0,793", "0,148", "15,3 %", "737.453", "4.097", "318", "444,0 s", "1.346,3 MB", "3.224,0 MB", "0,836"):
        assert figure in rows, figure
    assert rows.count("no supera") >= 2 and "C01" in rows and "C07" in rows and "C09" in rows and "pendiente" in rows and "@gmail" not in rows
    assert not re.search(r"[A-Za-z]:[\\/]+(Users|Documents and Settings)", rows) and "Users" not in rows
