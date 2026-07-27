"""Contract tests for ``qa_scope`` (QA Agent contract sections 3.2 and 3.10).

Scope resolution is exercised against a real (temporary) git repository so the
diff, ref-range and intersection semantics are tested for real. Every non-git
subprocess is stubbed: resolving a scope must never run the project toolchain.
"""

import argparse
import contextlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

try:  # pragma: no cover - package import
    from .. import qa_common as common
    from .. import qa_scope
except ImportError:  # pragma: no cover - direct script execution
    import qa_common as common
    import qa_scope


_GIT = shutil.which("git")
_REAL_RUN = subprocess.run
_REAL_CHECK_OUTPUT = subprocess.check_output
_REAL_POPEN = subprocess.Popen


class _Completed(object):
    def __init__(self, args, returncode=0, stdout=b"", stderr=b""):
        self.args = args
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _is_git(args):
    if isinstance(args, (list, tuple)) and args:
        return os.path.basename(str(args[0])) == "git"
    return False


class GitOnlySubprocess(object):
    """Let git through untouched; answer every other command from a canned stub."""

    def __init__(self):
        self.blocked = []
        self._patchers = []

    def run(self, args, **kwargs):
        if _is_git(args):
            return _REAL_RUN(args, **kwargs)
        self.blocked.append([str(a) for a in args] if isinstance(args, (list, tuple)) else [str(args)])
        text = bool(kwargs.get("text") or kwargs.get("universal_newlines") or kwargs.get("encoding"))
        return _Completed(args, 0, "" if text else b"", "" if text else b"")

    def check_output(self, args, **kwargs):
        if _is_git(args):
            return _REAL_CHECK_OUTPUT(args, **kwargs)
        self.blocked.append([str(a) for a in args] if isinstance(args, (list, tuple)) else [str(args)])
        text = bool(kwargs.get("text") or kwargs.get("universal_newlines") or kwargs.get("encoding"))
        return "" if text else b""

    def popen(self, args, **kwargs):
        if _is_git(args):
            return _REAL_POPEN(args, **kwargs)
        raise AssertionError("scope resolution must not launch {0!r}".format(args))

    def __enter__(self):
        for name, replacement in (
            ("run", self.run),
            ("check_output", self.check_output),
            ("Popen", self.popen),
        ):
            patcher = mock.patch("subprocess." + name, replacement)
            patcher.start()
            self._patchers.append(patcher)
        return self

    def __exit__(self, *exc):
        for patcher in reversed(self._patchers):
            patcher.stop()
        self._patchers = []
        return False


def _git(repo, *args):
    env = dict(os.environ)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_TERMINAL_PROMPT"] = "0"
    _REAL_RUN(
        ["git"] + [str(a) for a in args],
        cwd=str(repo),
        env=env,
        shell=False,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _write(root, rel, text):
    path = pathlib.Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _entry(module, name):
    commands = getattr(module, "COMMANDS", None)
    if commands:
        for entry in commands:
            if entry[0] == name:
                return entry[2], entry[3]
        raise AssertionError("{0} does not own the {1!r} subcommand".format(module, name))
    assert getattr(module, "COMMAND", None) == name, "COMMAND must be {0!r}".format(name)
    return module.add_arguments, module.run


#: The feature-branch change set, shared by most cases below.
FEATURE_FILES = {
    "frontend/src/components/foo.tsx": "export const Foo = () => <div />;\n",
    "frontend/src/styles/app.css": ".btn { color: red; }\n",
    "frontend/src/lib/util.ts": "export const add = (a: number, b: number) => a + b;\n",
    "frontend/src/__tests__/foo.test.tsx": "test('foo', () => {});\n",
    "frontend/src/assets/logo.svg": "<svg></svg>\n",
    "frontend/vite.config.ts": "export default {};\n",
    "docs/guide.md": "# guide\n",
    "backend/src/Backend.Api/Controllers/FooController.cs": "public class FooController { }\n",
    "backend/Pages/Index.cshtml": "@page\n<h1>Hi</h1>\n",
}


@unittest.skipUnless(_GIT, "git is not installed in this environment")
class ScopeFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)
        self._build_repo()
        self.stub = GitOnlySubprocess()
        self.stub.__enter__()
        self.addCleanup(self.stub.__exit__, None, None, None)

    def _build_repo(self):
        _git(self.repo, "init", "--quiet")
        _git(self.repo, "symbolic-ref", "HEAD", "refs/heads/main")
        _git(self.repo, "config", "user.email", "qa-agent@example.invalid")
        _git(self.repo, "config", "user.name", "QA Agent Test")
        _git(self.repo, "config", "commit.gpgsign", "false")

        _write(self.repo, "README.md", "# fixture\n")
        _write(
            self.repo,
            "frontend/package.json",
            json.dumps({"name": "frontend", "scripts": {"test": "vitest"}}, indent=2) + "\n",
        )
        _write(self.repo, "frontend/package-lock.json", "{}\n")
        _write(self.repo, "backend/Backend.sln", "Microsoft Visual Studio Solution File\n")
        _write(self.repo, "e2e/app.spec.ts", "test('e2e', async () => {});\n")
        _write(self.repo, "tasks/prd-checkout/prd.md", "# PRD\n\n- FR-1 checkout works\n")
        _write(self.repo, "tasks/prd-checkout/techspec.md", "# Tech Spec\n")
        _write(self.repo, "tasks/prd-checkout/tasks.md", "# Tasks\n")
        _write(self.repo, "docs/prd-notes.md", "# older prd notes\n")
        _write(self.repo, "checkout_user_stories.md", "# user stories\n")
        _write(self.repo, "adrs/adr-001.md", "# ADR 001\n")
        _write(self.repo, ".github/ISSUE_TEMPLATE/bug.md", "# bug template\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "--quiet", "-m", "base")

        _git(self.repo, "checkout", "--quiet", "-b", "feature")
        for rel, text in sorted(FEATURE_FILES.items()):
            _write(self.repo, rel, text)
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "--quiet", "-m", "feature")

    def scope(self, argv, config=None):
        add_arguments, runner = _entry(qa_scope, "scope")
        parser = argparse.ArgumentParser(prog="qa.py scope")
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
        doc = json.loads(stdout) if stdout.strip() else {}
        return code, doc

    @staticmethod
    def paths(doc):
        return sorted(entry["path"] for entry in doc.get("files", []))

    @staticmethod
    def by_path(doc):
        return dict((entry["path"], entry) for entry in doc.get("files", []))


class DocumentShapeTest(ScopeFixture):
    """Section 3.2: the scope document shape is fixed."""

    def test_top_level_keys(self):
        code, doc = self.scope([])
        self.assertEqual(code, common.OK)
        self.assertEqual(doc["schemaVersion"], 1)
        for key in (
            "sources",
            "base",
            "refRange",
            "empty",
            "files",
            "packages",
            "requirementDocs",
            "notes",
        ):
            self.assertIn(key, doc)
        self.assertIsInstance(doc["files"], list)
        self.assertIsInstance(doc["sources"], list)

    def test_file_entries_carry_the_contract_fields(self):
        _, doc = self.scope([])
        for entry in doc["files"]:
            with self.subTest(path=entry.get("path")):
                self.assertIn(entry["kind"], ("source", "test", "config", "doc", "asset", "other"))
                self.assertIsInstance(entry["touchesUi"], bool)
                self.assertIsInstance(entry["isTest"], bool)
                self.assertIn("project", entry)
                self.assertRegex(str(entry["status"]), r"^[AMDRCUT?]")
                self.assertNotIn("\\", entry["path"])


class DefaultDiffTest(ScopeFixture):
    """Section 3.2: with no source given the scope is the diff against the default branch."""

    def test_defaults_to_the_diff_against_main(self):
        code, doc = self.scope([])
        self.assertEqual(code, common.OK)
        self.assertEqual(doc["sources"], ["diff"])
        self.assertEqual(doc["base"], "main")
        self.assertTrue(str(doc["refRange"]).startswith("main..."))
        self.assertFalse(doc["empty"])
        self.assertEqual(self.paths(doc), sorted(FEATURE_FILES))

    def test_explicit_diff_flag_matches_the_default(self):
        _, implicit = self.scope([])
        _, explicit = self.scope(["--diff"])
        self.assertEqual(self.paths(explicit), self.paths(implicit))
        self.assertEqual(explicit["sources"], ["diff"])

    def test_explicit_base_is_honoured(self):
        _, doc = self.scope(["--base", "main"])
        self.assertEqual(doc["base"], "main")
        self.assertEqual(self.paths(doc), sorted(FEATURE_FILES))


class IntersectionTest(ScopeFixture):
    """Section 3.2: when several sources are given, the intersection wins."""

    def test_path_intersected_with_ref_range(self):
        code, doc = self.scope(
            ["--path", "frontend/src/components", "--ref-range", "main...HEAD"]
        )
        self.assertEqual(code, common.OK)
        self.assertEqual(self.paths(doc), ["frontend/src/components/foo.tsx"])
        self.assertEqual(len(doc["sources"]), 2)
        self.assertTrue(any("path" in s for s in doc["sources"]), doc["sources"])
        self.assertTrue(any("ref" in s.lower() for s in doc["sources"]), doc["sources"])

    def test_two_paths_union_within_the_same_source(self):
        _, doc = self.scope(
            [
                "--path",
                "frontend/src/components",
                "--path",
                "frontend/src/lib",
                "--ref-range",
                "main...HEAD",
            ]
        )
        self.assertEqual(
            self.paths(doc),
            ["frontend/src/components/foo.tsx", "frontend/src/lib/util.ts"],
        )

    def test_empty_intersection_exits_empty_scope(self):
        code, doc = self.scope(["--path", "e2e", "--ref-range", "main...HEAD"])
        self.assertEqual(code, common.EMPTY_SCOPE)
        self.assertTrue(doc["empty"])
        self.assertEqual(doc["files"], [])


class ClassificationTest(ScopeFixture):
    """Section 3.2: kind / isTest / touchesUi classification."""

    def test_touches_ui_is_true_for_rendered_surfaces(self):
        _, doc = self.scope(["--ref-range", "main...HEAD"])
        entries = self.by_path(doc)
        for path in (
            "frontend/src/components/foo.tsx",
            "frontend/src/styles/app.css",
            "backend/Pages/Index.cshtml",
        ):
            with self.subTest(path=path):
                self.assertTrue(entries[path]["touchesUi"], path)

    def test_touches_ui_is_false_for_non_rendered_code(self):
        _, doc = self.scope(["--ref-range", "main...HEAD"])
        entries = self.by_path(doc)
        for path in (
            "frontend/src/lib/util.ts",
            "backend/src/Backend.Api/Controllers/FooController.cs",
            "docs/guide.md",
        ):
            with self.subTest(path=path):
                self.assertFalse(entries[path]["touchesUi"], path)

    def test_kind_classification(self):
        _, doc = self.scope(["--ref-range", "main...HEAD"])
        entries = self.by_path(doc)
        self.assertEqual(entries["frontend/src/components/foo.tsx"]["kind"], "source")
        self.assertEqual(entries["frontend/src/__tests__/foo.test.tsx"]["kind"], "test")
        self.assertEqual(entries["frontend/vite.config.ts"]["kind"], "config")
        self.assertEqual(entries["docs/guide.md"]["kind"], "doc")
        self.assertEqual(entries["frontend/src/assets/logo.svg"]["kind"], "asset")

    def test_is_test_flag_tracks_test_files_only(self):
        _, doc = self.scope(["--ref-range", "main...HEAD"])
        entries = self.by_path(doc)
        self.assertTrue(entries["frontend/src/__tests__/foo.test.tsx"]["isTest"])
        self.assertFalse(entries["frontend/src/components/foo.tsx"]["isTest"])


class PackagesTest(ScopeFixture):
    """Section 3.2 / 6: scope is derived per changed package; --package narrows it."""

    def test_packages_lists_every_project_with_an_in_scope_file(self):
        _, doc = self.scope([])
        self.assertEqual(sorted(doc["packages"]), ["backend", "frontend"])
        self.assertEqual(doc["packages"], sorted(doc["packages"]))

    def test_package_flag_narrows_the_scope(self):
        code, doc = self.scope(["--package", "frontend"])
        self.assertEqual(code, common.OK)
        self.assertEqual(doc["packages"], ["frontend"])
        self.assertTrue(doc["files"])
        for entry in doc["files"]:
            self.assertTrue(entry["path"].startswith("frontend/"), entry["path"])

    def test_files_record_their_owning_project(self):
        _, doc = self.scope([])
        entries = self.by_path(doc)
        self.assertEqual(entries["frontend/src/components/foo.tsx"]["project"], "frontend")
        self.assertEqual(
            entries["backend/src/Backend.Api/Controllers/FooController.cs"]["project"], "backend"
        )


class RequirementDiscoveryTest(ScopeFixture):
    """Section 3.2: requirement documents are auto-discovered, issue templates are not."""

    def test_auto_discovers_prd_techspec_and_tasks(self):
        _, doc = self.scope([])
        discovered = set(doc["requirementDocs"])
        for expected in (
            "tasks/prd-checkout/prd.md",
            "tasks/prd-checkout/techspec.md",
            "tasks/prd-checkout/tasks.md",
        ):
            self.assertIn(expected, discovered)

    def test_auto_discovers_docs_user_stories_and_adrs(self):
        _, doc = self.scope([])
        discovered = set(doc["requirementDocs"])
        self.assertIn("docs/prd-notes.md", discovered)
        self.assertIn("checkout_user_stories.md", discovered)
        self.assertIn("adrs/adr-001.md", discovered)

    def test_issue_templates_are_never_requirement_docs(self):
        _, doc = self.scope([])
        for path in doc["requirementDocs"]:
            self.assertFalse(path.startswith(".github/"), path)

    def test_explicit_requirements_replace_discovery(self):
        _, doc = self.scope(["--requirements", "tasks/prd-checkout/prd.md"])
        self.assertIn("tasks/prd-checkout/prd.md", doc["requirementDocs"])
        self.assertNotIn("adrs/adr-001.md", doc["requirementDocs"])

    def test_discovery_output_is_sorted(self):
        _, doc = self.scope([])
        self.assertEqual(doc["requirementDocs"], sorted(doc["requirementDocs"]))


class PlanTest(ScopeFixture):
    """Section 3.10: build_plan provides structure; inferenceBased flags a missing spec."""

    def _stack_doc(self):
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
                    "targets": [
                        {
                            "project": "frontend",
                            "runner": "vitest",
                            "command": ["npm", "run", "test", "--", "--run"],
                            "cwd": "frontend",
                            "testDirs": ["frontend/src/__tests__"],
                            "testGlobs": ["**/*.test.tsx"],
                            "reportFormat": "vitest-json",
                            "reportFlag": [],
                        }
                    ],
                    "reason": None,
                },
                "integration": {"available": False, "targets": [], "reason": "none"},
                "e2e": {"available": False, "targets": [], "reason": "none"},
                "a11y": {"available": False, "targets": [], "reason": "axe tooling not installed"},
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

    def _build(self, requirement_docs):
        _, scope_doc = self.scope([])
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            ctx = common.Context(repo=self.repo, json_only=True)
            plan = qa_scope.build_plan(ctx, scope_doc, self._stack_doc(), requirement_docs)
        return plan

    def test_plan_without_requirement_documents_is_inference_based(self):
        plan = self._build([])
        self.assertEqual(plan["schemaVersion"], 1)
        self.assertTrue(plan["inferenceBased"])
        self.assertEqual(plan["requirementDocs"], [])

    def test_plan_with_requirement_documents_is_not_inference_based(self):
        plan = self._build(["tasks/prd-checkout/prd.md"])
        self.assertFalse(plan["inferenceBased"])
        self.assertIn("tasks/prd-checkout/prd.md", plan["requirementDocs"])

    def test_checks_carry_the_contract_fields(self):
        plan = self._build(["tasks/prd-checkout/prd.md"])
        self.assertIsInstance(plan["checks"], list)
        for check in plan["checks"]:
            with self.subTest(check=check.get("id")):
                self.assertRegex(check["id"], r"^CHK-\d{3}$")
                self.assertIn(check["layer"], common.LAYER_ORDER)
                self.assertIn(check["status"], ("planned", "generated", "manual", "existing"))
                self.assertIn("target", check)
                self.assertIn("reason", check)
                self.assertIn("manualReason", check)
                self.assertIn("requirementRef", check)


class ModuleSurfaceTest(unittest.TestCase):
    """Section 9: qa_scope owns `scope` and `plan` and exposes both library helpers."""

    def test_owns_both_subcommands(self):
        for name in ("scope", "plan"):
            add_arguments, runner = _entry(qa_scope, name)
            self.assertTrue(callable(add_arguments), name)
            self.assertTrue(callable(runner), name)

    def test_exposes_library_functions(self):
        self.assertTrue(callable(getattr(qa_scope, "resolve_scope", None)))
        self.assertTrue(callable(getattr(qa_scope, "build_plan", None)))


if __name__ == "__main__":  # pragma: no cover - manual execution
    unittest.main()
