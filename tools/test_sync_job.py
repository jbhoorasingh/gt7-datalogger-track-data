"""Tests for the merge job.

Three layers, tested three ways. The corroboration policy and the gate are
arithmetic and are tested as arithmetic, case for case against the sync
service's reference implementation (`src/domain/policy.ts` there), because a
quorum off by one is a wall somebody drew alone published as fact. Layout
identification is tested against every survey this repository actually holds:
each must be recognised as the configuration its contributor confirmed, and
each must be told from its reverse twin. And the whole run is exercised
against a temporary copy of the repository with a bare git remote, a fake
service that records what it was told, and a fake forge — so the branch, the
commit, the pull request, the statuses and the publication are all asserted
on rather than trusted.

The end-to-end tests need the datalogger's compiler. They skip without it;
`.github/workflows/sync.yml` installs it and runs them before every run. To
run them from a checkout of the datalogger instead:

    GT7_DATALOGGER_BACKEND=/path/to/gt7-datalogger/backend python tools/test_sync_job.py

One more layer runs only when pointed at a live service — a local
`wrangler dev` of the sync service, seeded — and checks that every request
the job makes is one the real handlers accept:

    GT7_SYNC_TEST_URL=http://localhost:8787 GT7_SYNC_SERVICE_KEY=… python tools/test_sync_job.py
"""

from __future__ import annotations

import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

backend = os.environ.get("GT7_DATALOGGER_BACKEND")
if backend:
    sys.path.insert(0, backend)
try:
    from app.processing import track_compile  # noqa: F401

    HAVE_COMPILER = True
except ImportError:
    HAVE_COMPILER = False

import corrections  # noqa: E402
import sync_job  # noqa: E402
from sync_job import (  # noqa: E402
    Context,
    Git,
    Repository,
    ServiceError,
    corroborate,
    crossing_spread,
    evaluate_gate,
    identify_layout,
    kind_changes,
    new_metres,
    policy_kinds,
    candidate_document,
    publishable_copy,
    run,
    with_authored,
)

# ── fixtures ────────────────────────────────────────────────────────────────

ALICE, BOB, CAROL = "usr_alice", "usr_bob", "usr_carol"
ACCOUNTS = {"aaaa11": ALICE, "aaaa22": ALICE, "bbbb11": BOB, "cccc11": CAROL}

SURVEY = ROOT / "tracks" / "deep-forest-raceway.json"
DEEP_FOREST = "0457d4"
DEEP_FOREST_REVERSE = "f3e708"


def load_survey(path: Path = SURVEY) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


CORNERS = [
    {"n": 1, "name": "Tunnel Hairpin", "direction": "L", "apex": {"x": 12.5, "z": -40.0},
     "entry": None, "exit": None, "note": ""},
    {"n": 2, "name": "", "direction": None, "apex": {"x": 80.0, "z": 5.5},
     "entry": None, "exit": None, "note": ""},
]
SECTIONS = [{"n": 1, "name": "Back Straight", "start": {"x": 0.0, "z": 0.0}, "end": {"x": 300.0, "z": 0.0}}]


def gate_side(pct: float = 100.0, closed: bool = True, gaps: int = 0) -> dict[str, Any]:
    return {"pct": pct, "closed": closed, "gaps": gaps}


def gate_input(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "published": False,
        "crossings": [{"x": 0, "z": 0}, {"x": 1, "z": 0}, {"x": 2, "z": 0}],
        "contributor_official_id": "ring-gp",
        "signature_official_id": "ring-gp",
        "coverage": {"left": gate_side(), "right": gate_side()},
    }
    base.update(overrides)
    return base


SETTINGS = {"min_finish_crossings": 3, "crossing_spread_m": 5, "require_full_coverage": True}


def edge(x: float, z: float, side: str, votes: dict[str, dict[str, list[int]]]) -> dict[str, Any]:
    return {"x": x, "z": z, "y": None, "hx": 1.0, "hz": 0.0, "side": side,
            "kind": sync_job.resolve_kind(votes), "votes": votes, "run": 1, "tw": None}


def document(edges: list[dict[str, Any]], sources: dict[str, int]) -> dict[str, Any]:
    return {
        "format": "gt7-datalogger-track-bundle", "version": 5,
        "meta": {"track": "Ring GP", "runs": sum(sources.values()), "source_runs": sources,
                 "updated_at": "2026-09-01T00:00:00+00:00",
                 "official": {"track": "Ring", "layout": "GP", "official_id": "ring-gp",
                              "official_name": "Ring GP", "turns": 3, "length_m": 1000.0, "reverse": False}},
        "edges": edges, "finish_crossings": [], "corners": [], "sections": [],
    }


# ── the corroboration policy ────────────────────────────────────────────────


class CorroborationTests(unittest.TestCase):
    def test_inferred_tier_decides_from_a_single_account(self) -> None:
        result = corroborate({"auto": {"aaaa11": [4, 7]}}, ACCOUNTS, 2)
        self.assertEqual((result["kind"], result["tier"], result["pending"]), ("auto", "inferred", []))

    def test_manual_kind_below_quorum_is_held_as_pending_evidence(self) -> None:
        result = corroborate({"wall": {"aaaa11": [3, 7]}, "straddle": {"bbbb11": [2, 4]}}, ACCOUNTS, 2)
        self.assertEqual(result["kind"], "straddle")
        self.assertEqual(result["pending"], ["wall"])
        self.assertEqual(result["corroborated"], [])
        self.assertEqual(result["evidence"][0]["contributors"], 1)

    def test_manual_kind_decides_once_a_second_account_votes_it(self) -> None:
        result = corroborate({"wall": {"aaaa11": [3, 7], "bbbb11": [1, 2]}, "straddle": {"cccc11": [9, 9]}},
                             ACCOUNTS, 2)
        self.assertEqual((result["kind"], result["tier"]), ("wall", "manual"))
        self.assertEqual(result["evidence"][0]["accounts"], [ALICE, BOB])

    def test_counts_accounts_not_installations(self) -> None:
        result = corroborate({"wall": {"aaaa11": [3, 7], "aaaa22": [2, 5]}, "auto": {"bbbb11": [1, 1]}}, ACCOUNTS, 2)
        self.assertEqual(result["kind"], "auto")
        self.assertFalse(result["evidence"][0]["quorum"])

    def test_satisfied_at_exactly_the_quorum(self) -> None:
        three = {"runoff": {"aaaa11": [1, 1], "bbbb11": [1, 1], "cccc11": [1, 1]}, "auto": {"aaaa11": [5, 5]}}
        self.assertEqual(corroborate(three, ACCOUNTS, 3)["kind"], "runoff")
        self.assertEqual(corroborate(three, ACCOUNTS, 4)["kind"], "auto")

    def test_every_drawn_source_is_one_contributor_and_never_a_quorum_alone(self) -> None:
        result = corroborate({"edge": {"drawn-one": [1, 1], "drawn-two": [1, 1], "aaaa11": [1, 1]},
                              "auto": {"bbbb11": [3, 3]}}, ACCOUNTS, 3)
        self.assertEqual(result["evidence"][0]["contributors"], 2)
        alone = corroborate({"edge": {"drawn-one": [1, 1], "drawn-two": [1, 1]}, "auto": {"bbbb11": [3, 3]}},
                            ACCOUNTS, 1)
        self.assertEqual(alone["kind"], "auto")

    def test_a_source_bound_to_no_account_is_evidence_not_a_voice(self) -> None:
        result = corroborate({"wall": {"aaaa11": [1, 1], "zzzz99": [1, 1]}, "auto": {"bbbb11": [1, 1]}},
                             ACCOUNTS, 2)
        self.assertEqual(result["kind"], "auto")
        self.assertEqual(result["evidence"][0]["unmapped"], ["zzzz99"])


class PolicyOnDocumentsTests(unittest.TestCase):
    def test_policy_kinds_reports_pending_conflicts_and_decisions(self) -> None:
        doc = document([
            edge(0, 0, "L", {"wall": {"aaaa11": [1, 1]}, "auto": {"bbbb11": [1, 1]}}),
            edge(1, 0, "L", {"wall": {"aaaa11": [1, 1], "bbbb11": [1, 1]},
                             "runoff": {"cccc11": [1, 1], "aaaa22": [1, 1]}}),
            edge(2, 0, "L", {"edge": {"aaaa11": [1, 1]}}),
        ], {"aaaa11": 1, "aaaa22": 1, "bbbb11": 1, "cccc11": 1})
        report = policy_kinds(doc, ACCOUNTS, 2, {(2, 0, "L"): "runoff"})
        self.assertEqual(report["kinds"][(0, 0, "L")], "auto")
        self.assertEqual(report["pending"], [(0, 0, "L"), (2, 0, "L")])
        self.assertEqual([c["kinds"] for c in report["conflicts"]], [["wall", "runoff"]])
        self.assertEqual(report["decided"], [(2, 0, "L")])
        self.assertEqual(report["kinds"][(2, 0, "L")], "runoff")

    def test_publishable_copy_never_touches_the_stored_document(self) -> None:
        doc = document([edge(0, 0, "L", {"wall": {"aaaa11": [1, 1]}, "auto": {"bbbb11": [1, 1]}})],
                       {"aaaa11": 1, "bbbb11": 1})
        kinds = policy_kinds(doc, ACCOUNTS, 2)["kinds"]
        drawn = publishable_copy(doc, kinds)
        self.assertEqual(drawn["edges"][0]["kind"], "auto")
        self.assertEqual(doc["edges"][0]["kind"], "wall")

    def test_kind_changes_are_corroborated_only_when_the_policy_agrees(self) -> None:
        before = document([edge(0, 0, "L", {"auto": {"bbbb11": [1, 1]}}),
                           edge(1, 0, "L", {"auto": {"bbbb11": [1, 1]}})], {"bbbb11": 1})
        after = document([edge(0, 0, "L", {"auto": {"bbbb11": [1, 1]}, "wall": {"aaaa11": [1, 1]}}),
                          edge(1, 0, "L", {"auto": {"bbbb11": [1, 1]}, "wall": {"aaaa11": [1, 1], "cccc11": [1, 1]}}),
                          edge(2, 0, "L", {"auto": {"aaaa11": [1, 1]}})],
                         {"aaaa11": 1, "bbbb11": 1, "cccc11": 1})
        changes = kind_changes(before, after, ACCOUNTS, 2)
        by_x = {c["x"]: c for c in changes}
        self.assertEqual(set(by_x), {0, 1})
        self.assertFalse(by_x[0]["corroborated"])
        self.assertTrue(by_x[1]["corroborated"])
        self.assertEqual(new_metres(before, after), 1)
        self.assertEqual(kind_changes(None, after, ACCOUNTS, 2), [])


# ── the gate ────────────────────────────────────────────────────────────────


class SmoothingSwitchTests(unittest.TestCase):
    """`compile.smooth_borders`, as the service serves it and as the job reads it."""

    def test_the_administrators_answer_is_read_from_the_policy(self) -> None:
        self.assertIs(sync_job.smooth_borders({"compile": {"smooth_borders": False}}), False)
        self.assertIs(sync_job.smooth_borders({"compile": {"smooth_borders": True}}), True)

    def test_a_service_from_before_the_switch_said_nothing(self) -> None:
        # None, not True: the compiler's default applies, and the job does not
        # put words in the administrator's mouth.
        self.assertIsNone(sync_job.smooth_borders({"policy": {"manual_quorum": 2}}))
        self.assertIsNone(sync_job.smooth_borders({"compile": None}))

    def test_only_a_boolean_is_an_answer(self) -> None:
        # "off" is truthy. A job that took it for yes would go on smoothing a
        # map whose owner had said not to.
        for value in ("off", "false", 0, 1, None, []):
            self.assertIsNone(sync_job.smooth_borders({"compile": {"smooth_borders": value}}), value)

    @unittest.skipUnless(HAVE_COMPILER, "needs the datalogger's compiler (app.processing.track_compile)")
    def test_the_compiler_is_told_and_the_document_says_what_it_got(self) -> None:
        if not sync_job.compiler_takes_smooth():
            self.skipTest("the installed compiler is from before it could smooth")
        doc = load_survey()
        off = sync_job.compile_geometry(doc, False)
        on = sync_job.compile_geometry(doc, True)
        self.assertIsNone(off["smoothing"])
        self.assertEqual(on["smoothing"]["method"], "taubin")
        # Off is the evidence as recorded: every drawn vertex is a record.
        recorded = {(round(e["x"], 2), round(e["z"], 2)) for e in doc["edges"]}
        drawn = [(v[0], v[1]) for side in ("L", "R") for run in off["borders"][side] for v in run]
        self.assertTrue(drawn and all(v in recorded for v in drawn))
        # On moves them, a little, and never invents or loses a gap.
        self.assertNotEqual(on["borders"], off["borders"])
        self.assertEqual(on["gaps"], off["gaps"])

    def test_an_older_compiler_is_called_as_it_always_was(self) -> None:
        calls: list[tuple[Any, ...]] = []

        class Old:
            @staticmethod
            def compile_bundle(doc: dict[str, Any]) -> dict[str, Any]:
                calls.append((doc,))
                return {"format": "gt7-datalogger-track-compiled"}

        original = sync_job._compiler
        sync_job._compiler = lambda: Old
        try:
            self.assertFalse(sync_job.compiler_takes_smooth())
            # Not a TypeError for a keyword it never had.
            self.assertEqual(sync_job.compile_geometry({"edges": []}, False)["format"],
                             "gt7-datalogger-track-compiled")
        finally:
            sync_job._compiler = original
        self.assertEqual(len(calls), 1)


class AuthoredWorkTests(unittest.TestCase):
    def test_corners_and_sections_ride_along_with_the_geometry(self) -> None:
        compiled = {"format": "gt7-datalogger-track-compiled", "borders": {"L": [], "R": []}}
        out = with_authored(compiled, {"corners": CORNERS, "sections": SECTIONS})
        self.assertEqual(out["corners"], CORNERS)
        self.assertEqual(out["sections"], SECTIONS)
        self.assertEqual(out["borders"], compiled["borders"])

    def test_the_geometry_the_gate_measured_is_left_as_it_was(self) -> None:
        compiled = {"borders": {"L": [], "R": []}}
        doc = {"corners": copy.deepcopy(CORNERS), "sections": []}
        out = with_authored(compiled, doc)
        self.assertNotIn("corners", compiled)
        out["corners"][0]["name"] = "changed"
        self.assertEqual(doc["corners"][0]["name"], "Tunnel Hairpin")

    def test_a_candidate_also_carries_the_crossings_the_gate_measured(self) -> None:
        crossings = [{"x": 0.0, "z": 1.0, "hx": 1.0, "hz": 0.0, "lap": 2.0}]
        doc = {"corners": CORNERS, "sections": SECTIONS, "finish_crossings": crossings}
        out = candidate_document({"borders": {"L": [], "R": []}}, doc)
        self.assertEqual(out["finish_crossings"], crossings)
        self.assertEqual(out["corners"], CORNERS)
        out["finish_crossings"][0]["x"] = 9.0
        self.assertEqual(doc["finish_crossings"][0]["x"], 0.0)
        self.assertEqual(candidate_document({"borders": {}}, {})["finish_crossings"], [])

    def test_a_circuit_nobody_has_marked_publishes_empty_lists(self) -> None:
        out = with_authored({"borders": {}}, {})
        self.assertEqual((out["corners"], out["sections"]), ([], []))


class GateTests(unittest.TestCase):
    def test_spread_is_a_diameter(self) -> None:
        self.assertEqual(crossing_spread([]), 0.0)
        self.assertEqual(crossing_spread([{"x": 0, "z": 0}, {"x": 4, "z": 0}, {"x": 8, "z": 0}]), 8.0)
        self.assertIsNone(crossing_spread([{"x": 0, "z": 0}, {"x": "no", "z": 0}]))

    def test_first_publication_passes_when_everything_holds(self) -> None:
        result = evaluate_gate(gate_input(), SETTINGS)
        self.assertTrue(result["pass"])
        self.assertEqual(result["mode"], "first_publication")
        self.assertEqual([c["id"] for c in result["criteria"]],
                         ["finish_crossings", "crossing_spread", "layout_agreement", "perimeter_complete"])

    def test_each_first_publication_criterion_fails_on_its_own(self) -> None:
        self.assertEqual(evaluate_gate(gate_input(crossings=[{"x": 0, "z": 0}]), SETTINGS)["failed"], ["finish_crossings"])
        wide = [{"x": 0, "z": 0}, {"x": 3, "z": 0}, {"x": 6, "z": 0}]
        self.assertEqual(evaluate_gate(gate_input(crossings=wide), SETTINGS)["failed"], ["crossing_spread"])
        self.assertEqual(evaluate_gate(gate_input(signature_official_id="ring-gp-reverse"), SETTINGS)["failed"],
                         ["layout_agreement"])
        gappy = gate_input(coverage={"left": gate_side(96.6, False, 2), "right": gate_side()})
        result = evaluate_gate(gappy, SETTINGS)
        self.assertEqual(result["failed"], ["perimeter_complete"])
        self.assertIn("96.6%, open, 2 gaps", result["criteria"][3]["value"])
        self.assertTrue(evaluate_gate(gappy, {**SETTINGS, "require_full_coverage": False})["pass"])

    def test_a_layout_a_person_accepted_passes_with_their_name_on_it(self) -> None:
        result = evaluate_gate(gate_input(signature_official_id="other", layout_accepted_at="2026-09-18T00:00:00Z"), SETTINGS)
        self.assertTrue(result["pass"])
        self.assertIn("accepted by the administrator", result["criteria"][2]["value"])

    def test_an_update_must_hold_coverage_and_corroborate_kind_changes(self) -> None:
        held = gate_input(published=True, previous_coverage={"left": gate_side(90), "right": gate_side(80)},
                          coverage={"left": gate_side(95), "right": gate_side(80)}, kind_changes=[])
        result = evaluate_gate(held, SETTINGS)
        self.assertTrue(result["pass"])
        self.assertEqual(result["mode"], "update")
        self.assertEqual([c["id"] for c in result["criteria"]][-2:], ["coverage_held", "kind_changes"])

        lost = evaluate_gate({**held, "coverage": {"left": gate_side(89), "right": gate_side(80)}}, SETTINGS)
        self.assertEqual(lost["failed"], ["coverage_held"])
        unknown = evaluate_gate({**held, "previous_coverage": None}, SETTINGS)
        self.assertEqual(unknown["failed"], ["coverage_held"])

        changed = evaluate_gate({**held, "kind_changes": [
            {"side": "L", "x": 12.34, "z": -5.0, "from": "auto", "to": "wall", "corroborated": False},
            {"side": "R", "x": 1.0, "z": 1.0, "from": "auto", "to": "straddle", "corroborated": True},
        ]}, SETTINGS)
        self.assertEqual(changed["failed"], ["kind_changes"])
        self.assertIn("1 of 2 not corroborated (first at (12.3, -5.0) side L: auto → wall)",
                      changed["criteria"][-1]["value"])


# ── which layout a survey is of ─────────────────────────────────────────────


class IdentificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.signatures = Repository(ROOT).signatures()

    def test_every_survey_in_the_repository_is_recognised_as_its_confirmed_layout(self) -> None:
        for path in sorted((ROOT / "tracks").glob("*.json")):
            doc = load_survey(path)
            claimed = doc["meta"]["official"]["official_id"]
            with self.subTest(path.name):
                layout = identify_layout(doc, None, self.signatures)
                self.assertIs(layout["agrees"], True, layout)
                self.assertEqual(layout["signature_official_id"], claimed)

    def test_a_survey_claimed_as_its_reverse_twin_is_caught(self) -> None:
        doc = load_survey()
        doc["meta"]["official"]["official_id"] = DEEP_FOREST_REVERSE
        layout = identify_layout(doc, None, self.signatures)
        self.assertIs(layout["agrees"], False)
        self.assertEqual(layout["signature_official_id"], DEEP_FOREST)
        self.assertGreater(layout["heading_agree"], layout["heading_disagree"])
        self.assertTrue(layout["signature_line"])

    def test_a_venue_no_signature_describes_is_neither_agreed_nor_disputed(self) -> None:
        doc = load_survey()
        for e in doc["edges"]:
            e["x"] += 50_000
        layout = identify_layout(doc, None, self.signatures)
        self.assertIsNone(layout["agrees"])
        self.assertEqual(layout["signature_official_id"], "")


# ── the whole run, against a fake service and a real git ────────────────────


class FakeService:
    """The sync service as the job sees it, remembering everything it was told."""

    def __init__(self, uploads: list[dict[str, Any]], bundles: dict[str, dict[str, Any]],
                 policy: dict[str, Any] | None = None, sources: dict[str, str] | None = None) -> None:
        self.uploads = uploads
        self.bundles = bundles
        # 20 m rather than the spec's 5 m default: the real survey these tests
        # merge crosses its finish line at five lateral positions 12.8 m
        # apart, which the Euclidean spread the reference gate measures
        # counts against it. The threshold is the administrator's to set;
        # the tests are about the job, not about the default.
        self._policy = policy or {"policy": {"manual_quorum": 2},
                                  "gate": {"min_finish_crossings": 3, "crossing_spread_m": 20,
                                           "require_full_coverage": True, "auto_merge": False}}
        self._sources = sources or {}
        self.statuses: list[tuple[str, str, str, str]] = []
        self.issues: list[dict[str, Any]] = []
        self.merge_requests: list[dict[str, Any]] = []
        self.compiled: dict[str, dict[str, Any]] = {}
        self.candidates: dict[str, tuple[dict[str, Any], str]] = {}
        self.refuses_candidates = False
        self.published: list[tuple[str, dict[str, Any]]] = []
        self.runs: list[dict[str, Any]] = []
        self.kind: list[dict[str, Any]] = []
        self.layout: list[dict[str, Any]] = []
        self.waiting: list[dict[str, Any]] = []
        self.settled: list[tuple[str, str, str]] = []
        self.refuses_to_settle: set[str] = set()
        self.asked_about: list[str] = []
        self.edits: list[dict[str, Any]] = []
        self.edit_docs: dict[str, dict[str, Any]] = {}
        self.edit_reports: list[tuple[str, str, str, str]] = []

    def waiting_merge_requests(self, official_id: str = "") -> list[dict[str, Any]]:
        self.asked_about.append(official_id)
        return [dict(row) for row in self.waiting if not official_id or row["official_id"] == official_id]

    def settle_merge_request(self, merge_request_id: str, status: str, pr_state: str) -> dict[str, Any]:
        if merge_request_id in self.refuses_to_settle:
            raise ServiceError(500, "internal", "a bad minute")
        self.settled.append((merge_request_id, status, pr_state))
        self.waiting = [row for row in self.waiting if row["id"] != merge_request_id]
        return {"merge_request_id": merge_request_id, "status": status, "outcome": "updated"}

    def open_edits(self, official_id: str = "") -> list[dict[str, Any]]:
        return [dict(e) for e in self.edits
                if e.get("status", "pending") in ("pending", "pr_open")
                and (not official_id or e["official_id"] == official_id)]

    def fetch_edit(self, edit_id: str) -> dict[str, Any]:
        return copy.deepcopy(self.edit_docs[edit_id])

    def report_edit(self, edit_id: str, status: str, reason: str = "", pr_url: str = "") -> None:
        self.edit_reports.append((edit_id, status, reason, pr_url))
        for edit in self.edits:
            if edit["id"] == edit_id:
                edit["status"] = status
                edit["pr_url"] = pr_url or edit.get("pr_url", "")

    def policy(self) -> dict[str, Any]:
        return self._policy

    def pending_uploads(self, official_id: str = "") -> list[dict[str, Any]]:
        return [u for u in self.uploads if not official_id or u["official_id"] == official_id]

    def fetch_bundle(self, upload: dict[str, Any]) -> dict[str, Any]:
        if upload["id"] not in self.bundles:
            raise ServiceError(404, "not_found", "the stored document for that upload is gone")
        return copy.deepcopy(self.bundles[upload["id"]])

    def sources(self) -> dict[str, str]:
        return dict(self._sources)

    def kind_decisions(self, official_id: str) -> list[dict[str, Any]]:
        return [d for d in self.kind if d["official_id"] == official_id]

    def layout_decisions(self, official_id: str) -> list[dict[str, Any]]:
        return [d for d in self.layout if d["official_id"] == official_id]

    def open_run(self) -> str:
        self.runs.append({"id": "job_test", "open": True})
        return "job_test"

    def close_run(self, run_id: str, ok: bool, counters: dict[str, int], detail: dict[str, Any]) -> None:
        self.runs.append({"id": run_id, "ok": ok, **counters, "detail": detail})

    def report_status(self, upload_id: str, status: str, reason: str = "", pr_url: str = "") -> None:
        self.statuses.append((upload_id, status, reason, pr_url))

    def report_merge_request(self, **fields: Any) -> dict[str, Any]:
        self.merge_requests.append(fields)
        return {"merge_request": fields}

    def raise_issue(self, **fields: Any) -> dict[str, Any]:
        self.issues.append(fields)
        return {"issue_id": f"iss_{len(self.issues)}", "outcome": "raised"}

    def put_compiled(self, official_id: str, compiled: dict[str, Any]) -> dict[str, Any]:
        self.compiled[official_id] = compiled
        return {"official_id": official_id, "r2_key": f"published/{official_id}.json"}

    def put_candidate(self, official_id: str, compiled: dict[str, Any], pr_url: str) -> dict[str, Any]:
        if self.refuses_candidates:
            raise ServiceError(404, "not_found", "no such route")
        self.candidates[official_id] = (compiled, pr_url)
        return {"official_id": official_id, "r2_key": f"candidates/{official_id}.json"}

    def publish(self, official_id: str, facts: dict[str, Any]) -> dict[str, Any]:
        self.published.append((official_id, facts))
        return {"track": facts}


class FakeForge:
    def __init__(self, merges: bool = True) -> None:
        self.merges = merges
        self.upserts: list[tuple[str, str, str, bool]] = []
        self.merged: list[str] = []
        self.workflows: list[str] = []
        self.already_merged: dict[str, str] = {}
        self.open: dict[str, str] = {}
        self.states: dict[str, str] = {}
        self.looked_at: list[str] = []

    def pr_state(self, pr_url: str) -> str:
        self.looked_at.append(pr_url)
        return self.states.get(pr_url, "OPEN")

    def open_pr_url(self, branch: str) -> str:
        return self.open.get(branch, "")

    def merged_pr_url(self, branch: str) -> str:
        return self.already_merged.get(branch, "")

    def upsert(self, branch: str, title: str, body: str, draft: bool) -> str:
        self.upserts.append((branch, title, body, draft))
        self.open[branch] = f"https://github.com/example/track-data/pull/{len(self.upserts)}"
        return self.open[branch]

    def merge(self, branch: str, attempts: int = 5, wait: Any = None) -> bool:
        if self.merges:
            self.merged.append(branch)
        return self.merges

    def workflow_run(self, workflow: str) -> None:
        self.workflows.append(workflow)


def upload_row(upload_id: str, official_id: str, source_id: str, user_id: str) -> dict[str, Any]:
    return {"id": upload_id, "user_id": user_id, "source_id": source_id, "official_id": official_id,
            "track_name": "Deep Forest Raceway", "version": 4, "edges": 100, "runs": 1, "crossings": 4,
            "bytes": 1000, "digest": "abc", "received_at": "2026-09-17T20:00:00Z"}


def survey_subset(doc: dict[str, Any], source: str, every: int = 2) -> dict[str, Any]:
    """A fresh survey of the same road: every n-th record, attributed to one new installation."""
    out = copy.deepcopy(doc)
    out["version"] = 4
    edges = []
    for i, e in enumerate(doc["edges"]):
        if i % every:
            continue
        kept = copy.deepcopy(e)
        kept["votes"] = {kept["kind"]: {source: [1, 1]}}
        kept["run"] = 1
        edges.append(kept)
    out["edges"] = edges
    out["meta"]["source_runs"] = {source: 1}
    out["meta"]["runs"] = 1
    return out


@unittest.skipUnless(HAVE_COMPILER, "needs the datalogger's compiler (app.processing.track_compile)")
class EndToEndTests(unittest.TestCase):
    """A temporary copy of this repository with a bare origin, one survey in it."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="sync-job-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        for name in ("catalog", "vendor"):
            shutil.copytree(ROOT / name, self.repo / name)
        (self.repo / "tools").mkdir()
        for script in ROOT.glob("tools/*.py"):
            shutil.copy(script, self.repo / "tools" / script.name)
        (self.repo / "tracks").mkdir()
        shutil.copy(SURVEY, self.repo / "tracks" / SURVEY.name)
        for derived in ("build_index.py", "build_signatures.py"):
            subprocess.run([sys.executable, str(self.repo / "tools" / derived)], cwd=self.repo,
                           check=True, capture_output=True)
        git = lambda *a: subprocess.run(["git", *a], cwd=self.repo, check=True, capture_output=True, text=True)  # noqa: E731
        git("init", "-q", "-b", "main")
        git("config", "user.email", "test@example.invalid")
        git("config", "user.name", "test")
        git("add", "-A")
        git("commit", "-q", "-m", "seed")
        self.origin = self.tmp / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(self.origin)], check=True)
        git("remote", "add", "origin", str(self.origin))
        git("push", "-q", "origin", "main")
        self.existing = load_survey(self.repo / "tracks" / SURVEY.name)
        self.log = io.StringIO()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def context(self, service: FakeService, forge: FakeForge | None = None, **overrides: Any) -> Context:
        repo = Repository(self.repo)
        fields: dict[str, Any] = dict(
            service=service, repo=repo, git=Git(self.repo), forge=forge or FakeForge(),
            policy=service.policy(), accounts=service.sources(),
            configs={c["official_id"]: c for c in repo.catalog_configurations()},
            signatures=repo.signatures(), log=lambda line: self.log.write(line + "\n"))
        fields.update(overrides)
        return Context(**fields)

    def origin_has(self, branch: str, path: str) -> str:
        return subprocess.run(["git", "show", f"{branch}:{path}"], cwd=self.origin,
                              capture_output=True, text=True).stdout

    def test_a_new_survey_of_a_published_circuit_opens_a_pull_request(self) -> None:
        upload = survey_subset(self.existing, "feedbeef")
        service = FakeService([upload_row("upl_1", DEEP_FOREST, "feedbeef", BOB)], {"upl_1": upload})
        forge = FakeForge()
        ok, outcomes = run(self.context(service, forge))

        self.assertTrue(ok, self.log.getvalue())
        outcome = outcomes[0]
        self.assertEqual(outcome.action, "pull_request", self.log.getvalue())
        self.assertTrue(outcome.gate["pass"], outcome.gate)
        self.assertEqual(outcome.gate["mode"], "update")
        branch, title, body, draft = forge.upserts[0]
        self.assertEqual(branch, "sync/deep-forest-raceway")
        self.assertFalse(draft)
        self.assertIn("| Coverage held | pass |", body)
        self.assertIn("`upl_1`", body)
        # The branch on origin carries the merged bundle, canonical, with the new installation's votes.
        pushed = self.origin_has(branch, "tracks/deep-forest-raceway.json")
        self.assertIn('"feedbeef"', pushed)
        # The derived files follow the bundle on the same branch: one more installation.
        index = json.loads(self.origin_has(branch, "index.json"))
        row = next(c for c in index["configurations"] if c["official_id"] == DEEP_FOREST)
        self.assertEqual(row["bundle"]["sources"], len(self.existing["meta"]["source_runs"]) + 1)
        # Auto-merge is off: the pull request waits, the upload stays pending, and nothing is published.
        self.assertEqual(service.merge_requests[0]["status"], "awaiting_review")
        self.assertEqual(service.statuses, [])
        self.assertEqual(service.published, [])
        self.assertEqual(service.issues, [])
        self.assertEqual(service.runs[-1]["prs_opened"], 1)
        self.assertEqual(service.runs[-1]["awaiting_review"], 1)
        # Whoever reviews it is sent what it would publish, under the pull request's address.
        sent, pr_url = service.candidates[DEEP_FOREST]
        self.assertTrue(pr_url.startswith("https://github.com/"))
        self.assertEqual(sent["format"], "gt7-datalogger-track-compiled")
        self.assertTrue(sent["borders"]["L"])
        self.assertEqual(len(sent["finish_crossings"]), len(self.existing["finish_crossings"]))
        self.assertEqual(service.compiled, {})

    def test_a_service_that_will_not_take_the_geometry_does_not_fail_the_run(self) -> None:
        upload = survey_subset(self.existing, "feedbeef")
        service = FakeService([upload_row("upl_1", DEEP_FOREST, "feedbeef", BOB)], {"upl_1": upload})
        service.refuses_candidates = True
        ok, outcomes = run(self.context(service, FakeForge()))

        self.assertTrue(ok, self.log.getvalue())
        self.assertEqual(outcomes[0].action, "pull_request")
        self.assertEqual(service.merge_requests[0]["status"], "awaiting_review")
        self.assertIn("did not take the pull request's geometry", self.log.getvalue())

    def test_with_auto_merge_on_the_gate_merges_reports_and_publishes(self) -> None:
        upload = survey_subset(self.existing, "feedbeef")
        service = FakeService([upload_row("upl_1", DEEP_FOREST, "feedbeef", BOB)], {"upl_1": upload})
        service._policy["gate"]["auto_merge"] = True
        forge = FakeForge(merges=True)
        ok, outcomes = run(self.context(service, forge))

        self.assertTrue(ok, self.log.getvalue())
        self.assertEqual(outcomes[0].action, "merged")
        self.assertEqual(forge.merged, ["sync/deep-forest-raceway"])
        self.assertEqual(forge.workflows, ["pack.yml", "pages.yml"])
        self.assertEqual(service.merge_requests[0]["status"], "auto_merged")
        self.assertEqual([s[:2] for s in service.statuses], [("upl_1", "merged")])
        self.assertTrue(service.statuses[0][3].startswith("https://github.com/"))
        self.assertIn(DEEP_FOREST, service.compiled)
        self.assertEqual(service.compiled[DEEP_FOREST]["format"], "gt7-datalogger-track-compiled")
        # Nothing is waiting, so there is no candidate for anybody to look at.
        self.assertEqual(service.candidates, {})
        official_id, facts = service.published[0]
        self.assertEqual(official_id, DEEP_FOREST)
        self.assertEqual(facts["latest_r2_key"], f"published/{DEEP_FOREST}.json")
        self.assertEqual(facts["track_name"], "Deep Forest Raceway")
        self.assertEqual(facts["contributors"], 3)  # two unbound sources in the survey, plus Bob
        self.assertEqual(service.runs[-1]["auto_merged"], 1)

    def test_the_smoothing_switch_reaches_the_geometry_the_service_is_sent(self) -> None:
        if not sync_job.compiler_takes_smooth():
            self.skipTest("the installed compiler is from before it could smooth")
        stored: dict[bool, dict[str, Any]] = {}
        for wanted in (True, False):
            self.setUp()
            upload = survey_subset(self.existing, "feedbeef")
            service = FakeService([upload_row("upl_1", DEEP_FOREST, "feedbeef", BOB)], {"upl_1": upload})
            service._policy["gate"]["auto_merge"] = True
            service._policy["compile"] = {"smooth_borders": wanted}
            ok, outcomes = run(self.context(service, FakeForge(merges=True)))
            self.assertTrue(ok, self.log.getvalue())
            # Whichever way it is set, the gate compares a before and an after
            # compiled the same way, so coverage holds either way.
            self.assertEqual(outcomes[0].action, "merged", self.log.getvalue())
            stored[wanted] = service.compiled[DEEP_FOREST]
            self.tearDown()
        self.assertIsNone(stored[False]["smoothing"])
        self.assertEqual(stored[True]["smoothing"]["cap_m"], 0.75)
        self.assertNotEqual(stored[True]["borders"], stored[False]["borders"])

    def test_an_upload_already_on_main_is_reported_merged_and_published(self) -> None:
        already = copy.deepcopy(self.existing)
        already["version"] = 4
        service = FakeService([upload_row("upl_1", DEEP_FOREST, "20597c92fb01", ALICE)], {"upl_1": already})
        forge = FakeForge()
        forge.already_merged["sync/deep-forest-raceway"] = "https://github.com/example/track-data/pull/7"
        ok, outcomes = run(self.context(service, forge))

        self.assertTrue(ok, self.log.getvalue())
        self.assertEqual(outcomes[0].action, "merged")
        self.assertEqual(service.statuses, [("upl_1", "merged", "already published in the track data",
                                             "https://github.com/example/track-data/pull/7")])
        self.assertEqual(forge.upserts, [])
        self.assertEqual(len(service.published), 1)
        self.assertEqual(service.published[0][1]["pr_url"], "https://github.com/example/track-data/pull/7")

    def test_a_survey_under_the_wrong_layout_is_held_with_both_lines(self) -> None:
        upload = survey_subset(self.existing, "feedbeef")
        upload["meta"]["official"]["official_id"] = DEEP_FOREST_REVERSE
        upload["meta"]["official"]["official_name"] = "Deep Forest Raceway (Reverse)"
        service = FakeService([upload_row("upl_1", DEEP_FOREST_REVERSE, "feedbeef", BOB)], {"upl_1": upload})
        forge = FakeForge()
        ok, outcomes = run(self.context(service, forge))

        self.assertTrue(ok, self.log.getvalue())
        self.assertEqual(outcomes[0].action, "held")
        self.assertEqual(forge.upserts, [])
        self.assertEqual([s[:2] for s in service.statuses], [("upl_1", "held")])
        issue = service.issues[0]
        self.assertEqual(issue["type"], "layout_mismatch")
        self.assertEqual(issue["detail"]["contributor_official_id"], DEEP_FOREST_REVERSE)
        self.assertEqual(issue["detail"]["signature_official_id"], DEEP_FOREST)
        self.assertGreater(len(issue["detail"]["contributor_line"]), 10)
        self.assertGreater(len(issue["detail"]["signature_line"]), 10)
        self.assertEqual(issue["upload_id"], "upl_1")

    def test_once_a_person_accepted_the_layout_the_survey_goes_through(self) -> None:
        upload = survey_subset(self.existing, "feedbeef")
        upload["meta"]["official"]["official_id"] = DEEP_FOREST_REVERSE
        service = FakeService([upload_row("upl_1", DEEP_FOREST_REVERSE, "feedbeef", BOB)], {"upl_1": upload})
        service.layout.append({"issue_id": "iss_1", "official_id": DEEP_FOREST_REVERSE, "upload_id": "upl_1",
                               "decided_at": "2026-09-18T00:00:00Z", "decided_by": "usr_admin"})
        forge = FakeForge()
        ok, outcomes = run(self.context(service, forge))

        self.assertTrue(ok, self.log.getvalue())
        self.assertEqual(outcomes[0].action, "pull_request", self.log.getvalue())
        layout = next(c for c in outcomes[0].gate["criteria"] if c["id"] == "layout_agreement")
        self.assertTrue(layout["pass"])
        self.assertIn("accepted by the administrator", layout["value"])
        # A first publication of the reverse layout: the perimeter rule applies.
        self.assertEqual(outcomes[0].gate["mode"], "first_publication")

    def test_a_document_the_repository_refuses_is_rejected_with_its_words(self) -> None:
        bad = survey_subset(self.existing, "feedbeef")
        bad["edges"][0]["hx"] = 5.0
        missing = upload_row("upl_2", DEEP_FOREST, "feedbeef", BOB)
        service = FakeService([upload_row("upl_1", DEEP_FOREST, "feedbeef", BOB), missing], {"upl_1": bad})
        ok, outcomes = run(self.context(service, FakeForge()))

        self.assertTrue(ok, self.log.getvalue())
        self.assertEqual(outcomes[0].action, "rejected")
        statuses = {s[0]: s for s in service.statuses}
        self.assertEqual(statuses["upl_1"][1], "rejected")
        self.assertIn("unit vector", statuses["upl_1"][2])
        self.assertEqual(statuses["upl_2"][1], "rejected")
        self.assertIn("gone", statuses["upl_2"][2])

    def test_publishing_what_is_already_here_draws_the_existing_surveys(self) -> None:
        service = FakeService([], {})
        ctx = self.context(service, git=None, forge=None)
        self.assertEqual(sync_job.publish_existing(ctx), 1)
        self.assertEqual(list(service.compiled), [DEEP_FOREST])
        self.assertTrue(service.compiled[DEEP_FOREST]["borders"]["L"])
        official_id, facts = service.published[0]
        self.assertEqual(official_id, DEEP_FOREST)
        self.assertEqual(facts["latest_r2_key"], f"published/{DEEP_FOREST}.json")
        self.assertGreater(facts["coverage"]["left"], 90)
        self.assertEqual(facts["pr_url"], "")
        self.assertEqual(service.statuses, [])

        looked = FakeService([], {})
        self.assertEqual(sync_job.publish_existing(self.context(looked, git=None, forge=None, dry_run=True)), 0)
        self.assertEqual(looked.published, [])

    def test_the_corners_somebody_marked_are_published_with_the_geometry(self) -> None:
        marked = copy.deepcopy(self.existing)
        marked["corners"], marked["sections"] = CORNERS, SECTIONS
        (self.repo / "tracks" / SURVEY.name).write_text(sync_job.canonical.dumps(marked), encoding="utf-8")

        service = FakeService([], {})
        self.assertEqual(sync_job.publish_existing(self.context(service, git=None, forge=None)), 1)
        self.assertEqual(service.compiled[DEEP_FOREST]["corners"], CORNERS)
        self.assertEqual(service.compiled[DEEP_FOREST]["sections"], SECTIONS)

    def test_corners_a_contributor_marked_reach_the_service_when_their_survey_merges(self) -> None:
        upload = survey_subset(self.existing, "feedbeef")
        upload["corners"] = CORNERS
        service = FakeService([upload_row("upl_1", DEEP_FOREST, "feedbeef", BOB)], {"upl_1": upload})
        service._policy["gate"]["auto_merge"] = True
        ok, _ = run(self.context(service, FakeForge(merges=True)))

        self.assertTrue(ok, self.log.getvalue())
        # The repository had none, so the first set anybody marks is the circuit's.
        self.assertEqual(service.compiled[DEEP_FOREST]["corners"], CORNERS)
        self.assertEqual(service.compiled[DEEP_FOREST]["sections"], [])

    def test_a_dry_run_writes_and_reports_nothing(self) -> None:
        upload = survey_subset(self.existing, "feedbeef")
        service = FakeService([upload_row("upl_1", DEEP_FOREST, "feedbeef", BOB)], {"upl_1": upload})
        ctx = self.context(service, git=None, forge=None, dry_run=True)
        ok, outcomes = run(ctx)
        self.assertTrue(ok)
        self.assertEqual(outcomes[0].action, "pull_request")
        self.assertTrue(outcomes[0].gate["pass"])
        self.assertEqual((service.statuses, service.merge_requests, service.runs, service.issues), ([], [], [], []))
        self.assertEqual(subprocess.run(["git", "status", "--porcelain"], cwd=self.repo,
                                        capture_output=True, text=True).stdout, "")


# ── the wire, against a live service ────────────────────────────────────────


# ── pull requests somebody settled on GitHub ───────────────────────────────

BARCELONA = "aa8dc5"
PR_83 = "https://github.com/example/track-data/pull/83"


def waiting_row(row_id: str, pr_url: str, official_id: str = BARCELONA) -> dict[str, Any]:
    return {"id": row_id, "official_id": official_id, "pr_url": pr_url, "branch": f"sync/{official_id}",
            "status": "awaiting_review", "created_at": "2026-09-20T21:44:17Z", "updated_at": "2026-09-20T21:44:17Z"}


class ReconciliationTests(unittest.TestCase):
    """The service is told what became of a pull request by this job and by
    nobody else, so this job has to notice the ones a person settled."""

    def setUp(self) -> None:
        self.log: list[str] = []
        self.service = FakeService([], {})
        self.forge = FakeForge()

    def context(self, **overrides: Any) -> Context:
        fields: dict[str, Any] = dict(service=self.service, repo=None, git=None, forge=self.forge, policy={},
                                      accounts={}, configs={}, signatures={}, log=self.log.append)
        fields.update(overrides)
        return Context(**fields)

    def test_a_pull_request_closed_by_hand_is_settled_as_closed(self) -> None:
        # Production, 2026-09-21: Barcelona's pull request closed on GitHub,
        # its survey already on main another way, nothing pending — and the
        # admin panel still offering a map for it, which could only 404.
        self.service.waiting = [waiting_row("mrq_bcn", PR_83)]
        self.forge.states[PR_83] = "CLOSED"
        settled = sync_job.reconcile_merge_requests(self.context())
        self.assertEqual(self.service.settled, [("mrq_bcn", "closed", "CLOSED")])
        self.assertEqual(settled, [{"id": "mrq_bcn", "official_id": BARCELONA, "pr_url": PR_83, "status": "closed"}])
        self.assertIn("closed on GitHub", self.log[-1])

    def test_one_a_person_merged_is_settled_as_landed(self) -> None:
        self.service.waiting = [waiting_row("mrq_1", PR_83)]
        self.forge.states[PR_83] = "MERGED"
        sync_job.reconcile_merge_requests(self.context())
        self.assertEqual(self.service.settled, [("mrq_1", "auto_merged", "MERGED")])

    def test_one_still_open_is_left_alone(self) -> None:
        self.service.waiting = [waiting_row("mrq_1", PR_83)]
        self.assertEqual(sync_job.reconcile_merge_requests(self.context()), [])
        self.assertEqual(self.service.settled, [])
        self.assertEqual(self.forge.looked_at, [PR_83])

    def test_it_is_never_settled_on_a_guess(self) -> None:
        # GitHub could not be asked — a bad token, an outage, an address that
        # is not a pull request. A row wrongly closed hides a pull request
        # somebody still has to decide about; a stale one only wastes a click.
        self.service.waiting = [waiting_row("mrq_1", PR_83), waiting_row("mrq_2", PR_83 + "0")]
        self.forge.states[PR_83] = ""
        self.forge.states[PR_83 + "0"] = "DRAFT"
        self.assertEqual(sync_job.reconcile_merge_requests(self.context()), [])
        self.assertEqual(self.service.settled, [])
        self.assertEqual(sum("could not tell" in line for line in self.log), 2)

    def test_one_that_cannot_be_settled_does_not_stop_the_rest(self) -> None:
        other = "https://github.com/example/track-data/pull/84"
        self.service.waiting = [waiting_row("mrq_bad", PR_83), waiting_row("mrq_good", other, "0457d4")]
        self.forge.states.update({PR_83: "CLOSED", other: "CLOSED"})
        self.service.refuses_to_settle = {"mrq_bad"}
        settled = sync_job.reconcile_merge_requests(self.context())
        self.assertEqual([row["id"] for row in settled], ["mrq_good"])
        self.assertTrue(any("could not be settled" in line for line in self.log))

    def test_a_run_for_one_circuit_asks_about_that_circuit(self) -> None:
        self.service.waiting = [waiting_row("mrq_bcn", PR_83), waiting_row("mrq_df", PR_83 + "1", DEEP_FOREST)]
        self.forge.states.update({PR_83: "CLOSED", PR_83 + "1": "CLOSED"})
        sync_job.reconcile_merge_requests(self.context(), DEEP_FOREST)
        self.assertEqual(self.service.asked_about, [DEEP_FOREST])
        self.assertEqual([row[0] for row in self.service.settled], ["mrq_df"])

    def test_a_dry_run_and_a_run_without_github_settle_nothing(self) -> None:
        self.service.waiting = [waiting_row("mrq_bcn", PR_83)]
        self.forge.states[PR_83] = "CLOSED"
        for overrides in ({"dry_run": True}, {"report": False}, {"forge": None}):
            self.assertEqual(sync_job.reconcile_merge_requests(self.context(**overrides)), [])
        self.assertEqual(self.service.settled, [])
        self.assertEqual(self.service.asked_about, [])

    def test_a_service_from_before_it_could_be_asked_has_nothing_waiting(self) -> None:
        class Older(sync_job.Service):
            def _request(self, method: str, path: str, *args: Any, **kwargs: Any) -> Any:
                raise ServiceError(404, "not_found", "no such route")

        self.assertEqual(Older("https://example.invalid", "key").waiting_merge_requests(), [])

        class Broken(sync_job.Service):
            def _request(self, method: str, path: str, *args: Any, **kwargs: Any) -> Any:
                raise ServiceError(500, "internal", "a bad minute")

        with self.assertRaises(ServiceError):
            Broken("https://example.invalid", "key").waiting_merge_requests()

    def test_a_night_with_nothing_to_merge_still_settles_what_is_stale(self) -> None:
        # The case the old job could never reach: no uploads pending for the
        # circuit, so it was never visited, so its row was never looked at.
        self.service.waiting = [waiting_row("mrq_bcn", PR_83)]
        self.forge.states[PR_83] = "CLOSED"
        ok, outcomes = run(self.context())
        self.assertTrue(ok)
        self.assertEqual(outcomes, [])
        self.assertEqual(self.service.settled, [("mrq_bcn", "closed", "CLOSED")])
        self.assertEqual(self.service.runs[-1]["detail"]["settled"][0]["pr_url"], PR_83)
        self.assertIn("merge requests settled 1", self.log[-1])

    def test_housekeeping_that_fails_outright_does_not_fail_the_night(self) -> None:
        def broken(official_id: str = "") -> list[dict[str, Any]]:
            raise ServiceError(500, "internal", "a bad minute")

        self.service.waiting_merge_requests = broken  # type: ignore[method-assign]
        ok, _ = run(self.context())
        self.assertTrue(ok)
        self.assertTrue(any("could not be reconciled" in line for line in self.log))


# ── what starts the job ────────────────────────────────────────────────────


class WorkflowTests(unittest.TestCase):
    """sync.yml is configuration, and two lines of it are load-bearing."""

    def setUp(self) -> None:
        self.text = (ROOT / ".github" / "workflows" / "sync.yml").read_text(encoding="utf-8")

    def test_it_runs_when_a_person_closes_one_of_its_pull_requests(self) -> None:
        # Nothing else tells the service that somebody pressed Merge, and the
        # other open pull requests have just gone stale in index.json.
        self.assertRegex(self.text, r"pull_request:\n\s+types: \[closed\]")

    def test_only_for_its_own_branches_and_never_for_a_fork(self) -> None:
        guard = " ".join(self.text.split("    if: >-")[1].split("runs-on:")[0].split())
        self.assertIn("startsWith(github.head_ref, 'sync/')", guard)
        self.assertIn("startsWith(github.head_ref, 'edit/')", guard)
        self.assertIn("github.event.pull_request.head.repo.full_name == github.repository", guard)
        # A branch name is somebody else's text. It is compared, never run:
        # nothing in a `run:` step may interpolate it.
        for block in self.text.split("run: |")[1:]:
            self.assertNotIn("head_ref", block.split("\n      - ")[0])

    def test_it_works_from_main_whatever_started_it(self) -> None:
        # A conflicted pull request has no test merge to check out, and that
        # is the very one a run on close is there to mend.
        self.assertIn("github.event_name == 'pull_request' && github.event.repository.default_branch", self.text)


# ── an administrator's edit ────────────────────────────────────────────────

DRAWN = "drawn-0a1b2c3d"


def drawn_bundle(existing: dict[str, Any], points: list[tuple[float, float]], side: str = "R",
                 source: str = DRAWN) -> dict[str, Any]:
    """What the editor sends for a border somebody drew: a bundle of its own,
    every record filed under a drawn source."""
    return {
        "format": existing["format"], "version": existing["version"],
        "meta": {"track": existing["meta"]["track"], "runs": 1, "source_runs": {source: 1},
                 "updated_at": "2026-09-21T00:00:00+00:00", "official": existing["meta"]["official"]},
        "edges": [{"x": x, "z": z, "y": None, "hx": 1.0, "hz": 0.0, "side": side, "kind": "edge",
                   "votes": {"edge": {source: [1, 1]}}, "run": 1, "tw": None} for x, z in points],
        "finish_crossings": [], "corners": [], "sections": [],
    }


def edit_document(official_id: str, track: str, *, note: str = "the pit wall is not the track's edge",
                  areas: list[dict[str, Any]] | None = None, smooth: bool | None = None,
                  drawn: dict[str, Any] | None = None, base: str = "") -> dict[str, Any]:
    corrected = corrections.empty(official_id, track)
    corrected["exclude"] = areas or []
    corrected["compile"]["smooth_borders"] = smooth
    return {"format": sync_job.EDIT_FORMAT, "version": sync_job.EDIT_VERSION, "official_id": official_id,
            "note": note, "drawn": drawn, "corrections": corrected, "base": {"corrections_sha256": base}}


def square(x: float, z: float, half: float = 20.0, **overrides: Any) -> dict[str, Any]:
    area = {"id": "a1", "sides": ["R"], "y": None, "only_drawn": False,
            "polygon": [[x - half, z - half], [x + half, z - half], [x + half, z + half], [x - half, z + half]],
            "reason": "the pit wall, recorded as the right-hand border", "by": "Alice",
            "at": "2026-09-21T00:00:00Z"}
    area.update(overrides)
    return area


class EditValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.existing = load_survey()

    def test_an_edit_may_only_add_what_was_drawn(self) -> None:
        # The editor draws; it does not survey. Votes under an installation's
        # id would be somebody's laps, forged.
        forged = drawn_bundle(self.existing, [(9000.0 + i, 9000.0) for i in range(6)], source="20597c92fb01")
        with self.assertRaisesRegex(ValueError, "may only add records under a drawn-"):
            sync_job.validate_edit(edit_document(DEEP_FOREST, "Deep Forest Raceway", drawn=forged), DEEP_FOREST)

    def test_what_else_is_refused(self) -> None:
        good = edit_document(DEEP_FOREST, "Deep Forest Raceway")
        self.assertEqual(sync_job.validate_edit(good, DEEP_FOREST)["note"], good["note"])
        for message, bad in {
            "needs a note": {**good, "note": "  "},
            "filed under": {**good, "official_id": "f18da2"},
            "format must be": {**good, "format": "nope"},
            "started from": {**good, "base": {}},
            "corrections name layout": {**good, "corrections": corrections.empty("f18da2", "Tsukuba Circuit")},
        }.items():
            with self.assertRaisesRegex(ValueError, message):
                sync_job.validate_edit(bad, DEEP_FOREST)
        crossings = drawn_bundle(self.existing, [(9000.0 + i, 9000.0) for i in range(6)])
        crossings["finish_crossings"] = self.existing["finish_crossings"][:1]
        with self.assertRaisesRegex(ValueError, "borders only"):
            sync_job.validate_edit({**good, "drawn": crossings}, DEEP_FOREST)

    def test_drawing_the_same_border_in_twice_adds_it_once(self) -> None:
        # "Is this edit already in main?" is answered by merging it again and
        # seeing nothing change, so merging must be exactly that harmless.
        drawn = drawn_bundle(self.existing, [(9000.0 + i, 9000.0) for i in range(6)])
        once = sync_job.merge_into(self.existing, drawn)
        twice = sync_job.merge_into(once, drawn)
        self.assertEqual(sync_job.canonical.dumps(once), sync_job.canonical.dumps(twice))
        self.assertEqual(len(once["edges"]), len(self.existing["edges"]) + 6)


@unittest.skipUnless(HAVE_COMPILER, "needs the datalogger's compiler (app.processing.track_compile)")
class EditEndToEndTests(unittest.TestCase):
    """The same temporary repository, edited instead of surveyed."""

    # The fixtures and not the class: inheriting would run every survey test
    # a second time under this name.
    setUp = EndToEndTests.setUp
    tearDown = EndToEndTests.tearDown
    context = EndToEndTests.context
    origin_has = EndToEndTests.origin_has

    def right_border_spot(self) -> tuple[float, float]:
        edge = next(e for e in self.existing["edges"] if e["side"] == "R")
        return edge["x"], edge["z"]

    def service_with(self, doc: dict[str, Any], **row: Any) -> FakeService:
        service = FakeService([], {})
        service.edits = [{"id": "edt_1", "official_id": DEEP_FOREST, "status": "pending",
                          "created_by": "Alice", "pr_url": "", **row}]
        service.edit_docs = {"edt_1": doc}
        return service

    def test_an_edit_becomes_a_pull_request_a_person_has_to_merge(self) -> None:
        x, z = self.right_border_spot()
        hidden = len(corrections.excluded(self.existing["edges"], {"exclude": [square(x, z)]}))
        self.assertGreater(hidden, 5)
        drawn = drawn_bundle(self.existing, [(9000.0 + i, 9000.0) for i in range(8)])
        service = self.service_with(edit_document(DEEP_FOREST, "Deep Forest Raceway",
                                                  areas=[square(x, z)], drawn=drawn))
        # Auto-merge on, a passing gate or not: an edit is one person's opinion
        # about the evidence, and a machine does not merge those.
        service._policy["gate"]["auto_merge"] = True
        forge = FakeForge(merges=True)
        ok, _ = run(self.context(service, forge))

        self.assertTrue(ok, self.log.getvalue())
        self.assertEqual(forge.merged, [])
        branch, title, body, draft = forge.upserts[0]
        self.assertEqual(branch, "edit/deep-forest-raceway")
        self.assertIn("(editor)", title)
        self.assertFalse(draft, self.log.getvalue())
        self.assertIn("Nothing is deleted", body)
        self.assertIn("the pit wall, recorded as the right-hand border", body)
        self.assertIn(f"keep {hidden} surveyed records out", body)
        self.assertIn("border drawn in, under a `drawn-` source: 8 m", body)

        # The branch carries the corrections beside the bundle, and the bundle
        # kept every record it had: the drawn ones were added, none removed.
        pushed = json.loads(self.origin_has(branch, "corrections/deep-forest-raceway.json"))
        self.assertEqual(pushed["exclude"][0]["id"], "a1")
        bundle = json.loads(self.origin_has(branch, "tracks/deep-forest-raceway.json"))
        self.assertEqual(len(bundle["edges"]), len(self.existing["edges"]) + 8)
        self.assertIn(DRAWN, bundle["meta"]["source_runs"])

        # The person deciding gets to look at it, and is told where it stands.
        self.assertEqual(service.merge_requests[0]["status"], "awaiting_review")
        self.assertEqual(service.merge_requests[0]["branch"], branch)
        candidate, pr_url = service.candidates[DEEP_FOREST]
        self.assertEqual(service.edit_reports, [("edt_1", "pr_open", "", pr_url)])
        self.assertEqual(service.published, [])
        # And what they look at has the excluded stretch taken out of it.
        untouched = sync_job.compile_geometry(self.existing, sync_job.smooth_borders(service.policy()))
        self.assertLess(candidate["coverage"]["R"]["surveyed_m"], untouched["coverage"]["R"]["surveyed_m"])
        self.assertEqual(service.runs[-1]["detail"]["edits"][0]["action"], "pull_request")

    def land(self, branch: str) -> None:
        """What a person pressing Merge on GitHub does."""
        git = lambda *a: subprocess.run(["git", *a], cwd=self.repo, check=True, capture_output=True, text=True)  # noqa: E731
        git("fetch", "-q", "origin", branch)
        git("checkout", "-q", "main")
        git("merge", "-q", "--no-edit", f"origin/{branch}")
        git("push", "-q", "origin", "main")

    def test_a_merged_edit_is_published_with_its_corrections_and_reported_applied(self) -> None:
        x, z = self.right_border_spot()
        doc = edit_document(DEEP_FOREST, "Deep Forest Raceway", areas=[square(x, z)])
        service = self.service_with(doc)
        forge = FakeForge()
        run(self.context(service, forge))
        pr_url = forge.open["edit/deep-forest-raceway"]
        self.land("edit/deep-forest-raceway")
        forge.open.clear()
        forge.already_merged["edit/deep-forest-raceway"] = pr_url

        ok, _ = run(self.context(service, forge))
        self.assertTrue(ok, self.log.getvalue())
        self.assertEqual(service.edit_reports[-1][:2], ("edt_1", "applied"))
        self.assertEqual(len(forge.upserts), 1)  # no second pull request
        official_id, facts = service.published[-1]
        self.assertEqual((official_id, facts["pr_url"]), (DEEP_FOREST, pr_url))
        # What is published is the evidence with the correction applied …
        published = service.compiled[DEEP_FOREST]
        untouched = sync_job.compile_geometry(self.existing, sync_job.smooth_borders(service.policy()))
        self.assertLess(published["coverage"]["R"]["surveyed_m"], untouched["coverage"]["R"]["surveyed_m"])
        # … and a finished edit is not picked up again.
        self.assertEqual(service.open_edits(), [])

    def test_a_correction_outlives_the_next_upload_of_the_very_records_it_hides(self) -> None:
        # The reason corrections exist. A logger uploads its whole bundle on
        # every autosave; were the records deleted, this upload would restore
        # them. They were never deleted, and the area still keeps them out.
        x, z = self.right_border_spot()
        service = self.service_with(edit_document(DEEP_FOREST, "Deep Forest Raceway", areas=[square(x, z)]))
        forge = FakeForge()
        run(self.context(service, forge))
        self.land("edit/deep-forest-raceway")
        forge.open.clear()
        run(self.context(service, forge))
        corrected = service.compiled[DEEP_FOREST]["coverage"]["R"]["surveyed_m"]

        again = FakeService([upload_row("upl_9", DEEP_FOREST, "feedbeef", BOB)],
                            {"upl_9": survey_subset(self.existing, "feedbeef", every=1)})
        again._policy["gate"]["auto_merge"] = True
        ok, outcomes = run(self.context(again, FakeForge(merges=True)))
        self.assertTrue(ok, self.log.getvalue())
        self.assertEqual(outcomes[0].action, "merged", self.log.getvalue())
        self.assertAlmostEqual(again.compiled[DEEP_FOREST]["coverage"]["R"]["surveyed_m"], corrected, delta=1.0)

    def test_a_pull_request_closed_unmerged_closes_the_edit(self) -> None:
        x, z = self.right_border_spot()
        service = self.service_with(edit_document(DEEP_FOREST, "Deep Forest Raceway", areas=[square(x, z)]))
        forge = FakeForge()
        run(self.context(service, forge))
        forge.open.clear()  # somebody closed it

        run(self.context(service, forge))
        self.assertEqual(service.edit_reports[-1][:2], ("edt_1", "closed"))
        self.assertEqual(len(forge.upserts), 1)  # and it is not reopened every night

    def branch_head(self, branch: str) -> str:
        return subprocess.run(["git", "rev-parse", f"refs/heads/{branch}"], cwd=self.origin,
                              capture_output=True, text=True, check=True).stdout.strip()

    def test_a_waiting_pull_request_is_left_alone_while_main_stands_still(self) -> None:
        x, z = self.right_border_spot()
        service = self.service_with(edit_document(DEEP_FOREST, "Deep Forest Raceway", areas=[square(x, z)]))
        forge = FakeForge()
        run(self.context(service, forge))
        pushed = self.branch_head("edit/deep-forest-raceway")
        run(self.context(service, forge))
        # A quiet night leaves a pull request quiet: no push, no edit to it,
        # nothing said to the service that it has not been told.
        self.assertEqual(self.branch_head("edit/deep-forest-raceway"), pushed)
        self.assertEqual(len(forge.upserts), 1)
        self.assertEqual([r[1] for r in service.edit_reports], ["pr_open"])
        self.assertIn("up to date with main", self.log.getvalue())

    def test_a_waiting_pull_request_is_rebuilt_when_something_else_lands(self) -> None:
        # Production, 2026-09-21. Three edits open at once; two were merged, and
        # the third then conflicted in index.json and stayed that way, because
        # an open edit was left alone. The line was the grand total at the top
        # — `"points": 128012` — which every pull request that adds a record
        # rewrites, so any two of them collide the moment one lands. A survey's
        # pull request is rebuilt from main every night. So is an edit's, now.
        x, z = self.right_border_spot()
        drawn = drawn_bundle(self.existing, [(9000.0 + i, 9000.0) for i in range(8)])
        service = self.service_with(edit_document(DEEP_FOREST, "Deep Forest Raceway",
                                                  areas=[square(x, z)], drawn=drawn))
        forge = FakeForge()
        run(self.context(service, forge))
        branch = "edit/deep-forest-raceway"
        before = self.branch_head(branch)

        # Somebody else's pull request lands, and it added records too: the
        # same total, on the same line, to a different number.
        git = lambda *a: subprocess.run(["git", *a], cwd=self.repo, check=True, capture_output=True, text=True)  # noqa: E731
        git("checkout", "-q", "main")
        path = self.repo / "index.json"
        text = path.read_text(encoding="utf-8")
        total = json.loads(text)["counts"]["points"]
        # The grand total is the first of them: this repository has one
        # circuit, so that circuit's own count is the same number further down.
        self.assertTrue(text.index(f'"points": {total},') < text.index('"unmatched_bundles"'))
        path.write_text(text.replace(f'"points": {total},', f'"points": {total + 153},', 1), encoding="utf-8")
        git("commit", "-q", "-am", "another circuit's edit lands")
        git("push", "-q", "origin", "main")
        git("fetch", "-q", "origin")
        collision = subprocess.run(["git", "merge-tree", "--write-tree", "--name-only", "origin/main", f"origin/{branch}"],
                                   cwd=self.repo, capture_output=True, text=True)
        self.assertNotEqual(collision.returncode, 0, "the fixture should reproduce the conflict")
        self.assertIn("index.json", collision.stdout)

        ok, _ = run(self.context(service, forge))
        self.assertTrue(ok, self.log.getvalue())
        self.assertIn("rebuilt on today's main", self.log.getvalue())
        self.assertNotEqual(self.branch_head(branch), before)
        # It is the same pull request, edited — not a second one — and it merges.
        self.assertEqual([u[0] for u in forge.upserts], [branch, branch])
        self.assertEqual(len(set(forge.open.values())), 1)
        git("fetch", "-q", "origin")
        merged = subprocess.run(["git", "merge-tree", "--write-tree", "origin/main", f"origin/{branch}"],
                                cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(merged.returncode, 0, merged.stdout)
        self.assertEqual(subprocess.run(["git", "merge-base", "--is-ancestor", "origin/main", f"origin/{branch}"],
                                        cwd=self.repo).returncode, 0)
        # Still the edit it was, and still somebody's to merge.
        pushed = json.loads(self.origin_has(branch, "corrections/deep-forest-raceway.json"))
        self.assertEqual(pushed["exclude"][0]["id"], "a1")
        self.assertEqual(service.edit_reports[-1][:2], ("edt_1", "pr_open"))
        self.assertEqual(forge.merged, [])

    def test_an_edit_started_from_other_corrections_is_stale(self) -> None:
        x, z = self.right_border_spot()
        doc = edit_document(DEEP_FOREST, "Deep Forest Raceway", areas=[square(x, z)], base="0" * 64)
        service = self.service_with(doc)
        forge = FakeForge()
        run(self.context(service, forge))
        self.assertEqual(service.edit_reports[-1][:2], ("edt_1", "stale"))
        self.assertEqual(forge.upserts, [])

    def test_a_forged_edit_is_refused_with_the_reason(self) -> None:
        forged = drawn_bundle(self.existing, [(9000.0 + i, 9000.0) for i in range(6)], source="20597c92fb01")
        service = self.service_with(edit_document(DEEP_FOREST, "Deep Forest Raceway", drawn=forged))
        forge = FakeForge()
        run(self.context(service, forge))
        edit_id, status, reason, _ = service.edit_reports[-1]
        self.assertEqual((edit_id, status), ("edt_1", "failed"))
        self.assertIn("may only add records under a drawn-", reason)
        self.assertEqual(forge.upserts, [])

    def test_a_circuits_own_answer_about_smoothing_beats_the_switch(self) -> None:
        if not sync_job.compiler_takes_smooth():
            self.skipTest("the installed compiler is from before it could smooth")
        service = self.service_with(edit_document(DEEP_FOREST, "Deep Forest Raceway", smooth=False,
                                                  note="this circuit's kerbs are better as recorded"))
        service._policy["compile"] = {"smooth_borders": True}
        run(self.context(service, FakeForge()))
        candidate, _ = service.candidates[DEEP_FOREST]
        self.assertIsNone(candidate["smoothing"])
        self.assertIs(sync_job.smoothing_for({"compile": {"smooth_borders": True}}, None), True)
        self.assertIs(sync_job.smoothing_for({"compile": {"smooth_borders": False}},
                                             {"compile": {"smooth_borders": True}}), True)


@unittest.skipUnless(os.environ.get("GT7_SYNC_TEST_URL") and os.environ.get("GT7_SYNC_SERVICE_KEY"),
                     "set GT7_SYNC_TEST_URL and GT7_SYNC_SERVICE_KEY to check the wire against a live service")
class ContractTests(unittest.TestCase):
    """Every request the job makes, made for real, against a service you point it at.

    Meant for a local `wrangler dev` of the sync service. It writes rows there
    — a job run, a merge request, a publication of a circuit called
    `sync-test` — so do not point it at the hosted one.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.service = sync_job.Service(os.environ["GT7_SYNC_TEST_URL"], os.environ["GT7_SYNC_SERVICE_KEY"])

    def test_the_read_side_answers_in_the_shapes_the_job_reads(self) -> None:
        policy = self.service.policy()
        self.assertIn("manual_quorum", policy["policy"])
        self.assertIn("auto_merge", policy["gate"])
        self.assertIsInstance(self.service.sources(), dict)
        self.assertIsInstance(self.service.pending_uploads(), list)
        self.assertIsInstance(self.service.kind_decisions("sync-test"), list)
        self.assertIsInstance(self.service.layout_decisions("sync-test"), list)

    def test_the_write_side_accepts_what_the_job_sends(self) -> None:
        run_id = self.service.open_run()
        compiled = {"format": "gt7-datalogger-track-compiled", "version": 1,
                    "borders": {"L": [[[0, 0, None], [1, 0, None]]], "R": [[[0, 2, None], [1, 2, None]]]},
                    "finish": [0, 0, 0, 2], "centerline": [[[0, 1, None, 2], [1, 1, None, 2]]], "road": [],
                    "coverage": {"L": {"surveyed_m": 1, "gap_m": 0, "pct": 100, "closed": True},
                                 "R": {"surveyed_m": 1, "gap_m": 0, "pct": 100, "closed": True}, "road_pct": 100}}
        stored = self.service.put_compiled("sync-test", compiled)
        self.assertEqual(stored["r2_key"], "published/sync-test.json")
        waiting = self.service.put_candidate("sync-test", {**compiled, "finish_crossings": [{"x": 0, "z": 1}]},
                                             "https://example.invalid/pull/1")
        self.assertEqual(waiting["r2_key"], "candidates/sync-test.json")
        gate = evaluate_gate(gate_input(), SETTINGS)
        reply = self.service.report_merge_request(official_id="sync-test", pr_url="https://example.invalid/pull/1",
                                                  branch="sync/sync-test", accounts=1, new_metres=2,
                                                  kind_changes=0, gate=gate, status="awaiting_review")
        self.assertIn("merge_request", reply)
        published = self.service.publish("sync-test", {"track_name": "Sync Test", "slug": "sync-test",
                                                       "length_m": 2, "coverage": {"left": 100, "right": 100},
                                                       "closed": True, "contributors": 1, "runs": 1,
                                                       "latest_r2_key": stored["r2_key"],
                                                       "merge_status": "auto_merged"})
        self.assertEqual(published["track"]["official_id"], "sync-test")
        issue = self.service.raise_issue(type="gate_failed", official_id="sync-test",
                                         summary="contract test", detail={"failed": ["finish_crossings"]},
                                         trigger={"failed": ["finish_crossings"]})
        self.assertIn(issue["outcome"], ("raised", "already_open", "suppressed"))
        self.service.close_run(run_id, True, {"tracks_touched": 1, "prs_opened": 1, "auto_merged": 0,
                                              "awaiting_review": 1, "issues_raised": 1}, {"scope": "sync-test"})


if __name__ == "__main__":
    unittest.main(verbosity=1)
