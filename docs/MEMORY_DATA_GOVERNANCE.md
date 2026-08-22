# Memory Agent — Data Governance

The Memory Agent is an analytics subsystem, not a fifth source of clinical
advice.

## Stored longitudinal fields

- pseudonymous patient key
- case ID
- timestamp
- sepsis severity
- suspected source
- SOFA total
- antibiotic KB version
- governance status
- antibiotic error state
- structured regimen
- warnings / missing inputs

The production adapter should also persist the existing audit event ID so a
memory record can be traced back to the original protected clinical event.

## Privacy boundary

Do not put direct identifiers into analytics tables by default. Generate a
stable pseudonymous key using a server-side secret. Keep the mapping outside
the analytics dataset and restrict access by role.

## Analytics examples

- number of sepsis cases
- septic shock proportion
- mean SOFA
- antibiotic governance BLOCK rate
- missing-input rate
- guideline version distribution
- time-to-antibiotic metrics when administration timestamps are available

No analytics result is allowed to automatically alter a patient's treatment.
