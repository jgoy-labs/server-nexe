"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/files/loaders/data.py
Description: Data loaders — CSV, JSON and XML turned into text worth chunking.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────

ADR-008 E3 (#1070). These three are parsed because their raw form chunks
badly: a CSV row separated from its header is a line of bare values, and a
minified JSON or XML export is one enormous line. Each loader falls back to
the raw text when the file does not parse — a malformed file is still a text
file, and indexing it as written beats refusing it.

Security, the part that must not drift:

* XML goes through `safe_xml_parser()` — entities are NOT resolved, no DTD is
  loaded and nothing is fetched from the network (XXE, billion laughs). The
  EPUB loader parses its XML with the same parser.
* JSON is `json.loads`; nothing is ever unpickled or evaluated. (YAML is not
  parsed at all — see `text.py`.)
"""

from __future__ import annotations

import csv
import io
import json
import logging
from pathlib import Path

from core.files.loaders import TextBudget, register_loader
from core.files.loaders.text import read_text_with_fallback

logger = logging.getLogger(__name__)

#: Delimiters the CSV sniffer may pick. `;` is what Excel writes in locales with
#: a decimal comma (ca/es), so a plain `,` default would split nothing there.
_CSV_DELIMITERS = ",;\t|"


def safe_xml_parser():
    """The only XML parser the loaders use: no entities, no DTD, no network."""
    from lxml import etree

    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
    )


def _sniff_dialect(sample: str):
    """The sniffer first; when it gives up (it does on ragged rows), the
    delimiter the header line uses most, else a plain comma."""
    try:
        return csv.Sniffer().sniff(sample, delimiters=_CSV_DELIMITERS)
    except csv.Error:
        header = sample.split("\n", 1)[0]
        best = max(_CSV_DELIMITERS, key=header.count)

        class _Dialect(csv.excel):
            delimiter = best if header.count(best) else ","

        return _Dialect


@register_loader([".csv"])
def load_csv_file(file_path: Path) -> str:
    """One block per row, each value next to its column name.

    `Row 3: city: Girona; price: 12` retrieves on its own; a chunk that starts
    mid-table still says what every number is.
    """
    raw = read_text_with_fallback(file_path)
    if not raw.strip():
        return raw
    reader = csv.reader(io.StringIO(raw), _sniff_dialect(raw[:8192]))
    try:
        header = [h.strip() for h in next(reader)]
    except StopIteration:
        return raw
    budget = TextBudget(sep="\n\n")
    for idx, row in enumerate(reader, start=1):
        if not any(cell.strip() for cell in row):
            continue
        pairs = []
        for col, value in enumerate(row):
            name = header[col] if col < len(header) and header[col] else f"col{col + 1}"
            pairs.append(f"  {name}: {value.strip()}")
        budget.add(f"Row {idx}:\n" + "\n".join(pairs))
    if not budget.parts:  # header only
        return raw
    return budget.text()


@register_loader([".json"])
def load_json_file(file_path: Path) -> str:
    raw = read_text_with_fallback(file_path)
    try:
        data = json.loads(raw)
    except ValueError:
        logger.info("JSON %s does not parse; indexing it as written", file_path.name)
        return raw
    text = json.dumps(data, indent=2, ensure_ascii=False)
    budget = TextBudget()
    budget.add(text)
    return text


@register_loader([".xml"])
def load_xml_file(file_path: Path) -> str:
    from lxml import etree

    try:
        tree = etree.parse(str(file_path), safe_xml_parser())  # nosec B320 - safe_xml_parser: no entities/DTD/network
    except etree.XMLSyntaxError:
        logger.info("XML %s does not parse; indexing it as written", file_path.name)
        return read_text_with_fallback(file_path)
    etree.indent(tree, space="  ")
    text = etree.tostring(tree, encoding="unicode")
    budget = TextBudget()
    budget.add(text)
    return text
