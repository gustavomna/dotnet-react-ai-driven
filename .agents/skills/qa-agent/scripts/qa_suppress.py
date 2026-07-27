"""Suppression governance: validation, listing, and recording.

A suppression is valid only when it records all three parts -- ``target``,
``reason``, and ``expires``. Anything missing or blank makes the entry invalid,
and an invalid entry never suppresses: the check runs anyway and the entry is
reported. Accessibility rules can never be disabled, and only a ``third-party``
scope may exclude a subtree.
"""

import argparse
import datetime
import fnmatch
import os
import pathlib
import re
from typing import Any, Dict, List, Optional, Sequence, Union

try:
    from . import qa_common as common
except ImportError:  # pragma: no cover - direct script execution
    import qa_common as common

COMMAND = "suppress"
HELP = "Validate, list, or add a recorded suppression."

SUPPRESSIONS_FILENAME = "suppressions.json"

SCOPES = ("third-party", "test", "rule")
DEFAULT_SCOPE = "test"

#: Only this scope may exclude a subtree from a scan.
SUBTREE_SCOPE = "third-party"

#: Selectors that are never an acceptable exclusion, whatever the scope.
BROAD_SELECTORS = ("html", "body", "#root", "#app", "*", ":root")

_SELECTOR_KEYS = ("exclude", "excludes", "selector", "selectors")

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_VERSION_RE = re.compile(r"^(?:[<>]=?|==|~>|[~^])?\s*v?\d+(?:\.\d+)*(?:[-+.][0-9A-Za-z.\-]+)?$")
_TICKET_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*-\d+$")
_SHORT_ISSUE_RE = re.compile(r"^[\w.\-]*(?:/[\w.\-]+)?#\d+$")
_URL_RE = re.compile(r"^https?://\S+$")
_BROAD_RE = re.compile(r"^(html|body|#root|#app|\*|:root)(\s*[>+~]?\s*\*)?$", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------


def suppressions_path(ctx: "common.Context") -> pathlib.Path:
    """Absolute path of the committed suppressions document."""
    return pathlib.Path(ctx.qa_dir) / SUPPRESSIONS_FILENAME


def _ensure_writable(ctx: "common.Context", path: pathlib.Path) -> pathlib.Path:
    """Refuse any write that escapes both the repo root and the QA directory."""
    return common.ensure_writable(ctx, path)


def load_suppressions(ctx: "common.Context") -> Dict[str, Any]:
    """Read ``qa/suppressions.json``; a missing file yields an empty document."""
    doc = common.read_json(suppressions_path(ctx), None)
    if not isinstance(doc, dict):
        return {"schemaVersion": common.SCHEMA_VERSION, "suppressions": []}
    entries = doc.get("suppressions")
    if not isinstance(entries, list):
        entries = []
    return {
        "schemaVersion": doc.get("schemaVersion", common.SCHEMA_VERSION),
        "suppressions": [e for e in entries if isinstance(e, dict)],
    }


def _entries(suppressions: Union[Dict[str, Any], Sequence[Dict[str, Any]], None]) -> List[Dict[str, Any]]:
    if suppressions is None:
        return []
    if isinstance(suppressions, dict):
        raw = suppressions.get("suppressions") or []
    else:
        raw = suppressions
    return [e for e in raw if isinstance(e, dict)]


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_iso_date(value: str) -> Optional[datetime.date]:
    if not _ISO_DATE_RE.match(value):
        return None
    try:
        return datetime.date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def utc_today() -> datetime.date:
    """Today's date in UTC."""
    return datetime.datetime.now(datetime.timezone.utc).date()


def _coerce_today(value: Any) -> datetime.date:
    """Accept ``None``, a ``date``/``datetime``, or an ISO ``YYYY-MM-DD`` string."""
    if value is None:
        return utc_today()
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    parsed = _parse_iso_date(_text(value))
    if parsed is None:
        raise common.QaError(
            "today must be an ISO date (YYYY-MM-DD), got: %s" % value, common.USAGE
        )
    return parsed


def classify_expiry(value: str) -> str:
    """Return ``date``, ``version``, ``ticket``, or ``none`` for an expiry token."""
    text = _text(value)
    if not text:
        return "none"
    if _parse_iso_date(text) is not None:
        return "date"
    if _URL_RE.match(text):
        return "ticket"
    if _TICKET_RE.match(text) or _SHORT_ISSUE_RE.match(text):
        return "ticket"
    if _VERSION_RE.match(text):
        return "version"
    return "none"


def is_broad_selector(selector: Any) -> bool:
    """True when a selector is too broad to ever be an acceptable exclusion."""
    if selector is None:
        return True
    text = _WS_RE.sub(" ", str(selector)).strip()
    if not text:
        return True
    for part in text.split(","):
        candidate = part.strip()
        if not candidate:
            return True
        if candidate.lower() in BROAD_SELECTORS:
            return True
        if _BROAD_RE.match(candidate):
            return True
    return False


def _selectors_of(entry: Dict[str, Any]) -> List[str]:
    found: List[str] = []
    for key in _SELECTOR_KEYS:
        if key not in entry:
            continue
        value = entry.get(key)
        if isinstance(value, (list, tuple)):
            found.extend(str(v) for v in value)
        elif value is None:
            found.append("")
        else:
            found.append(str(value))
    return found


def targets_a11y(entry: Dict[str, Any]) -> bool:
    """True when the entry points at the accessibility layer."""
    if _text(entry.get("source")).lower() == "a11y":
        return True
    if _text(entry.get("layer")).lower() == "a11y":
        return True
    target = _text(entry.get("target")).lower()
    return target.startswith("a11y:") or ":a11y:" in target


def validate_entry(entry: Dict[str, Any], today: Any = None) -> Dict[str, Any]:
    """Validate one suppression entry.

    ``today`` accepts a ``date`` or an ISO ``YYYY-MM-DD`` string. Returns a report
    dict: ``valid`` says the entry is well-formed and permitted, ``expired`` says a
    dated entry has run out, ``state`` is ``valid``/``invalid``/``expired``, and
    ``suppresses`` says whether it actually silences anything (an expired entry
    never does).
    """
    today = _coerce_today(today)
    errors: List[str] = []
    entry = entry if isinstance(entry, dict) else {}

    target = _text(entry.get("target"))
    reason = _text(entry.get("reason"))
    expires = _text(entry.get("expires"))
    scope = _text(entry.get("scope")) or DEFAULT_SCOPE

    if not target:
        errors.append("target is missing or blank")
    if not reason:
        errors.append("reason is missing or blank")
    if not expires:
        errors.append("expires is missing or blank")

    expiry_kind = classify_expiry(expires)
    if expires and expiry_kind == "none":
        errors.append(
            "expires must be an ISO date (YYYY-MM-DD), a version (>=2.0.0), "
            "or a ticket reference (JIRA-123 or a URL)"
        )

    if scope not in SCOPES:
        errors.append("scope must be one of %s" % ", ".join(SCOPES))

    if scope == "rule" and targets_a11y(entry):
        errors.append(
            "accessibility rules may never be disabled; record a third-party "
            "scoped exclusion for a vendor widget instead"
        )

    if target and is_broad_selector(target):
        errors.append("broad exclude rejected: %s" % target)

    selectors = _selectors_of(entry)
    if selectors and scope != SUBTREE_SCOPE:
        errors.append(
            "only scope %s may exclude a subtree (found an exclusion under scope %s)"
            % (SUBTREE_SCOPE, scope)
        )
    for selector in selectors:
        if is_broad_selector(selector):
            errors.append(
                "broad exclude rejected: %s" % (_text(selector) or "<empty selector>")
            )

    expired = False
    if not errors and expiry_kind == "date":
        parsed = _parse_iso_date(expires)
        if parsed is not None and parsed < today:
            expired = True

    valid = not errors
    if not valid:
        state = "invalid"
    elif expired:
        state = "expired"
    else:
        state = "valid"

    return {
        "id": _text(entry.get("id")) or None,
        "target": target or None,
        "scope": scope,
        "reason": reason or None,
        "expires": expires or None,
        "expiryKind": expiry_kind,
        "valid": valid,
        "expired": expired,
        "state": state,
        "suppresses": valid and not expired,
        "errors": errors,
    }


def validate_all(
    suppressions: Union[Dict[str, Any], Sequence[Dict[str, Any]], None],
    today: Any = None,
) -> Dict[str, Any]:
    """Validate every entry and return reports plus ``valid``/``invalid``/``expired`` counts."""
    today = _coerce_today(today)
    reports = [validate_entry(entry, today) for entry in _entries(suppressions)]
    counts = {
        "valid": len([r for r in reports if r["state"] == "valid"]),
        "invalid": len([r for r in reports if r["state"] == "invalid"]),
        "expired": len([r for r in reports if r["state"] == "expired"]),
        "total": len(reports),
    }
    return {"entries": reports, "counts": counts}


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------


def _identities(finding: Dict[str, Any]) -> List[str]:
    source = _text(finding.get("source"))
    layer = _text(finding.get("layer"))
    rule = _text(finding.get("rule"))
    path = str(finding.get("file") or "").replace("\\", "/").strip()
    test_id = _text(finding.get("testId"))
    target = _text(finding.get("target"))
    ids: List[str] = []
    for prefix in [p for p in (source, layer) if p]:
        if rule and path:
            ids.append("%s:%s:%s" % (prefix, rule, path))
        if rule and target:
            ids.append("%s:%s:%s" % (prefix, rule, target))
        if rule:
            ids.append("%s:%s" % (prefix, rule))
        if path:
            ids.append("%s:%s" % (prefix, path))
        if test_id:
            ids.append("%s:%s" % (prefix, test_id))
    for value in (path, test_id, target, rule):
        if value:
            ids.append(value)
    seen: List[str] = []
    for value in ids:
        if value not in seen:
            seen.append(value)
    return seen


def matches(entry_target: str, finding: Dict[str, Any]) -> bool:
    """True when a suppression target designates this finding."""
    pattern = _text(entry_target)
    if not pattern:
        return False
    prefix = pattern.rstrip("/") + "/"
    for identity in _identities(finding):
        if identity == pattern:
            return True
        if identity.startswith(prefix):
            return True
        if any(ch in pattern for ch in "*?[") and fnmatch.fnmatchcase(identity, pattern):
            return True
    return False


def is_suppressed(
    finding: Dict[str, Any],
    suppressions: Union[Dict[str, Any], Sequence[Dict[str, Any]], None],
    today: Any = None,
) -> bool:
    """True only when a valid, unexpired suppression covers this finding."""
    today = _coerce_today(today)
    for entry in _entries(suppressions):
        report = validate_entry(entry, today)
        if not report["suppresses"]:
            continue
        if matches(report["target"] or "", finding):
            return True
    return False


# --------------------------------------------------------------------------
# Command
# --------------------------------------------------------------------------


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Declare the ``suppress`` subcommand's own flags."""
    parser.add_argument(
        "action",
        choices=["validate", "list", "add"],
        help="suppression operation to perform",
    )
    parser.add_argument("--target", dest="target", default=None, help="exact target to suppress")
    parser.add_argument("--reason", dest="reason", default=None, help="why it is suppressed")
    parser.add_argument(
        "--expires",
        dest="expires",
        default=None,
        help="expiry condition: ISO date, version, or ticket reference",
    )
    parser.add_argument(
        "--scope",
        dest="scope",
        default=None,
        choices=list(SCOPES),
        help="suppression scope (default: %s)" % DEFAULT_SCOPE,
    )
    parser.add_argument(
        "--exclude",
        dest="exclude",
        default=None,
        help="selector subtree to exclude; only valid with --scope third-party",
    )
    parser.add_argument("--by", dest="by", default=None, help="who recorded it")
    parser.add_argument(
        "--today",
        dest="today",
        default=None,
        metavar="YYYY-MM-DD",
        help="evaluate expiry against this date instead of today (UTC)",
    )


def _today_from(args: argparse.Namespace) -> datetime.date:
    raw = getattr(args, "today", None)
    if raw is None or not _text(raw):
        return utc_today()
    parsed = _parse_iso_date(_text(raw))
    if parsed is None:
        raise common.QaError("--today must be an ISO date (YYYY-MM-DD)", common.USAGE)
    return parsed


def _report_document(ctx: "common.Context", doc: Dict[str, Any], today: datetime.date) -> Dict[str, Any]:
    result = validate_all(doc, today)
    return {
        "schemaVersion": common.SCHEMA_VERSION,
        "path": ctx.rel(suppressions_path(ctx)),
        "today": today.isoformat(),
        "counts": result["counts"],
        "entries": result["entries"],
    }


def _validate(ctx: "common.Context", args: argparse.Namespace) -> int:
    today = _today_from(args)
    doc = load_suppressions(ctx)
    report = _report_document(ctx, doc, today)
    ctx.emit(report)
    counts = report["counts"]
    ctx.note(
        "[qa] suppressions: %d valid, %d invalid, %d expired"
        % (counts["valid"], counts["invalid"], counts["expired"])
    )
    if counts["invalid"]:
        for entry in report["entries"]:
            if entry["state"] == "invalid":
                ctx.progress(
                    "[qa] suppression status=invalid target=%s errors=%s"
                    % (entry["target"] or "<missing>", "; ".join(entry["errors"]))
                )
        return common.INVALID_SUPPRESSION
    return common.OK


def _list(ctx: "common.Context", args: argparse.Namespace) -> int:
    today = _today_from(args)
    doc = load_suppressions(ctx)
    report = _report_document(ctx, doc, today)
    report["suppressions"] = doc.get("suppressions") or []
    ctx.emit(report)
    counts = report["counts"]
    ctx.note(
        "[qa] %d suppression(s): %d valid, %d invalid, %d expired"
        % (counts["total"], counts["valid"], counts["invalid"], counts["expired"])
    )
    return common.OK


def _next_id(entries: Sequence[Dict[str, Any]]) -> str:
    highest = 0
    for entry in entries:
        raw = _text(entry.get("id"))
        if raw.startswith("sup-") and raw[4:].isdigit():
            highest = max(highest, int(raw[4:], 10))
    return "sup-%03d" % (highest + 1)


def _add(ctx: "common.Context", args: argparse.Namespace) -> int:
    today = _today_from(args)
    doc = load_suppressions(ctx)
    entries = list(doc.get("suppressions") or [])
    candidate = {
        "id": _next_id(entries),
        "target": _text(args.target),
        "reason": _text(args.reason),
        "expires": _text(args.expires),
        "scope": _text(args.scope) or DEFAULT_SCOPE,
        "addedBy": _text(args.by) or os.environ.get("USER") or "unknown",
        "addedAt": today.isoformat(),
    }
    if args.exclude is not None:
        candidate["exclude"] = str(args.exclude)
    report = validate_entry(candidate, today)
    if not report["valid"]:
        ctx.emit(
            {
                "schemaVersion": common.SCHEMA_VERSION,
                "action": "add",
                "written": False,
                "entry": candidate,
                "validation": report,
            }
        )
        ctx.progress(
            "[qa] suppression rejected: %s" % "; ".join(report["errors"])
        )
        return common.INVALID_SUPPRESSION
    entries.append(candidate)
    path = _ensure_writable(ctx, suppressions_path(ctx))
    common.write_json(
        path, {"schemaVersion": common.SCHEMA_VERSION, "suppressions": entries}
    )
    ctx.emit(
        {
            "schemaVersion": common.SCHEMA_VERSION,
            "action": "add",
            "written": True,
            "path": ctx.rel(path),
            "entry": candidate,
            "validation": report,
        }
    )
    ctx.note(
        "[qa] recorded %s (scope %s, expires %s)"
        % (candidate["id"], candidate["scope"], candidate["expires"])
    )
    return common.OK


def run(args: argparse.Namespace, ctx: "common.Context") -> int:
    """Dispatch the ``suppress`` subcommand."""
    action = getattr(args, "action", None)
    if action == "validate":
        return _validate(ctx, args)
    if action == "list":
        return _list(ctx, args)
    if action == "add":
        return _add(ctx, args)
    raise common.QaError("unknown suppress action: %s" % action, common.USAGE)
