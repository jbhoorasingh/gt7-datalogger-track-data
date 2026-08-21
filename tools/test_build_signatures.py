from __future__ import annotations

import contextlib
import io
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import build_signatures  # noqa: E402

# Enough points at a fine enough spacing that the 20 m grid in
# heading_agreement finds a neighbour for every edge: a circle of radius 100 is
# 628 m round, so 32 points sit about 20 m apart.
LOOP_POINTS = 32
LOOP_RADIUS = 100.0


def loop(*, clockwise: bool = False) -> list[list[int]]:
    """A closed lap as a circle of whole-metre points, in driving order."""
    turn = -1 if clockwise else 1
    return [[round(LOOP_RADIUS * math.cos(turn * 2 * math.pi * i / LOOP_POINTS)),
             round(LOOP_RADIUS * math.sin(turn * 2 * math.pi * i / LOOP_POINTS))]
            for i in range(LOOP_POINTS)]


def loop_edges(*, clockwise: bool = False) -> list[dict]:
    """Edge records round the same circle, carrying the heading of travel."""
    turn = -1 if clockwise else 1
    out = []
    for i in range(LOOP_POINTS):
        angle = turn * 2 * math.pi * i / LOOP_POINTS
        out.append({
            "x": round(LOOP_RADIUS * math.cos(angle), 1),
            "z": round(LOOP_RADIUS * math.sin(angle), 1),
            # Tangent to the circle in the direction of travel.
            "hx": round(-turn * math.sin(angle), 5),
            "hz": round(turn * math.cos(angle), 5),
            "side": "L", "kind": "edge",
        })
    return out


def layout(name: str, official_id: str, length_m: float,
           reverse: dict | None = None) -> dict:
    return {"name": name, "official_id": official_id, "official_name": name,
            "length_m": length_m, "turns": 4, "type": "original", "reverse": reverse}


def capture(file: str, name: str, length_m: float, *, box=(-100.0, 100.0, -100.0, 100.0),
            start=(0.0, 0.0), end=(0.0, 0.0), path=None) -> dict:
    min_x, max_x, min_z, max_z = box
    return {"file": file, "name": name, "variation_name": name, "length_m": length_m,
            "points": 1000, "min_x": min_x, "max_x": max_x, "min_z": min_z, "max_z": max_z,
            "start_x": start[0], "start_z": start[1], "end_x": end[0], "end_z": end[1],
            "path": loop() if path is None else path,
            "sha256": "0" * 64}


def bundle(official_id: str, official_name: str, length_m: float,
           *, edges=None, box=None) -> dict:
    if edges is None:
        edges = loop_edges()
    if box is not None:
        min_x, max_x, min_z, max_z = box
        edges = edges + [{"x": min_x, "z": min_z, "side": "L", "kind": "edge"},
                         {"x": max_x, "z": max_z, "side": "R", "kind": "edge"}]
    return {
        "format": "gt7-datalogger-track-bundle", "version": 4,
        "meta": {"track": official_name, "runs": 1, "source_runs": {"aa": 1},
                 "official": {"official_id": official_id, "official_name": official_name,
                              "length_m": length_m, "reverse": False}},
        "edges": edges,
        "finish_crossings": [], "corners": [], "sections": [],
    }


class SignatureBuildTests(unittest.TestCase):
    """The build, run against fixtures rather than the committed data.

    Real captures are what the numbers in signatures.json come from, but a
    rule is only pinned down by the case that exercises it, and several of
    these — an unmapped name, a line running the wrong way, a stale file —
    must not exist in the real data.
    """

    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        (self.dir / "tracks").mkdir()
        (self.dir / "vendor").mkdir()
        self.patches = mock.patch.multiple(
            build_signatures,
            CATALOG=self.dir / "catalog.json",
            TRACKS=self.dir / "tracks",
            CAPTURES=self.dir / "vendor" / "circuits.json",
            SIGNATURES=self.dir / "signatures.json",
        )
        self.patches.start()
        self.addCleanup(self.patches.stop)

    def write(self, *, layouts: list[dict], captures: list[dict],
              bundles: list[dict] | None = None, path_step_m: int = 20) -> None:
        (self.dir / "catalog.json").write_text(json.dumps(
            {"tracks": [{"name": "Fixtures", "country_name": "Nowhere", "layouts": layouts}]},
        ), encoding="utf-8")
        (self.dir / "vendor" / "circuits.json").write_text(json.dumps(
            {"format": "gt7-datalogger-capture-signatures", "version": 2,
             "path_step_m": path_step_m, "source": {}, "captures": captures},
        ), encoding="utf-8")
        for doc in bundles or []:
            name = doc["meta"]["official"]["official_id"]
            (self.dir / "tracks" / f"{name}.json").write_text(json.dumps(doc), encoding="utf-8")

    def run_main(self, argv: list[str]) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = build_signatures.main(argv)
        return code, out.getvalue()

    def rows(self) -> dict[str, dict]:
        doc = json.loads((self.dir / "signatures.json").read_text(encoding="utf-8"))
        return {r["official_id"]: r for r in doc["signatures"]}

    def doc(self) -> dict:
        return json.loads((self.dir / "signatures.json").read_text(encoding="utf-8"))

    # --- the line, and the order it is in ---------------------------------

    def test_the_path_is_carried_in_driving_order(self) -> None:
        driven = loop()
        self.write(layouts=[layout("Only", "aaaaaa", 1000)],
                   captures=[capture("only.json", "Only", 1000, path=driven)])
        self.assertEqual(self.run_main([])[0], 0)
        # Order is the entire point: a path sorted by position instead of by
        # travel would be a confident wrong answer rather than a decline.
        self.assertEqual(self.rows()["aaaaaa"]["path"], driven)

    def test_a_path_too_short_for_the_app_to_read_is_omitted(self) -> None:
        self.write(layouts=[layout("Only", "aaaaaa", 1000)],
                   captures=[capture("only.json", "Only", 1000, path=[[0, 0], [1, 1]])])
        self.assertEqual(self.run_main([])[0], 0)
        # The app refuses direction from a path under 8 points, so shipping one
        # would be bytes pretending to be evidence.
        self.assertNotIn("path", self.rows()["aaaaaa"])
        self.assertEqual(self.doc()["counts"]["with_path"], 0)

    # --- the reverse twin --------------------------------------------------

    def test_the_reverse_twin_is_named_on_the_forward_row(self) -> None:
        self.write(
            layouts=[layout("Both Ways", "aaaaaa", 1000, reverse={"official_id": "bbbbbb"}),
                     layout("One Way", "cccccc", 1000)],
            captures=[capture("both.json", "Both Ways", 1000),
                      capture("one.json", "One Way", 1000,
                              box=(4900.0, 5100.0, -100.0, 100.0))],
        )
        self.assertEqual(self.run_main([])[0], 0)
        rows = self.rows()
        self.assertEqual(rows["aaaaaa"]["reverse"],
                         {"official_id": "bbbbbb", "official_name": "Both Ways (Reverse)"})
        # Null, not omitted: a lap going the other way round a one-way circuit
        # is a lap that did not drive it, and the app declines rather than names.
        self.assertIsNone(rows["cccccc"]["reverse"])
        self.assertEqual(self.doc()["counts"]["with_reverse_twin"], 1)

    def test_a_reverse_layout_gets_no_row_of_its_own(self) -> None:
        self.write(
            layouts=[layout("Both Ways", "aaaaaa", 1000, reverse={"official_id": "bbbbbb"})],
            captures=[capture("both.json", "Both Ways", 1000)],
        )
        self.assertEqual(self.run_main([])[0], 0)
        doc = self.doc()
        # Not because it cannot be told apart — with a path it can — but
        # because the forward row already carries it.
        self.assertEqual([r["official_id"] for r in doc["signatures"]], ["aaaaaa"])
        self.assertEqual(doc["signatures"][0]["reverse"]["official_id"], "bbbbbb")
        self.assertEqual(doc["counts"]["reverse_layouts"], 1)
        self.assertEqual(doc["counts"]["configurations"], 2)

    def test_a_reverse_bundle_does_not_become_a_second_row(self) -> None:
        self.write(
            layouts=[layout("Both Ways", "aaaaaa", 1000, reverse={"official_id": "bbbbbb"})],
            captures=[capture("both.json", "Both Ways", 1000)],
            bundles=[bundle("aaaaaa", "Both Ways", 1000),
                     bundle("bbbbbb", "Both Ways (Reverse)", 1000)],
        )
        self.assertEqual(self.run_main([])[0], 0)
        self.assertEqual([r["official_id"] for r in self.doc()["signatures"]], ["aaaaaa"])

    # --- where a survey row's path comes from ------------------------------

    def test_a_survey_row_borrows_the_capture_path_and_keeps_the_survey_box(self) -> None:
        driven = loop()
        self.write(
            layouts=[layout("Surveyed", "aaaaaa", 1000)],
            captures=[capture("surveyed.json", "Surveyed", 1010, path=driven)],
            bundles=[bundle("aaaaaa", "Surveyed", 1000, box=(-110.0, 112.0, -110.0, 112.0))],
        )
        self.assertEqual(self.run_main([])[0], 0)
        row = self.rows()["aaaaaa"]
        self.assertEqual(row["provenance"], "survey")
        self.assertEqual((row["min_x"], row["max_x"]), (-110.0, 112.0))
        self.assertEqual(row["length_m"], 1010.0)
        # Borrowed purely as direction evidence; the box stays the survey's.
        self.assertEqual(row["path"], driven)
        self.assertEqual(row["flags"], [])

    def test_a_borrowed_path_running_against_the_survey_is_flagged_and_dropped(self) -> None:
        self.write(
            layouts=[layout("Surveyed", "aaaaaa", 1000)],
            # A capture of the REVERSE layout, borrowed for a forward row: the
            # exact misfiling the path field exists to stop.
            captures=[capture("surveyed.json", "Surveyed", 1000, path=loop(clockwise=True))],
            bundles=[bundle("aaaaaa", "Surveyed", 1000, edges=loop_edges())],
        )
        code, printed = self.run_main([])
        self.assertEqual(code, 0)
        row = self.rows()["aaaaaa"]
        self.assertIn(build_signatures.FLAG_PATH_HEADING_DISAGREES, row["flags"])
        # Loudly, and without picking one: the row keeps its box and loses its
        # path, so the app declines direction rather than answering wrongly.
        self.assertNotIn("path", row)
        self.assertIn("AGAINST THE SURVEY", printed)

    def test_a_survey_without_a_capture_has_no_path_at_all(self) -> None:
        self.write(
            layouts=[layout("Surveyed", "aaaaaa", 1000)],
            captures=[capture("surveyed.json", "Surveyed", 1010, start=(0.0, 0.0),
                              end=(500.0, 0.0))],  # dropped: not a whole lap
            bundles=[bundle("aaaaaa", "Surveyed", 1000)],
        )
        self.assertEqual(self.run_main([])[0], 0)
        row = self.rows()["aaaaaa"]
        self.assertNotIn("path", row)
        self.assertEqual(row["length_m"], 1000.0)
        self.assertEqual(row["flags"], [build_signatures.FLAG_LENGTH_FROM_CATALOG])

    # --- rules carried over from the first spec ----------------------------

    def test_a_capture_that_does_not_close_is_dropped_and_reported(self) -> None:
        self.write(
            layouts=[layout("Whole Lap", "aaaaaa", 1000), layout("Fragment", "bbbbbb", 1000)],
            captures=[
                capture("whole.json", "Whole Lap", 1000, start=(0.0, 0.0), end=(3.0, 0.0)),
                # 500 m from where it started, against a threshold of
                # max(60, 5 % of 1000) = 60 m.
                capture("fragment.json", "Fragment", 1000, start=(0.0, 0.0), end=(500.0, 0.0)),
            ],
        )
        code, printed = self.run_main([])
        self.assertEqual(code, 0)
        doc = self.doc()
        self.assertEqual([r["official_id"] for r in doc["signatures"]], ["aaaaaa"])
        self.assertEqual([d["official_id"] for d in doc["dropped_captures"]], ["bbbbbb"])
        self.assertEqual(doc["dropped_captures"][0]["closes_at_m"], 500.0)
        # A silent drop reads as "we covered everything" when we did not.
        self.assertIn("Fragment", printed)
        self.assertIn("500.0 m from its start", printed)

    def test_an_unmapped_capture_name_fails_the_build(self) -> None:
        self.write(
            layouts=[layout("Known Circuit", "aaaaaa", 1000)],
            captures=[capture("known.json", "Known Circuit", 1000),
                      capture("stranger.json", "Circuit Nobody Has Heard Of", 1000)],
        )
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stdout(io.StringIO()):
            build_signatures.main([])
        message = str(raised.exception)
        self.assertIn("Circuit Nobody Has Heard Of", message)
        self.assertIn("CAPTURE_NAME_FIXES", message)
        self.assertFalse((self.dir / "signatures.json").exists())

    def test_a_bundle_naming_no_known_configuration_fails_the_build(self) -> None:
        self.write(
            layouts=[layout("Known Circuit", "aaaaaa", 1000)],
            captures=[capture("known.json", "Known Circuit", 1000)],
            bundles=[bundle("zzzzzz", "Circuit From Nowhere", 1000)],
        )
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stdout(io.StringIO()):
            build_signatures.main([])
        self.assertIn("zzzzzz", str(raised.exception))
        self.assertFalse((self.dir / "signatures.json").exists())

    def test_two_colliding_circuits_each_list_the_other(self) -> None:
        self.write(
            layouts=[layout("Twin A", "aaaaaa", 1000), layout("Twin B", "bbbbbb", 1010),
                     layout("Elsewhere", "cccccc", 1000)],
            captures=[capture("a.json", "Twin A", 1000),
                      capture("b.json", "Twin B", 1010),
                      capture("c.json", "Elsewhere", 1000,
                              box=(4900.0, 5100.0, -100.0, 100.0))],
        )
        self.assertEqual(self.run_main([])[0], 0)
        rows = self.rows()
        self.assertEqual(rows["aaaaaa"]["ambiguous_with"], ["bbbbbb"])
        self.assertEqual(rows["bbbbbb"]["ambiguous_with"], ["aaaaaa"])
        # Non-empty is normal, but it has to mean something: a circuit half a
        # world away is not ambiguous with anything.
        self.assertEqual(rows["cccccc"]["ambiguous_with"], [])

    def test_a_catalog_length_disagreement_flags_without_correcting(self) -> None:
        self.write(
            layouts=[layout("Disputed", "aaaaaa", 1000), layout("Agreed", "bbbbbb", 1000)],
            captures=[capture("disputed.json", "Disputed", 1200),   # +20 %
                      capture("agreed.json", "Agreed", 1030)],      # +3 %, inside tolerance
        )
        self.assertEqual(self.run_main([])[0], 0)
        rows = self.rows()
        self.assertEqual(rows["aaaaaa"]["flags"], [build_signatures.FLAG_LENGTH_DISAGREES])
        # The measurement stands. Which of the two is wrong is a human's call.
        self.assertEqual(rows["aaaaaa"]["length_m"], 1200.0)
        self.assertEqual(rows["bbbbbb"]["flags"], [])

    def test_check_passes_on_a_fresh_file_and_fails_on_a_stale_one(self) -> None:
        self.write(layouts=[layout("Only", "aaaaaa", 1000)],
                   captures=[capture("only.json", "Only", 1000)])
        self.assertEqual(self.run_main([])[0], 0)

        code, printed = self.run_main(["--check"])
        self.assertEqual(code, 0)
        self.assertIn("up to date", printed)

        doc = self.doc()
        doc["signatures"][0]["length_m"] = 999.0
        (self.dir / "signatures.json").write_text(json.dumps(doc), encoding="utf-8")

        code, printed = self.run_main(["--check"])
        self.assertEqual(code, 1)
        self.assertIn("stale", printed)
        # A failed check reports, it does not repair.
        self.assertEqual(self.doc()["signatures"][0]["length_m"], 999.0)

    def test_the_published_step_is_the_one_the_vendored_data_has(self) -> None:
        self.write(layouts=[layout("Only", "aaaaaa", 1000)],
                   captures=[capture("only.json", "Only", 1000)], path_step_m=5)
        self.assertEqual(self.run_main([])[0], 0)
        # Read from the manifest rather than assumed, so changing the step is
        # visibly a re-vendor and cannot drift from what the paths actually are.
        self.assertEqual(self.doc()["counts"]["path_step_m"], 5)


class CommittedSignatureTests(unittest.TestCase):
    """What the file this repository actually ships has to be true of."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = json.loads(build_signatures.SIGNATURES.read_text(encoding="utf-8"))
        cls.vendored = json.loads(build_signatures.CAPTURES.read_text(encoding="utf-8"))

    def test_the_committed_file_matches_its_inputs(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(build_signatures.main(["--check"]), 0)

    def test_every_row_is_shaped_the_way_the_app_reads_it(self) -> None:
        seen = set()
        for row in self.doc["signatures"]:
            present = [k for k in row]
            self.assertEqual(present, [k for k in build_signatures.ROW_KEYS if k in row],
                             f"{row['official_name']}: keys out of contract order")
            self.assertNotIn(row["official_id"], seen)
            seen.add(row["official_id"])
            self.assertIn(row["provenance"], ("survey", "capture"))
            self.assertGreater(row["length_m"], 0)
            self.assertLessEqual(row["min_x"], row["max_x"])
            self.assertLessEqual(row["min_z"], row["max_z"])

    def test_every_path_is_readable_by_the_app(self) -> None:
        for row in self.doc["signatures"]:
            path = row.get("path")
            if path is None:
                continue
            # The app refuses under 8 points and over 10,000.
            self.assertGreaterEqual(len(path), build_signatures.MIN_PATH_POINTS)
            self.assertLess(len(path), 10_000)
            for point in path:
                self.assertEqual(len(point), 2)
                self.assertTrue(all(isinstance(c, int) for c in point), point)

    def test_a_reverse_twin_is_named_and_identified_or_absent_entirely(self) -> None:
        ids = {r["official_id"] for r in self.doc["signatures"]}
        for row in self.doc["signatures"]:
            twin = row["reverse"]
            if twin is None:
                continue
            # Half a name cannot be written to a session, and the app refuses
            # a row carrying one without the other.
            self.assertTrue(twin["official_id"] and twin["official_name"])
            self.assertTrue(twin["official_name"].endswith("(Reverse)"))
            # A twin is reached through this row, never as a row of its own.
            self.assertNotIn(twin["official_id"], ids)

    def test_a_survey_row_path_is_the_capture_it_borrowed(self) -> None:
        by_id = {r["official_id"]: r for r in self.doc["signatures"]}
        lengths = {c["length_m"]: c for c in self.vendored["captures"]}
        borrowed = 0
        for row in self.doc["signatures"]:
            if row["provenance"] != "survey" or "path" not in row:
                continue
            capture = lengths.get(row["length_m"])
            self.assertIsNotNone(capture, row["official_name"])
            self.assertEqual(row["path"], capture["path"], row["official_name"])
            borrowed += 1
        self.assertEqual(borrowed, sum(1 for r in by_id.values()
                                       if r["provenance"] == "survey" and "path" in r))
        self.assertGreater(borrowed, 0)

    def test_every_bundle_in_this_repository_is_a_survey_row(self) -> None:
        bundles = {json.loads(p.read_text(encoding="utf-8"))["meta"]["official"]["official_id"]
                   for p in sorted(build_signatures.TRACKS.glob("*.json"))}
        surveyed = {r["official_id"] for r in self.doc["signatures"]
                    if r["provenance"] == "survey"}
        self.assertEqual(bundles, surveyed)

    def test_ambiguity_is_recorded_from_both_sides_where_it_is_mutual(self) -> None:
        rows = {r["official_id"]: r for r in self.doc["signatures"]}
        for row in self.doc["signatures"]:
            for other in row["ambiguous_with"]:
                self.assertIn(other, rows, f"{row['official_name']} points at a missing row")


if __name__ == "__main__":
    unittest.main()
