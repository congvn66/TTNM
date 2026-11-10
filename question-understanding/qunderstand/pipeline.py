"""One question in, one interaction record out, in the format of data_design.pdf section 4.2."""

import hashlib
from dataclasses import dataclass, field

from . import guards
from .answer import LABELS, answer_text, formula_display
from .calculator import OK, CalcResult, calculate
from .evidence import EvidenceStore
from .numbers import as_json_number
from .parsers.base import ParseFailure, Parser
from .request import QueryRequest
from .resolver import CLARIFY, CONFLICT, NOT_FOUND, Resolved, ResolvedOperand, Stop, related_series, resolve
from .text import tokens


@dataclass
class Session:
    """What the conversation is about. Passed to the parser so follow-up questions keep their scope."""

    history: list[dict] = field(default_factory=list)
    pending_options: list = field(default_factory=list)

    def last_request(self) -> QueryRequest | None:
        return self.history[-1]["request_obj"] if self.history else None


def _qa_code(document_code: str, question: str, salt: int) -> str:
    digest = hashlib.sha1(f"{document_code}|{question}|{salt}".encode()).hexdigest()[:10]
    return f"QA_{digest.upper()}"


def _dependency_role(operation: str, operand) -> str:
    if operand.text is not None:
        return "context_text"
    return "comparison_group" if operation == "rank_group" else "direct_operand"


def _input_row(item: ResolvedOperand) -> dict:
    evidence, op = item.evidence, item.operand
    return {"param_key": op.param_key, "evidence_code": evidence.code, "role": op.role, "series_name": op.label, "time_period": op.period,
            "value": as_json_number(op.value), "unit": op.unit.label, "data_status": op.data_status, "extraction_method": evidence.extraction_method,
            "verification_status": evidence.verification_status, "page": evidence.page, "bbox": evidence.location.get("bbox")}


def _computed(result: CalcResult, items: list[ResolvedOperand]) -> dict:
    ranking = [{**{k: as_json_number(v) if k in {"metric", "base_val", "target_val"} else v for k, v in row.items()}} for row in result.ranking]
    data = {"status": result.status, "value": as_json_number(result.value), "unit": result.unit_label, "is_tie": result.is_tie,
            "div_by_zero": result.div_by_zero, "ranking": ranking, "excluded": result.excluded, "problem_keys": result.problem_keys,
            "inputs": [_input_row(i) for i in items]}
    if "absolute_change" in result.extra:
        data["absolute_change"] = as_json_number(result.extra["absolute_change"])
        data["absolute_unit"] = result.extra["absolute_unit"]
    return data


def build_args(request: QueryRequest, items: list[ResolvedOperand]) -> dict:
    args = {"operands": [{"param_key": i.operand.param_key, "role": i.operand.role, "evidence_code": i.evidence.code} for i in items]}
    if request.operation == "rank_group":
        args["metric_type"] = request.metric_type or "value"
        args["order"] = request.order
        if request.base_period:
            args["base_period"] = request.base_period
        if request.target_period:
            args["target_period"] = request.target_period
    if request.mode:
        args["mode"] = request.mode
    if request.output_unit:
        args["output_unit"] = request.output_unit
    units = {i.operand.unit.label for i in items if i.operand.unit.label}
    if len(units) == 1:
        args["canonical_unit"] = next(iter(units))
    return args


def _scope(request: QueryRequest | None, items: list[ResolvedOperand]) -> str:
    if request is None or not items:
        return ""
    names = list(dict.fromkeys(i.operand.label for i in items))
    periods = list(dict.fromkeys(i.operand.period for i in items if i.operand.period))
    label = LABELS.get(request.operation or "", "")
    return f"Đang xét: {', '.join(names)}" + (f"; kỳ: {', '.join(periods)}" if periods else "") + (f"; phép tính: {label}" if label else "")


def _record(store: EvidenceStore, question: str, session: Session | None, *, operation: str, args: dict, formula: str, text: str, computed: dict,
            dependencies: list[dict], clarification: dict | None = None, scope: str = "", parser_name: str = "", warnings: list[str] | None = None) -> dict:
    salt = len(session.history) if session else 0
    return {"qa_code": _qa_code(store.document_code, question, salt), "document_code": store.document_code, "question_text": question,
            "operation_name": operation, "operation_args": args, "formula_display": formula, "answer_text": text, "computed_result": computed,
            "dependencies": dependencies, "recomputation_log": [], "clarification": clarification, "scope": scope, "parser": parser_name,
            "warnings": warnings or []}


def _stop_record(store, question, session, status: str, message: str, *, options=None, related=None, reason=None, parser_name="") -> dict:
    computed = {"status": status, "value": None, "unit": "", "is_tie": False, "div_by_zero": False, "ranking": [], "excluded": [], "problem_keys": [], "inputs": [],
                "related_series": related or [], "reason": reason}
    clarification = None
    if options is not None and status in {CLARIFY, CONFLICT}:
        clarification = {"question": message, "options": [{"label": o.label, "request": o.request.to_dict()} for o in options]}
    return _record(store, question, session, operation="none", args={}, formula="", text=message, computed=computed, dependencies=[],
                   clarification=clarification, parser_name=parser_name)


def run_request(store: EvidenceStore, question: str, request: QueryRequest, session: Session | None = None, parser_name: str = "", *, user_chose: bool = False, use_guards: bool = True) -> dict:
    """Everything after parsing. A chosen option also enters here, with no AI call and without the ambiguity checks: the user has decided."""
    if not user_chose and use_guards:
        request = guards.guard_before_resolve(question, request)
    if request.intent == "clarify":
        record = _stop_record(store, question, session, CLARIFY, request.question, options=request.options, reason=request.reason, parser_name=parser_name)
        _remember(session, question, request, record, request.options)
        return record
    if request.intent == "unanswerable":
        message = request.reason or "Báo cáo không có thông tin để trả lời câu hỏi này."
        related = _related_for(store, question)
        if related:
            message += " Các chỉ tiêu liên quan có trong báo cáo: " + ", ".join(related) + "."
        record = _stop_record(store, question, session, NOT_FOUND, message, related=related, parser_name=parser_name)
        _remember(session, question, request, record)
        return record

    resolved = resolve(store, request)
    if isinstance(resolved, Stop):
        message = resolved.message
        if resolved.related and resolved.status == NOT_FOUND:
            message += " Các chỉ tiêu liên quan có trong báo cáo: " + ", ".join(resolved.related) + "."
        record = _stop_record(store, question, session, resolved.status, message, options=resolved.options, related=resolved.related, parser_name=parser_name)
        _remember(session, question, request, record, resolved.options)
        return record
    follow_up = None if user_chose or not use_guards else guards.guard_after_resolve(question, resolved, store)
    if follow_up is not None:
        record = _stop_record(store, question, session, CLARIFY, follow_up.question, options=follow_up.options, reason=follow_up.reason, parser_name=parser_name)
        _remember(session, question, request, record, follow_up.options)
        return record
    return _finish(store, question, resolved, session, parser_name)


def _finish(store, question, resolved: Resolved, session, parser_name) -> dict:
    request, items = resolved.request, resolved.operands
    args = build_args(request, items)
    result = calculate(request.operation, [i.operand for i in items], args)
    deps = [{"evidence_code": i.evidence.code, "dependency_role": _dependency_role(request.operation, i.operand), "param_key": i.operand.param_key} for i in items]
    for note in resolved.context:
        key = note.code.removeprefix("EVD_")
        if not any(d["evidence_code"] == note.code for d in deps):
            deps.append({"evidence_code": note.code, "dependency_role": "context_text", "param_key": key})
    text = answer_text(request.operation, items, result, args, resolved.warnings)
    if resolved.context and result.status == OK:
        text += " Căn cứ: " + " ".join(f"{n.text_content.rstrip('.')} (trang {n.page})." for n in resolved.context)
    record = _record(store, question, session, operation=request.operation, args=args, formula=formula_display(request.operation, items, result, args), text=text,
                     computed=_computed(result, items), dependencies=deps, scope=_scope(request, items), parser_name=parser_name, warnings=list(resolved.warnings) + list(result.warnings))
    _remember(session, question, request, record)
    return record


def _related_for(store: EvidenceStore, question: str) -> list[str]:
    stop = {"cua", "cong", "ty", "trong", "la", "bao", "nhieu", "nam", "quy", "thang"}
    useful = " ".join(t for t in tokens(question) if t not in stop and not t.isdigit())
    return related_series(store, useful, 3)


def _remember(session, question, request, record, options=None):
    if session is None:
        return
    session.pending_options = list(options or [])
    session.history.append({"question": question, "request": request.to_dict(), "request_obj": request, "status": record["computed_result"]["status"],
                            "answer": record["answer_text"], "scope": record.get("scope", "")})


def ask(store: EvidenceStore, question: str, parser: Parser, session: Session | None = None, *, use_guards: bool = True) -> dict:
    question = (question or "").strip()
    if not question:
        return _stop_record(store, question, session, "invalid_question", "Câu hỏi đang trống.")
    try:
        request = parser.parse(question, store, session)
    except ParseFailure as exc:
        record = _stop_record(store, question, session, "parser_error",
                              "Hệ thống chưa hiểu được câu hỏi này nên không đưa ra con số nào. Hãy thử viết lại câu hỏi rõ hơn.", reason=str(exc), parser_name=parser.name)
        _remember(session, question, QueryRequest(intent="unanswerable", reason="parser_error"), record)  # a later "còn X?" must not reuse an older scope
        return record
    try:
        return run_request(store, question, request, session, parser.name, use_guards=use_guards)
    except Exception as exc:  # a bug must never turn into a number on the screen
        return _stop_record(store, question, session, "internal_error", "Có lỗi khi xử lý câu hỏi nên hệ thống không đưa ra con số nào.",
                            reason=f"{type(exc).__name__}: {exc}", parser_name=parser.name)


def choose_option(store: EvidenceStore, question: str, option_index: int, session: Session) -> dict:
    """The user picked a clarification option. The chosen request runs without another AI call."""
    if not 0 <= option_index < len(session.pending_options):
        raise IndexError("no such option")
    option = session.pending_options[option_index]
    return run_request(store, question, option.request, session, "user_choice", user_chose=True)
