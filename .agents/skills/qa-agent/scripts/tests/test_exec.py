"""Contract tests for ``qa_exec`` (QA Agent contract sections 2, 3.4 and 4).

Layers run in the order unit -> integration -> e2e -> a11y, a failing layer never
stops the ones after it, unavailable layers are skipped rather than failed, a
test that only passes on retry is flaky (never passed), timeouts surface as exit
124, and nothing secret ever reaches a log.

Every "runner" here is a short-lived ``python -c`` script, so no npm, dotnet or
playwright process is ever launched.
"""

import argparse
import contextlib
import io
import json
import os
import pathlib
import shlex
import sys
import tempfile
import unittest

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

try:  # pragma: no cover - package import
    from .. import qa_common as common
    from .. import qa_baseline
    from .. import qa_exec
except ImportError:  # pragma: no cover - direct script execution
    import qa_common as common
    import qa_baseline
    import qa_exec


RUN_ID = "20260725-140233"
A11Y_REASON = "axe tooling not installed (jest-axe, @axe-core/playwright)"


def _entry(module, name):
    commands = getattr(module, "COMMANDS", None)
    if commands:
        for entry in commands:
            if entry[0] == name:
                return entry[2], entry[3]
        raise AssertionError("{0} does not own the {1!r} subcommand".format(module, name))
    assert getattr(module, "COMMAND", None) == name, "COMMAND must be {0!r}".format(name)
    return module.add_arguments, module.run


def _marker_script(marker, label, exit_code):
    """A runner that records that it ran, prints a line, and exits deterministically."""
    return (
        'import sys; f = open("{marker}", "a"); f.write("{label}\\n"); f.close(); '
        'sys.stdout.write("{label} runner output\\n"); '
        'sys.stderr.write("{label} runner diagnostics\\n"); '
        "sys.exit({code})"
    ).format(marker=marker, label=label, code=exit_code)


def _flaky_script(counter, marker):
    """Fails on the first invocation, passes on every one after it."""
    return (
        'import os, sys; p = "{counter}"; '
        "n = (int(open(p).read()) if os.path.exists(p) else 0) + 1; "
        'f = open(p, "w"); f.write(str(n)); f.close(); '
        'g = open("{marker}", "a"); g.write("unit\\n"); g.close(); '
        'sys.stdout.write("attempt " + str(n) + "\\n"); '
        "sys.exit(1 if n == 1 else 0)"
    ).format(counter=counter, marker=marker)


def _secret_script():
    return (
        'import sys; sys.stdout.write("MY_API_TOKEN=supersecretvalue123\\n"); '
        'sys.stderr.write("Authorization: Bearer eyJab0123456789xyz\\n"); '
        "sys.exit(1)"
    )


def _sleep_script():
    return "import time; time.sleep(30)"


def _target(project, runner, command, cwd="."):
    return {
        "project": project,
        "runner": runner,
        "command": command,
        "cwd": cwd,
        "testDirs": [],
        "testGlobs": [],
        "reportFormat": None,
        "reportFlag": [],
    }


class ExecFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)
        (self.repo / "frontend").mkdir(parents=True, exist_ok=True)
        (self.repo / "backend").mkdir(parents=True, exist_ok=True)
        (self.repo / "qa" / "rounds" / "001").mkdir(parents=True, exist_ok=True)
        self.marker = (self.repo / "order.txt").as_posix()
        self.counter = (self.repo / "counter.txt").as_posix()

    # -- fixtures ----------------------------------------------------------

    def stack(self, unit_exit=0, integration_exit=0, e2e_exit=0, unit_command=None):
        unit = unit_command or [
            sys.executable,
            "-c",
            _marker_script(self.marker, "unit", unit_exit),
        ]
        return {
            "schemaVersion": 1,
            "repo": str(self.repo),
            "detected": True,
            "projects": [
                {
                    "id": "frontend",
                    "root": "frontend",
                    "language": "typescript",
                    "packageManager": "npm",
                    "markers": ["frontend/package.json"],
                }
            ],
            "layers": {
                "unit": {
                    "available": True,
                    "targets": [_target("frontend", "vitest", unit, cwd="frontend")],
                    "reason": None,
                },
                "integration": {
                    "available": True,
                    "targets": [
                        _target(
                            "backend",
                            "dotnet",
                            [
                                sys.executable,
                                "-c",
                                _marker_script(self.marker, "integration", integration_exit),
                            ],
                        )
                    ],
                    "reason": None,
                },
                "e2e": {
                    "available": True,
                    "targets": [
                        _target(
                            "frontend",
                            "playwright",
                            [
                                sys.executable,
                                "-c",
                                _marker_script(self.marker, "e2e", e2e_exit),
                            ],
                        )
                    ],
                    "reason": None,
                },
                "a11y": {"available": False, "targets": [], "reason": A11Y_REASON},
            },
            "conventions": {
                "testFileSuffixes": [".test.tsx"],
                "fileNaming": "kebab-case",
                "assertionLibraries": ["vitest"],
                "e2eFramework": "playwright",
                "componentTestLibrary": "@testing-library/react",
            },
            "runtimes": {
                "node": {"available": True, "version": "22.x"},
                "dotnet": {"available": True, "version": "10.x"},
                "headlessBrowser": {"available": False, "detail": "not installed"},
            },
            "notes": [],
        }

    def write_stack(self, stack):
        path = self.repo / "stack.json"
        path.write_text(json.dumps(stack, indent=2), encoding="utf-8")
        return path

    # -- invocation --------------------------------------------------------

    def exec_cli(self, stack, extra_argv=(), config=None, run_id=RUN_ID):
        stack_path = self.write_stack(stack)
        argv = [
            "--round",
            "1",
            "--stack",
            str(stack_path),
            "--run-id",
            run_id,
        ] + list(extra_argv)
        add_arguments, runner = _entry(qa_exec, "exec")
        parser = argparse.ArgumentParser(prog="qa.py exec")
        add_arguments(parser)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                namespace = argparse.Namespace(
                    repo=str(self.repo), qa_dir=None, config=None, json=True
                )
                args = parser.parse_args(argv, namespace)
                ctx = common.Context(repo=self.repo, config=config, json_only=True)
                code = runner(args, ctx)
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else common.USAGE
        stdout = out.getvalue()
        return code, (json.loads(stdout) if stdout.strip() else {}), err.getvalue()

    def run_dir(self, run_id=RUN_ID):
        return self.repo / "qa" / "rounds" / "001" / "runs" / run_id

    def run_json(self, run_id=RUN_ID):
        return json.loads((self.run_dir(run_id) / "run.json").read_text(encoding="utf-8"))

    def order(self):
        path = pathlib.Path(self.marker)
        if not path.is_file():
            return []
        return [line for line in path.read_text(encoding="utf-8").split("\n") if line]

    @staticmethod
    def layer(doc, name):
        for entry in doc.get("layers", []):
            if entry.get("layer") == name:
                return entry
        return None


class LayerOrderTest(ExecFixture):
    """Section 3.4.1/3.4.2: fixed layer order; a failure never stops the rest."""

    def test_layers_execute_in_the_contract_order(self):
        self.exec_cli(self.stack())
        self.assertEqual(self.order(), ["unit", "integration", "e2e"])

    def test_reported_layers_follow_the_contract_order(self):
        _, doc, _ = self.exec_cli(self.stack())
        reported = [entry["layer"] for entry in doc["layers"]]
        self.assertEqual(reported, [name for name in common.LAYER_ORDER if name in reported])
        self.assertEqual(reported[0], "unit")

    def test_a_failing_layer_does_not_stop_the_later_layers(self):
        code, doc, _ = self.exec_cli(
            self.stack(unit_exit=1, integration_exit=1), extra_argv=["--no-retry-failed"]
        )
        self.assertEqual(self.order(), ["unit", "integration", "e2e"])
        self.assertEqual(self.layer(doc, "e2e")["status"], "passed")
        self.assertEqual(self.layer(doc, "e2e")["exitCode"], 0)
        self.assertEqual(doc["verdict"], "fail")
        self.assertEqual(code, common.FAIL)

    def test_only_the_requested_layer_runs(self):
        self.exec_cli(self.stack(), extra_argv=["--layer", "unit"])
        self.assertEqual(self.order(), ["unit"])


class RunDocumentTest(ExecFixture):
    """Section 3.4: run.json shape and persistence."""

    def test_run_json_is_written_with_the_contract_keys(self):
        code, doc, _ = self.exec_cli(self.stack())
        self.assertEqual(code, common.OK)
        persisted = self.run_json()
        for key in (
            "schemaVersion",
            "round",
            "runId",
            "startedAt",
            "finishedAt",
            "repo",
            "layers",
            "verdict",
            "complete",
            "skippedLayers",
        ):
            self.assertIn(key, persisted)
        self.assertEqual(persisted["schemaVersion"], 1)
        self.assertEqual(persisted["round"], 1)
        self.assertEqual(persisted["runId"], RUN_ID)
        self.assertRegex(persisted["startedAt"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertRegex(persisted["finishedAt"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_stdout_document_matches_the_persisted_run(self):
        _, doc, _ = self.exec_cli(self.stack())
        self.assertEqual(doc["runId"], self.run_json()["runId"])
        self.assertEqual(doc["verdict"], self.run_json()["verdict"])

    def test_each_layer_entry_carries_the_contract_fields(self):
        _, doc, _ = self.exec_cli(self.stack())
        for entry in doc["layers"]:
            with self.subTest(layer=entry["layer"]):
                for key in (
                    "layer",
                    "status",
                    "exitCode",
                    "timedOut",
                    "retried",
                    "durationMs",
                    "command",
                    "cwd",
                    "reproduce",
                    "log",
                    "reason",
                    "failures",
                    "flakes",
                ):
                    self.assertIn(key, entry)
                self.assertIn(
                    entry["status"], ("passed", "failed", "flaky", "skipped-unavailable")
                )
                self.assertIsInstance(entry["failures"], list)
                self.assertIsInstance(entry["flakes"], list)

    def test_per_layer_logs_are_captured(self):
        self.exec_cli(self.stack())
        for layer in ("unit", "integration", "e2e"):
            log = self.run_dir() / "{0}.log".format(layer)
            with self.subTest(layer=layer):
                self.assertTrue(log.is_file(), "missing {0}".format(log))
                body = log.read_text(encoding="utf-8")
                self.assertIn("{0} runner output".format(layer), body)
                self.assertIn("{0} runner diagnostics".format(layer), body)

    def test_layer_entry_names_its_log_file(self):
        _, doc, _ = self.exec_cli(self.stack())
        self.assertEqual(self.layer(doc, "unit")["log"], "unit.log")


class ReproduceTest(ExecFixture):
    """Section 3.4.5: the recorded command must reproduce the run by hand."""

    def test_command_and_cwd_are_recorded(self):
        """The recorded argv is the argv that ran: the target's own command, then any
        reporter flags the runner injects."""
        stack = self.stack()
        expected = stack["layers"]["unit"]["targets"][0]["command"]
        _, doc, _ = self.exec_cli(stack)
        unit = self.layer(doc, "unit")
        self.assertEqual(unit["command"][: len(expected)], expected)
        self.assertEqual(unit["cwd"], "frontend")

    def test_reproduce_string_round_trips_the_argv(self):
        stack = self.stack()
        expected = stack["layers"]["unit"]["targets"][0]["command"]
        _, doc, _ = self.exec_cli(stack)
        reproduce = self.layer(doc, "unit")["reproduce"]
        prefix = "cd frontend && "
        self.assertTrue(
            reproduce.startswith(prefix),
            "expected {0!r} to start with {1!r}".format(reproduce, prefix),
        )
        # Parsing the reproduce line back must yield the real argv, quoting intact.
        self.assertEqual(shlex.split(reproduce[len(prefix):])[: len(expected)], expected)

    def test_recorded_command_actually_runs(self):
        import subprocess

        stack = self.stack()
        _, doc, _ = self.exec_cli(stack)
        unit = self.layer(doc, "unit")
        completed = subprocess.run(
            unit["command"],
            cwd=str(self.repo / unit["cwd"]),
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(completed.returncode, unit["exitCode"])


class SkippedLayerTest(ExecFixture):
    """Sections 3.4.7 and 4: an unavailable layer is skipped, never silently passed."""

    def test_unavailable_layer_is_reported_as_skipped_unavailable(self):
        _, doc, _ = self.exec_cli(self.stack())
        a11y = self.layer(doc, "a11y")
        self.assertIsNotNone(a11y, "the a11y layer must still be reported")
        self.assertEqual(a11y["status"], "skipped-unavailable")
        self.assertIsNone(a11y["exitCode"])
        self.assertEqual(a11y["reason"], A11Y_REASON)

    def test_skip_marks_the_run_incomplete_but_keeps_the_pass_verdict(self):
        code, doc, _ = self.exec_cli(self.stack())
        self.assertEqual(doc["verdict"], "pass")
        self.assertFalse(doc["complete"])
        self.assertEqual(code, common.OK)
        skipped = doc["skippedLayers"]
        self.assertTrue(skipped)
        self.assertEqual(skipped[0]["layer"], "a11y")
        self.assertIn("axe", skipped[0]["reason"].lower())

    def test_strict_gate_promotes_a_skip_to_a_failure(self):
        import copy

        config = copy.deepcopy(common.DEFAULT_CONFIG)
        config["gate"]["skippedLayers"] = "fail"
        code, doc, _ = self.exec_cli(self.stack(), config=config)
        self.assertEqual(doc["verdict"], "fail")
        self.assertFalse(doc["complete"])
        self.assertEqual(code, common.FAIL)


class FlakeTest(ExecFixture):
    """Section 3.4.6 and 4: a test that passes on retry is flaky, never passed."""

    def _flaky_stack(self):
        return self.stack(
            unit_command=[sys.executable, "-c", _flaky_script(self.counter, self.marker)]
        )

    def test_a_retry_that_passes_marks_the_layer_flaky(self):
        code, doc, _ = self.exec_cli(self._flaky_stack())
        unit = self.layer(doc, "unit")
        self.assertEqual(unit["status"], "flaky")
        self.assertNotEqual(unit["status"], "passed")
        self.assertTrue(unit["retried"])

    def test_a_flaky_layer_records_the_flake(self):
        _, doc, _ = self.exec_cli(self._flaky_stack())
        self.assertTrue(self.layer(doc, "unit")["flakes"], "flakes[] must record the flake")

    def test_a_flaky_layer_fails_the_run(self):
        code, doc, _ = self.exec_cli(self._flaky_stack())
        self.assertEqual(doc["verdict"], "fail")
        self.assertEqual(code, common.FAIL)

    def test_retry_disabled_reports_a_plain_failure(self):
        _, doc, _ = self.exec_cli(self._flaky_stack(), extra_argv=["--no-retry-failed"])
        unit = self.layer(doc, "unit")
        self.assertEqual(unit["status"], "failed")
        self.assertEqual(unit["exitCode"], 1)
        self.assertFalse(unit["retried"])

    def test_a_passing_layer_is_never_retried(self):
        _, doc, _ = self.exec_cli(self.stack())
        self.assertFalse(self.layer(doc, "unit")["retried"])


class TimeoutTest(ExecFixture):
    """Section 3.4.8: a per-layer timeout is exit 124 with timedOut true."""

    def test_timeout_produces_exit_124(self):
        stack = self.stack(unit_command=[sys.executable, "-c", _sleep_script()])
        code, doc, _ = self.exec_cli(
            stack, extra_argv=["--layer", "unit", "--timeout", "1", "--no-retry-failed"]
        )
        unit = self.layer(doc, "unit")
        self.assertEqual(unit["status"], "failed")
        self.assertTrue(unit["timedOut"])
        self.assertEqual(unit["exitCode"], 124)
        self.assertEqual(code, common.FAIL)


class RedactionTest(ExecFixture):
    """Section 3.4.4: secrets never reach the log or run.json."""

    def _secret_stack(self):
        return self.stack(unit_command=[sys.executable, "-c", _secret_script()])

    def test_secrets_are_scrubbed_from_the_layer_log(self):
        self.exec_cli(self._secret_stack(), extra_argv=["--layer", "unit", "--no-retry-failed"])
        body = (self.run_dir() / "unit.log").read_text(encoding="utf-8")
        self.assertNotIn("supersecretvalue123", body)
        self.assertNotIn("eyJab0123456789xyz", body)
        self.assertIn("***REDACTED***", body)

    def test_secrets_are_scrubbed_from_run_json(self):
        self.exec_cli(self._secret_stack(), extra_argv=["--layer", "unit", "--no-retry-failed"])
        raw = (self.run_dir() / "run.json").read_text(encoding="utf-8")
        self.assertNotIn("supersecretvalue123", raw)
        self.assertNotIn("eyJab0123456789xyz", raw)


class ProgressStreamTest(ExecFixture):
    """Section 3.4.3: progress streams to stderr, colour-free and one line per change."""

    def test_progress_lines_name_the_layer_and_its_status(self):
        _, _, stderr = self.exec_cli(self.stack(integration_exit=1))
        self.assertIn("layer=unit status=running", stderr)
        self.assertIn("layer=integration status=failed", stderr)
        self.assertNotIn("\x1b[", stderr, "progress output must not depend on colour")

    def test_progress_is_emitted_even_under_json_only(self):
        _, _, stderr = self.exec_cli(self.stack())
        self.assertIn("[qa]", stderr)
        self.assertIn("layer=e2e", stderr)


class LibraryApiTest(ExecFixture):
    """Section 9: execute_layers(ctx, stack, round_no, layers, **opts)."""

    def test_execute_layers_returns_the_run_document(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            ctx = common.Context(repo=self.repo, json_only=True)
            doc = qa_exec.execute_layers(ctx, self.stack(), 1, ["unit"])
        self.assertEqual(doc["schemaVersion"], 1)
        self.assertEqual(doc["round"], 1)
        self.assertEqual([entry["layer"] for entry in doc["layers"]], ["unit"])
        self.assertEqual(doc["layers"][0]["status"], "passed")
        self.assertEqual(self.order(), ["unit"])


class CoarseFingerprintTest(unittest.TestCase):
    """A coarse failure must identify itself, or baselining one masks the rest.

    Exercises `_coarse_finding` with REAL log tails -- including the `=== qa ...`
    banner lines qa writes itself -- because a signature taken from the banner is
    identical for every failure of a given layer+target.
    """

    TARGET = {"project": "app", "runner": "vitest", "testDirs": ["app/src/__tests__"]}

    def _coarse(self, runner_output):
        # The tail as _run_target really sees it: qa's own banner first, then the
        # runner's output.
        tail = [
            "=== qa layer=unit target=app runner=vitest attempt=1 ===",
            "=== command: npm run test -- --run",
            "=== cwd: app",
        ] + list(runner_output)
        return qa_exec._coarse_finding(
            "unit", self.TARGET, "app", 1, tail, False, 1800, "cd app && npm run test"
        )

    def test_two_unrelated_crashes_get_different_fingerprints(self):
        a = self._coarse(["TypeError: cannot read property foo of undefined in module alpha"])
        b = self._coarse(["ReferenceError: beta is not defined in module beta"])
        self.assertNotEqual(a["target"], b["target"])
        self.assertNotEqual(qa_baseline.fingerprint(a), qa_baseline.fingerprint(b))

    def test_volatile_tokens_inside_the_line_do_not_change_the_fingerprint(self):
        """Timings, temp paths, hashes and line:col markers differ run to run."""
        first = self._coarse(
            ["FAIL app/src/foo.test.ts:12:4 duration 12.4ms cache /tmp/vitest-a1b2c3d4"]
        )
        second = self._coarse(
            ["FAIL app/src/foo.test.ts:19:7 duration 87.1ms cache /tmp/vitest-9f8e7d6c"]
        )
        self.assertEqual(
            qa_baseline.fingerprint(first),
            qa_baseline.fingerprint(second),
            "volatile run detail must not change a coarse fingerprint",
        )

    def test_a_banner_only_tail_is_not_baselineable(self):
        """No runner output at all -> nothing identifying -> refuse to baseline."""
        finding = self._coarse([])
        self.assertFalse(qa_baseline.identifiable(finding) and "#unclassified" not in finding["target"])

    def test_a_timeout_is_signed_as_a_timeout(self):
        finding = qa_exec._coarse_finding(
            "e2e", self.TARGET, "app", 124, ["=== qa layer=e2e ==="], True, 30, None
        )
        self.assertIn("#timeout", finding["target"])


class ModuleSurfaceTest(unittest.TestCase):
    """Section 9: qa_exec owns `exec` and exposes execute_layers."""

    def test_owns_the_exec_subcommand(self):
        add_arguments, runner = _entry(qa_exec, "exec")
        self.assertTrue(callable(add_arguments))
        self.assertTrue(callable(runner))

    def test_exposes_execute_layers(self):
        self.assertTrue(callable(getattr(qa_exec, "execute_layers", None)))


if __name__ == "__main__":  # pragma: no cover - manual execution
    unittest.main()
