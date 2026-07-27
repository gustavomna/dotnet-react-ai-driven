"""Contract tests for ``qa_common`` (QA Agent contract sections 3, 3.4, 4, 5, 9).

Every assertion here is derived from the contract text, not from the
implementation: constants, exit codes, the default configuration shape, the deep
config merge, secret redaction, YAML scalar quoting, fingerprint stability,
atomic writes and default-base-branch resolution.
"""

import contextlib
import copy
import hashlib
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

try:  # pragma: no cover - package import
    from .. import qa_common as common
except ImportError:  # pragma: no cover - direct script execution
    import qa_common as common


_GIT = shutil.which("git")

#: Section 6 of the contract, transcribed verbatim.
CONTRACT_DEFAULT_CONFIG = {
    "schemaVersion": 1,
    "roundSequence": "independent",
    "outputDir": "qa",
    "layers": {"unit": True, "integration": True, "e2e": True, "a11y": True},
    "gate": {
        "skippedLayers": "warn",
        "staleRound": "warn",
        "flaky": "fail",
        "baselineOnly": False,
    },
    "scope": {"defaultBase": "main", "packages": []},
    "generation": {"autoStage": False, "testDirOverrides": {}},
    "a11y": {
        "tags": ["wcag2a", "wcag2aa", "wcag22aa"],
        "routes": [],
        "failOnIncomplete": False,
        "resultsGlob": [
            "test-results/**/axe-*.json",
            "**/qa-axe-*.json",
            "**/axe-results*.json",
        ],
    },
    "execution": {"timeoutSeconds": 1800, "retryFailedOnce": True},
}


def _git(repo, *args):
    env = dict(os.environ)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_TERMINAL_PROMPT"] = "0"
    subprocess.run(
        ["git"] + [str(a) for a in args],
        cwd=str(repo),
        env=env,
        shell=False,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _init_repo(root, branch="main"):
    """Create a committed git repo on ``branch`` with no remote configured."""
    _git(root, "init", "--quiet")
    _git(root, "symbolic-ref", "HEAD", "refs/heads/" + branch)
    _git(root, "config", "user.email", "qa-agent@example.invalid")
    _git(root, "config", "user.name", "QA Agent Test")
    _git(root, "config", "commit.gpgsign", "false")
    (pathlib.Path(root) / "README.md").write_text("# fixture\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "--quiet", "-m", "base")


class ConstantsTest(unittest.TestCase):
    """Section 9: the shared constants other modules are written against."""

    def test_layer_order_is_unit_integration_e2e_a11y(self):
        self.assertEqual(common.LAYER_ORDER, ("unit", "integration", "e2e", "a11y"))

    def test_severities_are_ordered_most_severe_first(self):
        self.assertEqual(common.SEVERITIES, ("critical", "high", "medium", "low"))

    def test_schema_version_is_one(self):
        self.assertEqual(common.SCHEMA_VERSION, 1)

    def test_exit_codes_match_the_contract_table(self):
        """Section 3: exit codes are a shared, numbered contract."""
        self.assertEqual(
            (
                common.OK,
                common.FAIL,
                common.USAGE,
                common.NO_STACK,
                common.EMPTY_SCOPE,
                common.INVALID_SUPPRESSION,
                common.SEALED_ROUND,
                common.RUNTIME_ERROR,
            ),
            (0, 1, 2, 3, 4, 5, 6, 7),
        )

    def test_default_config_matches_section_six_exactly(self):
        self.assertEqual(common.DEFAULT_CONFIG, CONTRACT_DEFAULT_CONFIG)


class QaErrorTest(unittest.TestCase):
    """Section 9: expected conditions raise QaError carrying an exit code."""

    def test_default_code_is_runtime_error(self):
        err = common.QaError("boom")
        self.assertEqual(err.code, common.RUNTIME_ERROR)
        self.assertEqual(str(err), "boom")

    def test_explicit_code_is_preserved(self):
        err = common.QaError("sealed", common.SEALED_ROUND)
        self.assertEqual(err.code, common.SEALED_ROUND)

    def test_is_an_exception(self):
        with self.assertRaises(common.QaError):
            raise common.QaError("nope", common.USAGE)


class ConfigMergeTest(unittest.TestCase):
    """Section 9 / 6: load_config deep-merges the user file over DEFAULT_CONFIG."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)

    def test_missing_file_yields_the_defaults(self):
        merged = common.load_config(self.repo / "qa" / "qa.config.json", self.repo)
        self.assertEqual(merged, CONTRACT_DEFAULT_CONFIG)

    def test_nested_keys_merge_instead_of_replacing_their_parent(self):
        path = self.repo / "qa" / "qa.config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"gate": {"skippedLayers": "fail"}, "a11y": {"routes": ["/", "/cart"]}}),
            encoding="utf-8",
        )
        merged = common.load_config(path, self.repo)

        self.assertEqual(merged["gate"]["skippedLayers"], "fail")
        # Sibling keys of the overridden branch survive.
        self.assertEqual(merged["gate"]["staleRound"], "warn")
        self.assertEqual(merged["gate"]["flaky"], "fail")
        # Sibling branches are untouched.
        self.assertEqual(merged["execution"], {"timeoutSeconds": 1800, "retryFailedOnce": True})
        self.assertEqual(merged["a11y"]["tags"], ["wcag2a", "wcag2aa", "wcag22aa"])
        # Lists replace wholesale rather than concatenating.
        self.assertEqual(merged["a11y"]["routes"], ["/", "/cart"])

    def test_merge_never_mutates_the_module_default(self):
        snapshot = copy.deepcopy(common.DEFAULT_CONFIG)
        path = self.repo / "qa" / "qa.config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"layers": {"e2e": False}}), encoding="utf-8")

        merged = common.load_config(path, self.repo)
        merged["layers"]["unit"] = False
        merged["scope"]["packages"].append("frontend")

        self.assertEqual(common.DEFAULT_CONFIG, snapshot)

    def test_unknown_keys_are_carried_through(self):
        path = self.repo / "qa" / "qa.config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"futureKey": {"a": 1}}), encoding="utf-8")
        merged = common.load_config(path, self.repo)
        self.assertEqual(merged["futureKey"], {"a": 1})
        self.assertEqual(merged["roundSequence"], "independent")


class RedactTest(unittest.TestCase):
    """Section 3.4.4: secrets never reach logs, run.json or issue files."""

    def test_key_value_pair_value_is_scrubbed(self):
        for line in (
            "MY_API_TOKEN=supersecretvalue123",
            "DB_PASSWORD: hunter2hunter2",
            "--auth-token=abcdefghijklmnop",
            "CLIENT_SECRET = 0123456789abcdef",
            "AWS_CREDENTIAL:zzzzzzzzzzzzzzzz",
        ):
            with self.subTest(line=line):
                out = common.redact(line)
                self.assertIn("***REDACTED***", out)
                for secret in (
                    "supersecretvalue123",
                    "hunter2hunter2",
                    "abcdefghijklmnop",
                    "0123456789abcdef",
                    "zzzzzzzzzzzzzzzz",
                ):
                    if secret in line:
                        self.assertNotIn(secret, out)

    def test_bare_and_hyphenated_key_forms_are_scrubbed(self):
        """The contract's regex has a bare `KEY` alternative, not only `_KEY`."""
        for line, secret in (
            ("KEY=abcdef123456789", "abcdef123456789"),
            ("x-api-key: qqqqqqqqqqqqqqq", "qqqqqqqqqqqqqqq"),
            ("--key=hunter2hunter2hunter", "hunter2hunter2hunter"),
            ("SOME_KEY=zzzzzzzzzzzzzzzz", "zzzzzzzzzzzzzzzz"),
        ):
            with self.subTest(line=line):
                out = common.redact(line)
                self.assertNotIn(secret, out)
                self.assertIn("***REDACTED***", out)

    def test_key_lookalikes_are_not_scrubbed(self):
        """Guarding both sides keeps ordinary prose and the `author:` key intact."""
        for line in (
            "the keyboard shortcut is documented",
            "monkey=banana",
            "author: qa-agent",
        ):
            with self.subTest(line=line):
                self.assertEqual(common.redact(line), line)

    def test_bearer_token_is_scrubbed(self):
        out = common.redact("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature")
        self.assertNotIn("eyJhbGciOiJIUzI1NiJ9.payload.signature", out)
        self.assertIn("***REDACTED***", out)

    def test_credential_url_password_is_scrubbed(self):
        out = common.redact("cloning https://ci-bot:p4ssw0rd-secret@example.invalid/repo.git")
        self.assertNotIn("p4ssw0rd-secret", out)
        self.assertIn("***REDACTED***", out)
        self.assertIn("example.invalid/repo.git", out)

    def test_known_secret_environment_variable_value_is_scrubbed(self):
        secret = "s3cr3t-env-value-9f2b1c"
        with mock.patch.dict(os.environ, {"QA_TEST_SECRET_TOKEN": secret}, clear=False):
            out = common.redact("integration layer connected using " + secret + " ok")
        self.assertNotIn(secret, out)
        self.assertIn("***REDACTED***", out)

    def test_ordinary_prose_survives_untouched(self):
        text = "3 tests failed in frontend/src/__tests__/foo.test.tsx (keyboard focus order)"
        self.assertEqual(common.redact(text), text)

    def test_never_raises_on_odd_input(self):
        odd = [
            "",
            "   ",
            "\n\n",
            "TOKEN=",
            "SECRET:",
            "a" * 20000,
            "\\ ( ) [ ] { } * + ? | ^ $ .",
            "éção ✓ \U0001f600 PASSWORD=über-secret-value",
            "multi\nline\nPASSWORD=abcdefghijkl\nmore",
            None,
            12345,
        ]
        for value in odd:
            with self.subTest(value=repr(value)[:40]):
                result = common.redact(value)
                self.assertIsInstance(result, str)

    def test_redaction_is_idempotent(self):
        once = common.redact("API_TOKEN=abcdefghijklmnop")
        twice = common.redact(once)
        self.assertEqual(once, twice)


class YamlScalarTest(unittest.TestCase):
    """Section 5: frontmatter values must stay valid YAML."""

    def test_plain_values_are_not_quoted(self):
        for value in ("open", "high", "unit", "frontend/src/components/foo.tsx", "qa-agent"):
            with self.subTest(value=value):
                self.assertEqual(common.yaml_scalar(value), value)

    def test_values_yaml_would_misparse_are_double_quoted(self):
        for value in (
            "a: b",
            "count # 3",
            "{braced}",
            "[bracketed]",
            "-leading-dash",
            "?leading-question",
            "",
        ):
            with self.subTest(value=value):
                rendered = common.yaml_scalar(value)
                self.assertTrue(
                    rendered.startswith('"') and rendered.endswith('"'),
                    "expected {0!r} to be double-quoted, got {1!r}".format(value, rendered),
                )

    def test_empty_value_renders_as_two_quote_characters(self):
        self.assertEqual(common.yaml_scalar(""), '""')

    def test_embedded_double_quotes_are_escaped(self):
        rendered = common.yaml_scalar('he said "no results"')
        self.assertTrue(rendered.startswith('"') and rendered.endswith('"'))
        self.assertIn('\\"', rendered)
        # The escaped body still contains the original words.
        self.assertIn("he said", rendered)

    def test_quoting_survives_a_naive_round_trip(self):
        for value in ("a: b", "x#y", "plain", "", "-dash"):
            with self.subTest(value=value):
                rendered = common.yaml_scalar(value)
                if rendered.startswith('"'):
                    body = rendered[1:-1]
                    decoded = body.replace('\\"', '"').replace("\\\\", "\\")
                    self.assertEqual(decoded, value)
                else:
                    self.assertEqual(rendered, value)

    def test_non_string_values_render_as_strings(self):
        self.assertIsInstance(common.yaml_scalar(42), str)
        self.assertIn("42", common.yaml_scalar(42))


class Sha256FpTest(unittest.TestCase):
    """Section 3.6: fingerprints join parts with '|' and are prefixed sha256:."""

    def test_matches_the_documented_formula(self):
        expected = "sha256:" + hashlib.sha256(
            "a11y|color-contrast|frontend/src/x.tsx|.btn".encode("utf-8")
        ).hexdigest()
        self.assertEqual(
            common.sha256_fp("a11y", "color-contrast", "frontend/src/x.tsx", ".btn"),
            expected,
        )

    def test_is_stable_across_calls(self):
        first = common.sha256_fp("unit", "", "a.ts", "t")
        second = common.sha256_fp("unit", "", "a.ts", "t")
        self.assertEqual(first, second)

    def test_shape_is_prefix_plus_64_hex_chars(self):
        value = common.sha256_fp("a", "b")
        self.assertTrue(value.startswith("sha256:"))
        self.assertRegex(value, r"^sha256:[0-9a-f]{64}$")

    def test_different_parts_produce_different_fingerprints(self):
        self.assertNotEqual(common.sha256_fp("a", "b"), common.sha256_fp("a", "c"))
        self.assertNotEqual(common.sha256_fp("a", "b"), common.sha256_fp("b", "a"))


class FilesystemHelperTest(unittest.TestCase):
    """Section 9: atomic_write / write_json / read_json / repo_rel."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)
        # The write guard is process-global once any Context has registered a
        # root; register this fixture explicitly so direct helper calls are legal.
        common.register_write_root(self.repo)

    def test_atomic_write_leaves_no_temporary_files_behind(self):
        target = self.repo / "out" / "file.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        common.atomic_write(target, "hello\n")
        self.assertEqual(target.read_text(encoding="utf-8"), "hello\n")
        self.assertEqual(sorted(p.name for p in target.parent.iterdir()), ["file.txt"])

    def test_atomic_write_overwrites_in_place(self):
        target = self.repo / "file.txt"
        common.atomic_write(target, "first\n")
        common.atomic_write(target, "second\n")
        self.assertEqual(target.read_text(encoding="utf-8"), "second\n")
        self.assertEqual(sorted(p.name for p in self.repo.iterdir()), ["file.txt"])

    def test_write_json_creates_parents_and_a_trailing_newline(self):
        target = self.repo / "qa" / "rounds" / "001" / "summary.json"
        common.write_json(target, {"schemaVersion": 1, "verdict": "pass"})
        raw = target.read_text(encoding="utf-8")
        self.assertTrue(raw.endswith("\n"))
        self.assertEqual(json.loads(raw), {"schemaVersion": 1, "verdict": "pass"})

    def test_write_json_preserves_key_order(self):
        target = self.repo / "ordered.json"
        common.write_json(target, {"zebra": 1, "alpha": 2})
        raw = target.read_text(encoding="utf-8")
        self.assertLess(raw.index("zebra"), raw.index("alpha"))

    def test_read_json_returns_the_default_for_a_missing_file(self):
        self.assertIsNone(common.read_json(self.repo / "nope.json"))
        self.assertEqual(common.read_json(self.repo / "nope.json", {"a": 1}), {"a": 1})

    def test_read_json_round_trips(self):
        target = self.repo / "doc.json"
        payload = {"schemaVersion": 1, "files": ["a", "b"]}
        common.write_json(target, payload)
        self.assertEqual(common.read_json(target), payload)

    def test_repo_rel_returns_posix_relative_paths(self):
        self.assertEqual(
            common.repo_rel(self.repo, self.repo / "frontend" / "src" / "a.tsx"),
            "frontend/src/a.tsx",
        )
        self.assertEqual(common.repo_rel(self.repo, self.repo), ".")

    def test_ensure_within_refuses_to_escape_the_root(self):
        with self.assertRaises(common.QaError):
            common.ensure_within(self.repo / "qa", self.repo / "frontend" / "src" / "a.tsx")


class TimestampTest(unittest.TestCase):
    """Section 2 / 3.4: UTC timestamps and run ids have fixed shapes."""

    def test_utc_now_iso_shape(self):
        value = common.utc_now_iso()
        self.assertRegex(value, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")

    def test_run_id_now_shape(self):
        value = common.run_id_now()
        self.assertRegex(value, r"^\d{8}-\d{6}$")
        datetime.strptime(value, "%Y%m%d-%H%M%S")


@unittest.skipUnless(_GIT, "git is not installed in this environment")
class GitHelperTest(unittest.TestCase):
    """Section 3.2: default branch resolution on a repo with no remote."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)

    def test_run_git_returns_code_stdout_stderr(self):
        _init_repo(self.root)
        code, out, err = common.run_git(self.root, "rev-parse", "--abbrev-ref", "HEAD")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "main")
        self.assertIsInstance(err, str)

    def test_run_git_does_not_raise_on_failure_by_default(self):
        _init_repo(self.root)
        code, _, _ = common.run_git(self.root, "rev-parse", "--verify", "refs/heads/does-not-exist")
        self.assertNotEqual(code, 0)

    def test_default_base_branch_prefers_main_without_a_remote(self):
        _init_repo(self.root, branch="main")
        self.assertEqual(common.default_base_branch(self.root), "main")

    def test_default_base_branch_falls_back_to_master(self):
        _init_repo(self.root, branch="master")
        self.assertEqual(common.default_base_branch(self.root), "master")

    def test_default_base_branch_is_none_when_nothing_resolves(self):
        _init_repo(self.root, branch="trunk")
        self.assertIsNone(common.default_base_branch(self.root))


class ContextTest(unittest.TestCase):
    """Section 3 / 9: stdout is JSON only, stderr is prose, --json silences notes."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)

    def _context(self, json_only=False):
        """Build a Context whose streams are captured (constructed inside the redirect)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            ctx = common.Context(repo=self.repo, json_only=json_only)
        return ctx, out, err

    def test_paths_are_absolute_and_qa_dir_defaults_under_the_repo(self):
        ctx, _, _ = self._context()
        self.assertTrue(ctx.repo.is_absolute())
        self.assertTrue(ctx.qa_dir.is_absolute())
        self.assertEqual(ctx.qa_dir, self.repo / "qa")

    def test_config_defaults_to_the_contract_defaults(self):
        ctx, _, _ = self._context()
        self.assertEqual(ctx.config, CONTRACT_DEFAULT_CONFIG)

    def test_emit_writes_indented_json_with_the_given_key_order(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            ctx = common.Context(repo=self.repo, json_only=True)
            ctx.emit({"schemaVersion": 1, "zebra": 1, "alpha": 2})
        text = out.getvalue()
        self.assertEqual(json.loads(text), {"schemaVersion": 1, "zebra": 1, "alpha": 2})
        self.assertIn("\n  ", text)
        self.assertLess(text.index("zebra"), text.index("alpha"))
        self.assertEqual(err.getvalue(), "")

    def test_note_is_suppressed_under_json_only_but_progress_is_not(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            ctx = common.Context(repo=self.repo, json_only=True)
            ctx.note("detected the frontend stack")
            ctx.progress("layer=unit status=running")
        stderr = err.getvalue()
        self.assertNotIn("detected the frontend stack", stderr)
        self.assertIn("layer=unit status=running", stderr)
        self.assertEqual(out.getvalue(), "")

    def test_note_reaches_stderr_when_json_only_is_off(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            ctx = common.Context(repo=self.repo, json_only=False)
            ctx.note("detected the frontend stack")
        self.assertIn("detected the frontend stack", err.getvalue())
        self.assertEqual(out.getvalue(), "")

    def test_rel_returns_repo_relative_posix_paths(self):
        ctx, _, _ = self._context()
        self.assertEqual(ctx.rel(self.repo / "frontend" / "src" / "a.tsx"), "frontend/src/a.tsx")
        self.assertEqual(ctx.rel(str(self.repo / "qa" / "baseline.json")), "qa/baseline.json")


class NoThirdPartyImportTest(unittest.TestCase):
    """Section 3 / 10: standard library only, forever."""

    def test_qa_common_imports_only_the_standard_library(self):
        source = pathlib.Path(common.__file__).read_text(encoding="utf-8")
        third_party = re.findall(
            r"^\s*(?:import|from)\s+(pytest|yaml|requests|numpy|pandas|click|rich|attrs)\b",
            source,
            re.MULTILINE,
        )
        self.assertEqual(third_party, [])


if __name__ == "__main__":  # pragma: no cover - manual execution
    unittest.main()
