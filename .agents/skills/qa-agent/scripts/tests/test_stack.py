"""Contract tests for ``qa_stack`` (QA Agent contract section 3.1).

Detection is exercised against synthetic repositories on disk. Every process
launch is stubbed out: detection must never install anything, never reach the
network, and never run the project's real toolchain during a test.
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
from unittest import mock

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

try:  # pragma: no cover - package import
    from .. import qa_common as common
    from .. import qa_stack
except ImportError:  # pragma: no cover - direct script execution
    import qa_common as common
    import qa_stack


CSPROJ_UNIT = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net10.0</TargetFramework>
    <IsPackable>false</IsPackable>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.11.1" />
    <PackageReference Include="xunit" Version="2.9.2" />
    <PackageReference Include="FluentAssertions" Version="6.12.1" />
  </ItemGroup>
</Project>
"""

CSPROJ_INTEGRATION = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net10.0</TargetFramework>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.11.1" />
    <PackageReference Include="xunit" Version="2.9.2" />
    <PackageReference Include="Microsoft.AspNetCore.Mvc.Testing" Version="10.0.0" />
  </ItemGroup>
</Project>
"""

PLAYWRIGHT_CONFIG = (
    "import { defineConfig } from '@playwright/test';\n"
    "export default defineConfig({ testDir: './e2e' });\n"
)


class _FakeCompleted(object):
    def __init__(self, args, returncode, stdout, stderr):
        self.args = args
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakePopen(object):
    def __init__(self, args, stdout, returncode):
        self.args = args
        self.returncode = returncode
        self._stdout = stdout
        self.stdout = None
        self.stderr = None

    def communicate(self, input=None, timeout=None):  # noqa: A002 - mirrors Popen
        return self._stdout, ""

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        return None

    def terminate(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class StubbedSubprocess(object):
    """Replace every subprocess entry point with a deterministic canned answer."""

    def __init__(self):
        self.calls = []
        self._patchers = []

    @staticmethod
    def _argv(args):
        if isinstance(args, (list, tuple)):
            return [str(a) for a in args]
        return [str(args)]

    def _canned(self, args):
        argv = self._argv(args)
        self.calls.append(argv)
        joined = " ".join(argv)
        if "--version" in argv or "-v" in argv or "version" in argv:
            return 0, "1.99.0\n"
        if "playwright" in joined:
            return 0, "Version 1.99.0\n"
        return 0, ""

    def _wants_text(self, kwargs):
        return bool(kwargs.get("text") or kwargs.get("universal_newlines") or kwargs.get("encoding"))

    def run(self, args, **kwargs):
        code, out = self._canned(args)
        if not self._wants_text(kwargs):
            return _FakeCompleted(args, code, out.encode("utf-8"), b"")
        return _FakeCompleted(args, code, out, "")

    def check_output(self, args, **kwargs):
        code, out = self._canned(args)
        if not self._wants_text(kwargs):
            return out.encode("utf-8")
        return out

    def call(self, args, **kwargs):
        code, _ = self._canned(args)
        return code

    def check_call(self, args, **kwargs):
        code, _ = self._canned(args)
        return code

    def popen(self, args, **kwargs):
        code, out = self._canned(args)
        if not self._wants_text(kwargs):
            out = out.encode("utf-8")
        return _FakePopen(args, out, code)

    def __enter__(self):
        for name, replacement in (
            ("run", self.run),
            ("check_output", self.check_output),
            ("call", self.call),
            ("check_call", self.check_call),
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


def _write(root, rel, text):
    path = pathlib.Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _package_json(name, scripts=None, dev_deps=None):
    return json.dumps(
        {
            "name": name,
            "private": True,
            "type": "module",
            "scripts": scripts if scripts is not None else {"test": "vitest"},
            "devDependencies": dev_deps if dev_deps is not None else {"vitest": "^3.0.0"},
        },
        indent=2,
    )


def _entry(module, name):
    """Resolve (add_arguments, run) for ``name`` from either contract shape."""
    commands = getattr(module, "COMMANDS", None)
    if commands:
        for entry in commands:
            if entry[0] == name:
                return entry[2], entry[3]
        raise AssertionError("{0} does not own the {1!r} subcommand".format(module, name))
    assert getattr(module, "COMMAND", None) == name, "COMMAND must be {0!r}".format(name)
    return module.add_arguments, module.run


def _run_cli(module, name, argv, repo, config=None):
    add_arguments, runner = _entry(module, name)
    parser = argparse.ArgumentParser(prog="qa.py " + name)
    add_arguments(parser)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            namespace = argparse.Namespace(repo=str(repo), qa_dir=None, config=None, json=True)
            args = parser.parse_args(argv, namespace)
            ctx = common.Context(repo=repo, config=config, json_only=True)
            code = runner(args, ctx)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else common.USAGE
    return code, out.getvalue(), err.getvalue()


class StackFixtureMixin(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)
        self.stub = StubbedSubprocess()
        self.stub.__enter__()
        self.addCleanup(self.stub.__exit__, None, None, None)

    def detect(self, config=None, browser=True):
        """Detect against the fixture repo.

        The headless-browser probe inspects the real machine, and a browser-less
        machine now correctly reports browser-bound layers as
        skipped-unavailable. Pin the probe so layer-detection tests assert layer
        detection rather than what happens to be installed on the runner; the
        `browser=False` path is asserted explicitly in HeadlessBrowserGateTest.
        """
        out, err = io.StringIO(), io.StringIO()
        real = qa_stack._detect_runtimes

        def pinned(scan, needs_browser):
            runtimes = real(scan, needs_browser)
            if needs_browser:
                runtimes["headlessBrowser"] = {
                    "available": bool(browser),
                    "detail": "pinned by the test fixture",
                }
            return runtimes

        qa_stack._detect_runtimes = pinned
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                ctx = common.Context(repo=self.repo, config=config, json_only=True)
                doc = qa_stack.detect_stack(ctx)
        finally:
            qa_stack._detect_runtimes = real
        return doc

    def full_repo(self, dev_deps=None, scripts=None, lockfile="package-lock.json"):
        """Frontend (vitest + playwright) plus a .NET xunit backend."""
        if dev_deps is None:
            dev_deps = {"vitest": "^3.0.0", "@playwright/test": "^1.50.0"}
        if scripts is None:
            scripts = {"dev": "vite", "test": "vitest", "build": "vite build"}
        _write(self.repo, "frontend/package.json", _package_json("frontend", scripts, dev_deps))
        _write(self.repo, "frontend/" + lockfile, "{}\n" if lockfile.endswith(".json") else "lock\n")
        _write(self.repo, "frontend/vite.config.ts", "export default {};\n")
        _write(self.repo, "frontend/src/__tests__/app.test.tsx", "test('x', () => {});\n")
        _write(self.repo, "playwright.config.ts", PLAYWRIGHT_CONFIG)
        _write(self.repo, "e2e/app.spec.ts", "test('x', async () => {});\n")
        _write(self.repo, "backend/Backend.sln", "Microsoft Visual Studio Solution File\n")
        _write(self.repo, "backend/src/Backend.Api/Backend.Api.csproj", "<Project />\n")
        _write(
            self.repo,
            "backend/tests/Backend.Api.Tests/Backend.Api.Tests.csproj",
            CSPROJ_UNIT,
        )
        _write(
            self.repo,
            "backend/tests/Backend.Api.Tests/HealthTests.cs",
            "public class HealthTests { }\n",
        )

    @staticmethod
    def project(doc, root):
        for project in doc.get("projects", []):
            candidate = str(project.get("root", "")).strip("/")
            if candidate.startswith("./"):
                candidate = candidate[2:]
            if candidate == root:
                return project
        return None

    @staticmethod
    def targets(doc, layer):
        return doc.get("layers", {}).get(layer, {}).get("targets", [])


class DocumentShapeTest(StackFixtureMixin):
    """Section 3.1: the detect document shape is fixed."""

    def test_top_level_keys_and_schema_version(self):
        self.full_repo()
        doc = self.detect()
        self.assertEqual(doc["schemaVersion"], 1)
        for key in ("repo", "detected", "projects", "layers", "conventions", "runtimes", "notes"):
            self.assertIn(key, doc)
        self.assertTrue(os.path.isabs(doc["repo"]))

    def test_layers_map_holds_exactly_the_four_contract_layers(self):
        self.full_repo()
        doc = self.detect()
        self.assertEqual(set(doc["layers"]), set(common.LAYER_ORDER))
        for layer, entry in doc["layers"].items():
            with self.subTest(layer=layer):
                self.assertIn("available", entry)
                self.assertIn("targets", entry)
                self.assertIn("reason", entry)
                self.assertIsInstance(entry["available"], bool)
                self.assertIsInstance(entry["targets"], list)

    def test_every_target_records_a_reproducible_command(self):
        self.full_repo()
        doc = self.detect()
        seen = 0
        for layer in common.LAYER_ORDER:
            for target in self.targets(doc, layer):
                seen += 1
                self.assertIn("project", target)
                self.assertIn("runner", target)
                self.assertIsInstance(target["command"], list)
                self.assertTrue(target["command"])
                self.assertTrue(all(isinstance(part, str) for part in target["command"]))
                self.assertIn("cwd", target)
        self.assertGreater(seen, 0)

    def test_conventions_and_runtimes_are_reported(self):
        self.full_repo()
        doc = self.detect()
        conventions = doc["conventions"]
        for key in (
            "testFileSuffixes",
            "fileNaming",
            "assertionLibraries",
            "e2eFramework",
            "componentTestLibrary",
        ):
            self.assertIn(key, conventions)
        self.assertEqual(conventions["e2eFramework"], "playwright")
        for runtime in ("node", "dotnet", "headlessBrowser"):
            self.assertIn("available", doc["runtimes"][runtime])


class LayerDetectionTest(StackFixtureMixin):
    """Section 3.1: unit / integration / e2e detection rules."""

    def test_vitest_unit_layer_is_detected_for_the_frontend(self):
        self.full_repo()
        doc = self.detect()
        self.assertTrue(doc["detected"])
        self.assertTrue(doc["layers"]["unit"]["available"])
        runners = [t.get("runner") for t in self.targets(doc, "unit")]
        self.assertIn("vitest", runners)

    def test_dotnet_xunit_test_project_becomes_a_unit_target(self):
        self.full_repo()
        doc = self.detect()
        dotnet_targets = [
            t for t in self.targets(doc, "unit") if t.get("command", [""])[0] == "dotnet"
        ]
        self.assertTrue(dotnet_targets, "expected a `dotnet test` unit target")
        command = dotnet_targets[0]["command"]
        self.assertIn("test", command)
        self.assertTrue(
            any("Backend.Api.Tests" in part for part in command),
            "the dotnet target must name the test project: {0}".format(command),
        )

    def test_playwright_config_yields_an_e2e_layer(self):
        self.full_repo()
        doc = self.detect()
        self.assertTrue(doc["layers"]["e2e"]["available"])
        commands = [" ".join(t["command"]) for t in self.targets(doc, "e2e")]
        self.assertTrue(
            any("playwright" in c for c in commands),
            "expected a playwright e2e command, got {0}".format(commands),
        )

    def test_projects_report_language_and_package_manager(self):
        self.full_repo()
        doc = self.detect()
        frontend = self.project(doc, "frontend")
        backend = self.project(doc, "backend")
        self.assertIsNotNone(frontend, "frontend project not detected")
        self.assertIsNotNone(backend, "backend project not detected")
        self.assertEqual(frontend["language"], "typescript")
        self.assertEqual(frontend["packageManager"], "npm")
        self.assertEqual(backend["language"], "csharp")
        self.assertEqual(backend["packageManager"], "dotnet")
        self.assertTrue(frontend["markers"])

    def test_integration_layer_absent_is_reported_not_an_error(self):
        self.full_repo()
        doc = self.detect()
        integration = doc["layers"]["integration"]
        self.assertFalse(integration["available"])
        self.assertEqual(integration["reason"], "no integration test target detected")
        self.assertEqual(integration["targets"], [])
        # An absent integration layer is not a stack failure.
        self.assertTrue(doc["detected"])

    def test_test_integration_script_enables_the_integration_layer(self):
        self.full_repo(
            scripts={"dev": "vite", "test": "vitest", "test:integration": "vitest run integration"}
        )
        doc = self.detect()
        self.assertTrue(doc["layers"]["integration"]["available"])
        self.assertIsNone(doc["layers"]["integration"]["reason"])
        self.assertTrue(self.targets(doc, "integration"))

    def test_web_application_factory_project_enables_the_integration_layer(self):
        self.full_repo()
        _write(
            self.repo,
            "backend/tests/Backend.Api.IntegrationTests/Backend.Api.IntegrationTests.csproj",
            CSPROJ_INTEGRATION,
        )
        doc = self.detect()
        self.assertTrue(doc["layers"]["integration"]["available"])
        commands = [" ".join(t["command"]) for t in self.targets(doc, "integration")]
        self.assertTrue(any("dotnet" in c for c in commands))


class PackageManagerInferenceTest(StackFixtureMixin):
    """Section 3.1: the package manager comes from the lockfile."""

    def _detect_with_lockfile(self, lockfile):
        self.full_repo(lockfile=lockfile)
        return self.detect()

    def test_npm_lockfile(self):
        doc = self._detect_with_lockfile("package-lock.json")
        self.assertEqual(self.project(doc, "frontend")["packageManager"], "npm")
        self.assertEqual(self.targets(doc, "unit")[0]["command"][0], "npm")

    def test_pnpm_lockfile(self):
        doc = self._detect_with_lockfile("pnpm-lock.yaml")
        self.assertEqual(self.project(doc, "frontend")["packageManager"], "pnpm")

    def test_yarn_lockfile(self):
        doc = self._detect_with_lockfile("yarn.lock")
        self.assertEqual(self.project(doc, "frontend")["packageManager"], "yarn")

    def test_bun_lockfile(self):
        doc = self._detect_with_lockfile("bun.lockb")
        self.assertEqual(self.project(doc, "frontend")["packageManager"], "bun")

    def test_missing_lockfile_defaults_to_npm(self):
        self.full_repo(lockfile="unused-marker.txt")
        doc = self.detect()
        self.assertEqual(self.project(doc, "frontend")["packageManager"], "npm")


class HeadlessBrowserGateTest(StackFixtureMixin):
    """PRD business rule: a missing required runtime is a SKIP, not a failure.

    "When a required runtime is unavailable -- no headless browser, no display
    server -- the affected layer reports skipped-unavailable. A skipped layer
    never counts toward a pass."
    """

    def test_e2e_is_skipped_not_failed_without_a_browser(self):
        self.full_repo()
        doc = self.detect(browser=False)
        e2e = doc["layers"]["e2e"]
        self.assertFalse(e2e["available"])
        self.assertEqual(e2e["targets"], [])
        self.assertIn("no headless browser", e2e["reason"])

    def test_e2e_runs_when_a_browser_is_present(self):
        self.full_repo()
        self.assertTrue(self.detect(browser=True)["layers"]["e2e"]["available"])

    def test_component_scans_survive_a_missing_browser(self):
        """Only the browser-bound half of a mixed a11y layer is dropped."""
        self.full_repo(
            dev_deps={
                "vitest": "^3.0.0",
                "@playwright/test": "^1.50.0",
                "vitest-axe": "^0.1.0",
                "@axe-core/playwright": "^4.10.0",
            }
        )
        doc = self.detect(browser=False)
        a11y = doc["layers"]["a11y"]
        if a11y["available"]:
            runners = {t["runner"] for t in a11y["targets"]}
            self.assertNotIn("playwright", runners, "browser-bound targets must be dropped")
            self.assertIn("vitest", runners, "component scans must survive")
        else:
            self.assertIn("no headless browser", a11y["reason"])


class AccessibilityAvailabilityTest(StackFixtureMixin):
    """Section 3.1 / 7: a11y needs axe tooling and is never auto-installed."""

    def test_unavailable_with_a_reason_naming_the_missing_packages(self):
        self.full_repo()
        doc = self.detect()
        a11y = doc["layers"]["a11y"]
        self.assertFalse(a11y["available"])
        self.assertEqual(a11y["targets"], [])
        self.assertIsInstance(a11y["reason"], str)
        self.assertIn("axe", a11y["reason"].lower())

    def test_available_with_axe_core_playwright(self):
        self.full_repo(
            dev_deps={
                "vitest": "^3.0.0",
                "@playwright/test": "^1.50.0",
                "@axe-core/playwright": "^4.10.0",
            }
        )
        doc = self.detect()
        self.assertTrue(doc["layers"]["a11y"]["available"])
        self.assertIsNone(doc["layers"]["a11y"]["reason"])
        self.assertTrue(self.targets(doc, "a11y"))

    def test_available_with_jest_axe(self):
        self.full_repo(
            dev_deps={"vitest": "^3.0.0", "@playwright/test": "^1.50.0", "jest-axe": "^9.0.0"}
        )
        self.assertTrue(self.detect()["layers"]["a11y"]["available"])

    def test_available_with_vitest_axe(self):
        self.full_repo(
            dev_deps={"vitest": "^3.0.0", "@playwright/test": "^1.50.0", "vitest-axe": "^1.0.0"}
        )
        self.assertTrue(self.detect()["layers"]["a11y"]["available"])

    def test_detection_never_installs_anything(self):
        self.full_repo()
        self.detect()
        for argv in self.stub.calls:
            joined = " ".join(argv)
            self.assertNotIn("install", joined)
            self.assertNotIn(" add ", " " + joined + " ")
            self.assertNotIn("npm i ", joined)


class NoStackTest(StackFixtureMixin):
    """Section 3.1: an undetectable stack stops the agent with NO_STACK."""

    def test_repo_without_any_test_tooling_reports_detected_false(self):
        _write(self.repo, "README.md", "# nothing here\n")
        _write(self.repo, "src/app.js", "export const a = 1;\n")
        doc = self.detect()
        self.assertFalse(doc["detected"])
        for layer in common.LAYER_ORDER:
            self.assertFalse(doc["layers"][layer]["available"], layer)
            self.assertIsInstance(doc["layers"][layer]["reason"], str)

    def test_detect_subcommand_exits_no_stack(self):
        _write(self.repo, "README.md", "# nothing here\n")
        code, stdout, _ = _run_cli(qa_stack, "detect", [], self.repo)
        self.assertEqual(code, common.NO_STACK)
        doc = json.loads(stdout)
        self.assertFalse(doc["detected"])
        self.assertEqual(doc["schemaVersion"], 1)

    def test_detect_subcommand_exits_ok_on_a_detectable_stack(self):
        self.full_repo()
        code, stdout, _ = _run_cli(qa_stack, "detect", [], self.repo)
        self.assertEqual(code, common.OK)
        doc = json.loads(stdout)
        self.assertTrue(doc["detected"])


class DeterminismTest(StackFixtureMixin):
    """Section 3: deterministic output ordering."""

    def test_two_detections_of_the_same_repo_agree(self):
        self.full_repo()
        first = self.detect()
        second = self.detect()
        self.assertEqual(
            json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True)
        )


class ModuleSurfaceTest(unittest.TestCase):
    """Section 9: qa_stack owns `detect` and exposes detect_stack()."""

    def test_declares_the_detect_subcommand(self):
        add_arguments, runner = _entry(qa_stack, "detect")
        self.assertTrue(callable(add_arguments))
        self.assertTrue(callable(runner))
        self.assertTrue(getattr(qa_stack, "HELP", "") or getattr(qa_stack, "COMMANDS", None))

    def test_exposes_detect_stack(self):
        self.assertTrue(callable(getattr(qa_stack, "detect_stack", None)))


if __name__ == "__main__":  # pragma: no cover - manual execution
    unittest.main()
