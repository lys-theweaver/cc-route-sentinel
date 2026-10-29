import json
import tempfile
import unittest
from pathlib import Path

from cc_route_sentinel.detect import active_transcript, scan_debug, scan_transcript


class DetectorTests(unittest.TestCase):
    def write_jsonl(self, root, rows):
        path = Path(root) / "session.jsonl"
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
        return path

    def test_model_mismatch_ignores_synthetic(self):
        with tempfile.TemporaryDirectory() as root:
            p = self.write_jsonl(root, [
                {"type":"assistant","uuid":"a","message":{"model":"claude-fable-5","content":[]}},
                {"type":"assistant","uuid":"b","message":{"model":"claude-opus-5-5","content":[]}},
                {"type":"assistant","uuid":"c","message":{"model":"<synthetic>","content":[]}},
            ])
            events = scan_transcript(p, "claude-fable-5")
            self.assertEqual([(e.kind, e.observed_model) for e in events], [("model_mismatch", "claude-opus-5-5")])

    def test_classifier_formats_and_quotes(self):
        with tempfile.TemporaryDirectory() as root:
            p = self.write_jsonl(root, [
                {"type":"assistant","message":{"content":[{"type":"thinking","thinking":"safeguards flagged this session"}]}},
                {"type":"assistant","message":{"content":[{"type":"text","text":"API Error: safeguards flagged this session Request ID: req_abc"}]}},
                {"type":"system","subtype":"informational","content":"Safety classifier stopped the response above."},
                {"type":"user","message":{"content":[{"type":"tool_result","is_error":True,"content":"Not run: response stopped by a safety classifier."}]}},
                {"type":"user","message":{"content":[{"type":"text","text":"My friend said safeguards flagged this session"}]}},
                {"type":"assistant","message":{"stop_reason":"refusal","content":[]}},
            ])
            events = scan_transcript(p)
            self.assertEqual([e.kind for e in events], ["provider_error", "system_notice", "tool_not_run", "stop_reason_refusal"])
            self.assertEqual(events[0].request_id, "req_abc")

    def test_debug_requires_engine_error_shape(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / "debug.log"
            p.write_text("quoted safeguards flagged this session\n2026-01-01 [ERROR] [engine] turn ended in error: safeguards flagged this message Request ID: req_z\n")
            events = scan_debug(p)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].request_id, "req_z")

    def test_binding(self):
        with tempfile.TemporaryDirectory() as root:
            r = Path(root); sid = "11111111-1111-1111-1111-111111111111"
            (r / f"{sid}.jsonl").write_text("")
            b = r / "state.json"; b.write_text(json.dumps({"current_session_id": sid}))
            self.assertEqual(active_transcript(b, r), r / f"{sid}.jsonl")


if __name__ == "__main__":
    unittest.main()
