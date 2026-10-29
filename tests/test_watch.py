import json
import tempfile
import unittest
from pathlib import Path

from cc_route_sentinel.watch import scan_incremental


class IncrementalTests(unittest.TestCase):
    def test_partial_line_waits_and_then_consumes_once(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / "s.jsonl"
            row = json.dumps({"type":"system","subtype":"informational","content":"Safety classifier stopped the response."})
            p.write_text(row[:-3])
            offset, events = scan_incremental(p, 0, None)
            self.assertEqual((offset, events), (0, []))
            p.write_text(row + "\n")
            offset, events = scan_incremental(p, 0, None)
            self.assertEqual(len(events), 1)
            same, again = scan_incremental(p, offset, None)
            self.assertEqual((same, again), (offset, []))

    def test_rewrite_smaller_resets_offset(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / "s.jsonl"
            row = json.dumps({"type":"assistant","message":{"model":"other","content":[]}}) + "\n"
            p.write_text(row)
            offset, events = scan_incremental(p, 99999, "wanted")
            self.assertEqual(len(events), 1)
            self.assertEqual(offset, len(row.encode()))


if __name__ == "__main__": unittest.main()
