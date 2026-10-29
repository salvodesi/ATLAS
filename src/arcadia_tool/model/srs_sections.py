"""Lists of SRS sections written as text (e.g. the row «Sezioni SRS principali» of the SA-1 sheets in Excel):
single sections and clauses (3.4.1, 3.6.3.2, A.3.3), groups of consecutive ones (4.8.1–4.8.5: from 4.8.1 to
4.8.5) and references to other documents (SUBSET-027, ERA_ERTMS_015560), which are not SRS items."""
import re
from dataclasses import dataclass, field

SECTION = r"(?:[A-Z]\.)?\d+(?:\.\d+)*"
SINGLE = re.compile(rf"^{SECTION}$")
RANGE = re.compile(rf"^({SECTION})\s*[-–—]\s*({SECTION})$")  # hyphen, en dash, em dash


@dataclass
class Reference:
    text: str  # as written
    start: str = ""
    end: str = ""  # a group: its last section
    external: bool = False  # another document: not an SRS item
    ids: list = field(default_factory=list)  # the sections it stands for (resolve)

    @property
    def is_range(self):
        return bool(self.end)


def parse_sections(text):
    """The references of a list separated by commas, semicolons or new lines."""
    result = []
    for token in re.split(r"[,;\n]", text or ""):
        token = token.strip().rstrip(".").strip()
        if not token:
            continue
        group = RANGE.match(token)
        if group:
            result.append(Reference(token, group[1], group[2]))
        elif SINGLE.match(token):
            result.append(Reference(token, token))
        else:
            result.append(Reference(token, external=True))
    return result


def expand(start, end, ordered_ids=()):
    """The sections of a group: same parent (4.8.1–4.8.5, A.3.7–A.3.10), the numbers from the first to the last;
    else those between the two in the order of the specification (ordered_ids) at the same depth."""
    head_a, _, last_a = start.rpartition(".")
    head_b, _, last_b = end.rpartition(".")
    if head_a == head_b and last_a.isdigit() and last_b.isdigit() and int(last_a) <= int(last_b):
        return [f"{head_a}.{n}" for n in range(int(last_a), int(last_b) + 1)]
    ordered = list(ordered_ids)
    if start in ordered and end in ordered and ordered.index(start) <= ordered.index(end):
        depth = start.count(".")
        return [i for i in ordered[ordered.index(start):ordered.index(end) + 1] if i.count(".") == depth]
    return [start, end]


def resolve(references, ordered_ids=()):
    """The sections of each reference (in place); returns the references."""
    for r in references:
        if not r.external:
            r.ids = expand(r.start, r.end, ordered_ids) if r.is_range else [r.start]
    return references
