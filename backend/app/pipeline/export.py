"""Export (5F, D-146): the owner's transactions of a range as CSV or an Excel workbook, built
on the server from the stored rows, with the standard library only (csv, zipfile, XML).

- Never raw SMS text or a reference: only what the app shows (name, category, label, role).
- Dates and times in IST; amounts as numbers in rupees (paise / 100); a direction column.
- A text cell that starts with = + - @, a tab or a carriage return gets a leading ' so a
  spreadsheet never runs it as a formula (CSV and Excel alike).
- Excel: a Transactions sheet and a Summary sheet (Spent, Invested, Paid back, Net, Income,
  Spent by category, as the app works them out), bold header, frozen first row, column
  widths, Indian digit grouping (a custom number format).
"""

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from xml.sax.saxutils import escape

COLUMNS = (
    ("Date", 12), ("Time", 7), ("Name", 30), ("Category", 18), ("Label", 16),
    ("Counted as", 20), ("Money", 7), ("Amount", 14), ("Bank", 10), ("Account", 9),
    ("Confirmed by you", 10), ("Note", 28),
)  # fmt: skip
AMOUNT = 7  # the column of the amount: a number
DANGER = ("=", "+", "-", "@", "\t", "\r")
# Indian grouping for amounts (1,23,45,678.00), the usual Excel custom format for it.
INDIAN = r"[>=10000000]##\,##\,##\,##0.00;[>=100000]##\,##\,##0.00;##,##0.00"
_BAD_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")


def safe(value: object) -> object:
    """A text cell that a spreadsheet would read as a formula gets a leading '."""
    if isinstance(value, str) and value.startswith(DANGER):
        return "'" + value
    return value


@dataclass
class Sheet:
    name: str
    header: tuple[str, ...]
    widths: tuple[int, ...]
    rows: list[list[object]]
    amounts: frozenset[int] = frozenset()  # 0-based columns holding rupees


def to_csv(header: tuple[str, ...], rows: list[list[object]]) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([f"{v:.2f}" if isinstance(v, float) else safe(v) for v in row])
    return ("﻿" + out.getvalue()).encode("utf-8")  # a BOM: Excel opens UTF-8 (₹, names)


def _col(i: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    name = ""
    i += 1
    while i:
        i, rest = divmod(i - 1, 26)
        name = chr(65 + rest) + name
    return name


def _cell(ref: str, value: object, style: int) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}" s="{style}"><v>{value}</v></c>'
    text = escape(_BAD_XML.sub("", str(safe(value))))
    return f'<c r="{ref}" t="inlineStr" s="{style}"><is><t xml:space="preserve">{text}</t></is></c>'


def _sheet_xml(sheet: Sheet) -> str:
    cols = "".join(
        f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>'
        for i, w in enumerate(sheet.widths, 1)
    )
    rows = ['<row r="1">' + "".join(
        _cell(f"{_col(i)}1", h, 1) for i, h in enumerate(sheet.header)
    ) + "</row>"]  # fmt: skip
    for n, row in enumerate(sheet.rows, 2):
        cells = "".join(
            _cell(f"{_col(i)}{n}", v, 2 if i in sheet.amounts else 0) for i, v in enumerate(row)
        )
        rows.append(f'<row r="{n}">{cells}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f"<cols>{cols}</cols><sheetData>{''.join(rows)}</sheetData></worksheet>"
    )


STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    f'<numFmts count="1"><numFmt numFmtId="164" formatCode="{escape(INDIAN)}"/></numFmts>'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    "</cellXfs></styleSheet>"
)


def to_xlsx(sheets: list[Sheet]) -> bytes:
    """A minimal Office Open XML workbook: one worksheet per Sheet, inline strings."""
    out = io.BytesIO()
    main = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        overrides = "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
            'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-'
            'officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            f"{overrides}</Types>",
        )
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{main}/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        names = "".join(
            f'<sheet name="{escape(s.name)}" sheetId="{i}" r:id="rId{i}"/>'
            for i, s in enumerate(sheets, 1)
        )
        z.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            f'xmlns:r="{main}"><sheets>{names}</sheets></workbook>',
        )
        rels = "".join(
            f'<Relationship Id="rId{i}" Type="{main}/worksheet" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        styles_id = len(sheets) + 1
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'{rels}<Relationship Id="rId{styles_id}" Type="{main}/styles" Target="styles.xml"/>'
            "</Relationships>",
        )
        z.writestr("xl/styles.xml", STYLES)
        for i, sheet in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(sheet))
    return out.getvalue()
