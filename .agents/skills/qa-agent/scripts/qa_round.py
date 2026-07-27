"""Round and run allocation for the QA Agent, plus the immutability guard.

A *round* is a numbered, immutable findings directory (``qa/rounds/NNN``, zero-padded to
three digits). A *run* is one execution of the layers inside a round
(``qa/rounds/NNN/runs/<runId>``); a round may hold several runs, but only the latest run's
``summary.json`` is authoritative.

A round is **sealed** the moment its ``summary.json`` exists. Sealed rounds are never
edited and never deleted: every mutating helper here refuses with exit code
``SEALED_ROUND`` (6), and ``round new`` always allocates ``max(existing) + 1``.

Standard library only, Python 3.9+.
"""

from __future__ import annotations

import os
import pathlib
import re
from typing import Any, Dict, List, Optional, Tuple

try:
    from . import qa_common as common
except ImportError:  # pragma: no cover - direct script execution
    import qa_common as common

# ---------------------------------------------------------------------------
# Command metadata (consumed by qa.py)
# ---------------------------------------------------------------------------

COMMAND = "round"
HELP = "Allocate, inspect, and seal immutable findings rounds."

ACTIONS = ("new", "current", "show", "seal")

SUMMARY_JSON = "summary.json"
SUMMARY_MD = "summary.md"
PLAN_JSON = "plan.json"
PLAN_MD = "plan.md"
RUNS_DIRNAME = "runs"
RUN_JSON = "run.json"

_ROUND_NAME_RE = re.compile(r"^[0-9]{1,9}$")
_ISSUE_NAME_RE = re.compile(r"^issue_([0-9]{1,9})\.md$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_HEADING_RE = re.compile(r"^#\s+(.+?)\s*$")

#: How many ``-2``, ``-3`` ... suffixes are tried before giving up on a run id.
_MAX_RUN_COLLISIONS = 999

#: Issue frontmatter keys, in the contract's order.
FRONTMATTER_KEYS = ("status", "file", "line", "severity", "author", "source")


# ---------------------------------------------------------------------------
# Round paths and numbering
# ---------------------------------------------------------------------------


def round_id(number: int) -> str:
    """``3`` -> ``"003"``. Rounds beyond 999 simply grow past three digits."""

    return "{0:03d}".format(int(number))


def validate_round(number: Any) -> int:
    """Return ``number`` as a positive round number, or raise :class:`QaError`."""

    try:
        value = int(number)
    except (TypeError, ValueError):
        raise common.QaError(
            "round must be a positive integer, got {0!r}".format(number), common.USAGE
        )
    if value < 1:
        raise common.QaError(
            "round must be a positive integer, got {0}".format(value), common.USAGE
        )
    return value


def round_dir(ctx: "common.Context", number: Any) -> pathlib.Path:
    """Absolute path of round ``number``. Does not create anything."""

    path = ctx.rounds_dir() / round_id(validate_round(number))
    return common.ensure_within(ctx.qa_dir, path)


def list_rounds(ctx: "common.Context") -> List[int]:
    """Every existing round number, ascending."""

    rounds_dir = ctx.rounds_dir()
    if not rounds_dir.is_dir():
        return []
    numbers = []
    try:
        entries = sorted(os.listdir(str(rounds_dir)))
    except OSError as exc:
        raise common.QaError("cannot list {0}: {1}".format(rounds_dir, exc))
    for name in entries:
        if not _ROUND_NAME_RE.match(name):
            continue
        if not (rounds_dir / name).is_dir():
            continue
        value = int(name)
        if value >= 1:
            numbers.append(value)
    return sorted(set(numbers))


def current_round(ctx: "common.Context") -> int:
    """Highest existing round number, or ``0`` when the repo has no rounds yet."""

    numbers = list_rounds(ctx)
    return numbers[-1] if numbers else 0


def is_sealed(ctx: "common.Context", number: Any) -> bool:
    """A round is sealed exactly when its ``summary.json`` exists."""

    return (round_dir(ctx, number) / SUMMARY_JSON).is_file()


def ensure_unsealed(ctx: "common.Context", number: Any) -> pathlib.Path:
    """Return the round directory, refusing (exit 6) when the round is sealed."""

    value = validate_round(number)
    directory = round_dir(ctx, value)
    if (directory / SUMMARY_JSON).is_file():
        raise common.QaError(
            "round {0} is sealed ({1} exists); rounds are never edited or deleted -- "
            "allocate the next one with `qa.py round new`".format(
                round_id(value), ctx.rel(directory / SUMMARY_JSON)
            ),
            common.SEALED_ROUND,
        )
    return directory


def new_round(ctx: "common.Context") -> Dict[str, Any]:
    """Allocate ``max(existing) + 1`` and create its directory."""

    number = current_round(ctx) + 1
    directory = round_dir(ctx, number)
    try:
        directory.mkdir(parents=True, exist_ok=False)
    except FileExistsError:  # pragma: no cover - defensive, numbering is exclusive
        raise common.QaError(
            "round {0} already exists at {1}".format(round_id(number), ctx.rel(directory))
        )
    except OSError as exc:
        raise common.QaError("cannot create {0}: {1}".format(directory, exc))
    return {
        "schemaVersion": common.SCHEMA_VERSION,
        "round": number,
        "id": round_id(number),
        "dir": ctx.rel(directory),
        "sealed": False,
    }


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def runs_dir(ctx: "common.Context", number: Any) -> pathlib.Path:
    """``qa/rounds/NNN/runs``. Does not create anything."""

    return common.ensure_within(ctx.qa_dir, round_dir(ctx, number) / RUNS_DIRNAME)


def _run_sort_key(run_id: str) -> Tuple[str, int]:
    """Sort ``20260725-140233-10`` after ``20260725-140233-2``, not before it."""

    parts = run_id.split("-")
    if len(parts) >= 3 and parts[-1].isdigit() and len(parts[-1]) <= 6:
        return ("-".join(parts[:-1]), int(parts[-1]))
    return (run_id, 1)


def list_runs(ctx: "common.Context", number: Any) -> List[str]:
    """Run ids inside a round, oldest first."""

    directory = runs_dir(ctx, number)
    if not directory.is_dir():
        return []
    try:
        names = [n for n in os.listdir(str(directory)) if (directory / n).is_dir()]
    except OSError as exc:
        raise common.QaError("cannot list {0}: {1}".format(directory, exc))
    return sorted(names, key=_run_sort_key)


def latest_run(ctx: "common.Context", number: Any) -> Optional[str]:
    """Most recent run id in a round, or ``None`` when it has no runs."""

    runs = list_runs(ctx, number)
    return runs[-1] if runs else None


def new_run_dir(
    ctx: "common.Context", number: Any, run_id: Optional[str] = None
) -> pathlib.Path:
    """Create and return ``qa/rounds/NNN/runs/<runId>``.

    ``run_id`` defaults to the UTC ``%Y%m%d-%H%M%S`` stamp. A second run inside the same
    second gets ``-2``, ``-3`` ... appended so a fast re-run never collides. Mutating a
    sealed round raises :class:`QaError` with ``SEALED_ROUND``.
    """

    value = validate_round(number)
    directory = ensure_unsealed(ctx, value)
    if not directory.is_dir():
        raise common.QaError(
            "round {0} does not exist ({1}); allocate it with `qa.py round new`".format(
                round_id(value), ctx.rel(directory)
            ),
            common.USAGE,
        )

    base = str(run_id).strip() if run_id else common.run_id_now()
    if not _RUN_ID_RE.match(base):
        raise common.QaError(
            "invalid run id {0!r}: use letters, digits, dot, dash or underscore".format(base),
            common.USAGE,
        )

    parent = runs_dir(ctx, value)
    candidate = base
    suffix = 1
    while True:
        target = common.ensure_within(ctx.qa_dir, parent / candidate)
        if not target.exists():
            break
        suffix += 1
        if suffix > _MAX_RUN_COLLISIONS:
            raise common.QaError(
                "cannot allocate a run directory for round {0}: {1} collisions on {2}".format(
                    round_id(value), _MAX_RUN_COLLISIONS, base
                )
            )
        candidate = "{0}-{1}".format(base, suffix)

    try:
        target.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise common.QaError("cannot create {0}: {1}".format(target, exc))
    return target


# ---------------------------------------------------------------------------
# Issues
# ---------------------------------------------------------------------------


def list_issue_numbers(ctx: "common.Context", number: Any) -> List[int]:
    """Issue numbers present in a round, ascending."""

    directory = round_dir(ctx, number)
    if not directory.is_dir():
        return []
    try:
        names = os.listdir(str(directory))
    except OSError as exc:
        raise common.QaError("cannot list {0}: {1}".format(directory, exc))
    numbers = []
    for name in names:
        match = _ISSUE_NAME_RE.match(name)
        if match and (directory / name).is_file():
            numbers.append(int(match.group(1)))
    return sorted(set(numbers))


def next_issue_number(ctx: "common.Context", number: Any) -> int:
    """Highest existing issue number in the round plus one; ``1`` when there is none."""

    numbers = list_issue_numbers(ctx, number)
    return (numbers[-1] + 1) if numbers else 1


def _unescape_double_quoted(inner: str) -> str:
    """Reverse :func:`qa_common.yaml_scalar`'s double-quoted escaping."""

    simple = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"'}
    out: List[str] = []
    index = 0
    length = len(inner)
    while index < length:
        char = inner[index]
        if char != "\\" or index + 1 >= length:
            out.append(char)
            index += 1
            continue
        nxt = inner[index + 1]
        if nxt == "x" and index + 3 < length:
            hex_digits = inner[index + 2 : index + 4]
            try:
                out.append(chr(int(hex_digits, 16)))
                index += 4
                continue
            except ValueError:
                pass
        out.append(simple.get(nxt, nxt))
        index += 2
    return "".join(out)


def _unquote(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        inner = text[1:-1]
        if text[0] == '"':
            return _unescape_double_quoted(inner)
        return inner.replace("''", "'")
    return text


def parse_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    """Split ``---`` frontmatter from the body. Only ``key: value`` lines are read."""

    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    fields: Dict[str, str] = {}
    for index in range(1, len(lines)):
        line = lines[index]
        if line.strip() == "---":
            return fields, "\n".join(lines[index + 1 :])
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        fields[key.strip()] = _unquote(value)
    return fields, ""


def _issue_title(body: str) -> str:
    for line in body.split("\n"):
        match = _HEADING_RE.match(line)
        if match:
            return match.group(1)
    return ""


def _read_text(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise common.QaError("cannot read {0}: {1}".format(path, exc))


def issue_info(ctx: "common.Context", number: Any, issue_number: int) -> Dict[str, Any]:
    """Frontmatter and title of one ``issue_NNN.md``."""

    identifier = "issue_{0:03d}".format(int(issue_number))
    path = common.ensure_within(
        ctx.qa_dir, round_dir(ctx, number) / "{0}.md".format(identifier)
    )
    fields, body = parse_frontmatter(_read_text(path))
    try:
        line = int(str(fields.get("line", "0")).strip() or 0)
    except ValueError:
        line = 0
    return {
        "id": identifier,
        "path": ctx.rel(path),
        "status": fields.get("status", ""),
        "file": fields.get("file", ""),
        "line": line,
        "severity": fields.get("severity", ""),
        "author": fields.get("author", ""),
        "source": fields.get("source", ""),
        "title": _issue_title(body),
    }


# ---------------------------------------------------------------------------
# Round inspection
# ---------------------------------------------------------------------------


def _run_info(ctx: "common.Context", number: Any, run: str) -> Dict[str, Any]:
    directory = common.ensure_within(ctx.qa_dir, runs_dir(ctx, number) / run)
    run_json = directory / RUN_JSON
    info: Dict[str, Any] = {
        "runId": run,
        "dir": ctx.rel(directory),
        "hasRunJson": run_json.is_file(),
        "startedAt": None,
        "finishedAt": None,
        "verdict": None,
        "complete": None,
        "layers": [],
    }
    if not info["hasRunJson"]:
        return info
    try:
        payload = common.read_json(run_json, default=None)
    except common.QaError:
        # A truncated run.json must not make `round show` unusable.
        info["hasRunJson"] = False
        return info
    if not isinstance(payload, dict):
        info["hasRunJson"] = False
        return info
    info["startedAt"] = payload.get("startedAt")
    info["finishedAt"] = payload.get("finishedAt")
    info["verdict"] = payload.get("verdict")
    info["complete"] = payload.get("complete")
    layers = payload.get("layers")
    if isinstance(layers, list):
        info["layers"] = [
            {
                "layer": entry.get("layer"),
                "status": entry.get("status"),
                "exitCode": entry.get("exitCode"),
            }
            for entry in layers
            if isinstance(entry, dict)
        ]
    return info


def round_info(ctx: "common.Context", number: Any) -> Dict[str, Any]:
    """Everything ``round show`` reports: artifacts, runs, and issues."""

    value = validate_round(number)
    directory = round_dir(ctx, value)
    runs = list_runs(ctx, value) if directory.is_dir() else []
    issues = [issue_info(ctx, value, n) for n in list_issue_numbers(ctx, value)]
    return {
        "schemaVersion": common.SCHEMA_VERSION,
        "round": value,
        "id": round_id(value),
        "dir": ctx.rel(directory),
        "exists": directory.is_dir(),
        "sealed": (directory / SUMMARY_JSON).is_file(),
        "artifacts": {
            "plan.md": (directory / PLAN_MD).is_file(),
            "plan.json": (directory / PLAN_JSON).is_file(),
            "summary.md": (directory / SUMMARY_MD).is_file(),
            "summary.json": (directory / SUMMARY_JSON).is_file(),
        },
        "latestRun": runs[-1] if runs else None,
        "runs": [_run_info(ctx, value, run) for run in runs],
        "issues": issues,
        "nextIssue": next_issue_number(ctx, value),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def add_arguments(parser: Any) -> None:
    """Declare ``round``'s own flags. Global flags are added by ``qa.py``."""

    parser.add_argument(
        "action",
        choices=list(ACTIONS),
        help="new: allocate the next round. current: highest round. "
        "show: round metadata, runs and issues. seal: verify immutability.",
    )
    parser.add_argument(
        "--round",
        metavar="N",
        default=None,
        help="Round number. Defaults to the current round for show and seal.",
    )


def _resolve_target_round(ctx: "common.Context", args: Any, action: str) -> int:
    raw = getattr(args, "round", None)
    if raw is not None and str(raw).strip() != "":
        return validate_round(raw)
    number = current_round(ctx)
    if number < 1:
        raise common.QaError(
            "no round exists yet; run `qa.py round new` before `round {0}`".format(action),
            common.USAGE,
        )
    return number


def run(args: Any, ctx: "common.Context") -> int:
    """Dispatch ``new`` / ``current`` / ``show`` / ``seal``."""

    action = getattr(args, "action", None)
    if action not in ACTIONS:
        raise common.QaError(
            "unknown round action {0!r}; expected one of {1}".format(
                action, ", ".join(ACTIONS)
            ),
            common.USAGE,
        )

    if action == "new":
        document = new_round(ctx)
        ctx.emit(document)
        ctx.note("allocated round {0} at {1}".format(document["id"], document["dir"]))
        return common.OK

    if action == "current":
        number = current_round(ctx)
        if number < 1:
            ctx.emit(
                {
                    "schemaVersion": common.SCHEMA_VERSION,
                    "round": 0,
                    "id": None,
                    "dir": None,
                    "sealed": False,
                }
            )
            ctx.note("no round exists yet; run `qa.py round new`")
            return common.OK
        directory = round_dir(ctx, number)
        ctx.emit(
            {
                "schemaVersion": common.SCHEMA_VERSION,
                "round": number,
                "id": round_id(number),
                "dir": ctx.rel(directory),
                "sealed": is_sealed(ctx, number),
            }
        )
        return common.OK

    number = _resolve_target_round(ctx, args, action)
    directory = round_dir(ctx, number)

    if action == "show":
        if not directory.is_dir():
            raise common.QaError(
                "round {0} does not exist ({1})".format(round_id(number), ctx.rel(directory)),
                common.USAGE,
            )
        document = round_info(ctx, number)
        ctx.emit(document)
        ctx.note(
            "round {0}: {1} run(s), {2} issue(s), sealed={3}".format(
                document["id"],
                len(document["runs"]),
                len(document["issues"]),
                "yes" if document["sealed"] else "no",
            )
        )
        return common.OK

    # action == "seal"
    if not directory.is_dir():
        raise common.QaError(
            "round {0} does not exist ({1})".format(round_id(number), ctx.rel(directory)),
            common.USAGE,
        )
    summary = directory / SUMMARY_JSON
    sealed = summary.is_file()
    document = {
        "schemaVersion": common.SCHEMA_VERSION,
        "round": number,
        "id": round_id(number),
        "dir": ctx.rel(directory),
        "sealed": sealed,
        "seal": ctx.rel(summary),
        "message": (
            "round {0} is sealed; rounds are never edited or deleted -- allocate the next "
            "one with `qa.py round new`".format(round_id(number))
            if sealed
            else "round {0} has no {1}; run `qa.py report --round {2}` first -- sealing is "
            "the presence of summary.json and `seal` never writes it".format(
                round_id(number), SUMMARY_JSON, number
            )
        ),
    }
    ctx.emit(document)
    ctx.note(document["message"])
    return common.SEALED_ROUND if sealed else common.USAGE


__all__ = [
    "COMMAND",
    "HELP",
    "ACTIONS",
    "FRONTMATTER_KEYS",
    "add_arguments",
    "current_round",
    "ensure_unsealed",
    "is_sealed",
    "issue_info",
    "latest_run",
    "list_issue_numbers",
    "list_rounds",
    "list_runs",
    "new_round",
    "new_run_dir",
    "next_issue_number",
    "parse_frontmatter",
    "round_dir",
    "round_id",
    "round_info",
    "run",
    "runs_dir",
    "validate_round",
]
