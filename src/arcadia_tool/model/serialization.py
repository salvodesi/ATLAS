"""Deterministic YAML serialization: one file per element, fields in schema order.

Stable output keeps Git diffs and merges small and readable.
"""
import yaml

from arcadia_tool.model.element import Element, is_empty
from arcadia_tool.model.schema import KINDS_BY_NAME, TABLE


# libyaml (C) is several times faster than the pure Python implementation on thousands of files.
_BaseDumper = getattr(yaml, "CSafeDumper", yaml.SafeDumper)
_Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


class _Dumper(_BaseDumper):
    pass


def _represent_str(dumper, value):
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _represent_str)


def _ordered_values(element):
    schema = KINDS_BY_NAME[element.kind]
    out = {}
    known = set()
    for f in schema.fields:
        known.add(f.name)
        value = element.values.get(f.name)
        if is_empty(value):
            continue
        if f.type == TABLE:
            order = [c.name for c in f.columns]
            value = [
                {**{c: row[c] for c in order if not is_empty(row.get(c))},
                 **{k: row[k] for k in sorted(row) if k not in order and not is_empty(row[k])}}
                for row in value
            ]
        out[f.name] = value
    # Fields unknown to this version of the schema are preserved, not dropped.
    for name in sorted(set(element.values) - known):
        if not is_empty(element.values[name]):
            out[name] = element.values[name]
    return out


def dumps(element):
    data = {"kind": element.kind, "uuid": element.uuid, **_ordered_values(element)}
    return yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True,
                     default_flow_style=False, width=4096)


def loads(text):
    data = yaml.load(text, Loader=_Loader) or {}
    kind = data.pop("kind")
    uuid = data.pop("uuid")
    return Element(kind, uuid, data)
