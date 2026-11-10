"""The clear request a question turns into, and the checks every parser output must pass."""

from dataclasses import dataclass, field

from .calculator import OPERATIONS

INTENTS = {"answer", "clarify", "unanswerable"}
ROLES = {"target", "base", "item", "numerator", "denominator", "rate", "subject"}
METRICS = {"value", "absolute", "percentage_growth"}


class RequestError(ValueError):
    """A parser returned something that does not follow the request format."""


@dataclass
class OperandRef:
    role: str
    series: str
    period: str | None = None
    evidence: str | None = None


@dataclass
class Option:
    label: str
    request: "QueryRequest"


@dataclass
class QueryRequest:
    intent: str
    operation: str | None = None
    operands: list[OperandRef] = field(default_factory=list)
    group_series: list[str] = field(default_factory=list)
    base_period: str | None = None
    target_period: str | None = None
    period: str | None = None
    metric_type: str | None = None
    order: str = "DESC"
    mode: str | None = None
    output_unit: str | None = None
    period_months: int | None = None
    question: str | None = None
    options: list[Option] = field(default_factory=list)
    reason: str | None = None
    pins: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = {"intent": self.intent}
        if self.operation:
            data["operation"] = self.operation
        if self.operands:
            data["operands"] = [{k: v for k, v in vars(o).items() if v is not None} for o in self.operands]
        if self.group_series:
            data["group_series"] = self.group_series
        for key in ("base_period", "target_period", "period", "metric_type", "mode", "output_unit", "question", "reason"):
            value = getattr(self, key)
            if value:
                data[key] = value
        if self.operation == "rank_group":
            data["order"] = self.order
        if self.period_months:
            data["period_months"] = self.period_months
        if self.pins:
            data["pins"] = self.pins
        if self.options:
            data["options"] = [{"label": o.label, "request": o.request.to_dict()} for o in self.options]
        return data


def _text(data: dict, key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RequestError(f"{key} must be text")
    return value.strip() or None


def request_from_dict(data, *, _depth: int = 0) -> QueryRequest:
    if not isinstance(data, dict):
        raise RequestError("request must be a JSON object")
    intent = data.get("intent")
    if intent not in INTENTS:
        raise RequestError(f"intent {intent!r} is not one of {sorted(INTENTS)}")
    request = QueryRequest(intent=intent, question=_text(data, "question"), reason=_text(data, "reason"))
    if intent == "clarify":
        if not request.question:
            raise RequestError("clarify needs a question")
        options = data.get("options") or []
        if not isinstance(options, list):
            raise RequestError("options must be a list")
        if _depth:
            raise RequestError("an option cannot contain options")
        for option in options:
            if not isinstance(option, dict) or not _text(option, "label"):
                raise RequestError("each option needs a label")
            request.options.append(Option(_text(option, "label"), request_from_dict(option.get("request"), _depth=1)))
        return request
    if intent == "unanswerable":
        return request

    operation = data.get("operation")
    if operation not in OPERATIONS:
        raise RequestError(f"operation {operation!r} is not one of {sorted(OPERATIONS)}")
    request.operation = operation
    raw_operands = data.get("operands") or []
    if not isinstance(raw_operands, list):
        raise RequestError("operands must be a list")
    for raw in raw_operands:
        if not isinstance(raw, dict):
            raise RequestError("each operand must be an object")
        role, series = raw.get("role", "subject"), _text(raw, "series")
        if role not in ROLES:
            raise RequestError(f"role {role!r} is not one of {sorted(ROLES)}")
        if not series:
            raise RequestError("each operand needs a series")
        request.operands.append(OperandRef(role, series, _text(raw, "period"), _text(raw, "evidence")))
    group = data.get("group_series") or []
    if not isinstance(group, list) or not all(isinstance(g, str) and g.strip() for g in group):
        raise RequestError("group_series must be a list of names")
    request.group_series = [g.strip() for g in group]
    for key in ("base_period", "target_period", "period", "mode", "output_unit"):
        setattr(request, key, _text(data, key))
    months = data.get("period_months")
    if months is not None and (not isinstance(months, int) or isinstance(months, bool) or months < 1):
        raise RequestError("period_months must be a positive whole number")
    request.period_months = months
    request.metric_type = data.get("metric_type")
    if request.metric_type is not None and request.metric_type not in METRICS:
        raise RequestError(f"metric_type {request.metric_type!r} is not one of {sorted(METRICS)}")
    order = str(data.get("order") or "DESC").upper()
    if order not in {"ASC", "DESC"}:
        raise RequestError(f"order {order!r} is not ASC or DESC")
    request.order = order
    pins = data.get("pins") or {}
    if not isinstance(pins, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in pins.items()):
        raise RequestError("pins must map text to text")
    request.pins = pins
    if request.mode is not None and request.mode not in {"portion", "add"}:
        raise RequestError(f"mode {request.mode!r} is not portion or add")
    if operation == "rank_group":
        if not (request.operands or request.group_series):
            raise RequestError("rank_group needs group_series or operands")
    elif not request.operands:
        raise RequestError(f"{operation} needs operands")
    return request
