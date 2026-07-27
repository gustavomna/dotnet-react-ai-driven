"""Contract tests for ``qa_round`` (QA Agent contract sections 2 and 3.3).

Rounds are zero-padded to three digits, allocated as max+1, sealed the moment a
``summary.json`` exists, and never mutated afterwards.
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
    from .. import qa_round
except ImportError:  # pragma: no cover - direct script execution
    import qa_common as common
    import qa_round


def _entry(module, name):
    commands = getattr(module, "COMMANDS", None)
    if commands:
        for entry in commands:
            if entry[0] == name:
                return entry[2], entry[3]
        raise AssertionError("{0} does not own the {1!r} subcommand".format(module, name))
    assert getattr(module, "COMMAND", None) == name, "COMMAND must be {0!r}".format(name)
    return module.add_arguments, module.run


class RoundFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)
        self.rounds = self.repo / "qa" / "rounds"

    def ctx(self, config=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            return common.Context(repo=self.repo, config=config, json_only=True)

    def make_round(self, number, sealed=False, issues=(), runs=()):
        path = self.rounds / "{0:03d}".format(number)
        path.mkdir(parents=True, exist_ok=True)
        (path / "plan.md").write_text("# plan\n", encoding="utf-8")
        for name in issues:
            (path / name).write_text("---\nstatus: open\n---\n\n# issue\n", encoding="utf-8")
        for run_id in runs:
            run_dir = path / "runs" / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "run.json").write_text(
                json.dumps({"schemaVersion": 1, "runId": run_id}), encoding="utf-8"
            )
        if sealed:
            (path / "summary.json").write_text(
                json.dumps({"schemaVersion": 1, "round": number, "verdict": "pass"}),
                encoding="utf-8",
            )
        return path

    def cli(self, argv, config=None):
        add_arguments, runner = _entry(qa_round, "round")
        parser = argparse.ArgumentParser(prog="qa.py round")
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


class AllocationTest(RoundFixture):
    """Section 3.3: `round new` allocates max(existing)+1, zero-padded to three digits."""

    def test_first_round_is_001(self):
        doc = qa_round.new_round(self.ctx())
        self.assertEqual(doc["schemaVersion"], 1)
        self.assertEqual(doc["round"], 1)
        self.assertEqual(doc["id"], "001")
        self.assertEqual(doc["dir"], "qa/rounds/001")
        self.assertFalse(doc["sealed"])
        self.assertTrue((self.rounds / "001").is_dir())

    def test_allocation_is_max_plus_one(self):
        self.make_round(1, sealed=True)
        self.make_round(2, sealed=True)
        doc = qa_round.new_round(self.ctx())
        self.assertEqual(doc["round"], 3)
        self.assertEqual(doc["id"], "003")

    def test_allocation_skips_gaps_rather_than_filling_them(self):
        self.make_round(1, sealed=True)
        self.make_round(7, sealed=True)
        doc = qa_round.new_round(self.ctx())
        self.assertEqual(doc["round"], 8)
        self.assertEqual(doc["id"], "008")
        self.assertTrue((self.rounds / "007").is_dir(), "existing rounds are never removed")

    def test_padding_survives_two_digit_rounds(self):
        self.make_round(9, sealed=True)
        doc = qa_round.new_round(self.ctx())
        self.assertEqual(doc["id"], "010")
        self.assertEqual(doc["dir"], "qa/rounds/010")

    def test_allocating_never_touches_an_existing_round(self):
        sealed = self.make_round(1, sealed=True, issues=["issue_001.md"])
        before = (sealed / "issue_001.md").read_text(encoding="utf-8")
        qa_round.new_round(self.ctx())
        self.assertEqual((sealed / "issue_001.md").read_text(encoding="utf-8"), before)
        self.assertTrue((sealed / "summary.json").is_file())


class CurrentRoundTest(RoundFixture):
    """Section 3.3: `round current` reports the highest existing round, 0 when none."""

    def test_zero_when_no_round_exists(self):
        self.assertEqual(qa_round.current_round(self.ctx()), 0)
        code, doc = self.cli(["current"])
        self.assertEqual(code, common.OK)
        self.assertEqual(doc["round"], 0)
        self.assertEqual(doc["schemaVersion"], 1)

    def test_highest_existing_round_wins(self):
        self.make_round(1, sealed=True)
        self.make_round(4, sealed=True)
        self.make_round(2, sealed=True)
        self.assertEqual(qa_round.current_round(self.ctx()), 4)

    def test_round_dir_is_absolute_and_zero_padded(self):
        path = qa_round.round_dir(self.ctx(), 3)
        self.assertTrue(pathlib.Path(path).is_absolute())
        self.assertEqual(pathlib.Path(path).name, "003")
        self.assertEqual(pathlib.Path(path).parent.name, "rounds")


class SealingTest(RoundFixture):
    """Section 2 / 3.3: a round is sealed once summary.json exists, and is immutable."""

    def test_is_sealed_tracks_summary_json(self):
        self.make_round(1, sealed=False)
        ctx = self.ctx()
        self.assertFalse(qa_round.is_sealed(ctx, 1))
        self.make_round(1, sealed=True)
        self.assertTrue(qa_round.is_sealed(ctx, 1))

    def test_sealing_a_sealed_round_exits_sealed_round(self):
        self.make_round(1, sealed=True)
        code, _ = self.cli(["seal", "--round", "1"])
        self.assertEqual(code, common.SEALED_ROUND)

    def test_allocating_a_run_in_a_sealed_round_is_refused(self):
        self.make_round(1, sealed=True)
        ctx = self.ctx()
        with self.assertRaises(common.QaError) as caught:
            qa_round.new_run_dir(ctx, 1)
        self.assertEqual(caught.exception.code, common.SEALED_ROUND)

    def test_run_allocation_is_allowed_while_the_round_is_open(self):
        self.make_round(1, sealed=False)
        path = pathlib.Path(qa_round.new_run_dir(self.ctx(), 1, run_id="20260725-140233"))
        self.assertTrue(path.is_dir())
        self.assertEqual(path.name, "20260725-140233")
        self.assertEqual(path.parent.name, "runs")


class RunAllocationTest(RoundFixture):
    """Section 2: several runs may live inside one round; ids never collide."""

    def test_colliding_run_id_is_suffixed_not_reused(self):
        self.make_round(1)
        ctx = self.ctx()
        first = pathlib.Path(qa_round.new_run_dir(ctx, 1, run_id="20260725-140233"))
        second = pathlib.Path(qa_round.new_run_dir(ctx, 1, run_id="20260725-140233"))
        self.assertNotEqual(first, second)
        self.assertTrue(first.is_dir())
        self.assertTrue(second.is_dir())
        self.assertTrue(second.name.startswith("20260725-140233"))

    def test_latest_run_is_none_without_runs(self):
        self.make_round(1)
        self.assertIsNone(qa_round.latest_run(self.ctx(), 1))

    def test_latest_run_returns_the_newest_run_id(self):
        self.make_round(1, runs=["20260725-140233", "20260725-150000", "20260724-090000"])
        self.assertEqual(qa_round.latest_run(self.ctx(), 1), "20260725-150000")

    def test_generated_run_id_has_the_contract_shape(self):
        self.make_round(1)
        path = pathlib.Path(qa_round.new_run_dir(self.ctx(), 1))
        self.assertRegex(path.name, r"^\d{8}-\d{6}")


class IssueNumberingTest(RoundFixture):
    """Section 3.5: issue numbering continues from the highest existing issue."""

    def test_first_issue_is_one(self):
        self.make_round(1)
        self.assertEqual(qa_round.next_issue_number(self.ctx(), 1), 1)

    def test_continues_from_the_highest_existing_issue(self):
        self.make_round(1, issues=["issue_001.md", "issue_004.md"])
        self.assertEqual(qa_round.next_issue_number(self.ctx(), 1), 5)

    def test_two_digit_and_three_digit_issues_are_ordered_numerically(self):
        self.make_round(1, issues=["issue_002.md", "issue_010.md", "issue_009.md"])
        self.assertEqual(qa_round.next_issue_number(self.ctx(), 1), 11)

    def test_unrelated_markdown_does_not_shift_the_counter(self):
        self.make_round(1, issues=["issue_003.md"])
        (self.rounds / "001" / "summary.md").write_text("# summary\n", encoding="utf-8")
        (self.rounds / "001" / "plan.md").write_text("# plan\n", encoding="utf-8")
        self.assertEqual(qa_round.next_issue_number(self.ctx(), 1), 4)


class ShowTest(RoundFixture):
    """Section 3.3: `round show` reports runs[] and issues[]."""

    def test_show_reports_runs_and_issues(self):
        self.make_round(
            1,
            sealed=True,
            issues=["issue_001.md", "issue_002.md"],
            runs=["20260725-140233", "20260725-150000"],
        )
        code, doc = self.cli(["show", "--round", "1"])
        self.assertEqual(code, common.OK)
        self.assertEqual(doc["schemaVersion"], 1)
        self.assertEqual(doc["round"], 1)
        self.assertTrue(doc["sealed"])
        self.assertEqual(len(doc["issues"]), 2)
        self.assertEqual(len(doc["runs"]), 2)

    def test_show_of_an_open_round_reports_sealed_false(self):
        self.make_round(2, sealed=False)
        code, doc = self.cli(["show", "--round", "2"])
        self.assertEqual(code, common.OK)
        self.assertFalse(doc["sealed"])


class NewSubcommandTest(RoundFixture):
    """Section 3.3: `round new` prints the documented document."""

    def test_new_prints_the_contract_document(self):
        self.make_round(1, sealed=True)
        self.make_round(2, sealed=True)
        code, doc = self.cli(["new"])
        self.assertEqual(code, common.OK)
        self.assertEqual(
            sorted(doc.keys()), sorted(["schemaVersion", "round", "id", "dir", "sealed"])
        )
        self.assertEqual(doc["round"], 3)
        self.assertEqual(doc["id"], "003")
        self.assertEqual(doc["dir"], "qa/rounds/003")
        self.assertIs(doc["sealed"], False)
        self.assertTrue((self.rounds / "003").is_dir())


class ModuleSurfaceTest(unittest.TestCase):
    """Section 9: qa_round owns `round` and exposes the round/run helpers."""

    def test_owns_the_round_subcommand(self):
        add_arguments, runner = _entry(qa_round, "round")
        self.assertTrue(callable(add_arguments))
        self.assertTrue(callable(runner))

    def test_exposes_library_functions(self):
        for name in (
            "new_round",
            "current_round",
            "round_dir",
            "is_sealed",
            "new_run_dir",
            "latest_run",
            "next_issue_number",
        ):
            with self.subTest(function=name):
                self.assertTrue(callable(getattr(qa_round, name, None)))


if __name__ == "__main__":  # pragma: no cover - manual execution
    unittest.main()
