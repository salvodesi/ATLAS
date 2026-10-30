"""Settings of the checks of a project, in checks.yaml (versioned with the model, shared with the team).

- Profiles: named sets of checks («Predefinito», «Gate SA»…); one is active and is the one «Verifica modello»
  runs. A profile has its checks, and for each check only what differs from the methodology: its parameters,
  its severity, its scope (the status and the domains of the sheets it applies to).
- Exceptions: findings accepted on purpose by the Design Authority, with the reason, who and when. An exception
  holds as long as its sheet does not change; then the finding comes back.
"""
import copy
import hashlib
from dataclasses import dataclass, field
from datetime import date

import yaml

from arcadia_tool.checks.params import params_of

DEFAULT_PROFILE = "Predefinito"
# Scope of a check by status of the sheet: any status, or only sheets in review or approved.
SCOPE_STATUS = {"all": "Tutte le schede", "review": "Solo schede in revisione o approvate",
                "approved": "Solo schede approvate"}
REVIEW_WORDS = ("revision", "rivist", "approvat", "decisa", "concordat")
APPROVED_WORDS = ("approvat", "decisa")
# Checks no longer in the catalogue: left out of the settings saved before (else «Verifica modello» would stop
# on unknown checks). SA2-12…14: the availability in the modes of the system functions, removed.
RETIRED = ("SA2-12", "SA2-13", "SA2-14")


@dataclass
class Profile:
    enabled: list = field(default_factory=list)
    params: dict = field(default_factory=dict)  # code → {name: value} (only the changed ones)
    severity: dict = field(default_factory=dict)  # code → E / A / I
    scope: dict = field(default_factory=dict)  # code → {"status": …, "domains": [uuid…]}

    @classmethod
    def from_data(cls, data):
        data = data if isinstance(data, dict) else {}

        def kept(values):
            return {c: v for c, v in dict(values or {}).items() if c not in RETIRED}
        return cls([c for c in data.get("enabled") or [] if c not in RETIRED], kept(data.get("params")),
                   kept(data.get("severity")), kept(data.get("scope")))

    def to_data(self, order=None):
        enabled = sorted(set(self.enabled), key=lambda c: order.get(c, 10 ** 6)) if order else list(self.enabled)
        data = {"enabled": enabled}
        for name in ("params", "severity", "scope"):
            value = {c: v for c, v in getattr(self, name).items() if v}
            if value:
                data[name] = dict(sorted(value.items(), key=lambda kv: order.get(kv[0], 10 ** 6) if order else 0))
        return data

    def param(self, code, name):
        value = (self.params.get(code) or {}).get(name)
        if value is not None:
            return value
        default = next((p.default for p in params_of(code) if p.name == name), None)
        return copy.deepcopy(default)

    def customized(self, code):
        """The check differs from the methodology (parameters, severity or scope)."""
        return bool(self.params.get(code) or self.severity.get(code) or self.scope.get(code))

    def reset(self, code):
        for name in ("params", "severity", "scope"):
            getattr(self, name).pop(code, None)


def fingerprint(element):
    """What an exception remembers of its sheet: when the sheet changes, the exception no longer holds."""
    text = yaml.safe_dump(element.values, sort_keys=True, allow_unicode=True) if element is not None else ""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


class ChecksConfig:
    def __init__(self, profiles=None, active=None, exceptions=None):
        self.profiles = profiles or {DEFAULT_PROFILE: Profile()}
        self.active = active if active in self.profiles else next(iter(self.profiles))
        self.exceptions = list(exceptions or [])

    # --- reading and writing --------------------------------------------------------------------

    @classmethod
    def from_data(cls, data):
        data = data if isinstance(data, dict) else {}
        profiles = {str(name): Profile.from_data(p) for name, p in (data.get("profiles") or {}).items()}
        exceptions = [e for e in data.get("exceptions") or [] if isinstance(e, dict) and e.get("code")]
        return cls(profiles or None, data.get("active"), exceptions)

    @classmethod
    def from_project_settings(cls, settings):
        """The settings of the first versions, in project.yaml («checks»): the profile «Predefinito»."""
        stored = (settings or {}).get("checks")
        if not isinstance(stored, dict):
            return cls()
        params = {}
        if stored.get("coding_domains"):
            params["SA5-13"] = {"coding_domains": list(stored["coding_domains"])}
        if stored.get("procedure_domain"):
            params["SA7-15"] = {"procedure_domain": stored["procedure_domain"]}
        if stored.get("fan_threshold"):
            params["IND-03"] = {"fan_threshold": stored["fan_threshold"]}
        return cls({DEFAULT_PROFILE: Profile(list(stored.get("enabled") or []), params)})

    def to_data(self):
        from arcadia_tool.checks import CHECKS
        order = {c.code: i for i, c in enumerate(CHECKS)}
        data = {"active": self.active, "profiles": {n: p.to_data(order) for n, p in self.profiles.items()}}
        if self.exceptions:
            data["exceptions"] = self.exceptions
        return data

    def dumps(self):
        return yaml.safe_dump(self.to_data(), sort_keys=False, allow_unicode=True)

    def copy(self):
        return ChecksConfig.from_data(copy.deepcopy(self.to_data()))

    def __eq__(self, other):
        return isinstance(other, ChecksConfig) and self.to_data() == other.to_data()

    # --- profiles -------------------------------------------------------------------------------

    @property
    def profile(self):
        return self.profiles[self.active]

    def add_profile(self, name, source=None):
        """A new profile, copy of `source` (the active one by default)."""
        base = self.profiles[source or self.active]
        self.profiles[name] = Profile.from_data(copy.deepcopy(base.to_data()))
        self.active = name

    def rename_profile(self, old, new):
        self.profiles = {new if n == old else n: p for n, p in self.profiles.items()}
        if self.active == old:
            self.active = new

    def remove_profile(self, name):
        if len(self.profiles) > 1:
            self.profiles.pop(name, None)
            if self.active == name:
                self.active = next(iter(self.profiles))

    # --- exceptions -----------------------------------------------------------------------------

    def exception_of(self, finding):
        """The exception recorded for a finding (same check, sheet and message), or None."""
        return next((e for e in self.exceptions if e.get("code") == finding.code
                     and e.get("element") == finding.element and e.get("message") == finding.message), None)

    def add_exception(self, finding, element, reason, author):
        self.remove_exception(finding)
        self.exceptions.append({"code": finding.code, "element": finding.element, "message": finding.message,
                                "fingerprint": fingerprint(element), "reason": reason, "author": author,
                                "date": date.today().isoformat()})

    def remove_exception(self, finding):
        self.exceptions = [e for e in self.exceptions if not (
            e.get("code") == finding.code and e.get("element") == finding.element
            and e.get("message") == finding.message)]


def in_status_scope(status, scope):
    s = (status or "").lower()
    if scope == "approved":
        return any(w in s for w in APPROVED_WORDS)
    if scope == "review":
        return any(w in s for w in REVIEW_WORDS)
    return True
