"""The strict reader on small files made here (U04; V02-V07; D03): each rule at its edges, in the order the file is read, with nothing
past the first row of the test months parsed when a stop is asked for."""

from __future__ import annotations

import dataclasses
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from flotsilica.ingest import MAX_FIELD_CHARS, read_arff, read_header
from flotsilica.schema import COLUMNS, SourceError
from tests.fixtures.arff_reader import parse

TEMPLATE_FIELDS = ["2017-03-10 01:00:00", "55,2", "16,98", "3019,53", "557,434", "395,713", "10,0664", "1,74", "249,214", "253,235", "250,576",
                   "295,096", "306,4", "250,225", "250,884", "457,396", "432,962", "424,954", "443,558", "502,255", "446,37", "523,344", "66,91", "1,16"]


@pytest.fixture(scope="module")
def header(small_arff) -> str:
    text = small_arff.read_bytes().decode("utf-8")
    return text[:text.index("@DATA\n") + len("@DATA\n")]


def line(date="2017-03-10 01:00:00", **fields) -> str:
    values = list(TEMPLATE_FIELDS)
    values[0] = date
    for position, text in fields.items():
        values[int(position[1:])] = text
    return ",".join(f"'{v}'" for v in values)


def write(tmp_path: Path, header: str, lines: list[str], name="x.arff", newline="\n") -> Path:
    path = tmp_path / name
    path.write_bytes((header + newline.join(lines) + newline).encode("utf-8"))
    return path


def read(cfg, path: Path, **kwargs):
    return read_arff(path, cfg, **kwargs)


def test_a_valid_file_is_read_into_typed_columns_with_the_decimal_comma_converted(quick_cfg, tmp_path, header):
    path = write(tmp_path, header, [line(), line(F3="-0,5", F23="0"), line("2017-03-10 02:00:00", F4="12")])
    frame, report = read(quick_cfg, path)
    assert list(frame.columns) == ["row_id", "hour", "row_in_hour", *COLUMNS[1:]]
    assert list(frame["row_id"]) == [1, 2, 3] and list(frame["row_in_hour"]) == [1, 2, 1]
    assert list(frame["hour"]) == [datetime(2017, 3, 10, 1), datetime(2017, 3, 10, 1), datetime(2017, 3, 10, 2)]
    assert frame["starch_flow"].tolist() == [3019.53, -0.5, 3019.53] and frame["feed_iron_pct"].tolist() == [55.2] * 3
    assert frame["silica_pct"].tolist() == [1.16, 0.0, 1.16] and frame["amina_flow"].tolist() == [557.434, 557.434, 12.0]
    assert frame["row_id"].dtype == "int64" and frame["starch_flow"].dtype == "float64" and str(frame["hour"].dtype) == "datetime64[ns]"
    assert (report.rows, report.hours, report.missing_hours, report.first_hour, report.last_hour) == (3, 2, 0, datetime(2017, 3, 10, 1), datetime(2017, 3, 10, 2))
    assert report.size_bytes == path.stat().st_size and report.stopped_before is None


def test_a_last_line_without_a_newline_is_read_and_an_empty_data_section_is_refused(quick_cfg, tmp_path, header):
    path = tmp_path / "x.arff"
    path.write_bytes((header + line()).encode("utf-8"))
    assert len(read(quick_cfg, path)[0]) == 1
    path.write_bytes(header.encode("utf-8"))
    with pytest.raises(SourceError, match="V04.*sin filas"):
        read(quick_cfg, path)


@pytest.mark.parametrize("number", ["0", "12", "-1,5", "3,14159", "-0,0", "007,5", "123456789,123456"])
def test_the_numbers_that_are_accepted(quick_cfg, tmp_path, header, number):
    frame, _ = read(quick_cfg, write(tmp_path, header, [line(F3=number)]))
    assert frame["starch_flow"].iloc[0] == float(number.replace(",", "."))


@pytest.mark.parametrize("number", ["1,", ",5", "1,,5", "+1", "1e3", "1.5", "١٢", "1 2", " 1", "1 ", "NaN", "inf", "-", "--1", "1,2,3", "0x1F", "1_000", "1,5e3",
                                    "-,5", "１２"])
def test_the_numbers_that_are_refused_are_v05_and_name_the_column(quick_cfg, tmp_path, header, number):
    with pytest.raises(SourceError) as error:
        read(quick_cfg, write(tmp_path, header, [line(), line(F3=number)]))
    assert error.value.rule_id == "V05" and error.value.problems[0]["column"] == "Starch_Flow" and error.value.problems[0]["line"] == len(header.split("\n")) + 1


@pytest.mark.parametrize("date", ["2017-02-30 01:00:00", "2017-03-10 24:00:00", "2017-03-10 01:30:00", "2017-03-10 01:00:01", "2017-3-10 01:00:00",
                                  "2017-03-10T01:00:00", "17-03-10 01:00:00", " 2017-03-10 01:00:00", "2017-03-10 01:00", "2017-03-10", "٢٠١٧-٠٣-١٠ ٠١:٠٠:٠٠",
                                  "2017-13-10 01:00:00", "2017-03-10 01:00:00 "])
def test_the_dates_that_are_refused_are_v05(quick_cfg, tmp_path, header, date):
    with pytest.raises(SourceError) as error:
        read(quick_cfg, write(tmp_path, header, [line(date)]))
    assert error.value.rule_id == "V05" and error.value.problems[0]["column"] == "date"


def test_the_shape_of_a_line_is_v04_before_any_value_is_looked_at(quick_cfg, tmp_path, header):
    bad = {
        "one field short": line().rsplit(",", 1)[0], "one field more": line() + ",'1'", "no quotes": line().replace("'", ""),
        "an empty line": "", "a comment": "% a comment", "no closing quote": line()[:-1], "an unquoted first field": line()[1:],
        "a field longer than the limit": line(F3="1" * (MAX_FIELD_CHARS + 1)), "double apostrophes": line().replace("','", "''"),
    }
    for name, text in bad.items():
        with pytest.raises(SourceError) as error:
            read(quick_cfg, write(tmp_path, header, [line(), text], name="x.arff"))
        assert error.value.rule_id == "V04", name
        assert error.value.problems[0]["line"] == len(header.split("\n")) + 1, name
    longest = line(F3="1" * MAX_FIELD_CHARS)
    assert len(read(quick_cfg, write(tmp_path, header, [longest]))[0]) == 1      # at the limit, a number that is huge but finite


def test_a_carriage_return_is_not_part_of_a_line_and_the_whole_file_with_crlf_is_refused(quick_cfg, tmp_path, header):
    with pytest.raises(SourceError) as error:
        read(quick_cfg, write(tmp_path, header.replace("\n", "\r\n"), [line()], newline="\r\n"))
    assert error.value.rule_id == "V02"
    with pytest.raises(SourceError) as error:
        read(quick_cfg, write(tmp_path, header, [line(), line()], newline="\r\n"))
    assert error.value.rule_id in ("V04", "V05")


def test_the_dates_must_not_decrease_and_an_hour_may_not_pass_the_limit_and_the_order_is_checked_across_chunks(quick_cfg, tmp_path, header, monkeypatch):
    dates = ["2017-03-10 01:00:00", "2017-03-10 02:00:00", "2017-03-10 01:00:00"]
    with pytest.raises(SourceError, match="V06") as error:
        read(quick_cfg, write(tmp_path, header, [line(d) for d in dates]))
    assert error.value.problems[0]["line"] == len(header.split("\n")) + 2
    assert len(read(quick_cfg, write(tmp_path, header, [line(d) for d in sorted(dates)]))[0]) == 3
    rows = quick_cfg.hours.rows_per_hour
    assert len(read(quick_cfg, write(tmp_path, header, [line()] * rows))[0]) == rows
    with pytest.raises(SourceError, match="V07") as error:
        read(quick_cfg, write(tmp_path, header, [line()] * (rows + 1)))
    assert error.value.problems[0]["hour"] == "2017-03-10 01:00:00"
    # the same defects with the chunk boundary between the two lines that show them
    from flotsilica import ingest
    monkeypatch.setattr(ingest, "CHUNK_ROWS", 2)
    with pytest.raises(SourceError, match="V06"):
        read(quick_cfg, write(tmp_path, header, [line("2017-03-10 02:00:00"), line("2017-03-10 03:00:00"), line("2017-03-10 02:00:00")]))
    with pytest.raises(SourceError, match="V07"):
        read(quick_cfg, write(tmp_path, header, [line()] * (rows + 1)))
    assert len(read(quick_cfg, write(tmp_path, header, [line()] * rows + [line("2017-03-10 02:00:00")] * 3))[0]) == rows + 3


def test_the_header_is_exact_and_comments_come_only_before_the_relation(quick_cfg, tmp_path, header):
    ok = write(tmp_path, header, [line()])
    assert read_header(ok, quick_cfg) == len(header.split("\n")) - 1
    lines = header.split("\n")
    relation = next(i for i, x in enumerate(lines) if x.startswith("@RELATION"))
    first_attribute = next(i for i, x in enumerate(lines) if x.startswith("@ATTRIBUTE"))
    cases = {
        "a comment after the relation": lines[:relation + 1] + ["% late"] + lines[relation + 1:],
        "an unknown line": lines[:first_attribute] + ["@FOO bar"] + lines[first_attribute:],
        "no data section": [x for x in lines if x != "@DATA"],
        "the relation twice": lines[:relation + 1] + [lines[relation]] + lines[relation + 1:],
        "lower case string": [x.replace(" STRING", " string") if x.endswith("Starch_Flow STRING") else x for x in lines],
        "a swapped pair": lines[:first_attribute] + [lines[first_attribute + 1], lines[first_attribute]] + lines[first_attribute + 2:],
        "an attribute with a space": [x.replace("Starch_Flow", "Starch Flow") for x in lines],
        "the data marker in lower case": [x.replace("@DATA", "@data") for x in lines],
    }
    quoted = tmp_path / "q.arff"      # a name written with double quotes is the same name
    quoted.write_bytes(("\n".join(x.replace("@ATTRIBUTE Starch_Flow", '@ATTRIBUTE "Starch_Flow"') for x in lines) + line() + "\n").encode("utf-8"))
    assert read_header(quoted, quick_cfg) == len(lines) - 1
    for name, changed in cases.items():
        path = tmp_path / "h.arff"
        path.write_bytes(("\n".join(changed) + line() + "\n").encode("utf-8"))
        with pytest.raises(SourceError) as error:
            read_header(path, quick_cfg)
        assert error.value.rule_id == "V02", name


def test_a_header_that_never_ends_is_refused_without_reading_the_whole_file(quick_cfg, tmp_path, header):
    path = tmp_path / "h.arff"
    path.write_bytes(b"% comment\n" * 5000)
    with pytest.raises(SourceError, match="V02") as error:
        read_header(path, quick_cfg)
    assert "@RELATION" in str(error.value) or "cabecera" in str(error.value)


def test_a_limit_on_the_number_of_rows_and_on_the_bytes_of_a_line_is_v03(quick_cfg, tmp_path, header):
    config = dataclasses.replace(quick_cfg, source=dataclasses.replace(quick_cfg.source, max_rows=3))
    assert len(read(config, write(tmp_path, header, [line("2017-03-10 01:00:00"), line("2017-03-10 02:00:00"), line("2017-03-10 03:00:00")]))[0]) == 3
    with pytest.raises(SourceError, match="V03.*max_rows"):
        read(config, write(tmp_path, header, [line(d) for d in ("2017-03-10 01:00:00", "2017-03-10 02:00:00", "2017-03-10 03:00:00", "2017-03-10 04:00:00")]))
    short_header = "\n".join(x for x in header.split("\n") if not x.startswith("%"))
    narrow = dataclasses.replace(quick_cfg, source=dataclasses.replace(quick_cfg.source, max_line_bytes=len(line()) + 5))
    assert len(read(narrow, write(tmp_path, short_header, [line()]))[0]) == 1
    with pytest.raises(SourceError, match="V03.*max_line_bytes"):
        read(narrow, write(tmp_path, short_header, [line(F3="1" * 30)]))


def test_nothing_from_the_first_row_at_or_after_the_stop_is_parsed(quick_cfg, tmp_path, header):
    rows = [line("2017-03-10 01:00:00"), line("2017-03-10 02:00:00"), line("2017-03-11 01:00:00", F3="oops")]
    path = write(tmp_path, header, rows)
    frame, report = read(quick_cfg, path, stop_before=datetime(2017, 3, 11))
    assert len(frame) == 2 and report.rows == 2 and report.stopped_before == datetime(2017, 3, 11) and frame["hour"].max() == datetime(2017, 3, 10, 2)
    with pytest.raises(SourceError, match="V05"):
        read(quick_cfg, path)
    # whatever follows the first row of the stop is not read at all, not even to see whether it is a row
    garbage = write(tmp_path, header, [*rows[:2], line("2017-03-11 01:00:00"), "garbage that is not a row", ""], name="y.arff")
    assert len(read(quick_cfg, garbage, stop_before=datetime(2017, 3, 11))[0]) == 2
    with pytest.raises(SourceError, match="V04"):
        read(quick_cfg, garbage)
    # a line that only looks like it is past the stop (not a whole date field) is not an excuse to stop reading
    with pytest.raises(SourceError, match="V04"):
        read(quick_cfg, write(tmp_path, header, [line(), "'2017-03-11 xxx", line("2017-03-12 01:00:00")], name="z.arff"), stop_before=datetime(2017, 3, 11))


def test_the_report_counts_the_hours_of_the_grid_that_are_missing(quick_cfg, tmp_path, header):
    path = write(tmp_path, header, [line("2017-03-10 01:00:00"), line("2017-03-10 04:00:00"), line("2017-03-10 05:00:00"), line("2017-03-10 09:00:00")])
    frame, report = read(quick_cfg, path)
    assert (report.rows, report.hours, report.missing_hours) == (4, 4, 2 + 3)
    assert isinstance(frame, pd.DataFrame)


def test_reading_the_fixture_gives_every_row_and_the_values_the_plain_reader_sees(canonical, fixture_arff, fixture_truth):
    parsed = parse(fixture_arff)
    frame = canonical.read
    assert len(frame) == len(parsed.rows) == fixture_truth.n_rows
    assert frame["starch_flow"].iloc[:50].tolist() == [float(r[3].replace(",", ".")) for r in parsed.rows[:50]]
    assert frame["silica_pct"].iloc[-50:].tolist() == [float(r[23].replace(",", ".")) for r in parsed.rows[-50:]]
    assert list(frame["hour"].astype(str).iloc[:3]) == [r[0] for r in parsed.rows[:3]]


# --- a number with no fractional part is written without apostrophes in the real file ---------------------------------------


def bare_line(bare: dict[int, str], date="2017-03-10 01:00:00") -> str:
    """A line whose fields at the given positions are written without apostrophes."""
    values = list(TEMPLATE_FIELDS)
    values[0] = date
    for position, text in bare.items():
        values[position] = text
    return ",".join(v if i in bare else f"'{v}'" for i, v in enumerate(values))


def test_an_integer_may_be_written_without_apostrophes_as_the_real_file_does_and_means_the_same_as_with_them(quick_cfg, tmp_path, header):
    path = write(tmp_path, header, [bare_line({5: "390"}), bare_line({3: "-5", 23: "1", 22: "66"}), line(F5="390"), bare_line({5: "0"}, date="2017-03-10 02:00:00")])
    frame, _ = read(quick_cfg, path)
    assert frame["ore_pulp_flow"].tolist() == [390.0, 395.713, 390.0, 0.0]
    assert frame["starch_flow"].iloc[1] == -5.0 and frame["silica_pct"].iloc[1] == 1.0 and frame["iron_conc_pct"].iloc[1] == 66.0
    assert frame["row_id"].tolist() == [1, 2, 3, 4]


@pytest.mark.parametrize("token", ["1,5", "abc", "", "+1", "1e3", "1.5", "390 ", " 390", "١٢", "0x10", "--1", "-", "NaN"])
def test_anything_else_without_apostrophes_is_not_a_field(quick_cfg, tmp_path, header, token):
    """A decimal comma outside apostrophes would be two fields; text, a sign, an exponent, a space or an empty field are not integers."""
    with pytest.raises(SourceError) as error:
        read(quick_cfg, write(tmp_path, header, [line(), bare_line({5: token})]))
    assert error.value.rule_id == "V04" and error.value.problems[0]["line"] == len(header.split("\n")) + 1


def test_an_unquoted_date_is_not_a_date(quick_cfg, tmp_path, header):
    with pytest.raises(SourceError) as error:
        read(quick_cfg, write(tmp_path, header, [bare_line({0: "20170310"})]))
    assert error.value.rule_id == "V05" and error.value.problems[0]["column"] == "date"


def test_the_two_forms_of_line_are_read_into_the_same_fields(quick_cfg, tmp_path, header):
    from flotsilica.ingest import _fields

    assert _fields(line()) == TEMPLATE_FIELDS
    assert _fields(bare_line({3: "3019", 23: "1"})) == [*TEMPLATE_FIELDS[:3], "3019", *TEMPLATE_FIELDS[4:23], "1"]
    assert _fields(line(F5="390")) == _fields(bare_line({5: "390"}))
    assert _fields("") is None and _fields("'") is None and _fields(line()[:-1]) is None and _fields("garbage") is None
    assert _fields(line() + ",") is None and _fields("," + line()) is None
