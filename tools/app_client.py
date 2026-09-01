"""Talk to a running GT7 Datalogger — read-only.

Both local servers here (the editor's and the GUI's) offer to browse a running
app and pull a surveyed track out of it, and `pull_from_app.py` does the same
from a terminal. This is the one place that knows what the app's endpoints are
called, so the three of them cannot disagree about it.

Read-only is a boundary, not a coincidence. The app is somebody's live survey:
this module lists and fetches, and pushing back is still `import_into_app.py`,
a separate command you have to mean to run.

Standard library only, like everything else in `tools/`.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_BASE = "http://localhost:8000"
TIMEOUT_S = 15
# 50,000 records is the format's ceiling and lands near 8 MB. This is a guard
# against a wrong URL streaming something enormous at us, not a real limit.
MAX_BYTES = 64 * 1024 * 1024

# The app's own slugs. Anything else is either a mistake or an attempt to walk
# out of the endpoint's path, and both deserve the same answer.
SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,120}$")


class AppError(RuntimeError):
    """The app could not be reached, or did not answer with what was asked."""


def normalise_base(base: str | None) -> str:
    """The app's base URL, or an explanation of why it is not one."""
    # Trailing slashes come off after parsing, not before: "http://".rstrip("/")
    # is "http:", which then reads as a bare host and quietly becomes a URL
    # that resolves to nothing.
    candidate = (base or DEFAULT_BASE).strip()
    if not candidate:
        candidate = DEFAULT_BASE
    if "://" not in candidate:
        candidate = f"http://{candidate}"
    parsed = urllib.parse.urlsplit(candidate)
    if parsed.scheme not in ("http", "https"):
        raise AppError(f"{base!r} is not an http(s) address")
    if not parsed.hostname:
        raise AppError(f"{base!r} has no host")
    try:
        parsed.port
    except ValueError as exc:
        raise AppError(f"{base!r} does not have a usable port") from exc
    if parsed.username or parsed.password:
        # A URL carrying credentials would put them in this process's logs and
        # in the page's history. Use --token, or GT7_ADMIN_TOKEN.
        raise AppError("put the app's token in --token or GT7_ADMIN_TOKEN, not in the URL")
    if parsed.query or parsed.fragment:
        raise AppError("the app's base URL takes no query string")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _get(url: str, token: str = "") -> Any:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", **({"X-API-Key": token} if token else {})},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            body = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        detail = exc.read(2048).decode("utf-8", "replace").strip()
        if exc.code in (401, 403):
            raise AppError(
                f"the app refused the request ({exc.code}). It has an admin token set — "
                "pass --token, or set GT7_ADMIN_TOKEN before starting this server."
            ) from exc
        raise AppError(f"the app answered {exc.code}: {detail[:200]}") from exc
    except urllib.error.URLError as exc:
        raise AppError(f"cannot reach {url}: {exc.reason}") from exc
    except OSError as exc:
        raise AppError(f"cannot reach {url}: {exc}") from exc
    if len(body) > MAX_BYTES:
        raise AppError("the app sent more than 64 MB — that is not a track bundle")
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AppError(
            f"{url} did not answer with JSON. Is that the datalogger's address?"
        ) from exc


def _row(raw: Any) -> dict[str, Any] | None:
    """One listing row, in the shape this repository's own tools want it.

    The app's listing has gained fields over time and may gain more. Reading it
    with .get and a default means a new datalogger does not break an old
    checkout of this repository over a field nothing here uses.
    """
    if not isinstance(raw, dict):
        return None
    slug = str(raw.get("slug") or "").strip()
    if not SLUG.match(slug):
        return None
    official = raw.get("official") if isinstance(raw.get("official"), dict) else {}

    def number(*names: str) -> int:
        for name in names:
            value = raw.get(name)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                return int(value)
        return 0

    return {
        "slug": slug,
        "track": str(raw.get("track") or raw.get("name") or slug),
        "official_id": str(official.get("official_id") or raw.get("official_id") or ""),
        "official_name": str(official.get("official_name") or raw.get("official_name") or ""),
        "points": number("points", "edges", "edge_count"),
        "runs": number("runs"),
        "updated_at": str(raw.get("updated_at") or ""),
    }


def list_bundles(base: str | None = None, token: str = "") -> list[dict[str, Any]]:
    """Every track bundle the app holds, newest name order."""
    root = normalise_base(base)
    payload = _get(f"{root}/api/track-bundles", token)
    if isinstance(payload, dict):
        payload = payload.get("bundles") or payload.get("tracks") or []
    if not isinstance(payload, list):
        raise AppError("the app's track listing was not a list of bundles")
    rows = [row for row in (_row(item) for item in payload) if row]
    return sorted(rows, key=lambda row: (row["official_name"] or row["track"]).lower())


def fetch_bundle(base: str | None, slug: str, token: str = "") -> dict[str, Any]:
    """One bundle document, exactly as the app stores it."""
    root = normalise_base(base)
    if not SLUG.match(slug or ""):
        raise AppError(f"{slug!r} is not a track slug")
    document = _get(f"{root}/api/track-bundles/{urllib.parse.quote(slug)}", token)
    if not isinstance(document, dict):
        raise AppError(f"the app did not return a bundle for {slug!r}")
    return document
