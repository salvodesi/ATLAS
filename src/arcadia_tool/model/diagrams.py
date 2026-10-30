"""Graphic views of the SA, computed from the model (in the left panel, tab «Viste grafiche»).

The functional breakdown (SA-1 and SA-2) is one for the whole model: domains and their system functions. The other
views (the «diagram» kind) are composed by the user with elements that are already in the model: a dataflow with
domains, system functions and external actors, a chain or a scenario with the steps of a functional chain. A view
stores only what it shows and where (its «layout»); everything else (names, exchanges between the elements shown,
the data exchanged) is read from the model every time, so the view cannot contradict it.
"""
from collections import defaultdict
from dataclasses import dataclass, field

from arcadia_tool.model.element import natural_key
from arcadia_tool.model.schema import (DIAGRAM_BREAKDOWN, DIAGRAM_CHAIN, DIAGRAM_DATAFLOW, DIAGRAM_FUNCTIONS,
                                       DIAGRAM_LEVELS, DIAGRAM_SCENARIO)

DIAGRAM = "diagram"
# The groups of the «Viste grafiche» tab of the left panel, one for each type of view, each with its SA.
VIEW_GROUPS = (("SA-1 Domini funzionali", DIAGRAM_BREAKDOWN), ("SA-2 Funzioni per dominio", DIAGRAM_FUNCTIONS),
               ("SA-5 Dataflow funzionali", DIAGRAM_DATAFLOW),
               ("SA-7 Catene funzionali", DIAGRAM_CHAIN), ("SA-7 Scenari di scambio", DIAGRAM_SCENARIO))
# Domains and their functions: SA-1 (the domains opened one by one) and SA-2 (the domains open on their functions).
BREAKDOWN_TYPES = (DIAGRAM_BREAKDOWN, DIAGRAM_FUNCTIONS)
# The breakdown of the whole model, first in the group of its SA: {kind of the SA: (name, with the functions, type)}.
# SA-1 only the domains (their names, not to be opened), SA-2 every domain open on its functions. Computed, not
# stored: the users create their own with the domains and functions they choose.
BREAKDOWN_VIEWS = {"domain": ("Vista complessiva", False, DIAGRAM_BREAKDOWN),
                   "system_function": ("Vista complessiva", True, DIAGRAM_FUNCTIONS)}
DATAFLOW_KINDS = ("domain", "system_function", "external_actor")
BY_DOMAIN, BY_FUNCTION = DIAGRAM_LEVELS
STEP = "step:"

# Sizes of the elements of the dataflow and of the chain, shared with the drawing (ui.diagrams).
NODE_W, NODE_H = 220, 60
HEADER_H, PAD, GAP = 46, 16, 12
COLUMN_W = 430  # a block and the room for the labels of the arrows to the next column


def views_of(model, diagram_type):
    """The views of a type, by name."""
    return sorted((v for v in model.of_kind(DIAGRAM) if v.get("diagram_type") == diagram_type),
                  key=lambda v: natural_key(v.get("name") or ""))


def ident_and_name(element):
    return element.get("id") or "", element.get("name") or element.get("title") or ""


# --- what a view shows, and where ---------------------------------------------------------------------

def positions(view):
    """{key: (x, y) or None}: the elements in the view («None»: not placed yet, see auto_layout)."""
    result = {}
    for key, text in (view.get("layout") or {}).items():
        try:
            x, y = (float(v) for v in str(text).split(","))
            result[key] = (x, y)
        except ValueError:
            result[key] = None
    return result


def set_positions(view, placed):
    """Store what the view shows and where, sorted (stable files, small diffs)."""
    view.set("layout", {key: (f"{round(p[0])},{round(p[1])}" if p else "") for key, p in sorted(placed.items())})


def step_key(index):
    return f"{STEP}{index}"


def step_index(key):
    return int(key[len(STEP):]) if key.startswith(STEP) and key[len(STEP):].isdigit() else None


def missing(model, view):
    """Keys of the view whose element is no longer in the model (deleted) or whose step is no longer in the
    chain: they are not shown, and go away when the view is saved."""
    if view.get("diagram_type") == DIAGRAM_DATAFLOW:
        return [k for k in positions(view) if model.get(k) is None or model.get(k).kind not in DATAFLOW_KINDS]
    if view.get("diagram_type") in BREAKDOWN_TYPES:
        return [k for k in positions(view)
                if model.get(k) is None or model.get(k).kind not in ("domain", "system_function")]
    steps = len(chain_steps(model, view))
    return [k for k in positions(view) if step_index(k) is None or step_index(k) >= steps]


# --- functional breakdown (SA-1, SA-2) ---------------------------------------------------------------

@dataclass
class BreakdownFunction:
    uuid: str
    ident: str
    name: str
    clauses: int  # SRS items traced to it (SA-3, primary or secondary function)


@dataclass
class BreakdownDomain:
    uuid: str  # None: the functions without a domain
    ident: str
    name: str
    functions: list = field(default_factory=list)
    partial: bool = False  # in a view: only the functions added, not the domain


def view_breakdown(model, view):
    """The domains of a breakdown composed by the user. A domain added shows all its functions; functions added on
    their own are shown in the block of their domain, with only them («partial»: the block is always open)."""
    keys = set(positions(view))
    result = []
    for d in breakdown(model):
        if d.uuid in keys:
            result.append(d)
        else:
            chosen = [f for f in d.functions if f.uuid in keys]
            if chosen:
                result.append(BreakdownDomain(d.uuid, d.ident, d.name, chosen, partial=True))
    return result


def domain_of_function(model, uuid):
    e = model.get(uuid)
    return e.get("domain") if e is not None and e.kind == "system_function" else None


def _within(model, item, uuids):
    """The SRS item, or one of its parents, is among uuids."""
    seen = set()
    while item is not None and item.uuid not in seen:
        if item.uuid in uuids:
            return True
        seen.add(item.uuid)
        item = model.get(item.get("parent")) if item.get("parent") else None
    return False


def breakdown(model):
    """The domains, in the order of their IDs, each with its system functions; last the functions without a
    domain, if any."""
    # The SRS items of a function: those it is allocated to («Sezioni SRS»: from its sheet, «Alloca a sezioni e
    # clausole SRS…», the import of SA-2) and those of the SA-3 records naming it, unless one of their parents is.
    traced = defaultdict(set)
    for f in model.of_kind("system_function"):
        traced[f.uuid].update(u for u in f.get("sections") or [] if model.get(u) is not None)
    for record in model.of_kind("trace_record"):
        item = model.get(record.get("requirement"))
        if item is None:
            continue
        for f in {record.get("primary_function"), *(record.get("secondary_functions") or [])}:
            if f and not _within(model, item, traced[f]):
                traced[f].add(item.uuid)
    by_domain = defaultdict(list)
    domains = {d.uuid for d in model.of_kind("domain")}
    for f in model.of_kind("system_function"):
        ident, name = ident_and_name(f)
        by_domain[f.get("domain") if f.get("domain") in domains else None].append(
            BreakdownFunction(f.uuid, ident, name, len(traced[f.uuid])))
    result = []
    for d in sorted(model.of_kind("domain"), key=lambda d: natural_key(d.get("id") or d.get("name") or "")):
        ident, name = ident_and_name(d)
        result.append(BreakdownDomain(d.uuid, ident, name, by_domain[d.uuid]))
    if by_domain[None]:
        result.append(BreakdownDomain(None, "", "Funzioni senza dominio", by_domain[None]))
    for d in result:
        d.functions.sort(key=lambda f: natural_key(f.ident or f.name))
    return result


# --- functional dataflow (SA-5) ------------------------------------------------------------------------

@dataclass
class Node:
    key: str
    kind: str
    ident: str
    name: str
    container: str = None  # the domain whose block holds the function
    outside: int = 0  # exchanges with elements not in the view


@dataclass
class Exchange:
    uuid: str
    ident: str
    data: str  # the exchange item, or the name of the exchange
    nature: str


@dataclass
class Edge:
    source: str
    target: str
    exchanges: list = field(default_factory=list)

    @property
    def event(self):
        return bool(self.exchanges) and all(x.nature == "EVENT" for x in self.exchanges)

    @property
    def nature(self):
        """The line of the arrow: EVENT or OPERATION when every exchange is one, else FLOW."""
        natures = {x.nature for x in self.exchanges}
        return natures.pop() if len(natures) == 1 and natures <= {"EVENT", "OPERATION"} else "FLOW"


@dataclass
class Container:
    key: str  # the domain
    ident: str
    name: str
    members: list = field(default_factory=list)  # keys of its functions in the view


@dataclass
class Dataflow:
    nodes: dict = field(default_factory=dict)
    containers: dict = field(default_factory=dict)
    edges: list = field(default_factory=list)


def dataflow(model, view):
    """The elements of a dataflow view and the exchanges between them.

    A function is drawn inside the block of its domain. A domain added alone is a block; its exchanges are those of
    all its functions not drawn on their own. An exchange between two elements of the view is an arrow (several
    between the same two elements share it); one with an element not in the view is counted on the element."""
    keys = [k for k in positions(view) if model.get(k) is not None and model.get(k).kind in DATAFLOW_KINDS]
    added = set(keys)
    result = Dataflow()
    for key in keys:
        e = model.get(key)
        ident, name = ident_and_name(e)
        if e.kind == "system_function":
            domain = model.get(e.get("domain")) if e.get("domain") else None
            node = Node(key, e.kind, ident, name, container=domain.uuid if domain is not None else None)
            result.nodes[key] = node
            if domain is not None:
                if domain.uuid not in result.containers:
                    result.containers[domain.uuid] = Container(domain.uuid, *ident_and_name(domain))
                result.containers[domain.uuid].members.append(key)
        else:
            result.nodes[key] = Node(key, e.kind, ident, name)
    for c in result.containers.values():
        result.nodes.pop(c.key, None)  # a domain with functions in the view: their block, not a block of its own
        c.members.sort(key=lambda k: natural_key(result.nodes[k].ident or result.nodes[k].name))

    def end(uuid):
        if uuid in result.nodes:
            return uuid
        e = model.get(uuid) if uuid else None
        domain = e.get("domain") if e is not None and e.kind == "system_function" else None
        if domain in added:  # the domain is in the view: it stands for its functions not drawn on their own
            return domain
        return None

    edges = {}
    for fe in model.of_kind("functional_exchange"):
        s, t = end(fe.get("source")), end(fe.get("target"))
        if s and t and s != t:
            item = model.get(fe.get("exchange_item")) if fe.get("exchange_item") else None
            data = (item.get("name") or item.get("id")) if item is not None else fe.get("name")
            nature = fe.get("nature") or (item.get("nature") if item is not None else None)
            edges.setdefault((s, t), Edge(s, t)).exchanges.append(
                Exchange(fe.uuid, fe.get("id") or "", data or "", nature or ""))
        elif s and not t and s in result.nodes:
            result.nodes[s].outside += 1
        elif t and not s and t in result.nodes:
            result.nodes[t].outside += 1
    for edge in edges.values():
        edge.exchanges.sort(key=lambda x: natural_key(x.ident))
    result.edges = list(edges.values())
    return result


CONNECTABLE = ("system_function", "external_actor")


def exchange_items_for(model, nature):
    """The data of the dictionary (SA-6) that a connector of that nature can carry: those of that nature or with
    no nature, the ones not carried by any exchange first (e.g. left by an exchange deleted)."""
    used = {fe.get("exchange_item") for fe in model.of_kind("functional_exchange")}
    items = [i for i in model.of_kind("exchange_item") if (i.get("nature") or nature) == nature]
    return sorted(items, key=lambda i: (i.uuid in used, natural_key(i.get("id") or i.get("name") or "")))


def same_exchange(model, source, target, item=None, name=None):
    """The exchange already carrying a datum from source to target (the datum by uuid, or a new one by its name),
    or None: a second one would duplicate it (check SA5-10)."""
    for fe in model.of_kind("functional_exchange"):
        if (fe.get("source"), fe.get("target")) != (source, target):
            continue
        carried = model.get(fe.get("exchange_item")) if fe.get("exchange_item") else None
        if item is not None and fe.get("exchange_item") == item:
            return fe
        if name and carried is not None and (carried.get("name") or "").strip().casefold() == name.strip().casefold():
            return fe
    return None


def unused_items(model, uuids):
    """Of the data given, those that no exchange carries any more."""
    used = {fe.get("exchange_item") for fe in model.of_kind("functional_exchange")}
    return [u for u in dict.fromkeys(uuids) if u and u not in used and model.get(u) is not None]


def container_rect(df, placed, key):
    """(x, y, w, h) of the block of a domain around its functions in the view."""
    members = [placed[k] for k in df.containers[key].members if placed.get(k)]
    if not members:
        return None
    left, top = min(p[0] for p in members), min(p[1] for p in members)
    right, bottom = max(p[0] for p in members) + NODE_W, max(p[1] for p in members) + NODE_H
    return left - PAD, top - HEADER_H, right - left + 2 * PAD, bottom - top + HEADER_H + PAD


def auto_layout(df, placed=None):
    """Positions of the elements of a dataflow: those already placed stay where they are (placed), the others are
    put in place. Without placed elements, all of them in columns, from the producers to the users."""
    placed = {k: p for k, p in (placed or {}).items() if p and k in df.nodes}
    todo = [k for k in df.nodes if k not in placed]
    if not todo:
        return placed
    if not placed:
        return _layered(df)
    for key in todo:
        node = df.nodes[key]
        siblings = [placed[k] for k in df.containers[node.container].members
                    if k in placed] if node.container else []
        if siblings:  # in the block of its domain, below the others
            x = siblings[0][0]
            y = max(p[1] for p in siblings) + NODE_H + GAP
        else:  # to the right of what is there
            x = max(p[0] for p in placed.values()) + COLUMN_W
            y = min(p[1] for p in placed.values())
        placed[key] = (x, y)
    return placed


def _unit(df, key):
    node = df.nodes[key]
    return node.container or key


def _layered(df):
    units = list(dict.fromkeys(_unit(df, k) for k in df.nodes))
    links = {(_unit(df, e.source), _unit(df, e.target)) for e in df.edges}
    links = sorted((a, b) for a, b in links if a != b)
    # Exchanges back towards an element already met (two domains that exchange data both ways) do not push the
    # columns: they are found with a depth-first visit and left out of the layering.
    state, back = {}, set()

    def visit(unit):
        state[unit] = "open"
        for a, b in links:
            if a == unit:
                if state.get(b) == "open":
                    back.add((a, b))
                elif b not in state:
                    visit(b)
        state[unit] = "done"

    for unit in units:
        if unit not in state:
            visit(unit)
    forward = [link for link in links if link not in back]
    layer = {u: 0 for u in units}
    for _ in range(len(units)):  # longest path from the producers
        changed = False
        for a, b in forward:
            if layer[b] < layer[a] + 1:
                layer[b] = layer[a] + 1
                changed = True
        if not changed:
            break
    placed, column_y = {}, defaultdict(lambda: 40)
    for unit in units:
        x, y = 40 + layer[unit] * COLUMN_W, column_y[layer[unit]]
        if unit in df.containers:
            members = df.containers[unit].members
            for i, key in enumerate(members):
                placed[key] = (x + PAD, y + HEADER_H + i * (NODE_H + GAP))
            height = HEADER_H + len(members) * (NODE_H + GAP) - GAP + PAD
        else:
            placed[unit] = (x + PAD, y)
            height = NODE_H
        column_y[layer[unit]] = y + height + 40
    return placed


# --- functional chain and scenario (SA-7) ----------------------------------------------------------------

@dataclass
class Step:
    index: int
    key: str
    cycle: str
    function: str  # uuid
    function_ident: str
    function_name: str
    domain: str
    domain_ident: str
    domain_name: str
    what: str
    data: str
    nature: str
    exchange: str
    bounce: bool = False  # back to a domain (or function) already passed, after another one (rule D4)

    def unit(self, level):
        return self.function if level == BY_FUNCTION or not self.domain else self.domain


def chain_steps(model, view):
    """Every step of the chain of the view («Percorso» of its sheet), in order."""
    chain = model.get(view.get("chain")) if view.get("chain") else None
    if chain is None:
        return []
    steps = []
    for i, row in enumerate(chain.get("steps") or []):
        function = model.get(row.get("function")) if row.get("function") else None
        domain = model.get(function.get("domain")) if function is not None and function.get("domain") else None
        f_ident, f_name = ident_and_name(function) if function is not None else ("", "")
        d_ident, d_name = ident_and_name(domain) if domain is not None else ("", "")
        steps.append(Step(i, step_key(i), str(row.get("cycle") or ""),
                          function.uuid if function is not None else None, f_ident, f_name,
                          domain.uuid if domain is not None else None, d_ident, d_name,
                          row.get("what") or "", row.get("data") or "", row.get("nature") or "",
                          row.get("exchange") if model.get(row.get("exchange") or "") is not None else None))
    return steps


def level(view):
    return view.get("level") or BY_DOMAIN


def shown_steps(model, view):
    """The steps the view shows, in the order of the chain, with the returns to a domain (or function) already
    passed marked (rule D4)."""
    keys = set(positions(view))
    steps = [s for s in chain_steps(model, view) if s.key in keys]
    seen, previous = set(), None
    for s in steps:
        unit = s.unit(level(view))
        s.bounce = unit is not None and unit in seen and unit != previous
        seen.add(unit)
        previous = unit
    return steps


STEP_W, STEP_H, STEP_DX = 170, 190, 220


def chain_layout(steps, placed=None):
    """Positions of the steps of a chain: those placed stay, the others in a row after them."""
    placed = {k: p for k, p in (placed or {}).items() if p}
    x = max((p[0] for p in placed.values()), default=40 - STEP_DX) + STEP_DX
    for s in steps:
        if s.key not in placed:
            placed[s.key] = (x, 60)
            x += STEP_DX
    return placed


@dataclass
class Lifeline:
    key: str
    ident: str
    name: str
    actor: bool = False


@dataclass
class Message:
    source: str
    target: str
    label: str
    ident: str
    nature: str
    cycle: str
    step: int


@dataclass
class Scenario:
    lifelines: list = field(default_factory=list)
    messages: list = field(default_factory=list)


def scenario(model, view):
    """The exchanges of the steps shown, in order: one lifeline for each domain (or function) and external actor.
    A step with its exchange is a message from the producer to the user of the exchange; without one, from the
    step to the next one, with the data it produces."""
    by = level(view)
    steps = shown_steps(model, view)
    lifelines = {}

    def lifeline(uuid):
        e = model.get(uuid) if uuid else None
        if e is None:
            return None
        if e.kind == "system_function" and by == BY_DOMAIN and model.get(e.get("domain") or ""):
            e = model.get(e.get("domain"))
        if e.uuid not in lifelines:
            lifelines[e.uuid] = Lifeline(e.uuid, *ident_and_name(e), actor=e.kind == "external_actor")
        return e.uuid

    result = Scenario()
    for i, s in enumerate(steps):
        fe = model.get(s.exchange) if s.exchange else None
        if fe is not None:
            source, target = lifeline(fe.get("source")), lifeline(fe.get("target"))
            item = model.get(fe.get("exchange_item")) if fe.get("exchange_item") else None
            label = (item.get("name") if item is not None else None) or fe.get("name") or s.data
            nature = s.nature or fe.get("nature") or ""
            ident = fe.get("id") or ""
        else:
            source = lifeline(s.function)
            target = lifeline(steps[i + 1].function) if i + 1 < len(steps) else None
            label, nature, ident = s.data, s.nature, ""
        if source is None:
            continue
        result.messages.append(Message(source, target or source, label or s.what, ident, nature, s.cycle, s.index))
    result.lifelines = list(lifelines.values())  # in the order they enter the scenario
    return result


# --- adding elements ------------------------------------------------------------------------------------

@dataclass
class Addable:
    key: str
    kind: str
    ident: str
    name: str
    group: str  # heading of the list: the kind, or the domain of a function


def addable(model, view):
    """The elements of the model that can be added to the view (those not in it yet)."""
    keys = set(positions(view))
    result = []
    if view.get("diagram_type") in BREAKDOWN_TYPES:
        domains = breakdown(model)
        result = [Addable(d.uuid, "domain", d.ident, d.name, "Domini funzionali")
                  for d in domains if d.uuid is not None and d.uuid not in keys]
        for d in domains:
            if d.uuid is None or d.uuid in keys:
                continue  # a domain in the view shows all its functions already
            heading = " · ".join(p for p in (d.ident, d.name) if p)
            result += [Addable(f.uuid, "system_function", f.ident, f.name, heading)
                       for f in d.functions if f.uuid not in keys]
        return result
    if view.get("diagram_type") == DIAGRAM_DATAFLOW:
        for actor in model.of_kind("external_actor"):
            if actor.uuid not in keys:
                result.append(Addable(actor.uuid, actor.kind, *ident_and_name(actor), "Attori esterni"))
        for d in breakdown(model):
            if d.uuid is not None and d.uuid not in keys:
                result.append(Addable(d.uuid, "domain", d.ident, d.name, "Domini funzionali"))
        for d in breakdown(model):
            heading = " · ".join(p for p in (d.ident, d.name) if p)
            for f in d.functions:
                if f.uuid not in keys:
                    result.append(Addable(f.uuid, "system_function", f.ident, f.name, heading))
        return result
    for s in chain_steps(model, view):
        if s.key not in keys:
            what = s.domain_ident if level(view) == BY_DOMAIN and s.domain_ident else s.function_ident
            result.append(Addable(s.key, "step", f"Passo {s.index + 1}", f"{what} · {s.what}".strip(" ·"),
                                  "Passi della catena"))
    return result


def new_view_layout(model, diagram_type, chain=None):
    """What a new view shows: nothing for a breakdown or a dataflow (the user adds the elements), every step for a
    chain or a scenario (the user can take some away)."""
    if diagram_type in (*BREAKDOWN_TYPES, DIAGRAM_DATAFLOW) or chain is None:
        return {}
    element = model.get(chain)
    return {step_key(i): "" for i in range(len(element.get("steps") or []))} if element is not None else {}
