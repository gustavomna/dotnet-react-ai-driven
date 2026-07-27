"""Contract tests for ``qa_suppress`` (QA Agent contract section 3.7, PRD ADR-005).

A suppression is valid only with a target, a reason and an expiry condition.
Anything missing, expired, rule-scoped against an axe rule, or aimed at a broad
selector is rejected -- and a rejected suppression means the check runs anyway.
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
    from .. import qa_suppress
except ImportError:  # pragma: no cover - direct script execution
    import qa_common as common
    import qa_suppress


TODAY = "2026-07-25"

VENDOR_TARGET = "a11y:aria-required-children:frontend/src/vendor/date-picker.tsx"

VALID_ENTRY = {
    "id": "sup-001",
    "target": VENDOR_TARGET,
    "reason": "third-party date picker; upstream issue vendor/dp#412",
    "expires": "2026-12-31",
    "scope": "third-party",
    "addedBy": "gustavo",
    "addedAt": "2026-07-25",
}

VENDOR_FINDING = {
    "source": "a11y",
    "rule": "aria-required-children",
    "testId": None,
    "name": "Required ARIA children missing",
    "file": "frontend/src/vendor/date-picker.tsx",
    "line": 0,
    "target": ".dp-root",
    "impact": "serious",
    "message": "axe reported aria-required-children",
    "expected": None,
    "actual": None,
    "requirementRef": None,
    "statedCriterion": False,
    "flaky": False,
    "helpUrl": None,
    "reproduce": "npx playwright test e2e/a11y.spec.ts",
    "suggestedFix": None,
}


def _entry(module, name):
    commands = getattr(module, "COMMANDS", None)
    if commands:
        for item in commands:
            if item[0] == name:
                return item[2], item[3]
        raise AssertionError("{0} does not own the {1!r} subcommand".format(module, name))
    assert getattr(module, "COMMAND", None) == name, "COMMAND must be {0!r}".format(name)
    return module.add_arguments, module.run


def _valid(result):
    assert isinstance(result, dict), "validate_entry must return a dict, got {0!r}".format(result)
    assert "valid" in result, "validate_entry result must carry a 'valid' flag: {0!r}".format(result)
    return bool(result["valid"])


class SuppressFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)
        self.qa_dir = self.repo / "qa"
        self.qa_dir.mkdir(parents=True, exist_ok=True)

    def ctx(self, config=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            return common.Context(repo=self.repo, config=config, json_only=True)

    def write_suppressions(self, entries):
        (self.qa_dir / "suppressions.json").write_text(
            json.dumps({"schemaVersion": 1, "suppressions": list(entries)}, indent=2),
            encoding="utf-8",
        )

    def loaded(self):
        return qa_suppress.load_suppressions(self.ctx())

    def suppressions_file(self):
        return json.loads((self.qa_dir / "suppressions.json").read_text(encoding="utf-8"))

    def cli(self, argv, config=None):
        add_arguments, runner = _entry(qa_suppress, "suppress")
        parser = argparse.ArgumentParser(prog="qa.py suppress")
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


class LoadTest(SuppressFixture):
    """Section 3.7: a missing suppressions file is an empty set, not an error."""

    def test_missing_file_yields_no_suppressions(self):
        self.assertEqual(self.loaded().get("suppressions"), [])

    def test_existing_file_is_loaded(self):
        self.write_suppressions([VALID_ENTRY])
        self.assertEqual(len(self.loaded()["suppressions"]), 1)


class ValidateEntryTest(SuppressFixture):
    """Section 3.7: all three parts are mandatory; anything else is invalid."""

    def test_a_complete_third_party_suppression_is_valid(self):
        result = qa_suppress.validate_entry(dict(VALID_ENTRY), TODAY)
        self.assertTrue(_valid(result), result)
        self.assertFalse(result.get("expired"), result)

    def test_missing_part_makes_the_entry_invalid(self):
        for part in ("target", "reason", "expires"):
            with self.subTest(missing=part):
                entry = dict(VALID_ENTRY)
                entry.pop(part)
                self.assertFalse(_valid(qa_suppress.validate_entry(entry, TODAY)))

    def test_empty_part_makes_the_entry_invalid(self):
        for part in ("target", "reason", "expires"):
            for value in ("", "   "):
                with self.subTest(part=part, value=repr(value)):
                    entry = dict(VALID_ENTRY)
                    entry[part] = value
                    self.assertFalse(_valid(qa_suppress.validate_entry(entry, TODAY)))

    def test_invalid_entries_report_why(self):
        entry = dict(VALID_ENTRY)
        entry.pop("reason")
        result = qa_suppress.validate_entry(entry, TODAY)
        self.assertFalse(_valid(result))
        self.assertTrue(
            json.dumps(result).lower().count("reason") >= 1,
            "the rejection must name the missing part: {0!r}".format(result),
        )

    def test_expiry_may_be_a_version_or_a_ticket(self):
        for expires in (">=2.0.0", "v3.1", "JIRA-123", "https://tracker.example/issues/1"):
            with self.subTest(expires=expires):
                entry = dict(VALID_ENTRY)
                entry["expires"] = expires
                result = qa_suppress.validate_entry(entry, TODAY)
                self.assertTrue(_valid(result), result)
                self.assertFalse(result.get("expired"), result)

    def test_a_past_iso_date_is_expired(self):
        entry = dict(VALID_ENTRY)
        entry["expires"] = "2020-01-01"
        result = qa_suppress.validate_entry(entry, TODAY)
        self.assertTrue(result.get("expired"), result)

    def test_a_future_iso_date_is_not_expired(self):
        entry = dict(VALID_ENTRY)
        entry["expires"] = "2099-01-01"
        result = qa_suppress.validate_entry(entry, TODAY)
        self.assertTrue(_valid(result), result)
        self.assertFalse(result.get("expired"), result)

    def test_rule_scope_against_an_axe_rule_is_rejected(self):
        entry = dict(VALID_ENTRY)
        entry["scope"] = "rule"
        entry["target"] = "a11y:color-contrast:frontend/src/components/foo.tsx"
        self.assertFalse(
            _valid(qa_suppress.validate_entry(entry, TODAY)),
            "disabling an axe rule is forbidden by the PRD",
        )

    def test_broad_selectors_are_rejected(self):
        for target in ("html", "body", "#root", "#app", "*", "", "   "):
            with self.subTest(target=repr(target)):
                entry = dict(VALID_ENTRY)
                entry["target"] = target
                self.assertFalse(_valid(qa_suppress.validate_entry(entry, TODAY)))

    def test_test_scope_is_accepted(self):
        entry = dict(VALID_ENTRY)
        entry["scope"] = "test"
        entry["target"] = "test:frontend/src/vendor/legacy.test.ts::vendor clock"
        self.assertTrue(_valid(qa_suppress.validate_entry(entry, TODAY)))

    def test_an_unknown_scope_is_rejected(self):
        entry = dict(VALID_ENTRY)
        entry["scope"] = "everything"
        self.assertFalse(_valid(qa_suppress.validate_entry(entry, TODAY)))


class IsSuppressedTest(SuppressFixture):
    """Section 3.7: an invalid or expired suppression never silences a check."""

    def test_a_valid_third_party_suppression_silences_the_matching_finding(self):
        self.write_suppressions([VALID_ENTRY])
        self.assertTrue(qa_suppress.is_suppressed(VENDOR_FINDING, self.loaded(), TODAY))

    def test_a_suppression_does_not_leak_to_other_findings(self):
        self.write_suppressions([VALID_ENTRY])
        other = dict(VENDOR_FINDING)
        other["file"] = "frontend/src/components/foo.tsx"
        self.assertFalse(qa_suppress.is_suppressed(other, self.loaded(), TODAY))

    def test_a_different_rule_is_not_suppressed(self):
        self.write_suppressions([VALID_ENTRY])
        other = dict(VENDOR_FINDING)
        other["rule"] = "color-contrast"
        self.assertFalse(qa_suppress.is_suppressed(other, self.loaded(), TODAY))

    def test_an_invalid_suppression_lets_the_check_run(self):
        for part in ("target", "reason", "expires"):
            with self.subTest(missing=part):
                entry = dict(VALID_ENTRY)
                entry.pop(part)
                self.write_suppressions([entry])
                self.assertFalse(
                    qa_suppress.is_suppressed(VENDOR_FINDING, self.loaded(), TODAY),
                    "an incomplete suppression must never silence a check",
                )

    def test_an_expired_suppression_lets_the_check_run(self):
        entry = dict(VALID_ENTRY)
        entry["expires"] = "2020-01-01"
        self.write_suppressions([entry])
        self.assertFalse(qa_suppress.is_suppressed(VENDOR_FINDING, self.loaded(), TODAY))

    def test_a_rule_scoped_axe_suppression_lets_the_check_run(self):
        entry = dict(VALID_ENTRY)
        entry["scope"] = "rule"
        self.write_suppressions([entry])
        self.assertFalse(qa_suppress.is_suppressed(VENDOR_FINDING, self.loaded(), TODAY))

    def test_no_suppressions_means_nothing_is_suppressed(self):
        self.assertFalse(qa_suppress.is_suppressed(VENDOR_FINDING, self.loaded(), TODAY))


class ValidateCommandTest(SuppressFixture):
    """Section 3.7: `suppress validate` exits 0 when clean, 5 when anything is invalid."""

    def test_all_valid_exits_zero(self):
        self.write_suppressions([VALID_ENTRY])
        code, doc = self.cli(["validate", "--today", TODAY])
        self.assertEqual(code, common.OK)
        self.assertEqual(doc["schemaVersion"], 1)

    def test_any_invalid_exits_invalid_suppression(self):
        broken = dict(VALID_ENTRY)
        broken["id"] = "sup-002"
        broken.pop("expires")
        self.write_suppressions([VALID_ENTRY, broken])
        code, doc = self.cli(["validate", "--today", TODAY])
        self.assertEqual(code, common.INVALID_SUPPRESSION)
        self.assertIn("sup-002", json.dumps(doc))

    def test_no_suppressions_file_is_clean(self):
        code, _ = self.cli(["validate", "--today", TODAY])
        self.assertEqual(code, common.OK)

    def test_expired_entries_are_reported(self):
        expired = dict(VALID_ENTRY)
        expired["expires"] = "2020-01-01"
        self.write_suppressions([expired])
        _, doc = self.cli(["validate", "--today", TODAY])
        self.assertIn("expired", json.dumps(doc).lower())

    def test_a_broad_exclusion_is_rejected_by_the_command(self):
        broad = dict(VALID_ENTRY)
        broad["target"] = "#root"
        self.write_suppressions([broad])
        code, _ = self.cli(["validate", "--today", TODAY])
        self.assertEqual(code, common.INVALID_SUPPRESSION)


class AddCommandTest(SuppressFixture):
    """Section 3.7: `suppress add` records id, addedAt and addedBy."""

    def test_add_appends_a_numbered_entry(self):
        code, _ = self.cli(
            [
                "add",
                "--target",
                VENDOR_TARGET,
                "--reason",
                "third-party date picker; upstream issue vendor/dp#412",
                "--expires",
                "2026-12-31",
                "--scope",
                "third-party",
                "--by",
                "gustavo",
            ]
        )
        self.assertEqual(code, common.OK)
        entries = self.suppressions_file()["suppressions"]
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["id"], "sup-001")
        self.assertEqual(entry["target"], VENDOR_TARGET)
        self.assertEqual(entry["expires"], "2026-12-31")
        self.assertEqual(entry["scope"], "third-party")
        self.assertEqual(entry["addedBy"], "gustavo")
        self.assertRegex(entry["addedAt"], r"^\d{4}-\d{2}-\d{2}")

    def test_ids_continue_from_the_highest_existing_entry(self):
        self.write_suppressions([VALID_ENTRY])
        self.cli(
            [
                "add",
                "--target",
                "test:frontend/src/vendor/legacy.test.ts::clock",
                "--reason",
                "vendor fixture depends on a fixed clock",
                "--expires",
                "JIRA-4711",
                "--scope",
                "test",
            ]
        )
        entries = self.suppressions_file()["suppressions"]
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["id"], "sup-001")
        self.assertEqual(entries[1]["id"], "sup-002")

    def test_added_by_falls_back_when_no_author_is_given(self):
        self.cli(
            [
                "add",
                "--target",
                VENDOR_TARGET,
                "--reason",
                "third-party widget",
                "--expires",
                "2026-12-31",
            ]
        )
        entry = self.suppressions_file()["suppressions"][0]
        self.assertTrue(entry["addedBy"])

    def test_file_keeps_the_contract_shape(self):
        self.cli(
            [
                "add",
                "--target",
                VENDOR_TARGET,
                "--reason",
                "third-party widget",
                "--expires",
                "2026-12-31",
            ]
        )
        doc = self.suppressions_file()
        self.assertEqual(doc["schemaVersion"], 1)
        self.assertIsInstance(doc["suppressions"], list)


class ListCommandTest(SuppressFixture):
    """Section 3.7: `suppress list` reports what is on record."""

    def test_list_reports_every_entry(self):
        self.write_suppressions([VALID_ENTRY])
        code, doc = self.cli(["list"])
        self.assertEqual(code, common.OK)
        self.assertIn(VENDOR_TARGET, json.dumps(doc))

    def test_list_of_an_empty_set_is_not_an_error(self):
        code, doc = self.cli(["list"])
        self.assertEqual(code, common.OK)
        self.assertEqual(doc["schemaVersion"], 1)


class ModuleSurfaceTest(unittest.TestCase):
    """Section 9: qa_suppress owns `suppress` and exposes its library helpers."""

    def test_owns_the_suppress_subcommand(self):
        add_arguments, runner = _entry(qa_suppress, "suppress")
        self.assertTrue(callable(add_arguments))
        self.assertTrue(callable(runner))

    def test_exposes_library_functions(self):
        for name in ("load_suppressions", "validate_entry", "is_suppressed"):
            with self.subTest(function=name):
                self.assertTrue(callable(getattr(qa_suppress, name, None)))


if __name__ == "__main__":  # pragma: no cover - manual execution
    unittest.main()
