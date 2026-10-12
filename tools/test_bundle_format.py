"""The authored records the validator and the canonical form know: sector
boundaries (datalogger 0.8) beside the corners and sections.

    python tools/test_bundle_format.py
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bundle_format  # noqa: E402
import canonical  # noqa: E402

SOURCE = "beef0000cafe"


def bundle(**over):
    doc = {
        "format": bundle_format.BUNDLE_FORMAT,
        "version": bundle_format.BUNDLE_VERSION,
        "meta": {
            "track": "Test Course", "runs": 1, "source_runs": {SOURCE: 1},
            "updated_at": "2026-01-01T00:00:00+00:00",
            "official": {"track": "Test Course", "layout": "Full", "official_id": "abc123",
                         "official_name": "Test Course", "turns": 3, "length_m": 1000.0,
                         "reverse": False},
        },
        "edges": [
            {"x": float(i), "z": 0.0, "y": None, "hx": 1.0, "hz": 0.0, "side": "L",
             "kind": "edge", "run": 1, "tw": None, "votes": {"edge": {SOURCE: [1, 1]}}}
            for i in range(4)
        ],
        "finish_crossings": [],
        "corners": [],
        "sections": [],
    }
    doc.update(over)
    return doc


SECTORS = [{"n": 1, "name": "", "end": {"x": 1.0, "z": 0.0}},
           {"n": 2, "name": "Esses", "end": {"x": 3.0, "z": 0.0}}]


class SectorTests(unittest.TestCase):
    def test_sector_boundaries_are_accepted(self) -> None:
        doc = bundle_format.validate_document(bundle(sectors=copy.deepcopy(SECTORS)))
        self.assertEqual(doc["sectors"], SECTORS)

    def test_a_bundle_without_the_key_is_still_a_bundle(self) -> None:
        # Every file written before datalogger 0.8 — the key is optional.
        doc = bundle_format.validate_document(bundle())
        self.assertNotIn("sectors", doc)

    def test_a_boundary_needs_a_position(self) -> None:
        for bad, wanted in (
            ([{"n": 1, "name": "", "end": None}], "end is not a position"),
            ([{"n": 0, "name": "", "end": {"x": 1.0, "z": 0.0}}], "not a sector number"),
            ([{"n": 1, "name": 7, "end": {"x": 1.0, "z": 0.0}}], "name is not text"),
            (["S1"], "is not an object"),
            ({"n": 1}, "is not an array"),
        ):
            with self.assertRaises(ValueError) as caught:
                bundle_format.validate_document(bundle(sectors=bad))
            self.assertIn(wanted, str(caught.exception))

    def test_at_most_twenty_boundaries(self) -> None:
        many = [{"n": i + 1, "name": "", "end": {"x": float(i), "z": 0.0}}
                for i in range(bundle_format.MAX_SECTORS + 1)]
        with self.assertRaises(ValueError) as caught:
            bundle_format.validate_document(bundle(sectors=many))
        self.assertIn("exceeds", str(caught.exception))

    def test_canonical_form_carries_them_in_key_order(self) -> None:
        text = canonical.dumps(bundle(sectors=[{"end": {"x": 1.0, "z": 0.0}, "name": "", "n": 1}]))
        self.assertIn('"sectors": [\n  {"n":1,"name":"","end":{"x":1.0,"z":0.0}}\n ]', text)
        # ...and an absent key renders as an empty list, so every file agrees.
        self.assertIn('"sectors": []', canonical.dumps(bundle()))


if __name__ == "__main__":
    unittest.main()
