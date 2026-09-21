"""Merge what the sync service collected, and publish it as pull requests.

The sync service (sync.gt7-datalogger.com) accepts survey bundles from
dataloggers and stores them; it never merges anything. This job is the other
half. Nightly, and on demand, it asks the service what is pending, merges each
circuit's uploads into the bundle this repository already holds with the same
rules `add_bundle.py` applies, compiles the geometry with the datalogger's own
compiler, judges the auto-merge gate, and opens one pull request per changed
circuit. Then it tells the service what became of every upload, so a
contributor's portal says `merged`, `held` or `rejected` with a reason they
can read, instead of `pending` for ever.

Why here and not in the service: the merge rules already exist in Python in
this repository, the datalogger runs the same ones, and GitHub is the source
of truth for track data. A Worker cannot run Python, and a second
implementation of the merge would be a second thing to keep honest.

The job is stateless on purpose. Every run starts from `main`, rebuilds the
`sync/<slug>` branch from every upload still pending for that circuit, and
force-pushes it; a pull request already open for the branch is updated rather
than duplicated. An upload is reported `merged` only when `main` already holds
everything it contributes — the merge produces no diff — which is true the run
after its pull request lands, whether the gate merged it or a person did.
Nothing has to remember which upload went into which pull request.

Two questions are held for a person rather than turned into a pull request,
because a pull request would be the wrong answer to them: a survey whose
confirmed layout disagrees with what `signatures.json` identifies (filing it
would put a circuit under the wrong name), and an update that would shrink
the published perimeter. Both raise an issue the admin resolves in the
service's panel, and both come back through the queue once resolved. Every
other gate failure opens the pull request anyway and raises a `gate_failed`
issue pointing at it: the survey may well be fine, and a person merging it is
the gate's own fallback.

Where the corroboration policy bites. A manual kind — wall, runoff, edge — is
one person's judgement, and the policy (spec §5) lets it decide a metre only
once `MANUAL_QUORUM` distinct accounts agree. The bundle format, though,
resolves `kind` from votes by its own rule; both validators insist the stored
`kind` matches, and the datalogger recomputes it on load and never trusts the
file. So the stored bundle keeps the format's own kinds and every vote, as
evidence, and the policy is applied to what is derived from it: the compiled
geometry the service publishes (a lone voter's wall is not drawn as a wall on
the map) and the gate (a pull request whose stored kinds changed without
quorum is not merged by a machine). A metre where two manual kinds both reach
quorum is a `quorum_conflict` for the admin, whose decision comes back through
`GET /v1/kind-decisions` and is applied to the geometry on the next run.

    python tools/sync_job.py                        # every circuit with pending uploads
    python tools/sync_job.py --official-id 0457d4   # one configuration
    python tools/sync_job.py --dry-run              # fetch, merge, judge; write and report nothing
    python tools/sync_job.py --no-git               # write tracks/, open no pull request
    python tools/sync_job.py --publish-existing     # compile and publish every survey already here

Needs the service key in `GT7_SYNC_SERVICE_KEY`; the datalogger installed for
its compiler (`pip install "gt7-datalogger @ git+https://github.com/jbhoorasingh/gt7-datalogger@main#subdirectory=backend"`,
or `GT7_DATALOGGER_BACKEND=/path/to/gt7-datalogger/backend` from a checkout);
and, for pull requests, `git` and `gh` with `GH_TOKEN`. The service address
defaults to the hosted one and `GT7_SYNC_URL` overrides it.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
# A datalogger checkout stands in for an installed one, for runs on a laptop.
if os.environ.get("GT7_DATALOGGER_BACKEND"):
    sys.path.insert(0, os.environ["GT7_DATALOGGER_BACKEND"])
import canonical  # noqa: E402
from add_bundle import merge_into  # noqa: E402
from build_index import configurations, slugify  # noqa: E402
from build_signatures import (  # noqa: E402
    CENTER_TOLERANCE_M,
    EXTENT_TOLERANCE,
    LENGTH_TOLERANCE,
    MIN_PATH_POINTS,
    box,
    heading_agreement,
)
from bundle_format import (  # noqa: E402
    AUTO_KINDS,
    KIND_ORDER,
    MANUAL_KINDS,
    edge_key,
    resolve_kind,
    validate_document,
)

ROOT = HERE.parent
DEFAULT_SERVICE = "https://sync.gt7-datalogger.com"
KEY_ENV = "GT7_SYNC_SERVICE_KEY"
URL_ENV = "GT7_SYNC_URL"
BRANCH_PREFIX = "sync/"
WORKFLOW = ".github/workflows/sync.yml"
USER_AGENT = "gt7-datalogger-track-data sync job (+https://github.com/jbhoorasingh/gt7-datalogger-track-data)"

# A hand-traced source: a contributor, never a quorum on its own.
DRAWN_PREFIX = "drawn-"

# How the compiled centre line is thinned for an issue's detail: enough to
# draw the shape beside the signature's line, not so much that one issue is
# a megabyte of coordinates.
LINE_POINTS = 200

# Text the service shows the contributor. Written for them, not for a log.
REASON_AWAITING = "waiting for a person to review the pull request"


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ── the service, as the job talks to it ────────────────────────────────────


class ServiceError(RuntimeError):
    """The service said no. `status` and `code` are its error contract."""

    def __init__(self, status: int, code: str, reason: str) -> None:
        super().__init__(f"{status} {code}: {reason}")
        self.status = status
        self.code = code
        self.reason = reason


class Service:
    """Every call the job makes, under the job's key and nothing else.

    Standard-library HTTP, like the rest of this repository's tools: the job
    must run on a bare Python in CI and needs no session, no browser and no
    third-party client to talk to an endpoint that answers JSON.
    """

    def __init__(self, base: str, key: str, opener: Callable[..., Any] = urllib.request.urlopen) -> None:
        self.base = base.rstrip("/")
        self.key = key
        self.opener = opener

    def _request(self, method: str, path: str, body: Any = None,
                 params: dict[str, Any] | None = None, raw: bool = False) -> Any:
        query = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        url = self.base + path + (f"?{urllib.parse.urlencode(query)}" if query else "")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", f"Bearer {self.key}")
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", USER_AGENT)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with self.opener(request, timeout=120) as response:
                text = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            try:
                doc = json.loads(detail)
                raise ServiceError(exc.code, str(doc.get("error", "")), str(doc.get("reason", ""))) from None
            except ValueError:
                raise ServiceError(exc.code, "http_error", detail[:200]) from None
        if raw:
            return text
        return json.loads(text) if text else {}

    # -- reading --

    def policy(self) -> dict[str, Any]:
        return self._request("GET", "/v1/policy")

    def pending_uploads(self, official_id: str = "") -> list[dict[str, Any]]:
        """The whole queue, oldest first, however many pages it is."""
        uploads: list[dict[str, Any]] = []
        since = ""
        while True:
            page = self._request("GET", "/v1/tracks/uploads",
                                 params={"limit": 200, "official_id": official_id, "since": since})
            uploads.extend(page.get("uploads", []))
            since = page.get("next_since") or ""
            if not since:
                return uploads

    def fetch_bundle(self, upload: dict[str, Any]) -> dict[str, Any]:
        text = self._request("GET", f"/v1/tracks/uploads/{upload['id']}/bundle", raw=True)
        return json.loads(text)

    def sources(self) -> dict[str, str]:
        """Every installation's account: what corroboration counts by."""
        out: dict[str, str] = {}
        cursor = ""
        while True:
            page = self._request("GET", "/v1/sources", params={"limit": 200, "cursor": cursor})
            for row in page.get("sources", []):
                out[str(row["source_id"])] = str(row["user_id"])
            cursor = page.get("cursor") or ""
            if not cursor:
                return out

    def kind_decisions(self, official_id: str) -> list[dict[str, Any]]:
        page = self._request("GET", "/v1/kind-decisions", params={"official_id": official_id, "limit": 200})
        return list(page.get("decisions", []))

    def layout_decisions(self, official_id: str) -> list[dict[str, Any]]:
        page = self._request("GET", "/v1/layout-decisions", params={"official_id": official_id, "limit": 200})
        return list(page.get("decisions", []))

    # -- reporting --

    def open_run(self) -> str:
        reply = self._request("POST", "/v1/job/runs", body={"started_at": now_iso()})
        return str(reply["run"]["id"])

    def close_run(self, run_id: str, ok: bool, counters: dict[str, int], detail: dict[str, Any]) -> None:
        self._request("POST", "/v1/job/runs",
                      body={"id": run_id, "finished_at": now_iso(), "ok": ok, **counters, "detail": detail})

    def report_status(self, upload_id: str, status: str, reason: str = "", pr_url: str = "") -> None:
        body: dict[str, Any] = {"status": status, "reason": reason[:500]}
        if pr_url:
            body["pr_url"] = pr_url
        self._request("POST", f"/v1/tracks/uploads/{upload_id}/status", body=body)

    def report_merge_request(self, **fields: Any) -> dict[str, Any]:
        return self._request("POST", "/v1/merge-requests", body=fields)

    def raise_issue(self, **fields: Any) -> dict[str, Any]:
        return self._request("POST", "/v1/issues", body=fields)

    def put_compiled(self, official_id: str, compiled: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/v1/tracks/{official_id}/compiled", body=compiled)

    def publish(self, official_id: str, facts: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/v1/tracks/{official_id}/published", body=facts)


# ── the corroboration policy (spec §5) ─────────────────────────────────────


def corroborate(votes: dict[str, dict[str, list[int]]], source_to_account: dict[str, str],
                quorum: int) -> dict[str, Any]:
    """The kind one metre publishes as, given its votes and who owns each source.

    Only the manual kinds that reached quorum, plus the whole inferred tier,
    are allowed into the resolution; the answer is then the format's own
    `resolve_kind` over that filtered set, so a metre the policy does not
    change resolves exactly as it would have. Distinctness is counted per
    account, not per source id, because source ids are free and accounts are
    not; every drawn source together counts as one contributor and never as a
    quorum on its own; a source bound to no account is evidence, not a voice.
    """
    wanted = max(1, int(quorum)) if isinstance(quorum, (int, float)) and math.isfinite(quorum) else 1

    evidence: list[dict[str, Any]] = []
    for kind in MANUAL_KINDS:
        bucket = votes.get(kind)
        if not bucket:
            continue
        sources = sorted(bucket)
        accounts: set[str] = set()
        unmapped: list[str] = []
        drawn = False
        for source in sources:
            if source.startswith(DRAWN_PREFIX):
                drawn = True
                continue
            account = source_to_account.get(source)
            if account is None:
                unmapped.append(source)
            else:
                accounts.add(account)
        contributors = len(accounts) + (1 if drawn else 0)
        evidence.append({
            "kind": kind,
            "sources": sources,
            "accounts": sorted(accounts),
            "drawn": drawn,
            "unmapped": unmapped,
            "contributors": contributors,
            "quorum": len(accounts) >= 1 and contributors >= wanted,
        })

    allowed: dict[str, dict[str, list[int]]] = {}
    corroborated: list[str] = []
    pending: list[str] = []
    for item in evidence:
        if item["quorum"]:
            corroborated.append(item["kind"])
            allowed[item["kind"]] = votes[item["kind"]]
        else:
            pending.append(item["kind"])
    for kind in AUTO_KINDS:
        if votes.get(kind):
            allowed[kind] = votes[kind]

    kind = resolve_kind(allowed)
    return {
        "kind": kind,
        "tier": "manual" if kind in MANUAL_KINDS else "inferred",
        "pending": pending,
        "corroborated": corroborated,
        "evidence": evidence,
    }


def cell_of(edge: dict[str, Any]) -> tuple[int, int, str]:
    return edge_key(edge)


def policy_kinds(doc: dict[str, Any], accounts: dict[str, str], quorum: int,
                 decisions: dict[tuple[int, int, str], str] | None = None) -> dict[str, Any]:
    """Every metre's published kind under the policy, and what the policy noticed.

    Returns `kinds` (cell → kind), `pending` (cells with a manual kind waiting
    for quorum), `conflicts` (cells where two manual kinds both reached it)
    and `decided` (cells an admin's decision settled). A decision wins over
    everything: it is the answer to the conflict the job raised.
    """
    decisions = decisions or {}
    kinds: dict[tuple[int, int, str], str] = {}
    pending: list[tuple[int, int, str]] = []
    conflicts: list[dict[str, Any]] = []
    decided: list[tuple[int, int, str]] = []
    for edge in doc.get("edges", []):
        cell = cell_of(edge)
        verdict = corroborate(edge.get("votes", {}), accounts, quorum)
        kind = verdict["kind"]
        if cell in decisions and decisions[cell] in KIND_ORDER:
            kind = decisions[cell]
            decided.append(cell)
        elif len(verdict["corroborated"]) > 1:
            conflicts.append({
                "side": edge["side"], "x": edge["x"], "z": edge["z"],
                "kinds": list(verdict["corroborated"]),
                "evidence": verdict["evidence"],
            })
        if verdict["pending"]:
            pending.append(cell)
        kinds[cell] = kind
    return {"kinds": kinds, "pending": pending, "conflicts": conflicts, "decided": decided}


def publishable_copy(doc: dict[str, Any], kinds: dict[tuple[int, int, str], str]) -> dict[str, Any]:
    """The document the compiler sees: the policy's kinds, everything else as stored.

    Never written to disk. Both validators would refuse it, rightly — its
    kinds do not follow from its votes — and it exists only so the geometry
    the service publishes draws what the policy decided.
    """
    out = copy.deepcopy(doc)
    for edge in out.get("edges", []):
        edge["kind"] = kinds.get(cell_of(edge), edge.get("kind", "auto"))
    return out


def with_authored(compiled: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
    """The compiled geometry with the bundle's corners and sections riding along.

    The compiler draws what was surveyed and knows nothing of what was
    authored: where somebody marked each apex and what they called it. Those
    live in the bundle, are kept through a merge rather than recomputed, and
    are corrected here by pull request — so the bundle on `main` is the one
    authority for them, and the service, which only ever sees the compiled
    document, has no other way to learn them. They are copied rather than
    compiled: the service draws a corner at its apex and prints its name.

    A copy, so the geometry the gate measured is the geometry it measured.
    """
    out = dict(compiled)
    out["corners"] = copy.deepcopy(doc.get("corners") or [])
    out["sections"] = copy.deepcopy(doc.get("sections") or [])
    return out


def stored_kinds(doc: dict[str, Any] | None) -> dict[tuple[int, int, str], str]:
    """The format's own kinds, as the file on disk carries them."""
    if not doc:
        return {}
    return {cell_of(e): resolve_kind(e.get("votes", {})) for e in doc.get("edges", [])}


def kind_changes(before: dict[str, Any] | None, after: dict[str, Any],
                 accounts: dict[str, str], quorum: int) -> list[dict[str, Any]]:
    """Metres whose stored kind this merge changes, and whether the policy agrees.

    A change to an inferred kind is always corroborated — it is physics. A
    change to a manual kind is corroborated only when the policy would decide
    that kind too, which is what stops one person's wall auto-merging.
    """
    was = stored_kinds(before)
    if not was:
        return []
    by_cell = {cell_of(e): e for e in after.get("edges", [])}
    changes: list[dict[str, Any]] = []
    for cell, edge in by_cell.items():
        old = was.get(cell)
        new = resolve_kind(edge.get("votes", {}))
        if old is None or old == new:
            continue
        corroborated = new in AUTO_KINDS or corroborate(edge.get("votes", {}), accounts, quorum)["kind"] == new
        changes.append({"side": edge["side"], "x": edge["x"], "z": edge["z"],
                        "from": old, "to": new, "corroborated": corroborated})
    return changes


def new_metres(before: dict[str, Any] | None, after: dict[str, Any]) -> int:
    had = {cell_of(e) for e in (before or {}).get("edges", [])}
    return sum(1 for e in after.get("edges", []) if cell_of(e) not in had)


# ── which layout the survey is of ──────────────────────────────────────────


def centreline_length(compiled: dict[str, Any] | None) -> float | None:
    """How far a car drives round the compiled centre line, or None without one."""
    if not compiled:
        return None
    total = 0.0
    seen = False
    for run in compiled.get("centerline") or []:
        for a, b in zip(run, run[1:]):
            total += math.hypot(b[0] - a[0], b[1] - a[1])
            seen = True
    return total if seen else None


def _box_matches(sig: dict[str, float], row: dict[str, Any]) -> bool:
    for lo, hi in (("min_x", "max_x"), ("min_z", "max_z")):
        if abs((sig[lo] + sig[hi]) / 2 - (row[lo] + row[hi]) / 2) > CENTER_TOLERANCE_M:
            return False
        extent, row_extent = sig[hi] - sig[lo], row[hi] - row[lo]
        if row_extent > 0 and abs(extent - row_extent) / row_extent > EXTENT_TOLERANCE:
            return False
    return True


def identify_layout(doc: dict[str, Any], compiled: dict[str, Any] | None,
                    signatures: dict[str, Any]) -> dict[str, Any]:
    """What `signatures.json` says this survey is of, walked in driving order.

    A signature row is a box, a length and a racing line in travel order, and
    a forward row carries its reverse twin. The box says which venue and
    configuration family; the length narrows it when a compiled centre line
    is there to measure; the survey's own recorded headings against the row's
    line say which way round — which is the one thing that tells a layout from
    its reverse. The question asked is whether the contributor's confirmed
    layout is among the readings the geometry supports, because two
    configurations of one venue can share a box entirely and the honest answer
    then is "either", not a coin toss.
    """
    claimed = str(((doc.get("meta") or {}).get("official") or {}).get("official_id", ""))
    edges = doc.get("edges", [])
    if not edges:
        return {"agrees": False, "signature_official_id": "", "candidates": [], "reason": "no edges"}
    sig = box(edges)
    length = centreline_length(compiled)

    rows = list(signatures.get("signatures", []))
    by_box = [row for row in rows if _box_matches(sig, row)]
    by_length = [row for row in by_box
                 if length is None or row.get("length_m", 0) <= 0
                 or abs(length - row["length_m"]) / row["length_m"] <= LENGTH_TOLERANCE]
    candidates = by_length or by_box

    readings: list[dict[str, Any]] = []
    for row in candidates:
        path = [tuple(p) for p in (row.get("path") or [])]
        twin = (row.get("reverse") or {}).get("official_id", "")
        if len(path) >= MIN_PATH_POINTS:
            agree, disagree = heading_agreement(edges, path)
            official_id = twin if (disagree > agree and twin) else row["official_id"]
            readings.append({"official_id": official_id, "row": row["official_id"],
                             "agree": agree, "disagree": disagree,
                             "signature_line": path})
        else:
            # No line to read direction from: the row and its twin are both
            # possible, and the geometry cannot say which.
            for official_id in (row["official_id"], twin):
                if official_id:
                    readings.append({"official_id": official_id, "row": row["official_id"],
                                     "agree": 0, "disagree": 0, "signature_line": []})

    consistent = [r for r in readings if r["official_id"] == claimed]
    best = max(readings, key=lambda r: (r["agree"] - r["disagree"], r["agree"]), default=None)
    chosen = consistent[0] if consistent else best
    return {
        # True: the geometry supports the confirmed layout. False: it supports
        # another. None: no signature describes this venue at all, which is a
        # first survey for a person to read, not a survey filed under the
        # wrong name — the gate reports it and the pull request waits.
        "agrees": True if consistent else (False if readings else None),
        "contributor_official_id": claimed,
        "signature_official_id": chosen["official_id"] if chosen else "",
        "candidates": sorted({r["official_id"] for r in readings}),
        "heading_agree": chosen["agree"] if chosen else 0,
        "heading_disagree": chosen["disagree"] if chosen else 0,
        "signature_line": [[float(x), float(z)] for x, z in chosen["signature_line"]] if chosen else [],
        "length_m": round(length, 1) if length is not None else None,
        "box": sig,
    }


def contributor_line(compiled: dict[str, Any] | None, points: int = LINE_POINTS) -> list[list[float]]:
    """The compiled centre line, thinned, for an issue a person will look at."""
    if not compiled:
        return []
    line: list[list[float]] = []
    for run in compiled.get("centerline") or []:
        line.extend([round(float(p[0]), 1), round(float(p[1]), 1)] for p in run)
    if len(line) <= points:
        return line
    step = len(line) / points
    return [line[int(i * step)] for i in range(points)]


# ── the auto-merge gate (spec §6) ──────────────────────────────────────────


def crossing_spread(crossings: list[dict[str, Any]]) -> float | None:
    """The greatest distance between any two crossings: a diameter, not a
    distance from a mean, because the ends are what say whether the finish
    line was found twice or approximated once."""
    if len(crossings) < 2:
        return 0.0
    worst = 0.0
    for i, a in enumerate(crossings):
        for b in crossings[i + 1:]:
            try:
                d = math.hypot(a["x"] - b["x"], a["z"] - b["z"])
            except (KeyError, TypeError):
                return None
            if not math.isfinite(d):
                return None
            worst = max(worst, d)
    return worst


def along_line_spread(crossings: list[dict[str, Any]]) -> float | None:
    """The spread of the crossings along the direction of travel only.

    Not the rule — the gate measures the Euclidean diameter, as the spec and
    the service's reference implementation do — but printed beside it, because
    on every survey this repository holds the two disagree by an order of
    magnitude: a car crosses the finish line at a different place across the
    road each lap (10–15 m of spread), while where it crosses along the road
    agrees to a metre or two. A reviewer reading "12.8 m" deserves to see
    "0.6 m along the line" next to it before deciding what the figure means.
    """
    if len(crossings) < 2:
        return 0.0
    try:
        hx = sum(float(c["hx"]) for c in crossings) / len(crossings)
        hz = sum(float(c["hz"]) for c in crossings) / len(crossings)
        norm = math.hypot(hx, hz)
        if norm == 0:
            return None
        along = [float(c["x"]) * hx / norm + float(c["z"]) * hz / norm for c in crossings]
    except (KeyError, TypeError, ValueError):
        return None
    return max(along) - min(along)


def gate_coverage(compiled: dict[str, Any] | None) -> dict[str, dict[str, Any]] | None:
    if not compiled:
        return None
    cov = compiled.get("coverage") or {}
    gaps = compiled.get("gaps") or {}
    out: dict[str, dict[str, Any]] = {}
    for label, side in (("left", "L"), ("right", "R")):
        s = cov.get(side) or {}
        out[label] = {"pct": float(s.get("pct", 0) or 0), "closed": bool(s.get("closed")),
                      "gaps": len(gaps.get(side) or [])}
    return out


def _metres(value: float) -> str:
    return f"{round(value * 100) / 100:g} m"


def _percent(value: float) -> str:
    return f"{round(value * 10) / 10:g}%"


def _side_complete(side: dict[str, Any]) -> bool:
    return bool(side["closed"]) and side["gaps"] == 0 and side["pct"] >= 100


def _describe_side(side: dict[str, Any]) -> str:
    gaps = "1 gap" if side["gaps"] == 1 else f"{side['gaps']} gaps"
    return f"{_percent(side['pct'])}, {'closed' if side['closed'] else 'open'}, {gaps}"


def evaluate_gate(inp: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Every criterion, whichever way it went, in the shape the service prints.

    Mirrors `src/domain/policy.ts` in the sync service, which is the reference
    implementation and the thing the admin panel renders these documents
    with. A criterion that cannot be evaluated fails rather than abstains: the
    cost of that is a pull request a human reads, and the cost of the other
    choice is an unreviewed regression.
    """
    min_crossings = max(1, int(settings.get("min_finish_crossings", 3)))
    max_spread = float(settings.get("crossing_spread_m", 5))
    require_full = bool(settings.get("require_full_coverage", True))
    criteria: list[dict[str, Any]] = []

    crossings = list(inp.get("crossings") or [])
    criteria.append({"id": "finish_crossings", "label": "Finish crossings",
                     "pass": len(crossings) >= min_crossings,
                     "value": str(len(crossings)), "expected": f"at least {min_crossings}"})

    spread = crossing_spread(crossings)
    along = along_line_spread(crossings)
    criteria.append({"id": "crossing_spread", "label": "Crossing spread",
                     "pass": spread is not None and spread <= max_spread,
                     "value": "not a position" if spread is None else
                     _metres(spread) + (f" ({_metres(along)} along the line)" if along is not None else ""),
                     "expected": f"within {_metres(max_spread)}"})

    contributor = str(inp.get("contributor_official_id", "")).strip()
    signature = str(inp.get("signature_official_id", "")).strip()
    accepted = inp.get("layout_accepted_at")
    if accepted:
        criteria.append({"id": "layout_agreement", "label": "Layout agreement", "pass": True,
                         "value": f"{contributor}, accepted by the administrator on {accepted}",
                         "expected": "the confirmed layout and the signature name the same configuration"})
    else:
        criteria.append({"id": "layout_agreement", "label": "Layout agreement",
                         "pass": contributor != "" and contributor == signature,
                         "value": (contributor or "neither side named a layout") if contributor == signature
                         else f"contributor {contributor or '(none)'}, signature {signature or '(none)'}",
                         "expected": "the confirmed layout and the signature name the same configuration"})

    coverage = inp["coverage"]
    if not inp.get("published"):
        complete = _side_complete(coverage["left"]) and _side_complete(coverage["right"])
        criteria.append({"id": "perimeter_complete", "label": "Perimeter complete",
                         "pass": complete or not require_full,
                         "value": f"left {_describe_side(coverage['left'])}; right {_describe_side(coverage['right'])}",
                         "expected": "both sides closed, 100%, no gaps" if require_full
                         else "not required on this deployment"})
    else:
        before = inp.get("previous_coverage")
        comparable = before is not None
        if comparable:
            lb, rb = before["left"]["pct"], before["right"]["pct"]
            la, ra = coverage["left"]["pct"], coverage["right"]["pct"]
        criteria.append({"id": "coverage_held", "label": "Coverage held",
                         "pass": comparable and la >= lb and ra >= rb,
                         "value": (f"left {_percent(lb)} → {_percent(la)}; right {_percent(rb)} → {_percent(ra)}"
                                   if comparable else "no published coverage to compare against"),
                         "expected": "neither side lower than what is published"})

        changes = list(inp.get("kind_changes") or [])
        uncorroborated = [c for c in changes if not c["corroborated"]]
        first = uncorroborated[0] if uncorroborated else None
        criteria.append({"id": "kind_changes", "label": "Kind changes corroborated",
                         "pass": not uncorroborated,
                         "value": (f"{len(changes)} change{'' if len(changes) == 1 else 's'}, all corroborated"
                                   if not uncorroborated else
                                   f"{len(uncorroborated)} of {len(changes)} not corroborated"
                                   + (f" (first at ({first['x']:.1f}, {first['z']:.1f}) side {first['side']}: "
                                      f"{first['from']} → {first['to']})" if first else "")),
                         "expected": "every changed metre satisfies the corroboration policy"})

    failed = [c["id"] for c in criteria if not c["pass"]]
    return {"pass": not failed, "mode": "update" if inp.get("published") else "first_publication",
            "criteria": criteria, "failed": failed}


# ── the repository: files, git, and the forge ──────────────────────────────


class Repository:
    """This checkout: the bundles, the derived files, and the checks."""

    def __init__(self, root: Path = ROOT, python: str = sys.executable) -> None:
        self.root = Path(root)
        self.python = python

    def catalog_configurations(self) -> list[dict[str, Any]]:
        return configurations(json.loads((self.root / "catalog" / "tracks.json").read_text(encoding="utf-8")))

    def signatures(self) -> dict[str, Any]:
        path = self.root / "signatures.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"signatures": []}

    def bundle_path(self, slug: str) -> Path:
        return self.root / "tracks" / f"{slug}.json"

    def read_bundle(self, slug: str) -> tuple[dict[str, Any] | None, str]:
        path = self.bundle_path(slug)
        if not path.exists():
            return None, ""
        text = path.read_text(encoding="utf-8")
        return validate_document(json.loads(text)), text

    def write_bundle(self, slug: str, doc: dict[str, Any]) -> Path:
        path = self.bundle_path(slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical.dumps(doc), encoding="utf-8")
        return path

    def _tool(self, script: str, *args: str) -> tuple[bool, str]:
        run = subprocess.run([self.python, str(self.root / "tools" / script), *args],
                             cwd=self.root, capture_output=True, text=True)
        return run.returncode == 0, (run.stdout + run.stderr).strip()

    def rebuild_derived(self) -> list[tuple[str, bool, str]]:
        """index.json and signatures.json follow the bundles; both are committed."""
        return [("index.json rebuilt", *self._tool("build_index.py")),
                ("signatures.json rebuilt", *self._tool("build_signatures.py"))]

    def checks(self) -> list[tuple[str, bool, str]]:
        """What validate.yml would ask, asked here — a pull request opened with
        GITHUB_TOKEN does not start workflows, so the answers go in the body."""
        return [("every bundle is valid", *self._tool("validate.py")),
                ("index.json matches the bundles", *self._tool("build_index.py", "--check")),
                ("signatures.json matches its inputs", *self._tool("build_signatures.py", "--check"))]


class Git:
    """The few git operations the job needs, against this checkout."""

    def __init__(self, root: Path, runner: Callable[..., Any] = subprocess.run) -> None:
        self.root = Path(root)
        self.runner = runner

    def run(self, *args: str, check: bool = True) -> str:
        result = self.runner(["git", *args], cwd=self.root, capture_output=True, text=True)
        if check and result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {result.stderr.strip() or result.stdout.strip()}")
        return result.stdout.strip()

    def prepare_branch(self, branch: str, base: str = "origin/main") -> None:
        """Start the branch again from the base, whatever it held before."""
        remote, _, ref = base.partition("/")
        self.run("fetch", remote, ref)
        self.run("checkout", "-B", branch, base)

    def commit(self, paths: list[str], message: str) -> bool:
        """Stage and commit; False when the paths hold nothing new."""
        self.run("add", "--", *paths)
        staged = self.runner(["git", "diff", "--cached", "--quiet"], cwd=self.root,
                             capture_output=True, text=True)
        if staged.returncode == 0:
            return False
        self.run("commit", "-q", "-m", message)
        return True

    def push_force(self, branch: str, remote: str = "origin") -> None:
        self.run("push", "--force", "-q", remote, branch)

    def current_branch(self) -> str:
        return self.run("rev-parse", "--abbrev-ref", "HEAD")


class Forge:
    """GitHub, through `gh`: pull requests, merging, and asking workflows to run."""

    def __init__(self, runner: Callable[..., Any] = subprocess.run, root: Path = ROOT) -> None:
        self.runner = runner
        self.root = Path(root)

    def gh(self, *args: str, check: bool = True) -> str:
        result = self.runner(["gh", *args], cwd=self.root, capture_output=True, text=True)
        if check and result.returncode != 0:
            raise RuntimeError(f"gh {' '.join(args)}: {result.stderr.strip() or result.stdout.strip()}")
        return result.stdout.strip()

    def open_pr_url(self, branch: str) -> str:
        return self.gh("pr", "list", "--head", branch, "--state", "open", "--json", "url",
                       "--jq", ".[0].url // empty", check=False)

    def merged_pr_url(self, branch: str) -> str:
        return self.gh("pr", "list", "--head", branch, "--state", "merged", "--json", "url",
                       "--jq", ".[0].url // empty", check=False)

    def upsert(self, branch: str, title: str, body: str, draft: bool) -> str:
        body_file = self.root / ".git" / f"sync-{branch.replace('/', '-')}.md"
        body_file.write_text(body, encoding="utf-8")
        url = self.open_pr_url(branch)
        if url:
            self.gh("pr", "edit", branch, "--title", title, "--body-file", str(body_file))
            return url
        args = ["pr", "create", "--base", "main", "--head", branch, "--title", title,
                "--body-file", str(body_file)]
        if draft:
            args.append("--draft")
        return self.gh(*args)

    def merge(self, branch: str, attempts: int = 5, wait: Callable[[float], None] = time.sleep) -> bool:
        # Mergeability is computed asynchronously; a pull request created a
        # moment ago is not always mergeable yet.
        self.gh("pr", "ready", branch, check=False)
        for attempt in range(1, attempts + 1):
            if self.runner(["gh", "pr", "merge", branch, "--squash", "--delete-branch"],
                           cwd=self.root, capture_output=True, text=True).returncode == 0:
                return True
            if attempt < attempts:
                wait(10)
        return False

    def workflow_run(self, workflow: str) -> None:
        # A merge made with GITHUB_TOKEN starts no workflow, so the pack and the
        # site are asked for by name; workflow_dispatch is the documented
        # exception to that rule.
        self.gh("workflow", "run", workflow, "--ref", "main", check=False)


# ── the compiler ───────────────────────────────────────────────────────────


def _compiler() -> Any:
    try:
        from app.processing import track_compile
    except ImportError:  # pragma: no cover - the message is the test
        raise SystemExit(
            "This job needs the datalogger's compiler, which the repository's own tools do not:\n"
            '  pip install "gt7-datalogger @ git+https://github.com/jbhoorasingh/gt7-datalogger'
            '@main#subdirectory=backend"'
        ) from None
    return track_compile


def smooth_borders(policy: dict[str, Any]) -> bool | None:
    """What the administrator said about smoothing the published borders.

    `compile.smooth_borders` in the service's settings, served with the rest
    of the policy. None is a service from before the switch existed, which
    said nothing — and then the compiler does whatever it does by default,
    rather than this job inventing an answer on the administrator's behalf.
    Only a real boolean counts: a switch that read "off" as true would go on
    smoothing a map its owner had said not to.
    """
    value = (policy.get("compile") or {}).get("smooth_borders")
    return value if isinstance(value, bool) else None


def compiler_takes_smooth() -> bool:
    """Whether the installed compiler can be told. One from before it learned
    to smooth cannot, and does not smooth either."""
    import inspect

    return "smooth" in inspect.signature(_compiler().compile_bundle).parameters


def compile_geometry(doc: dict[str, Any], smooth: bool | None = None) -> dict[str, Any]:
    """The datalogger's own compiler, which this repository never re-implements.

    `smooth` is the administrator's answer (see `smooth_borders`). Every
    compile in a run gets the same one — a circuit's published geometry and
    its candidate above all, because "coverage held" compares the two, and a
    smoothed border is a fraction shorter than the same border as recorded.
    """
    compiler = _compiler()
    if smooth is None or not compiler_takes_smooth():
        return compiler.compile_bundle(doc)
    return compiler.compile_bundle(doc, smooth=smooth)


# ── one circuit ────────────────────────────────────────────────────────────


@dataclass
class Context:
    service: Service
    repo: Repository
    git: Git | None
    forge: Forge | None
    policy: dict[str, Any]
    accounts: dict[str, str]
    configs: dict[str, dict[str, Any]]
    signatures: dict[str, Any]
    dry_run: bool = False
    report: bool = True
    log: Callable[[str], None] = print


@dataclass
class Outcome:
    official_id: str
    name: str
    slug: str
    action: str = "nothing"  # merged | pull_request | held | rejected | nothing
    uploads: list[str] = field(default_factory=list)
    pr_url: str = ""
    gate: dict[str, Any] | None = None
    issues_raised: int = 0
    auto_merged: bool = False
    reason: str = ""


def _decisions_by_cell(decisions: list[dict[str, Any]]) -> dict[tuple[int, int, str], str]:
    out: dict[tuple[int, int, str], str] = {}
    for decision in decisions:
        detail = decision.get("detail") or {}
        try:
            cell = (round(float(detail["x"])), round(float(detail["z"])), str(detail["side"]))
        except (KeyError, TypeError, ValueError):
            continue
        out[cell] = str(decision.get("kind", ""))
    return out


def _report(ctx: Context, upload_ids: list[str], status: str, reason: str = "", pr_url: str = "") -> None:
    if not ctx.report or ctx.dry_run:
        return
    for upload_id in upload_ids:
        ctx.service.report_status(upload_id, status, reason, pr_url)


def _raise(ctx: Context, outcome: Outcome, **issue: Any) -> None:
    outcome.issues_raised += 1
    if not ctx.report or ctx.dry_run:
        ctx.log(f"  would raise {issue.get('type')}: {issue.get('summary')}")
        return
    reply = ctx.service.raise_issue(**issue)
    ctx.log(f"  {issue.get('type')} {reply.get('outcome', '?')}: {issue.get('summary')}")


def publication_facts(config: dict[str, Any], doc: dict[str, Any], compiled: dict[str, Any],
                      accounts: dict[str, str], r2_key: str, pr_url: str,
                      merge_status: str) -> dict[str, Any]:
    """What the public Tracks page shows, from the merged document and its geometry."""
    cov = compiled.get("coverage") or {}
    sources = list((doc.get("meta") or {}).get("source_runs", {}).keys())
    known = {accounts[s] for s in sources if s in accounts}
    unmapped = [s for s in sources if s not in accounts and not s.startswith(DRAWN_PREFIX)]
    left = (cov.get("L") or {})
    right = (cov.get("R") or {})
    return {
        "track_name": config["official_name"],
        "slug": slugify(config["official_name"]),
        "length_m": int(round(float(config.get("length_m") or 0))),
        "coverage": {"left": float(left.get("pct", 0) or 0), "right": float(right.get("pct", 0) or 0)},
        "closed": bool(left.get("closed")) and bool(right.get("closed")),
        "contributors": len(known) + len(unmapped),
        "runs": int((doc.get("meta") or {}).get("runs", 0) or 0),
        "latest_r2_key": r2_key,
        "pr_url": pr_url,
        "merge_status": merge_status,
        "published_at": now_iso(),
    }


def pr_body(outcome: Outcome, config: dict[str, Any], uploads: list[dict[str, Any]],
            policy_report: dict[str, Any], checks: list[tuple[str, bool, str]],
            new_m: int, changes: list[dict[str, Any]], accounts_count: int) -> str:
    gate = outcome.gate or {"criteria": [], "pass": False, "mode": "first_publication"}
    lines = [
        f"{len(uploads)} survey upload{'' if len(uploads) == 1 else 's'} of **{config['official_name']}** "
        f"(`{config['official_id']}`) from the sync service, merged into `tracks/{outcome.slug}.json` "
        f"with the same rules `add_bundle.py` applies.",
        "",
        f"- contributing accounts: {accounts_count}",
        f"- new metres of border: {new_m}",
        f"- metres whose stored kind changed: {len(changes)}"
        + (f" ({sum(1 for c in changes if not c['corroborated'])} not corroborated)" if changes else ""),
        f"- metres with a manual kind still waiting for quorum: {len(policy_report.get('pending', []))}",
        f"- quorum conflicts raised for the administrator: {len(policy_report.get('conflicts', []))}",
        "",
        f"## Gate — {'passed' if gate['pass'] else 'not passed'} ({gate['mode'].replace('_', ' ')})",
        "",
        "| criterion | result | value | expected |",
        "| --- | --- | --- | --- |",
    ]
    for c in gate["criteria"]:
        lines.append(f"| {c['label']} | {'pass' if c['pass'] else '**FAIL**'} | {c['value']} | {c['expected']} |")
    lines += ["", "## Uploads", ""]
    for upload in uploads:
        lines.append(f"- `{upload['id']}` — {upload.get('edges', 0)} records, {upload.get('runs', 0)} runs, "
                     f"received {upload.get('received_at', '')}, account `{upload.get('user_id', '')}`")
    lines += ["", "## Checks", ""]
    for name, ok, _ in checks:
        lines.append(f"- {name}: {'pass' if ok else '**FAIL**'}")
    lines += [
        "",
        f"_Opened by `{WORKFLOW}`. Run in this job, not on the pull request: one opened with "
        "`GITHUB_TOKEN` does not start workflows, so `validate` will not run on it by itself. "
        "Pushing any commit of your own to this branch will start it._",
    ]
    return "\n".join(lines) + "\n"


def process_track(ctx: Context, official_id: str, uploads: list[dict[str, Any]]) -> Outcome:
    config = ctx.configs.get(official_id)
    ids = [u["id"] for u in uploads]
    if config is None:
        outcome = Outcome(official_id, official_id, "", "rejected", ids,
                          reason="this layout id is not in catalog/tracks.json, so there is nowhere to file it")
        ctx.log(f"{official_id}: {outcome.reason}")
        _report(ctx, ids, "rejected", outcome.reason)
        return outcome

    slug = slugify(config["official_name"])
    outcome = Outcome(official_id, config["official_name"], slug, uploads=ids)
    branch = BRANCH_PREFIX + slug
    ctx.log(f"{official_id}  {config['official_name']}: {len(uploads)} pending")

    # Start from main, so the branch is rebuilt from what is published now.
    if ctx.git is not None and not ctx.dry_run:
        ctx.git.prepare_branch(branch)

    existing, existing_text = ctx.repo.read_bundle(slug)

    # Fetch and validate each upload; a document the repository would refuse
    # is refused now, with the validator's own words for the contributor.
    docs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for upload in uploads:
        try:
            doc = validate_document(ctx.service.fetch_bundle(upload))
            claimed = str(((doc.get("meta") or {}).get("official") or {}).get("official_id", ""))
            if claimed != official_id:
                raise ValueError(f"the bundle names layout {claimed!r}, but was filed under {official_id!r}")
        except (ValueError, KeyError, TypeError, ServiceError) as exc:
            reason = f"the survey could not be merged: {exc}"
            ctx.log(f"  {upload['id']} rejected: {exc}")
            _report(ctx, [upload["id"]], "rejected", reason)
            continue
        docs.append((upload, doc))
    if not docs:
        outcome.action = "rejected"
        return outcome

    # The corroboration policy counts accounts; every source in every upload
    # belongs to the account that uploaded it.
    accounts = dict(ctx.accounts)
    for upload, doc in docs:
        accounts.setdefault(str(upload["source_id"]), str(upload["user_id"]))
        for source in (doc.get("meta") or {}).get("source_runs", {}):
            accounts.setdefault(str(source), str(upload["user_id"]))
    quorum = int((ctx.policy.get("policy") or {}).get("manual_quorum", 2))
    gate_settings = ctx.policy.get("gate") or {}

    merged = copy.deepcopy(existing) if existing else None
    for _, doc in docs:
        merged = merge_into(merged, doc) if merged is not None else copy.deepcopy(doc)
    assert merged is not None
    merged_text = canonical.dumps(merged)
    merged_ids = [u["id"] for u, _ in docs]

    if existing is not None and merged_text == existing_text:
        # Everything these uploads contribute is already on main: a pull
        # request that landed, or a survey somebody merged by hand.
        pr_url = ctx.forge.merged_pr_url(branch) if ctx.forge and not ctx.dry_run else ""
        ctx.log(f"  already in main → merged" + (f" ({pr_url})" if pr_url else ""))
        outcome.action = "merged"
        outcome.pr_url = pr_url
        _report(ctx, merged_ids, "merged", "already published in the track data", pr_url)
        if ctx.report and not ctx.dry_run:
            kinds = policy_kinds(existing, accounts, quorum,
                                 _decisions_by_cell(ctx.service.kind_decisions(official_id)))["kinds"]
            compiled = compile_geometry(publishable_copy(existing, kinds), smooth_borders(ctx.policy))
            stored = ctx.service.put_compiled(official_id, with_authored(compiled, existing))
            ctx.service.publish(official_id, publication_facts(
                config, existing, compiled, accounts, stored["r2_key"], pr_url, "auto_merged"))
        return outcome

    # The policy, applied to the geometry; the format's kinds stay in the file.
    decisions = _decisions_by_cell(ctx.service.kind_decisions(official_id))
    after = policy_kinds(merged, accounts, quorum, decisions)
    before = policy_kinds(existing, accounts, quorum, decisions) if existing else None
    smooth = smooth_borders(ctx.policy)
    compiled_after = compile_geometry(publishable_copy(merged, after["kinds"]), smooth)
    compiled_before = (compile_geometry(publishable_copy(existing, before["kinds"]), smooth)
                       if existing and before else None)

    # Which layout the geometry says this is, and whether a person already answered.
    layout = identify_layout(merged, compiled_after, ctx.signatures)
    accepted = ctx.service.layout_decisions(official_id)
    accepted_at = str(accepted[-1].get("decided_at", "")) if accepted else ""
    if layout["agrees"] is False and not accepted_at:
        first_upload = docs[0][0]
        summary = (f"the contributor confirmed {layout['contributor_official_id']}; "
                   f"signatures.json identifies {layout['signature_official_id'] or 'no configuration'}")
        _raise(ctx, outcome, type="layout_mismatch", official_id=official_id,
               upload_id=first_upload["id"], user_id=first_upload["user_id"], summary=summary,
               detail={
                   "contributor_official_id": layout["contributor_official_id"],
                   "signature_official_id": layout["signature_official_id"],
                   "candidates": layout["candidates"],
                   "heading_agree": layout["heading_agree"],
                   "heading_disagree": layout["heading_disagree"],
                   "centreline_length_m": layout["length_m"],
                   "uploads": merged_ids,
                   "contributor_line": contributor_line(compiled_after),
                   "signature_line": layout["signature_line"][:LINE_POINTS],
               },
               trigger={"contributor": layout["contributor_official_id"],
                        "signature": layout["signature_official_id"]})
        outcome.action = "held"
        outcome.reason = summary
        _report(ctx, merged_ids, "held", f"held for a layout check: {summary}")
        return outcome

    for conflict in after["conflicts"]:
        _raise(ctx, outcome, type="quorum_conflict", official_id=official_id,
               upload_id=docs[0][0]["id"],
               summary=f"two manual kinds each reach quorum at ({conflict['x']:.1f}, {conflict['z']:.1f}) "
                       f"side {conflict['side']}: {' and '.join(conflict['kinds'])}",
               detail={"side": conflict["side"], "x": conflict["x"], "z": conflict["z"],
                       "kinds": conflict["kinds"],
                       "votes": {e["kind"]: {"accounts": e["accounts"], "drawn": e["drawn"],
                                             "unmapped": e["unmapped"]} for e in conflict["evidence"]}},
               trigger={"side": conflict["side"], "x": round(conflict["x"]), "z": round(conflict["z"])})

    changes = kind_changes(existing, merged, accounts, quorum)
    new_m = new_metres(existing, merged)
    accounts_count = len({str(u["user_id"]) for u, _ in docs})
    coverage = gate_coverage(compiled_after)
    gate = evaluate_gate({
        "published": existing is not None,
        "crossings": merged.get("finish_crossings", []),
        "contributor_official_id": layout["contributor_official_id"],
        "signature_official_id": layout["signature_official_id"],
        "layout_accepted_at": accepted_at,
        "coverage": coverage,
        "previous_coverage": gate_coverage(compiled_before),
        "kind_changes": changes,
    }, gate_settings)
    outcome.gate = gate
    ctx.log(f"  gate {'passed' if gate['pass'] else 'failed: ' + ', '.join(gate['failed'])}")

    if existing is not None and "coverage_held" in gate["failed"] and compiled_before:
        prev = gate_coverage(compiled_before) or {}
        worse = [side for side in ("left", "right") if coverage[side]["pct"] < prev[side]["pct"]]
        summary = "merging these uploads would lower the published coverage on the " + " and ".join(worse) + " side"
        _raise(ctx, outcome, type="coverage_regressed", official_id=official_id,
               upload_id=docs[0][0]["id"], summary=summary,
               detail={"sides": worse,
                       **{f"{side}_before_pct": prev[side]["pct"] for side in worse},
                       **{f"{side}_after_pct": coverage[side]["pct"] for side in worse},
                       **{f"{side}_gaps_after": coverage[side]["gaps"] for side in worse},
                       "uploads": merged_ids},
               trigger={"sides": worse, "uploads": merged_ids})
        outcome.action = "held"
        outcome.reason = summary
        _report(ctx, merged_ids, "held", f"held: {summary}")
        return outcome

    if ctx.dry_run or ctx.git is None:
        if ctx.git is None and not ctx.dry_run:
            ctx.repo.write_bundle(slug, merged)
            ctx.log(f"  wrote tracks/{slug}.json (no git)")
        outcome.action = "pull_request"
        return outcome

    # The branch: the bundle, the derived files, the checks, the pull request.
    ctx.repo.write_bundle(slug, merged)
    derived = ctx.repo.rebuild_derived()
    checks = derived + ctx.repo.checks()
    clean = all(ok for _, ok, _ in checks)
    for name, ok, output in checks:
        if not ok:
            ctx.log(f"  {name}: FAIL\n{output}")
    message = (f"Merge {len(docs)} survey upload{'' if len(docs) == 1 else 's'} of "
               f"{config['official_name']} from the sync service\n\n"
               f"Opened by {WORKFLOW}. Which uploads, what changed and how the gate\n"
               f"judged it are in the pull request body.")
    ctx.git.commit([f"tracks/{slug}.json", "index.json", "signatures.json"], message)
    ctx.git.push_force(branch)

    title = f"Merge {len(docs)} survey upload{'' if len(docs) == 1 else 's'} of {config['official_name']} (sync)"
    body = pr_body(outcome, config, [u for u, _ in docs], after, checks, new_m, changes, accounts_count)
    assert ctx.forge is not None
    pr_url = ctx.forge.upsert(branch, title, body, draft=not clean)
    outcome.pr_url = pr_url
    outcome.action = "pull_request"
    ctx.log(f"  pull request: {pr_url}" + ("" if clean else " (a check failed; left as a draft)"))

    auto_merge = bool(gate_settings.get("auto_merge", False))
    status = "awaiting_review"
    if gate["pass"] and clean and auto_merge:
        if ctx.forge.merge(branch):
            status = "auto_merged"
            outcome.auto_merged = True
            outcome.action = "merged"
            ctx.log("  merged")
            ctx.forge.workflow_run("pack.yml")
            ctx.forge.workflow_run("pages.yml")
        else:
            ctx.log("  could not merge; left open for a person")

    if ctx.report:
        ctx.service.report_merge_request(
            official_id=official_id, pr_url=pr_url, branch=branch, accounts=accounts_count,
            new_metres=new_m, kind_changes=len(changes), gate=gate, status=status)
        if status == "auto_merged":
            stored = ctx.service.put_compiled(official_id, with_authored(compiled_after, merged))
            ctx.service.publish(official_id, publication_facts(
                config, merged, compiled_after, accounts, stored["r2_key"], pr_url, "auto_merged"))
            _report(ctx, merged_ids, "merged", "merged and published", pr_url)
        elif not gate["pass"]:
            _raise(ctx, outcome, type="gate_failed", official_id=official_id, upload_id=docs[0][0]["id"],
                   summary=f"the gate declined to merge {config['official_name']}: " + ", ".join(gate["failed"]),
                   detail={"pr_url": pr_url, "failed": gate["failed"], "uploads": merged_ids,
                           **{c["id"]: c["value"] for c in gate["criteria"]}},
                   trigger={"failed": gate["failed"], "uploads": merged_ids})
    return outcome


# ── the run ────────────────────────────────────────────────────────────────


def group_by_track(uploads: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for upload in uploads:
        groups.setdefault(str(upload["official_id"]), []).append(upload)
    return groups


def run(ctx: Context, official_id: str = "") -> tuple[bool, list[Outcome]]:
    uploads = ctx.service.pending_uploads(official_id)
    groups = group_by_track(uploads)
    ctx.log(f"{len(uploads)} pending upload{'' if len(uploads) == 1 else 's'} across "
            f"{len(groups)} circuit{'' if len(groups) == 1 else 's'}"
            + (" (dry run: nothing is written or reported)" if ctx.dry_run else ""))

    run_id = ""
    if ctx.report and not ctx.dry_run:
        run_id = ctx.service.open_run()

    ok = True
    outcomes: list[Outcome] = []
    for track, pending in groups.items():
        try:
            outcomes.append(process_track(ctx, track, pending))
        except Exception as exc:  # noqa: BLE001 - one circuit must not take the night down
            ok = False
            ctx.log(f"{track}: failed: {exc}")
            outcomes.append(Outcome(track, track, "", "nothing", [u["id"] for u in pending], reason=str(exc)))

    counters = {
        "tracks_touched": len(groups),
        "prs_opened": sum(1 for o in outcomes if o.pr_url and o.action in ("pull_request", "merged")),
        "auto_merged": sum(1 for o in outcomes if o.auto_merged),
        "awaiting_review": sum(1 for o in outcomes if o.action == "pull_request" and o.pr_url),
        "issues_raised": sum(o.issues_raised for o in outcomes),
    }
    if run_id:
        ctx.service.close_run(run_id, ok, counters, {
            "scope": official_id or "all",
            "tracks": [{"official_id": o.official_id, "action": o.action, "pr_url": o.pr_url,
                        "uploads": o.uploads, "reason": o.reason} for o in outcomes],
        })
    ctx.log(", ".join(f"{k.replace('_', ' ')} {v}" for k, v in counters.items()))
    return ok, outcomes


def publish_existing(ctx: Context) -> int:
    """Compile and publish every survey this repository already holds.

    The nightly run publishes a circuit's geometry only when it merges
    something for it, so a service that was deployed after the surveys were
    merged by hand shows their facts and not their outlines. This is the
    catch-up: the policy applied, the compiler run, the geometry stored and
    the facts published for each bundle in tracks/, exactly as a merge would
    have done. Idempotent, and it reports nothing about uploads.
    """
    quorum = int((ctx.policy.get("policy") or {}).get("manual_quorum", 2))
    published = 0
    for config in ctx.configs.values():
        slug = slugify(config["official_name"])
        existing, _ = ctx.repo.read_bundle(slug)
        if existing is None:
            continue
        official_id = config["official_id"]
        decisions = _decisions_by_cell(ctx.service.kind_decisions(official_id)) if ctx.report else {}
        kinds = policy_kinds(existing, ctx.accounts, quorum, decisions)["kinds"]
        compiled = compile_geometry(publishable_copy(existing, kinds), smooth_borders(ctx.policy))
        cov = compiled.get("coverage") or {}
        summary = (f"left {float((cov.get('L') or {}).get('pct', 0)):.1f}%, "
                   f"right {float((cov.get('R') or {}).get('pct', 0)):.1f}%")
        if ctx.dry_run or not ctx.report:
            ctx.log(f"{official_id}  {config['official_name']}: would publish ({summary})")
            continue
        stored = ctx.service.put_compiled(official_id, with_authored(compiled, existing))
        ctx.service.publish(official_id, publication_facts(
            config, existing, compiled, ctx.accounts, stored["r2_key"], "", "auto_merged"))
        ctx.log(f"{official_id}  {config['official_name']}: published ({summary})")
        published += 1
    return published


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--official-id", default="", help="one configuration; blank means every circuit with pending uploads")
    parser.add_argument("--service", default=os.environ.get(URL_ENV) or DEFAULT_SERVICE, help="the sync service's base URL")
    parser.add_argument("--dry-run", action="store_true", help="fetch, merge and judge; write and report nothing")
    parser.add_argument("--no-git", action="store_true", help="write tracks/ but open no branch or pull request")
    parser.add_argument("--no-report", action="store_true", help="do not tell the service what happened")
    parser.add_argument("--publish-existing", action="store_true",
                        help="compile and publish every survey already in tracks/, and read no queue")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    key = os.environ.get(KEY_ENV, "")
    if not key:
        print(f"{KEY_ENV} is not set; the service will not answer without it", file=sys.stderr)
        return 2
    service = Service(args.service, key)
    repo = Repository(ROOT)
    ctx = Context(
        service=service,
        repo=repo,
        git=None if (args.no_git or args.dry_run) else Git(ROOT),
        forge=None if (args.no_git or args.dry_run) else Forge(root=ROOT),
        policy=service.policy(),
        accounts=service.sources(),
        configs={c["official_id"]: c for c in repo.catalog_configurations()},
        signatures=repo.signatures(),
        dry_run=args.dry_run,
        report=not args.no_report,
    )
    # Said once, up front: which way the borders are being drawn is the first
    # thing to know about a map that looks different from yesterday's.
    wanted = smooth_borders(ctx.policy)
    if wanted is None:
        ctx.log("borders: the service said nothing about smoothing; the compiler's default applies")
    elif not compiler_takes_smooth():
        ctx.log(f"borders: the administrator set smoothing {'on' if wanted else 'off'}, but the installed "
                "compiler is from before it could smooth and compiles the evidence as recorded")
    else:
        ctx.log(f"borders: smoothing {'on' if wanted else 'off'} (compile.smooth_borders)")
    if args.publish_existing:
        count = publish_existing(ctx)
        print(f"{count} circuit{'' if count == 1 else 's'} published")
        return 0
    ok, _ = run(ctx, args.official_id.strip())
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
