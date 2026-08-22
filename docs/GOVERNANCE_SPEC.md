# Governance Layer Specification

## Purpose

The Governance/Safety Monitor is the final deterministic boundary before an
agent output is considered trusted.

### It may

- validate schemas and identifiers
- verify active KB version
- verify drugs/doses/routes against the deterministic KB
- detect critical missing inputs
- enforce review-state transitions
- emit PASS / WARNING / BLOCK
- create audit events

### It may not

- choose a replacement antibiotic
- invent a dose
- use an LLM to decide whether an output is clinically correct
- silently modify an agent response
- activate a guideline without human approval

## States

```text
PENDING ──► APPROVED
   │
   └──────► REJECTED
```

No reverse transition is allowed through the normal approval API.

## Fail-closed rule

Any of the following must BLOCK:

- response KB version != active KB version
- drug absent from deterministic KB
- dose mismatch
- route mismatch
- case ID mismatch
- critical missing input
- approval attempted for a non-pending review
- missing reviewer
- malformed proposed KB

Warnings do not block, but must be visible and auditable.
