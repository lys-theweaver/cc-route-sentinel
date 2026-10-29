from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

CLASSIFIER_WORD = re.compile(
    r"\b(?:classifiers?|safeguards?|safety(?: layer| system)?)\b|安全分类器|安全保护",
    re.I,
)
CLASSIFIER_BLOCK = re.compile(
    r"\b(?:stopped|blocked|flagged|refused|rejected|prevented|withheld)\b|拦截|阻止|拒绝|扣下",
    re.I,
)
ENGINE_CLASSIFIER = re.compile(
    r"\[ERROR\].*\[engine\].*(?:safeguards?|safety classifier).*(?:flagged|blocked|stopped|refused|rejected)",
    re.I,
)
REQUEST_ID = re.compile(r"\breq_[A-Za-z0-9_-]+\b")


@dataclass(frozen=True)
class Event:
    category: str
    kind: str
    source: str
    line: int
    timestamp: str | None = None
    event_id: str | None = None
    expected_model: str | None = None
    observed_model: str | None = None
    confidence: str = "high"
    request_id: str | None = None

    def json(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def blocked_notice(text: Any) -> bool:
    return isinstance(text, str) and bool(CLASSIFIER_WORD.search(text) and CLASSIFIER_BLOCK.search(text))


def _provider_error_outside_thinking(obj: dict[str, Any]) -> str | None:
    msg = obj.get("message") if isinstance(obj.get("message"), dict) else {}
    content = msg.get("content")
    if isinstance(content, str):
        return content if blocked_notice(content) else None
    if not isinstance(content, list):
        return None
    for block in content:
        if not isinstance(block, dict) or block.get("type") in {"thinking", "redacted_thinking"}:
            continue
        candidate = block.get("text") or block.get("content")
        if blocked_notice(candidate if isinstance(candidate, str) else _text(candidate)):
            return _text(candidate)
    return None


def transcript_events(obj: dict[str, Any], *, line: int, source: str, expected_model: str | None) -> list[Event]:
    out: list[Event] = []
    typ = obj.get("type")
    msg = obj.get("message") if isinstance(obj.get("message"), dict) else {}
    timestamp = obj.get("timestamp") if isinstance(obj.get("timestamp"), str) else None
    event_id = str(obj.get("uuid") or msg.get("id") or line)

    if typ == "assistant":
        model = msg.get("model")
        if isinstance(model, str) and model and model != "<synthetic>" and expected_model and model != expected_model:
            out.append(Event("route", "model_mismatch", source, line, timestamp, event_id,
                             expected_model, model, "high", str(obj.get("requestId") or "") or None))
        if msg.get("stop_reason") == "refusal":
            out.append(Event("classifier", "stop_reason_refusal", source, line, timestamp,
                             event_id, confidence="medium"))
        provider_text = _provider_error_outside_thinking(obj)
        if provider_text:
            req = REQUEST_ID.search(provider_text)
            out.append(Event("classifier", "provider_error", source, line, timestamp,
                             event_id, confidence="high", request_id=req.group(0) if req else None))

    if typ == "system" and obj.get("subtype") == "informational" and blocked_notice(obj.get("content")):
        out.append(Event("classifier", "system_notice", source, line, timestamp, event_id, confidence="high"))

    if typ == "user" and isinstance(msg.get("content"), list):
        for block in msg["content"]:
            if not isinstance(block, dict) or block.get("type") != "tool_result" or block.get("is_error") is not True:
                continue
            candidate = block.get("content")
            candidate_text = candidate if isinstance(candidate, str) else _text(candidate)
            if blocked_notice(candidate_text):
                out.append(Event("classifier", "tool_not_run", source, line, timestamp, event_id, confidence="high"))
                break
    return out


def iter_jsonl(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, raw in enumerate(handle, 1):
            try:
                obj = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if isinstance(obj, dict):
                yield line_no, obj


def scan_transcript(path: Path, expected_model: str | None = None) -> list[Event]:
    events: list[Event] = []
    for line_no, obj in iter_jsonl(path):
        events.extend(transcript_events(obj, line=line_no, source=str(path), expected_model=expected_model))
    return dedupe(events)


def scan_debug(path: Path) -> list[Event]:
    events: list[Event] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, raw in enumerate(handle, 1):
            if not ENGINE_CLASSIFIER.search(raw):
                continue
            req = REQUEST_ID.search(raw)
            timestamp = raw.split(" ", 1)[0] if raw[:4].isdigit() else None
            events.append(Event("classifier", "engine_error", str(path), line_no, timestamp,
                                request_id=req.group(0) if req else None, confidence="high"))
    return dedupe(events)


def dedupe(events: Iterable[Event]) -> list[Event]:
    result: list[Event] = []
    seen: set[tuple[Any, ...]] = set()
    for event in events:
        # Nearby formats can describe the same refusal. Keep distinct evidence kinds,
        # but never repeat an identical event from the same source position.
        key = (event.category, event.kind, event.source, event.line, event.event_id)
        if key not in seen:
            seen.add(key)
            result.append(event)
    return result


def active_transcript(binding: Path, transcript_root: Path) -> Path:
    data = json.loads(binding.read_text(encoding="utf-8"))
    sid = data.get("current_session_id") or data.get("session_id")
    if not isinstance(sid, str) or not re.fullmatch(r"[0-9a-fA-F-]{36}", sid):
        raise ValueError("binding has no valid current_session_id/session_id")
    path = transcript_root / f"{sid}.jsonl"
    if not path.is_file():
        raise FileNotFoundError(path)
    return path
