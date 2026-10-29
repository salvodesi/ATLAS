"""The SA-1 sheets of the functional domains kept in Excel (one worksheet per domain named after its ID, a title
row «DF01 name», the fields in the first column and their values in the second): read to import the principal SRS
sections of a domain."""
import re
from dataclasses import dataclass

import openpyxl

ID_AND_NAME = "id e nome"
PRINCIPAL = "sezioni srs principali"


@dataclass
class DomainSheet:
    sheet: str  # the worksheet
    ident: str  # DF01
    name: str
    principal: str  # the row «Sezioni SRS principali», as written
    note: str = ""  # the sheet contradicts itself (e.g. «ID e nome» of another domain)


def read_domain_sheets(path):
    """The worksheets of the workbook with a row «Sezioni SRS principali», in their order."""
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        result = []
        for ws in workbook.worksheets:
            values, title = {}, ""
            for row in ws.iter_rows(max_col=2, values_only=True):
                if not title and row and isinstance(row[0], str) and DOMAIN_ID.match(row[0].strip()):
                    title = row[0].strip()  # the title row: «DF01 name»
                if row and isinstance(row[0], str) and len(row) > 1:
                    values.setdefault(row[0].strip().lower(), row[1])
            if PRINCIPAL not in values:
                continue
            result.append(_sheet(ws.title, title, values))
        return result
    finally:
        workbook.close()


DOMAIN_ID = re.compile(r"^DF[0-9]+(?![0-9A-Za-z])", re.IGNORECASE)


def _sheet(sheet, title, values):
    """Its ID: the name of the worksheet (DF01), else the title row, else «ID e nome»; its name from the title
    row or «ID e nome». «ID e nome» of another domain is noted."""
    heading = str(values.get(ID_AND_NAME) or "").strip()
    sources = [s for s in (title, heading) if DOMAIN_ID.match(s)]
    ident = sheet.strip() if DOMAIN_ID.match(sheet.strip()) else (sources[0].split()[0] if sources else sheet)
    named = next((s for s in sources if s.split()[0].upper() == ident.upper()), title or heading)
    name = named.partition(" ")[2] if DOMAIN_ID.match(named) else named
    note = ""
    if heading and DOMAIN_ID.match(heading) and heading.split()[0].upper() != ident.upper():
        note = f"Nel foglio {sheet} il campo «ID e nome» indica «{heading}»: si usa {ident} (il nome del foglio)."
    return DomainSheet(sheet, ident, name.strip(), str(values[PRINCIPAL] or "").strip(), note)


def sheet_of(sheets, domain):
    """The sheet of a domain: by its ID (DF01), else by its name; None if none matches."""
    ident, name = (domain.get("id") or "").strip().upper(), (domain.get("name") or "").strip().lower()
    for s in sheets:
        if ident and (s.ident.upper() == ident or s.sheet.strip().upper() == ident):
            return s
    return next((s for s in sheets if name and s.name.lower() == name), None)
