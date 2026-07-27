"""Scope resolution and test-plan skeleton generation for the QA agent.

``scope`` answers "what changed and what does it belong to"; ``plan`` turns that
answer plus the detected stack into ``plan.json`` / ``plan.md`` skeletons. The
script supplies structure, discovered conventions and target suggestions only —
mapping a requirement to a layer is the agent's judgement and is left as an
explicit TODO row.
"""

import argparse
import os
import pathlib
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

try:
    from . import qa_common as common
except ImportError:  # pragma: no cover - direct script execution
    import qa_common as common

try:
    from . import qa_stack
except ImportError:  # pragma: no cover - direct script execution
    import qa_stack

HELP_SCOPE = "Resolve the file scope for a QA round."
HELP_PLAN = "Write the plan.json and plan.md skeletons for a round."

# ---------------------------------------------------------------------------
# Classification tables
# ---------------------------------------------------------------------------

SOURCE_EXTS = frozenset((
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".vue",
    ".svelte", ".cs", ".fs", ".vb", ".css", ".scss", ".sass", ".less",
    ".html", ".cshtml", ".razor", ".py", ".go", ".rb", ".java", ".kt", ".rs",
    ".php", ".swift", ".sql", ".sh",
))

UI_EXTS = frozenset((
    ".tsx", ".jsx", ".vue", ".svelte", ".css", ".html", ".cshtml", ".razor",
    ".scss", ".sass", ".less",
))

DOC_EXTS = frozenset((".md", ".mdx", ".txt", ".rst", ".adoc"))

ASSET_EXTS = frozenset((
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif", ".ico", ".bmp",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3", ".mp4", ".webm", ".wav",
    ".pdf", ".zip",
))

CONFIG_EXTS = frozenset((
    ".sln", ".csproj", ".fsproj", ".vbproj", ".props", ".targets", ".yml",
    ".yaml", ".toml", ".ini", ".cfg", ".lock", ".env",
))

CONFIG_BASENAMES = frozenset((
    "package.json", "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml",
    "yarn.lock", "bun.lockb", "bun.lock", "components.json", "nuget.config",
    "global.json", "dockerfile", "makefile", "procfile", "license", "notice",
))

CONFIG_BASENAME_RE = re.compile(r"^[^/]*\.config\.[cm]?[jt]s$")
TS_CONFIG_RE = re.compile(r"^tsconfig(\..+)?\.json$")

TEST_DIR_NAMES = frozenset((
    "__tests__", "__test__", "__integration__", "tests", "test", "e2e",
    "spec", "specs", "cypress", "integration-tests", "integrationtests",
))

JS_TEST_FILE_RE = re.compile(r"^(?P<stem>.+)\.(test|spec)\.[cm]?[jt]sx?$")
CS_TEST_FILE_RE = re.compile(r"^.+?(Tests?|Specs?)\.cs$")

# ---------------------------------------------------------------------------
# Requirement discovery
# ---------------------------------------------------------------------------

REQUIREMENT_DOC_PATTERNS = (
    "tasks/prd-*/prd.md",
    "tasks/prd-*/techspec.md",
    "tasks/prd-*/tasks.md",
    "tasks/prd-*/_user_stories.md",
    "tasks/prd-*/adrs/*.md",
    "docs/prd*.md",
    "docs/adrs/*.md",
    "adrs/*.md",
    "*_user_stories.md",
    "prd*.md",
    "*_prd.md",
)

REQUIREMENT_DOC_EXCLUDE_PREFIXES = (".github/ISSUE_TEMPLATE",)

REQ_REF_RE = re.compile(r"\b((?:FR|NFR|US|AC|BR|TR|REQ|CR|ADR)-\d{1,4})\b")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
BULLET_RE = re.compile(r"^\s{0,6}[-*+]\s+(.*)$")
CRITERIA_HEADING_RE = re.compile(r"requirement|acceptance|criteri|user stor|goal", re.IGNORECASE)
PATH_TOKEN_RE = re.compile(r"[A-Za-z0-9_./\\@-]+\.[A-Za-z0-9]{1,6}")

MAX_REQUIREMENTS = 200
MAX_FILE_CHECKS = 50

STOPWORDS = frozenset((
    "the", "a", "an", "and", "or", "of", "to", "for", "with", "when", "then",
    "that", "this", "from", "into", "is", "are", "be", "must", "should",
    "shall", "not", "no", "it", "its", "as", "by", "on", "in", "at", "all",
    "any", "each", "every", "which", "while", "also", "only", "user", "users",
    "system", "shows", "show", "given", "have", "has", "does", "done", "make",
))


# ---------------------------------------------------------------------------
# Small path helpers
# ---------------------------------------------------------------------------

def _posix(path: str) -> str:
    return path.replace(os.sep, "/")


def _under(path: str, root: str) -> bool:
    if root in ("", "."):
        return True
    return path == root or path.startswith(root + "/")


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _dirname(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _read_text(path: pathlib.Path, limit: int = 2 * 1024 * 1024) -> str:
    try:
        with open(str(path), "r", encoding="utf-8", errors="replace") as handle:
            return handle.read(limit)
    except (OSError, ValueError):
        return ""


# ---------------------------------------------------------------------------
# File classification
# ---------------------------------------------------------------------------

def _is_config(path: str) -> bool:
    base = _basename(path).lower()
    if base in CONFIG_BASENAMES or base.startswith("."):
        return True
    if TS_CONFIG_RE.match(base) or CONFIG_BASENAME_RE.match(base):
        return True
    return os.path.splitext(base)[1] in CONFIG_EXTS


def _in_test_dir(path: str) -> bool:
    parts = path.split("/")[:-1]
    return any(part.lower() in TEST_DIR_NAMES for part in parts)


def classify_file(path: str, projects: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Classify one repo-relative path into the contract's file record shape."""
    base = _basename(path)
    ext = os.path.splitext(base)[1].lower()
    if JS_TEST_FILE_RE.match(base) or CS_TEST_FILE_RE.match(base):
        kind = "test"
    elif _is_config(path):
        kind = "config"
    elif ext in DOC_EXTS:
        kind = "doc"
    elif ext in ASSET_EXTS:
        kind = "asset"
    elif _in_test_dir(path) and ext in SOURCE_EXTS:
        kind = "test"
    elif ext in SOURCE_EXTS:
        kind = "source"
    else:
        kind = "other"
    return {
        "kind": kind,
        "project": _project_for(path, projects),
        "touchesUi": ext in UI_EXTS,
        "isTest": kind == "test",
    }


def _project_for(path: str, projects: Sequence[Dict[str, Any]]) -> Optional[str]:
    best = None  # type: Optional[Dict[str, Any]]
    for project in projects:
        if not _under(path, project["root"]):
            continue
        if best is None or len(project["root"]) > len(best["root"]):
            best = project
    return best["id"] if best else None


# ---------------------------------------------------------------------------
# Git plumbing
# ---------------------------------------------------------------------------

def _git_ok(repo, *args) -> Tuple[bool, str]:
    code, out, _err = common.run_git(repo, *args)
    return code == 0, (out or "").strip()


def _is_git_repo(repo) -> bool:
    ok, out = _git_ok(repo, "rev-parse", "--is-inside-work-tree")
    return ok and out == "true"


def _parse_name_status(output: str) -> List[Tuple[str, str]]:
    entries = []
    for line in (output or "").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0].strip()[:1].upper() or "M"
        entries.append((status, _posix(parts[-1].strip())))
    return entries


def _untracked(repo) -> List[Tuple[str, str]]:
    ok, out = _git_ok(repo, "ls-files", "--others", "--exclude-standard")
    if not ok or not out:
        return []
    return [("A", _posix(line.strip())) for line in out.splitlines() if line.strip()]


def _resolve_base(repo, requested: Optional[str], configured: Optional[str],
                  notes: List[str]) -> Optional[str]:
    candidates = []  # type: List[str]
    if requested:
        candidates.append(requested)
    else:
        if configured:
            candidates.append(configured)
        discovered = common.default_base_branch(repo)
        if discovered:
            candidates.append(discovered)
    for candidate in candidates:
        ok, _out = _git_ok(repo, "rev-parse", "--verify", "--quiet", candidate + "^{commit}")
        if ok:
            return candidate
    if requested:
        raise common.QaError("base branch %r does not resolve to a commit" % requested,
                             common.USAGE)
    return None


def _diff_entries(repo, requested_base: Optional[str], configured_base: Optional[str],
                  notes: List[str]) -> Tuple[List[Tuple[str, str]], Optional[str], Optional[str]]:
    """Working-tree-plus-committed diff. Returns (entries, base, refRange)."""
    if not _is_git_repo(repo):
        notes.append("not a git repository; the diff source contributes no files")
        return [], None, None

    has_head, _out = _git_ok(repo, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    if not has_head:
        notes.append("repository has no commits; the diff source falls back to untracked files")
        return _untracked(repo), None, None

    ok, branch = _git_ok(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if ok and branch == "HEAD":
        notes.append("HEAD is detached; the diff is computed from the current commit")

    base = _resolve_base(repo, requested_base, configured_base, notes)
    entries = []  # type: List[Tuple[str, str]]
    ref_range = None  # type: Optional[str]

    if base:
        merged, merge_base = _git_ok(repo, "merge-base", base, "HEAD")
        if merged and merge_base:
            ok, out = _git_ok(repo, "diff", "--name-status", merge_base)
            if ok:
                entries = _parse_name_status(out)
                ref_range = "%s...HEAD" % base
            else:
                notes.append("git diff against %s failed; comparing the working tree to HEAD"
                             % base)
        else:
            notes.append("no merge base between %s and HEAD; comparing the working tree to HEAD"
                         % base)
            base = None
    else:
        notes.append(
            "no default branch resolved (origin/HEAD, main, master); "
            "comparing the working tree to HEAD"
        )

    if ref_range is None:
        ok, out = _git_ok(repo, "diff", "--name-status", "HEAD")
        entries = _parse_name_status(out) if ok else []

    seen = {path for _status, path in entries}
    for status, path in _untracked(repo):
        if path not in seen:
            entries.append((status, path))
    entries.sort(key=lambda item: item[1])
    return entries, base, ref_range


def _ref_range_entries(repo, ref_range: str) -> List[Tuple[str, str]]:
    ok, out = _git_ok(repo, "diff", "--name-status", ref_range)
    if not ok:
        raise common.QaError("git could not resolve the ref range %r" % ref_range, common.USAGE)
    return _parse_name_status(out)


# ---------------------------------------------------------------------------
# Requirement documents
# ---------------------------------------------------------------------------

def discover_requirement_docs(ctx, in_scope: Sequence[str]) -> Tuple[List[str], List[str]]:
    """Auto-discover requirement artifacts. Returns (docs, notes)."""
    repo = pathlib.Path(ctx.repo)
    notes = []  # type: List[str]
    found = set()  # type: Set[str]
    for pattern in REQUIREMENT_DOC_PATTERNS:
        for match in repo.glob(pattern):
            if not match.is_file():
                continue
            rel = _posix(os.path.relpath(str(match), str(repo)))
            if any(rel.startswith(prefix) for prefix in REQUIREMENT_DOC_EXCLUDE_PREFIXES):
                continue
            found.add(rel)

    feature_dirs = sorted({
        _dirname(path) for path in in_scope
        if path.startswith("tasks/") and path.count("/") >= 2
    })
    feature_roots = sorted({"/".join(d.split("/")[:2]) for d in feature_dirs})
    if feature_roots:
        narrowed = sorted(doc for doc in found
                          if any(_under(doc, root) for root in feature_roots))
        if narrowed:
            notes.append(
                "requirement docs narrowed to the in-scope feature directories: %s"
                % ", ".join(feature_roots)
            )
            return narrowed, notes
    return sorted(found), notes


def _clean_requirement_text(line: str, ref: Optional[str]) -> str:
    text = line.strip()
    text = BULLET_RE.sub(r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text)
    if ref:
        text = text.replace(ref, "", 1)
    text = text.replace("**", "").replace("`", "").replace("__", "")
    text = re.sub(r"^[\s:|>\[\]\-\u2013\u2014]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:300]


def extract_requirements(ctx, docs: Sequence[str]) -> Tuple[List[Dict[str, str]], List[str]]:
    """Pull requirement rows out of the requirement documents, in reading order."""
    repo = pathlib.Path(ctx.repo)
    notes = []  # type: List[str]
    requirements = []  # type: List[Dict[str, str]]
    seen = set()  # type: Set[str]

    for doc in docs:
        text = _read_text(repo / doc)
        if not text.strip():
            notes.append("requirement document %s is empty or unreadable" % doc)
            continue
        lines = text.splitlines()
        doc_refs = 0
        for index, line in enumerate(lines, start=1):
            for ref in REQ_REF_RE.findall(line):
                if ref in seen:
                    continue
                seen.add(ref)
                doc_refs += 1
                requirements.append({
                    "ref": ref,
                    "text": _clean_requirement_text(line, ref),
                    "source": "%s#L%d" % (doc, index),
                })
        if doc_refs == 0:
            requirements.extend(_synthesize_requirements(doc, lines, seen))
    if len(requirements) > MAX_REQUIREMENTS:
        notes.append("requirement list truncated to the first %d entries" % MAX_REQUIREMENTS)
        requirements = requirements[:MAX_REQUIREMENTS]
    return requirements, notes


def _synthesize_requirements(doc: str, lines: Sequence[str],
                             seen: Set[str]) -> List[Dict[str, str]]:
    """When a doc carries no explicit refs, mine bullets under criteria headings."""
    synthesized = []  # type: List[Dict[str, str]]
    in_section = False
    counter = len([r for r in seen if r.startswith("REQ-")])
    for index, line in enumerate(lines, start=1):
        heading = HEADING_RE.match(line)
        if heading:
            in_section = bool(CRITERIA_HEADING_RE.search(heading.group(1)))
            continue
        if not in_section:
            continue
        bullet = BULLET_RE.match(line)
        if not bullet:
            continue
        text = _clean_requirement_text(line, None)
        if len(text) < 8:
            continue
        counter += 1
        ref = "REQ-%03d" % counter
        if ref in seen:
            continue
        seen.add(ref)
        synthesized.append({"ref": ref, "text": text, "source": "%s#L%d" % (doc, index)})
    return synthesized


def _requirement_referenced_files(ctx, docs: Sequence[str],
                                  file_set: Set[str]) -> Tuple[Set[str], List[str]]:
    repo = pathlib.Path(ctx.repo)
    notes = []  # type: List[str]
    referenced = set()  # type: Set[str]
    for doc in docs:
        text = _read_text(repo / doc)
        for token in PATH_TOKEN_RE.findall(text):
            candidate = _posix(token).lstrip("./")
            if candidate in file_set:
                referenced.add(candidate)
    if not referenced:
        notes.append(
            "the requirement documents reference no repository file paths; "
            "the requirements source does not narrow the scope"
        )
    return referenced, notes


# ---------------------------------------------------------------------------
# Scope resolution
# ---------------------------------------------------------------------------

def resolve_scope(ctx, paths=None, ref_range=None, requirements=None, diff=False,
                  base=None, packages=None) -> Dict[str, Any]:
    """Resolve the scope document. Intersection wins when several sources are given."""
    repo = pathlib.Path(ctx.repo)
    notes = []  # type: List[str]
    projects = qa_stack.detect_projects(ctx)
    repo_files = qa_stack.list_repo_files(repo)
    file_set = set(repo_files)

    scope_config = ctx.config.get("scope") or {}
    configured_base = scope_config.get("defaultBase")
    configured_packages = scope_config.get("packages") or []
    packages = list(packages or []) or list(configured_packages)

    diff_entries, resolved_base, resolved_range = _diff_entries(
        repo, base, configured_base, notes
    )
    status_map = {}  # type: Dict[str, str]
    for status, path in diff_entries:
        status_map.setdefault(path, status)

    sources = []  # type: List[str]
    candidate_sets = []  # type: List[Set[str]]
    dropped = []  # type: List[str]

    if paths:
        sources.append("path")
        candidate_sets.append(_paths_candidates(ctx, paths, repo_files))

    if ref_range:
        sources.append("ref-range")
        entries = _ref_range_entries(repo, ref_range)
        for status, path in entries:
            status_map.setdefault(path, status)
        candidate_sets.append({path for _status, path in entries})
        resolved_range = ref_range

    explicit_requirements = [str(item) for item in (requirements or [])]
    requirement_docs = []  # type: List[str]
    if explicit_requirements:
        sources.append("requirements")
        requirement_docs = _normalize_requirement_docs(ctx, explicit_requirements)
        referenced, req_notes = _requirement_referenced_files(ctx, requirement_docs, file_set)
        notes.extend(req_notes)
        if referenced:
            candidate_sets.append(referenced)
        else:
            dropped.append("requirements")

    if packages:
        sources.append("package")
        candidate_sets.append(_package_candidates(packages, projects, repo_files))

    use_diff = bool(diff or base) or not sources
    if not use_diff and dropped and not candidate_sets:
        notes.append(
            "the %s source contributed no files; falling back to the diff against the "
            "default branch" % ", ".join(sorted(dropped))
        )
        use_diff = True
    if use_diff:
        sources.append("diff")
        candidate_sets.append({path for _status, path in diff_entries})

    selected = None  # type: Optional[Set[str]]
    for candidate in candidate_sets:
        selected = set(candidate) if selected is None else (selected & candidate)
    if selected is None:
        selected = set()
    if len(candidate_sets) > 1:
        notes.append("%d scope sources were given; their intersection is the scope"
                     % len(candidate_sets))

    qa_rel = common.repo_rel(repo, ctx.qa_dir)
    if not qa_rel.startswith(".."):
        own_output = {path for path in selected if _under(path, qa_rel)}
        if own_output:
            selected -= own_output
            notes.append("%d file(s) under the QA output directory %s were excluded from scope"
                         % (len(own_output), qa_rel))

    files = []  # type: List[Dict[str, Any]]
    for path in sorted(selected):
        record = classify_file(path, projects)
        entry = {"path": path, "status": status_map.get(path, "?")}
        entry.update({
            "kind": record["kind"],
            "project": record["project"],
            "touchesUi": record["touchesUi"],
            "isTest": record["isTest"],
        })
        files.append(entry)

    in_scope_paths = [entry["path"] for entry in files]
    if not explicit_requirements:
        requirement_docs, doc_notes = discover_requirement_docs(ctx, in_scope_paths)
        notes.extend(doc_notes)
        if not requirement_docs:
            notes.append(
                "no requirement artifact found; the plan will be inference-based"
            )

    package_ids = sorted({
        project["id"] for project in projects
        if any(_under(path, project["root"]) for path in in_scope_paths)
    })

    if any(entry["status"] == "D" for entry in files):
        notes.append("deleted files are listed for traceability but carry no test target")
    if any(entry["touchesUi"] for entry in files):
        notes.append("the scope touches UI; the a11y layer is required for this round")

    return {
        "schemaVersion": common.SCHEMA_VERSION,
        "sources": sorted(set(sources)),
        "base": resolved_base,
        "refRange": resolved_range,
        "empty": not files,
        "files": files,
        "packages": package_ids,
        "requirementDocs": sorted(set(requirement_docs)),
        "notes": sorted(set(notes)),
    }


def _paths_candidates(ctx, paths: Sequence[str], repo_files: Sequence[str]) -> Set[str]:
    repo = pathlib.Path(ctx.repo)
    selected = set()  # type: Set[str]
    for raw in paths:
        target = qa_stack.resolve_input_path(ctx, raw)
        try:
            relative = _posix(os.path.relpath(str(target), str(repo)))
        except ValueError:
            raise common.QaError("path %r is outside the repository" % raw, common.USAGE)
        if relative.startswith(".."):
            raise common.QaError("path %r is outside the repository" % raw, common.USAGE)
        relative = relative.lstrip("./") or ""
        matched = [path for path in repo_files if path == relative or _under(path, relative)]
        if not matched:
            raise common.QaError("path %r matches no file in the repository" % raw, common.USAGE)
        selected.update(matched)
    return selected


def _package_candidates(packages: Sequence[str], projects: Sequence[Dict[str, Any]],
                        repo_files: Sequence[str]) -> Set[str]:
    known = {project["id"]: project["root"] for project in projects}
    roots = []  # type: List[str]
    for name in packages:
        cleaned = str(name).strip().strip("/")
        if cleaned in known:
            roots.append(known[cleaned])
            continue
        matches = [root for root in known.values() if root == cleaned]
        if matches:
            roots.extend(matches)
            continue
        raise common.QaError(
            "unknown package %r; detected packages: %s"
            % (name, ", ".join(sorted(known)) or "none"),
            common.USAGE,
        )
    return {path for path in repo_files if any(_under(path, root) for root in roots)}


def _normalize_requirement_docs(ctx, values: Sequence[str]) -> List[str]:
    repo = pathlib.Path(ctx.repo)
    docs = []  # type: List[str]
    for value in values:
        target = qa_stack.resolve_input_path(ctx, value)
        if not target.is_file():
            raise common.QaError("requirements document not found: %s" % value, common.USAGE)
        relative = _posix(os.path.relpath(str(target), str(repo)))
        docs.append(relative if not relative.startswith("..") else str(target))
    return docs


# ---------------------------------------------------------------------------
# Plan construction
# ---------------------------------------------------------------------------

LAYER_REASONS = {
    "unit": "logic is observable from a rendered component or a pure function",
    "integration": "crosses a process boundary; needs the application host",
    "e2e": "behaviour is only observable in a running page",
    "a11y": "renders UI; a WCAG 2.2 AA scan is required for any UI change",
}


def _tokens(text: str) -> Set[str]:
    return {
        token for token in re.split(r"[^a-z0-9]+", (text or "").lower())
        if len(token) >= 4 and token not in STOPWORDS
    }


def _path_tokens(path: str) -> Set[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", path)
    return {
        token for token in re.split(r"[^a-zA-Z0-9]+", spaced.lower())
        if len(token) >= 4 and token not in STOPWORDS
    }


def _available_layers(stack: Dict[str, Any]) -> List[str]:
    layers = stack.get("layers") or {}
    return [name for name in common.LAYER_ORDER
            if (layers.get(name) or {}).get("available")]


def _fallback_layer(available: Sequence[str]) -> str:
    """A plan row always names a layer; ``unit`` is the honest default."""
    return available[0] if available else "unit"


def _project_of(path: Optional[str], files: Sequence[Dict[str, Any]]) -> Optional[str]:
    for entry in files:
        if entry["path"] == path:
            return entry.get("project")
    return None


def _suggest_layer(path: str, touches_ui: bool, available: Sequence[str]) -> str:
    lower = path.lower()
    preference = []  # type: List[str]
    if lower.endswith((".cs", ".fs", ".vb")):
        if any(marker in lower for marker in ("controller", "endpoint", "/api/", "program.")):
            preference = ["integration", "unit"]
        else:
            preference = ["unit", "integration"]
    elif touches_ui:
        if any(marker in lower for marker in ("/pages/", "/routes/", "/views/", "/app/")):
            preference = ["e2e", "unit"]
        else:
            preference = ["unit", "e2e"]
    else:
        preference = ["unit", "integration", "e2e"]
    for layer in preference:
        if layer in available:
            return layer
    return _fallback_layer(available)


def _unit_test_dirs(stack: Dict[str, Any], project: Optional[str]) -> List[str]:
    dirs = []  # type: List[str]
    layers = stack.get("layers") or {}
    for layer_name in ("unit", "integration"):
        entry = layers.get(layer_name) or {}
        for target in entry.get("targets") or []:
            if project is None or target.get("project") == project:
                dirs.extend(target.get("testDirs") or [])
    return sorted(set(dirs))


def _suggest_test_file(path: str, project: Optional[str], stack: Dict[str, Any]) -> Optional[str]:
    base = _basename(path)
    stem, ext = os.path.splitext(base)
    test_dirs = _unit_test_dirs(stack, project)
    if ext == ".cs":
        dotnet_dirs = [d for d in test_dirs if "test" in d.lower()]
        target_dir = dotnet_dirs[0] if dotnet_dirs else _dirname(path)
        parts = path.split("/")
        sub = ""
        if "src" in parts:
            index = parts.index("src")
            sub = "/".join(parts[index + 2:-1])
        candidate = "/".join(part for part in (target_dir, sub, stem + "Tests.cs") if part)
        return candidate
    if ext in (".ts", ".tsx", ".js", ".jsx", ".vue", ".svelte"):
        suffix_ext = ext.lstrip(".")
        if suffix_ext in ("vue", "svelte"):
            suffix_ext = "ts"
        js_dirs = [d for d in test_dirs if "__tests__" in d or d.endswith("/tests")
                   or d.endswith("/test")]
        target_dir = js_dirs[0] if js_dirs else _dirname(path)
        return "/".join(part for part in (target_dir, "%s.test.%s" % (stem, suffix_ext)) if part)
    return None


def _candidate_targets(requirement_text: str, source_files: Sequence[Dict[str, Any]],
                       limit: int = 3) -> List[str]:
    wanted = _tokens(requirement_text)
    if not wanted:
        return []
    scored = []  # type: List[Tuple[int, str]]
    for entry in source_files:
        overlap = len(wanted & _path_tokens(entry["path"]))
        if overlap:
            scored.append((overlap, entry["path"]))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [path for _score, path in scored[:limit]]


def build_plan(ctx, scope: Dict[str, Any], stack: Dict[str, Any],
               requirement_docs: Optional[Sequence[str]] = None,
               round_no: int = 0) -> Dict[str, Any]:
    """Build the plan skeleton. Layer judgement rows are left as explicit TODOs."""
    docs = list(requirement_docs if requirement_docs is not None
                else scope.get("requirementDocs") or [])
    requirements, notes = extract_requirements(ctx, docs)
    inference_based = not docs or not requirements
    if docs and not requirements:
        notes.append(
            "requirement documents were found but carried no extractable criteria; "
            "the plan falls back to inference"
        )

    available = _available_layers(stack)
    files = scope.get("files") or []
    source_files = [entry for entry in files
                    if entry["kind"] == "source" and entry["status"] != "D"]
    ui_files = [entry for entry in source_files if entry["touchesUi"]]
    truncated = False
    if len(source_files) > MAX_FILE_CHECKS:
        source_files = source_files[:MAX_FILE_CHECKS]
        truncated = True

    checks = []  # type: List[Dict[str, Any]]
    counter = 0

    for requirement in requirements:
        counter += 1
        candidates = _candidate_targets(requirement["text"], source_files)
        target = candidates[0] if candidates else None
        touches_ui = any(entry["path"] == target and entry["touchesUi"]
                         for entry in source_files)
        layer = _suggest_layer(target, touches_ui, available) if target \
            else _fallback_layer(available)
        checks.append({
            "id": "CHK-%03d" % counter,
            "requirementRef": requirement["ref"],
            "layer": layer,
            "target": target,
            "reason": "TODO — confirm this mapping; suggested because %s"
                      % LAYER_REASONS.get(layer, "it is the only available layer"),
            "status": "planned",
            "manualReason": None,
            "testFile": _suggest_test_file(target, _project_of(target, source_files),
                                           stack) if target else None,
            "todo": True,
            "candidateLayers": list(available),
            "candidateTargets": candidates,
        })

    for entry in source_files:
        layer = _suggest_layer(entry["path"], entry["touchesUi"], available)
        if layer is None:
            continue
        test_file = _suggest_test_file(entry["path"], entry.get("project"), stack)
        counter += 1
        checks.append({
            "id": "CHK-%03d" % counter,
            "requirementRef": None,
            "layer": layer,
            "target": entry["path"],
            "reason": LAYER_REASONS.get(layer),
            "status": "existing" if _test_file_exists(ctx, test_file) else "planned",
            "manualReason": None,
            "testFile": test_file,
            "todo": False,
            "candidateLayers": list(available),
            "candidateTargets": [entry["path"]],
        })

    a11y_reason = ((stack.get("layers") or {}).get("a11y") or {}).get("reason")
    if ui_files:
        if "a11y" in available:
            for entry in ui_files[:MAX_FILE_CHECKS]:
                counter += 1
                checks.append({
                    "id": "CHK-%03d" % counter,
                    "requirementRef": None,
                    "layer": "a11y",
                    "target": entry["path"],
                    "reason": LAYER_REASONS["a11y"],
                    "status": "planned",
                    "manualReason": None,
                    "testFile": _a11y_test_file(entry["path"], entry.get("project"), stack),
                    "todo": False,
                    "candidateLayers": ["a11y"],
                    "candidateTargets": [entry["path"]],
                })
        else:
            counter += 1
            checks.append({
                "id": "CHK-%03d" % counter,
                "requirementRef": None,
                "layer": "a11y",
                "target": "; ".join(entry["path"] for entry in ui_files[:5]),
                "reason": LAYER_REASONS["a11y"],
                "status": "manual",
                "manualReason": a11y_reason or "the a11y layer is unavailable",
                "testFile": None,
                "todo": False,
                "candidateLayers": [],
                "candidateTargets": [entry["path"] for entry in ui_files[:5]],
            })

    if truncated:
        notes.append(
            "the scope holds more than %d source files; per-file checks were truncated"
            % MAX_FILE_CHECKS
        )
    if not checks:
        notes.append("no requirement and no testable source file in scope; nothing to plan")

    return {
        "schemaVersion": common.SCHEMA_VERSION,
        "round": round_no,
        "inferenceBased": inference_based,
        "requirementDocs": sorted(set(docs)),
        "requirements": requirements,
        "checks": checks,
        "availableLayers": available,
        "notes": sorted(set(notes)),
    }


def _test_file_exists(ctx, test_file: Optional[str]) -> bool:
    """A suggested test file that is already on disk is `existing`, never regenerated."""
    if not test_file:
        return False
    return (pathlib.Path(ctx.repo) / test_file).is_file()


def _a11y_test_file(path: str, project: Optional[str], stack: Dict[str, Any]) -> Optional[str]:
    base = _basename(path)
    stem, ext = os.path.splitext(base)
    dirs = _unit_test_dirs(stack, project)
    target_dir = dirs[0] if dirs else _dirname(path)
    suffix = "tsx" if ext in (".tsx", ".jsx") else "ts"
    return "/".join(part for part in (target_dir, "%s.a11y.test.%s" % (stem, suffix)) if part)


# ---------------------------------------------------------------------------
# plan.md rendering
# ---------------------------------------------------------------------------

def _cell(value: Optional[str]) -> str:
    if value is None or value == "":
        return "TODO"
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_plan_markdown(plan: Dict[str, Any], scope: Dict[str, Any],
                         stack: Dict[str, Any]) -> str:
    """Render plan.md: readable prose plus one row per planned check."""
    lines = []  # type: List[str]
    if plan["inferenceBased"]:
        lines.append(
            "> INFERENCE-BASED PLAN — no requirement artifact was found, so expected "
            "behaviour is inferred from the diff and the public interfaces it touches."
        )
        lines.append("")
    lines.append("# QA Plan — Round %03d" % int(plan.get("round") or 0))
    lines.append("")
    lines.append("- Generated: %s" % common.utc_now_iso())
    lines.append("- Scope: %d file(s) across %s"
                 % (len(scope.get("files") or []),
                    ", ".join(scope.get("packages") or []) or "no detected package"))
    lines.append("- Ref range: %s" % (scope.get("refRange") or "working tree"))
    docs = plan.get("requirementDocs") or []
    lines.append("- Requirement documents: %s"
                 % (", ".join("`%s`" % doc for doc in docs) or "none found"))
    lines.append("- Available layers: %s"
                 % (", ".join(plan.get("availableLayers") or []) or "none"))
    for layer in common.LAYER_ORDER:
        entry = (stack.get("layers") or {}).get(layer) or {}
        if not entry.get("available"):
            lines.append("- Layer `%s` unavailable: %s"
                         % (layer, entry.get("reason") or "unknown"))
    lines.append("")

    lines.append("## Checks")
    lines.append("")
    lines.append("Each row maps one criterion to one layer. Rows marked `TODO` need the")
    lines.append("agent's judgement: pick the layer, name the target, and state the reason.")
    lines.append("")
    lines.append("| ID | Requirement | Layer | Target | Reason | Status |")
    lines.append("|---|---|---|---|---|---|")
    manual = []  # type: List[Dict[str, Any]]
    for check in plan.get("checks") or []:
        if check.get("status") == "manual":
            manual.append(check)
        target = check.get("target")
        if not target and check.get("candidateTargets"):
            target = "candidates: " + ", ".join(check["candidateTargets"])
        layer = check.get("layer")
        if check.get("todo"):
            layer = "%s (TODO)" % layer
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            check["id"],
            _cell(check.get("requirementRef")),
            _cell(layer),
            _cell(target),
            _cell(check.get("reason")),
            _cell(check.get("status")),
        ))
    if not (plan.get("checks") or []):
        lines.append("| — | — | — | — | nothing testable in scope | — |")
    lines.append("")

    lines.append("## Requirements")
    lines.append("")
    if plan.get("requirements"):
        for requirement in plan["requirements"]:
            lines.append("- `%s` — %s _(%s)_"
                         % (requirement["ref"], requirement["text"] or "(no text)",
                            requirement["source"]))
    else:
        lines.append("No stated requirement was found. Expected behaviour is inferred from the")
        lines.append("diff and the public interfaces it touches; every verdict below inherits")
        lines.append("that uncertainty.")
    lines.append("")

    lines.append("## Manual items")
    lines.append("")
    if manual:
        for check in manual:
            lines.append("- `%s` — %s — %s"
                         % (check["id"], check.get("target") or "(no target)",
                            check.get("manualReason") or "requires human judgement"))
    else:
        lines.append("None recorded yet. Mark any criterion that cannot be automated as")
        lines.append("`manual` with a stated reason — it must surface as an open item, never")
        lines.append("as a silent pass.")
    lines.append("")

    lines.append("## Scope")
    lines.append("")
    lines.append("| File | Status | Kind | Project | UI |")
    lines.append("|---|---|---|---|---|")
    for entry in scope.get("files") or []:
        lines.append("| `%s` | %s | %s | %s | %s |" % (
            entry["path"], entry.get("status") or "?", entry.get("kind"),
            entry.get("project") or "—", "yes" if entry.get("touchesUi") else "no",
        ))
    if not (scope.get("files") or []):
        lines.append("| — | — | — | — | — |")
    lines.append("")

    lines.append("## How to complete this plan")
    lines.append("")
    lines.append("1. Replace every `TODO` layer with `unit`, `integration`, `e2e` or `a11y`,")
    lines.append("   and state why that layer is the cheapest one that can observe the behaviour.")
    lines.append("2. Name a concrete target file or route for every check.")
    lines.append("3. Set `status` to `planned`, `generated`, `existing` or `manual`.")
    lines.append("4. Keep `plan.json` and this file in step — `plan.json` is the machine copy.")
    if plan.get("notes"):
        lines.append("")
        lines.append("## Notes")
        lines.append("")
        for note in plan["notes"]:
            lines.append("- %s" % note)
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI — scope
# ---------------------------------------------------------------------------

def add_scope_arguments(parser: argparse.ArgumentParser) -> None:
    """Declare only this subcommand's own flags."""
    parser.add_argument("--path", action="append", dest="paths", metavar="P", default=None,
                        help="restrict the scope to this file or directory (repeatable).")
    parser.add_argument("--ref-range", dest="ref_range", metavar="A...B", default=None,
                        help="restrict the scope to the files changed in this git range.")
    parser.add_argument("--requirements", action="append", dest="requirements", metavar="F",
                        default=None,
                        help="requirement document to read (repeatable). Disables auto-discovery.")
    parser.add_argument("--diff", action="store_true", default=False,
                        help="use the diff against the default branch as a scope source.")
    parser.add_argument("--base", metavar="BRANCH", default=None,
                        help="base branch for the diff source.")
    parser.add_argument("--package", action="append", dest="packages", metavar="NAME",
                        default=None,
                        help="restrict the scope to this detected package (repeatable).")
    parser.add_argument("--out", metavar="PATH", default=None,
                        help="also write the scope JSON to PATH (for `plan --scope`).")


def run_scope(args: argparse.Namespace, ctx) -> int:
    """Resolve the scope, emit it, and return OK or EMPTY_SCOPE."""
    document = resolve_scope(
        ctx,
        paths=getattr(args, "paths", None),
        ref_range=getattr(args, "ref_range", None),
        requirements=getattr(args, "requirements", None),
        diff=getattr(args, "diff", False),
        base=getattr(args, "base", None),
        packages=getattr(args, "packages", None),
    )

    out = getattr(args, "out", None)
    if out:
        path = qa_stack.guard_write_path(ctx, out)
        common.write_json(path, document)
        ctx.note("scope written to %s" % ctx.rel(path))

    ctx.emit(document)

    ctx.note("sources: %s" % (", ".join(document["sources"]) or "none"))
    ctx.note("files in scope: %d" % len(document["files"]))
    ctx.note("packages: %s" % (", ".join(document["packages"]) or "none"))
    if document["empty"]:
        ctx.progress("[qa] scope resolved to no files; nothing to verify")
        return common.EMPTY_SCOPE
    return common.OK


# ---------------------------------------------------------------------------
# CLI — plan
# ---------------------------------------------------------------------------

def add_plan_arguments(parser: argparse.ArgumentParser) -> None:
    """Declare only this subcommand's own flags."""
    parser.add_argument("--round", dest="round_no", type=int, required=True, metavar="N",
                        help="round number to write plan.json and plan.md into.")
    parser.add_argument("--scope", metavar="FILE", default=None,
                        help="scope JSON produced by `qa.py scope` (resolved live when omitted).")
    parser.add_argument("--stack", metavar="FILE", default=None,
                        help="stack JSON produced by `qa.py detect` (detected live when omitted).")
    parser.add_argument("--requirements", action="append", dest="requirements", metavar="F",
                        default=None,
                        help="requirement document to read (repeatable).")


def _load_document(ctx, value: Optional[str], label: str) -> Optional[Dict[str, Any]]:
    if not value:
        return None
    path = qa_stack.resolve_input_path(ctx, value)
    if not path.is_file():
        raise common.QaError("%s file not found: %s" % (label, value), common.USAGE)
    document = common.read_json(path)
    if not isinstance(document, dict):
        raise common.QaError("%s file is not a JSON object: %s" % (label, value), common.USAGE)
    return document


def _round_module():
    """Import qa_round lazily so this module stays importable on its own."""
    try:
        from . import qa_round  # type: ignore
        return qa_round
    except ImportError:
        pass
    try:
        import qa_round  # type: ignore
        return qa_round
    except ImportError:
        raise common.QaError("the qa_round module is unavailable", common.RUNTIME_ERROR)


def run_plan(args: argparse.Namespace, ctx) -> int:
    """Write plan.json and plan.md into the round directory."""
    round_no = int(getattr(args, "round_no", 0) or 0)
    if round_no <= 0:
        raise common.QaError("--round must be a positive round number", common.USAGE)

    rounds = _round_module()
    if rounds.is_sealed(ctx, round_no):
        raise common.QaError(
            "round %03d is sealed; run `qa.py round new` before planning again" % round_no,
            common.SEALED_ROUND,
        )
    round_dir = pathlib.Path(rounds.round_dir(ctx, round_no))
    if not round_dir.is_dir():
        raise common.QaError(
            "round %03d does not exist; run `qa.py round new` first" % round_no, common.USAGE
        )

    stack = _load_document(ctx, getattr(args, "stack", None), "stack")
    if stack is None:
        stack = qa_stack.detect_stack(ctx)
    scope = _load_document(ctx, getattr(args, "scope", None), "scope")
    if scope is None:
        scope = resolve_scope(ctx, requirements=getattr(args, "requirements", None))

    requested_docs = getattr(args, "requirements", None)
    docs = None  # type: Optional[List[str]]
    if requested_docs:
        docs = _normalize_requirement_docs(ctx, requested_docs)

    plan = build_plan(ctx, scope, stack, docs, round_no=round_no)

    plan_json = qa_stack.guard_write_path(ctx, round_dir / "plan.json")
    plan_md = qa_stack.guard_write_path(ctx, round_dir / "plan.md")
    common.write_json(plan_json, plan)
    common.atomic_write(plan_md, render_plan_markdown(plan, scope, stack))

    document = dict(plan)
    document["files"] = {"planJson": ctx.rel(plan_json), "planMd": ctx.rel(plan_md)}
    ctx.emit(document)

    ctx.note("plan written to %s and %s" % (ctx.rel(plan_json), ctx.rel(plan_md)))
    ctx.note("checks: %d (%d need a layer decision)"
             % (len(plan["checks"]), len([c for c in plan["checks"] if c.get("todo")])))
    if plan["inferenceBased"]:
        ctx.progress("[qa] plan is INFERENCE-BASED: no requirement artifact was found")
    return common.OK


COMMANDS = [
    ("scope", HELP_SCOPE, add_scope_arguments, run_scope),
    ("plan", HELP_PLAN, add_plan_arguments, run_plan),
]
