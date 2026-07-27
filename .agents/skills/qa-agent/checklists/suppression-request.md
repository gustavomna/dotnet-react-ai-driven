# Checklist — Suppression Request

Walk this list **before** adding an entry to `qa/suppressions.json`. Every item is phrased
so that **yes = proceed**. A single `no` means the suppression is refused and the check
runs.

A suppression is not a way to make a failure go away. It is a dated, justified, reviewable
admission that a known problem is being carried on purpose. If you cannot write the
justification, you do not have a suppression — you have a finding.

---

## 1. The three mandatory parts

A suppression is valid **only** with all three. Missing or empty any one of them makes the
entry **invalid**, which means the entry is reported *and the check runs anyway*.

| Part | What it must be | Rejected |
|---|---|---|
| `target` | The exact thing being suppressed, as `<source>:<rule>:<file-or-selector>` — one finding, not a family | `a11y:*`, a bare directory, a whole layer |
| `reason` | Why this specific finding is being carried, naming the constraint and the owner of the fix | "known issue", "false positive", "will fix later", an empty string |
| `expires` | An ISO date (`2026-12-31`), a version (`>=2.0.0`, `v3.1`), or a ticket reference (`JIRA-123` or a URL) | "never", "TBD", omitted |

- [ ] **Is `target` narrow enough to name one finding — one rule, on one file or one selector?**
      *If no:* narrow it. A suppression that catches tomorrow's regression as well as today's known problem is a disabled check.
- [ ] **Does `reason` say why the finding cannot be fixed now, not merely that it exists?**
      *If no:* rewrite it. Good reasons name an external constraint: an upstream bug with a link, a vendor bundle you do not control, a documented deprecation window.
- [ ] **Does `reason` name where the fix lives — an upstream issue, a ticket, or an owning team?**
      *If no:* add it. A reason without an owner never expires in practice, only on paper.
- [ ] **Is `expires` a condition that will actually arrive?**
      *If no:* replace it. See the guidance below.

## 2. What a good expiry looks like

An expiry is a promise that the suppression is temporary, expressed so that a machine can
tell when the promise comes due.

| Form | Example | Good when |
|---|---|---|
| ISO date | `2026-12-31` | The constraint is time-bound: a release window, a migration deadline, a contract end. Prefer the next quarter boundary; six months is a long suppression, twelve is an exceptional one. |
| Version | `>=2.0.0`, `v3.1` | The fix ships in a known upstream release. Pin the version that contains the fix, not "the next version". |
| Ticket | `JIRA-4471`, `https://github.com/vendor/dp/issues/412` | The work is tracked and someone owns it. The reference must resolve to a real, open item. |

- [ ] **Is the date within twelve months, or is a longer window explicitly justified in `reason`?**
      *If no:* shorten it. A three-year expiry is "never" with extra steps.
- [ ] **Does the version reference the release that actually contains the fix?**
      *If no:* find it, or use a date instead.
- [ ] **Does the ticket reference resolve to a real, open, owned item?**
      *If no:* open one first. The ticket is the expiry mechanism; a dead link disables it.
- [ ] **Do you accept that an expired suppression stops suppressing and the check comes back?**
      *If no:* you want a fix, not a suppression. Expired suppressions are reported as `expired` and never suppress.

## 3. Never suppressible

The following are rejected outright. No `reason` and no `expires` makes them valid.

- [ ] **Is this suppression NOT an attempt to disable an axe rule?**
      *If it is:* refused. `scope: "rule"` against an accessibility rule is always rejected. Disabling an axe rule removes a whole class of checks from every future round; the PRD forbids it and the tooling enforces it.
- [ ] **Is the selector NOT broad — not `html`, `body`, `#root`, `*`, and not empty or whitespace?**
      *If it is:* refused. A broad exclude silently deletes the a11y layer while leaving it looking green.
- [ ] **Is this NOT a failing test of an explicit stated acceptance criterion?**
      *If it is:* refused. A stated criterion is the definition of the work being correct. Suppressing it means shipping something that does not do what it was specified to do — that is a scope conversation with the requirement's owner, recorded by changing the requirement, not by hiding its check.
- [ ] **Is this NOT a flaky test?**
      *If it is:* refused. Flakiness is fixed or the test is rewritten; suppressing it hides an unreliable signal behind a reliable-looking green.
- [ ] **Is this NOT a whole layer, directory, package, or test file?**
      *If it is:* refused. Only `scope: "third-party"` may exclude a subtree, and only for a genuine third-party widget you do not author.
- [ ] **Is this NOT a way to unblock a merge under time pressure, with the intent to revisit "soon"?**
      *If it is:* refused. Write the issue file, ship with the finding visible, and let the humans decide. That decision is not the agent's to pre-empt.

## 4. Scope selection

`scope` is exactly one of:

| Scope | Meaning | Allowed to exclude a subtree? |
|---|---|---|
| `third-party` | A vendored or npm-installed widget whose markup you do not author | **Yes** — the only scope that may |
| `test` | A specific test that is known-broken for a recorded external reason | No |
| `rule` | A specific rule on a specific file, outside the a11y layer | No |

- [ ] **Is `scope: "third-party"` used only where the code is genuinely not yours to change?**
      *If no:* pick a different scope, or fix the code. "We copied it in once and never touched it" is your code.
- [ ] **For `third-party`, does the exclusion cover only the vendor subtree, leaving your own wrapper and everything around it scanned?**
      *If no:* narrow the selector.

## 5. Recording it

Add the entry with the CLI, so `id`, `addedAt`, and `addedBy` are filled consistently:

```bash
python3 .agents/skills/qa-agent/scripts/qa.py suppress add \
  --target "a11y:aria-required-children:frontend/src/vendor/date-picker.tsx" \
  --reason "third-party date picker; upstream issue vendor/dp#412" \
  --expires "2026-12-31" \
  --scope third-party
```

The exact JSON entry appended to `qa/suppressions.json`:

```json
{
  "id": "sup-001",
  "target": "a11y:aria-required-children:frontend/src/vendor/date-picker.tsx",
  "reason": "third-party date picker; upstream issue vendor/dp#412",
  "expires": "2026-12-31",
  "scope": "third-party",
  "addedBy": "gustavo",
  "addedAt": "2026-07-25"
}
```

It lives inside the top-level `suppressions` array:

```json
{
  "schemaVersion": 1,
  "suppressions": [ { "id": "sup-001", "...": "..." } ]
}
```

Then validate — this is not optional:

```bash
python3 .agents/skills/qa-agent/scripts/qa.py suppress validate
python3 .agents/skills/qa-agent/scripts/qa.py suppress list
```

`suppress validate` exits 0 when every entry is valid and 5 when any entry is malformed.

- [ ] **Does `suppress validate` exit 0 after the addition?**
      *If no:* fix the entry. Until it validates, the check runs — which is the correct behaviour, not a bug to work around.
- [ ] **Is `qa/suppressions.json` committed alongside the change it justifies, in the same pull request?**
      *If no:* commit it. A suppression added out of band is a suppression nobody reviewed.
- [ ] **Does the pull request description mention the suppression and its expiry?**
      *If no:* add it. The whole point is that weakening a gate is impossible to do silently.

---

## Refuse gate

If any item above answered `no`, do not add the entry. Say so plainly, in these terms:

> This finding is not suppressible: `<reason from the list above>`. It stays as
> `issue_NNN.md` at severity `<severity>`. Fixing it, or changing the requirement it
> tests, are the two available paths.

Then leave the issue file in place and let the round report `FAIL`.
