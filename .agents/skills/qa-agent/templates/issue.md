<!--
HOW TO FILL THIS TEMPLATE

1. DELETE THIS COMMENT BLOCK. The `---` opening the frontmatter must be line 1 of the
   emitted file, or the issue is unparseable and invisible to CI.
2. Save as `qa/rounds/<NNN>/issue_<NNN>.md`. Issue numbering is zero-padded to three
   digits and continues from the highest existing issue in that round.
3. One file per failure. Never combine two unrelated problems.
4. Frontmatter keys are exactly `status`, `file`, `line`, `severity`, `author`, `source`
   in that order — no extras, no omissions.
     status   : open | informational   (informational = baseline-matched, non-blocking)
     file     : repo-relative POSIX path
     line     : integer; 0 when there is no meaningful line
     severity : critical | high | medium | low
     author   : qa-agent, unless another author is passed with --author
     source   : unit | integration | e2e | a11y | flake | plan
   Double-quote any value containing `:` `#` `{` `[` or a leading `-`/`?`, and any empty
   value, so the YAML still parses.
5. All five body sections are mandatory. "Suggested fix" may say the cause is
   undetermined, but the section is never omitted.
6. Redact secrets. Logs and issue files are committed artifacts.
-->
---
status: open
file: <frontend/src/components/foo.tsx>
line: <42>
severity: <high>
author: qa-agent
source: <unit>
---

# issue_<NNN> — <one-line title: what is wrong, in the reader's terms, not the runner's>

## Failing assertion

`<expect(screen.getByText('No results')).toBeInTheDocument()>` — <what the runner
actually reported, quoted or paraphrased in one sentence>.

## Observed vs expected

| | |
|---|---|
| Expected | <the behaviour the criterion requires, stated as an observable outcome> |
| Observed | <what actually happened, stated as an observable outcome> |

## Reproduce

```bash
<cd frontend && npm run test -- --run src/__tests__/foo.test.tsx -t "renders empty state">
```

## Requirement

`<FR-3>` — <tasks/prd-<feature>/prd.md> — "<the criterion, quoted>"

<For an inferred expectation, write: `inferred` — derived from <source>, no stated
criterion. For an accessibility finding, add the axe rule and its help URL:
`axe: <rule-id>` — <https://dequeuniversity.com/rules/axe/4.10/<rule-id>>.>

## Suggested fix

<A concrete, located change: the file and line that causes the behaviour, why it causes
it, and what to do instead. When the cause is undetermined, say so and name the next
diagnostic step — never leave this section empty and never guess silently.>
