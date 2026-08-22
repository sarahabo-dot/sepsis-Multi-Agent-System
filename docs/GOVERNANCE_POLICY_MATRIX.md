# Governance Policy Matrix

This matrix is the authoritative deterministic policy for the Governance/Safety Monitor.
It defines what happens after validation finds a discrepancy or warning.

| Class | Examples | Decision | Physician | Memory | Audit |
|---|---|---|---|---|---|
| Identity / provenance | case ID mismatch, request type mismatch, KB version mismatch | **BLOCK** | Do not release | Record failure | Record block |
| Clinical regimen | unknown drug, dose/route/frequency mismatch | **BLOCK** | Do not release | Record failure | Record block |
| Renal safety | renal adjustment or renal note mismatch | **BLOCK** | Do not release | Record failure | Record block |
| Modifier integrity | modifier count/type/trigger/action mismatch | **BLOCK** | Do not release | Record failure | Record block |
| Fungal safety | fabricated/mismatched fungal flag | **BLOCK** | Do not release | Record failure | Record block |
| Timing | timing target mismatch | **BLOCK** | Do not release | Record failure | Record block |
| Missing data | missing-input mismatch or critical missing input | **BLOCK** | Do not release | Record failure | Record block |
| Non-critical missing data | missing inputs present | **WARNING** | Visible warning | Record | Record warning |
| Manual specialist review | fungal risk requiring ID/pharmacy review | **WARNING** | Visible warning | Record | Record warning |
| Narration | empty rationale | **WARNING** | Visible warning | Record | Record warning |
| Guideline approval | no reviewer, invalid review state, missing review ID | **BLOCK** | No activation | Record failure | Record block |
| Guideline KB integrity | empty/malformed KB or same active version | **BLOCK** | No activation | Record failure | Record block |
| Version assignment | proposed KB version omitted | **WARNING** | Visible warning | Record | Record warning |
| Unknown/new finding | finding not present in matrix | **BLOCK** | Do not release | Record failure | Record block |

## Fail-closed rule

The last row is intentional: **a new governance finding is a BLOCK until explicitly added to this matrix**. This prevents a future code change from silently introducing a safety condition that defaults to PASS.

## Release semantics

- **PASS:** trusted clinical output may cross the governance boundary.
- **WARNING:** output may cross the boundary, but warnings must remain visible and auditable.
- **BLOCK:** output must not cross the governance boundary. The raw response may remain available internally for debugging/audit, but it is not a trusted clinical recommendation.

## Data separation

- **Audit Trail:** records what happened, when, and why.
- **Memory Agent:** receives only the structured case snapshot permitted by the memory governance policy; a blocked antibiotic is not recorded as a trusted regimen.
- **Governance:** validates and gates; it never selects a replacement treatment.
