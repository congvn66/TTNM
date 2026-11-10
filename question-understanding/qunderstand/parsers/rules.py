"""An offline parser with no AI. It handles common question shapes and refuses the rest.

It lets the team run and test the CLI with no API key. It raises ParseFailure on a shape
it does not know, because a refusal is safe and a wrong guess is not.
"""

import re

from ..periods import Period, display, find_periods, parse_period, shift
from ..request import OperandRef, QueryRequest
from ..text import norm, tokens
from .base import ParseFailure

_UNSUPPORTED = re.compile(r"\b(trung binh|binh quan|neu tinh|neu |vi sao|tai sao|du bao|ke hoach|nua cuoi)\b")
_DEFINE = re.compile(r"dinh nghia|duoc tinh the nao|nghia la gi|\bla gi\b")
_FOLLOW = re.compile(r"^(con|vay|the|so voi|cung ky|tang hay giam|nam truoc)\b|thi sao\b")
_GROUP = re.compile(r"\b(khu vuc|mien|mang|chuoi|tuyen|khach hang)\s+nao\b")
_TIME_GROUP = re.compile(r"\b(thang|quy)\s+nao\b")
_TOP = re.compile(r"\b(nhat)\b")
_LOW = re.compile(r"\b(thap nhat|it nhat|nho nhat|kem nhat)\b")
_CHANGE = re.compile(r"\b(tang|giam|tang truong)\b")
_PCT = re.compile(r"phan tram|%")
_POINT = re.compile(r"\bdiem\b")
_DIFF = re.compile(r"chenh lech|cao hon|thap hon|tang bao nhieu|giam bao nhieu|tang hay giam|hon bao nhieu|\bhieu\b")
_SUM = re.compile(r"\btong\b|cong lai|cong voi")
_ASKED_UNIT = re.compile(r"(?:bao nhieu|theo|bang)\s+((?:nghin ty|ty|trieu|nghin)\s+(?:dong|usd|vnd)|usd|nghin tan|tan)\b")
_SHARE = re.compile(r"(hoan thanh|chiem) bao nhieu|bao nhieu phan tram (muc tieu|ke hoach)")


_QUALIFIERS = {"sau", "truoc", "gop", "rong", "thuan", "cot", "tu"}
_OPTIONAL_HEAD = {"so", "thuan", "gop"}
_KNOWN_WORDS = set("""
cua trong la bao nhieu mot cac nhung duoc hay nao co o tai theo va voi thi ma de ve khi nay do
cong ty toan ca hpg mwg khoang gan xap xi cho minh xin biet hoi lai giup nhe a nhi vay the sao con
so sanh muc tieu ke hoach hoan thanh da ca doanh thu tang giam cao hon thap nhat it lon nho tong dau nam thang quy ky cung truoc sau cuoi mang chuoi kenh tuyen khu vuc mien
phan tram % diem ty le tuyet doi gia tri tu len den may bieu dang nhanh manh tot luy ke van tai dinh nghia tinh nghia gi the nao
chenh lech hieu tang truong
""".split())


class RuleParser:
    name = "rules"

    def parse(self, question: str, store, session) -> QueryRequest:
        text = norm(question)
        prev = session.last_request() if session else None
        is_follow = bool(_FOLLOW.search(text)) and prev is not None and prev.intent == "answer"
        if _UNSUPPORTED.search(text):
            raise ParseFailure("rule parser does not handle this question shape")

        metric, entity, entity_count = _match_series(text, store)
        periods = [p for p in find_periods(text)]
        words = set(tokens(question))
        if entity_count > 1 and not _GROUP.search(text):
            raise ParseFailure("rule parser handles one entity at a time")
        if metric or entity:
            unknown = _unknown_words(text, metric, entity, periods)
            if unknown:
                raise ParseFailure(f"rule parser does not know these words: {', '.join(sorted(unknown))}")
        if not metric and not is_follow and _GROUP.search(text):
            heads = {n.partition(" - ")[0] for n in store.series_names() if " - " in n}
            if len(heads) == 1:
                metric = next(iter(heads))
        if not metric and not is_follow:
            if _GROUP.search(text) or len(words) > 2:
                return QueryRequest(intent="unanswerable", reason="Báo cáo không có thông tin để trả lời câu hỏi này.")
            raise ParseFailure("no metric found")

        request = self._follow_up(text, prev, metric, entity, periods, store, session) if is_follow else self._fresh(text, metric, entity, periods, store)
        asked_unit = _ASKED_UNIT.search(text)
        if asked_unit and request.intent == "answer" and request.operation in {"lookup", "sum", "diff"}:
            request.output_unit = asked_unit.group(1)
        return request

    def _fresh(self, text, metric, entity, periods, store) -> QueryRequest:
        series = _join(metric, entity)
        if _DEFINE.search(text):
            note = next((s for s in store.series_names() if norm(s).startswith("dinh nghia") and set(tokens(metric)) <= set(tokens(s))), None)
            if not note:
                return QueryRequest(intent="unanswerable", reason="Báo cáo không có định nghĩa này.")
            refs = [OperandRef("subject", note)]
            if periods:
                refs.append(OperandRef("subject", series, _p(periods[0])))
            return QueryRequest(intent="answer", operation="lookup", operands=refs)
        if _GROUP.search(text) and _TOP.search(text):
            group = _group_members(text, metric, store)
            order = "ASC" if _LOW.search(text) else "DESC"
            if _CHANGE.search(text):
                if len(periods) < 2:
                    if len(periods) == 1 and "cung ky" in text:
                        base = shift(periods[0], years=-1)
                        periods = [periods[0], base] if base else periods
                    if len(periods) < 2:
                        raise ParseFailure("ranking a change needs two periods")
                target, base = _split_pair(text, periods)
                return QueryRequest(intent="answer", operation="rank_group", group_series=group, base_period=_p(base), target_period=_p(target), order=order)
            period = _p(periods[0]) if periods else None
            return QueryRequest(intent="answer", operation="rank_group", group_series=group, period=period, metric_type="value", order=order)
        if _TIME_GROUP.search(text) and _TOP.search(text):
            order = "ASC" if _LOW.search(text) else "DESC"
            return QueryRequest(intent="answer", operation="rank_group", group_series=[series], metric_type="value", order=order)
        if _SHARE.search(text):
            goal = next((s for s in store.series_names() if norm(s).startswith(("muc tieu", "ke hoach")) and set(tokens(metric)) & set(tokens(s))), None)
            achieved = re.sub(r"^(mục tiêu|kế hoạch)\s+", "", metric, flags=re.IGNORECASE)
            whole = _join(achieved[:1].upper() + achieved[1:], "Tổng")
            if not goal or not store.find_series(whole) or not periods:
                raise ParseFailure("rule parser cannot pick the target of a share")
            return QueryRequest(intent="answer", operation="share", operands=[OperandRef("numerator", whole, _p(periods[0])), OperandRef("denominator", goal)])
        if _POINT.search(text) and len(periods) >= 2:
            target, base = _split_pair(text, periods)
            return QueryRequest(intent="answer", operation="pct_point_diff", operands=[OperandRef("target", series, _p(target)), OperandRef("base", series, _p(base))])
        if _CHANGE.search(text) and _PCT.search(text) and len(periods) >= 2:
            target, base = _split_pair(text, periods)
            return QueryRequest(intent="answer", operation="pct_growth", operands=[OperandRef("target", series, _p(target)), OperandRef("base", series, _p(base))])
        if _CHANGE.search(text) and _PCT.search(text) and len(periods) == 1 and "cung ky" in text:
            base = shift(periods[0], years=-1)
            if base is None:
                base = _other_year(series, periods[0], store)
            if base is None:
                raise ParseFailure("no earlier year")
            target = _with_latest_year(series, periods[0], store)
            return QueryRequest(intent="answer", operation="pct_growth", operands=[OperandRef("target", series, _p(target)), OperandRef("base", series, _p(base))])
        if _DIFF.search(text) and _PCT.search(text) and len(periods) >= 2:
            target, base = _split_pair(text, periods)
            return QueryRequest(intent="answer", operation="pct_growth", operands=[OperandRef("target", series, _p(target)), OperandRef("base", series, _p(base))])
        if _DIFF.search(text) and len(periods) >= 2:
            target, base = _split_pair(text, periods)
            return QueryRequest(intent="answer", operation="diff", operands=[OperandRef("target", series, _p(target)), OperandRef("base", series, _p(base))])
        if _SUM.search(text):
            if not periods:
                raise ParseFailure("sum needs a period")
            if len(periods) == 1:
                return QueryRequest(intent="answer", operation="sum", operands=[OperandRef("item", series, _p(periods[0]))])
            return QueryRequest(intent="answer", operation="sum", operands=[OperandRef("item", series, _p(p)) for p in periods])
        if _PCT.search(text) or _DIFF.search(text):
            raise ParseFailure("a change needs two periods")
        if len(periods) > 1:
            raise ParseFailure("two periods but no known operation")
        return QueryRequest(intent="answer", operation="lookup", operands=[OperandRef("subject", series, _p(periods[0]) if periods else None)])

    def _follow_up(self, text, prev, metric, entity, periods, store, session) -> QueryRequest:
        refs = prev.operands
        if not refs:
            raise ParseFailure("nothing to follow up on")
        last = refs[-1] if prev.operation == "lookup" else next((r for r in refs if r.role == "target"), refs[-1])
        old_metric, _, old_entity = last.series.partition(" - ")
        series = _join(metric or old_metric, entity or old_entity)
        old_period = parse_period(last.period)
        wants_pct = bool(_PCT.search(text))
        wants_change = bool(_CHANGE.search(text)) or wants_pct
        names_later = re.search(r"\b(thang|quy|nam) sau\b", text)
        if names_later:
            step = shift(old_period, months=1 if old_period.kind == "M" else 3) if old_period and not wants_change and names_later.group(1) != "nam" else None
            if step is None:
                raise ParseFailure("the rule parser handles only a plain lookup of the next month or quarter")
            return QueryRequest(intent="answer", operation="lookup", operands=[OperandRef("subject", series, _p(step))])
        if not wants_change and "so voi" not in text and not periods and re.search(r"\b(thang|quy) truoc\b", text):
            step = shift(old_period, months=-1 if old_period.kind == "M" else -3) if old_period else None
            if step is None:
                raise ParseFailure("no earlier period")
            return QueryRequest(intent="answer", operation="lookup", operands=[OperandRef("subject", series, _p(step))])

        if wants_change or "thang truoc" in text or "quy truoc" in text or "nam truoc" in text or "cung ky" in text:
            if periods:
                raise ParseFailure("this follow-up names a new period, which the rule parser does not combine with a change")
            if "thang truoc" in text or "quy truoc" in text:
                base = shift(old_period, months=-1 if old_period.kind == "M" else -3) if old_period else None
            elif "nam truoc" in text or "cung ky" in text:
                base = _other_year(series, old_period, store) if old_period else None
            else:
                earlier = _previous_period(session, last.period)
                base = parse_period(earlier) if earlier else None
            if not old_period or not base:
                raise ParseFailure("cannot find the two periods of this follow-up")
            if _is_later(base, old_period):
                return _change_request(text, wants_pct, series, base, old_period)
            if "cung ky" in text and not _CHANGE.search(text):
                return QueryRequest(intent="answer", operation="lookup", operands=[OperandRef("subject", series, _p(base))])
            operation = "pct_growth" if wants_pct else "diff"
            return QueryRequest(intent="answer", operation=operation, operands=[OperandRef("target", series, last.period), OperandRef("base", series, _p(base))])
        if prev.operation in {"pct_growth", "pct_point_diff", "diff"} and (entity or metric):
            return QueryRequest(intent="answer", operation=prev.operation, operands=[OperandRef(r.role, series, r.period) for r in refs])
        period = _p(periods[0]) if periods else last.period
        return QueryRequest(intent="answer", operation="lookup", operands=[OperandRef("subject", series, period)])


def _is_later(first: Period, second: Period) -> bool:
    size = {"Q": 3, "M": 1, "L": 1, "Y": 12}
    if first.year is None or second.year is None or first.kind not in size or second.kind not in size:
        return False
    return (first.year, first.number * size[first.kind]) > (second.year, second.number * size[second.kind])


def _change_request(text: str, wants_pct: bool, series: str, target: Period, base: Period) -> QueryRequest:
    if "cung ky" in text and not _CHANGE.search(text):
        return QueryRequest(intent="answer", operation="lookup", operands=[OperandRef("subject", series, _p(base))])
    operation = "pct_growth" if wants_pct else "diff"
    return QueryRequest(intent="answer", operation=operation, operands=[OperandRef("target", series, _p(target)), OperandRef("base", series, _p(base))])


def _p(period: Period) -> str:
    return display(period) if period.kind != "R" else period.raw


def _split_pair(text: str, periods: list[Period]) -> tuple[Period, Period]:
    """Which period is the base. 'so với X' and 'từ X' name it, and in 'A cao hơn B' it is B. Otherwise the earlier period is the base."""
    for period in periods[:2]:
        if period.raw and re.search(rf"\b(so voi|tu)\s+(ky\s+)?{re.escape(period.raw)}", text):
            other = periods[1] if period is periods[0] else periods[0]
            return other, period
    first, second = periods[0], periods[1]
    if re.search(r"\b(cao|thap|lon|nho|nhieu|it) hon\b", text):
        return first, second
    if (first.year or 0, first.number) <= (second.year or 0, second.number):
        return second, first
    return first, second


def _group_members(text: str, metric: str, store) -> list[str]:
    members = [s for s in store.series_names() if norm(s).startswith(norm(metric)) and " - " in s and norm(s.split(" - ", 1)[1]) != "tong"]
    if re.search(r"\b(mien|khu vuc)\s+nao\b", text):
        regions = [s for s in members if norm(s.split(" - ", 1)[1]).startswith("mien")]
        return regions or members
    return members


def _unknown_words(text: str, metric: str, entity: str, periods: list[Period]) -> set[str]:
    """Words the parser did not use. Any such word can change the meaning, so the parser must not ignore it."""
    used = set(tokens(metric)) | set(tokens(entity)) | _KNOWN_WORDS
    for period in periods:
        used |= set(tokens(period.raw))
    return {w for w in tokens(text) if w not in used and not w.isdigit() and not re.fullmatch(r"[tq]?\d+[a-z]?", w)}


def _join(metric: str, entity: str) -> str:
    return f"{metric} - {entity}" if entity else metric


def _other_year(series: str, period: Period, store) -> Period | None:
    if period is None:
        return None
    if period.year:
        return shift(period, years=-1)
    latest = _with_latest_year(series, period, store)
    return shift(latest, years=-1) if latest.year else None


def _with_latest_year(series: str, period: Period, store) -> Period:
    if period.year:
        return period
    names = store.find_series(series)
    years = sorted({e.period.year for name in names for e in store.lookup(name, period) if e.period and e.period.year})
    return Period(period.kind, period.number, years[-1]) if years else period


def _previous_period(session, current: str | None) -> str | None:
    for item in reversed(session.history):
        request = item["request_obj"]
        for ref in request.operands:
            if ref.period and ref.period != current:
                return ref.period
    return None


def _match_series(text: str, store) -> tuple[str, str, int]:
    """The metric and entity named in a question, using the words of the catalog."""
    metrics: dict[str, str] = {}
    entities: dict[str, str] = {}
    for name in store.series_names():
        head, _, tail = name.partition(" - ")
        metrics[norm(head)] = head
        if tail:
            entities[norm(tail)] = tail
    question_tokens = tokens(text)
    mentioned = [entities[k] for k in sorted(entities, key=len, reverse=True) if re.search(rf"(?<![\w]){re.escape(k)}(?![\w])", text)]
    entity = mentioned[0] if mentioned else ""
    if not entity and "tong" in entities and re.search(r"\b(toan cong ty|cua cong ty|ca cong ty)\b", text):
        entity = entities["tong"]
    scored: list[tuple[int, str]] = []
    for key, head in metrics.items():
        if key.startswith("dinh nghia"):
            continue
        head_tokens = tokens(key)
        required = [t for t in head_tokens if t not in _OPTIONAL_HEAD]
        run, next_word = _longest_prefix_run(head_tokens, question_tokens)
        full = run == len(head_tokens)
        # "doanh thu" may name "doanh thu thuần"; "tỷ trọng" inside "công ty trong" must not name "tỷ trọng kênh trực tuyến".
        optional_tail = run >= 2 and set(head_tokens[run:]) <= _OPTIONAL_HEAD and next_word not in _QUALIFIERS
        if full or optional_tail:
            scored.append((run, head))
        elif required and head_tokens[0] in _OPTIONAL_HEAD:
            inner, after = _longest_prefix_run(required, question_tokens)
            if inner == len(required) and after not in _QUALIFIERS:
                scored.append((inner, head))
    if not scored:
        return "", entity, len(mentioned)
    best = max(score for score, _ in scored)
    top = [head for score, head in scored if score == best]
    if len(top) == 1:
        return top[0], entity, len(mentioned)
    shared = _shared_words(top)
    return shared or top[0], entity, len(mentioned)


def _longest_prefix_run(head: list[str], question: list[str]) -> tuple[int, str]:
    """How many leading words of the metric name appear together in the question, and the word after them."""
    best, after = 0, ""
    for start in range(len(question)):
        count = 0
        while count < len(head) and start + count < len(question) and question[start + count] == head[count]:
            count += 1
        if count > best:
            best = count
            position = start + count
            after = question[position] if position < len(question) else ""
    return best, after


def _shared_words(names: list[str]) -> str:
    split = [n.split() for n in names]
    shared = []
    for group in zip(*split):
        if len({norm(w) for w in group}) != 1:
            break
        shared.append(group[0])
    return " ".join(shared)
