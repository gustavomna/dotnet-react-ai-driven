"""Contract tests for ``qa_findings`` (QA Agent contract sections 3.5, 3.8, 4 and 5).

The issue file is the agent's only output contract, so its frontmatter key set and
order are asserted exactly. Severity follows the section 4 table including its
"at minimum" rules, and the verdict follows the section 4 reconciliation of
skipped layers.
"""

import argparse
import contextlib
import copy
import io
import json
import os
import pathlib
import re
import sys
import tempfile
import unittest

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

try:  # pragma: no cover - package import
    from .. import qa_common as common
    from .. import qa_findings
except ImportError:  # pragma: no cover - direct script execution
    import qa_common as common
    import qa_findings


RUN_ID = "20260725-140233"

#: Section 5: exactly these keys, in exactly this order.
FRONTMATTER_KEYS = ["status", "file", "line", "severity", "author", "source"]


def _rank(severity):
    """Lower is worse; `SEVERITIES` is ordered most severe first."""
    return common.SEVERITIES.index(severity)


def _entry(module, name):
    commands = getattr(module, "COMMANDS", None)
    if commands:
        for entry in commands:
            if entry[0] == name:
                return entry[2], entry[3]
        raise AssertionError("{0} does not own the {1!r} subcommand".format(module, name))
    assert getattr(module, "COMMAND", None) == name, "COMMAND must be {0!r}".format(name)
    return module.add_arguments, module.run


def _finding(**overrides):
    finding = {
        "source": "a11y",
        "rule": "color-contrast",
        "testId": None,
        "name": "Insufficient contrast on the primary button",
        "file": "frontend/src/components/foo.tsx",
        "line": 0,
        "target": ".hero .btn",
        "impact": "serious",
        "message": "Element has insufficient colour contrast of 2.9:1",
        "expected": "contrast ratio of at least 4.5:1",
        "actual": "2.9:1",
        "requirementRef": "FR-3",
        "statedCriterion": True,
        "flaky": False,
        "helpUrl": "https://dequeuniversity.com/rules/axe/4.10/color-contrast",
        "reproduce": "cd frontend && npx playwright test e2e/a11y.spec.ts",
        "suggestedFix": "Darken --color-primary to meet 4.5:1 against the button background.",
        "severity": "high",
        "status": "open",
    }
    finding.update(overrides)
    return finding


def _failure(**overrides):
    failure = {
        "testId": "src/foo.test.tsx::renders empty state",
        "name": "renders empty state",
        "file": "frontend/src/__tests__/foo.test.tsx",
        "line": 24,
        "message": "expected 'A' to equal 'B'",
        "expected": "B",
        "actual": "A",
        "requirementRef": "FR-3",
        "impact": None,
        "rule": None,
        "source": "unit",
        "target": "src/foo.test.tsx::renders empty state",
        "statedCriterion": True,
        "flaky": False,
        "helpUrl": None,
        "reproduce": "cd frontend && npm run test -- --run src/__tests__/foo.test.tsx",
        "suggestedFix": "Reset isLoading in the settled branch of the effect.",
    }
    failure.update(overrides)
    return failure


def _layer(name, status="passed", exit_code=0, failures=(), flakes=(), reason=None):
    return {
        "layer": name,
        "status": status,
        "exitCode": exit_code,
        "timedOut": False,
        "retried": False,
        "durationMs": 1200,
        "command": ["npm", "run", "test", "--", "--run"],
        "cwd": "frontend",
        "reproduce": "cd frontend && npm run test -- --run",
        "log": "{0}.log".format(name),
        "reason": reason,
        "failures": list(failures),
        "flakes": list(flakes),
    }


class FindingsFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)
        self.round_dir = self.repo / "qa" / "rounds" / "001"
        self.round_dir.mkdir(parents=True, exist_ok=True)

    def ctx(self, config=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            return common.Context(repo=self.repo, config=config, json_only=True)

    def write_run(self, layers, verdict="fail", complete=True, skipped=(), run_id=RUN_ID):
        run_dir = self.round_dir / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        doc = {
            "schemaVersion": 1,
            "round": 1,
            "runId": run_id,
            "startedAt": "2026-07-25T14:02:33Z",
            "finishedAt": "2026-07-25T14:06:01Z",
            "repo": str(self.repo),
            "layers": layers,
            "verdict": verdict,
            "complete": complete,
            "skippedLayers": list(skipped),
        }
        (run_dir / "run.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
        for layer in layers:
            (run_dir / "{0}.log".format(layer["layer"])).write_text("log\n", encoding="utf-8")
        return run_dir

    def cli(self, name, argv, config=None):
        add_arguments, runner = _entry(qa_findings, name)
        parser = argparse.ArgumentParser(prog="qa.py " + name)
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

    def issue_files(self):
        return sorted(p.name for p in self.round_dir.glob("issue_*.md"))

    def summary(self):
        return json.loads((self.round_dir / "summary.json").read_text(encoding="utf-8"))

    @staticmethod
    def frontmatter(text):
        assert text.startswith("---\n"), "issue files start with a YAML frontmatter fence"
        end = text.index("\n---", 4)
        pairs = []
        for line in text[4:end].split("\n"):
            if not line.strip():
                continue
            key, _, value = line.partition(":")
            pairs.append((key.strip(), value.strip()))
        return pairs


class RenderIssueTest(FindingsFixture):
    """Section 5: the issue file format is exact."""

    def test_frontmatter_key_set_and_order(self):
        text = qa_findings.render_issue(3, _finding())
        keys = [key for key, _ in self.frontmatter(text)]
        self.assertEqual(keys, FRONTMATTER_KEYS)

    def test_frontmatter_values(self):
        text = qa_findings.render_issue(3, _finding())
        values = dict(self.frontmatter(text))
        self.assertEqual(values["status"], "open")
        self.assertEqual(values["file"], "frontend/src/components/foo.tsx")
        self.assertEqual(values["line"], "0")
        self.assertEqual(values["severity"], "high")
        self.assertEqual(values["source"], "a11y")
        self.assertTrue(values["author"])

    def test_line_is_rendered_as_a_bare_integer(self):
        text = qa_findings.render_issue(7, _finding(line=42))
        self.assertIn("\nline: 42\n", text)

    def test_title_uses_the_zero_padded_issue_number(self):
        text = qa_findings.render_issue(3, _finding())
        self.assertIn("# issue_003", text)
        self.assertIn("Insufficient contrast on the primary button", text)

    def test_body_carries_the_mandatory_sections(self):
        text = qa_findings.render_issue(1, _finding())
        for heading in ("## Failing assertion", "## Reproduce"):
            self.assertIn(heading, text)
        self.assertIn("cd frontend && npx playwright test", text)
        self.assertIn("FR-3", text)
        self.assertIn("Darken --color-primary", text)

    def test_values_needing_yaml_quoting_are_quoted(self):
        text = qa_findings.render_issue(1, _finding(file="frontend/src/a:b#c.tsx"))
        values = dict(self.frontmatter(text))
        self.assertTrue(
            values["file"].startswith('"') and values["file"].endswith('"'),
            "a file containing ':' must be quoted: {0}".format(values["file"]),
        )

    def test_empty_file_value_is_quoted(self):
        text = qa_findings.render_issue(1, _finding(file=""))
        values = dict(self.frontmatter(text))
        self.assertEqual(values["file"], '""')

    def test_source_is_one_of_the_contract_values(self):
        for source in ("unit", "integration", "e2e", "a11y", "flake", "plan"):
            with self.subTest(source=source):
                text = qa_findings.render_issue(1, _finding(source=source, severity="medium"))
                self.assertEqual(dict(self.frontmatter(text))["source"], source)

    def test_secrets_in_a_finding_never_reach_the_issue_body(self):
        text = qa_findings.render_issue(
            1, _finding(message="failed with API_TOKEN=supersecretvalue123")
        )
        self.assertNotIn("supersecretvalue123", text)


class WriteIssueTest(FindingsFixture):
    """Section 3.5: one file per failure, zero-padded, never merged."""

    def test_writes_one_zero_padded_file_per_finding(self):
        ctx = self.ctx()
        first = pathlib.Path(qa_findings.write_issue(ctx, 1, 1, _finding()))
        second = pathlib.Path(
            qa_findings.write_issue(ctx, 1, 2, _finding(name="Missing form label"))
        )
        self.assertEqual(first.name, "issue_001.md")
        self.assertEqual(second.name, "issue_002.md")
        self.assertNotEqual(first, second)
        self.assertEqual(self.issue_files(), ["issue_001.md", "issue_002.md"])
        self.assertIn("Missing form label", second.read_text(encoding="utf-8"))
        self.assertNotIn("Missing form label", first.read_text(encoding="utf-8"))

    def test_written_file_lands_in_the_round_directory(self):
        path = pathlib.Path(qa_findings.write_issue(self.ctx(), 1, 5, _finding()))
        self.assertEqual(path.parent, self.round_dir)
        self.assertEqual(path.name, "issue_005.md")


class SeverityTableTest(unittest.TestCase):
    """Section 4: the severity table, including its 'at minimum' rules."""

    def test_axe_impact_mapping(self):
        self.assertEqual(qa_findings.severity_for("a11y", impact="critical"), "critical")
        self.assertEqual(qa_findings.severity_for("a11y", impact="serious"), "high")
        self.assertEqual(qa_findings.severity_for("a11y", impact="moderate"), "medium")
        self.assertEqual(qa_findings.severity_for("a11y", impact="minor"), "low")

    def test_stated_criterion_failure_is_at_minimum_high(self):
        for source in ("unit", "integration", "e2e"):
            with self.subTest(source=source):
                severity = qa_findings.severity_for(source, stated_criterion=True)
                self.assertLessEqual(_rank(severity), _rank("high"), severity)

    def test_flaky_is_at_minimum_medium(self):
        severity = qa_findings.severity_for("unit", flaky=True)
        self.assertLessEqual(_rank(severity), _rank("medium"), severity)

    def test_flaky_stated_criterion_keeps_the_stronger_rule(self):
        severity = qa_findings.severity_for("unit", flaky=True, stated_criterion=True)
        self.assertLessEqual(_rank(severity), _rank("high"), severity)

    def test_inferred_functional_failure_defaults_to_medium(self):
        self.assertEqual(qa_findings.severity_for("unit", stated_criterion=False), "medium")

    def test_preexisting_findings_are_forced_to_low(self):
        self.assertEqual(
            qa_findings.severity_for("a11y", impact="critical", preexisting=True), "low"
        )
        self.assertEqual(
            qa_findings.severity_for("unit", stated_criterion=True, preexisting=True), "low"
        )
        self.assertEqual(qa_findings.severity_for("unit", flaky=True, preexisting=True), "low")

    def test_every_result_is_a_contract_severity(self):
        for source in ("unit", "integration", "e2e", "a11y", "flake", "plan"):
            for impact in (None, "critical", "serious", "moderate", "minor"):
                severity = qa_findings.severity_for(source, impact=impact)
                self.assertIn(severity, common.SEVERITIES)


class ComputeVerdictTest(unittest.TestCase):
    """Section 4: verdict, complete, and the skipped-layer reconciliation."""

    def config(self, skipped_gate="warn"):
        config = copy.deepcopy(common.DEFAULT_CONFIG)
        config["gate"]["skippedLayers"] = skipped_gate
        return config

    def test_all_layers_passing_is_a_complete_pass(self):
        layers = [_layer("unit"), _layer("integration"), _layer("e2e"), _layer("a11y")]
        result = qa_findings.compute_verdict(layers, self.config())
        self.assertEqual(result["verdict"], "pass")
        self.assertTrue(result["complete"])
        self.assertIn("reasons", result)

    def test_any_failing_layer_fails_the_round(self):
        layers = [_layer("unit"), _layer("e2e", status="failed", exit_code=1)]
        result = qa_findings.compute_verdict(layers, self.config())
        self.assertEqual(result["verdict"], "fail")
        self.assertTrue(result["reasons"])

    def test_a_flaky_layer_fails_the_round(self):
        layers = [
            _layer("unit", status="flaky", exit_code=0, flakes=[{"testId": "a::b"}]),
            _layer("e2e"),
        ]
        result = qa_findings.compute_verdict(layers, self.config())
        self.assertEqual(result["verdict"], "fail")

    def test_skipped_layer_keeps_the_pass_but_marks_it_incomplete(self):
        layers = [
            _layer("unit"),
            _layer("a11y", status="skipped-unavailable", exit_code=None, reason="no axe"),
        ]
        result = qa_findings.compute_verdict(layers, self.config("warn"))
        self.assertEqual(result["verdict"], "pass")
        self.assertFalse(result["complete"])
        self.assertTrue(result["reasons"], "an incomplete pass must say why")

    def test_strict_gate_turns_a_skipped_layer_into_a_failure(self):
        layers = [
            _layer("unit"),
            _layer("a11y", status="skipped-unavailable", exit_code=None, reason="no axe"),
        ]
        result = qa_findings.compute_verdict(layers, self.config("fail"))
        self.assertEqual(result["verdict"], "fail")
        self.assertFalse(result["complete"])


class ReportTest(FindingsFixture):
    """Section 3.5: one issue per failure, continued numbering, machine summary."""

    def _failing_run(self):
        return self.write_run(
            [
                _layer(
                    "unit",
                    status="failed",
                    exit_code=1,
                    failures=[
                        _failure(),
                        _failure(
                            testId="src/foo.test.tsx::shows the error banner",
                            name="shows the error banner",
                            line=51,
                            requirementRef="FR-4",
                        ),
                    ],
                ),
                _layer("integration"),
                _layer("e2e"),
                _layer(
                    "a11y",
                    status="failed",
                    exit_code=1,
                    failures=[
                        _failure(
                            source="a11y",
                            rule="color-contrast",
                            impact="serious",
                            testId=None,
                            target=".hero .btn",
                            name="Insufficient contrast on the primary button",
                            file="frontend/src/components/foo.tsx",
                            line=0,
                            statedCriterion=False,
                        )
                    ],
                ),
            ]
        )

    def test_one_issue_file_per_failure(self):
        self._failing_run()
        code, doc = self.cli("report", ["--round", "1", "--run", RUN_ID])
        self.assertEqual(self.issue_files(), ["issue_001.md", "issue_002.md", "issue_003.md"])
        self.assertEqual(doc["schemaVersion"], 1)
        self.assertEqual(code, common.FAIL)

    def test_numbering_continues_from_the_highest_existing_issue(self):
        (self.round_dir / "issue_001.md").write_text("---\nstatus: open\n---\n", encoding="utf-8")
        (self.round_dir / "issue_002.md").write_text("---\nstatus: open\n---\n", encoding="utf-8")
        before = (self.round_dir / "issue_001.md").read_text(encoding="utf-8")
        self._failing_run()
        self.cli("report", ["--round", "1", "--run", RUN_ID])
        self.assertEqual(
            self.issue_files(),
            ["issue_001.md", "issue_002.md", "issue_003.md", "issue_004.md", "issue_005.md"],
        )
        self.assertEqual((self.round_dir / "issue_001.md").read_text(encoding="utf-8"), before)

    def test_stated_criterion_failure_is_at_minimum_high(self):
        self._failing_run()
        self.cli("report", ["--round", "1", "--run", RUN_ID])
        text = (self.round_dir / "issue_001.md").read_text(encoding="utf-8")
        severity = dict(self.frontmatter(text))["severity"]
        self.assertLessEqual(_rank(severity), _rank("high"), severity)

    def test_axe_serious_violation_becomes_high(self):
        self._failing_run()
        self.cli("report", ["--round", "1", "--run", RUN_ID])
        a11y_issues = [
            path
            for path in self.round_dir.glob("issue_*.md")
            if "source: a11y" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(len(a11y_issues), 1)
        severity = dict(self.frontmatter(a11y_issues[0].read_text(encoding="utf-8")))["severity"]
        self.assertEqual(severity, "high")

    def test_summary_json_shape(self):
        self._failing_run()
        self.cli("report", ["--round", "1", "--run", RUN_ID])
        summary = self.summary()
        for key in (
            "schemaVersion",
            "round",
            "runId",
            "verdict",
            "complete",
            "generatedAt",
            "layers",
            "counts",
            "issues",
            "manualItems",
            "suppressions",
            "baseline",
            "skippedLayers",
            "coverage",
        ):
            self.assertIn(key, summary)
        self.assertEqual(summary["schemaVersion"], 1)
        self.assertEqual(summary["round"], 1)
        self.assertEqual(summary["runId"], RUN_ID)
        self.assertRegex(summary["generatedAt"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_summary_counts_add_up(self):
        self._failing_run()
        self.cli("report", ["--round", "1", "--run", RUN_ID])
        counts = self.summary()["counts"]
        for severity in common.SEVERITIES:
            self.assertIn(severity, counts)
        self.assertEqual(counts["total"], sum(counts[s] for s in common.SEVERITIES))
        self.assertEqual(counts["total"], len(self.issue_files()))

    def test_summary_issue_entries_reference_their_files(self):
        self._failing_run()
        self.cli("report", ["--round", "1", "--run", RUN_ID])
        issues = self.summary()["issues"]
        self.assertEqual(len(issues), 3)
        for issue in issues:
            with self.subTest(issue=issue.get("id")):
                self.assertRegex(issue["id"], r"^issue_\d{3}$")
                self.assertIn(issue["severity"], common.SEVERITIES)
                self.assertIn(issue["source"], ("unit", "integration", "e2e", "a11y", "flake", "plan"))
                self.assertIn(issue["status"], ("open", "informational"))
                self.assertTrue(issue["title"])
                self.assertIn("line", issue)

    def test_summary_markdown_is_written_alongside_the_json(self):
        self._failing_run()
        self.cli("report", ["--round", "1", "--run", RUN_ID])
        self.assertTrue((self.round_dir / "summary.md").is_file())
        body = (self.round_dir / "summary.md").read_text(encoding="utf-8")
        self.assertIn("FAIL", body)

    def test_dry_run_writes_nothing(self):
        self._failing_run()
        self.cli("report", ["--round", "1", "--run", RUN_ID, "--dry-run"])
        self.assertEqual(self.issue_files(), [])
        self.assertFalse((self.round_dir / "summary.json").exists())


class CleanRoundTest(FindingsFixture):
    """Section 3.5.3: a clean round writes no issue files."""

    def test_pass_writes_a_summary_and_no_issues(self):
        self.write_run(
            [_layer("unit"), _layer("integration"), _layer("e2e"), _layer("a11y")],
            verdict="pass",
        )
        code, doc = self.cli("report", ["--round", "1", "--run", RUN_ID])
        self.assertEqual(code, common.OK)
        self.assertEqual(self.issue_files(), [])
        self.assertEqual(self.summary()["verdict"], "pass")
        self.assertEqual(self.summary()["counts"]["total"], 0)
        self.assertTrue((self.round_dir / "summary.md").is_file())

    def test_incomplete_pass_is_never_reported_as_a_bare_pass(self):
        self.write_run(
            [
                _layer("unit"),
                _layer("integration"),
                _layer("e2e"),
                _layer(
                    "a11y",
                    status="skipped-unavailable",
                    exit_code=None,
                    reason="axe tooling not installed",
                ),
            ],
            verdict="pass",
            complete=False,
            skipped=[{"layer": "a11y", "reason": "axe tooling not installed"}],
        )
        code, _ = self.cli("report", ["--round", "1", "--run", RUN_ID])
        self.assertEqual(code, common.OK)
        summary = self.summary()
        self.assertEqual(summary["verdict"], "pass")
        self.assertFalse(summary["complete"])
        self.assertTrue(summary["skippedLayers"])
        body = (self.round_dir / "summary.md").read_text(encoding="utf-8")
        self.assertIn("INCOMPLETE", body.upper())


class BaselineIntegrationTest(FindingsFixture):
    """Sections 3.6 and 4: baseline-matched findings are forced low + informational."""

    def _baseline_run(self):
        finding = _failure(
            source="a11y",
            rule="color-contrast",
            impact="critical",
            testId=None,
            target=".legacy .btn",
            name="Insufficient contrast in the legacy widget",
            file="frontend/src/legacy/widget.tsx",
            line=0,
            statedCriterion=False,
        )
        fingerprint = common.sha256_fp(
            "a11y", "color-contrast", "frontend/src/legacy/widget.tsx", ".legacy .btn"
        )
        (self.repo / "qa").mkdir(parents=True, exist_ok=True)
        (self.repo / "qa" / "baseline.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "generatedAt": "2026-07-01T00:00:00Z",
                    "generatedBy": "qa-agent",
                    "reason": "initial adoption",
                    "history": [],
                    "fingerprints": [
                        {
                            "fp": fingerprint,
                            "source": "a11y",
                            "rule": "color-contrast",
                            "file": "frontend/src/legacy/widget.tsx",
                            "target": ".legacy .btn",
                            "severity": "critical",
                        }
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        self.write_run([_layer("a11y", status="failed", exit_code=1, failures=[finding])])

    def test_preexisting_finding_is_low_and_informational(self):
        self._baseline_run()
        self.cli("report", ["--round", "1", "--run", RUN_ID])
        self.assertEqual(self.issue_files(), ["issue_001.md"])
        values = dict(
            self.frontmatter((self.round_dir / "issue_001.md").read_text(encoding="utf-8"))
        )
        self.assertEqual(values["severity"], "low")
        self.assertEqual(values["status"], "informational")

    def test_summary_reports_the_baseline_partition(self):
        self._baseline_run()
        self.cli("report", ["--round", "1", "--run", RUN_ID])
        baseline = self.summary()["baseline"]
        self.assertTrue(baseline["used"])
        self.assertEqual(baseline["preexisting"], 1)
        self.assertEqual(baseline["introduced"], 0)

    def test_no_baseline_flag_disables_the_partition(self):
        self._baseline_run()
        self.cli("report", ["--round", "1", "--run", RUN_ID, "--no-baseline"])
        values = dict(
            self.frontmatter((self.round_dir / "issue_001.md").read_text(encoding="utf-8"))
        )
        self.assertEqual(values["severity"], "critical")
        self.assertEqual(values["status"], "open")
        self.assertFalse(self.summary()["baseline"]["used"])


class BaselineOnlyGateTest(FindingsFixture):
    """Section 4: the verdict rule is absolute unless `gate.baselineOnly` opts out.

    A silent fail -> pass flip made `run.json` and `summary.json` disagree, so a
    CI gate reading summary.json passed a round whose unit layer exited 1.
    """

    def _governed_run(self):
        BaselineIntegrationTest._baseline_run(self)

    def test_baseline_alone_does_not_flip_the_verdict(self):
        self._governed_run()
        code, _ = self.cli("report", ["--round", "1", "--run", RUN_ID])
        summary = self.summary()
        self.assertEqual(summary["verdict"], "fail")
        self.assertEqual(summary["rawVerdict"], "fail")
        self.assertFalse(summary["verdictAdjusted"])
        self.assertEqual(code, common.FAIL)
        # The layer-level truth and the reported verdict agree.
        self.assertEqual(summary["layers"][0]["status"], "failed")

    def test_opt_in_flips_the_verdict_but_records_the_raw_one(self):
        self._governed_run()
        config = copy.deepcopy(common.DEFAULT_CONFIG)
        config["gate"]["baselineOnly"] = True
        code, _ = self.cli("report", ["--round", "1", "--run", RUN_ID], config=config)
        summary = self.summary()
        self.assertEqual(summary["verdict"], "pass")
        self.assertEqual(summary["rawVerdict"], "fail")
        self.assertTrue(summary["verdictAdjusted"])
        self.assertEqual(code, common.OK)
        self.assertTrue(
            any("gate.baselineOnly=true" in reason for reason in summary["reasons"]),
            "the summary must say why the verdict was adjusted",
        )

    def test_verdict_subcommand_does_not_contradict_itself(self):
        self._governed_run()
        config = copy.deepcopy(common.DEFAULT_CONFIG)
        config["gate"]["baselineOnly"] = True
        self.cli("report", ["--round", "1", "--run", RUN_ID], config=config)
        _, document = self.cli("verdict", ["--round", "1", "--run", RUN_ID], config=config)
        self.assertEqual(document["verdict"], "pass")
        self.assertTrue(document["verdictAdjusted"])
        # The reasons must explain the pass, not argue for a fail.
        joined = " ".join(document["reasons"])
        self.assertIn("gate.baselineOnly=true", joined)


class AxeIngestionTest(FindingsFixture):
    """Section 7: axe payloads reach the pipeline, so impact -> severity is real."""

    AXE = {
        "url": "http://localhost:5173/cart",
        "violations": [
            {
                "id": "color-contrast",
                "impact": "critical",
                "help": "Elements must have sufficient colour contrast",
                "helpUrl": "https://dequeuniversity.com/rules/axe/4.10/color-contrast",
                "nodes": [
                    {
                        "impact": "critical",
                        "target": [".cart .total"],
                        "failureSummary": "Fix any of the following: contrast 2.1:1",
                    }
                ],
            }
        ],
        "incomplete": [
            {
                "id": "aria-hidden-focus",
                "impact": "serious",
                "help": "aria-hidden elements must not be focusable",
                "nodes": [{"target": ["#promo"]}],
            }
        ],
    }

    def _run_with_axe(self):
        payload = self.repo / "test-results" / "cart" / "axe-cart.json"
        payload.parent.mkdir(parents=True, exist_ok=True)
        payload.write_text(json.dumps(self.AXE), encoding="utf-8")
        coarse = _failure(
            source="a11y",
            rule=None,
            impact=None,
            testId=None,
            target="frontend:playwright#abc",
            name="a11y layer failed with exit code 1",
            file="e2e",
            line=0,
            statedCriterion=False,
        )
        self.write_run([_layer("a11y", status="failed", exit_code=1, failures=[coarse])])
        return payload

    def test_axe_impact_drives_severity_not_the_coarse_default(self):
        payload = self._run_with_axe()
        self.cli("report", ["--round", "1", "--run", RUN_ID, "--axe", str(payload)])
        self.assertEqual(self.issue_files(), ["issue_001.md"])
        text = (self.round_dir / "issue_001.md").read_text(encoding="utf-8")
        values = dict(self.frontmatter(text))
        # axe impact "critical" -> severity critical, NOT the medium a coarse
        # runner failure would have carried.
        self.assertEqual(values["severity"], "critical")
        self.assertEqual(values["source"], "a11y")
        self.assertIn("color-contrast", text)

    def test_incomplete_results_become_manual_items_never_failures(self):
        payload = self._run_with_axe()
        self.cli("report", ["--round", "1", "--run", RUN_ID, "--axe", str(payload)])
        summary = self.summary()
        self.assertTrue(summary["manualItems"], "axe incomplete[] must surface as manual")
        self.assertTrue(
            any("aria-hidden-focus" in json.dumps(item) for item in summary["manualItems"])
        )
        # The incomplete rule must not have been filed as a blocking issue.
        self.assertNotIn(
            "aria-hidden-focus",
            (self.round_dir / "issue_001.md").read_text(encoding="utf-8"),
        )

    def test_component_scan_payload_still_gets_a_real_file(self):
        """jest-axe payloads carry no `url`; an empty `file:` frontmatter is a bug."""
        payload = self.repo / "qa-axe-user-menu.json"
        payload.write_text(
            json.dumps(
                {
                    "component": "frontend/src/components/user-menu.tsx",
                    "violations": self.AXE["violations"],
                }
            ),
            encoding="utf-8",
        )
        self.write_run([_layer("a11y", status="failed", exit_code=1, failures=[])])
        self.cli("report", ["--round", "1", "--run", RUN_ID, "--axe", str(payload)])
        values = dict(
            self.frontmatter((self.round_dir / "issue_001.md").read_text(encoding="utf-8"))
        )
        self.assertEqual(values["file"], "frontend/src/components/user-menu.tsx")

    def test_payload_without_url_or_component_falls_back_to_the_artifact_path(self):
        payload = self.repo / "qa-axe-anon.json"
        payload.write_text(json.dumps({"violations": self.AXE["violations"]}), encoding="utf-8")
        self.write_run([_layer("a11y", status="failed", exit_code=1, failures=[])])
        self.cli("report", ["--round", "1", "--run", RUN_ID, "--axe", str(payload)])
        values = dict(
            self.frontmatter((self.round_dir / "issue_001.md").read_text(encoding="utf-8"))
        )
        self.assertTrue(values["file"].strip('"'), "an issue must never have an empty file")

    def test_missing_axe_file_is_a_usage_error(self):
        self.write_run([_layer("a11y", status="failed", exit_code=1, failures=[])])
        with self.assertRaises(common.QaError) as caught:
            self.cli("report", ["--round", "1", "--run", RUN_ID, "--axe", "nope/missing.json"])
        # qa.py's dispatcher turns a QaError into its exit code.
        self.assertEqual(caught.exception.code, common.USAGE)


class ManualItemTest(FindingsFixture):
    """Section 3.5 / 1: criteria that cannot be automated surface as open items."""

    def test_manual_plan_checks_reach_the_summary(self):
        plan = {
            "schemaVersion": 1,
            "round": 1,
            "inferenceBased": False,
            "requirementDocs": ["tasks/prd-x/prd.md"],
            "requirements": [{"ref": "FR-7", "text": "print stylesheet", "source": "prd.md#L7"}],
            "checks": [
                {
                    "id": "CHK-001",
                    "requirementRef": "FR-7",
                    "layer": "e2e",
                    "target": "/invoice",
                    "reason": "requires visual judgement",
                    "status": "manual",
                    "manualReason": "requires visual judgement",
                    "testFile": None,
                }
            ],
        }
        plan_path = self.round_dir / "plan.json"
        plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        self.write_run([_layer("unit")], verdict="pass")
        self.cli("report", ["--round", "1", "--run", RUN_ID, "--plan", str(plan_path)])
        manual = self.summary()["manualItems"]
        self.assertTrue(manual, "a manual check must never be a silent pass")
        self.assertIn("FR-7", json.dumps(manual))
        self.assertIn("visual judgement", json.dumps(manual))


class VerdictSubcommandTest(FindingsFixture):
    """Section 3.8: `verdict` recomputes and exits 0 on pass, 1 on fail."""

    def test_pass_exits_zero(self):
        self.write_run([_layer("unit"), _layer("e2e")], verdict="pass")
        code, doc = self.cli("verdict", ["--round", "1", "--run", RUN_ID])
        self.assertEqual(code, common.OK)
        self.assertEqual(doc["verdict"], "pass")
        self.assertIn("complete", doc)
        self.assertIn("reasons", doc)

    def test_fail_exits_one(self):
        self.write_run([_layer("unit", status="failed", exit_code=1)], verdict="fail")
        code, doc = self.cli("verdict", ["--round", "1", "--run", RUN_ID])
        self.assertEqual(code, common.FAIL)
        self.assertEqual(doc["verdict"], "fail")
        self.assertTrue(doc["reasons"])

    def test_flaky_layer_fails_even_though_the_retry_passed(self):
        self.write_run(
            [_layer("unit", status="flaky", exit_code=0, flakes=[{"testId": "a::b"}])],
            verdict="fail",
        )
        code, doc = self.cli("verdict", ["--round", "1", "--run", RUN_ID])
        self.assertEqual(code, common.FAIL)
        self.assertEqual(doc["verdict"], "fail")


class ModuleSurfaceTest(unittest.TestCase):
    """Section 9: qa_findings owns `report` and `verdict`."""

    def test_owns_both_subcommands(self):
        for name in ("report", "verdict"):
            add_arguments, runner = _entry(qa_findings, name)
            self.assertTrue(callable(add_arguments), name)
            self.assertTrue(callable(runner), name)

    def test_exposes_library_functions(self):
        for name in ("severity_for", "compute_verdict", "write_issue", "render_issue"):
            with self.subTest(function=name):
                self.assertTrue(callable(getattr(qa_findings, name, None)))


if __name__ == "__main__":  # pragma: no cover - manual execution
    unittest.main()
