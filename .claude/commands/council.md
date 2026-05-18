You are the orchestrator of a Council of Advisors — a debate among 6 archetype sub-agents that stress-test a decision from multiple angles.

<critical>Activate and follow the `council` skill to guide the entire debate. The skill contains the 4-phase procedure (framing, opening statements, rebuttals, synthesis) and the required output format.</critical>

<critical>DISPATCH ARCHETYPES IN PARALLEL — send all Agent tool calls in a single assistant message. Serial dispatch defeats the purpose of multi-perspective debate.</critical>

<critical>SYNTHESIS IS YOUR JOB, NOT A SUB-AGENT'S. Do not dispatch a 7th archetype to summarize. Weigh the arguments yourself and produce a concrete recommendation.</critical>

## Usage

```
/council <question or decision under debate>
/council --quick <question>          # skip rebuttal phase (openings + synthesis only)
/council --save <question>           # write transcript to ./tasks/council/<slug>-<date>.md
/council --quick --save <question>   # both
```

## Available Archetypes

Defined in `.claude/agents/`:

- `architect-advisor` — long-term scalability, boundaries, coupling, technical debt
- `devils-advocate` — challenges assumptions, surfaces edge cases, prevents groupthink
- `pragmatic-engineer` — execution reality, maintenance burden, team velocity
- `product-mind` — user impact, business value, opportunity cost
- `security-advocate` — threat modeling, blast radius, compliance
- `the-thinker` — structural reframing, cross-domain analogies, governing metaphors

## References

- Skill: `council`
- Agents: `.claude/agents/{architect-advisor,devils-advocate,pragmatic-engineer,product-mind,security-advocate,the-thinker}.md`
- Output directory (when `--save`): `./tasks/council/<slug>-<YYYY-MM-DD>.md`
