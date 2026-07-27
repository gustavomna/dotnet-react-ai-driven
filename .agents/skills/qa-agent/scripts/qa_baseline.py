"""Baseline handling: fingerprinting, partitioning, and the ``baseline`` command.

A baseline records the violations a repository already had before the QA Agent
arrived. Findings whose fingerprint is in the baseline are *pre-existing*: they
are reported as informational ``low`` issues and never block. Everything else is
*introduced* and gates normally.

Fingerprints are deliberately line-number-free so they survive line moves.
"""

import argparse
import os
import pathlib
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from . import qa_common as common
    from . import qa_axe
except ImportError:  # pragma: no cover - direct script execution
    import qa_common as common
    import qa_axe

COMMAND = "baseline"
HELP = "Create, compare, regenerate, or show the committed QA baseline."

BASELINE_FILENAME = "baseline.json"

_RUN_ID_RE = re.compile(r"^[0-9A-Za-z._-]+$")
_WS_RE = re.compile(r"\s+")


# --------------------------------------------------------------------------
# Paths and safety
# --------------------------------------------------------------------------


def baseline_path(ctx: "common.Context") -> pathlib.Path:
    """Absolute path of the committed baseline document."""
    return pathlib.Path(ctx.qa_dir) / BASELINE_FILENAME


def _ensure_writable(ctx: "common.Context", path: pathlib.Path) -> pathlib.Path:
    """Refuse any write that escapes both the repo root and the QA directory."""
    return common.ensure_writable(ctx, path)


def _rounds_dir(ctx: "common.Context") -> pathlib.Path:
    return pathlib.Path(ctx.qa_dir) / "rounds"


def _run_json_path(ctx: "common.Context", round_no: int, run_id: str) -> pathlib.Path:
    return _rounds_dir(ctx) / ("%03d" % round_no) / "runs" / run_id / "run.json"


def parse_run_spec(spec: str) -> Tuple[int, str]:
    """Parse ``<round>/<runId>`` (a trailing ``run.json`` is tolerated)."""
    parts = [p for p in str(spec).replace("\\", "/").split("/") if p and p != "."]
    if parts and parts[-1] == "run.json":
        parts = parts[:-1]
    if len(parts) >= 2 and parts[-2] == "runs":
        parts = parts[:-2] + parts[-1:]
    if len(parts) < 2:
        raise common.QaError(
            "run reference must be <round>/<runId>, for example 001/20260725-140233",
            common.USAGE,
        )
    round_part, run_id = parts[-2], parts[-1]
    if not round_part.isdigit():
        raise common.QaError(
            "run reference must start with a numeric round: %s" % spec, common.USAGE
        )
    if not _RUN_ID_RE.match(run_id):
        raise common.QaError("unsafe run id: %s" % run_id, common.USAGE)
    return int(round_part, 10), run_id


def latest_run_spec(ctx: "common.Context") -> Optional[Tuple[int, str]]:
    """Highest round that has a run, and its most recent run id."""
    rounds_dir = _rounds_dir(ctx)
    if not rounds_dir.is_dir():
        return None
    best: Optional[Tuple[int, str]] = None
    for round_dir in sorted(rounds_dir.iterdir()):
        if not round_dir.is_dir() or not round_dir.name.isdigit():
            continue
        runs_dir = round_dir / "runs"
        if not runs_dir.is_dir():
            continue
        run_ids = sorted(
            d.name for d in runs_dir.iterdir() if d.is_dir() and (d / "run.json").is_file()
        )
        if not run_ids:
            continue
        best = (int(round_dir.name, 10), run_ids[-1])
    return best


def load_run(ctx: "common.Context", round_no: int, run_id: str) -> Dict[str, Any]:
    """Read one ``run.json``; raise a usage error when it is missing."""
    path = _run_json_path(ctx, round_no, run_id)
    doc = common.read_json(path, None)
    if not isinstance(doc, dict):
        raise common.QaError("no run document at %s" % ctx.rel(path), common.USAGE)
    return doc


# --------------------------------------------------------------------------
# Findings extraction (shared with qa_findings so both read run.json the same way)
# --------------------------------------------------------------------------


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _finding_from_failure(
    failure: Dict[str, Any], layer: str, reproduce: Optional[str], flaky: bool
) -> Dict[str, Any]:
    is_flaky = bool(flaky or failure.get("flaky"))
    message = common.redact(str(failure.get("message") or ""))
    name = (
        failure.get("name")
        or failure.get("testId")
        or failure.get("rule")
        or (message.splitlines()[0] if message else "")
        or "Unnamed failure"
    )
    stated = failure.get("statedCriterion")
    if stated is None:
        stated = bool(failure.get("requirementRef"))
    return {
        "source": "flake" if is_flaky else layer,
        "layer": layer,
        "rule": failure.get("rule"),
        "testId": failure.get("testId"),
        "name": common.redact(str(name)),
        "file": str(failure.get("file") or ""),
        "line": _as_int(failure.get("line")),
        "target": failure.get("target") or failure.get("testId"),
        "impact": failure.get("impact"),
        "assertion": common.redact(str(failure["assertion"]))
        if failure.get("assertion")
        else None,
        "message": message,
        "expected": common.redact(str(failure["expected"]))
        if failure.get("expected") is not None
        else None,
        "actual": common.redact(str(failure["actual"]))
        if failure.get("actual") is not None
        else None,
        "requirementRef": failure.get("requirementRef"),
        "statedCriterion": bool(stated),
        "flaky": is_flaky,
        "helpUrl": failure.get("helpUrl"),
        "reproduce": failure.get("reproduce") or reproduce,
        "suggestedFix": failure.get("suggestedFix"),
        "severity": failure.get("severity"),
    }


def findings_from_run(run: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten a ``run.json`` document into normalized findings.

    Every ``failures[]`` entry becomes a finding on its own layer; every
    ``flakes[]`` entry becomes a ``flake``-sourced finding. One failure, one
    finding -- unrelated problems are never merged.
    """
    findings: List[Dict[str, Any]] = []
    for layer in run.get("layers") or []:
        if not isinstance(layer, dict):
            continue
        name = str(layer.get("layer") or "unit")
        reproduce = layer.get("reproduce")
        for failure in layer.get("failures") or []:
            if isinstance(failure, dict):
                findings.append(_finding_from_failure(failure, name, reproduce, False))
        for flake in layer.get("flakes") or []:
            if isinstance(flake, dict):
                findings.append(_finding_from_failure(flake, name, reproduce, True))
    return findings


# --------------------------------------------------------------------------
# Fingerprints
# --------------------------------------------------------------------------


def normalize_file(value: Any) -> str:
    """Repo-relative POSIX form, as far as a pure string transform can go."""
    text = str(value or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    while "//" in text:
        text = text.replace("//", "/")
    return text


def normalize_target(finding: Dict[str, Any]) -> str:
    """The axe target selector or the test id, whitespace-normalized."""
    raw = finding.get("target") or finding.get("testId") or ""
    return _WS_RE.sub(" ", str(raw)).strip()


def fingerprint(finding: Dict[str, Any]) -> str:
    """Stable, line-number-free identity of a finding."""
    return common.sha256_fp(
        str(finding.get("source") or ""),
        str(finding.get("rule") or ""),
        normalize_file(finding.get("file")),
        normalize_target(finding),
    )


def entry_for(finding: Dict[str, Any]) -> Dict[str, Any]:
    """Baseline record for one finding."""
    severity = finding.get("severity")
    if not severity:
        severity = qa_axe.impact_to_severity(finding.get("impact"))
    return {
        "fp": fingerprint(finding),
        "source": str(finding.get("source") or ""),
        "rule": finding.get("rule"),
        "file": normalize_file(finding.get("file")),
        "target": normalize_target(finding) or None,
        "severity": str(severity),
    }


def empty_baseline() -> Dict[str, Any]:
    """The document shape used when no baseline has been committed yet."""
    return {
        "schemaVersion": common.SCHEMA_VERSION,
        "generatedAt": None,
        "generatedBy": None,
        "reason": None,
        "history": [],
        "fingerprints": [],
    }


def load_baseline(ctx: "common.Context") -> Dict[str, Any]:
    """Read ``qa/baseline.json``; a missing file yields an empty baseline."""
    doc = common.read_json(baseline_path(ctx), None)
    if not isinstance(doc, dict):
        return empty_baseline()
    base = empty_baseline()
    base.update(doc)
    if not isinstance(base.get("fingerprints"), list):
        base["fingerprints"] = []
    if not isinstance(base.get("history"), list):
        base["history"] = []
    return base


def partition(
    findings: Sequence[Dict[str, Any]], baseline: Optional[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split findings into ``(preexisting, introduced)``.

    Each finding is annotated in place with its ``fp`` so callers can report it.
    """
    known = set()
    for entry in (baseline or {}).get("fingerprints") or []:
        if isinstance(entry, dict) and entry.get("fp"):
            known.add(str(entry["fp"]))
        elif isinstance(entry, str):
            known.add(entry)
    preexisting: List[Dict[str, Any]] = []
    introduced: List[Dict[str, Any]] = []
    for finding in findings:
        fp = finding.get("fp") or fingerprint(finding)
        finding["fp"] = fp
        if fp in known:
            preexisting.append(finding)
        else:
            introduced.append(finding)
    return preexisting, introduced


def build_document(
    findings: Sequence[Dict[str, Any]],
    *,
    reason: str,
    by: str,
    history: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Assemble a baseline document from findings, deduplicated and sorted.

    Findings that cannot identify themselves are refused: a fingerprint built
    from an empty rule AND an empty target collides with every other such
    finding in the same layer, so baselining one would silently mask every
    future unrelated failure there. Those are reported under ``skipped`` and
    never gate anything.
    """
    entries: Dict[str, Dict[str, Any]] = {}
    skipped: List[Dict[str, Any]] = []
    for finding in findings:
        entry = entry_for(finding)
        if not identifiable(finding):
            skipped.append(
                {
                    "source": entry["source"],
                    "file": entry["file"],
                    "reason": "no rule and no target: the fingerprint cannot identify "
                    "this violation, so it would match unrelated future failures",
                }
            )
            continue
        entries.setdefault(entry["fp"], entry)
    document = {
        "schemaVersion": common.SCHEMA_VERSION,
        "generatedAt": common.utc_now_iso(),
        "generatedBy": by,
        "reason": reason,
        "history": list(history or []),
        "fingerprints": [entries[fp] for fp in sorted(entries)],
    }
    if skipped:
        # Trailing, additive: the contract's documented keys keep their order.
        document["skipped"] = skipped
    return document


def identifiable(finding: Dict[str, Any]) -> bool:
    """Can this finding's fingerprint name a specific violation?"""
    return bool(
        str(finding.get("rule") or "").strip() or normalize_target(finding).strip()
    )


# --------------------------------------------------------------------------
# Command
# --------------------------------------------------------------------------


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Declare the ``baseline`` subcommand's own flags."""
    parser.add_argument(
        "action",
        choices=["create", "compare", "regenerate", "show"],
        help="baseline operation to perform",
    )
    parser.add_argument(
        "--from-run",
        dest="from_run",
        default=None,
        metavar="ROUND/RUNID",
        help="run to build the baseline from (create, regenerate)",
    )
    parser.add_argument(
        "--run",
        dest="run",
        default=None,
        metavar="ROUND/RUNID",
        help="run to compare against the baseline (compare)",
    )
    parser.add_argument(
        "--reason",
        dest="reason",
        default=None,
        help="why the baseline is being written; required for regenerate",
    )
    parser.add_argument(
        "--by",
        dest="by",
        default=None,
        help="who requested it (defaults to $USER, else qa-agent)",
    )


def _author(args: argparse.Namespace) -> str:
    return str(args.by or os.environ.get("USER") or "qa-agent")


def _resolve_source_run(
    ctx: "common.Context", args: argparse.Namespace, spec: Optional[str]
) -> Tuple[int, str]:
    if spec:
        return parse_run_spec(spec)
    latest = latest_run_spec(ctx)
    if latest is None:
        raise common.QaError(
            "no run found under %s; run `qa.py exec` first" % ctx.rel(_rounds_dir(ctx)),
            common.USAGE,
        )
    return latest


def _write_baseline(ctx: "common.Context", document: Dict[str, Any]) -> pathlib.Path:
    path = _ensure_writable(ctx, baseline_path(ctx))
    common.write_json(path, document)
    return path


def _create(ctx: "common.Context", args: argparse.Namespace) -> int:
    existing = common.read_json(baseline_path(ctx), None)
    if isinstance(existing, dict) and existing.get("fingerprints"):
        raise common.QaError(
            "%s already exists; use `baseline regenerate --reason TEXT` to replace it"
            % ctx.rel(baseline_path(ctx)),
            common.USAGE,
        )
    round_no, run_id = _resolve_source_run(ctx, args, args.from_run)
    findings = findings_from_run(load_run(ctx, round_no, run_id))
    document = build_document(
        findings, reason=str(args.reason or "initial adoption"), by=_author(args)
    )
    path = _write_baseline(ctx, document)
    ctx.emit(
        {
            "schemaVersion": common.SCHEMA_VERSION,
            "action": "create",
            "baseline": ctx.rel(path),
            "fromRun": "%03d/%s" % (round_no, run_id),
            "reason": document["reason"],
            "count": len(document["fingerprints"]),
        }
    )
    ctx.note(
        "[qa] baseline created with %d fingerprint(s) at %s"
        % (len(document["fingerprints"]), ctx.rel(path))
    )
    return common.OK


def _regenerate(ctx: "common.Context", args: argparse.Namespace) -> int:
    if not args.reason or not str(args.reason).strip():
        message = (
            "baseline regenerate requires --reason TEXT; a baseline is never "
            "regenerated automatically"
        )
        ctx.emit(
            {
                "schemaVersion": common.SCHEMA_VERSION,
                "action": "regenerate",
                "written": False,
                "error": message,
            }
        )
        ctx.progress("[qa] baseline regenerate refused: %s" % message)
        return common.USAGE
    previous = load_baseline(ctx)
    round_no, run_id = _resolve_source_run(ctx, args, args.from_run)
    findings = findings_from_run(load_run(ctx, round_no, run_id))
    history = list(previous.get("history") or [])
    history.append(
        {
            "at": common.utc_now_iso(),
            "reason": str(args.reason).strip(),
            "by": _author(args),
            "fromRun": "%03d/%s" % (round_no, run_id),
            "previousCount": len(previous.get("fingerprints") or []),
        }
    )
    document = build_document(
        findings, reason=str(args.reason).strip(), by=_author(args), history=history
    )
    path = _write_baseline(ctx, document)
    ctx.emit(
        {
            "schemaVersion": common.SCHEMA_VERSION,
            "action": "regenerate",
            "baseline": ctx.rel(path),
            "fromRun": "%03d/%s" % (round_no, run_id),
            "reason": document["reason"],
            "count": len(document["fingerprints"]),
            "previousCount": len(previous.get("fingerprints") or []),
            "history": len(history),
        }
    )
    ctx.note(
        "[qa] baseline regenerated: %d -> %d fingerprint(s); reason recorded in history[]"
        % (len(previous.get("fingerprints") or []), len(document["fingerprints"]))
    )
    return common.OK


def _compare(ctx: "common.Context", args: argparse.Namespace) -> int:
    spec = args.run or args.from_run
    round_no, run_id = _resolve_source_run(ctx, args, spec)
    baseline = load_baseline(ctx)
    findings = findings_from_run(load_run(ctx, round_no, run_id))
    preexisting, introduced = partition(findings, baseline)
    ctx.emit(
        {
            "schemaVersion": common.SCHEMA_VERSION,
            "action": "compare",
            "run": "%03d/%s" % (round_no, run_id),
            "baselineUsed": bool(baseline.get("fingerprints")),
            "preexisting": sorted(f["fp"] for f in preexisting),
            "introduced": sorted(f["fp"] for f in introduced),
            "counts": {
                "preexisting": len(preexisting),
                "introduced": len(introduced),
                "total": len(findings),
            },
        }
    )
    ctx.note(
        "[qa] baseline compare: %d pre-existing, %d introduced"
        % (len(preexisting), len(introduced))
    )
    return common.OK


def _show(ctx: "common.Context", args: argparse.Namespace) -> int:
    baseline = load_baseline(ctx)
    document = dict(baseline)
    document["schemaVersion"] = common.SCHEMA_VERSION
    document["path"] = ctx.rel(baseline_path(ctx))
    document["exists"] = baseline_path(ctx).is_file()
    document["count"] = len(baseline.get("fingerprints") or [])
    ctx.emit(document)
    ctx.note(
        "[qa] baseline holds %d fingerprint(s), %d history entr(ies)"
        % (document["count"], len(baseline.get("history") or []))
    )
    return common.OK


def run(args: argparse.Namespace, ctx: "common.Context") -> int:
    """Dispatch the ``baseline`` subcommand."""
    action = getattr(args, "action", None)
    if action == "create":
        return _create(ctx, args)
    if action == "regenerate":
        return _regenerate(ctx, args)
    if action == "compare":
        return _compare(ctx, args)
    if action == "show":
        return _show(ctx, args)
    raise common.QaError("unknown baseline action: %s" % action, common.USAGE)
