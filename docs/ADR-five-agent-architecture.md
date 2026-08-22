# ADR — Five-Agent Governed Sepsis Architecture

**Status:** Proposed implementation
**Date:** 2026-08-21

## Decision

Extend the existing three-agent design into a governed five-agent architecture:

| Agent | Name | Runtime | Authority |
|---|---|---|---|
| 1 | Sepsis Bundle Agent / Orchestrator | real time | coordinates case workflow; deterministic SOFA remains authoritative |
| 2 | Antibiotic Specialist Agent | real time | proposes antibiotic regimen from approved deterministic KB; LLM narrates only |
| 3 | Guideline Surveillance Agent | scheduled background | detects candidate guideline changes; cannot activate clinical rules |
| 4 | Memory & Clinical Analytics Agent | asynchronous / longitudinal | stores structured case snapshots and computes aggregate analytics; cannot recommend treatment |
| 5 | Governance / Safety Monitor | synchronous gate + background audit | validates agent outputs, KB state, permissions and safety invariants; cannot choose treatment |

## Control flow

```text
                         ┌──────────────────────┐
                         │  3. Guideline        │
                         │  Surveillance Agent  │
                         └──────────┬───────────┘
                                    │ pending review
                                    ▼
                         ┌──────────────────────┐
                         │  5. Governance       │
                         │  approval gate        │
                         └──────────┬───────────┘
                                    │ approved immutable KB
                                    ▼
┌──────────────┐       ┌──────────────────────┐
│ Physician    │──────►│ 1. Sepsis Bundle     │
│              │       │    Orchestrator       │
└──────────────┘       └──────────┬───────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                           ▼
          deterministic SOFA           2. Antibiotic Agent
                                                │
                                                ▼
                                      5. Governance validation
                                                │
                                  ┌─────────────┴─────────────┐
                                  ▼                           ▼
                               PASS                         BLOCK
                                  │                           │
                                  ▼                           ▼
                        physician-facing result       manual review
                                  │
                                  ▼
                         4. Memory & Analytics
```

Agent 3 never runs in the patient-critical request path. Agent 4 never writes
a treatment recommendation. Agent 5 never selects or changes a drug.

## Non-negotiable safety properties

1. A language model cannot create a drug/dose/frequency that becomes trusted
   merely because it is plausible.
2. A guideline update cannot become active without an explicit human review.
3. Every trusted antibiotic response is tied to an immutable active KB version.
4. Governance is fail-closed: a critical mismatch results in BLOCK.
5. Antibiotic-path failure cannot block SOFA/Bundle output.
6. Memory analytics cannot modify source clinical records.
7. Analytics are aggregate by default and use pseudonymous patient keys.
8. All governance decisions are auditable.

## Important limitation

This is an engineering architecture, not evidence that the clinical KB is
correct. The existing KB remains a scaffold until reviewed by an ID physician /
clinical pharmacist and calibrated to the local antibiogram. The guideline
surveillance fetch remains license-gated.
