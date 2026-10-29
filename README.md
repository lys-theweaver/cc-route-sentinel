# cc-route-sentinel

A small, read-only detector for two things visible from a Claude Code terminal:

1. **Visible model-route drift** — an assistant event reports a model id different from the one you expected.
2. **Provider safety-classifier stops** — Claude Code records a safeguard/classifier stop in its JSONL transcript or debug log.

It does not call Claude, modify sessions, send notifications, or require API keys. Python 3.10+ only; no runtime dependencies.

## Install

```bash
python3 -m pip install .
```

Or install directly from GitHub:

```bash
python3 -m pip install git+https://github.com/lys-theweaver/cc-route-sentinel.git
```

Or run without installation:

```bash
PYTHONPATH=src python3 -m cc_route_sentinel.cli --help
```

## Scan one transcript

```bash
cc-sentinel \
  --transcript ~/.claude/projects/my-project/SESSION_ID.jsonl \
  --expected-model claude-opus-4-6 \
  --debug-log ~/.local/state/claude/debug.log
```

JSON for shell/monitoring integrations:

```bash
cc-sentinel --transcript session.jsonl --expected-model claude-opus-4-6 --json
```

Exit codes:

- `0`: no high-confidence route drift or classifier stop
- `10`: visible model mismatch
- `20`: classifier stop
- `30`: both
- `2`: invalid input/read error

A bare `stop_reason=refusal` is included as a medium-confidence signal but does not fail by default. Add `--fail-on-refusal-only` if your environment treats it as sufficient evidence.

## Resolve the active transcript from a binding file

If your launcher keeps a JSON file with `current_session_id` or `session_id`:

```bash
cc-sentinel \
  --binding ~/.local/state/my-claude/forge_state.json \
  --transcript-root ~/.claude/projects/-home-me-project \
  --expected-model claude-opus-4-6 \
  --json
```

## What it recognizes

Classifier detection is deliberately context-aware:

- provider error text in non-thinking assistant output;
- informational system notices that combine classifier/safeguard terms with stopped/blocked/flagged/refused wording;
- failed `tool_result` blocks saying the tool was not run because a classifier stopped the response;
- old `[ERROR] [engine] ... safeguards flagged ...` debug-log formats;
- `stop_reason=refusal` as a separate medium-confidence signal.

It ignores classifier words found only in thinking blocks, ordinary user/assistant quotations, successful initialization messages, and unrelated network blocks.

## Limits

This detects **client-visible evidence**. It cannot prove that a provider did or did not swap an internal backend while preserving the same public model id. Treat a clean result as “no visible drift found,” not cryptographic proof of server-side routing.

The tool reports metadata only: category, evidence kind, file position, timestamp, event id, request id, and visible model ids. It never emits conversation text.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Incremental watcher

For a timer or cron job, use `cc-sentinel-watch`. It stores only transcript path/inode/byte offset. The first run and every session change anchor at EOF by default, so installation does not replay old incidents. `--replay` opts into history. Partial JSONL lines wait for the next run, and transcript rewrites reset safely.

```bash
cc-sentinel-watch \
  --binding ~/.local/state/my-claude/forge_state.json \
  --transcript-root ~/.claude/projects/-home-me-project \
  --state ~/.local/state/cc-sentinel/state.json \
  --expected-model claude-opus-4-6 --json
```

## Optional systemd polling

See [`examples/cc-sentinel.service`](examples/cc-sentinel.service) and [`examples/cc-sentinel.timer`](examples/cc-sentinel.timer). Copy them and replace the placeholder paths/model. The example writes JSON locally; connect your own alerting only after reviewing what it sends.
