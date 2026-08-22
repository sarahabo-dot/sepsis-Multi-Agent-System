# Integration patch: urine output — explicit mL/kg/hr vs mL/24h

Fixes the original bug: a single ambiguous "urine output" field let a
15 mL/hr rate get silently treated as a 15 mL/24h total. This patch makes
the unit an explicit, required choice — no field is ever ambiguous.

Also resolves the `weight_kg` gap flagged in the antibiotic integration
patch: weight is now captured once, on the SOFA form, and reused by the
antibiotic endpoint — no more asking the physician to enter it twice.

---

## Step 1 — Add a small conversion helper

New file, same directory as `sofa_calculator.py`:

```python
# urine_output_conversion.py
"""
Converts urine output input into the 24h total that score_renal() expects.
Two input modes, chosen explicitly by the physician — never inferred:

  - "ml_24h":   a measured cumulative 24h total. Used as-is.
  - "ml_kg_hr": a rate (mL/kg/hr), projected to a 24h total via
                rate x weight_kg x 24. This is an ESTIMATE, not a
                confirmed measurement — the projection note makes that
                explicit so it can be surfaced in the UI/interpretation
                rather than presented as equivalent to a real 24h total.

Per the discussion that led to this fix: a short observation window (e.g.
1-2h) projected to 24h is less reliable than an actual 24h collection.
This module does the arithmetic; it does not judge reliability — that
judgment belongs to the physician and to whatever narrates the SOFA result
(the /interpretation endpoint mentioning "projected" data is a reasonable
next step, not implemented in this module).
"""

from typing import Optional, Literal, Tuple

UrineOutputUnit = Literal["ml_24h", "ml_kg_hr"]


def convert_urine_output_to_24h(
    value: Optional[float],
    unit: Optional[UrineOutputUnit],
    weight_kg: Optional[float],
) -> Tuple[Optional[float], Optional[str]]:
    """Returns (value_in_ml_per_24h, note). `note` is None only when the
    value was a direct, already-24h measurement — every projected value
    carries an explicit note so it's never silently treated as confirmed.
    """
    if value is None:
        return None, None

    if unit is None or unit == "ml_24h":
        return value, None

    if unit == "ml_kg_hr":
        if weight_kg is None:
            return None, "urine_output_ml_kg_hr_provided_without_weight_kg"
        if weight_kg <= 0:
            return None, f"invalid_weight_kg:{weight_kg}"
        projected = value * weight_kg * 24
        note = (
            f"projected: {value} mL/kg/hr x {weight_kg} kg x 24h = {projected:.0f} mL. "
            "This is an extrapolation from a rate, not a confirmed 24h collection."
        )
        return projected, note

    return None, f"unknown_urine_output_unit:{unit}"
```

---

## Step 2 — Extend `SofaRequest` in api/main.py

Replace the single `urine_output_24h` field with the explicit two-option
version, and add `weight_kg` (also resolves the gap noted in the
antibiotic patch — captured once here, reused by `/antibiotic/recommend`):

```python
class SofaRequest(BaseModel):
    patient_id: str
    pao2_fio2: Optional[float] = None
    platelets: Optional[float] = None
    bilirubin: Optional[float] = None
    map_mmhg: Optional[float] = None
    pressor_drug: str = "none"
    pressor_dose: Optional[float] = None
    gcs: Optional[float] = None
    creatinine: Optional[float] = None
    weight_kg: Optional[float] = None

    # Urine output — two explicit modes, chosen by the physician.
    # No default that silently assumes one unit over the other.
    urine_output_value: Optional[float] = None
    urine_output_unit: Optional[str] = None  # "ml_24h" | "ml_kg_hr"
```

Add the import near the top:

```python
from urine_output_conversion import convert_urine_output_to_24h
```

---

## Step 3 — Use the conversion in `sofa_calculate`

Inside `sofa_calculate`, before the `raw = {...}` dict is built, add:

```python
    # Persist weight once, reused by /antibiotic/recommend later — see
    # last_confirmed_value(db, session.id, "weight_kg") in that endpoint.
    if req.weight_kg is not None:
        db.add(ClinicalValueRecord(
            session_id=session.id, domain="weight_kg", value=req.weight_kg, unit="kg",
            source=user.username, status=DataStatus.CONFIRMED.value, flag_reason=None,
            timestamp=now,
        ))
        db.commit()

    effective_weight = req.weight_kg or last_confirmed_value(db, session.id, "weight_kg")
    urine_output_24h, urine_output_note = convert_urine_output_to_24h(
        req.urine_output_value, req.urine_output_unit, effective_weight,
    )
```

Then change the `raw = {...}` dict's urine output line from the old
`req.urine_output_24h` to the newly computed value:

```python
    raw = {
        "pao2_fio2": req.pao2_fio2, "platelets": req.platelets, "bilirubin": req.bilirubin,
        "map_mmhg": req.map_mmhg, "gcs": req.gcs, "creatinine": req.creatinine,
        "urine_output_24h": urine_output_24h,
    }
```

---

## Step 4 — Surface the conversion note in the response

In the `return {...}` at the end of `sofa_calculate`, add one field:

```python
    return {
        "total": result.total, "components": result.components,
        "completeness": result.completeness, "missing_domains": result.missing_domains,
        "baseline": session.baseline_sofa, "delta_from_baseline": delta,
        "meets_sepsis3_criteria": sepsis3, "draft_flags": draft_flags,
        "urine_output_note": urine_output_note,  # None if a direct 24h value was given
    }
```

This is what should be shown next to the renal SOFA component in the UI
whenever it's not `None` — e.g. a small "(projected)" label.

---

## Step 5 — Also update the audit record

In `record_audit(db, user.username, "sofa_calculated", {...})`, add the
note so it's traceable later:

```python
    record_audit(db, user.username, "sofa_calculated", {
        "patient_id": req.patient_id, "total": result.total, "draft_flags": draft_flags,
        "urine_output_note": urine_output_note,
    })
```

---

## Frontend: the two-option input

```jsx
// UrineOutputInput.jsx — matches the existing "PATIENT VALUES" panel style
import { useState } from "react";

const styles = {
  wrap: { marginBottom: "4px" },
  label: {
    fontSize: "12px", color: "#5eead4", textTransform: "uppercase",
    letterSpacing: "0.05em", marginBottom: "6px", display: "block",
  },
  row: { display: "flex", gap: "8px" },
  input: {
    flex: 1, background: "#0a0e1a", border: "1px solid #1e2536",
    borderRadius: "6px", padding: "8px 10px", color: "#e2e8f0", fontSize: "14px",
  },
  unitToggle: { display: "flex", border: "1px solid #1e2536", borderRadius: "6px", overflow: "hidden" },
  unitButton: (active) => ({
    padding: "8px 10px", fontSize: "12px", cursor: "pointer",
    background: active ? "#0c1f1a" : "transparent",
    color: active ? "#5eead4" : "#64748b",
    border: "none",
  }),
  note: { fontSize: "11px", color: "#fbbf24", marginTop: "6px" },
};

export default function UrineOutputInput({ value, unit, onChange, weightKg }) {
  const [localUnit, setLocalUnit] = useState(unit || "ml_24h");

  function handleUnitChange(newUnit) {
    setLocalUnit(newUnit);
    onChange({ value, unit: newUnit });
  }

  function handleValueChange(e) {
    onChange({ value: e.target.value === "" ? null : parseFloat(e.target.value), unit: localUnit });
  }

  const showWeightWarning = localUnit === "ml_kg_hr" && !weightKg;

  return (
    <div style={styles.wrap}>
      <label style={styles.label}>Urine output</label>
      <div style={styles.row}>
        <input
          type="number"
          style={styles.input}
          value={value ?? ""}
          onChange={handleValueChange}
          placeholder={localUnit === "ml_24h" ? "e.g. 900" : "e.g. 0.4"}
        />
        <div style={styles.unitToggle}>
          <button
            type="button"
            style={styles.unitButton(localUnit === "ml_24h")}
            onClick={() => handleUnitChange("ml_24h")}
          >
            mL/24h
          </button>
          <button
            type="button"
            style={styles.unitButton(localUnit === "ml_kg_hr")}
            onClick={() => handleUnitChange("ml_kg_hr")}
          >
            mL/kg/hr
          </button>
        </div>
      </div>
      {showWeightWarning && (
        <div style={styles.note}>Weight required to convert mL/kg/hr — enter weight above first.</div>
      )}
    </div>
  );
}
```

Parent form sends `urine_output_value` and `urine_output_unit` (matching
the new `SofaRequest` fields) instead of the old single `urine_output_24h`.

---

## Why two explicit buttons instead of a smarter auto-detect

A physician typing "15" with no unit visible is exactly how the original
bug happened. Forcing an explicit unit choice — visible, not a placeholder
hint — removes the ambiguity at the source rather than trying to guess
intent from the number's magnitude (which is unreliable: 15 could be a
very low mL/kg/hr rate for a large patient, or a very low mL/24h total).
