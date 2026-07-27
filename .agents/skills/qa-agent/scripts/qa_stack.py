"""Test-stack detection for the QA agent.

Walks the repository, discovers project roots, and reports which QA layers
(unit, integration, e2e, a11y) can actually be executed together with the exact
command for each. It never installs anything and never writes into the project
(the optional ``--out`` file is the single, explicitly requested exception).
"""

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from . import qa_common as common
except ImportError:  # pragma: no cover - direct script execution
    import qa_common as common

COMMAND = "detect"
HELP = "Detect the project's test stack."

# Directories that never hold first-party project sources.
EXCLUDED_DIRS = frozenset((
    ".cache", ".git", ".gradle", ".hg", ".idea", ".mypy_cache", ".next",
    ".nuxt", ".pytest_cache", ".svelte-kit", ".svn", ".terraform", ".turbo",
    ".venv", ".vs", ".vscode", "TestResults", "__pycache__", "bin",
    "blob-report", "coverage", "dist", "dist-ssr", "node_modules", "obj",
    "playwright-report", "test-results", "venv",
))

MAX_WALK_FILES = 200000
PROBE_TIMEOUT_SECONDS = 20

# Lockfile -> package manager, in resolution order (first match wins).
LOCKFILES = (
    ("package-lock.json", "npm"),
    ("npm-shrinkwrap.json", "npm"),
    ("pnpm-lock.yaml", "pnpm"),
    ("yarn.lock", "yarn"),
    ("bun.lockb", "bun"),
    ("bun.lock", "bun"),
)

# Package managers that need `--` before forwarding arguments to a script.
PM_NEEDS_DOUBLE_DASH = ("npm", "bun")

JS_CONFIG_MARKER_RE = re.compile(
    r"^(vite|vitest|jest|webpack|rollup|next|nuxt|svelte|astro|tsup|rspack"
    r"|babel|karma|tailwind|remix|angular)\.config\.[cm]?[jt]s$"
)

E2E_CONFIG_RE = re.compile(r"^(playwright|cypress)\.config\.[cm]?[jt]s$")

JS_TEST_FILE_RE = re.compile(r"^(?P<stem>.+)\.(?P<infix>test|spec)\.(?P<ext>[cm]?[jt]sx?)$")
CS_TEST_FILE_RE = re.compile(r"^.+?(?P<suffix>Tests?|Specs?)\.cs$")

DOTNET_PROJECT_EXTS = {".csproj": "csharp", ".fsproj": "fsharp", ".vbproj": "visualbasic"}

PACKAGE_REFERENCE_RE = re.compile(
    r"<PackageReference\s[^>]*Include\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE
)
IS_TEST_PROJECT_RE = re.compile(r"<IsTestProject>\s*true\s*</IsTestProject>", re.IGNORECASE)
TEST_DIR_OPTION_RE = re.compile(r"testDir\s*:\s*[\"'`]([^\"'`]+)[\"'`]")

DOTNET_TEST_PACKAGES = ("microsoft.net.test.sdk", "xunit", "nunit", "mstest.testframework")
DOTNET_INTEGRATION_PACKAGE = "microsoft.aspnetcore.mvc.testing"

AXE_PACKAGES = (
    "jest-axe",
    "vitest-axe",
    "@axe-core/playwright",
    "axe-core",
    "@axe-core/react",
)
AXE_COMPONENT_PACKAGES = ("jest-axe", "vitest-axe", "axe-core", "@axe-core/react")
AXE_PAGE_PACKAGES = ("@axe-core/playwright",)

# Generated a11y tests are filtered by this substring in their file path.
A11Y_FILTER = "a11y"

INTEGRATION_DIR_NAMES = ("integration", "__integration__", "integration-tests", "integrationtests")

UI_SOURCE_EXTS = (".tsx", ".jsx", ".vue", ".svelte", ".cshtml", ".razor")

JS_ASSERTION_PACKAGES = (
    ("vitest", "vitest"),
    ("jest", "jest"),
    ("chai", "chai"),
    ("expect", "expect"),
    ("should", "should"),
)
DOTNET_ASSERTION_PACKAGES = (
    ("fluentassertions", "fluentassertions"),
    ("shouldly", "shouldly"),
    ("xunit", "xunit"),
    ("nunit", "nunit"),
    ("mstest.testframework", "mstest"),
)
COMPONENT_TEST_LIBRARIES = (
    "@testing-library/react",
    "@testing-library/vue",
    "@testing-library/svelte",
    "@testing-library/angular",
    "@vue/test-utils",
    "enzyme",
)


# ---------------------------------------------------------------------------
# Shared path helpers (also used by qa_scope)
# ---------------------------------------------------------------------------

def guard_write_path(ctx, path) -> pathlib.Path:
    """Resolve ``path`` and refuse anything outside the repo or the qa dir."""
    resolved = pathlib.Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = (pathlib.Path(ctx.repo) / resolved)
    resolved = pathlib.Path(os.path.normpath(str(resolved)))
    allowed = [pathlib.Path(os.path.normpath(str(ctx.repo)))]
    qa_dir = getattr(ctx, "qa_dir", None)
    if qa_dir is not None:
        allowed.append(pathlib.Path(os.path.normpath(str(qa_dir))))
    for root in allowed:
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        return resolved
    raise common.QaError(
        "refusing to write outside the repository root: %s" % resolved, common.USAGE
    )


def resolve_input_path(ctx, value) -> pathlib.Path:
    """Resolve a user-supplied input path against the repo root, then the cwd.

    The repo root wins because ``--repo`` makes every other path in the CLI
    repo-relative; falling back to the cwd keeps ad-hoc invocations working.
    """
    candidate = pathlib.Path(str(value)).expanduser()
    if candidate.is_absolute():
        return candidate
    from_repo = pathlib.Path(ctx.repo) / candidate
    if from_repo.exists():
        return from_repo
    from_cwd = pathlib.Path(os.getcwd()) / candidate
    if from_cwd.exists():
        return from_cwd
    return from_repo


def _posix(path: str) -> str:
    return path.replace(os.sep, "/")


def _rel(repo: pathlib.Path, absolute: str) -> str:
    return _posix(os.path.relpath(absolute, str(repo)))


def _dirname(rel_path: str) -> str:
    parent = rel_path.rsplit("/", 1)[0] if "/" in rel_path else ""
    return parent


def _join(base: str, name: str) -> str:
    if not base or base == ".":
        return name
    if not name or name == ".":
        return base
    return base + "/" + name


def _under(path: str, root: str) -> bool:
    """True when ``path`` is inside directory ``root`` (root "" is the repo)."""
    if root in ("", "."):
        return True
    return path == root or path.startswith(root + "/")


def _read_text(path: pathlib.Path, limit: int = 2 * 1024 * 1024) -> str:
    try:
        with open(str(path), "r", encoding="utf-8", errors="replace") as handle:
            return handle.read(limit)
    except (OSError, ValueError):
        return ""


# ---------------------------------------------------------------------------
# Repository walk
# ---------------------------------------------------------------------------

def list_repo_files(repo) -> List[str]:
    """Every non-excluded repo-relative file path, sorted. Shared with qa_scope."""
    files, _ = _walk_files(pathlib.Path(repo))
    return files


def _walk_files(repo: pathlib.Path) -> Tuple[List[str], bool]:
    """Return every non-excluded repo-relative file path, plus a truncation flag."""
    files = []  # type: List[str]
    truncated = False
    for dirpath, dirnames, filenames in os.walk(str(repo)):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS)
        for name in sorted(filenames):
            files.append(_rel(repo, os.path.join(dirpath, name)))
            if len(files) >= MAX_WALK_FILES:
                truncated = True
                break
        if truncated:
            break
    files.sort()
    return files, truncated


# ---------------------------------------------------------------------------
# Project discovery
# ---------------------------------------------------------------------------

def _load_package_json(repo: pathlib.Path, rel_path: str) -> Optional[Dict[str, Any]]:
    text = _read_text(repo / rel_path)
    if not text.strip():
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    deps = {}  # type: Dict[str, str]
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        section = data.get(key)
        if isinstance(section, dict):
            for name, version in section.items():
                deps[str(name)] = str(version)
    scripts = {}  # type: Dict[str, str]
    raw_scripts = data.get("scripts")
    if isinstance(raw_scripts, dict):
        for name, value in raw_scripts.items():
            scripts[str(name)] = str(value)
    return {
        "path": rel_path,
        "dir": _dirname(rel_path),
        "name": str(data.get("name") or ""),
        "deps": deps,
        "scripts": scripts,
    }


def _package_manager_for(repo: pathlib.Path, project_dir: str, all_files: Iterable[str]) -> str:
    present = set(all_files)
    search_dir = project_dir
    while True:
        for lockfile, manager in LOCKFILES:
            if _join(search_dir, lockfile) in present:
                return manager
        if not search_dir:
            break
        search_dir = _dirname(search_dir)
    return "npm"


def _js_language(repo: pathlib.Path, project_dir: str, deps: Dict[str, str],
                 files_by_dir: Dict[str, List[str]]) -> str:
    if "typescript" in deps:
        return "typescript"
    for rel_path in files_by_dir.get(project_dir, []):
        base = rel_path.rsplit("/", 1)[-1]
        if base.startswith("tsconfig") and base.endswith(".json"):
            return "typescript"
    for rel_path in files_by_dir.get("__all__", []):
        if _under(rel_path, project_dir) and (rel_path.endswith(".ts") or rel_path.endswith(".tsx")):
            return "typescript"
    return "javascript"


def _unique_id(base: str, taken: Dict[str, int]) -> str:
    if base not in taken:
        taken[base] = 1
        return base
    taken[base] += 1
    return "%s-%d" % (base, taken[base])


def _id_for_root(root: str) -> str:
    if not root or root == ".":
        return "root"
    return root.replace("/", "-")


def _scan(ctx) -> Dict[str, Any]:
    """Collect every fact the layer builders need, in one repository walk."""
    repo = pathlib.Path(ctx.repo)
    files, truncated = _walk_files(repo)
    notes = []  # type: List[str]
    if truncated:
        notes.append(
            "repository walk stopped at %d files; detection may be incomplete" % MAX_WALK_FILES
        )

    file_set = set(files)
    files_by_dir = {"__all__": files}  # type: Dict[str, List[str]]
    for rel_path in files:
        files_by_dir.setdefault(_dirname(rel_path), []).append(rel_path)

    packages = []  # type: List[Dict[str, Any]]
    for rel_path in files:
        if rel_path.rsplit("/", 1)[-1] != "package.json":
            continue
        record = _load_package_json(repo, rel_path)
        if record is None:
            notes.append("could not parse %s; ignored" % rel_path)
            continue
        packages.append(record)

    solutions = [p for p in files if p.lower().endswith(".sln")]
    dotnet_projects = []  # type: List[Dict[str, Any]]
    for rel_path in files:
        ext = os.path.splitext(rel_path)[1].lower()
        if ext not in DOTNET_PROJECT_EXTS:
            continue
        text = _read_text(repo / rel_path)
        refs = [r.strip().lower() for r in PACKAGE_REFERENCE_RE.findall(text)]
        is_test = bool(IS_TEST_PROJECT_RE.search(text)) or _has_test_package(refs)
        dotnet_projects.append({
            "path": rel_path,
            "dir": _dirname(rel_path),
            "language": DOTNET_PROJECT_EXTS[ext],
            "refs": refs,
            "isTest": is_test,
        })

    e2e_configs = []  # type: List[Dict[str, Any]]
    for rel_path in files:
        base = rel_path.rsplit("/", 1)[-1]
        match = E2E_CONFIG_RE.match(base)
        if not match:
            continue
        text = _read_text(repo / rel_path)
        test_dir_match = TEST_DIR_OPTION_RE.search(text)
        raw_dir = test_dir_match.group(1) if test_dir_match else "."
        config_dir = _dirname(rel_path)
        resolved = _posix(os.path.normpath(_join(config_dir, raw_dir))) if raw_dir else config_dir
        if resolved == ".":
            resolved = config_dir
        e2e_configs.append({
            "framework": match.group(1),
            "path": rel_path,
            "dir": config_dir,
            "testDir": resolved,
        })

    projects = []  # type: List[Dict[str, Any]]
    taken = {}  # type: Dict[str, int]
    for record in sorted(packages, key=lambda r: r["dir"]):
        project_dir = record["dir"]
        markers = [record["path"]]
        for sibling in files_by_dir.get(project_dir, []):
            base = sibling.rsplit("/", 1)[-1]
            if JS_CONFIG_MARKER_RE.match(base) or E2E_CONFIG_RE.match(base):
                markers.append(sibling)
        projects.append({
            "id": _unique_id(_id_for_root(project_dir), taken),
            "root": project_dir,
            "language": _js_language(repo, project_dir, record["deps"], files_by_dir),
            "packageManager": _package_manager_for(repo, project_dir, files),
            "markers": sorted(set(markers)),
            "kind": "js",
            "package": record,
        })

    solution_dirs = sorted({_dirname(p) for p in solutions})
    dotnet_roots = {}  # type: Dict[str, Dict[str, Any]]
    for solution in sorted(solutions):
        root = _dirname(solution)
        entry = dotnet_roots.setdefault(root, {"markers": [], "projects": []})
        entry["markers"].append(solution)
    for record in sorted(dotnet_projects, key=lambda r: r["path"]):
        owner = ""
        best = None  # type: Optional[str]
        for root in solution_dirs:
            if _under(record["path"], root) and (best is None or len(root) > len(best)):
                best = root
        if best is not None:
            owner = best
        else:
            owner = record["dir"]
            dotnet_roots.setdefault(owner, {"markers": [record["path"]], "projects": []})
        dotnet_roots[owner]["projects"].append(record)

    for root in sorted(dotnet_roots):
        entry = dotnet_roots[root]
        languages = sorted({p["language"] for p in entry["projects"]}) or ["csharp"]
        projects.append({
            "id": _unique_id(_id_for_root(root), taken),
            "root": root,
            "language": languages[0],
            "packageManager": "dotnet",
            "markers": sorted(set(entry["markers"])),
            "kind": "dotnet",
            "dotnetProjects": entry["projects"],
        })

    projects.sort(key=lambda p: (p["root"], p["id"]))
    return {
        "repo": repo,
        "files": files,
        "fileSet": file_set,
        "filesByDir": files_by_dir,
        "packages": packages,
        "dotnetProjects": dotnet_projects,
        "e2eConfigs": e2e_configs,
        "projects": projects,
        "notes": notes,
    }


def _has_test_package(refs: Sequence[str]) -> bool:
    for ref in refs:
        for marker in DOTNET_TEST_PACKAGES:
            if ref == marker or ref.startswith(marker + "."):
                return True
    return False


def detect_projects(ctx) -> List[Dict[str, Any]]:
    """Public project list: ``id``, ``root``, ``language``, ``packageManager``, ``markers``."""
    scan = _scan(ctx)
    return _public_projects(scan)


def _public_projects(scan: Dict[str, Any]) -> List[Dict[str, Any]]:
    result = []
    for project in scan["projects"]:
        result.append({
            "id": project["id"],
            "root": project["root"],
            "language": project["language"],
            "packageManager": project["packageManager"],
            "markers": list(project["markers"]),
        })
    return result


# ---------------------------------------------------------------------------
# Runner inference and command construction
# ---------------------------------------------------------------------------

def _infer_js_runner(script_text: str, deps: Dict[str, str]) -> Optional[str]:
    text = (script_text or "").lower()
    for token, runner in (
        ("vitest", "vitest"),
        ("jest", "jest"),
        ("mocha", "mocha"),
        ("playwright", "playwright"),
        ("cypress", "cypress"),
    ):
        if token in text:
            return runner
    for name, runner in (
        ("vitest", "vitest"),
        ("jest", "jest"),
        ("mocha", "mocha"),
        ("@playwright/test", "playwright"),
        ("playwright", "playwright"),
        ("cypress", "cypress"),
    ):
        if name in deps:
            return runner
    return None


def _pm_run(manager: str, script: str, extra: Sequence[str]) -> List[str]:
    command = [manager, "run", script]
    extra = list(extra)
    if not extra:
        return command
    if manager in PM_NEEDS_DOUBLE_DASH:
        return command + ["--"] + extra
    return command + extra


def _runner_extra_args(runner: Optional[str]) -> List[str]:
    if runner == "vitest":
        return ["--run"]
    return []


def _report_spec(runner: Optional[str]) -> Tuple[Optional[str], List[str], Dict[str, str]]:
    """Return ``(reportFormat, reportFlag, reportEnv)`` for a runner."""
    if runner == "vitest":
        return "vitest-json", ["--reporter=json", "--outputFile=<REPORT>"], {}
    if runner == "jest":
        return "jest-json", ["--json", "--outputFile=<REPORT>"], {}
    if runner == "mocha":
        return "mocha-json", ["--reporter=json", "--reporter-options=output=<REPORT>"], {}
    if runner == "playwright":
        return "playwright-json", ["--reporter=json"], {"PLAYWRIGHT_JSON_OUTPUT_NAME": "<REPORT>"}
    if runner == "cypress":
        return "cypress-json", ["--reporter", "json", "--reporter-options", "output=<REPORT>"], {}
    if runner == "dotnet":
        return "trx", ["--logger", "trx;LogFileName=<REPORT>"], {}
    return None, [], {}


def _target(project_id: str, runner: Optional[str], command: Sequence[str], cwd: str,
            test_dirs: Sequence[str], test_globs: Sequence[str]) -> Dict[str, Any]:
    report_format, report_flag, report_env = _report_spec(runner)
    return {
        "project": project_id,
        "runner": runner or "unknown",
        "command": list(command),
        "cwd": cwd or ".",
        "testDirs": sorted(set(test_dirs)),
        "testGlobs": sorted(set(test_globs)),
        "reportFormat": report_format,
        "reportFlag": report_flag,
        "reportEnv": report_env,
    }


# ---------------------------------------------------------------------------
# Test file discovery and conventions
# ---------------------------------------------------------------------------

def _js_test_files(scan: Dict[str, Any], root: str) -> List[Tuple[str, str, str]]:
    """Return ``(path, infix, ext)`` for every JS/TS test file under ``root``."""
    found = []
    for rel_path in scan["files"]:
        if not _under(rel_path, root):
            continue
        match = JS_TEST_FILE_RE.match(rel_path.rsplit("/", 1)[-1])
        if match:
            found.append((rel_path, match.group("infix"), match.group("ext")))
    return found


def _cs_test_files(scan: Dict[str, Any], root: str) -> List[Tuple[str, str]]:
    found = []
    for rel_path in scan["files"]:
        if not _under(rel_path, root) or not rel_path.endswith(".cs"):
            continue
        match = CS_TEST_FILE_RE.match(rel_path.rsplit("/", 1)[-1])
        if match:
            found.append((rel_path, match.group("suffix") + ".cs"))
    return found


def _js_extensions(scan: Dict[str, Any], root: str, language: str) -> List[str]:
    base = "ts" if language == "typescript" else "js"
    exts = [base]
    jsx = base + "x"
    for rel_path in scan["files"]:
        if _under(rel_path, root) and rel_path.endswith("." + jsx):
            exts.append(jsx)
            break
    return exts


def _globs_for(infixes: Iterable[str], exts: Iterable[str]) -> List[str]:
    return sorted("**/*.%s.%s" % (infix, ext) for infix in set(infixes) for ext in set(exts))


def _apply_test_dir_override(ctx, project_id: str, test_dirs: Sequence[str]) -> List[str]:
    overrides = (ctx.config.get("generation") or {}).get("testDirOverrides") or {}
    if isinstance(overrides, dict) and project_id in overrides:
        return [str(overrides[project_id]).strip("/")]
    return list(test_dirs)


# ---------------------------------------------------------------------------
# Layer builders
# ---------------------------------------------------------------------------

def _js_unit_targets(ctx, scan: Dict[str, Any], notes: List[str]) -> List[Dict[str, Any]]:
    targets = []
    e2e_dirs = {config["dir"] for config in scan["e2eConfigs"]}
    for project in scan["projects"]:
        if project["kind"] != "js":
            continue
        package = project["package"]
        scripts = package["scripts"]
        deps = package["deps"]
        script_name = "test" if "test" in scripts else None
        runner = _infer_js_runner(scripts.get("test", ""), deps)
        if runner in ("playwright", "cypress"):
            continue
        if script_name is None and runner is None:
            continue
        root = project["root"]
        test_files = [
            entry for entry in _js_test_files(scan, root)
            if not any(_under(entry[0], d) for d in e2e_dirs if d != root)
        ]
        infixes = sorted({entry[1] for entry in test_files}) or ["test", "spec"]
        exts = _js_extensions(scan, root, project["language"])
        test_dirs = sorted({_dirname(entry[0]) for entry in test_files}) or [root]
        test_dirs = _apply_test_dir_override(ctx, project["id"], test_dirs)
        if script_name is not None:
            command = _pm_run(project["packageManager"], script_name, _runner_extra_args(runner))
            if runner is None:
                notes.append(
                    "project %s has a test script with an unrecognised runner; "
                    "running it verbatim" % project["id"]
                )
        else:
            command = ["npx", runner, "run"] if runner == "vitest" else ["npx", runner]
            notes.append(
                "project %s has no test script; falling back to the local %s CLI"
                % (project["id"], runner)
            )
        targets.append(_target(project["id"], runner, command, root, test_dirs,
                               _globs_for(infixes, exts)))
    return targets


def _dotnet_unit_targets(ctx, scan: Dict[str, Any], notes: List[str]) -> List[Dict[str, Any]]:
    targets = []
    for project in scan["projects"]:
        if project["kind"] != "dotnet":
            continue
        for dotnet in project["dotnetProjects"]:
            if not dotnet["isTest"]:
                continue
            root = project["root"]
            rel_project = _posix(os.path.relpath(dotnet["path"], root or ".")) if root else dotnet["path"]
            test_dirs = _apply_test_dir_override(ctx, project["id"], [dotnet["dir"]])
            suffixes = sorted({entry[1] for entry in _cs_test_files(scan, dotnet["dir"])}) or ["Tests.cs"]
            targets.append(_target(
                project["id"], "dotnet", ["dotnet", "test", rel_project], root,
                test_dirs, ["**/*%s" % suffix for suffix in suffixes],
            ))
    return targets


def _integration_targets(ctx, scan: Dict[str, Any], notes: List[str]) -> List[Dict[str, Any]]:
    targets = []
    for project in scan["projects"]:
        if project["kind"] != "dotnet":
            continue
        root = project["root"]
        for dotnet in project["dotnetProjects"]:
            if not dotnet["isTest"]:
                continue
            uses_factory = DOTNET_INTEGRATION_PACKAGE in dotnet["refs"]
            if not uses_factory:
                uses_factory = _mentions_web_application_factory(scan, dotnet["dir"])
            if not uses_factory:
                continue
            rel_project = _posix(os.path.relpath(dotnet["path"], root or ".")) if root else dotnet["path"]
            command = ["dotnet", "test", rel_project]
            integration_dir = _find_integration_dir(scan, dotnet["dir"])
            if integration_dir:
                command = command + ["--filter", "FullyQualifiedName~Integration"]
                test_dirs = [integration_dir]
            else:
                test_dirs = [dotnet["dir"]]
                notes.append(
                    "%s serves both the unit and the integration layer "
                    "(it references Microsoft.AspNetCore.Mvc.Testing); the integration run "
                    "repeats those tests" % dotnet["path"]
                )
            targets.append(_target(project["id"], "dotnet", command, root, test_dirs,
                                   ["**/*Tests.cs"]))

    for project in scan["projects"]:
        if project["kind"] != "js":
            continue
        package = project["package"]
        scripts = package["scripts"]
        deps = package["deps"]
        root = project["root"]
        if "test:integration" in scripts:
            runner = _infer_js_runner(scripts["test:integration"], deps)
            command = _pm_run(project["packageManager"], "test:integration",
                              _runner_extra_args(runner))
            test_dirs = _find_js_integration_dirs(scan, root) or [root]
            targets.append(_target(project["id"], runner, command, root, test_dirs,
                                   _globs_for(["test", "spec"],
                                              _js_extensions(scan, root, project["language"]))))
            continue
        integration_dirs = _find_js_integration_dirs(scan, root)
        if not integration_dirs or "test" not in scripts:
            continue
        runner = _infer_js_runner(scripts.get("test", ""), deps)
        if runner in ("playwright", "cypress"):
            continue
        extra = _runner_extra_args(runner) + ["integration"]
        command = _pm_run(project["packageManager"], "test", extra)
        targets.append(_target(project["id"], runner, command, root, integration_dirs,
                               _globs_for(["test", "spec"],
                                          _js_extensions(scan, root, project["language"]))))
    return targets


def _mentions_web_application_factory(scan: Dict[str, Any], root: str) -> bool:
    repo = scan["repo"]
    inspected = 0
    for rel_path in scan["files"]:
        if not _under(rel_path, root) or not rel_path.endswith(".cs"):
            continue
        inspected += 1
        if inspected > 200:
            return False
        if "WebApplicationFactory" in _read_text(repo / rel_path, 256 * 1024):
            return True
    return False


def _find_integration_dir(scan: Dict[str, Any], root: str) -> Optional[str]:
    for rel_path in scan["filesByDir"]:
        if rel_path == "__all__" or not _under(rel_path, root):
            continue
        if rel_path.rsplit("/", 1)[-1].lower() in INTEGRATION_DIR_NAMES:
            return rel_path
    return None


def _find_js_integration_dirs(scan: Dict[str, Any], root: str) -> List[str]:
    found = []
    for rel_path in scan["filesByDir"]:
        if rel_path == "__all__" or not _under(rel_path, root):
            continue
        if rel_path.rsplit("/", 1)[-1].lower() in INTEGRATION_DIR_NAMES:
            found.append(rel_path)
    return sorted(found)


def _e2e_targets(ctx, scan: Dict[str, Any], notes: List[str]) -> List[Dict[str, Any]]:
    targets = []
    for config in sorted(scan["e2eConfigs"], key=lambda c: c["path"]):
        owner = _owning_project(scan, config["dir"])
        project_id = owner["id"] if owner else _id_for_root(config["dir"])
        language = owner["language"] if owner else "typescript"
        test_dir = config["testDir"] or config["dir"]
        infixes = sorted({entry[1] for entry in _js_test_files(scan, test_dir)}) or ["spec", "test"]
        exts = _js_extensions(scan, test_dir, language)
        if config["framework"] == "playwright":
            command = ["npx", "playwright", "test"]
            runner = "playwright"
        else:
            command = ["npx", "cypress", "run"]
            runner = "cypress"
        test_dirs = _apply_test_dir_override(ctx, project_id, [test_dir])
        targets.append(_target(project_id, runner, command, config["dir"], test_dirs,
                               _globs_for(infixes, exts)))
    return targets


def _owning_project(scan: Dict[str, Any], directory: str) -> Optional[Dict[str, Any]]:
    best = None
    for project in scan["projects"]:
        if project["kind"] != "js":
            continue
        if _under(directory, project["root"]):
            if best is None or len(project["root"]) > len(best["root"]):
                best = project
    return best


def _axe_packages_present(scan: Dict[str, Any]) -> Dict[str, List[str]]:
    """Map each axe package found to the project ids that declare it."""
    present = {}  # type: Dict[str, List[str]]
    for project in scan["projects"]:
        if project["kind"] != "js":
            continue
        deps = project["package"]["deps"]
        for package in AXE_PACKAGES:
            if package in deps:
                present.setdefault(package, []).append(project["id"])
    for package in present:
        present[package].sort()
    return present


def _a11y_targets(ctx, scan: Dict[str, Any], unit_targets: List[Dict[str, Any]],
                  e2e_targets: List[Dict[str, Any]], notes: List[str]
                  ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    axe = _axe_packages_present(scan)
    targets = []  # type: List[Dict[str, Any]]

    component_projects = set()
    for package in AXE_COMPONENT_PACKAGES:
        for project_id in axe.get(package, []):
            component_projects.add(project_id)
    page_projects = set()
    for package in AXE_PAGE_PACKAGES:
        for project_id in axe.get(package, []):
            page_projects.add(project_id)

    component_hosts = [t for t in unit_targets if t["runner"] in ("vitest", "jest", "mocha")]
    page_hosts = [t for t in e2e_targets if t["runner"] in ("playwright", "cypress")]

    # A workspace often declares axe in one package.json while the runner lives in
    # another (a root playwright config, for example). Prefer a host in the
    # declaring project, then fall back to any host that can run the scan.
    if component_projects and component_hosts:
        preferred = [t for t in component_hosts if t["project"] in component_projects]
        for target in (preferred or component_hosts):
            targets.append(_target(
                target["project"], target["runner"],
                list(target["command"]) + [A11Y_FILTER], target["cwd"],
                target["testDirs"], ["**/*.%s.*" % A11Y_FILTER],
            ))

    if page_projects and page_hosts:
        preferred = [t for t in page_hosts if t["project"] in page_projects]
        for target in (preferred or page_hosts):
            targets.append(_target(
                target["project"], target["runner"],
                list(target["command"]) + [A11Y_FILTER], target["cwd"],
                target["testDirs"], ["**/*.%s.*" % A11Y_FILTER],
            ))

    if targets:
        notes.append(
            "a11y targets filter test files by the substring '%s'; generated a11y tests "
            "must carry it in their file name (for example foo.%s.test.tsx)"
            % (A11Y_FILTER, A11Y_FILTER)
        )
        return targets, None

    missing = []  # type: List[str]
    unit_runners = {target["runner"] for target in unit_targets}
    if "vitest" in unit_runners:
        missing.append("vitest-axe or jest-axe")
    elif unit_runners:
        missing.append("jest-axe")
    if any(target["runner"] == "playwright" for target in e2e_targets):
        missing.append("@axe-core/playwright")
    if not missing:
        missing.append("jest-axe, @axe-core/playwright")
    reason = "axe tooling not installed (%s)" % ", ".join(missing)
    if axe:
        reason = (
            "axe packages found (%s) but no unit or e2e target can host an a11y scan"
            % ", ".join(sorted(axe))
        )
    return [], reason


# ---------------------------------------------------------------------------
# Conventions and runtimes
# ---------------------------------------------------------------------------

def _naming_style(name: str) -> Optional[str]:
    stem = name.split(".")[0]
    if not stem or not stem[0].isalpha():
        return None
    if "-" in stem:
        return "kebab-case"
    if "_" in stem:
        return "snake_case"
    if stem[0].isupper():
        return "PascalCase"
    if any(char.isupper() for char in stem):
        return "camelCase"
    return "kebab-case"


def _detect_file_naming(scan: Dict[str, Any]) -> str:
    counts = {}  # type: Dict[str, int]
    for project in scan["projects"]:
        if project["kind"] != "js":
            continue
        for rel_path in scan["files"]:
            if not _under(rel_path, project["root"]):
                continue
            base = rel_path.rsplit("/", 1)[-1]
            if not base.endswith((".ts", ".tsx", ".js", ".jsx", ".vue", ".svelte")):
                continue
            if JS_TEST_FILE_RE.match(base):
                continue
            style = _naming_style(base)
            if style:
                counts[style] = counts.get(style, 0) + 1
    if not counts:
        return "kebab-case"
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return "mixed"
    return ranked[0][0]


def _detect_conventions(scan: Dict[str, Any], unit_targets: List[Dict[str, Any]],
                        e2e_targets: List[Dict[str, Any]]) -> Dict[str, Any]:
    suffixes = set()  # type: set
    for project in scan["projects"]:
        root = project["root"]
        if project["kind"] == "js":
            infixes = {entry[1] for entry in _js_test_files(scan, root)}
            exts = _js_extensions(scan, root, project["language"])
            for infix in infixes:
                for ext in exts:
                    suffixes.add(".%s.%s" % (infix, ext))
        else:
            for _, suffix in _cs_test_files(scan, root):
                suffixes.add(suffix)

    assertion_libraries = set()  # type: set
    component_library = None  # type: Optional[str]
    for project in scan["projects"]:
        if project["kind"] == "js":
            deps = project["package"]["deps"]
            for package, label in JS_ASSERTION_PACKAGES:
                if package in deps:
                    assertion_libraries.add(label)
            for library in COMPONENT_TEST_LIBRARIES:
                if library in deps and component_library is None:
                    component_library = library
        else:
            for dotnet in project["dotnetProjects"]:
                for ref in dotnet["refs"]:
                    for package, label in DOTNET_ASSERTION_PACKAGES:
                        if ref == package or ref.startswith(package + "."):
                            assertion_libraries.add(label)

    e2e_framework = None  # type: Optional[str]
    for target in e2e_targets:
        e2e_framework = target["runner"]
        break

    return {
        "testFileSuffixes": sorted(suffixes),
        "fileNaming": _detect_file_naming(scan),
        "assertionLibraries": sorted(assertion_libraries),
        "e2eFramework": e2e_framework,
        "componentTestLibrary": component_library,
    }


def _probe(command: Sequence[str], cwd: Optional[str] = None) -> Tuple[bool, str]:
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=PROBE_TIMEOUT_SECONDS,
            shell=False,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return False, ""
    if completed.returncode != 0:
        return False, ""
    text = (completed.stdout or b"").decode("utf-8", "replace").strip()
    if not text:
        text = (completed.stderr or b"").decode("utf-8", "replace").strip()
    return True, text.splitlines()[0].strip() if text else ""


def _major_version(raw: str) -> Optional[str]:
    match = re.search(r"(\d+)\.", raw or "")
    if match:
        return match.group(1) + ".x"
    match = re.search(r"(\d+)", raw or "")
    return match.group(1) + ".x" if match else None


def _playwright_cli(scan: Dict[str, Any]) -> Optional[str]:
    repo = scan["repo"]
    candidates = []  # type: List[str]
    for project in scan["projects"]:
        if project["kind"] != "js":
            continue
        candidates.append(str(repo / project["root"] / "node_modules" / ".bin" / "playwright"))
    candidates.append(str(repo / "node_modules" / ".bin" / "playwright"))
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which("playwright")
    return found


def _browsers_cache() -> Optional[str]:
    home = pathlib.Path(os.path.expanduser("~"))
    for candidate in (home / "Library" / "Caches" / "ms-playwright", home / ".cache" / "ms-playwright"):
        if candidate.is_dir():
            return str(candidate)
    env_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env_path and os.path.isdir(env_path):
        return env_path
    return None


def _detect_runtimes(scan: Dict[str, Any], needs_browser: bool) -> Dict[str, Any]:
    node_ok, node_raw = _probe(["node", "--version"])
    dotnet_ok, dotnet_raw = _probe(["dotnet", "--version"])

    browser = {"available": False, "detail": "no headless browser detected"}
    if needs_browser:
        cli = _playwright_cli(scan)
        cache = _browsers_cache()
        if cli and cache:
            ok, version = _probe([cli, "--version"])
            detail = "playwright CLI at %s with browsers cache at %s" % (cli, cache)
            if ok and version:
                detail = "%s (%s)" % (detail, version)
            browser = {"available": bool(ok), "detail": detail}
            if not ok:
                browser["detail"] = "playwright CLI at %s did not respond to --version" % cli
        elif cli and not cache:
            browser = {
                "available": False,
                "detail": "playwright CLI found but no browsers cache "
                          "(run: npx playwright install)",
            }
        else:
            browser = {
                "available": False,
                "detail": "playwright CLI not resolvable from the project's node_modules or PATH",
            }
    else:
        browser = {"available": False, "detail": "no browser-based layer detected"}

    return {
        "node": {
            "available": node_ok,
            "version": _major_version(node_raw) if node_ok else None,
            "detail": node_raw or None,
        },
        "dotnet": {
            "available": dotnet_ok,
            "version": _major_version(dotnet_raw) if dotnet_ok else None,
            "detail": dotnet_raw or None,
        },
        "headlessBrowser": browser,
    }


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def _layer_enabled(ctx, layer: str) -> bool:
    layers = ctx.config.get("layers") or {}
    if not isinstance(layers, dict):
        return True
    return layers.get(layer, True) is not False


def _layer_entry(ctx, layer: str, targets: List[Dict[str, Any]],
                 reason: Optional[str]) -> Dict[str, Any]:
    if not _layer_enabled(ctx, layer):
        return {
            "available": False,
            "targets": [],
            "reason": "disabled by configuration (layers.%s = false)" % layer,
        }
    if not targets:
        return {"available": False, "targets": [], "reason": reason or _default_reason(layer)}
    return {"available": True, "targets": targets, "reason": None}


#: Runners that cannot do anything without a headless browser.
BROWSER_RUNNERS = ("playwright", "cypress")


def _drop_browser_targets(
    layers: Dict[str, Any], browser: Dict[str, Any], notes: List[str]
) -> None:
    """Mark browser-dependent work unavailable when no headless browser exists.

    Only the browser-bound targets are dropped: an a11y layer with both a
    component (vitest) host and a page (playwright) host keeps running its
    component scans and reports the page half honestly.
    """
    detail = str(browser.get("detail") or "no headless browser detected")
    for name, entry in layers.items():
        targets = entry.get("targets") or []
        if not targets:
            continue
        remaining = [t for t in targets if t.get("runner") not in BROWSER_RUNNERS]
        if len(remaining) == len(targets):
            continue
        if remaining:
            entry["targets"] = remaining
            notes.append(
                "%s: browser-dependent targets were dropped (%s); the remaining "
                "targets still run" % (name, detail)
            )
            continue
        entry["available"] = False
        entry["targets"] = []
        entry["reason"] = "no headless browser available (%s)" % detail
        notes.append(
            "%s: reported skipped-unavailable because no headless browser is "
            "available (%s)" % (name, detail)
        )


def _default_reason(layer: str) -> str:
    if layer == "unit":
        return "no unit test target detected"
    if layer == "integration":
        return "no integration test target detected"
    if layer == "e2e":
        return "no e2e test target detected (no playwright or cypress config found)"
    return "no a11y test target detected"


def detect_stack(ctx) -> Dict[str, Any]:
    """Detect projects, runnable layers, conventions and runtimes for the repo."""
    scan = _scan(ctx)
    notes = list(scan["notes"])

    unit_targets = []  # type: List[Dict[str, Any]]
    unit_targets.extend(_js_unit_targets(ctx, scan, notes))
    unit_targets.extend(_dotnet_unit_targets(ctx, scan, notes))
    integration_targets = _integration_targets(ctx, scan, notes)
    e2e_targets = _e2e_targets(ctx, scan, notes)
    a11y_targets, a11y_reason = _a11y_targets(ctx, scan, unit_targets, e2e_targets, notes)

    layers = {
        "unit": _layer_entry(ctx, "unit", unit_targets, None),
        "integration": _layer_entry(ctx, "integration", integration_targets, None),
        "e2e": _layer_entry(ctx, "e2e", e2e_targets, None),
        "a11y": _layer_entry(ctx, "a11y", a11y_targets, a11y_reason),
    }

    needs_browser = layers["e2e"]["available"] or bool(
        [t for t in a11y_targets if t["runner"] in ("playwright", "cypress")]
    )
    runtimes = _detect_runtimes(scan, needs_browser)

    if not runtimes["node"]["available"] and any(
        target["runner"] != "dotnet"
        for layer in layers.values() for target in layer["targets"]
    ):
        notes.append("node was not found on PATH; JavaScript layers will report a runtime failure")
    if not runtimes["dotnet"]["available"] and any(
        target["runner"] == "dotnet"
        for layer in layers.values() for target in layer["targets"]
    ):
        notes.append("dotnet was not found on PATH; .NET layers will report a runtime failure")
    if not runtimes["headlessBrowser"]["available"]:
        # PRD business rule: "When a required runtime is unavailable -- no headless
        # browser, no display server -- the affected layer reports
        # skipped-unavailable." Without this gate a browser-less machine RAN the
        # layer and reported a plain failure, which is a silent misattribution:
        # the code is not broken, the runtime is missing.
        _drop_browser_targets(layers, runtimes["headlessBrowser"], notes)

    projects = _public_projects(scan)
    if not projects:
        notes.append("no package.json, solution, or project file found in the repository")

    detected = any(layer["available"] for layer in layers.values())
    return {
        "schemaVersion": common.SCHEMA_VERSION,
        "repo": str(ctx.repo),
        "detected": detected,
        "projects": projects,
        "layers": layers,
        "conventions": _detect_conventions(scan, unit_targets, e2e_targets),
        "runtimes": runtimes,
        "notes": sorted(set(notes)),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Declare only this subcommand's own flags."""
    parser.add_argument(
        "--out",
        metavar="PATH",
        default=None,
        help="also write the detected stack JSON to PATH (for `exec --stack`).",
    )


def run(args: argparse.Namespace, ctx) -> int:
    """Detect the stack, emit it, and return OK or NO_STACK."""
    document = detect_stack(ctx)

    out = getattr(args, "out", None)
    if out:
        path = guard_write_path(ctx, out)
        common.write_json(path, document)
        ctx.note("stack written to %s" % ctx.rel(path))

    ctx.emit(document)

    for layer in common.LAYER_ORDER:
        entry = document["layers"][layer]
        if entry["available"]:
            runners = sorted({target["runner"] for target in entry["targets"]})
            ctx.note("layer %s: available (%s)" % (layer, ", ".join(runners)))
        else:
            ctx.note("layer %s: unavailable — %s" % (layer, entry["reason"]))

    if not document["detected"]:
        ctx.progress("[qa] no test stack detected; adding a test framework is a human decision")
        return common.NO_STACK
    return common.OK
