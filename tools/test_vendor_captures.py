from __future__ import annotations

import math
from pathlib import Path
import sys
import unittest


TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import vendor_captures  # noqa: E402


def capture(file: str, name: str, length_m: float, *, path=None, sha="a" * 64,
            box=(-1.0, 1.0, -1.0, 1.0)) -> dict:
    min_x, max_x, min_z, max_z = box
    return {"file": file, "name": name, "variation_name": name, "length_m": length_m,
            "points": 100, "min_x": min_x, "max_x": max_x, "min_z": min_z, "max_z": max_z,
            "start_x": 0.0, "start_z": 0.0, "end_x": 0.0, "end_z": 0.0,
            "path": path if path is not None else [[0, 0], [1, 1]], "sha256": sha}


def manifest(*captures: dict) -> dict:
    return {"format": "gt7-datalogger-capture-signatures", "version": 2,
            "path_step_m": 20, "source": {}, "captures": list(captures)}


class ThinTests(unittest.TestCase):
    """The line is thinned to the resolution the question has, not to save bytes."""

    def test_points_come_out_about_one_step_apart(self) -> None:
        # A straight line sampled every 2 m, thinned to every 20 m.
        xs = [float(i) * 2 for i in range(101)]
        zs = [0.0] * 101
        path = vendor_captures.thin(xs, zs, 20)
        gaps = [math.dist(a, b) for a, b in zip(path, path[1:], strict=False)]
        self.assertTrue(all(19 <= g <= 21 for g in gaps), gaps)
        self.assertEqual(path[0], [0, 0])

    def test_distance_is_walked_along_the_line_not_counted_in_samples(self) -> None:
        # Dense at the start, sparse at the end: taking every nth sample would
        # crowd the first half and skip the second, which is backwards — the
        # corners are where the samples bunch up and where the path matters.
        xs = [float(i) * 0.5 for i in range(41)] + [20.0 + i * 10.0 for i in range(1, 9)]
        zs = [0.0] * len(xs)
        path = vendor_captures.thin(xs, zs, 20)
        gaps = [math.dist(a, b) for a, b in zip(path, path[1:], strict=False)]
        self.assertTrue(all(g >= 20 for g in gaps), gaps)

    def test_order_is_preserved(self) -> None:
        xs = [float(i) * 25 for i in range(10)]
        zs = [0.0] * 10
        path = vendor_captures.thin(xs, zs, 20)
        # Driving order is the property the whole file exists to carry.
        self.assertEqual([p[0] for p in path], sorted(p[0] for p in path))

    def test_whole_metres_never_collapse_two_points_into_one(self) -> None:
        xs = [0.0, 0.4, 0.8, 1.2]
        zs = [0.0, 0.0, 0.0, 0.0]
        path = vendor_captures.thin(xs, zs, 1)
        self.assertEqual(len(path), len(set(tuple(p) for p in path)))


class ChangeReportTests(unittest.TestCase):
    """What a scheduled refresh tells whoever reads the pull request it opens."""

    def test_a_new_capture_is_reported_as_added(self) -> None:
        before = manifest(capture("old.json", "Old Circuit", 1000))
        after = manifest(capture("old.json", "Old Circuit", 1000),
                         capture("new.json", "New Circuit", 2500, sha="b" * 64))
        lines = vendor_captures.changes(before, after)
        self.assertEqual(len(lines), 1)
        self.assertIn("+ New Circuit", lines[0])
        self.assertIn("2,500 m", lines[0])

    def test_a_vanished_capture_is_reported_as_removed(self) -> None:
        before = manifest(capture("gone.json", "Gone Circuit", 1000))
        lines = vendor_captures.changes(before, manifest())
        self.assertEqual(lines, ["- Gone Circuit (gone.json)"])

    def test_a_changed_capture_says_which_numbers_moved(self) -> None:
        before = manifest(capture("c.json", "Circuit", 1000, path=[[0, 0], [1, 1]]))
        after = manifest(capture("c.json", "Circuit", 1200, sha="b" * 64,
                                 path=[[0, 0], [1, 1], [2, 2]], box=(-9.0, 1.0, -1.0, 1.0)))
        line, = vendor_captures.changes(before, after)
        self.assertIn("length 1,000 -> 1,200 m", line)
        self.assertIn("path 2 -> 3 points", line)
        self.assertIn("bounding box moved", line)

    def test_an_upstream_rename_is_reported(self) -> None:
        # The six known misspellings are mapped by hand, so a name changing
        # upstream is exactly the event that makes one of those lines wrong.
        before = manifest(capture("c.json", "Nürburgring Nordeschleife", 20701))
        after = manifest(capture("c.json", "Nürburgring Nordschleife", 20701, sha="b" * 64))
        line, = vendor_captures.changes(before, after)
        self.assertIn("named 'Nürburgring Nordeschleife' -> 'Nürburgring Nordschleife'", line)

    def test_an_upstream_edit_that_moves_no_number_is_still_reported(self) -> None:
        before = manifest(capture("c.json", "Circuit", 1000))
        after = manifest(capture("c.json", "Circuit", 1000, sha="b" * 64))
        line, = vendor_captures.changes(before, after)
        self.assertIn("re-recorded, same measurements", line)

    def test_an_untouched_capture_is_not_reported(self) -> None:
        before = manifest(capture("c.json", "Circuit", 1000))
        self.assertEqual(vendor_captures.changes(before, manifest(
            capture("c.json", "Circuit", 1000))), [])

    def test_a_first_vendoring_lists_everything(self) -> None:
        after = manifest(capture("a.json", "A", 1), capture("b.json", "B", 2))
        self.assertEqual(len(vendor_captures.changes(None, after)), 2)


class VendoredManifestTests(unittest.TestCase):
    """What the committed manifest has to be true of."""

    def test_it_round_trips_through_the_writer_unchanged(self) -> None:
        import json
        text = vendor_captures.CAPTURES.read_text(encoding="utf-8")
        self.assertEqual(vendor_captures.dumps(json.loads(text)), text)


if __name__ == "__main__":
    unittest.main()
