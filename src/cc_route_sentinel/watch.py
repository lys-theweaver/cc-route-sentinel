from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .detect import active_transcript, transcript_events


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def scan_incremental(path: Path, offset: int, expected_model: str | None) -> tuple[int, list[dict[str, Any]]]:
    size = path.stat().st_size
    if offset > size:
        offset = 0
    with path.open("rb") as handle:
        handle.seek(offset)
        data = handle.read()
    if not data:
        return offset, []
    if not data.endswith(b"\n"):
        cut = data.rfind(b"\n")
        if cut < 0:
            return offset, []
        data = data[:cut + 1]
    next_offset = offset + len(data)
    events = []
    for index, raw in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            events.extend(e.json() for e in transcript_events(
                obj, line=index, source=str(path), expected_model=expected_model
            ))
    return next_offset, events


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Incrementally watch the active Claude Code transcript.")
    p.add_argument("--binding", type=Path, required=True)
    p.add_argument("--transcript-root", type=Path, required=True)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--expected-model")
    p.add_argument("--replay", action="store_true", help="scan existing history on first run/session change")
    p.add_argument("--json", action="store_true")
    p.add_argument("--fail-on-refusal-only", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        transcript = active_transcript(args.binding, args.transcript_root)
        stat = transcript.stat()
        state = load(args.state)
        changed = state.get("transcript") != str(transcript) or state.get("inode") != stat.st_ino
        if changed:
            offset = 0 if args.replay else stat.st_size
            state = {"transcript": str(transcript), "inode": stat.st_ino, "offset": offset}
            save(args.state, state)
            payload = {"ok": True, "anchored": True, "transcript": str(transcript), "offset": offset, "events": []}
            print(json.dumps(payload, ensure_ascii=False) if args.json else f"anchored: {transcript} @ {offset}")
            return 0
        offset, events = scan_incremental(transcript, int(state.get("offset") or 0), args.expected_model)
        state["offset"] = offset
        save(args.state, state)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 2

    route = [e for e in events if e["category"] == "route"]
    classifier = [e for e in events if e["category"] == "classifier" and
                  (args.fail_on_refusal_only or e["kind"] != "stop_reason_refusal")]
    payload = {"ok": not route and not classifier, "anchored": False, "transcript": str(transcript),
               "offset": offset, "route_drift": bool(route), "classifier_stop": bool(classifier), "events": events}
    print(json.dumps(payload, ensure_ascii=False) if args.json else
          f"new events: {len(events)} | route={len(route)} classifier={len(classifier)}")
    return 30 if route and classifier else 20 if classifier else 10 if route else 0


if __name__ == "__main__":
    raise SystemExit(main())
