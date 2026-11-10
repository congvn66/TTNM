"""Recalculate a saved answer after a number changes. No AI: only saved operation, arguments and current values."""

from .answer import answer_text, formula_display
from .calculator import calculate
from .evidence import EvidenceStore
from .pipeline import _computed
from .resolver import ResolvedOperand, _to_operand


def affected(interactions: list[dict], evidence_code: str) -> list[dict]:
    return [i for i in interactions if any(d["evidence_code"] == evidence_code for d in i.get("dependencies", []))]


def recompute(interaction: dict, store: EvidenceStore) -> dict:
    """Return a new interaction. The old answer moves into recomputation_log. The input is not changed."""
    args = interaction.get("operation_args") or {}
    rows = args.get("operands") or []
    if interaction.get("operation_name") in (None, "none") or not rows:
        return dict(interaction)
    items: list[ResolvedOperand] = []
    for row in rows:
        evidence = store.by_code.get(row["evidence_code"])
        if evidence is None:
            raise KeyError(f"evidence {row['evidence_code']} is not in the store")
        items.append(_to_operand(row["role"], evidence))
    operation = interaction["operation_name"]
    result = calculate(operation, [i.operand for i in items], args)
    updated = dict(interaction)
    log_entry = {"previous_answer_text": interaction["answer_text"], "previous_computed_result": interaction["computed_result"]}
    updated["recomputation_log"] = list(interaction.get("recomputation_log") or []) + [log_entry]
    updated["computed_result"] = _computed(result, items)
    updated["answer_text"] = answer_text(operation, items, result, args, [])
    updated["formula_display"] = formula_display(operation, items, result, args)
    return updated
