"""The supported bootstrap operations, shared by checker and interpreter."""

RESOURCE_TYPE = "Catalog"
MODEL_TYPE = "Planner"
RETURN_TYPE = "DecisionResult"
PLAN_TYPE = "Patch"
EFFECTS = {"Snapshot": "resource", "Infer": "model", "Explore": "resource", "Commit": "resource"}
# Argument kinds and result kind. A state accepts a snapshot or simulation.
METHODS = {
    "source_fields_unchanged": (("state", "state"), "bool"),
    "valid_unit_arithmetic": (("state",), "bool"),
    "unresolved_units": (("state",), "int"),
}
PROPOSE_ARGS = ("snapshot", "string", "int")
SIMULATE_ARGS = ("plan",)
BRANCH_FORBIDDEN = {"snapshot", "propose", "explore", "select", "commit"}


def accepts(expected: str, actual: str) -> bool:
    return actual in {"snapshot", "simulated"} if expected == "state" else expected == actual
