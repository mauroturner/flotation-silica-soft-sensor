"""The variants (U11; RF18, AC23): nothing that chooses reads their table or imports their module, and they are computed only after the launch part of the seal."""

from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "flotsilica"
CHOOSING = ("model", "baselines", "intervals", "split", "features", "hours")           # the code that selects, refits, calibrates or makes the features


def test_no_choosing_function_reads_a_variant_table():
    for module in CHOOSING:
        text = (SRC / f"{module}.py").read_text(encoding="utf-8")
        assert "eval_variants" not in text, f"{module}.py reads the table of the variants"
        assert "import variants" not in text and "flotsilica.variants" not in text, f"{module}.py imports the variants"
    assert "eval_variants" not in (SRC / "scoring.py").read_text(encoding="utf-8") and "eval_variants" not in (SRC / "launch.py").read_text(encoding="utf-8")
    # the variants are read by the evaluation that writes them, and by nothing that runs before the test
    importers = sorted(p.stem for p in SRC.glob("*.py") if "flotsilica.variants" in p.read_text(encoding="utf-8") or "import variants" in p.read_text(encoding="utf-8")
                       or "from flotsilica import" in p.read_text(encoding="utf-8") and "variants" in p.read_text(encoding="utf-8").split("from flotsilica import", 1)[1].split("\n", 1)[0])
    assert importers == ["reporting"]
