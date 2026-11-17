"""What ``python -m flotsilica docs-sync`` writes into ``docs/data-dictionary.md`` (RF26, AC39; plan, section 25; D44, D49).

The README's results block is the summary the ``report`` task writes, copied between the ``results`` markers by ``reporting.sync_block``; that part of ``docs-sync`` stays in
``cli.py``. The tables of the data dictionary come from the semantic model (``dashboard.semantic_model.MODEL``), the specification the export checks every Parquet file
against: one section per table, in the order of the model, with every column, its type, its unit and its meaning, between the ``columns`` markers of the dictionary, written
with the same ``sync_block`` so that a second run changes nothing. The 24 source columns and the 67 features are written by hand and checked against ``schema.py`` by a test
(``tests/docs/test_docs.py``). Adapted from project 04's ``docs_sync.py``; this project has no table that is not versioned.
"""

from __future__ import annotations

from pathlib import Path

from flotsilica.dashboard.semantic_model import SemanticModel
from flotsilica.reporting import sync_block

COLUMNS_START = "<!-- columns:start -->"
COLUMNS_END = "<!-- columns:end -->"
DICTIONARY_NAME = "data-dictionary.md"
KIND_ES = {"dimension": "Dimensión", "fact": "Hecho"}
KEY_ES = {"dimension": "Clave", "fact": "Grano"}
DTYPE_ES = {"int8": "entero 8", "int32": "entero 32", "int64": "entero 64", "float64": "decimal", "string": "texto", "bool": "verdadero/falso", "date": "fecha",
            "datetime": "fecha y hora"}
NO_UNIT = "—"
VERSIONED_ES = "Se versiona en `outputs/powerbi/{name}.parquet`."


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_dictionary_tables(model: SemanticModel) -> str:
    """One section per table of the model, in its order: what it is, where it is written, its key or grain, and every column with its type, unit and meaning."""
    lines: list[str] = []
    for table in model.tables:
        keys = ", ".join(f"`{k}`" for k in table.key)
        lines += [f"### `{table.name}`", "", f"{KIND_ES[table.kind]}. {_cell(table.description_es)} {VERSIONED_ES.format(name=table.name)} {KEY_ES[table.kind]}: {keys}.", ""]
        lines += ["| Columna | Tipo | Unidad | Significado |", "| --- | --- | --- | --- |"]
        lines += [f"| `{c.name}` | {DTYPE_ES[c.dtype]} | {_cell(c.unit or NO_UNIT)} | {_cell(c.description_es)} |" for c in table.columns]
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def dictionary_path(figures_dir: Path) -> Path:
    """Where the dictionary lives: next to the figures folder (``docs/`` in the project; the quick mode has none)."""
    return Path(figures_dir).parent / DICTIONARY_NAME


def sync_dictionary(dictionary: Path, model: SemanticModel) -> bool:
    """Write the tables between the ``columns`` markers of the dictionary; True if the file changed (a second run changes nothing)."""
    return sync_block(Path(dictionary), COLUMNS_START, COLUMNS_END, render_dictionary_tables(model))


__all__ = ["COLUMNS_END", "COLUMNS_START", "dictionary_path", "render_dictionary_tables", "sync_dictionary"]
