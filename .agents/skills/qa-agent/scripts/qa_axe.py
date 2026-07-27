"""Normalization of axe-core payloads into QA Agent finding dicts.

Library only: this module owns no subcommand. It accepts either a raw axe-core
result document or the ``{"violations": [], "incomplete": []}`` subset written by
``@axe-core/playwright``, and converts it into the normalized finding shape that
``qa_findings``, ``qa_baseline``, and ``qa_suppress`` all consume.
"""

import re
from typing import Any, Dict, List, Optional, Sequence

try:
    from . import qa_common as common
except ImportError:  # pragma: no cover - direct script execution
    import qa_common as common

# axe impact -> QA severity, per the contract's severity table.
IMPACT_SEVERITY = {
    "critical": "critical",
    "serious": "high",
    "moderate": "medium",
    "minor": "low",
}

#: Severity used when axe reports no impact, or an impact we do not know.
UNKNOWN_IMPACT_SEVERITY = "medium"

_PAYLOAD_KEYS = ("results", "axeResults", "axe", "report", "violationsByPage")


def impact_to_severity(impact: Optional[str]) -> str:
    """Map an axe impact to a QA severity.

    ``critical`` -> critical, ``serious`` -> high, ``moderate`` -> medium,
    ``minor`` -> low, anything else (including ``None``) -> medium.
    """
    if impact is None:
        return UNKNOWN_IMPACT_SEVERITY
    key = str(impact).strip().lower()
    return IMPACT_SEVERITY.get(key, UNKNOWN_IMPACT_SEVERITY)


def flatten_target(value: Any) -> List[str]:
    """Flatten an axe ``node.target`` (which may nest frame selector arrays)."""
    flat: List[str] = []
    if value is None:
        return flat
    if isinstance(value, str):
        text = value.strip()
        if text:
            flat.append(text)
        return flat
    if isinstance(value, (list, tuple)):
        for item in value:
            flat.extend(flatten_target(item))
        return flat
    text = str(value).strip()
    if text:
        flat.append(text)
    return flat


def target_selector(node: Dict[str, Any]) -> Optional[str]:
    """Return the joined selector for one axe node, or ``None`` when absent."""
    parts = flatten_target(node.get("target"))
    if not parts:
        return None
    return " ".join(parts)


def iter_payloads(payload: Any) -> List[Dict[str, Any]]:
    """Yield every axe result document inside ``payload``.

    Tolerates a single document, a list of documents, and documents wrapped in a
    ``results``-style envelope.
    """
    docs: List[Dict[str, Any]] = []
    if payload is None:
        return docs
    if isinstance(payload, (list, tuple)):
        for item in payload:
            docs.extend(iter_payloads(item))
        return docs
    if isinstance(payload, dict):
        if "violations" in payload or "incomplete" in payload:
            docs.append(payload)
            return docs
        for key in _PAYLOAD_KEYS:
            inner = payload.get(key)
            if isinstance(inner, (dict, list)):
                docs.extend(iter_payloads(inner))
        return docs
    return docs


def route_path(value: Any) -> str:
    """Reduce an absolute page URL to its path, leaving anything else alone.

    ``file`` feeds the baseline fingerprint, and a full URL would bind a finding
    to a host and port -- the same page scanned on ``localhost:5173`` in
    development and ``127.0.0.1:4173`` in CI would fingerprint differently and a
    committed baseline would stop matching. The path identifies the page and
    survives the move.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*://[^/]*(?P<path>/[^?#]*)?", text)
    if not match:
        return text
    return match.group("path") or "/"


def _resolve_file(doc: Dict[str, Any], route: Optional[str], component: Optional[str]) -> str:
    """Resolve the finding's ``file``: the component path when known, else the route."""
    if component:
        return str(component)
    if route:
        return route_path(route)
    url = doc.get("url")
    if url:
        return route_path(url)
    return ""


def _first_line(text: Optional[str]) -> str:
    if not text:
        return ""
    for line in str(text).splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _entry_nodes(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The violating nodes of one axe entry; a node-less entry yields nothing."""
    nodes = entry.get("nodes")
    if isinstance(nodes, (list, tuple)):
        return [node for node in nodes if isinstance(node, dict)]
    return []


def _finding_from_node(
    entry: Dict[str, Any],
    node: Dict[str, Any],
    doc: Dict[str, Any],
    route: Optional[str],
    component: Optional[str],
) -> Dict[str, Any]:
    rule = str(entry.get("id") or entry.get("ruleId") or "unknown-rule")
    impact = node.get("impact") or entry.get("impact")
    impact = str(impact).strip().lower() if impact else None
    selector = target_selector(node)
    help_text = entry.get("help") or entry.get("description") or rule
    summary = node.get("failureSummary") or entry.get("help") or entry.get("description") or ""
    message = common.redact(_first_line(summary) or str(help_text))
    where = selector or _resolve_file(doc, route, component) or "the scanned page"
    tags = entry.get("tags")
    return {
        "source": "a11y",
        "rule": rule,
        "testId": None,
        "name": "%s: %s" % (rule, common.redact(str(help_text))),
        "file": _resolve_file(doc, route, component),
        "line": 0,
        "target": selector,
        "impact": impact,
        "message": message,
        "expected": "No `%s` violation at `%s`" % (rule, where),
        "actual": message,
        "requirementRef": None,
        "statedCriterion": False,
        "flaky": False,
        "helpUrl": entry.get("helpUrl"),
        "reproduce": None,
        "suggestedFix": None,
        "severity": impact_to_severity(impact),
        "layer": "a11y",
        "route": route or doc.get("url"),
        "component": component,
        "html": common.redact(str(node.get("html"))) if node.get("html") else None,
        "tags": list(tags) if isinstance(tags, (list, tuple)) else [],
    }


def normalize_axe_results(
    payload: Any,
    *,
    route: Optional[str] = None,
    component: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Convert an axe payload into normalized findings, one per violating node.

    Findings keep the payload's own order -- violation by violation, node by
    node -- so two runs over the same payload always produce the same list.
    """
    findings: List[Dict[str, Any]] = []
    for doc in iter_payloads(payload):
        violations = doc.get("violations")
        if not isinstance(violations, (list, tuple)):
            continue
        for entry in violations:
            if not isinstance(entry, dict):
                continue
            for node in _entry_nodes(entry):
                findings.append(_finding_from_node(entry, node, doc, route, component))
    return findings


def collect_incomplete(
    payload: Any,
    *,
    route: Optional[str] = None,
    component: Optional[str] = None,
    fail_on_incomplete: bool = False,
) -> List[Dict[str, Any]]:
    """Convert axe ``incomplete[]`` entries into open items.

    Incomplete results are things axe could not decide. They are reported as
    manual open items -- never as a pass, never as a failure -- unless the caller
    passes ``fail_on_incomplete=True`` (config key ``a11y.failOnIncomplete``), in
    which case they are returned as ordinary blocking findings.
    """
    items: List[Dict[str, Any]] = []
    for doc in iter_payloads(payload):
        incomplete = doc.get("incomplete")
        if not isinstance(incomplete, (list, tuple)):
            continue
        for entry in incomplete:
            if not isinstance(entry, dict):
                continue
            for node in _entry_nodes(entry):
                item = _finding_from_node(entry, node, doc, route, component)
                where = item.get("target") or item.get("file") or "the scanned page"
                item["criterion"] = "a11y rule `%s` at `%s`" % (item["rule"], where)
                item["reason"] = (
                    item.get("message")
                    or "axe could not determine the result; manual review required"
                )
                item["manual"] = not fail_on_incomplete
                item["incomplete"] = True
                if fail_on_incomplete:
                    item["status"] = "open"
                items.append(item)
    return items


def manual_items(items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Reduce collected incomplete entries to the summary ``manualItems`` shape."""
    reduced: List[Dict[str, Any]] = []
    for item in items:
        if not item.get("manual"):
            continue
        reduced.append(
            {
                "criterion": str(item.get("criterion") or item.get("rule") or "a11y check"),
                "reason": str(item.get("reason") or "requires manual review"),
            }
        )
    return reduced
