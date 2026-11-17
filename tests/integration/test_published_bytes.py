"""What is published carries no path of this machine (U15, AC27; RNF12; D43): the Parquet files, the site files, the seal, the summary, the design of the dashboard and the figures of
a run are searched byte by byte for an absolute path, the user's directory and their name. There is nobody to protect in the data (D43), but a path in a versioned file exposes the
machine that built it."""

from __future__ import annotations

import getpass
import io
import re
import shutil
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from flotsilica.reporting import build_summary, write_summary
from flotsilica.warehouse import connect

TEXT_SUFFIXES = (".json", ".html", ".md", ".svg", ".txt")
# a path of a machine: a drive, a user's folder on any system, a temporary folder, a file address; «https://» is not one (a letter before the drive letter, or two slashes after)
GENERIC = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/](?![\\/])|/Users/|\\Users\\|/home/|/tmp/|/var/folders/|file://|\\\\\w+\\", re.IGNORECASE)


def local_names(*folders: Path) -> list[str]:
    """The strings that can only be there if a path of this run leaked: the user's directory and name, the temporary folder, the project and the folders of the run, in both spellings."""
    names = {str(Path.home()), getpass.getuser(), tempfile.gettempdir(), *map(str, folders), str(Path(__file__).resolve().parents[2])}
    names |= {n.replace("\\", "/") for n in names} | {n.replace("/", "\\") for n in names}
    return sorted((n for n in names if len(n) >= 4), key=len, reverse=True)


def decoded(path: Path) -> str:
    """The text a reader of the file sees: a text file as it is, a Parquet file as its metadata and its string values, any other file as it is not (only searched for literals)."""
    if path.suffix == ".parquet":
        table = pq.read_table(io.BytesIO(path.read_bytes()))
        values = [str(v) for column in table.columns if pa.types.is_string(column.type) for v in column.to_pylist() if v is not None]
        return "\n".join([*(f"{k.decode()}={v.decode()}" for k, v in (table.schema.metadata or {}).items()), *values])
    return path.read_text(encoding="utf-8") if path.suffix in TEXT_SUFFIXES else ""


def problems_of(path: Path, names: list[str]) -> list[str]:
    raw, text = path.read_bytes(), decoded(path)
    found = [f"{path.name}: {n!r}" for n in names if n.encode("utf-8", "replace") in raw or n in text or n.lower() in text.lower()]
    return found + [f"{path.name}: {m.group()!r}" for m in GENERIC.finditer(text)]


# --- the RED of U15 ----------------------------------------------------------------------------------------------------------------------


def test_published_files_carry_no_local_path(star_files, site_files, rendered_html, figures_written, tmp_path):
    history, run = star_files.history, star_files.run
    reports = tmp_path / "reports"
    conn = connect(history.paths.db)
    try:
        summary = build_summary(conn, history.sealed, run=run, seal_path=history.paths.seal)
    finally:
        conn.close()
    write_summary(summary, reports)
    shutil.copy2(history.paths.seal, reports / "model_seal.json")
    published = {"outputs/powerbi": star_files.out_dir, "outputs/site": site_files.out_dir, "reports": reports, "dashboard": rendered_html.path.parent, "docs/figures": figures_written[0]}
    names = local_names(history.paths.db.parent, tmp_path, *published.values())
    files = {where: sorted(p for p in folder.iterdir() if p.is_file()) for where, folder in published.items()}
    assert {where: len(found) for where, found in files.items()} == {"outputs/powerbi": 21, "outputs/site": 6, "reports": 3, "dashboard": 1, "docs/figures": 7}
    found = [problem for found_files in files.values() for path in found_files for problem in problems_of(path, names)]
    assert found == [], "a path of this machine in what is published"


def test_the_search_finds_a_path_where_one_is_written(tmp_path):
    """The search itself: a path in a JSON, in an HTML, in the metadata of a Parquet file, in one of its values and in a PNG (searched for the literal only) is found, and the address of a
    page is not taken for one."""
    names = local_names(tmp_path)
    home = str(Path.home())
    (tmp_path / "a.json").write_text(f'{{"file": "{home}"}}'.replace("\\", "\\\\"), encoding="utf-8")
    (tmp_path / "b.html").write_text("<p>C:\\Users\\someone\\work</p>", encoding="utf-8")
    (tmp_path / "c.png").write_bytes(b"\x89PNG\r\n\x1a\n" + str(tmp_path).encode() + b"\x00")
    pq.write_table(pa.table({"x": [1]}).replace_schema_metadata({"flotsilica.run_key": "/home/someone/run"}), tmp_path / "d.parquet")
    pq.write_table(pa.table({"x": ["/Users/someone/data"]}), tmp_path / "e.parquet")
    (tmp_path / "f.html").write_text('<a href="https://example.org/a">a</a> and a time 12:30', encoding="utf-8")
    assert all(problems_of(tmp_path / name, names) for name in ("a.json", "b.html", "c.png", "d.parquet", "e.parquet"))
    assert problems_of(tmp_path / "f.html", names) == []

