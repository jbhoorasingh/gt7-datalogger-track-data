"""Corrections: the format, its canonical form, and what an area keeps out.

    python tools/test_corrections.py
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import corrections  # noqa: E402

SQUARE = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]


def area(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"id": "a1", "sides": ["R"], "polygon": copy.deepcopy(SQUARE), "y": None,
                            "only_drawn": False, "reason": "the pit wall, not the track's edge",
                            "by": "Alice", "at": "2026-09-21T00:00:00Z"}
    base.update(overrides)
    return base


def document(*areas: dict[str, Any], smooth: bool | None = None) -> dict[str, Any]:
    doc = corrections.empty("f18da2", "Tsukuba Circuit")
    doc["exclude"] = list(areas)
    doc["compile"]["smooth_borders"] = smooth
    return doc


def edge(x: float, z: float, side: str = "R", y: float | None = None,
         sources: tuple[str, ...] = ("88fcdd09894f",)) -> dict[str, Any]:
    return {"x": x, "z": z, "y": y, "hx": 1.0, "hz": 0.0, "side": side, "kind": "edge",
            "votes": {"edge": {source: [1, 1] for source in sources}}, "run": 1, "tw": None}


class FormatTests(unittest.TestCase):
    def test_a_document_that_says_nothing_is_valid_and_empty(self) -> None:
        doc = corrections.validate(corrections.empty("f18da2", "Tsukuba Circuit"))
        self.assertTrue(corrections.is_empty(doc))
        self.assertTrue(corrections.is_empty(None))
        self.assertFalse(corrections.is_empty(document(area())))
        self.assertFalse(corrections.is_empty(document(smooth=False)))

    def test_an_area_needs_a_reason(self) -> None:
        # A hole in the map nobody can later judge whether to keep.
        with self.assertRaisesRegex(ValueError, "reason"):
            corrections.validate(document(area(reason="")))
        with self.assertRaisesRegex(ValueError, "reason"):
            corrections.validate(document(area(reason="   ")))

    def test_what_is_refused(self) -> None:
        cases = {
            "sides": area(sides=[]),
            "sides may only": area(sides=["L", "X"]),
            "polygon must have": area(polygon=[[0, 0], [1, 1]]),
            "encloses no ground": area(polygon=[[0, 0], [5, 5], [10, 10]]),
            r"polygon\[1\]": area(polygon=[[0, 0], [float("nan"), 1], [1, 0]]),
            r"polygon\[0\]": area(polygon=[[9e9, 0], [1, 1], [1, 0]]),
            r"\.y must be": area(y=[5, 1]),
            "only_drawn": area(only_drawn="yes"),
            "unknown key": {**area(), "delete": True},
        }
        for message, bad in cases.items():
            with self.assertRaisesRegex(ValueError, message):
                corrections.validate(document(bad))
        with self.assertRaisesRegex(ValueError, "id of its own"):
            corrections.validate(document(area(), area()))
        with self.assertRaisesRegex(ValueError, "format must be"):
            corrections.validate({**document(), "format": "something-else"})

    def test_only_a_boolean_or_null_answers_the_smoothing_question(self) -> None:
        for answer in (True, False, None):
            self.assertIs(corrections.smooth_override(corrections.validate(document(smooth=answer))), answer)
        for wrong in ("off", 0, 1, "false"):
            with self.assertRaisesRegex(ValueError, "smooth_borders"):
                corrections.validate(document(smooth=wrong))  # type: ignore[arg-type]
        self.assertIsNone(corrections.smooth_override(None))

    def test_canonical_form_is_stable_and_one_area_a_line(self) -> None:
        doc = document(area(), area(id="a2", sides=["R", "L"], y=[3, 9.5], only_drawn=True), smooth=False)
        text = corrections.dumps(doc)
        self.assertEqual(corrections.dumps(json.loads(text)), text)
        self.assertTrue(text.endswith("}\n"))
        self.assertEqual(sum(1 for line in text.splitlines() if line.lstrip().startswith('{"id"')), 2)
        # Sides come out in one order whatever order they went in, or two
        # people saying the same thing produce different bytes.
        self.assertIn('"sides":["L","R"]', text)
        self.assertEqual(json.loads(text), corrections.validate(doc))


class ExclusionTests(unittest.TestCase):
    def test_an_area_keeps_out_its_own_side_only(self) -> None:
        a = corrections.validate(document(area()))["exclude"][0]
        self.assertTrue(corrections.excludes(a, edge(5, 5, "R")))
        self.assertFalse(corrections.excludes(a, edge(5, 5, "L")))
        self.assertFalse(corrections.excludes(a, edge(15, 5, "R")))

    def test_a_record_next_week_in_the_cell_next_door_is_still_kept_out(self) -> None:
        # The whole reason an area is an area: a survey jitters, and a list of
        # last week's cells would leak.
        a = corrections.validate(document(area()))["exclude"][0]
        for x, z in ((4.2, 6.7), (5.4, 6.1), (3.9, 7.3)):
            self.assertTrue(corrections.excludes(a, edge(x, z)))

    def test_a_level_range_tells_a_bridge_from_the_road_beneath_it(self) -> None:
        a = corrections.validate(document(area(y=[6.5, 9.5])))["exclude"][0]
        self.assertTrue(corrections.excludes(a, edge(5, 5, y=8.0)))
        self.assertFalse(corrections.excludes(a, edge(5, 5, y=0.0)))
        # No elevation is every level: a metre from before elevation existed
        # must not slip out from under an area drawn round it.
        self.assertTrue(corrections.excludes(a, edge(5, 5, y=None)))

    def test_only_drawn_takes_back_a_bridge_without_hiding_a_later_survey(self) -> None:
        a = corrections.validate(document(area(only_drawn=True)))["exclude"][0]
        self.assertTrue(corrections.excludes(a, edge(5, 5, sources=("drawn-0a1b2c3d",))))
        self.assertFalse(corrections.excludes(a, edge(5, 5, sources=("88fcdd09894f",))))
        # Somebody drove it: the cell is no longer only an opinion.
        self.assertFalse(corrections.excludes(a, edge(5, 5, sources=("drawn-0a1b2c3d", "88fcdd09894f"))))

    def test_a_concave_area_excludes_what_is_inside_it_and_not_its_notch(self) -> None:
        notch = [[0, 0], [10, 0], [10, 10], [5, 3], [0, 10]]
        a = corrections.validate(document(area(polygon=notch)))["exclude"][0]
        self.assertTrue(corrections.excludes(a, edge(2, 2)))
        self.assertFalse(corrections.excludes(a, edge(5, 8)))

    def test_applying_never_touches_the_bundle(self) -> None:
        bundle = {"edges": [edge(5, 5), edge(50, 50), edge(5, 6, "L")], "meta": {"runs": 1}}
        before = json.dumps(bundle, sort_keys=True)
        out = corrections.apply(bundle, corrections.validate(document(area())))
        self.assertEqual(json.dumps(bundle, sort_keys=True), before)
        self.assertEqual([(e["x"], e["side"]) for e in out["edges"]], [(50, "R"), (5, "L")])
        self.assertEqual(corrections.excluded(bundle["edges"], document(area())), [0])
        # Nothing to say, nothing copied: the same object comes back.
        self.assertIs(corrections.apply(bundle, None), bundle)
        self.assertIs(corrections.apply(bundle, corrections.empty("f18da2", "Tsukuba Circuit")), bundle)


if __name__ == "__main__":
    unittest.main()
