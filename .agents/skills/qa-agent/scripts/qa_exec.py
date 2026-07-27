"""Layer execution for the QA Agent: run the suites, stream, retry flakes, report.

Layers run in the fixed order ``unit -> integration -> e2e -> a11y``. **A failing layer
never stops the remaining layers** -- one round reports every problem it can find.

Per layer this module:

* streams one screen-reader-friendly progress line per state change to stderr;
* writes the combined stdout+stderr of every attempt to ``<run>/<layer>.log`` as it
  arrives (never buffered whole in memory), with ANSI escapes stripped and secrets
  scrubbed by :func:`qa_common.redact`;
* records the exact argv, cwd, environment additions and a copy-pasteable reproduce
  string;
* enforces a per-layer timeout by killing the whole process group (``exitCode`` 124);
* re-runs only the failed tests once when the runner supports a targeted re-run, and
  reports anything that passes on retry as ``flaky`` -- never as passed;
* parses the runner's machine-readable report (vitest/jest JSON, playwright JSON, VSTest
  TRX) into normalized findings, and always falls back to a coarse finding built from the
  log tail rather than dropping a failure silently.

Standard library only, Python 3.9+.
"""

from __future__ import annotations

import collections
import os
import pathlib
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import xml.etree.ElementTree as ElementTree
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

try:
    from . import qa_common as common
    from . import qa_round
except ImportError:  # pragma: no cover - direct script execution
    import qa_common as common
    import qa_round

# ---------------------------------------------------------------------------
# Command metadata (consumed by qa.py)
# ---------------------------------------------------------------------------

COMMAND = "exec"
HELP = "Execute the test layers for a round and write run.json."

STATUS_RUNNING = "running"
STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_FLAKY = "flaky"
STATUS_SKIPPED = "skipped-unavailable"

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_JS_LOCATION_RE = re.compile(r"([A-Za-z0-9_./\\@+-]+\.[cm]?[jt]sx?):(\d+)(?::\d+)?")
_CS_LOCATION_RE = re.compile(r"\sin\s(.+?):line\s(\d+)")
_EXPECT_RE = re.compile(
    r"expected\s+(?P<actual>.+?)\s+to\s+(?:strictly\s+|deeply\s+)?"
    r"(?:be|equal|match|contain)\s+(?P<expected>.+?)\s*$",
    re.IGNORECASE,
)
_USAGE_ERROR_RE = re.compile(
    r"unknown (?:option|argument|command)|unrecognized option|error: unknown|"
    r"is not a recognized option",
    re.IGNORECASE,
)

_MAX_LOG_LINE = 8000
_LOG_TAIL_KEEP = 200
_COARSE_TAIL_LINES = 40
_MAX_MESSAGE_CHARS = 4000
_MAX_VALUE_CHARS = 500
_KILL_GRACE_SECONDS = 10
_PUMP_JOIN_SECONDS = 15
_DEFAULT_TIMEOUT_SECONDS = 1800

#: Environment added to every runner so the captured log stays colour-free and readable
#: linearly by a screen reader.
_BASE_ENV: Dict[str, str] = {"NO_COLOR": "1", "FORCE_COLOR": "0"}

_SCRIPT_RUNNERS = ("npm", "pnpm", "yarn", "bun")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def add_arguments(parser: Any) -> None:
    """Declare ``exec``'s own flags. Global flags are added by ``qa.py``."""

    parser.add_argument("--round", metavar="N", required=True, help="Round number.")
    parser.add_argument(
        "--layer",
        metavar="L",
        action="append",
        choices=list(common.LAYER_ORDER),
        help="Layer to run; repeatable. Default: every layer the stack reports.",
    )
    parser.add_argument("--stack", metavar="FILE", help="Detect output; default: detect now.")
    parser.add_argument("--scope", metavar="FILE", help="Scope document, recorded as provenance.")
    parser.add_argument(
        "--plan", metavar="FILE", help="Plan document; supplies requirement references."
    )
    parser.add_argument(
        "--timeout",
        metavar="S",
        type=int,
        default=None,
        help="Per-layer timeout in seconds (default: execution.timeoutSeconds, 1800).",
    )
    parser.add_argument(
        "--no-retry-failed",
        action="store_true",
        help="Do not re-run failed tests once to detect flakiness.",
    )
    parser.add_argument("--run-id", metavar="ID", default=None, help="Run id (testing hook).")


def run(args: Any, ctx: "common.Context") -> int:
    """Execute the selected layers and return 0 on a pass verdict, 1 on a fail."""

    round_no = qa_round.validate_round(getattr(args, "round", None))
    stack = _load_stack(ctx, getattr(args, "stack", None))

    plan_path = getattr(args, "plan", None)
    plan = None
    if plan_path:
        plan = common.read_json(_resolve_input(ctx, plan_path, "plan"), default=None)
    scope_path = getattr(args, "scope", None)
    if scope_path:
        _resolve_input(ctx, scope_path, "scope")

    retry = not bool(getattr(args, "no_retry_failed", False))
    document = execute_layers(
        ctx,
        stack,
        round_no,
        getattr(args, "layer", None),
        timeout=getattr(args, "timeout", None),
        retry=retry,
        run_id=getattr(args, "run_id", None),
        plan=plan,
        inputs={
            "stack": getattr(args, "stack", None),
            "scope": scope_path,
            "plan": plan_path,
        },
    )
    ctx.emit(document)
    _human_summary(ctx, document)
    return common.OK if document.get("verdict") == "pass" else common.FAIL


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


def _resolve_input(ctx: "common.Context", path: Any, label: str) -> pathlib.Path:
    """Resolve an input file against the cwd first, then the repo root."""

    candidate = pathlib.Path(str(path))
    if not candidate.is_absolute():
        absolute = pathlib.Path(os.path.abspath(str(candidate)))
        candidate = absolute if absolute.is_file() else (ctx.repo / candidate)
    if not candidate.is_file():
        raise common.QaError("{0} file not found: {1}".format(label, path), common.USAGE)
    return candidate


def _load_stack(ctx: "common.Context", path: Any) -> Dict[str, Any]:
    """Read ``--stack`` when given, otherwise detect the stack now."""

    if path:
        payload = common.read_json(_resolve_input(ctx, path, "stack"), default=None)
        if not isinstance(payload, dict):
            raise common.QaError(
                "stack file {0} must contain a JSON object".format(path), common.USAGE
            )
        return payload

    try:
        from . import qa_stack  # type: ignore
    except ImportError:  # pragma: no cover - direct script execution
        try:
            import qa_stack  # type: ignore
        except ImportError as exc:
            raise common.QaError(
                "cannot detect the stack ({0}); pass --stack FILE".format(exc),
                common.RUNTIME_ERROR,
            )
    detect = getattr(qa_stack, "detect_stack", None)
    if detect is None:
        raise common.QaError(
            "qa_stack.detect_stack() is unavailable; pass --stack FILE", common.RUNTIME_ERROR
        )
    detected = detect(ctx)
    if not isinstance(detected, dict):
        raise common.QaError("qa_stack.detect_stack() did not return an object")
    return detected


def _plan_index(plan: Any) -> Tuple[Dict[str, str], bool]:
    """Map each planned test file to its requirement reference."""

    index: Dict[str, str] = {}
    if not isinstance(plan, dict):
        return index, False
    inference = bool(plan.get("inferenceBased"))
    for check in plan.get("checks") or []:
        if not isinstance(check, dict):
            continue
        ref = check.get("requirementRef")
        if not ref:
            continue
        for key in ("testFile", "target"):
            value = check.get(key)
            if isinstance(value, str) and value.strip():
                index.setdefault(value.strip().replace("\\", "/"), str(ref))
    return index, inference


def _apply_plan(findings: List[Dict[str, Any]], index: Dict[str, str], inference: bool) -> None:
    """Attach requirement references from the plan to matching findings."""

    if not index:
        return
    for item in findings:
        path = str(item.get("file") or "").replace("\\", "/")
        ref = index.get(path)
        if ref is None:
            continue
        item["requirementRef"] = ref
        item["statedCriterion"] = not inference


# ---------------------------------------------------------------------------
# Layer selection
# ---------------------------------------------------------------------------


def _select_layers(
    ctx: "common.Context", requested: Optional[Sequence[str]]
) -> Tuple[List[str], List[Dict[str, str]]]:
    """Split the fixed layer order into what runs and what is skipped up front."""

    configured = ctx.config.get("layers") or {}
    wanted = [str(layer) for layer in (requested or [])]
    for layer in wanted:
        if layer not in common.LAYER_ORDER:
            raise common.QaError(
                "unknown layer {0!r}; expected one of {1}".format(
                    layer, ", ".join(common.LAYER_ORDER)
                ),
                common.USAGE,
            )

    selected: List[str] = []
    skipped: List[Dict[str, str]] = []
    for layer in common.LAYER_ORDER:
        if wanted and layer not in wanted:
            skipped.append({"layer": layer, "reason": "not selected (--layer)"})
            continue
        if configured.get(layer, True) is False:
            skipped.append(
                {
                    "layer": layer,
                    "reason": "disabled in qa.config.json (layers.{0} = false)".format(layer),
                }
            )
            continue
        selected.append(layer)
    return selected, skipped


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def execute_layers(
    ctx: "common.Context",
    stack: Dict[str, Any],
    round_no: Any,
    layers: Optional[Sequence[str]] = None,
    **opts: Any
) -> Dict[str, Any]:
    """Run the layers of ``stack`` inside ``round_no``, write and return ``run.json``.

    Options: ``timeout`` (per-layer seconds), ``retry`` (flake re-run, default from
    ``execution.retryFailedOnce``), ``run_id``, ``plan`` (plan document) and ``inputs``
    (provenance paths).
    """

    round_number = qa_round.validate_round(round_no)
    stack_layers = stack.get("layers") if isinstance(stack, dict) else None
    stack_layers = stack_layers if isinstance(stack_layers, dict) else {}
    if not any(
        isinstance(info, dict) and info.get("available") for info in stack_layers.values()
    ):
        raise common.QaError(
            "no test layer is available in the detected stack; nothing to execute",
            common.NO_STACK,
        )

    execution = ctx.config.get("execution") or {}
    timeout = opts.get("timeout")
    if timeout is None:
        timeout = execution.get("timeoutSeconds", _DEFAULT_TIMEOUT_SECONDS)
    try:
        timeout_seconds = int(timeout)
    except (TypeError, ValueError):
        raise common.QaError("timeout must be an integer number of seconds", common.USAGE)
    if timeout_seconds < 1:
        raise common.QaError("timeout must be at least 1 second", common.USAGE)

    retry = opts.get("retry")
    if retry is None:
        retry = execution.get("retryFailedOnce", True)
    retry_enabled = bool(retry)

    selected, skipped = _select_layers(ctx, layers)
    plan_index, inference = _plan_index(opts.get("plan"))

    run_dir = qa_round.new_run_dir(ctx, round_number, opts.get("run_id"))
    run_id = run_dir.name
    started_at = common.utc_now_iso()
    started = time.time()
    ctx.progress(
        "[qa] run={0} round={1} status=starting layers={2}".format(
            run_id, qa_round.round_id(round_number), ",".join(selected) or "none"
        )
    )

    entries: List[Dict[str, Any]] = []
    for layer in selected:
        info = stack_layers.get(layer)
        info = info if isinstance(info, dict) else {}
        entry = _execute_layer(
            ctx, layer, info, run_dir, timeout_seconds, retry_enabled, plan_index, inference
        )
        entries.append(entry)
        if entry["status"] == STATUS_SKIPPED:
            skipped.append({"layer": layer, "reason": entry.get("reason") or "unavailable"})

    skipped.sort(key=lambda item: common.LAYER_ORDER.index(item["layer"]))
    verdict, reasons = _verdict(entries, skipped, ctx.config)
    document = {
        "schemaVersion": common.SCHEMA_VERSION,
        "round": round_number,
        "runId": run_id,
        "startedAt": started_at,
        "finishedAt": common.utc_now_iso(),
        "repo": ctx.repo.as_posix(),
        "layers": entries,
        "verdict": verdict,
        "complete": not skipped,
        "skippedLayers": skipped,
        "runDir": ctx.rel(run_dir),
        "verdictReasons": reasons,
        "inputs": _inputs(opts.get("inputs")),
    }
    document = _clean(document)
    common.write_json(run_dir / "run.json", document, root=ctx.qa_dir)
    ctx.progress(
        "[qa] run={0} status=finished verdict={1} duration={2}".format(
            run_id, verdict.upper(), _seconds(time.time() - started)
        )
    )
    return document


def _inputs(raw: Any) -> Dict[str, Any]:
    values = raw if isinstance(raw, dict) else {}
    return {
        "stack": values.get("stack"),
        "scope": values.get("scope"),
        "plan": values.get("plan"),
    }


def _execute_layer(
    ctx: "common.Context",
    layer: str,
    info: Dict[str, Any],
    run_dir: pathlib.Path,
    timeout_seconds: int,
    retry_enabled: bool,
    plan_index: Dict[str, str],
    inference: bool,
) -> Dict[str, Any]:
    """Run every target of one layer, writing ``<run>/<layer>.log`` as output arrives."""

    log_name = "{0}.log".format(layer)
    log_path = common.ensure_within(ctx.qa_dir, run_dir / log_name)
    targets = [target for target in (info.get("targets") or []) if isinstance(target, dict)]
    available = bool(info.get("available")) and bool(targets)

    if not available:
        reason = str(
            info.get("reason")
            or ("no runnable {0} target detected in the stack".format(layer))
        )
        common.atomic_write(
            log_path,
            "=== qa layer={0} status=skipped-unavailable ===\n{1}\n".format(
                layer, common.redact(reason)
            ),
            root=ctx.qa_dir,
        )
        ctx.progress(
            '[qa] layer={0} status={1} reason="{2}"'.format(layer, STATUS_SKIPPED, reason)
        )
        return {
            "layer": layer,
            "status": STATUS_SKIPPED,
            "exitCode": None,
            "timedOut": False,
            "retried": False,
            "durationMs": 0,
            "command": [],
            "cwd": None,
            "reproduce": None,
            "log": log_name,
            "reason": reason,
            "failures": [],
            "flakes": [],
            "env": {},
            "targets": [],
        }

    started = time.time()
    deadline = started + timeout_seconds
    log = _LayerLog(log_path)
    results: List[Dict[str, Any]] = []
    try:
        for target in targets:
            results.append(
                _run_target(ctx, layer, target, log, deadline, timeout_seconds, retry_enabled)
            )
    finally:
        log.close()

    failures: List[Dict[str, Any]] = []
    flakes: List[Dict[str, Any]] = []
    for result in results:
        failures.extend(result["failures"])
        flakes.extend(result["flakes"])
    _apply_plan(failures, plan_index, inference)
    _apply_plan(flakes, plan_index, inference)

    exit_code = 0
    for result in results:
        if result["exitCode"]:
            exit_code = result["exitCode"]
            break
    timed_out = any(result["timedOut"] for result in results)
    retried = any(result["retried"] for result in results)

    if failures or exit_code or timed_out:
        status = STATUS_FAILED
    elif flakes:
        status = STATUS_FLAKY
    else:
        status = STATUS_PASSED

    duration = time.time() - started
    primary = results[0]
    reproduce = (
        primary["reproduce"]
        if len(results) == 1
        else " && ".join("({0})".format(result["reproduce"]) for result in results)
    )
    progress = "[qa] layer={0} status={1} exit={2} duration={3} failures={4}".format(
        layer, status, exit_code, _seconds(duration), len(failures)
    )
    if flakes:
        progress += " flakes={0}".format(len(flakes))
    if timed_out:
        progress += " timedOut=true"
    ctx.progress(progress)

    entry = {
        "layer": layer,
        "status": status,
        "exitCode": exit_code,
        "timedOut": timed_out,
        "retried": retried,
        "durationMs": int(round(duration * 1000)),
        "command": primary["command"],
        "cwd": primary["cwd"],
        "reproduce": reproduce,
        "log": log_name,
        "reason": None,
        "failures": failures,
        "flakes": flakes,
        "env": primary["env"],
        "targets": results,
    }
    if layer == "a11y":
        # Record where the raw axe payloads landed. `report` normalizes them, so
        # the axe impact -> severity mapping and incomplete[] -> manual items are
        # reachable through the ordinary pipeline instead of needing a flag.
        entry["axeArtifacts"] = _discover_axe_artifacts(ctx, started)
    return entry


def _discover_axe_artifacts(ctx: "common.Context", since: float) -> List[str]:
    """Repo-relative paths of axe JSON payloads written by this a11y run."""

    globs = (ctx.config.get("a11y") or {}).get("resultsGlob") or []
    found: List[str] = []
    seen = set()
    for pattern in globs:
        try:
            matches = sorted(pathlib.Path(ctx.repo).glob(str(pattern)))
        except (ValueError, OSError):
            continue
        for path in matches:
            try:
                if not path.is_file() or path.stat().st_mtime + 1.0 < since:
                    continue
            except OSError:
                continue
            rel = ctx.rel(path)
            if rel not in seen:
                seen.add(rel)
                found.append(rel)
    return found


# ---------------------------------------------------------------------------
# Target execution and the flake retry
# ---------------------------------------------------------------------------


def _run_target(
    ctx: "common.Context",
    layer: str,
    target: Dict[str, Any],
    log: "_LayerLog",
    deadline: float,
    timeout_seconds: int,
    retry_enabled: bool,
) -> Dict[str, Any]:
    """Run one stack target, retry its failures once, and normalize the outcome."""

    project = str(target.get("project") or "")
    runner = str(target.get("runner") or "")
    cwd_rel = str(target.get("cwd") or ".").strip() or "."
    argv_base = [str(item) for item in (target.get("command") or [])]
    result: Dict[str, Any] = {
        "project": project,
        "runner": runner,
        "command": list(argv_base),
        "cwd": cwd_rel,
        "reproduce": _reproduce(cwd_rel, argv_base) if argv_base else None,
        "env": {},
        "exitCode": 0,
        "timedOut": False,
        "retried": False,
        "durationMs": 0,
        "attempts": [],
        "failures": [],
        "flakes": [],
    }

    if not argv_base:
        message = "stack target {0!r} in the {1} layer has no command".format(project, layer)
        log.line("=== qa layer={0} target={1} status=error ===".format(layer, project or "-"))
        log.line(message)
        result["exitCode"] = common.USAGE
        result["failures"] = [
            _coarse_finding(layer, target, cwd_rel, common.USAGE, [message], False,
                            timeout_seconds, None)
        ]
        return result

    cwd_abs = pathlib.Path(cwd_rel)
    if not cwd_abs.is_absolute():
        cwd_abs = ctx.repo / cwd_rel
    cwd_abs = pathlib.Path(os.path.abspath(str(cwd_abs)))
    outside = False
    try:
        common.ensure_within(ctx.repo, cwd_abs)
    except common.QaError:
        outside = True
    if outside or not cwd_abs.is_dir():
        message = (
            "working directory {0} is outside the repository".format(cwd_rel)
            if outside
            else "working directory {0} does not exist".format(cwd_rel)
        )
        log.line("=== qa layer={0} target={1} status=error ===".format(layer, project or "-"))
        log.line(message)
        result["exitCode"] = common.USAGE
        result["failures"] = [
            _coarse_finding(layer, target, cwd_rel, common.USAGE, [message], False,
                            timeout_seconds, result["reproduce"])
        ]
        return result

    kind = _runner_kind(target)
    context = {
        "layer": layer,
        "target": target,
        "kind": kind,
        "argv_base": argv_base,
        "cwd_abs": cwd_abs,
        "cwd_rel": cwd_rel,
        "timeout_seconds": timeout_seconds,
    }

    # Announce the layer BEFORE the first attempt runs. A long suite must not look like a
    # hang (PRD Core Feature 3), and a retry must never be the first thing a reader sees.
    ctx.progress(
        '[qa] layer={0} status={1} command="{2}" cwd={3}'.format(
            layer, STATUS_RUNNING, shlex.join(argv_base), cwd_rel
        )
    )

    tmpdir = tempfile.mkdtemp(prefix="qa-exec-")
    try:
        first = _attempt(ctx, context, log, deadline, tmpdir, 1, [])
        result["command"] = first["argv"]
        result["env"] = first["env"]
        result["attempts"].append(_attempt_summary(first))
        failures = list(first["failures"])
        flakes = list(first["flakes"])
        exit_code = first["exitCode"]
        timed_out = first["timedOut"]
        duration_ms = first["durationMs"]

        should_retry = (
            retry_enabled
            and not timed_out
            and (exit_code != 0 or failures)
            and (deadline - time.time()) > 0
        )
        if should_retry:
            targeted = _targeted_args(kind, failures)
            ctx.progress(
                '[qa] layer={0} status=retrying command="{1}" cwd={2}'.format(
                    layer,
                    shlex.join(_append_args(argv_base, targeted or [])),
                    cwd_rel,
                )
            )
            second = _attempt(ctx, context, log, deadline, tmpdir, 2, targeted or [])
            result["retried"] = True
            result["attempts"].append(_attempt_summary(second))
            duration_ms += second["durationMs"]

            if targeted and _looks_like_usage_error(second):
                log.line(
                    "=== qa retry: the runner rejected the targeted re-run flags; "
                    "re-running the whole layer once ==="
                )
                third = _attempt(ctx, context, log, deadline, tmpdir, 3, [])
                result["attempts"].append(_attempt_summary(third))
                duration_ms += third["durationMs"]
                second = third

            failures, recovered = _merge_retry(failures, second)
            flakes.extend(_flake_finding(item, layer) for item in recovered)
            flakes.extend(second["flakes"])
            exit_code = second["exitCode"]
            timed_out = second["timedOut"]

        result["exitCode"] = exit_code
        result["timedOut"] = timed_out
        result["durationMs"] = duration_ms
        result["failures"] = failures
        result["flakes"] = flakes
        result["reproduce"] = _reproduce(cwd_rel, argv_base)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return result


def _attempt_summary(attempt: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "attempt": attempt["attempt"],
        "command": attempt["argv"],
        "exitCode": attempt["exitCode"],
        "timedOut": attempt["timedOut"],
        "durationMs": attempt["durationMs"],
        "failures": len(attempt["failures"]),
    }


def _finding_key(item: Dict[str, Any]) -> str:
    """Identity used to line up the same failure across two attempts."""

    test_id = item.get("testId")
    if test_id:
        return "id:{0}".format(test_id)
    return "coarse:{0}|{1}|{2}".format(item.get("source"), item.get("file"), item.get("name"))


def _merge_retry(
    first_failures: List[Dict[str, Any]], second: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return ``(still failing, recovered)`` after the retry attempt.

    A failure is only credited as recovered when the retry produced a parseable report
    that identifies tests and does not mention it. Anything unproven stays a failure --
    a flaky test is never reported as passed, and an unparseable retry never erases a
    failure. Findings without a test id (the coarse whole-layer fallback) are matched by
    name and file so one layer failure is never reported twice.
    """

    if second["exitCode"] == 0 and not second["failures"]:
        return [], list(first_failures)
    if not second["failures"]:
        return list(first_failures), []

    by_key: Dict[str, Dict[str, Any]] = {}
    for item in second["failures"]:
        by_key.setdefault(_finding_key(item), item)

    first_keys = set()
    still: List[Dict[str, Any]] = []
    recovered: List[Dict[str, Any]] = []
    for item in first_failures:
        key = _finding_key(item)
        first_keys.add(key)
        if key in by_key:
            still.append(by_key[key])
        elif item.get("testId"):
            recovered.append(item)
        else:
            still.append(item)
    for item in second["failures"]:
        if _finding_key(item) not in first_keys:
            still.append(item)
    return still, recovered


def _attempt(
    ctx: "common.Context",
    context: Dict[str, Any],
    log: "_LayerLog",
    deadline: float,
    tmpdir: str,
    attempt: int,
    extra_args: Sequence[str],
) -> Dict[str, Any]:
    """One process invocation plus the parsing of whatever report it produced."""

    layer = context["layer"]
    target = context["target"]
    kind = context["kind"]
    argv_base = context["argv_base"]
    cwd_abs = context["cwd_abs"]
    cwd_rel = context["cwd_rel"]
    timeout_seconds = context["timeout_seconds"]

    report_args, report_env, report_path, report_format = _report_spec(
        target, kind, tmpdir, attempt
    )
    argv = _append_args(argv_base, list(report_args) + list(extra_args))
    env_add = dict(_BASE_ENV)
    env_add.update(report_env)

    remaining = deadline - time.time()
    if remaining <= 0:
        message = (
            "the {0} layer timeout ({1}s) was exhausted before this target ran".format(
                layer, timeout_seconds
            )
        )
        log.reset_tail()
        log.line("=== qa layer={0} attempt={1} status=not-run ===".format(layer, attempt))
        log.line(message)
        return {
            "attempt": attempt,
            "argv": argv,
            "env": env_add,
            "exitCode": 124,
            "timedOut": True,
            "durationMs": 0,
            "tail": [message],
            "failures": [
                _coarse_finding(layer, target, cwd_rel, 124, [message], True,
                                timeout_seconds, _reproduce(cwd_rel, argv_base))
            ],
            "flakes": [],
        }

    log.reset_tail()
    log.line(
        "=== qa layer={0} target={1} runner={2} attempt={3} ===".format(
            layer, target.get("project") or "-", kind, attempt
        )
    )
    log.line("=== command: {0}".format(shlex.join(argv)))
    log.line("=== cwd: {0}".format(cwd_rel))
    if env_add:
        log.line(
            "=== env: {0}".format(
                " ".join("{0}={1}".format(k, env_add[k]) for k in sorted(env_add))
            )
        )

    exit_code, timed_out, duration = _run_process(argv, cwd_abs, env_add, remaining, log)
    tail = log.tail_lines()
    log.line(
        "=== exit={0} duration={1}{2} ===".format(
            exit_code, _seconds(duration), " timedOut=true" if timed_out else ""
        )
    )

    failures, flakes = _parse_report(ctx, context, report_format, report_path, timed_out)
    if timed_out:
        failures.append(
            _coarse_finding(layer, target, cwd_rel, 124, tail, True, timeout_seconds,
                            _reproduce(cwd_rel, argv_base))
        )
    elif exit_code != 0 and not failures:
        failures.append(
            _coarse_finding(layer, target, cwd_rel, exit_code, tail, False, timeout_seconds,
                            _reproduce(cwd_rel, argv_base))
        )

    return {
        "attempt": attempt,
        "argv": argv,
        "env": env_add,
        "exitCode": exit_code,
        "timedOut": timed_out,
        "durationMs": int(round(duration * 1000)),
        "tail": tail,
        "failures": failures,
        "flakes": flakes,
    }


def _looks_like_usage_error(attempt: Dict[str, Any]) -> bool:
    """True when the runner rejected the flags rather than running the tests."""

    if attempt["exitCode"] == 0 or attempt["timedOut"]:
        return False
    if attempt["failures"] and any(f.get("testId") for f in attempt["failures"]):
        return False
    return any(_USAGE_ERROR_RE.search(line) for line in attempt["tail"])


# ---------------------------------------------------------------------------
# Process plumbing
# ---------------------------------------------------------------------------


class _LayerLog:
    """The layer's ``.log`` file: streamed, ANSI-stripped, redacted, line by line."""

    def __init__(self, path: pathlib.Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = open(str(path), "w", encoding="utf-8", newline="\n")
        except OSError as exc:
            raise common.QaError("cannot open log {0}: {1}".format(path, exc))
        self._tail: Deque[str] = collections.deque(maxlen=_LOG_TAIL_KEEP)

    def line(self, text: str) -> None:
        clean = common.redact(_ANSI_RE.sub("", text.replace("\r", "")))
        if len(clean) > _MAX_LOG_LINE:
            clean = clean[:_MAX_LOG_LINE] + " ... [truncated]"
        try:
            self._handle.write(clean + "\n")
            self._handle.flush()
        except (OSError, ValueError):  # pragma: no cover - a full or closed disk
            return
        self._tail.append(clean)

    def reset_tail(self) -> None:
        self._tail.clear()

    def tail_lines(self) -> List[str]:
        return list(self._tail)

    def close(self) -> None:
        try:
            self._handle.close()
        except OSError:  # pragma: no cover - defensive
            pass


def _pump(stream: Any, log: "_LayerLog") -> None:
    """Copy the child's combined output into the log as it arrives."""

    try:
        for raw in iter(stream.readline, b""):
            log.line(raw.decode("utf-8", "replace").rstrip("\n"))
    except (OSError, ValueError):  # pragma: no cover - stream closed by the kill path
        return


def _run_process(
    argv: List[str],
    cwd: pathlib.Path,
    env_add: Dict[str, str],
    timeout: float,
    log: "_LayerLog",
) -> Tuple[int, bool, float]:
    """Run ``argv`` streaming into ``log``; return ``(exitCode, timedOut, seconds)``."""

    env = os.environ.copy()
    env.update(env_add)
    popen_extra: Dict[str, Any] = {}
    if os.name == "posix":
        popen_extra["start_new_session"] = True

    started = time.time()
    try:
        process = subprocess.Popen(  # noqa: S603 - argv list, shell=False
            argv,
            cwd=str(cwd),
            env=env,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            close_fds=True,
            **popen_extra
        )
    except FileNotFoundError:
        log.line("executable not found: {0}".format(argv[0]))
        return 127, False, time.time() - started
    except OSError as exc:
        log.line("cannot start {0}: {1}".format(argv[0], exc))
        return 126, False, time.time() - started

    thread = threading.Thread(target=_pump, args=(process.stdout, log), daemon=True)
    thread.start()

    timed_out = False
    try:
        exit_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate(process)
        exit_code = 124

    thread.join(timeout=_PUMP_JOIN_SECONDS)
    if process.stdout is not None:
        try:
            process.stdout.close()
        except OSError:  # pragma: no cover - defensive
            pass
    return int(exit_code), timed_out, time.time() - started


def _terminate(process: "subprocess.Popen") -> None:
    """Kill the child's whole process group so no runner child survives a timeout."""

    if os.name == "posix":
        try:
            group = os.getpgid(process.pid)
        except OSError:
            group = None
        if group is not None:
            for sig, grace in ((signal.SIGTERM, _KILL_GRACE_SECONDS), (signal.SIGKILL, 5)):
                try:
                    os.killpg(group, sig)
                except OSError:
                    break
                try:
                    process.wait(timeout=grace)
                    return
                except subprocess.TimeoutExpired:
                    continue
            return
    try:
        process.kill()
        process.wait(timeout=_KILL_GRACE_SECONDS)
    except (OSError, subprocess.TimeoutExpired):  # pragma: no cover - defensive
        pass


# ---------------------------------------------------------------------------
# Runner knowledge: report flags, targeted re-runs, reproduce strings
# ---------------------------------------------------------------------------


def _runner_kind(target: Dict[str, Any]) -> str:
    """Classify the runner so the report and re-run flags can be chosen."""

    haystack = " ".join(
        [str(target.get("runner") or ""), str(target.get("reportFormat") or "")]
        + [str(item) for item in (target.get("command") or [])]
    ).lower()
    for needle, kind in (
        ("vitest", "vitest"),
        ("jest", "jest"),
        ("playwright", "playwright"),
        ("cypress", "cypress"),
        ("dotnet", "dotnet"),
        ("xunit", "dotnet"),
        ("nunit", "dotnet"),
        ("mstest", "dotnet"),
        ("trx", "dotnet"),
    ):
        if needle in haystack:
            return kind
    return "unknown"


def _report_spec(
    target: Dict[str, Any], kind: str, tmpdir: str, attempt: int
) -> Tuple[List[str], Dict[str, str], Optional[str], Optional[str]]:
    """Return ``(extra argv, env additions, report path, report format)``."""

    declared_format = str(target.get("reportFormat") or "").strip().lower() or None
    declared_flags = [str(item) for item in (target.get("reportFlag") or [])]

    if declared_flags:
        suffix = ".trx" if declared_format == "trx" else ".json"
        report = os.path.join(tmpdir, "qa-report-{0}{1}".format(attempt, suffix))
        args = [
            flag.replace("<REPORT>", report)
            .replace("<REPORT_DIR>", tmpdir)
            .replace("<REPORT_NAME>", os.path.basename(report))
            for flag in declared_flags
        ]
        env: Dict[str, str] = {}
        if declared_format == "playwright-json":
            env["PLAYWRIGHT_JSON_OUTPUT_NAME"] = report
        return args, env, report, declared_format

    if kind == "vitest":
        report = os.path.join(tmpdir, "qa-report-{0}.json".format(attempt))
        return (
            ["--reporter=default", "--reporter=json", "--outputFile={0}".format(report)],
            {},
            report,
            "vitest-json",
        )
    if kind == "jest":
        report = os.path.join(tmpdir, "qa-report-{0}.json".format(attempt))
        return (["--json", "--outputFile={0}".format(report)], {}, report, "jest-json")
    if kind == "playwright":
        report = os.path.join(tmpdir, "qa-report-{0}.json".format(attempt))
        return (
            ["--reporter=list,json"],
            {"PLAYWRIGHT_JSON_OUTPUT_NAME": report},
            report,
            "playwright-json",
        )
    if kind == "dotnet":
        name = "qa-report-{0}.trx".format(attempt)
        report = os.path.join(tmpdir, name)
        return (
            ["--logger", "trx;LogFileName={0}".format(name), "--results-directory", tmpdir],
            {},
            report,
            "trx",
        )
    return [], {}, None, None


def _append_args(argv: Sequence[str], extra: Sequence[str]) -> List[str]:
    """Append runner flags, inserting ``--`` for package-manager script wrappers."""

    result = [str(item) for item in argv]
    if not extra:
        return result
    first = os.path.basename(result[0]).lower() if result else ""
    if first.split(".")[0] in _SCRIPT_RUNNERS and "--" not in result:
        result = result + ["--"]
    return result + [str(item) for item in extra]


def _targeted_args(kind: str, failures: Sequence[Dict[str, Any]]) -> Optional[List[str]]:
    """Flags that re-run only the failed tests, or ``None`` when unsupported."""

    reruns = [f.get("_rerun") or {} for f in failures]
    if kind in ("vitest", "jest"):
        files = sorted(set(str(r["file"]) for r in reruns if r.get("file")))
        names = sorted(set(str(r["name"]) for r in reruns if r.get("name")))
        if not files and not names:
            return None
        args = list(files)
        if names:
            args += ["-t", "|".join(re.escape(name) for name in names)]
        return args
    if kind == "playwright":
        return ["--last-failed"] if failures else None
    if kind == "dotnet":
        fqns = sorted(set(str(r["fqn"]) for r in reruns if r.get("fqn")))
        if not fqns:
            return None
        return ["--filter", "|".join("FullyQualifiedName~{0}".format(f) for f in fqns)]
    return None


def _reproduce(cwd_rel: str, argv: Sequence[str]) -> str:
    """A copy-pasteable shell line for a human."""

    command = shlex.join([str(item) for item in argv])
    if cwd_rel and cwd_rel != ".":
        return "cd {0} && {1}".format(cwd_rel, command)
    return command


def _finding_reproduce(
    kind: str, argv_base: Sequence[str], cwd_rel: str, rerun: Dict[str, Any]
) -> str:
    """The narrowest reproduce command for a single failing test."""

    extra: List[str] = []
    if kind in ("vitest", "jest"):
        if rerun.get("file"):
            extra.append(str(rerun["file"]))
        if rerun.get("name"):
            extra += ["-t", str(rerun["name"])]
    elif kind == "playwright":
        if rerun.get("file"):
            extra.append(str(rerun["file"]))
        if rerun.get("name"):
            extra += ["-g", str(rerun["name"])]
    elif kind == "dotnet":
        if rerun.get("fqn"):
            extra += ["--filter", "FullyQualifiedName~{0}".format(rerun["fqn"])]
    if not extra:
        return _reproduce(cwd_rel, argv_base)
    return _reproduce(cwd_rel, _append_args(argv_base, extra))


# ---------------------------------------------------------------------------
# Normalized findings
# ---------------------------------------------------------------------------


def _int(value: Any, default: int = 0) -> int:
    """Best-effort integer coercion; report fields are never trusted blindly."""

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clip(text: Any, limit: int = _MAX_MESSAGE_CHARS) -> str:
    value = "" if text is None else str(text)
    value = _ANSI_RE.sub("", value).strip()
    if len(value) > limit:
        return value[:limit] + " ... [truncated]"
    return value


def finding(
    source: str,
    name: str,
    file: str,
    line: int = 0,
    message: str = "",
    **extra: Any
) -> Dict[str, Any]:
    """Build a normalized finding dict in the contract's key order."""

    test_id = extra.get("test_id")
    document = {
        "source": source,
        "rule": extra.get("rule"),
        "testId": test_id,
        "name": name,
        "file": file,
        "line": int(line or 0),
        "target": extra.get("target", test_id),
        "impact": extra.get("impact"),
        "message": message,
        "expected": extra.get("expected"),
        "actual": extra.get("actual"),
        "requirementRef": extra.get("requirement_ref"),
        "statedCriterion": bool(extra.get("stated_criterion", False)),
        "flaky": bool(extra.get("flaky", False)),
        "helpUrl": extra.get("help_url"),
        "reproduce": extra.get("reproduce"),
        "suggestedFix": extra.get("suggested_fix"),
    }
    rerun = extra.get("rerun")
    if rerun:
        document["_rerun"] = rerun
    return document


def _flake_finding(source_finding: Dict[str, Any], layer: str) -> Dict[str, Any]:
    """A failure that passed on retry: recorded as a flake, never as a pass."""

    flake = dict(source_finding)
    flake["source"] = "flake"
    flake["flaky"] = True
    flake["name"] = "Flaky test: {0}".format(source_finding.get("name") or "unnamed test")
    flake["message"] = _clip(
        "This test failed and then passed on an unchanged re-run in the {0} layer, so its "
        "result is not trustworthy. First failure:\n{1}".format(
            layer, source_finding.get("message") or "(no message captured)"
        )
    )
    return flake


def _coarse_finding(
    layer: str,
    target: Dict[str, Any],
    cwd_rel: str,
    exit_code: int,
    tail: Sequence[str],
    timed_out: bool,
    timeout_seconds: int,
    reproduce: Optional[str],
) -> Dict[str, Any]:
    """The never-drop-a-failure fallback, built from the tail of the layer log."""

    lines = [line for line in tail if line.strip()][-_COARSE_TAIL_LINES:]
    body = "\n".join(lines) or "(no output captured)"
    project = str(target.get("project") or "").strip()
    where = " ({0})".format(project) if project else ""
    if timed_out:
        name = "{0} layer timed out after {1}s{2}".format(layer, timeout_seconds, where)
        message = (
            "The runner was killed with its process group after the per-layer timeout of "
            "{0}s. Last output:\n{1}".format(timeout_seconds, body)
        )
    else:
        name = "{0} layer failed with exit code {1}{2}".format(layer, exit_code, where)
        message = (
            "The runner exited {0} and produced no machine-readable failure report, so this "
            "finding carries the raw output instead. Last output:\n{1}".format(exit_code, body)
        )
    test_dirs = [str(d) for d in (target.get("testDirs") or []) if d]
    return finding(
        layer,
        name,
        test_dirs[0] if test_dirs else cwd_rel,
        0,
        _clip(message),
        reproduce=reproduce,
        # A coarse finding has no rule and no test id, so without a discriminating
        # target every coarse failure in a layer would share one fingerprint --
        # baselining a single one would then mask every future failure in that
        # layer. Bind the fingerprint to the target AND the failure's own shape.
        target="{0}:{1}#{2}".format(
            project or "-",
            str(target.get("runner") or "-"),
            _failure_signature(lines, timed_out),
        ),
    )


# Volatile fragments that must not enter a fingerprint: durations, counts, temp
# paths, hex ids, and line/column markers all differ run to run for one defect.
_VOLATILE = re.compile(
    r"""(
        \d+\.\d+m?s | \b\d+\s*ms\b            # durations
      | /(?:private/)?(?:tmp|var/folders)/\S+ # temp paths
      | \b[0-9a-f]{7,}\b                      # hashes / ids
      | :\d+:\d+\b | \bline\s+\d+\b           # line:col markers
      | \b\d+\b                               # bare counts
    )""",
    re.VERBOSE | re.IGNORECASE,
)


def _failure_signature(lines: Sequence[str], timed_out: bool) -> str:
    """A short, run-stable digest of what actually broke.

    Only the RUNNER's own output counts. Every line qa writes into the layer log
    is prefixed ``=== `` (the attempt banner, the command, the cwd, the env), and
    those are identical for every failure of a given layer+target -- digesting one
    would hand every coarse failure the same fingerprint, which is the collision
    this signature exists to prevent.
    """

    if timed_out:
        return "timeout"
    for raw in lines:
        text = str(raw).strip()
        if not text or text.startswith("==="):
            continue
        text = _VOLATILE.sub("#", text).strip()
        if len(text) >= 8:
            return common.sha256_fp(text).split(":", 1)[-1][:12]
    return "unclassified"


# ---------------------------------------------------------------------------
# Report parsing
# ---------------------------------------------------------------------------


def _parse_report(
    ctx: "common.Context",
    context: Dict[str, Any],
    report_format: Optional[str],
    report_path: Optional[str],
    timed_out: bool,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Parse the runner's report into findings; never raise on a malformed report."""

    if timed_out:
        # The process was killed mid-write; a half-written report is not trustworthy.
        return [], []
    if not report_format or not report_path or not os.path.isfile(report_path):
        return [], []
    try:
        if report_format == "trx":
            return _parse_trx(ctx, context, report_path)
        payload = common.read_json(report_path, default=None)
        if not isinstance(payload, dict):
            return [], []
        if report_format == "playwright-json":
            return _parse_playwright(ctx, context, payload)
        if report_format in ("vitest-json", "jest-json"):
            return _parse_vitest(ctx, context, payload)
    except common.QaError:
        return [], []
    except (OSError, ValueError, ElementTree.ParseError):  # pragma: no cover - defensive
        return [], []
    return [], []


def _repo_path(ctx: "common.Context", raw: Any, cwd_abs: pathlib.Path) -> str:
    """A runner-reported path as a repo-relative POSIX path.

    Runners print absolute paths that may travel through a symlinked prefix (macOS
    ``/tmp`` and ``/var``, container mounts, ``/home`` links), so a ``..`` result is
    retried against the resolved paths before it is accepted.
    """

    if not raw:
        return ""
    path = pathlib.Path(str(raw))
    if not path.is_absolute():
        path = cwd_abs / path
    relative = common.repo_rel(ctx.repo, path)
    if relative.startswith(".."):
        resolved = common.repo_rel(
            pathlib.Path(os.path.realpath(str(ctx.repo))),
            pathlib.Path(os.path.realpath(str(path))),
        )
        if not resolved.startswith(".."):
            return resolved
    return relative


def _runner_path(ctx: "common.Context", repo_relative: str, cwd_abs: pathlib.Path) -> str:
    """A repo-relative path expressed relative to the runner's cwd."""

    if not repo_relative:
        return ""
    absolute = os.path.abspath(str(ctx.repo / repo_relative))
    try:
        return pathlib.PurePath(os.path.relpath(absolute, str(cwd_abs))).as_posix()
    except ValueError:  # pragma: no cover - different drives on Windows
        return repo_relative


def _js_location(message: str, file_hint: str) -> int:
    """First line number in a JS/TS stack trace, preferring the failing test file."""

    best = 0
    base = os.path.basename(file_hint) if file_hint else ""
    for match in _JS_LOCATION_RE.finditer(message or ""):
        path, line = match.group(1), int(match.group(2))
        if base and os.path.basename(path) == base:
            return line
        if not best:
            best = line
    return best


def _expect_pair(message: str) -> Tuple[Optional[str], Optional[str]]:
    for line in (message or "").split("\n"):
        match = _EXPECT_RE.search(line.strip())
        if match:
            return (
                _clip(match.group("expected"), _MAX_VALUE_CHARS),
                _clip(match.group("actual"), _MAX_VALUE_CHARS),
            )
    return None, None


def _parse_vitest(
    ctx: "common.Context", context: Dict[str, Any], payload: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """vitest/jest ``--reporter=json`` output -> normalized findings."""

    layer = context["layer"]
    kind = context["kind"]
    cwd_abs = context["cwd_abs"]
    cwd_rel = context["cwd_rel"]
    argv_base = context["argv_base"]
    failures: List[Dict[str, Any]] = []

    suites = payload.get("testResults")
    if not isinstance(suites, list):
        return failures, []

    for suite in suites:
        if not isinstance(suite, dict):
            continue
        file_repo = _repo_path(ctx, suite.get("name"), cwd_abs)
        file_runner = _runner_path(ctx, file_repo, cwd_abs)
        assertions = suite.get("assertionResults")
        assertions = assertions if isinstance(assertions, list) else []
        seen = False
        for assertion in assertions:
            if not isinstance(assertion, dict) or assertion.get("status") != "failed":
                continue
            seen = True
            title = str(assertion.get("title") or "").strip()
            ancestors = [str(a) for a in (assertion.get("ancestorTitles") or []) if a]
            full_name = str(assertion.get("fullName") or "").strip()
            if not full_name:
                full_name = " > ".join(ancestors + ([title] if title else []))
            message = _clip("\n".join(str(m) for m in (assertion.get("failureMessages") or [])))
            location = assertion.get("location")
            line = _int(location.get("line")) if isinstance(location, dict) else 0
            if not line:
                line = _js_location(message, file_repo)
            expected, actual = _expect_pair(message)
            rerun = {"file": file_runner, "name": title or full_name}
            failures.append(
                finding(
                    layer,
                    full_name or "unnamed test",
                    file_repo,
                    line,
                    message or "test failed without a message",
                    test_id="{0}::{1}".format(file_repo, full_name),
                    expected=expected,
                    actual=actual,
                    reproduce=_finding_reproduce(kind, argv_base, cwd_rel, rerun),
                    rerun=rerun,
                )
            )
        if not seen and str(suite.get("status") or "") == "failed":
            message = _clip(suite.get("message") or "the test file failed to run")
            rerun = {"file": file_runner}
            failures.append(
                finding(
                    layer,
                    "{0} failed to run".format(file_repo or "test file"),
                    file_repo,
                    _js_location(message, file_repo),
                    message,
                    test_id="{0}::<file>".format(file_repo),
                    reproduce=_finding_reproduce(kind, argv_base, cwd_rel, rerun),
                    rerun=rerun,
                )
            )
    return failures, []


def _parse_playwright(
    ctx: "common.Context", context: Dict[str, Any], payload: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """playwright ``--reporter=json`` output -> normalized findings and native flakes."""

    layer = context["layer"]
    kind = context["kind"]
    cwd_abs = context["cwd_abs"]
    cwd_rel = context["cwd_rel"]
    argv_base = context["argv_base"]
    failures: List[Dict[str, Any]] = []
    flakes: List[Dict[str, Any]] = []

    def spec_finding(spec: Dict[str, Any], titles: List[str], test: Dict[str, Any]) -> Dict[str, Any]:
        title = str(spec.get("title") or "").strip()
        full_name = " > ".join([t for t in titles if t] + ([title] if title else []))
        results = [r for r in (test.get("results") or []) if isinstance(r, dict)]
        error: Dict[str, Any] = {}
        for result in results:
            candidate = result.get("error")
            if isinstance(candidate, dict) and candidate:
                error = candidate
        message = _clip(
            "\n".join(
                str(part)
                for part in (error.get("message"), error.get("stack"))
                if part
            )
            or "the spec failed without an error message"
        )
        location = error.get("location") if isinstance(error.get("location"), dict) else {}
        file_repo = _repo_path(ctx, location.get("file") or spec.get("file"), cwd_abs)
        line = _int(location.get("line")) or _int(spec.get("line"))
        expected, actual = _expect_pair(message)
        rerun = {"file": str(spec.get("file") or ""), "name": title}
        return finding(
            layer,
            full_name or title or "unnamed spec",
            file_repo,
            line,
            message,
            test_id="{0}::{1}".format(file_repo, full_name or title),
            expected=expected,
            actual=actual,
            reproduce=_finding_reproduce(kind, argv_base, cwd_rel, rerun),
            rerun=rerun,
        )

    def walk(suite: Any, titles: List[str], depth: int) -> None:
        if not isinstance(suite, dict):
            return
        title = str(suite.get("title") or "")
        chain = titles if depth == 0 else titles + [title]
        for spec in suite.get("specs") or []:
            if not isinstance(spec, dict):
                continue
            for test in spec.get("tests") or []:
                if not isinstance(test, dict):
                    continue
                status = str(test.get("status") or "")
                if status == "unexpected":
                    failures.append(spec_finding(spec, chain, test))
                elif status == "flaky":
                    flakes.append(_flake_finding(spec_finding(spec, chain, test), layer))
        for child in suite.get("suites") or []:
            walk(child, chain, depth + 1)

    for suite in payload.get("suites") or []:
        walk(suite, [], 0)

    for error in payload.get("errors") or []:
        if not isinstance(error, dict):
            continue
        location = error.get("location") if isinstance(error.get("location"), dict) else {}
        message = _clip(error.get("message") or "playwright reported a run-level error")
        failures.append(
            finding(
                layer,
                "playwright run-level error",
                _repo_path(ctx, location.get("file"), cwd_abs) or cwd_rel,
                _int(location.get("line")),
                message,
                reproduce=_reproduce(cwd_rel, argv_base),
            )
        )
    return failures, flakes


def _local_tag(tag: Any) -> str:
    text = str(tag)
    return text.rsplit("}", 1)[-1]


def _parse_trx(
    ctx: "common.Context", context: Dict[str, Any], report_path: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """VSTest TRX (``dotnet test --logger trx``) -> normalized findings."""

    layer = context["layer"]
    kind = context["kind"]
    cwd_abs = context["cwd_abs"]
    cwd_rel = context["cwd_rel"]
    argv_base = context["argv_base"]
    target = context["target"]
    failures: List[Dict[str, Any]] = []

    root = ElementTree.parse(report_path).getroot()
    for element in root.iter():
        if _local_tag(element.tag) != "UnitTestResult":
            continue
        if str(element.get("outcome") or "").lower() != "failed":
            continue
        name = str(element.get("testName") or "unnamed test")
        message = ""
        stack = ""
        for child in element.iter():
            local = _local_tag(child.tag)
            if local == "Message" and child.text and not message:
                message = child.text
            elif local == "StackTrace" and child.text and not stack:
                stack = child.text
        combined = _clip("\n".join(part for part in (message, stack) if part))
        file_repo = ""
        line = 0
        match = _CS_LOCATION_RE.search(stack or "")
        if match:
            file_repo = _repo_path(ctx, match.group(1), cwd_abs)
            line = _int(match.group(2))
        if not file_repo:
            test_dirs = [str(d) for d in (target.get("testDirs") or []) if d]
            file_repo = test_dirs[0] if test_dirs else cwd_rel
        fqn = name.split("(")[0].strip()
        expected, actual = _expect_pair(combined)
        rerun = {"fqn": fqn}
        failures.append(
            finding(
                layer,
                name,
                file_repo,
                line,
                combined or "the test failed without a message",
                test_id=fqn or name,
                expected=expected,
                actual=actual,
                reproduce=_finding_reproduce(kind, argv_base, cwd_rel, rerun),
                rerun=rerun,
            )
        )
    return failures, []


# ---------------------------------------------------------------------------
# Verdict, redaction, human summary
# ---------------------------------------------------------------------------


def _verdict(
    layers: Sequence[Dict[str, Any]],
    skipped: Sequence[Dict[str, str]],
    config: Dict[str, Any],
) -> Tuple[str, List[str]]:
    """``pass`` iff every executed layer exited zero and no test is flaky."""

    gate = config.get("gate") or {}
    reasons: List[str] = []
    for entry in layers:
        if entry.get("status") == STATUS_FAILED:
            reasons.append(
                "layer {0} failed (exit {1}, {2} failure(s))".format(
                    entry.get("layer"), entry.get("exitCode"), len(entry.get("failures") or [])
                )
            )
        elif entry.get("status") == STATUS_FLAKY:
            if str(gate.get("flaky", "fail")).lower() == "warn":
                continue
            reasons.append(
                "layer {0} reported {1} flaky test(s)".format(
                    entry.get("layer"), len(entry.get("flakes") or [])
                )
            )
    if skipped and str(gate.get("skippedLayers", "warn")).lower() == "fail":
        for item in skipped:
            reasons.append(
                'layer {0} was skipped ({1}) and gate.skippedLayers is "fail"'.format(
                    item.get("layer"), item.get("reason")
                )
            )
    return ("fail" if reasons else "pass"), reasons


def _clean(obj: Any) -> Any:
    """Redact every string and drop internal ``_``-prefixed keys before persisting."""

    if isinstance(obj, dict):
        return {
            key: _clean(value)
            for key, value in obj.items()
            if not str(key).startswith("_")
        }
    if isinstance(obj, list):
        return [_clean(item) for item in obj]
    if isinstance(obj, str):
        return common.redact(obj)
    return obj


def _seconds(value: float) -> str:
    return "{0:.1f}s".format(max(0.0, float(value)))


def _human_summary(ctx: "common.Context", document: Dict[str, Any]) -> None:
    """The colour-free verdict block on stderr."""

    verdict = str(document.get("verdict") or "fail").upper()
    skipped = document.get("skippedLayers") or []
    if verdict == "PASS" and skipped:
        detail = "; ".join(
            "{0}: {1}".format(item.get("layer"), _skip_status(document, item))
            for item in skipped
        )
        headline = "PASS — INCOMPLETE ({0})".format(detail)
    else:
        headline = verdict
    ctx.note("verdict: {0}".format(headline))
    for entry in document.get("layers") or []:
        ctx.note(
            "  layer {0}: {1} (exit {2}, {3} failure(s), {4} flake(s)) -> {5}".format(
                entry.get("layer"),
                entry.get("status"),
                entry.get("exitCode"),
                len(entry.get("failures") or []),
                len(entry.get("flakes") or []),
                entry.get("log"),
            )
        )
    for reason in document.get("verdictReasons") or []:
        ctx.note("  reason: {0}".format(reason))
    ctx.note("run directory: {0}".format(document.get("runDir")))


def _skip_status(document: Dict[str, Any], item: Dict[str, Any]) -> str:
    for entry in document.get("layers") or []:
        if entry.get("layer") == item.get("layer"):
            return str(entry.get("status") or STATUS_SKIPPED)
    return "skipped"


__all__ = [
    "COMMAND",
    "HELP",
    "STATUS_FAILED",
    "STATUS_FLAKY",
    "STATUS_PASSED",
    "STATUS_SKIPPED",
    "add_arguments",
    "execute_layers",
    "finding",
    "run",
]
