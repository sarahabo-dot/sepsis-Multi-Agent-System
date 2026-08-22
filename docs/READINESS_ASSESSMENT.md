# Antibiotic Recommendation Pipeline — Readiness Assessment

**Last updated:** 2026-08-20
**Purpose:** A precise, honest answer to "is this ready for real patients?" —
for use in conversations with reviewers, collaborators, or any external party
asking about deployment readiness. Every claim below is backed by either a
passing automated test or an explicit, named gap.

---

## Summary

**The software engineering is production-grade. The clinical content is not
yet validated. These are two separate kinds of "done," and this document
keeps them separate on purpose.**

| Layer | Status |
|---|---|
| Code architecture, error handling, failure isolation | ✅ Production-grade, tested |
| Deterministic regimen-selection logic | ✅ Production-grade, tested |
| Clinical accuracy of the knowledge base content | ❌ Scaffold only — not validated |
| Guideline currency / external source monitoring | ❌ Not implemented (license gate blocks it, intentionally) |
| Regulatory pathway | ⚠️ Not yet assessed for this feature specifically |

---

## What is verified and tested (20/20 automated tests passing)

- **Determinism.** The same patient inputs always produce the same
  recommendation. Verified by `test_same_input_produces_same_output`.
- **Renal dose adjustment applies correctly at every threshold boundary**
  (just below, exactly at, and above each creatinine cutoff). Verified by
  `test_renal_adjustment_boundaries` (5 boundary cases).
- **Out-of-range or missing input data is never silently used.** A
  creatinine value outside physiological range (e.g. a likely unit error)
  is flagged, not applied to a dosing rule. Verified by
  `test_creatinine_out_of_range_is_flagged_not_used` and
  `test_missing_creatinine_is_flagged`.
- **An unmapped source/severity combination does not silently return "no
  antibiotics needed."** It either falls back to a documented default (and
  says so) or raises a `CRITICAL_` flag if no fallback exists. Verified by
  `test_unmapped_source_falls_back_to_undifferentiated` and
  `test_no_kb_entry_at_all_is_loud_not_silent`.
- **Fungal coverage is never auto-added to a regimen** — only ever
  surfaced as a separate flag for manual ID/pharmacy review. Verified by
  `test_fungal_risk_never_auto_added_to_regimen`.
- **Anaerobic coverage is not redundantly duplicated** when the base
  regimen already has anaerobic activity. Verified by
  `test_anaerobic_not_double_added_when_base_regimen_already_covers_it`.
- **A failure in the Antibiotic Specialist Agent (Agent 2) does not block
  SOFA/Bundle results (Agent 1) from reaching the physician.** This is the
  single most safety-critical property in the pipeline. Verified by
  `test_antibiotic_failure_does_not_block_sofa`.
- **Knowledge base versions are immutable** — publishing a new version can
  never overwrite an existing one, and rollback to a prior version is
  possible without deleting anything. Verified by
  `test_publish_never_overwrites_existing_version` and
  `test_rollback_restores_previous_active_version`.
- **No external guideline source can be fetched unless its license status
  is explicitly `VERIFIED`** in `config/source_registry.json`. Verified by
  `test_license_gate_blocks_unverified_source` and related tests.

Full suite: `test_antibiotic_pipeline.py`, 20 tests, all passing as of this
document's date.

## Bugs found and fixed during this hardening pass

Documented here deliberately — a readiness assessment that only lists
strengths is not credible. These were found and corrected, not left in:

1. A hash-comparison bug in the guideline change detector would have
   flagged every single scheduled check as a change, regardless of whether
   the source content actually changed (`old_hash != new_text` instead of
   `old_hash != new_hash`).
2. A malformed AI response during guideline diff summarization would have
   crashed the surveillance job and silently lost the underlying change
   alert. Now falls back to a low-confidence manual-review flag instead.
3. A malformed or failed narration call (Claude API) would have caused the
   entire antibiotic recommendation — including the deterministic, clinically
   important regimen — to be lost. Now falls back to a templated summary
   that preserves the regimen even if the prose generation fails.

---

## What is explicitly NOT ready — and why that's by design, not an oversight

### 1. The knowledge base content (`antibiotic_knowledge_base.json`)
Every drug, dose, and interval in this file is a **scaffold placeholder**
used to validate that the pipeline's logic works correctly end-to-end. None
of it has been reviewed by a pharmacist or infectious disease physician, and
none of it has been checked against a real hospital antibiogram.

**Required before any clinical use:** Pharmacist/ID physician review of
every entry, and calibration against local resistance patterns.

### 2. Guideline source fetching (Agent 3)
`_fetch_source_topic_text()` deliberately raises `NotImplementedError`. This
is not an unfinished feature — it is a safety gate. SCCM and IDSA guideline
content is likely copyrighted, and may have been published through a
scientific journal (with separate publisher rights) rather than directly by
the society. Automated fetching must not begin until licensing terms are
confirmed with the relevant rights holder(s).

**Current state:** Both sources are marked `VERIFY_BEFORE_PRODUCTION_USE`
in `config/source_registry.json`. The license gate (`check_license_gate`)
enforces this — it is not just a note, it is a hard block, and this block
is verified by an automated test rather than being provided.

### 3. Regulatory pathway for this specific feature
The Sepsis Bundle Agent's regulatory framing (EDA Law 151/2019, shadow-mode
validation plan) was developed for the SOFA/Bundle tracking feature. Adding
an antibiotic recommendation capability is a materially different kind of
clinical decision support and has not yet been assessed against that
framework specifically. This should be revisited before any real deployment
conversation, particularly with a government entity.

### 4. Clinical validation
No shadow-mode testing, no real-case comparison against physician decisions,
no measurement of recommendation accuracy against actual outcomes. The
system has been tested for whether it behaves correctly given its own rules
— not for whether those rules are clinically correct.

---

## How to answer "is it ready?" precisely

If asked directly, the accurate answer is:

> "The system architecture is built and tested to production engineering
> standards — deterministic logic, isolated failure handling, immutable
> audit trail, and a hard licensing gate on external content. The clinical
> content inside it is a scaffold that has not yet been validated by a
> pharmacist or ID physician, and the guideline-monitoring component is
> intentionally disabled pending a licensing review. It is ready for
> continued development and shadow-mode testing — not for direct clinical
> use."

This is a stronger, more credible answer than an unqualified "yes, it's
ready" — and it is the honest one.
