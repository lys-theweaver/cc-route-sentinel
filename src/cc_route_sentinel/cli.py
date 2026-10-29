from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .detect import active_transcript, scan_debug, scan_transcript


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cc-sentinel", description="Detect visible Claude Code route drift and provider classifier stops.")
    p.add_argument("--transcript", type=Path, help="Claude Code JSONL transcript")
    p.add_argument("--binding", type=Path, help="JSON file containing current_session_id/session_id")
    p.add_argument("--transcript-root", type=Path, help="directory containing <session-id>.jsonl")
    p.add_argument("--debug-log", type=Path, action="append", default=[], help="optional Claude Code debug log; repeatable")
    p.add_argument("--expected-model", help="exact visible assistant.message.model expected in transcript")
    p.add_argument("--json", action="store_true", help="emit stable JSON")
    p.add_argument("--fail-on-refusal-only", action="store_true", help="treat bare stop_reason=refusal as a classifier hit")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        transcript = args.transcript
        if transcript is None:
            if not args.binding or not args.transcript_root:
                raise ValueError("use --transcript, or both --binding and --transcript-root")
            transcript = active_transcript(args.binding, args.transcript_root)
        events = scan_transcript(transcript, args.expected_model)
        for debug in args.debug_log:
            events.extend(scan_debug(debug))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(payload, ensure_ascii=False) if args.json else payload["error"], file=sys.stderr)
        return 2

    route = [e for e in events if e.category == "route"]
    classifier = [e for e in events if e.category == "classifier" and (args.fail_on_refusal_only or e.kind != "stop_reason_refusal")]
    refusal_signals = [e for e in events if e.category == "classifier" and e.kind == "stop_reason_refusal"]
    payload = {
        "ok": not route and not classifier,
        "transcript": str(transcript),
        "expected_model": args.expected_model,
        "route_drift": bool(route),
        "classifier_stop": bool(classifier),
        "events": [e.json() for e in events],
        "summary": {"route": len(route), "classifier": len(classifier), "refusal_signals": len(refusal_signals)},
        "limitations": [
            "Only client-visible model metadata is checked.",
            "A provider-side backend swap that preserves the same public model id cannot be proven locally.",
            "A bare stop_reason=refusal is reported as a medium-confidence signal unless --fail-on-refusal-only is used.",
        ],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"transcript: {transcript}")
        print(f"route drift: {'YES' if route else 'no'} | classifier stop: {'YES' if classifier else 'no'}")
        for event in events:
            model = f" {event.expected_model} -> {event.observed_model}" if event.observed_model else ""
            print(f"- {event.category}/{event.kind} {event.source}:{event.line}{model} confidence={event.confidence}")
    if route and classifier:
        return 30
    if classifier:
        return 20
    if route:
        return 10
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
