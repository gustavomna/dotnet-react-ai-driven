# Scope Resolution

Scope resolution answers two questions: *what changed*, and *what was it supposed to do*. It
yields exactly one target file set per round. The mechanics belong to
`qa.py scope`; the judgement — which criterion maps to which layer — belongs to the agent.

```bash
python3 .agents/skills/qa-agent/scripts/qa.py scope --diff --json > qa/rounds/001/scope.json
```

## The four scope sources

| Source | Flag | Produces |
|---|---|---|
| Explicit path or package | `--path P` (repeatable), `--package NAME` (repeatable) | Every file under the given paths, or under the roots of the named projects |
| Git ref range | `--ref-range A...B` | Every file changed between the two refs |
| Requirements document | `--requirements F` (repeatable) | The files the document's criteria point at, plus the document itself as a `requirementDoc` |
| Working-tree diff | `--diff`, `--base BRANCH` | Every file changed against the base branch, plus uncommitted changes |

## Intersection semantics

**When several sources are given, the intersection wins.** Not the union.

Two sources naming disjoint file sets produce an empty scope — that is a legitimate signal, not
a bug. `--path frontend/src/components --ref-range main...HEAD` means *the components touched by
this branch*, and if the branch touched no component, the answer is "nothing to verify here".

- Exit code 4 (`EMPTY_SCOPE`) with `"empty": true` when the intersection is empty.
- On an empty scope, report which sources were intersected and what each one produced
  individually. Ask for an explicit narrower or wider source. **Never widen the scope yourself
  to find something to test.**

## The default-to-diff rule

When **no** source is given, the scope is the diff against the default branch. The base is
resolved in this order, first that resolves winning:

1. `origin/HEAD`
2. `main`
3. `master`
4. no base resolves (a fresh repo with a single branch, a detached CI checkout) → the
   working-tree diff, recorded in `notes[]` so the report can say why

`scope.defaultBase` in `qa/qa.config.json` overrides the search. The resolved base and range are
echoed back as `base` and `refRange`.

## The result document

```json
{
  "schemaVersion": 1,
  "sources": ["diff"],
  "base": "main",
  "refRange": "main...HEAD",
  "empty": false,
  "files": [
    {"path": "frontend/src/components/foo.tsx", "status": "M", "kind": "source",
     "project": "frontend", "touchesUi": true, "isTest": false}
  ],
  "packages": ["frontend"],
  "requirementDocs": ["tasks/prd-x/prd.md"],
  "notes": ["..."]
}
```

- `kind` is one of `source`, `test`, `config`, `doc`, `asset`, `other`.
- `isTest` marks files that are themselves tests — they inform convention discovery and
  collision detection, and they are not targets for generation.
- **`touchesUi` is the a11y trigger.** It is true for `.tsx`, `.jsx`, `.vue`, `.svelte`, `.css`,
  `.html`, and for Razor/`.cshtml`. **Any `touchesUi` file in scope makes the a11y layer
  required for the round, without the developer asking for it.** Follow
  [../../a11y-testing/SKILL.md](../../a11y-testing/SKILL.md) for that layer.

## Monorepo: per-package derivation

Scope is derived **per changed package automatically**. The agent does not require an explicit
package target and does not test the whole repository because one package moved.

- `packages[]` lists every project from the detected stack whose root prefixes at least one
  in-scope file.
- Each package's checks run against that package's own runner, cwd, and conventions. A change
  spanning `frontend/` and `backend/` produces checks in both, each using its own toolchain.
- `--package NAME` **narrows** the derived set; it never adds a package that has no changed
  file. `scope.packages` in the config pins a fixed list for repositories where derivation is
  not wanted.
- A file that belongs to no detected project is recorded with `"project": null` and reported —
  it may indicate an undetected project root.

## Requirement-artifact discovery

When `--requirements` is absent, these are searched, in this order, and every match is recorded
in `requirementDocs[]`:

- `tasks/prd-*/prd.md`
- `tasks/prd-*/techspec.md`
- `tasks/prd-*/tasks.md`
- `docs/prd*.md`
- `*_user_stories.md`
- `adrs/*.md`

`.github/ISSUE_TEMPLATE` is **not** a requirement document — it describes how to file an issue,
not what the software must do. Neither are `README.md`, changelogs, or commit messages.

Read every discovered document in full before planning. Extract each acceptance criterion with a
stable reference (`FR-3`, `US-014`, `AC-2`) and the source location (`tasks/prd-x/prd.md#L42`)
so every generated test and every issue can cite it.

## The inference-based fallback

When discovery finds nothing, the agent does not stop and does not guess silently. It derives
expected behavior from:

1. **The diff itself** — what the change added, removed, or altered, and the behavior implied by
   the new branches and error paths.
2. **Public interfaces** — exported functions, component props, controller routes and their DTOs,
   published events. These are contracts even when nothing writes them down.
3. **Existing tests around the changed code** — the conventions they encode and the behaviors
   they already assert.

Then:

- `plan.json` sets `"inferenceBased": true`.
- **The first line of `plan.md` states that the plan is inference-based**, naming what it was
  inferred from.
- The final report repeats it. An inferred failure defaults to severity `medium`, not `high` —
  `high` is reserved for an explicit stated criterion.
- Every inferred criterion is still traceable: the test header cites the interface or diff hunk
  it was derived from, in place of a requirement reference.
