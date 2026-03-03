# Architecture Decision Record

Create an ADR for a significant technical decision.

## Template

Create a new file: `docs/decisions/ADR-NNN-<slug>.md`

```markdown
# ADR-NNN: <Title>

**Status:** Proposed | Accepted | Deprecated | Superseded
**Date:** YYYY-MM-DD
**Context:** What prompted this decision?

## Decision

What was decided and why.

## Alternatives Considered

| Option | Pros | Cons |
|--------|------|------|
| Chosen | ... | ... |
| Rejected A | ... | ... |
| Rejected B | ... | ... |

## Consequences

What changes as a result of this decision?

## References

Links to relevant docs, issues, benchmarks.
```

## Numbering

Check existing ADRs: `ls docs/decisions/`
Use the next sequential number.

## When to Write an ADR

- Choosing between competing technologies (vLLM vs SGLang)
- Changing the architecture (adding a node, changing a database)
- Selecting a deployment strategy
- Any decision that would be hard to reverse
