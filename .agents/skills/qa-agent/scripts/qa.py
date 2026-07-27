#!/usr/bin/env python3
"""QA Agent command-line dispatcher.

Every subcommand lives in a sibling module (``qa_stack``, ``qa_scope``,
``qa_round``, ``qa_exec``, ``qa_findings``, ``qa_baseline``, ``qa_suppress``);
this file only discovers them, wires the global flags, builds the execution
context and maps errors onto the shared exit-code table.

stdout is always JSON. Human prose and progress go to stderr. A sibling module
that fails to import is reported and skipped, so a partially installed bundle
still runs the commands it does have -- pass ``--strict-imports`` to make that
fatal instead.
"""

from __future__ import annotations

import argparse
import importlib
import io
import os
import pathlib
import sys
import traceback
import unittest
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

try:
    from . import qa_common as common
except ImportError:  # pragma: no cover - direct script execution
    import qa_common as common


BUNDLE_VERSION = "1.0.0"

#: Sibling modules that contribute subcommands, in the order they are listed in
#: the implementation contract.
MODULE_NAMES: Tuple[str, ...] = (
    "qa_stack",
    "qa_scope",
    "qa_round",
    "qa_exec",
    "qa_findings",
    "qa_baseline",
    "qa_suppress",
)

EXIT_CODES: Tuple[Tuple[int, str, str], ...] = (
    (common.OK, "OK", "success / verdict pass"),
    (common.FAIL, "FAIL", "verdict fail (findings exist)"),
    (common.USAGE, "USAGE", "bad arguments"),
    (common.NO_STACK, "NO_STACK", "no test stack detectable - stop and report"),
    (common.EMPTY_SCOPE, "EMPTY_SCOPE", "scope resolved to nothing"),
    (common.INVALID_SUPPRESSION, "INVALID_SUPPRESSION", "a suppression is malformed"),
    (common.SEALED_ROUND, "SEALED_ROUND", "attempt to mutate a sealed round"),
    (common.RUNTIME_ERROR, "RUNTIME_ERROR", "unexpected internal error"),
)


def _epilog() -> str:
    """The contract, readable from ``--help`` alone."""

    lines = [
        "layer order:",
        "  " + " -> ".join(common.LAYER_ORDER),
        "  Layers run in that order and a failing layer never stops the ones after",
        "  it, so a single round reports every problem it can find.",
        "",
        "exit codes:",
    ]
    for code, name, meaning in EXIT_CODES:
        lines.append("  {0}  {1:<20} {2}".format(code, name, meaning))
    lines.extend(
        [
            "",
            "output:",
            "  stdout carries the JSON document (always, --json or not).",
            "  stderr carries human prose and per-layer progress; --json silences the",
            "  prose but never the progress.",
            "",
            "global flags (--repo, --qa-dir, --config, --json, --strict-imports) are",
            "accepted both before and after the subcommand.",
            "",
            "typical round:",
            "  qa.py detect > /tmp/stack.json",
            "  qa.py scope --diff > /tmp/scope.json",
            "  qa.py round new",
            "  qa.py exec --round 1",
            "  qa.py report --round 1",
        ]
    )
    return "\n".join(lines)


class CommandEntry:
    """One registered subcommand."""

    def __init__(
        self,
        name: str,
        help_text: str,
        add_arguments: Optional[Callable[[argparse.ArgumentParser], None]],
        run: Callable[[argparse.Namespace, Any], Optional[int]],
        module: str,
    ) -> None:
        self.name = name
        self.help = help_text or ""
        self.add_arguments = add_arguments
        self.run = run
        self.module = module


def _entries_from_module(module: Any, module_name: str) -> List[CommandEntry]:
    """Read a module's ``COMMANDS`` list, or its singular ``COMMAND`` triple."""

    plural = getattr(module, "COMMANDS", None)
    entries: List[CommandEntry] = []

    if plural:
        for index, item in enumerate(plural):
            try:
                parts = list(item)
            except TypeError:
                raise ValueError("COMMANDS[{0}] is not a sequence".format(index))
            if len(parts) < 4:
                raise ValueError(
                    "COMMANDS[{0}] must be (name, help, add_arguments, run)".format(index)
                )
            name, help_text, add_args, run_fn = parts[0], parts[1], parts[2], parts[3]
            if not isinstance(name, str) or not name:
                raise ValueError("COMMANDS[{0}] has no subcommand name".format(index))
            if not callable(run_fn):
                raise ValueError("COMMANDS[{0}] ({1}) has no callable run()".format(index, name))
            if add_args is not None and not callable(add_args):
                raise ValueError("COMMANDS[{0}] ({1}) add_arguments is not callable".format(index, name))
            entries.append(CommandEntry(name, help_text, add_args, run_fn, module_name))
        return entries

    name = getattr(module, "COMMAND", None)
    if not isinstance(name, str) or not name:
        raise ValueError("module declares neither COMMAND nor COMMANDS")
    run_fn = getattr(module, "run", None)
    if not callable(run_fn):
        raise ValueError("module declares COMMAND but no callable run()")
    add_args = getattr(module, "add_arguments", None)
    if add_args is not None and not callable(add_args):
        raise ValueError("module add_arguments is not callable")
    entries.append(CommandEntry(name, getattr(module, "HELP", ""), add_args, run_fn, module_name))
    return entries


def load_command_modules(
    names: Sequence[str] = MODULE_NAMES,
) -> Tuple[List[CommandEntry], List[Tuple[str, str]]]:
    """Import every command module, collecting failures instead of raising."""

    entries: List[CommandEntry] = []
    errors: List[Tuple[str, str]] = []
    seen: Dict[str, str] = {}

    for module_name in names:
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001 - a broken sibling must not kill the CLI
            errors.append((module_name, "{0}: {1}".format(type(exc).__name__, exc)))
            continue
        try:
            found = _entries_from_module(module, module_name)
        except Exception as exc:  # noqa: BLE001
            errors.append((module_name, "{0}: {1}".format(type(exc).__name__, exc)))
            continue
        for entry in found:
            if entry.name in seen:
                errors.append(
                    (
                        module_name,
                        "subcommand '{0}' already provided by {1}".format(
                            entry.name, seen[entry.name]
                        ),
                    )
                )
                continue
            seen[entry.name] = module_name
            entries.append(entry)

    return entries, errors


# ---------------------------------------------------------------------------
# selftest (owned by this module)
# ---------------------------------------------------------------------------

SELFTEST_HELP = "Run the bundled unittest suite and print a JSON summary."


def add_selftest_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--pattern",
        default="test_*.py",
        metavar="GLOB",
        help="test file pattern to discover (default: test_*.py)",
    )


def run_selftest(args: argparse.Namespace, ctx: Any) -> int:
    scripts_dir = pathlib.Path(_SCRIPTS_DIR)
    tests_dir = scripts_dir / "tests"
    summary = {
        "schemaVersion": common.SCHEMA_VERSION,
        "tests": 0,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "passed": True,
    }

    if not tests_dir.is_dir():
        ctx.note("no bundled tests directory at {0} - nothing to run".format(tests_dir.as_posix()))
        ctx.emit(summary)
        return common.OK

    loader = unittest.TestLoader()
    try:
        suite = loader.discover(
            start_dir=str(tests_dir),
            pattern=getattr(args, "pattern", "test_*.py"),
            top_level_dir=str(scripts_dir),
        )
    except Exception as exc:  # noqa: BLE001
        raise common.QaError("cannot discover bundled tests: {0}".format(exc))

    buffer = io.StringIO()
    result = unittest.TextTestRunner(stream=buffer, verbosity=2).run(suite)

    summary["tests"] = int(result.testsRun)
    summary["failures"] = len(result.failures)
    summary["errors"] = len(result.errors)
    summary["skipped"] = len(getattr(result, "skipped", []))
    summary["passed"] = bool(result.wasSuccessful())

    detail = buffer.getvalue().strip()
    if detail and not ctx.json_only:
        sys.stderr.write(detail + "\n")
    ctx.note(
        "selftest tests={0} failures={1} errors={2} skipped={3} verdict={4}".format(
            summary["tests"],
            summary["failures"],
            summary["errors"],
            summary["skipped"],
            "PASS" if summary["passed"] else "FAIL",
        )
    )
    ctx.emit(summary)
    return common.OK if summary["passed"] else common.FAIL


SELFTEST_ENTRY = CommandEntry("selftest", SELFTEST_HELP, add_selftest_arguments, run_selftest, "qa")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def build_global_parser() -> argparse.ArgumentParser:
    """The flags every subcommand shares, accepted before and after the command.

    Defaults are ``SUPPRESS`` so that a value parsed before the subcommand is not
    clobbered by the subparser's own default.
    """

    parser = argparse.ArgumentParser(add_help=False)
    group = parser.add_argument_group("global options")
    group.add_argument(
        "--repo",
        metavar="PATH",
        default=argparse.SUPPRESS,
        help="repository root (default: the git toplevel of the cwd, else the cwd)",
    )
    group.add_argument(
        "--qa-dir",
        metavar="PATH",
        default=argparse.SUPPRESS,
        help="QA output directory; relative paths resolve against the repo (default: <repo>/qa)",
    )
    group.add_argument(
        "--config",
        metavar="PATH",
        default=argparse.SUPPRESS,
        help="optional config file (default: <qa-dir>/qa.config.json); a missing file is fine",
    )
    group.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="suppress the stderr prose; stdout is JSON either way",
    )
    group.add_argument(
        "--strict-imports",
        action="store_true",
        default=argparse.SUPPRESS,
        help="fail instead of warning when a command module cannot be imported",
    )
    return parser


def build_parser(
    entries: Sequence[CommandEntry], errors: Optional[Sequence[Tuple[str, str]]] = None
) -> argparse.ArgumentParser:
    """Build the root parser plus one subparser per registered command."""

    global_parser = build_global_parser()
    parser = argparse.ArgumentParser(
        prog="qa.py",
        description="QA Agent - detect the test stack, plan, execute and report a findings round.",
        epilog=_epilog(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[global_parser],
    )
    parser.add_argument(
        "--version",
        action="version",
        version="qa-agent {0} (schemaVersion {1})".format(BUNDLE_VERSION, common.SCHEMA_VERSION),
    )

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    for entry in entries:
        sub = subparsers.add_parser(
            entry.name,
            help=entry.help,
            description=entry.help,
            parents=[global_parser],
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        if entry.add_arguments is not None:
            try:
                entry.add_arguments(sub)
            except Exception as exc:  # noqa: BLE001 - keep the rest of the CLI usable
                sys.stderr.write(
                    "[qa] warning: {0} could not declare arguments for '{1}' ({2}: {3})\n".format(
                        entry.module, entry.name, type(exc).__name__, exc
                    )
                )
        sub.set_defaults(_entry=entry)

    for module_name, message in errors or ():
        sys.stderr.write(
            "[qa] warning: command module {0} unavailable ({1})\n".format(module_name, message)
        )
    return parser


# ---------------------------------------------------------------------------
# Context construction
# ---------------------------------------------------------------------------


def resolve_repo(value: Optional[str]) -> pathlib.Path:
    """``--repo`` when given, else the git toplevel of the cwd, else the cwd."""

    if value:
        return pathlib.Path(os.path.abspath(os.path.expanduser(str(value))))
    cwd = pathlib.Path(os.path.abspath(os.getcwd()))
    code, out, _ = common.run_git(cwd, "rev-parse", "--show-toplevel")
    toplevel = out.strip()
    if code == 0 and toplevel:
        return pathlib.Path(os.path.abspath(toplevel))
    return cwd


def _resolve_against(repo: pathlib.Path, value: str) -> pathlib.Path:
    path = pathlib.Path(os.path.expanduser(str(value)))
    if not path.is_absolute():
        path = repo / path
    return pathlib.Path(os.path.abspath(str(path)))


def build_context(args: argparse.Namespace) -> Any:
    """Resolve repo, output directory and configuration into a :class:`Context`."""

    repo = resolve_repo(getattr(args, "repo", None))
    if not repo.is_dir():
        raise common.QaError("repository path is not a directory: {0}".format(repo), common.USAGE)

    qa_dir_arg = getattr(args, "qa_dir", None)
    config_arg = getattr(args, "config", None)

    bootstrap_qa_dir = (
        _resolve_against(repo, qa_dir_arg)
        if qa_dir_arg
        else repo / str(common.DEFAULT_CONFIG["outputDir"])
    )
    config_path = (
        _resolve_against(repo, config_arg) if config_arg else bootstrap_qa_dir / "qa.config.json"
    )

    config = common.load_config(config_path, repo)

    if qa_dir_arg:
        qa_dir = bootstrap_qa_dir
    else:
        qa_dir = repo / str(config.get("outputDir") or common.DEFAULT_CONFIG["outputDir"])

    return common.Context(
        repo=repo,
        qa_dir=qa_dir,
        config=config,
        json_only=bool(getattr(args, "json", False)),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    strict = "--strict-imports" in argv

    entries, errors = load_command_modules()
    if strict and errors:
        for module_name, message in errors:
            sys.stderr.write(
                "[qa] error: command module {0} unavailable ({1})\n".format(module_name, message)
            )
        sys.stderr.write(
            "[qa] error: --strict-imports: {0} command module(s) failed to load\n".format(
                len(errors)
            )
        )
        return common.RUNTIME_ERROR

    entries = list(entries) + [SELFTEST_ENTRY]
    parser = build_parser(entries, errors)
    args = parser.parse_args(argv)

    entry = getattr(args, "_entry", None)
    if entry is None:
        parser.print_help(sys.stderr)
        sys.stderr.write("\n[qa] error: a subcommand is required\n")
        return common.USAGE

    try:
        ctx = build_context(args)
        code = entry.run(args, ctx)
    except common.QaError as exc:
        sys.stderr.write("[qa] error: {0}\n".format(exc.message))
        return exc.code
    except KeyboardInterrupt:
        sys.stderr.write("[qa] error: interrupted\n")
        return common.RUNTIME_ERROR
    except Exception:  # noqa: BLE001 - unexpected: show the trace, return RUNTIME_ERROR
        sys.stderr.write(traceback.format_exc())
        sys.stderr.write(
            "[qa] error: unexpected internal error in '{0}' ({1})\n".format(entry.name, entry.module)
        )
        return common.RUNTIME_ERROR

    return common.OK if code is None else int(code)


if __name__ == "__main__":
    sys.exit(main())
