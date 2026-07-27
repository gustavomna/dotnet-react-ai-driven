"""Findings emission: severity, issue files, run summary, and the round verdict.

One failure becomes one ``issue_NNN.md``. Unrelated problems are never merged.
A clean round writes no issue files and records a pass verdict. Every verdict is
written as the word ``PASS`` or ``FAIL`` -- never colour alone -- and a round that
skipped a layer reports ``PASS - INCOMPLETE (layer: skipped-unavailable)``.
"""

import argparse
import pathlib
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from . import qa_common as common
    from . import qa_axe
    from . import qa_baseline
    from . import qa_round
    from . import qa_suppress
except ImportError:  # pragma: no cover - direct script execution
    import qa_common as common
    import qa_axe
    import qa_baseline
    import qa_round
    import qa_suppress

DEFAULT_AUTHOR = "qa-agent"

#: Allowed ``source`` values in issue frontmatter.
ISSUE_SOURCES = ("unit", "integration", "e2e", "a11y", "flake", "plan")

#: Allowed ``status`` values in issue frontmatter.
ISSUE_STATUSES = ("open", "informational")

_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_SOURCE_RANK = {"unit": 0, "integration": 1, "e2e": 2, "a11y": 3, "flake": 4, "plan": 5}

_MAX_SUMMARY_ISSUES = 5
_RUN_ID_RE = re.compile(r"^[0-9A-Za-z._-]+$")

A11Y_HONESTY_NOTE = (
    "Automated accessibility scanning catches roughly a third to a half of real "
    "issues. A clean a11y layer is evidence, not proof of conformance."
)


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_bool(value: Any) -> bool:
    """Config values arrive from JSON, so accept the string spellings too."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _one_line(value: Any) -> str:
    return " ".join(str(value or "").split())


def _cell(value: Any) -> str:
    """Escape a value so it cannot break out of a markdown table cell."""
    text = _one_line(value)
    return text.replace("|", "\\|")


def _fm(value: Any) -> str:
    """Render one frontmatter scalar, quoted whenever YAML would misparse it."""
    if isinstance(value, bool):
        return common.yaml_scalar(str(value).lower())
    if isinstance(value, int):
        return str(value)
    return common.yaml_scalar(str(value))


def _ensure_writable(ctx: "common.Context", path: pathlib.Path) -> pathlib.Path:
    """Refuse any write that escapes both the repo root and the QA directory."""
    return common.ensure_writable(ctx, path)


# --------------------------------------------------------------------------
# Severity
# --------------------------------------------------------------------------


def _worst(first: str, second: str) -> str:
    """Return the more severe of two severities."""
    if _SEVERITY_RANK.get(first, 9) <= _SEVERITY_RANK.get(second, 9):
        return first
    return second


def severity_for(
    source: str,
    *,
    impact: Optional[str] = None,
    flaky: bool = False,
    stated_criterion: bool = False,
    preexisting: bool = False,
) -> str:
    """Severity of one finding, per the contract's severity table.

    A baseline-matched finding is forced to ``low``. An accessibility violation
    inherits the axe impact mapping. A failing test of an explicit stated
    acceptance criterion is at minimum ``high``; a flaky test is at minimum
    ``medium`` and is never dismissed by a passing retry. Everything else starts
    at ``medium``.
    """
    if preexisting:
        return "low"
    layer = str(source or "").strip().lower()
    is_a11y = layer == "a11y" or impact is not None
    if is_a11y:
        severity = qa_axe.impact_to_severity(impact)
    else:
        severity = "medium"
        if stated_criterion:
            severity = _worst(severity, "high")
    if flaky or layer == "flake":
        severity = _worst(severity, "medium")
    return severity


def severity_of(finding: Dict[str, Any]) -> str:
    """Severity already carried by a finding, otherwise computed from it."""
    recorded = str(finding.get("severity") or "").strip().lower()
    if recorded in _SEVERITY_RANK:
        return recorded
    return severity_for(
        str(finding.get("source") or "unit"),
        impact=finding.get("impact"),
        flaky=bool(finding.get("flaky")),
        stated_criterion=bool(finding.get("statedCriterion")),
        preexisting=bool(finding.get("preexisting")),
    )


def _status_of(finding: Dict[str, Any]) -> str:
    if finding.get("preexisting"):
        return "informational"
    status = str(finding.get("status") or "open").strip().lower()
    return status if status in ISSUE_STATUSES else "open"


def _source_of(finding: Dict[str, Any]) -> str:
    source = str(finding.get("source") or "").strip().lower()
    return source if source in ISSUE_SOURCES else "plan"


# --------------------------------------------------------------------------
# Verdict
# --------------------------------------------------------------------------


def compute_verdict(
    layers: Sequence[Dict[str, Any]], config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Compute the round verdict from executed layers.

    ``pass`` iff every executed layer exited zero and no test is flaky. A layer
    reported ``skipped-unavailable`` never counts toward a pass: the verdict may
    stay ``pass`` but ``complete`` becomes ``false``, and ``gate.skippedLayers``
    set to ``"fail"`` promotes the skip to a failure.
    """
    gate = (config or {}).get("gate") or {}
    skipped_policy = str(gate.get("skippedLayers") or "warn").strip().lower()
    flaky_policy = str(gate.get("flaky") or "fail").strip().lower()

    reasons: List[str] = []
    skipped: List[Dict[str, Any]] = []
    failed = False

    for layer in layers or []:
        if not isinstance(layer, dict):
            continue
        name = str(layer.get("layer") or "unknown")
        status = str(layer.get("status") or "").strip().lower()
        exit_code = layer.get("exitCode")

        if status == "skipped-unavailable":
            skipped.append(
                {"layer": name, "reason": str(layer.get("reason") or "layer unavailable")}
            )
            continue

        if status == "failed" or (exit_code is not None and _as_int(exit_code) != 0):
            failed = True
            if layer.get("timedOut"):
                reasons.append(
                    "layer=%s timed out (exit %s)" % (name, exit_code if exit_code is not None else 124)
                )
            else:
                reasons.append(
                    "layer=%s exited %s with %d failure(s)"
                    % (name, exit_code, len(layer.get("failures") or []))
                )

        flakes = layer.get("flakes") or []
        if status == "flaky" or flakes:
            if flaky_policy == "fail":
                failed = True
                reasons.append(
                    "layer=%s reported %d flaky test(s); a flaky test is never a pass"
                    % (name, len(flakes))
                )
            else:
                reasons.append(
                    "layer=%s reported %d flaky test(s) (gate.flaky=%s)"
                    % (name, len(flakes), flaky_policy)
                )

    for entry in skipped:
        if skipped_policy == "fail":
            failed = True
            reasons.append(
                "layer=%s skipped-unavailable: %s (gate.skippedLayers=fail)"
                % (entry["layer"], entry["reason"])
            )
        else:
            reasons.append(
                "layer=%s skipped-unavailable: %s (round is incomplete)"
                % (entry["layer"], entry["reason"])
            )

    if not failed and not reasons:
        reasons.append("every executed layer exited zero and no test was flaky")

    return {
        "verdict": "fail" if failed else "pass",
        "complete": not skipped,
        "reasons": reasons,
        "skippedLayers": skipped,
    }


def verdict_line(verdict: Dict[str, Any]) -> str:
    """Screen-reader friendly verdict line; never colour-only."""
    word = "FAIL" if str(verdict.get("verdict")) == "fail" else "PASS"
    skipped = verdict.get("skippedLayers") or []
    if not skipped:
        return word
    detail = "; ".join("%s: skipped-unavailable" % entry["layer"] for entry in skipped)
    return "%s — INCOMPLETE (%s)" % (word, detail)


# --------------------------------------------------------------------------
# Issue rendering
# --------------------------------------------------------------------------


def _assertion_text(finding: Dict[str, Any]) -> str:
    assertion = _one_line(finding.get("assertion"))
    message = _one_line(finding.get("message"))
    rule = _one_line(finding.get("rule"))
    impact = _one_line(finding.get("impact"))
    if assertion and message:
        return "`%s` - %s" % (assertion, message)
    if assertion:
        return "`%s` did not hold." % assertion
    if rule:
        head = "Rule `%s`" % rule
        if impact:
            head = "%s (axe impact: %s)" % (head, impact)
        return "%s - %s" % (head, message or "violation reported by axe-core.")
    if message:
        return message
    if finding.get("flaky"):
        return "The test failed on the first attempt and passed on retry."
    return "The check failed without a captured assertion message; see the layer log."


def _expected_text(finding: Dict[str, Any]) -> str:
    expected = _one_line(finding.get("expected"))
    if expected:
        return expected
    rule = _one_line(finding.get("rule"))
    if rule:
        target = _one_line(finding.get("target")) or _one_line(finding.get("file"))
        return "No `%s` violation%s" % (rule, (" at `%s`" % target) if target else "")
    ref = _one_line(finding.get("requirementRef"))
    if ref:
        return "The behaviour stated by `%s` holds" % ref
    return "The check passes"


def _observed_text(finding: Dict[str, Any]) -> str:
    actual = _one_line(finding.get("actual"))
    if actual:
        return actual
    if finding.get("flaky"):
        return (
            "Failed, then passed on retry - the test is flaky and is never "
            "reported as passed"
        )
    message = _one_line(finding.get("message"))
    return message or "The check failed; see the layer log for raw output"


def _reproduce_text(finding: Dict[str, Any]) -> str:
    command = str(finding.get("reproduce") or "").strip()
    if command:
        return command
    return "# no reproducing command was recorded for this failure; see the layer log"


def _requirement_text(finding: Dict[str, Any]) -> str:
    ref = _one_line(finding.get("requirementRef"))
    if not ref:
        return (
            "No stated acceptance criterion. Expected behaviour was inferred from "
            "the change and its public interfaces."
        )
    parts = ["`%s`" % ref]
    doc = _one_line(finding.get("requirementDoc"))
    if doc:
        parts.append(doc)
    text = _one_line(finding.get("requirementText"))
    if text:
        parts.append('"%s"' % text)
    return " - ".join(parts)


def _fix_text(finding: Dict[str, Any]) -> str:
    suggested = str(finding.get("suggestedFix") or "").strip()
    if suggested:
        return suggested
    where = _one_line(finding.get("file"))
    line = _as_int(finding.get("line"))
    if where and line:
        anchor = "`%s:%d`" % (where, line)
    elif where:
        anchor = "`%s`" % where
    else:
        anchor = "the failing check"
    if finding.get("preexisting"):
        return (
            "Pre-existing per the committed baseline, so it does not block this "
            "round. Fix at %s when the surrounding code is next touched." % anchor
        )
    return (
        "Not determined automatically. Start at %s and work from the failing "
        "assertion above. Weakening the check - deleting or skipping the test, "
        "disabling the rule, widening the tolerance - is not an acceptable fix."
        % anchor
    )


def render_issue(number: int, finding: Dict[str, Any]) -> str:
    """Render one ``issue_NNN.md`` document."""
    ident = "issue_%03d" % _as_int(number)
    lines = [
        "---",
        "status: %s" % _fm(_status_of(finding)),
        "file: %s" % _fm(str(finding.get("file") or "")),
        "line: %s" % _fm(_as_int(finding.get("line"))),
        "severity: %s" % _fm(severity_of(finding)),
        "author: %s" % _fm(str(finding.get("author") or DEFAULT_AUTHOR)),
        "source: %s" % _fm(_source_of(finding)),
        "---",
        "",
        "# %s - %s" % (ident, _one_line(finding.get("name")) or "Unnamed failure"),
        "",
        "## Failing assertion",
        "",
        _assertion_text(finding),
    ]
    help_url = _one_line(finding.get("helpUrl"))
    if help_url:
        lines.extend(["", "Reference: %s" % help_url])
    lines.extend(
        [
            "",
            "## Observed vs expected",
            "",
            "| | |",
            "|---|---|",
            "| Expected | %s |" % _cell(_expected_text(finding)),
            "| Observed | %s |" % _cell(_observed_text(finding)),
            "",
            "## Reproduce",
            "",
            "```bash",
            _reproduce_text(finding),
            "```",
            "",
            "## Requirement",
            "",
            _requirement_text(finding),
            "",
            "## Suggested fix",
            "",
            _fix_text(finding),
        ]
    )
    return common.redact("\n".join(lines).rstrip() + "\n")


def write_issue(
    ctx: "common.Context", round_no: int, number: int, finding: Dict[str, Any]
) -> pathlib.Path:
    """Write one issue file into a round, refusing to touch a sealed round."""
    if qa_round.is_sealed(ctx, round_no):
        raise common.QaError(
            "round %03d is sealed; it is never edited" % round_no, common.SEALED_ROUND
        )
    path = _ensure_writable(
        ctx, pathlib.Path(qa_round.round_dir(ctx, round_no)) / ("issue_%03d.md" % _as_int(number))
    )
    common.atomic_write(path, render_issue(number, finding))
    return path


# --------------------------------------------------------------------------
# Report assembly
# --------------------------------------------------------------------------


def _sort_key(finding: Dict[str, Any]) -> Tuple[int, int, str, int, str]:
    return (
        _SEVERITY_RANK.get(severity_of(finding), 9),
        _SOURCE_RANK.get(_source_of(finding), 9),
        str(finding.get("file") or ""),
        _as_int(finding.get("line")),
        _one_line(finding.get("name")),
    )


def _counts(findings: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "total": 0}
    for finding in findings:
        severity = severity_of(finding)
        if severity in counts:
            counts[severity] += 1
        counts["total"] += 1
    return counts


def _apply_plan(findings: Sequence[Dict[str, Any]], plan: Optional[Dict[str, Any]]) -> None:
    """Attach requirement context and settle ``statedCriterion`` from the plan."""
    requirements: Dict[str, Dict[str, Any]] = {}
    inference_based = False
    if isinstance(plan, dict):
        inference_based = bool(plan.get("inferenceBased"))
        for requirement in plan.get("requirements") or []:
            if isinstance(requirement, dict) and requirement.get("ref"):
                requirements[str(requirement["ref"])] = requirement
    for finding in findings:
        ref = str(finding.get("requirementRef") or "")
        requirement = requirements.get(ref)
        if requirement:
            finding["requirementDoc"] = requirement.get("source")
            finding["requirementText"] = requirement.get("text")
        if inference_based:
            finding["statedCriterion"] = False
        elif requirement:
            finding["statedCriterion"] = True
        else:
            finding["statedCriterion"] = bool(finding.get("statedCriterion"))


def _manual_items(
    plan: Optional[Dict[str, Any]], run: Dict[str, Any]
) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    requirement_text: Dict[str, str] = {}
    if isinstance(plan, dict):
        for requirement in plan.get("requirements") or []:
            if isinstance(requirement, dict) and requirement.get("ref"):
                requirement_text[str(requirement["ref"])] = _one_line(requirement.get("text"))
        for check in plan.get("checks") or []:
            if not isinstance(check, dict) or str(check.get("status")) != "manual":
                continue
            ref = _one_line(check.get("requirementRef") or check.get("id") or "unspecified")
            label = _one_line(check.get("target")) or requirement_text.get(ref, "")
            items.append(
                {
                    "criterion": ("%s %s" % (ref, label)).strip(),
                    "reason": _one_line(check.get("manualReason"))
                    or "cannot be automated; needs human judgement",
                }
            )
    for layer in run.get("layers") or []:
        if not isinstance(layer, dict):
            continue
        for item in layer.get("manualItems") or []:
            if isinstance(item, dict) and item.get("criterion"):
                items.append(
                    {
                        "criterion": _one_line(item.get("criterion")),
                        "reason": _one_line(item.get("reason")) or "requires manual review",
                    }
                )
    unique: List[Dict[str, str]] = []
    seen = set()
    for item in items:
        key = (item["criterion"], item["reason"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    unique.sort(key=lambda entry: (entry["criterion"], entry["reason"]))
    return unique


def _coverage(
    plan: Optional[Dict[str, Any]], manual_items: Sequence[Dict[str, str]]
) -> Dict[str, int]:
    if not isinstance(plan, dict):
        return {
            "criteria": 0,
            "automated": 0,
            "manual": len(manual_items),
            "uncovered": 0,
        }
    refs = [
        str(r["ref"])
        for r in plan.get("requirements") or []
        if isinstance(r, dict) and r.get("ref")
    ]
    automated_refs = set()
    manual_refs = set()
    for check in plan.get("checks") or []:
        if not isinstance(check, dict):
            continue
        ref = str(check.get("requirementRef") or check.get("id") or "")
        if not ref:
            continue
        if str(check.get("status")) == "manual":
            manual_refs.add(ref)
        else:
            automated_refs.add(ref)
    manual_refs -= automated_refs
    if refs:
        known = set(refs)
        automated = len(known & automated_refs)
        manual = len(known & manual_refs)
        criteria = len(known)
        uncovered = max(0, criteria - automated - manual)
    else:
        automated = len(automated_refs)
        manual = len(manual_refs)
        criteria = automated + manual
        uncovered = 0
    return {
        "criteria": criteria,
        "automated": automated,
        "manual": manual,
        "uncovered": uncovered,
    }


def _layer_rows(run: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for layer in run.get("layers") or []:
        if not isinstance(layer, dict):
            continue
        rows.append(
            {
                "layer": str(layer.get("layer") or "unknown"),
                "status": str(layer.get("status") or "unknown"),
                "exitCode": layer.get("exitCode"),
                "reproduce": common.redact(str(layer.get("reproduce") or "")),
            }
        )
    return rows


def _relax_for_governed_findings(
    verdict: Dict[str, Any],
    run: Dict[str, Any],
    introduced: Sequence[Dict[str, Any]],
    preexisting: Sequence[Dict[str, Any]],
    suppressed: Sequence[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Downgrade a layer-level failure to a pass when nothing new was introduced.

    OFF BY DEFAULT. The PRD's verdict rule is absolute -- a round is ``pass``
    only when every executed layer exited zero and no test is flaky -- so the
    baseline rule is expressed in severity and status (``low`` +
    ``informational``, excluded from the blocking counts), not by flipping the
    round verdict. Teams that want a baseline-clean round to gate green opt in
    with ``gate.baselineOnly: true``; when they do, the summary records
    ``rawVerdict`` and ``verdictAdjusted`` so ``run.json`` and ``summary.json``
    can never silently disagree.

    Even when enabled this only applies where a committed baseline or a valid
    suppression accounts for every failure, only when every failing layer
    actually reported the failures it exited on, and never over a flaky or
    timed-out layer.
    """
    gate = (config or {}).get("gate") or {}
    if not _as_bool(gate.get("baselineOnly")):
        return verdict
    if str(verdict.get("verdict")) != "fail":
        return verdict
    if introduced or not (preexisting or suppressed):
        return verdict
    for layer in run.get("layers") or []:
        if not isinstance(layer, dict):
            continue
        status = str(layer.get("status") or "").strip().lower()
        exit_code = layer.get("exitCode")
        broken = status == "failed" or (exit_code is not None and _as_int(exit_code) != 0)
        if status == "flaky" or layer.get("flakes") or layer.get("timedOut"):
            return verdict
        if broken and not (layer.get("failures") or []):
            return verdict
    relaxed = dict(verdict)
    relaxed["verdict"] = "pass"
    relaxed["rawVerdict"] = str(verdict.get("verdict"))
    relaxed["adjusted"] = True
    relaxed["reasons"] = list(verdict.get("reasons") or []) + [
        "gate.baselineOnly=true: all %d failure(s) are pre-existing per the committed "
        "baseline (%d) or covered by a valid suppression (%d), so the round gates on "
        "introduced violations; the raw layer verdict was FAIL"
        % (len(preexisting) + len(suppressed), len(preexisting), len(suppressed))
    ]
    return relaxed


def _render_summary_md(document: Dict[str, Any], issues: Sequence[Dict[str, Any]]) -> str:
    counts = document["counts"]
    lines = [
        "# QA round %03d - summary" % document["round"],
        "",
        "**Verdict: %s**" % document["verdictLine"],
        "",
        "Run `%s` - generated %s - artifacts in `%s`"
        % (document["runId"], document["generatedAt"], document["roundDir"]),
        "",
        "## Findings by severity",
        "",
        "| severity | count |",
        "|---|---|",
        "| critical | %d |" % counts["critical"],
        "| high | %d |" % counts["high"],
        "| medium | %d |" % counts["medium"],
        "| low | %d |" % counts["low"],
        "| **total** | **%d** |" % counts["total"],
        "",
    ]

    lines.append("## Issues")
    lines.append("")
    if not issues:
        lines.append("No findings. Every executed check held.")
    else:
        for position, issue in enumerate(issues[:_MAX_SUMMARY_ISSUES], start=1):
            where = issue["file"] or "(no file)"
            if issue["line"]:
                where = "%s:%d" % (where, issue["line"])
            lines.append(
                "%d. `%s` - **%s** - %s - `%s` - %s"
                % (
                    position,
                    issue["id"],
                    issue["severity"],
                    issue["source"],
                    where,
                    issue["title"],
                )
            )
        remaining = len(issues) - _MAX_SUMMARY_ISSUES
        if remaining > 0:
            lines.append("")
            lines.append(
                "%d more finding(s) in `%s` (`issue_%03d.md` onward)."
                % (remaining, document["roundDir"], _as_int(issues[_MAX_SUMMARY_ISSUES]["id"][-3:]))
            )
    lines.append("")

    lines.extend(["## Why this verdict", ""])
    for reason in document["reasons"]:
        lines.append("- %s" % reason)
    lines.append("")

    lines.extend(
        ["## Layers", "", "| layer | status | exit | reproduce |", "|---|---|---|---|"]
    )
    for layer in document["layers"]:
        exit_code = "n/a" if layer["exitCode"] is None else str(layer["exitCode"])
        reproduce = "`%s`" % _cell(layer["reproduce"]) if layer["reproduce"] else "n/a"
        lines.append(
            "| %s | %s | %s | %s |"
            % (layer["layer"], layer["status"], exit_code, reproduce)
        )
    lines.append("")

    if document["skippedLayers"]:
        lines.extend(["## Skipped layers", ""])
        for entry in document["skippedLayers"]:
            lines.append(
                "- `%s` - skipped-unavailable - %s" % (entry["layer"], entry["reason"])
            )
        lines.append(
            "- A skipped layer never counts toward a pass; this round is incomplete."
        )
        lines.append("")

    if document["manualItems"]:
        lines.extend(["## Manual items", ""])
        for item in document["manualItems"]:
            lines.append("- %s - %s" % (item["criterion"], item["reason"]))
        lines.append("")

    coverage = document["coverage"]
    baseline = document["baseline"]
    suppressions = document["suppressions"]
    lines.extend(
        [
            "## Coverage, baseline, suppressions",
            "",
            "- Criteria: %d total, %d automated, %d manual, %d uncovered."
            % (
                coverage["criteria"],
                coverage["automated"],
                coverage["manual"],
                coverage["uncovered"],
            ),
            "- Baseline: %s (%d pre-existing, %d introduced)."
            % (
                "used" if baseline["used"] else "not used",
                baseline["preexisting"],
                baseline["introduced"],
            ),
            "- Suppressions: %d valid, %d invalid, %d expired. An invalid or expired "
            "suppression never silences a check."
            % (
                suppressions["valid"],
                suppressions["invalid"],
                suppressions["expired"],
            ),
            "",
            "## Notes",
            "",
            "- %s" % A11Y_HONESTY_NOTE,
            "- The only permitted response to a failure is an issue file. Deleting or "
            "skipping a test, disabling a rule, widening a tolerance, or broadening an "
            "exclusion is forbidden.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------


def add_report_args(parser: argparse.ArgumentParser) -> None:
    """Declare the ``report`` subcommand's own flags."""
    parser.add_argument("--round", dest="round", type=int, required=True, help="round number")
    parser.add_argument("--run", dest="run", default=None, help="run id (default: latest)")
    parser.add_argument("--plan", dest="plan", default=None, help="path to plan.json")
    parser.add_argument(
        "--author", dest="author", default=DEFAULT_AUTHOR, help="issue frontmatter author"
    )
    parser.add_argument(
        "--axe",
        dest="axe",
        action="append",
        default=None,
        metavar="FILE",
        help="axe-core JSON payload to ingest (repeatable); the a11y layer's own "
        "artifacts are picked up automatically",
    )
    parser.add_argument(
        "--no-baseline",
        dest="no_baseline",
        action="store_true",
        help="ignore the committed baseline for this report",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="compute the report without writing any file",
    )


def _resolve_run_id(ctx: "common.Context", round_no: int, requested: Optional[str]) -> str:
    if requested:
        run_id = str(requested).strip()
        if not _RUN_ID_RE.match(run_id):
            raise common.QaError("unsafe run id: %s" % requested, common.USAGE)
        return run_id
    latest = qa_round.latest_run(ctx, round_no)
    if not latest:
        raise common.QaError(
            "round %03d has no run; execute the layers first" % round_no, common.USAGE
        )
    return str(latest)


def _load_run(ctx: "common.Context", round_no: int, run_id: str) -> Dict[str, Any]:
    path = pathlib.Path(qa_round.round_dir(ctx, round_no)) / "runs" / run_id / "run.json"
    document = common.read_json(path, None)
    if not isinstance(document, dict):
        raise common.QaError("no run document at %s" % ctx.rel(path), common.USAGE)
    return document


def _load_plan(
    ctx: "common.Context", args: argparse.Namespace, round_dir: pathlib.Path
) -> Optional[Dict[str, Any]]:
    path = pathlib.Path(args.plan) if args.plan else round_dir / "plan.json"
    if not path.is_absolute():
        path = pathlib.Path(ctx.repo) / path
    document = common.read_json(path, None)
    return document if isinstance(document, dict) else None


def _axe_payload_paths(
    ctx: "common.Context", args: argparse.Namespace, run: Dict[str, Any]
) -> List[pathlib.Path]:
    """Explicit --axe files first, then whatever the a11y layer left behind."""
    candidates: List[str] = [str(item) for item in (getattr(args, "axe", None) or [])]
    for layer in run.get("layers") or []:
        if isinstance(layer, dict) and str(layer.get("layer")) == "a11y":
            candidates.extend(str(item) for item in (layer.get("axeArtifacts") or []))

    paths: List[pathlib.Path] = []
    seen = set()
    for raw in candidates:
        path = pathlib.Path(raw)
        if not path.is_absolute():
            path = pathlib.Path(ctx.repo) / path
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            paths.append(path)
        elif raw in (getattr(args, "axe", None) or []):
            raise common.QaError("no axe payload at %s" % ctx.rel(path), common.USAGE)
    return paths


def _ingest_axe(
    ctx: "common.Context",
    args: argparse.Namespace,
    run: Dict[str, Any],
    findings: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Fold raw axe payloads into the findings and the run's manual items.

    Without this the axe impact -> severity mapping is unreachable: an axe
    ``critical`` would be filed as a coarse ``medium`` runner failure carrying
    no rule and no help URL, and ``incomplete[]`` could never surface as a
    manual item.
    """
    paths = _axe_payload_paths(ctx, args, run)
    if not paths:
        return findings

    fail_on_incomplete = bool((ctx.config.get("a11y") or {}).get("failOnIncomplete"))
    axe_findings: List[Dict[str, Any]] = []
    manual: List[Dict[str, Any]] = []
    for path in paths:
        payload = common.read_json(path, None)
        if payload is None:
            ctx.note("[qa] skipping unreadable axe payload %s" % ctx.rel(path))
            continue
        route = None
        component = None
        if isinstance(payload, dict):
            route = payload.get("url") or payload.get("route")
            # Component scans (jest-axe / vitest-axe) carry no url, so without a
            # component every finding would land with an empty `file:`. Prefer
            # what the payload declares; fall back to the artifact's own path so
            # the issue always points at something real.
            component = (
                payload.get("component")
                or payload.get("testFile")
                or payload.get("sourceFile")
                or payload.get("file")
            )
        if not route and not component:
            component = ctx.rel(path)
        axe_findings.extend(
            qa_axe.normalize_axe_results(payload, route=route, component=component)
        )
        items = qa_axe.collect_incomplete(
            payload,
            route=route,
            component=component,
            fail_on_incomplete=fail_on_incomplete,
        )
        if fail_on_incomplete:
            axe_findings.extend(items)
        else:
            manual.extend(items)

    if manual:
        for layer in run.get("layers") or []:
            if isinstance(layer, dict) and str(layer.get("layer")) == "a11y":
                existing = list(layer.get("manualItems") or [])
                layer["manualItems"] = existing + [
                    {
                        "criterion": _one_line(item.get("name") or item.get("rule"))
                        or "axe incomplete result",
                        "reason": _one_line(item.get("message"))
                        or "axe could not decide this rule; a human must check it",
                    }
                    for item in manual
                ]
                break

    if not axe_findings:
        return findings

    # The axe findings supersede the coarse "a11y layer exited N" record: same
    # failure, named rule, real impact. Keep every non-a11y finding untouched.
    kept = [
        item
        for item in findings
        if str(item.get("source")) != "a11y" or str(item.get("rule") or "").strip()
    ]
    ctx.note(
        "[qa] ingested %d axe violation(s) from %d payload(s)"
        % (len(axe_findings), len(paths))
    )
    return kept + axe_findings


def run_report(args: argparse.Namespace, ctx: "common.Context") -> int:
    """Turn the latest run of a round into issue files, a summary, and a verdict."""
    round_no = _as_int(args.round)
    round_dir = pathlib.Path(qa_round.round_dir(ctx, round_no))
    if not round_dir.is_dir():
        raise common.QaError(
            "round %03d does not exist under %s" % (round_no, ctx.rel(ctx.qa_dir)),
            common.USAGE,
        )
    summary_json = round_dir / "summary.json"
    if summary_json.exists() and not args.dry_run:
        raise common.QaError(
            "round %03d is already sealed (%s exists); re-running QA allocates the "
            "next round" % (round_no, ctx.rel(summary_json)),
            common.SEALED_ROUND,
        )
    if summary_json.exists():
        ctx.note("[qa] round %03d is sealed; dry run writes nothing" % round_no)

    run_id = _resolve_run_id(ctx, round_no, args.run)
    run_document = _load_run(ctx, round_no, run_id)
    plan = _load_plan(ctx, args, round_dir)

    findings = qa_baseline.findings_from_run(run_document)
    findings = _ingest_axe(ctx, args, run_document, findings)
    _apply_plan(findings, plan)
    for finding in findings:
        finding["author"] = str(args.author or DEFAULT_AUTHOR)

    today = qa_suppress.utc_today()
    suppression_doc = qa_suppress.load_suppressions(ctx)
    suppression_report = qa_suppress.validate_all(suppression_doc, today)
    kept: List[Dict[str, Any]] = []
    suppressed: List[Dict[str, Any]] = []
    for finding in findings:
        if qa_suppress.is_suppressed(finding, suppression_doc, today):
            suppressed.append(finding)
        else:
            kept.append(finding)

    baseline_used = False
    preexisting: List[Dict[str, Any]] = []
    introduced: List[Dict[str, Any]] = list(kept)
    if not args.no_baseline:
        baseline = qa_baseline.load_baseline(ctx)
        if baseline.get("fingerprints"):
            baseline_used = True
            preexisting, introduced = qa_baseline.partition(kept, baseline)

    for finding in preexisting:
        finding["preexisting"] = True
        finding["status"] = "informational"
        finding["severity"] = "low"
    for finding in introduced:
        finding["preexisting"] = False
        finding["status"] = "open"
        finding["severity"] = severity_for(
            str(finding.get("source") or "unit"),
            impact=finding.get("impact"),
            flaky=bool(finding.get("flaky")),
            stated_criterion=bool(finding.get("statedCriterion")),
            preexisting=False,
        )

    reportable = sorted(kept, key=_sort_key)
    verdict = compute_verdict(run_document.get("layers") or [], ctx.config)
    verdict = _relax_for_governed_findings(
        verdict, run_document, introduced, preexisting, suppressed, ctx.config
    )

    first_number = _as_int(qa_round.next_issue_number(ctx, round_no)) or 1
    issues: List[Dict[str, Any]] = []
    written: List[str] = []
    for offset, finding in enumerate(reportable):
        number = first_number + offset
        ident = "issue_%03d" % number
        issues.append(
            {
                "id": ident,
                "file": str(finding.get("file") or ""),
                "line": _as_int(finding.get("line")),
                "severity": severity_of(finding),
                "source": _source_of(finding),
                "status": _status_of(finding),
                "title": _one_line(finding.get("name")) or "Unnamed failure",
            }
        )
        if not args.dry_run:
            path = write_issue(ctx, round_no, number, finding)
            written.append(ctx.rel(path))

    manual_items = _manual_items(plan, run_document)
    document = {
        "schemaVersion": common.SCHEMA_VERSION,
        "round": round_no,
        "runId": run_id,
        "verdict": verdict["verdict"],
        "rawVerdict": str(verdict.get("rawVerdict") or verdict["verdict"]),
        "verdictAdjusted": bool(verdict.get("adjusted")),
        "reasons": list(verdict.get("reasons") or []),
        "complete": verdict["complete"],
        "generatedAt": common.utc_now_iso(),
        "layers": _layer_rows(run_document),
        "counts": _counts(reportable),
        "issues": issues,
        "manualItems": manual_items,
        "suppressions": {
            "valid": suppression_report["counts"]["valid"],
            "invalid": suppression_report["counts"]["invalid"],
            "expired": suppression_report["counts"]["expired"],
        },
        "baseline": {
            "used": baseline_used,
            "preexisting": len(preexisting),
            "introduced": len(introduced),
        },
        "skippedLayers": verdict["skippedLayers"],
        "coverage": _coverage(plan, manual_items),
    }
    rendered = dict(document)
    rendered["verdictLine"] = verdict_line(verdict)
    rendered["reasons"] = verdict["reasons"]
    rendered["roundDir"] = ctx.rel(round_dir)
    summary_md = _render_summary_md(rendered, issues)

    if not args.dry_run:
        common.atomic_write(_ensure_writable(ctx, round_dir / "summary.md"), summary_md)
        common.write_json(_ensure_writable(ctx, summary_json), document)

    emitted = dict(document)
    emitted["issueFiles"] = written
    emitted["suppressed"] = len(suppressed)
    if args.dry_run:
        emitted["dryRun"] = True
    ctx.emit(emitted)

    counts = document["counts"]
    ctx.progress(
        "[qa] report round=%03d run=%s verdict=\"%s\" findings=%d critical=%d high=%d "
        "medium=%d low=%d"
        % (
            round_no,
            run_id,
            verdict_line(verdict),
            counts["total"],
            counts["critical"],
            counts["high"],
            counts["medium"],
            counts["low"],
        )
    )
    ctx.note(summary_md)
    return common.OK if verdict["verdict"] == "pass" else common.FAIL


# --------------------------------------------------------------------------
# verdict
# --------------------------------------------------------------------------


def add_verdict_args(parser: argparse.ArgumentParser) -> None:
    """Declare the ``verdict`` subcommand's own flags."""
    parser.add_argument("--round", dest="round", type=int, required=True, help="round number")
    parser.add_argument("--run", dest="run", default=None, help="run id (default: latest)")


def run_verdict(args: argparse.Namespace, ctx: "common.Context") -> int:
    """Recompute and print the verdict for a round."""
    round_no = _as_int(args.round)
    round_dir = pathlib.Path(qa_round.round_dir(ctx, round_no))
    if not round_dir.is_dir():
        raise common.QaError(
            "round %03d does not exist under %s" % (round_no, ctx.rel(ctx.qa_dir)),
            common.USAGE,
        )
    run_id = _resolve_run_id(ctx, round_no, args.run)
    run_document = _load_run(ctx, round_no, run_id)
    verdict = compute_verdict(run_document.get("layers") or [], ctx.config)

    sealed = common.read_json(round_dir / "summary.json", None)
    if (
        isinstance(sealed, dict)
        and str(sealed.get("runId") or "") == run_id
        and sealed.get("verdict") in ("pass", "fail")
    ):
        # A sealed round is authoritative: it already folded in the baseline and
        # the recorded suppressions, and a sealed round is never re-decided. Take
        # its reasons too -- splicing a sealed verdict onto recomputed fail
        # reasons produced a document that contradicted itself.
        sealed_reasons = [str(item) for item in (sealed.get("reasons") or []) if str(item).strip()]
        verdict = {
            "verdict": str(sealed["verdict"]),
            "rawVerdict": str(sealed.get("rawVerdict") or sealed["verdict"]),
            "adjusted": bool(sealed.get("verdictAdjusted")),
            "complete": bool(sealed.get("complete", verdict["complete"])),
            "reasons": (sealed_reasons or list(verdict["reasons"]))
            + ["verdict read from the sealed summary.json of round %03d" % round_no],
            "skippedLayers": sealed.get("skippedLayers") or verdict["skippedLayers"],
        }

    ctx.emit(
        {
            "schemaVersion": common.SCHEMA_VERSION,
            "round": round_no,
            "runId": run_id,
            "verdict": verdict["verdict"],
            "rawVerdict": str(verdict.get("rawVerdict") or verdict["verdict"]),
            "verdictAdjusted": bool(verdict.get("adjusted")),
            "complete": verdict["complete"],
            "reasons": verdict["reasons"],
            "skippedLayers": verdict["skippedLayers"],
        }
    )
    ctx.progress('[qa] verdict round=%03d verdict="%s"' % (round_no, verdict_line(verdict)))
    return common.OK if verdict["verdict"] == "pass" else common.FAIL


COMMANDS = [
    ("report", "Write issue files, summary.md, and summary.json for a round.", add_report_args, run_report),
    ("verdict", "Recompute the pass/fail verdict for a round.", add_verdict_args, run_verdict),
]
