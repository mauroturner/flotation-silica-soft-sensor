"""A plain reader of the synthetic ARFF for the tests, independent of the pipeline's reader (U04): lines up to ``@DATA`` are the header and
each data line is one csv record with ``'`` as the quote. The tests that check the pipeline against the bytes use this one."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tests.fixtures.make_fixture import SENSORS

COLUMNS = ["hour", "feed_iron", "feed_silica", *SENSORS, "iron_conc", "silica"]


@dataclass
class ParsedArff:
    comments: list[str]
    relation: str
    attributes: list[tuple[str, str]]
    rows: list[list[str]]      # the 24 fields of every data line, as text, without their apostrophes
    raw_lines: list[str]


def parse(path: Path) -> ParsedArff:
    """The ARFF read the plain way: lines up to ``@DATA`` are the header, each data line is one csv record with ``'`` as the quote."""
    text = path.read_bytes().decode("utf-8")
    assert "\r" not in text and "\x00" not in text and text.endswith("\n")
    lines = text.split("\n")[:-1]
    at = lines.index("@DATA")
    header, data = lines[:at], lines[at + 1:]
    comments = [line for line in header if line.startswith("%")]
    relation = next(line for line in header if line.startswith("@RELATION")).split(" ", 1)[1]
    attributes = []
    for line in header:
        if line.startswith("@ATTRIBUTE"):
            _tag, name, kind = line.split(" ")
            attributes.append((name.strip('"'), kind))
    rows = list(csv.reader(data, quotechar="'", delimiter=","))
    return ParsedArff(comments, relation, attributes, rows, data)


def number(field: str) -> float:
    assert "." not in field and field.count(",") <= 1, field    # the decimal comma, never a dot
    return float(field.replace(",", "."))


def hours_of(parsed: ParsedArff) -> dict[datetime, list[list[str]]]:
    by_hour: dict[datetime, list[list[str]]] = {}
    stamps: dict[str, datetime] = {}          # twelve rows of an hour (a hundred and eighty in the real file) share one text: it is parsed once
    for row in parsed.rows:
        hour = stamps.get(row[0])
        if hour is None:
            hour = stamps[row[0]] = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
        by_hour.setdefault(hour, []).append(row)
    return by_hour


def column(rows: list[list[str]], name: str) -> list[float]:
    position = COLUMNS.index(name)
    return [number(row[position]) for row in rows]
