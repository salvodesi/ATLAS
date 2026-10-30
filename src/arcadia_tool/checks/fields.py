"""Where the problem of each check is in the sheet that violates it: the name of a field of the schema, or «@srs»
for the traceability card of the sheet (SRS items of a domain or function, voce madre and logical function of a
derived requirement). A double click on a finding opens the sheet there. A finding may name another field (e.g.
the first empty one); none: the top of the sheet."""

SRS_CARD = "@srs"

CHECK_FIELDS = {
    "GEN-01": "id", "GEN-02": "id", "GEN-03": "id", "GEN-04": "name",
    "A4-01": "primary_domain", "A4-02": "contributing_domains", "A4-03": "contributing_domains",
    "A4-04": "primary_domain", "A4-05": "primary_domain", "A4-06": "category", "A4-07": "category",
    "A4-08": "category", "A4-09": "replaces",
    "SA1-01": "mission", "SA1-02": "team", "SA1-03": "team", "SA1-04": "team", "SA1-05": SRS_CARD,
    "SA1-06": SRS_CARD, "SA1-07": "name", "SA1-08": "planned_components", "SA1-09": SRS_CARD,
    "SA1-10": "exclusion_reason",
    "SA2-01": "domain", "SA2-02": "id", "SA2-03": "name", "SA2-04": "name", "SA2-05": "name", "SA2-06": "name",
    "SA2-07": SRS_CARD, "SA2-08": SRS_CARD, "SA2-09": SRS_CARD, "SA2-10": "new_reason", "SA2-11": "related_adrs",
    "SA2-15": "rows_452", "SA2-17": "proposed_component",
    "SA3-01": "requirement", "SA3-02": "requirement", "SA3-03": "outcome", "SA3-04": "b5_question",
    "SA3-05": "primary_function", "SA3-06": "secondary_functions", "SA3-07": "outcome", "SA3-08": "exchange_items",
    "SA3-09": "exchange_items", "SA3-10": "outcome", "SA3-11": "primary_function", "SA3-12": "primary_function",
    "SA3-13": "secondary_functions", "SA3-14": "primary_function",
    "SA4-01": SRS_CARD, "SA4-02": SRS_CARD, "SA4-03": "id", "SA4-04": "obligation", "SA4-05": "domain",
    "SA4-06": SRS_CARD, "SA4-07": "domain", "SA4-08": "b6_scheme", "SA4-09": "domain", "SA4-11": SRS_CARD,
    "SA4-12": SRS_CARD,
    "SA5-01": "source", "SA5-02": "target", "SA5-03": "target", "SA5-04": "target", "SA5-05": "source",
    "SA5-06": "exchange_item", "SA5-07": "nature", "SA5-08": "production_condition", "SA5-09": "id",
    "SA5-10": "exchange_item", "SA5-11": "status", "SA5-12": "clauses", "SA5-13": "exchange_item",
    "SA6-03": "nature", "SA6-04": "elements", "SA6-05": "elements", "SA6-06": "elements", "SA6-07": "srs_origin",
    "SA6-08": "name",
    "SA7-01": "steps", "SA7-02": "steps", "SA7-03": "steps", "SA7-04": "steps", "SA7-05": "trigger",
    "SA7-06": "steps", "SA7-07": "steps", "SA7-08": "steps", "SA7-09": "steps", "SA7-10": "steps",
    "SA7-11": "steps", "SA7-12": "adrs", "SA7-13": "responsible_domain", "SA7-14": "steps", "SA7-15": "steps",
    "SA7-16": "variants",
    "LA1-01": "parent", "LA1-05": "responsibility", "LA1-06": "safety_constraints", "LA1-08": "name",
    "LA2-01": "refines", "LA2-02": "component", "LA2-03": "component", "LA2-04": "parent", "LA2-05": "parent",
    "LA2-06": "id", "LA2-07": "contributes_to", "LA2-08": SRS_CARD, "LA2-09": SRS_CARD, "LA2-10": SRS_CARD,
    "LA2-11": "component", "LA2-12": "name", "LA2-13": "source", "LA2-14": "refines",
    "LA3-01": "target", "LA3-02": "realizes", "LA3-04": "realizes", "LA3-05": "realizes", "LA3-06": "exchange_item",
    "LA3-07": "realizes", "LA3-08": "id", "LA3-09": "exchange_item", "LA3-10": "cycle_rw",
    "LA4-01": "chain", "LA4-02": "steps", "LA4-03": "steps", "LA4-04": "steps", "LA4-05": "steps",
    "LA4-06": "steps", "LA4-07": "steps", "LA4-08": "steps", "LA4-09": "outcome", "LA4-10": "chain",
    "EPBS-01": "domains", "EPBS-02": "referent", "EPBS-03": "independent_verifier", "EPBS-04": "domains",
    "EPBS-05": "design_authority", "EPBS-06": "members",
    "X-01": "superseded_by", "X-02": "decision", "X-03": "clause", "X-04": "clause",
    "IND-01": "steps",
    "VER-01": "domain", "VER-02": "primary_domain", "VER-04": "component",
}
