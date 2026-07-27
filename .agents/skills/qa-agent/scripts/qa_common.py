"""Shared primitives for the QA Agent CLI.

Everything that more than one QA module needs lives here: exit codes, the default
configuration, the execution :class:`Context`, JSON/atomic-write helpers, git
plumbing, secret redaction, fingerprinting and YAML scalar quoting.

No module ever imports ``qa.py`` (that would be circular) -- they import this
module instead. Standard library only, Python 3.9+.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
LAYER_ORDER = ("unit", "integration", "e2e", "a11y")
SEVERITIES = ("critical", "high", "medium", "low")

#: Placeholder substituted for every scrubbed secret.
REDACTED = "***REDACTED***"

# Exit codes -- the single source for every module and for the shell harnesses.
OK = 0
FAIL = 1
USAGE = 2
NO_STACK = 3
EMPTY_SCOPE = 4
INVALID_SUPPRESSION = 5
SEALED_ROUND = 6
RUNTIME_ERROR = 7

#: Default configuration; a user's ``qa/qa.config.json`` is deep-merged over it.
DEFAULT_CONFIG: Dict[str, Any] = {
    "schemaVersion": 1,
    "roundSequence": "independent",
    "outputDir": "qa",
    "layers": {"unit": True, "integration": True, "e2e": True, "a11y": True},
    "gate": {
        "skippedLayers": "warn",
        "staleRound": "warn",
        "flaky": "fail",
        # OFF by default: the PRD verdict rule is absolute. Opting in lets a round
        # whose every failure is baseline-matched or suppressed gate green, and the
        # summary then records rawVerdict + verdictAdjusted so nothing is hidden.
        "baselineOnly": False,
    },
    "scope": {"defaultBase": "main", "packages": []},
    "generation": {"autoStage": False, "testDirOverrides": {}},
    "a11y": {
        "tags": ["wcag2a", "wcag2aa", "wcag22aa"],
        "routes": [],
        "failOnIncomplete": False,
        # Where the a11y layer leaves raw axe payloads. Playwright's testInfo
        # attachments land under test-results/; the component helpers write
        # qa-axe-*.json. Globs are repo-relative.
        "resultsGlob": [
            "test-results/**/axe-*.json",
            "**/qa-axe-*.json",
            "**/axe-results*.json",
        ],
    },
    "execution": {"timeoutSeconds": 1800, "retryFailedOnce": True},
}

PathLike = Union[str, "os.PathLike[str]", pathlib.Path]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class QaError(Exception):
    """An expected, reportable condition. Carries the process exit code.

    Raise this instead of letting a traceback reach the operator whenever the
    situation is one the CLI knows how to describe (bad config, sealed round,
    empty scope, ...).
    """

    def __init__(self, message: str, code: int = RUNTIME_ERROR) -> None:
        super().__init__(message)
        self.message = str(message)
        self.code = int(code)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


# ---------------------------------------------------------------------------
# Write-scope guard
# ---------------------------------------------------------------------------

_WRITE_ROOTS: List[str] = []


def register_write_root(path: PathLike) -> None:
    """Allow writes under ``path``.

    While no root is registered the guard is inert (library and unit-test use).
    :class:`Context` registers the repo root and the QA output directory, which
    is what enforces the contract's write-scope rule at runtime.
    """

    try:
        real = os.path.realpath(str(path))
    except (OSError, ValueError):  # pragma: no cover - defensive
        return
    if real and real not in _WRITE_ROOTS:
        _WRITE_ROOTS.append(real)


def ensure_within(root: PathLike, path: PathLike) -> pathlib.Path:
    """Return ``path`` as an absolute path, or raise when it escapes ``root``."""

    target = pathlib.Path(os.path.realpath(os.path.abspath(str(path))))
    base = pathlib.Path(os.path.realpath(os.path.abspath(str(root))))
    try:
        target.relative_to(base)
    except ValueError:
        raise QaError(
            "refusing to write outside {0}: {1}".format(base.as_posix(), target.as_posix()),
            RUNTIME_ERROR,
        )
    return pathlib.Path(os.path.abspath(str(path)))


def ensure_writable(ctx: "Context", path: PathLike) -> pathlib.Path:
    """Refuse any write that escapes both the repo root and the QA directory.

    Comparison is done on the realpath so a symlink cannot be used to escape, but
    the ABSPATH is returned: ``Context.rel`` relativizes against the repo's
    un-resolved form, and on macOS (``/tmp`` -> ``/private/tmp``) the two disagree,
    which reported a correct write under a nonsense path. Single implementation on
    purpose -- three private copies of this drifted apart once already.
    """

    absolute = pathlib.Path(os.path.abspath(str(path)))
    resolved = pathlib.Path(path).resolve()
    for root in (pathlib.Path(ctx.repo).resolve(), pathlib.Path(ctx.qa_dir).resolve()):
        if resolved == root or root in resolved.parents:
            return absolute
    raise QaError(
        "refusing to write outside the repository: {0}".format(resolved), USAGE
    )


def _guard_write(path: PathLike) -> pathlib.Path:
    """Check ``path`` against every registered write root."""

    absolute = pathlib.Path(os.path.abspath(str(path)))
    if not _WRITE_ROOTS:
        return absolute
    real = os.path.realpath(str(absolute))
    for root in _WRITE_ROOTS:
        if real == root or real.startswith(root.rstrip(os.sep) + os.sep):
            return absolute
    raise QaError(
        "refusing to write outside the allowed roots ({0}): {1}".format(
            ", ".join(_WRITE_ROOTS), absolute.as_posix()
        ),
        RUNTIME_ERROR,
    )


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------


def atomic_write(path: PathLike, text: str, root: Optional[PathLike] = None) -> None:
    """Write ``text`` via a temp file in the same directory, then ``os.replace``.

    Parent directories are created. ``root``, when given, additionally pins the
    write to that subtree.
    """

    target = _guard_write(path)
    if root is not None:
        ensure_within(root, target)
    directory = target.parent
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise QaError("cannot create directory {0}: {1}".format(directory, exc))

    handle = None
    tmp_name = ""
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=".{0}.".format(target.name), suffix=".tmp", dir=str(directory)
        )
        handle = os.fdopen(fd, "w", encoding="utf-8", newline="\n")
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        handle = None
        os.replace(tmp_name, str(target))
        tmp_name = ""
    except OSError as exc:
        raise QaError("cannot write {0}: {1}".format(target, exc))
    finally:
        if handle is not None:  # pragma: no cover - defensive
            try:
                handle.close()
            except OSError:
                pass
        if tmp_name and os.path.exists(tmp_name):  # pragma: no cover - defensive
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def write_json(path: PathLike, obj: Any, root: Optional[PathLike] = None) -> None:
    """Serialize ``obj`` as pretty JSON with a trailing newline, atomically."""

    try:
        text = json.dumps(obj, indent=2, sort_keys=False, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise QaError("cannot serialize JSON for {0}: {1}".format(path, exc))
    atomic_write(path, text + "\n", root=root)


def read_json(path: PathLike, default: Any = None) -> Any:
    """Read a JSON document, returning ``default`` when the file is absent."""

    target = pathlib.Path(str(path))
    if not target.is_file():
        return default
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise QaError("cannot read {0}: {1}".format(target, exc))
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise QaError("invalid JSON in {0}: {1}".format(target, exc), USAGE)


def repo_rel(repo: PathLike, path: PathLike) -> str:
    """Return ``path`` relative to ``repo`` using POSIX separators."""

    base = pathlib.Path(os.path.abspath(str(repo)))
    target = pathlib.Path(os.path.abspath(str(path)))
    try:
        return target.relative_to(base).as_posix()
    except ValueError:
        try:
            return pathlib.PurePath(os.path.relpath(str(target), str(base))).as_posix()
        except ValueError:  # pragma: no cover - different drives on Windows
            return target.as_posix()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge ``override`` into a copy of ``base``.

    Dicts merge key by key; scalars and lists replace wholesale.
    """

    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_config(path: Optional[PathLike] = None, repo: Optional[PathLike] = None) -> Dict[str, Any]:
    """Return :data:`DEFAULT_CONFIG` deep-merged with the user's config file.

    A missing file is not an error -- the defaults stand on their own.
    """

    defaults = copy.deepcopy(DEFAULT_CONFIG)
    if path is None:
        base = pathlib.Path(os.path.abspath(str(repo))) if repo is not None else pathlib.Path.cwd()
        path = base / str(defaults["outputDir"]) / "qa.config.json"
    user = read_json(path, default=None)
    if user is None:
        return defaults
    if not isinstance(user, dict):
        raise QaError("config {0} must contain a JSON object".format(path), USAGE)
    return _deep_merge(defaults, user)


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------


def utc_now_iso() -> str:
    """UTC timestamp such as ``2026-07-25T14:02:33Z``."""

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_id_now() -> str:
    """UTC run identifier such as ``20260725-140233``."""

    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------


def run_git(repo: PathLike, *args: str, **kwargs: Any) -> Tuple[int, str, str]:
    """Run ``git -C <repo> <args>`` and return ``(returncode, stdout, stderr)``.

    Never raises on a non-zero exit. ``check=True`` turns a non-zero exit into a
    :class:`QaError`. A missing ``git`` binary yields ``(127, "", reason)``.
    """

    check = bool(kwargs.pop("check", False))
    timeout = kwargs.pop("timeout", 120)
    if kwargs:
        raise TypeError("run_git() got unexpected keyword arguments: {0}".format(sorted(kwargs)))

    argv = ["git", "-C", str(repo)] + [str(a) for a in args]
    try:
        completed = subprocess.run(  # noqa: S603 - argv list, shell=False
            argv,
            shell=False,
            cwd=None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        code = int(completed.returncode)
        out = completed.stdout.decode("utf-8", "replace")
        err = completed.stderr.decode("utf-8", "replace")
    except FileNotFoundError:
        code, out, err = 127, "", "git executable not found on PATH"
    except subprocess.TimeoutExpired:
        code, out, err = 124, "", "git timed out after {0}s: {1}".format(timeout, " ".join(argv))
    except OSError as exc:  # pragma: no cover - defensive
        code, out, err = 1, "", "cannot run git: {0}".format(exc)

    if check and code != 0:
        raise QaError("git {0} failed ({1}): {2}".format(" ".join(args), code, err.strip()))
    return code, out, err


def default_base_branch(repo: PathLike) -> Optional[str]:
    """Resolve the default base branch: ``origin/HEAD`` -> ``main`` -> ``master``.

    When ``origin/HEAD`` points at a branch that also exists locally the short
    local name is returned (``main``), otherwise the remote-tracking name
    (``origin/main``). Returns ``None`` when nothing resolves.
    """

    code, out, _ = run_git(repo, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    remote_ref = out.strip()
    if code == 0 and remote_ref:
        short = remote_ref.split("/", 1)[1] if "/" in remote_ref else remote_ref
        if short and _git_ref_exists(repo, "refs/heads/{0}".format(short)):
            return short
        return remote_ref

    for candidate in ("main", "master"):
        if _git_ref_exists(repo, "refs/heads/{0}".format(candidate)):
            return candidate
        if _git_ref_exists(repo, "refs/remotes/origin/{0}".format(candidate)):
            return "origin/{0}".format(candidate)
    return None


def _git_ref_exists(repo: PathLike, ref: str) -> bool:
    code, _, _ = run_git(repo, "rev-parse", "--verify", "--quiet", ref)
    return code == 0


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

# "AUTH" carries a lookahead so that "author:" -- a legitimate issue frontmatter
# key -- is never mistaken for a credential; "AUTHORIZATION" is matched outright.
# "KEY" is guarded on BOTH sides so that "keyboard" and "monkey" survive while the
# contract's bare-KEY alternative still matches "KEY=", "--key=", "x-api-key:" and
# "SOME_KEY=". "APIKEY"-style run-ons keep their own explicit alternatives, since a
# preceding letter blocks the guarded form.
_SECRET_WORD = (
    r"(?:TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|CREDENTIAL|PRIVATE_?KEY|ACCESS_?KEY"
    r"|(?<![A-Za-z])KEY(?![A-Za-z])|AUTHORIZATION|AUTH(?![A-Za-z]))"
)

#: Matches an environment variable *name* that is likely to hold a secret.
SECRET_NAME_RE = re.compile(_SECRET_WORD, re.IGNORECASE)

# KEY=VALUE / KEY: VALUE, optionally as a --flag. Quantifiers are bounded so the
# pattern stays linear on hostile input.
_KEY_VALUE_RE = re.compile(
    r"(?P<key>(?:--?)?[A-Za-z0-9_.\-]{0,64}"
    + _SECRET_WORD
    + r"[A-Za-z0-9_.\-]{0,64})"
    r"(?P<sep>[ \t]*[=:][ \t]*)"
    r"(?P<val>(?:(?:bearer|basic|token)[ \t]+)?(?:\"[^\"\n]*\"|'[^'\n]*'|[^\s]+))",
    re.IGNORECASE,
)

_BEARER_RE = re.compile(
    r"\b(?P<kind>bearer)[ \t]+(?P<tok>[A-Za-z0-9\-._~+/]{4,}=*)", re.IGNORECASE
)

_URL_CRED_RE = re.compile(
    r"(?P<scheme>[A-Za-z][A-Za-z0-9+.\-]{0,31}://)(?P<user>[^\s/@:]{1,128}):(?P<pw>[^\s/@]{0,256})@"
)


def _env_secret_values() -> List[str]:
    """Literal values of secret-looking environment variables, longest first."""

    values = []
    for name, value in os.environ.items():
        if not value or len(value) <= 6:
            continue
        if SECRET_NAME_RE.search(name):
            values.append(value)
    values.sort(key=len, reverse=True)
    return values


def redact(text: str) -> str:
    """Scrub secrets from ``text``. Never raises; safe on very large strings.

    Removes ``KEY=VALUE`` / ``KEY: VALUE`` pairs whose key names a credential,
    ``Bearer``/``Basic`` tokens, ``scheme://user:pass@host`` URLs, and the literal
    value of any secret-looking environment variable longer than six characters.
    """

    try:
        if text is None:
            return ""
        if not isinstance(text, str):
            text = str(text)
        if not text:
            return text

        out = _KEY_VALUE_RE.sub(lambda m: m.group("key") + m.group("sep") + REDACTED, text)
        out = _BEARER_RE.sub(lambda m: m.group("kind") + " " + REDACTED, out)
        out = _URL_CRED_RE.sub(lambda m: m.group("scheme") + REDACTED + "@", out)
        for value in _env_secret_values():
            if value in out:
                out = out.replace(value, REDACTED)
        return out
    except Exception:  # pragma: no cover - redaction must never break a run
        return text if isinstance(text, str) else str(text)


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------


def sha256_fp(*parts: str) -> str:
    """Stable ``sha256:<hex>`` fingerprint over ``parts`` joined with ``|``."""

    payload = "|".join("" if p is None else str(p) for p in parts)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# YAML scalars (issue frontmatter)
# ---------------------------------------------------------------------------

_YAML_SPECIAL_CHARS = frozenset(":#{}[],&*!|>'\"%@`")
_YAML_RESERVED_WORDS = frozenset(
    ["true", "false", "yes", "no", "on", "off", "y", "n", "null", "none", "~"]
)


def _looks_like_number(value: str) -> bool:
    candidate = value.strip()
    if not candidate:
        return False
    try:
        float(candidate)
        return True
    except ValueError:
        pass
    try:
        int(candidate, 0)
        return True
    except ValueError:
        return False


def _double_quote(value: str) -> str:
    chunks = []
    for char in value:
        if char == "\\":
            chunks.append("\\\\")
        elif char == '"':
            chunks.append('\\"')
        elif char == "\n":
            chunks.append("\\n")
        elif char == "\r":
            chunks.append("\\r")
        elif char == "\t":
            chunks.append("\\t")
        elif ord(char) < 0x20 or ord(char) == 0x7F:
            chunks.append("\\x{0:02x}".format(ord(char)))
        else:
            chunks.append(char)
    return '"' + "".join(chunks) + '"'


def yaml_scalar(value: Any) -> str:
    """Render ``value`` as a YAML scalar, double-quoting whenever YAML would misparse it."""

    if value is None:
        return '""'
    if not isinstance(value, str):
        return _double_quote(str(value))
    if value == "":
        return '""'
    if value != value.strip():
        return _double_quote(value)
    if any(char in _YAML_SPECIAL_CHARS for char in value):
        return _double_quote(value)
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return _double_quote(value)
    if value[0] in "-?":
        return _double_quote(value)
    if value.lower() in _YAML_RESERVED_WORDS:
        return _double_quote(value)
    if _looks_like_number(value):
        return _double_quote(value)
    return value


# ---------------------------------------------------------------------------
# Execution context
# ---------------------------------------------------------------------------


class Context:
    """Everything a subcommand needs: paths, config, and the two output streams.

    stdout carries JSON only; stderr carries human prose. ``note`` is silenced by
    ``--json``; ``progress`` never is, so a long suite is never mistaken for a hang.
    """

    def __init__(
        self,
        repo: PathLike,
        qa_dir: Optional[PathLike] = None,
        config: Optional[Dict[str, Any]] = None,
        json_only: bool = False,
        stdout: Any = None,
        stderr: Any = None,
    ) -> None:
        self.repo = pathlib.Path(os.path.abspath(str(repo)))
        self.config = copy.deepcopy(DEFAULT_CONFIG) if config is None else config
        if qa_dir is None:
            qa_dir = self.repo / str(self.config.get("outputDir") or "qa")
        qa_path = pathlib.Path(str(qa_dir))
        if not qa_path.is_absolute():
            qa_path = self.repo / qa_path
        self.qa_dir = pathlib.Path(os.path.abspath(str(qa_path)))
        self.json_only = bool(json_only)
        self._stdout = stdout if stdout is not None else sys.stdout
        self._stderr = stderr if stderr is not None else sys.stderr

        register_write_root(self.repo)
        register_write_root(self.qa_dir)

    # -- output ------------------------------------------------------------

    def emit(self, obj: Dict[str, Any]) -> None:
        """Write the command's JSON document to stdout."""

        try:
            text = json.dumps(obj, indent=2, sort_keys=False, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise QaError("cannot serialize command output: {0}".format(exc))
        self._stdout.write(text + "\n")
        self._stdout.flush()

    def note(self, msg: str) -> None:
        """Human prose on stderr, suppressed by ``--json``."""

        if self.json_only:
            return
        self._write_stderr(msg)

    def progress(self, msg: str) -> None:
        """Progress line on stderr; always emitted, even under ``--json``."""

        self._write_stderr(msg)

    def _write_stderr(self, msg: str) -> None:
        line = "" if msg is None else str(msg)
        if not line.startswith("[qa]"):
            line = "[qa] " + line
        self._stderr.write(line + "\n")
        self._stderr.flush()

    # -- paths -------------------------------------------------------------

    def rel(self, p: PathLike) -> str:
        """``p`` as a repo-relative POSIX path."""

        return repo_rel(self.repo, p)

    def rounds_dir(self) -> pathlib.Path:
        """``<qa-dir>/rounds``."""

        return self.qa_dir / "rounds"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Context(repo={0!r}, qa_dir={1!r}, json_only={2!r})".format(
            self.repo.as_posix(), self.qa_dir.as_posix(), self.json_only
        )


__all__ = [
    "SCHEMA_VERSION",
    "LAYER_ORDER",
    "SEVERITIES",
    "REDACTED",
    "OK",
    "FAIL",
    "USAGE",
    "NO_STACK",
    "EMPTY_SCOPE",
    "INVALID_SUPPRESSION",
    "SEALED_ROUND",
    "RUNTIME_ERROR",
    "DEFAULT_CONFIG",
    "QaError",
    "Context",
    "atomic_write",
    "default_base_branch",
    "ensure_within",
    "load_config",
    "read_json",
    "redact",
    "register_write_root",
    "repo_rel",
    "run_git",
    "run_id_now",
    "sha256_fp",
    "utc_now_iso",
    "write_json",
    "yaml_scalar",
]
