"""Contract tests for ``qa_baseline`` (QA Agent contract section 3.6).

Fingerprints are deliberately line-number-free so they survive a line move, and
change when the rule, file, target or source changes. The baseline is only ever
regenerated on an explicit, recorded request.
"""

import argparse
import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

try:  # pragma: no cover - package import
    from .. import qa_common as common
    from .. import qa_baseline
except ImportError:  # pragma: no cover - direct script execution
    import qa_common as common
    import qa_baseline


RUN_A = "20260725-140233"
RUN_B = "20260725-150000"


def _entry(module, name):
    commands = getattr(module, "COMMANDS", None)
    if commands:
        for entry in commands:
            if entry[0] == name:
                return entry[2], entry[3]
        raise AssertionError("{0} does not own the {1!r} subcommand".format(module, name))
    assert getattr(module, "COMMAND", None) == name, "COMMAND must be {0!r}".format(name)
    return module.add_arguments, module.run


def _a11y_finding(rule, file, target, line=0, impact="serious", name=None):
    return {
        "source": "a11y",
        "rule": rule,
        "testId": None,
        "name": name or "{0} on {1}".format(rule, target),
        "file": file,
        "line": line,
        "target": target,
        "impact": impact,
        "message": "axe reported {0}".format(rule),
        "expected": None,
        "actual": None,
        "requirementRef": None,
        "statedCriterion": False,
        "flaky": False,
        "helpUrl": "https://dequeuniversity.com/rules/axe/4.10/" + rule,
        "reproduce": "cd frontend && npx playwright test e2e/a11y.spec.ts",
        "suggestedFix": None,
    }


def _unit_finding(test_id, file, line=10):
    return {
        "source": "unit",
        "rule": None,
        "testId": test_id,
        "name": test_id.split("::")[-1],
        "file": file,
        "line": line,
        "target": test_id,
        "impact": None,
        "message": "expected 'A' to equal 'B'",
        "expected": "B",
        "actual": "A",
        "requirementRef": "FR-3",
        "statedCriterion": True,
        "flaky": False,
        "helpUrl": None,
        "reproduce": "cd frontend && npm run test -- --run",
        "suggestedFix": None,
    }


def _identity(item):
    """partition()/compare may yield findings or bare fingerprints; compare by fingerprint."""
    if isinstance(item, dict):
        return item.get("fp") or qa_baseline.fingerprint(item)
    return str(item)


FINDING_A = _a11y_finding("color-contrast", "frontend/src/legacy/widget.tsx", ".legacy .btn")
FINDING_B = _a11y_finding("image-alt", "frontend/src/legacy/hero.tsx", ".hero img", impact="critical")
FINDING_C = _a11y_finding("label", "frontend/src/components/form.tsx", "#email", impact="serious")


class FingerprintTest(unittest.TestCase):
    """Section 3.6: sha256(source|rule|normFile|normTarget), line-number-free."""

    def test_matches_the_documented_formula(self):
        self.assertEqual(
            qa_baseline.fingerprint(FINDING_A),
            common.sha256_fp(
                "a11y", "color-contrast", "frontend/src/legacy/widget.tsx", ".legacy .btn"
            ),
        )

    def test_shape_is_sha256_prefixed_hex(self):
        self.assertRegex(qa_baseline.fingerprint(FINDING_A), r"^sha256:[0-9a-f]{64}$")

    def test_survives_a_line_number_change(self):
        moved = dict(FINDING_A)
        moved["line"] = 412
        self.assertEqual(qa_baseline.fingerprint(FINDING_A), qa_baseline.fingerprint(moved))

    def test_survives_a_message_change(self):
        reworded = dict(FINDING_A)
        reworded["message"] = "axe 4.11 reworded this message entirely"
        reworded["name"] = "a different human title"
        self.assertEqual(qa_baseline.fingerprint(FINDING_A), qa_baseline.fingerprint(reworded))

    def test_changes_when_the_rule_changes(self):
        other = dict(FINDING_A)
        other["rule"] = "link-name"
        self.assertNotEqual(qa_baseline.fingerprint(FINDING_A), qa_baseline.fingerprint(other))


class NonIdentifyingFingerprintTest(unittest.TestCase):
    """A fingerprint with no rule AND no target names nothing, so it cannot baseline.

    Baselining one such finding would otherwise force every future, unrelated
    failure in that layer to `low` + `informational` and stop it gating.
    """

    @staticmethod
    def _coarse(file="frontend", target=None):
        return {
            "source": "unit",
            "rule": None,
            "testId": None,
            "name": "unit layer failed with exit code 1",
            "file": file,
            "line": 0,
            "target": target,
            "impact": None,
            "message": "no machine-readable report",
        }

    def test_identifiable_requires_a_rule_or_a_target(self):
        self.assertFalse(qa_baseline.identifiable(self._coarse()))
        self.assertTrue(qa_baseline.identifiable(self._coarse(target="frontend:vitest#a1b2")))

    def test_build_document_refuses_a_non_identifying_finding(self):
        document = qa_baseline.build_document(
            [self._coarse()], reason="initial adoption", by="qa-agent"
        )
        self.assertEqual(document["fingerprints"], [])
        self.assertEqual(len(document["skipped"]), 1)
        self.assertIn("cannot identify", document["skipped"][0]["reason"])

    def test_two_distinct_coarse_failures_do_not_collide(self):
        a = self._coarse(target="frontend:vitest#aaaaaaaaaaaa")
        b = self._coarse(target="frontend:vitest#bbbbbbbbbbbb")
        self.assertNotEqual(qa_baseline.fingerprint(a), qa_baseline.fingerprint(b))
        document = qa_baseline.build_document([a, b], reason="adopt", by="qa-agent")
        self.assertEqual(len(document["fingerprints"]), 2)

    def test_changes_when_the_file_changes(self):
        other = dict(FINDING_A)
        other["file"] = "frontend/src/legacy/other.tsx"
        self.assertNotEqual(qa_baseline.fingerprint(FINDING_A), qa_baseline.fingerprint(other))

    def test_changes_when_the_target_changes(self):
        other = dict(FINDING_A)
        other["target"] = ".legacy .link"
        self.assertNotEqual(qa_baseline.fingerprint(FINDING_A), qa_baseline.fingerprint(other))

    def test_changes_when_the_source_changes(self):
        other = dict(FINDING_A)
        other["source"] = "e2e"
        self.assertNotEqual(qa_baseline.fingerprint(FINDING_A), qa_baseline.fingerprint(other))

    def test_test_failures_fingerprint_on_their_test_id(self):
        first = _unit_finding("src/foo.test.tsx::renders empty state", "frontend/src/foo.tsx", 10)
        moved = _unit_finding("src/foo.test.tsx::renders empty state", "frontend/src/foo.tsx", 99)
        renamed = _unit_finding("src/foo.test.tsx::renders the error", "frontend/src/foo.tsx", 10)
        self.assertEqual(qa_baseline.fingerprint(first), qa_baseline.fingerprint(moved))
        self.assertNotEqual(qa_baseline.fingerprint(first), qa_baseline.fingerprint(renamed))

    def test_is_stable_across_calls(self):
        self.assertEqual(qa_baseline.fingerprint(FINDING_A), qa_baseline.fingerprint(FINDING_A))


class BaselineFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)
        self.qa_dir = self.repo / "qa"
        self.round_dir = self.qa_dir / "rounds" / "001"
        self.round_dir.mkdir(parents=True, exist_ok=True)

    def ctx(self, config=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            return common.Context(repo=self.repo, config=config, json_only=True)

    def write_run(self, run_id, findings):
        run_dir = self.round_dir / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        doc = {
            "schemaVersion": 1,
            "round": 1,
            "runId": run_id,
            "startedAt": "2026-07-25T14:02:33Z",
            "finishedAt": "2026-07-25T14:06:01Z",
            "repo": str(self.repo),
            "layers": [
                {
                    "layer": "a11y",
                    "status": "failed",
                    "exitCode": 1,
                    "timedOut": False,
                    "retried": False,
                    "durationMs": 4200,
                    "command": ["npx", "playwright", "test", "e2e/a11y.spec.ts"],
                    "cwd": ".",
                    "reproduce": "npx playwright test e2e/a11y.spec.ts",
                    "log": "a11y.log",
                    "reason": None,
                    "failures": list(findings),
                    "flakes": [],
                }
            ],
            "verdict": "fail",
            "complete": True,
            "skippedLayers": [],
        }
        (run_dir / "run.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
        return run_dir

    def baseline_doc(self):
        return json.loads((self.qa_dir / "baseline.json").read_text(encoding="utf-8"))

    def write_baseline(self, findings, history=()):
        self.qa_dir.mkdir(parents=True, exist_ok=True)
        doc = {
            "schemaVersion": 1,
            "generatedAt": "2026-07-01T00:00:00Z",
            "generatedBy": "qa-agent",
            "reason": "initial adoption",
            "history": list(history),
            "fingerprints": [
                {
                    "fp": qa_baseline.fingerprint(finding),
                    "source": finding["source"],
                    "rule": finding["rule"],
                    "file": finding["file"],
                    "target": finding["target"],
                    "severity": "medium",
                }
                for finding in findings
            ],
        }
        (self.qa_dir / "baseline.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
        return doc

    def cli(self, argv, config=None):
        add_arguments, runner = _entry(qa_baseline, "baseline")
        parser = argparse.ArgumentParser(prog="qa.py baseline")
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
        return code, (json.loads(stdout) if stdout.strip() else {})


class LoadBaselineTest(BaselineFixture):
    """Section 3.6: a missing baseline is an empty baseline, not an error."""

    def test_missing_file_yields_no_fingerprints(self):
        doc = qa_baseline.load_baseline(self.ctx())
        self.assertEqual(doc.get("fingerprints"), [])

    def test_existing_file_is_loaded(self):
        self.write_baseline([FINDING_A])
        doc = qa_baseline.load_baseline(self.ctx())
        self.assertEqual(len(doc["fingerprints"]), 1)
        self.assertEqual(doc["fingerprints"][0]["fp"], qa_baseline.fingerprint(FINDING_A))


class PartitionTest(BaselineFixture):
    """Section 3.6: findings split into pre-existing and introduced."""

    def test_known_fingerprints_are_preexisting_and_the_rest_introduced(self):
        baseline = self.write_baseline([FINDING_A])
        preexisting, introduced = qa_baseline.partition([FINDING_A, FINDING_C], baseline)
        self.assertEqual(
            [_identity(item) for item in preexisting],
            [qa_baseline.fingerprint(FINDING_A)],
        )
        self.assertEqual(
            [_identity(item) for item in introduced],
            [qa_baseline.fingerprint(FINDING_C)],
        )

    def test_empty_baseline_makes_everything_introduced(self):
        baseline = self.write_baseline([])
        preexisting, introduced = qa_baseline.partition([FINDING_A, FINDING_C], baseline)
        self.assertEqual(preexisting, [])
        self.assertEqual(len(introduced), 2)

    def test_partition_is_total(self):
        baseline = self.write_baseline([FINDING_A, FINDING_B])
        findings = [FINDING_A, FINDING_B, FINDING_C]
        preexisting, introduced = qa_baseline.partition(findings, baseline)
        self.assertEqual(len(preexisting) + len(introduced), len(findings))

    def test_a_moved_line_stays_preexisting(self):
        baseline = self.write_baseline([FINDING_A])
        moved = dict(FINDING_A)
        moved["line"] = 999
        preexisting, introduced = qa_baseline.partition([moved], baseline)
        self.assertEqual(len(preexisting), 1)
        self.assertEqual(introduced, [])


class CreateTest(BaselineFixture):
    """Section 3.6: `baseline create --from-run` records the current violation set."""

    def test_create_writes_a_fingerprint_per_finding(self):
        self.write_run(RUN_A, [FINDING_A, FINDING_B])
        code, doc = self.cli(
            ["create", "--from-run", "1/" + RUN_A, "--reason", "initial adoption"]
        )
        self.assertEqual(code, common.OK)
        self.assertEqual(doc["schemaVersion"], 1)
        baseline = self.baseline_doc()
        self.assertEqual(baseline["schemaVersion"], 1)
        self.assertEqual(
            sorted(item["fp"] for item in baseline["fingerprints"]),
            sorted(
                [qa_baseline.fingerprint(FINDING_A), qa_baseline.fingerprint(FINDING_B)]
            ),
        )

    def test_create_records_provenance(self):
        self.write_run(RUN_A, [FINDING_A])
        self.cli(["create", "--from-run", "1/" + RUN_A, "--reason", "initial adoption"])
        baseline = self.baseline_doc()
        self.assertEqual(baseline["reason"], "initial adoption")
        self.assertTrue(baseline["generatedBy"])
        self.assertRegex(baseline["generatedAt"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertIn("history", baseline)

    def test_fingerprint_entries_carry_their_context(self):
        self.write_run(RUN_A, [FINDING_A])
        self.cli(["create", "--from-run", "1/" + RUN_A, "--reason", "initial adoption"])
        entry = self.baseline_doc()["fingerprints"][0]
        for key in ("fp", "source", "rule", "file", "target", "severity"):
            self.assertIn(key, entry)
        self.assertEqual(entry["source"], "a11y")
        self.assertEqual(entry["rule"], "color-contrast")


class CompareTest(BaselineFixture):
    """Section 3.6: `baseline compare` reports pre-existing versus introduced."""

    def test_compare_splits_the_run_against_the_baseline(self):
        self.write_baseline([FINDING_A, FINDING_B])
        self.write_run(RUN_B, [FINDING_A, FINDING_C])
        code, doc = self.cli(["compare", "--run", "1/" + RUN_B])
        self.assertEqual(doc["schemaVersion"], 1)
        self.assertIn("preexisting", doc)
        self.assertIn("introduced", doc)
        preexisting = [_identity(item) for item in doc["preexisting"]]
        introduced = [_identity(item) for item in doc["introduced"]]
        self.assertIn(qa_baseline.fingerprint(FINDING_A), preexisting)
        self.assertIn(qa_baseline.fingerprint(FINDING_C), introduced)
        self.assertNotIn(qa_baseline.fingerprint(FINDING_C), preexisting)
        self.assertEqual(code, common.OK)

    def test_compare_without_a_baseline_reports_everything_as_introduced(self):
        self.write_run(RUN_B, [FINDING_A, FINDING_C])
        _, doc = self.cli(["compare", "--run", "1/" + RUN_B])
        self.assertEqual(doc["preexisting"], [])
        self.assertEqual(len(doc["introduced"]), 2)


class RegenerateTest(BaselineFixture):
    """Section 3.6 / 6: regeneration is explicit, justified and appended to history."""

    def test_regenerate_without_a_reason_is_a_usage_error(self):
        self.write_baseline([FINDING_A])
        self.write_run(RUN_A, [FINDING_A])
        code, _ = self.cli(["regenerate"])
        self.assertEqual(code, common.USAGE)

    def test_regenerate_without_a_reason_changes_nothing(self):
        self.write_baseline([FINDING_A])
        self.write_run(RUN_A, [FINDING_A])
        before = self.baseline_doc()
        self.cli(["regenerate"])
        self.assertEqual(self.baseline_doc(), before)

    def test_regenerate_appends_a_history_entry(self):
        self.write_baseline([FINDING_A])
        self.write_run(RUN_A, [FINDING_A, FINDING_C])
        before = len(self.baseline_doc()["history"])
        code, _ = self.cli(
            ["regenerate", "--reason", "playwright 2.0 upgrade changed the rule set"]
        )
        self.assertEqual(code, common.OK)
        history = self.baseline_doc()["history"]
        self.assertEqual(len(history), before + 1)
        latest = history[-1]
        self.assertEqual(latest["reason"], "playwright 2.0 upgrade changed the rule set")
        self.assertIn("at", latest)
        self.assertIn("by", latest)

    def test_history_accumulates_in_order(self):
        self.write_baseline([FINDING_A])
        self.write_run(RUN_A, [FINDING_A])
        self.cli(["regenerate", "--reason", "first regeneration"])
        self.cli(["regenerate", "--reason", "second regeneration"])
        history = self.baseline_doc()["history"]
        self.assertGreaterEqual(len(history), 2)
        self.assertEqual(history[-2]["reason"], "first regeneration")
        self.assertEqual(history[-1]["reason"], "second regeneration")


class ShowTest(BaselineFixture):
    """Section 3.6: `baseline show` prints the committed baseline."""

    def test_show_reports_the_current_baseline(self):
        self.write_baseline([FINDING_A, FINDING_B])
        code, doc = self.cli(["show"])
        self.assertEqual(code, common.OK)
        self.assertEqual(doc["schemaVersion"], 1)
        self.assertEqual(len(doc["fingerprints"]), 2)

    def test_show_without_a_baseline_is_not_an_error(self):
        code, doc = self.cli(["show"])
        self.assertEqual(code, common.OK)
        self.assertEqual(doc.get("fingerprints"), [])


class ModuleSurfaceTest(unittest.TestCase):
    """Section 9: qa_baseline owns `baseline` and exposes its library helpers."""

    def test_owns_the_baseline_subcommand(self):
        add_arguments, runner = _entry(qa_baseline, "baseline")
        self.assertTrue(callable(add_arguments))
        self.assertTrue(callable(runner))

    def test_exposes_library_functions(self):
        for name in ("fingerprint", "load_baseline", "partition"):
            with self.subTest(function=name):
                self.assertTrue(callable(getattr(qa_baseline, name, None)))


if __name__ == "__main__":  # pragma: no cover - manual execution
    unittest.main()
