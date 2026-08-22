# Architecture Decision Record: Antibiotic Recommendation — Multi-Agent Design

**Project:** Sepsis Bundle Agent (Shura platform)
**Status:** Accepted — design phase, implementation pending
**Author:** Sarah (Clinical Lead / Product Architect)
**Date:** 2026-08-19

---

## 1. Context

The Sepsis Bundle Agent currently handles deterministic SOFA scoring and Hour-1
Bundle tracking (`sofa_calculator.py`, existing production system). We want to
add a feature that helps the physician select an appropriate empirical
antibiotic for a sepsis case, according to current guidelines and dosing, and
later suggest de-escalation once culture results are available.

This is a materially different kind of decision than SOFA scoring:

- SOFA is a fixed, deterministic threshold table. Antibiotic selection depends
  on local antibiogram, MDR/MRSA/anaerobic/fungal risk factors, renal/hepatic
  dosing, and allergy history — a real decision tree, not a lookup table.
- The knowledge underlying antibiotic choice changes over time (guideline
  updates) in a way SOFA thresholds do not.
- The clinical risk of a wrong suggestion (drug, dose, or missed
  contraindication) is higher than a mis-scored SOFA component.

Two questions had to be answered before implementation:

1. Should antibiotic recommendation be a **tool inside** the existing Sepsis
   Bundle Agent's tool-use loop, or a **separate agent**?
2. How do we keep the underlying antibiotic knowledge current without letting
   an automated process silently change what a treating physician sees?

---

## 2. Decision

Build **three separate agents**, not one:

| # | Agent | Role | When it runs |
|---|---|---|---|
| 1 | **Sepsis Bundle Agent** | Orchestrator. Owns SOFA calculation and Hour-1 Bundle tracking (existing, unchanged). Dispatches to Agent 2 and merges results. | Real-time, per patient case |
| 2 | **Antibiotic Specialist Agent** | Proposes empirical antibiotic (by severity/source/risk factors) and later de-escalation advice (by culture result). Own system prompt, own knowledge base, possibly a different model. | Real-time, in parallel with SOFA/Bundle tools |
| 3 | **Guideline Surveillance Agent** | Periodically checks external guideline sources, compares to the current knowledge base, and alerts the clinical lead when a change is detected. | Background/async (e.g. weekly), never during an active patient case |

Agent 1 remains the single entry point the physician interacts with. Agents 2
and 3 are new.

---

## 3. Rationale

### 3.1 Why Agent 2 is separate from Agent 1 (not a tool in the same loop)

- **Architectural isolation for maintainability.** Antibiotic logic has its own
  decision tree (severity × source × MDR × MRSA × anaerobic × renal dosing)
  and its own test surface. Keeping it separate means it can be built, tested,
  and changed without touching SOFA/Bundle logic, and vice versa.
- **Different model requirement.** Agent 2 may use a different underlying
  model than Agent 1. A single-agent tool-use loop cannot swap models
  mid-conversation; a separate agent can.
- **Different knowledge source lifecycle.** SOFA thresholds are fixed
  clinical constants. The antibiotic knowledge base must reflect the local
  antibiogram and is expected to change — this needs its own update pipeline
  (see Agent 3), independent of anything else in the system.
- **Different risk/sign-off profile.** A drug + dose recommendation carries
  different review requirements than a bundle-timing recommendation. Keeping
  them as separate calls makes it possible to isolate audit trail and sign-off
  per decision type, not just per case.

### 3.2 Why Agent 3 is separate from Agent 2 (not the same agent doing both)

- Agent 2 answers "what should this patient get, right now." Agent 3 answers
  "has the underlying guideline changed." These operate on completely
  different timescales (seconds vs. weeks) and different inputs (patient data
  vs. external literature).
- Mixing them would mean the agent making real-time treatment suggestions
  also has the ability to search the web mid-consult — unacceptable for
  reproducibility and latency reasons in an active sepsis case.

### 3.3 Rejected alternative: single agent with an antibiotic tool

Considered and rejected. Would have been simpler to build, but:
- Locks Agent 2's logic to the same model as Agent 1.
- Any antibiogram update would require re-testing the whole Sepsis Bundle
  Agent, not just the antibiotic component.
- No clean way to isolate sign-off/audit for antibiotic decisions specifically.

---

## 4. Design details

### 4.1 Real-time flow (Agents 1 + 2)

```
Physician submits case
        │
        ▼
Sepsis Bundle Agent (orchestrator)
        │
        ├──► SOFA & Bundle tools (existing, deterministic)
        │
        └──► Antibiotic Specialist Agent (separate model + KB)
                     │
        (both run in parallel, not sequentially)
                     │
                     ▼
              Synthesis layer
                     │
                     ▼
            Physician sign-off
```

**Parallel dispatch, not sequential.** Total latency = the slower of the two
branches, not the sum. This directly addresses the earlier concern about
tool-call latency compounding inside a single loop.

**Failure handling (graceful degradation).** If Agent 2 fails or times out,
the synthesis layer still returns SOFA/Bundle results immediately, with the
antibiotic section marked unavailable. SOFA/Bundle output must never be
blocked by a failure in the antibiotic path.

**Audit trail.** Every case gets a single `case_id` that links the Agent 1 and
Agent 2 records in the audit log, so a later review can reconstruct the full
picture (SOFA at time T, antibiotic suggestion at time T, physician's
approval/edit) rather than two disconnected logs.

### 4.2 Empirical antibiotic decision framework (Agent 2 logic)

Based on Surviving Sepsis Campaign guidance (see research notes, 2026-08-19
session):

```
INPUT: severity (sepsis / septic shock), suspected_source,
       MDR_risk_factors[], MRSA_risk_factors[], anaerobic_risk_factors[],
       fungal_risk_factors[], creatinine (renal dose adjustment)

STEP 1 — Timing target
  septic_shock      → 1 hour
  sepsis_no_shock   → 3 hours

STEP 2 — Base empirical regimen
  Looked up from curated local knowledge base (NOT LLM memory),
  keyed by source × severity.

STEP 3 — Coverage modifiers (each evaluated and surfaced independently)
  IF MDR_risk_factors present       → add/switch to MDR-covering agent
  IF MRSA_risk_factors present      → add MRSA coverage
  IF anaerobic_risk_factors present → add anaerobic coverage
  IF fungal_risk_factors present    → flag for case-by-case ID/pharmacy
                                       review, not auto-added

STEP 4 — Renal/hepatic dose adjustment
  Uses existing creatinine field already captured for SOFA.

STEP 5 — Output
  Proposal + rationale citing which risk factor triggered which modifier.
  Physician confirms/rejects each modifier individually — not an
  all-or-nothing regimen approval.
```

De-escalation logic (post-culture) is a separate code path: compares
organism/sensitivity result to the active regimen, proposes narrowing when
appropriate, and raises an immediate high-priority alert if the organism is
resistant to what was empirically started. Standard re-assessment window:
48–72 hours.

### 4.3 Guideline Surveillance Agent (Agent 3)

```
External guideline sources (SCCM, IDSA — pre-approved sources only)
        │
        ▼
Guideline Surveillance Agent (scheduled, e.g. weekly)
        │
        ▼
Compares to current Antibiotic Knowledge Base
        │
        ▼
   Change detected? ── no ──► nothing happens
        │ yes
        ▼
Alert to Clinical Lead (Sarah) — NOT the treating physician
        │
        ▼
Clinical Lead reviews, approves or edits
        │
        ▼
Antibiotic Knowledge Base updated (versioned, timestamped)
```

**Decision: Option B — non-blocking updates.** While a guideline change is
pending review, the system continues serving the current (older) knowledge
base version rather than blocking. This prioritizes clinical continuity over
being maximally current. Rationale: a system that stops recommending
antibiotics because a review is pending is worse than one using a slightly
outdated but validated guideline.

**Open items this decision requires before implementation:**
- SLA for reviewing a pending alert (proposed default: 5 business days —
  confirm final value).
- What happens if the SLA is missed — reminder escalation, or does it stay
  pending indefinitely? (needs a decision)
- Pending alerts must be visible in a persistent list/dashboard, not a
  transient notification that can be missed.
- Knowledge base versioning: every approved update needs a timestamp/version
  so a later audit can identify which guideline version a given case was
  treated under.
- Handling of multiple simultaneous pending updates — reviewed individually
  or batched (needs a decision, expected to be rare).

---

## 5. Consequences

**Positive:**
- Antibiotic logic can be built, tested, and iterated independently of
  SOFA/Bundle logic.
- A model change for Agent 2 doesn't require touching Agent 1.
- Guideline currency is handled without ever letting an automated process
  change patient-facing recommendations without human review.
- Audit trail supports full reconstruction of a case's decision history.

**Costs / trade-offs accepted:**
- More moving parts than a single-agent design: three system prompts, two
  knowledge bases (antibiotic KB + antibiogram data), and an orchestration
  layer that must handle partial failure.
- Requires a background job scheduler for Agent 3 (new infrastructure
  component if not already present).
- Requires a review dashboard/queue for pending guideline changes (new UI
  surface).

---

## 6. Follow-up work (not yet designed)

- [ ] Request/response schema between Agent 1 and Agent 2
- [ ] Agent 2 system prompt + full knowledge base structure
- [ ] Agent 3 comparison logic (how "change" is detected against the current KB)
- [ ] FMEA additions for: wrong dose at renal impairment, ignored documented
      allergy, missed SLA on pending guideline review, antibiogram drift
- [ ] SLA value and escalation policy (open item, needs a decision)
- [ ] Knowledge base versioning scheme

---

## 7. References

- Surviving Sepsis Campaign guidance on empirical antibiotic timing, MDR/MRSA/
  anaerobic/fungal coverage decisions (research notes captured 2026-08-19)
- `sofa_calculator.py` — existing deterministic SOFA implementation, precedent
  for the "AI proposes, physician decides" separation of deterministic
  computation from LLM narration
- Consensus AI platform design (Router → Specialists → Priority AI →
  Synthesis) — architectural precedent within Shura for this pattern
