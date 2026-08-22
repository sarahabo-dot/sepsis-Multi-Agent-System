"""
urine_output_conversion.py
Converts urine output input into the 24h total that score_renal() expects.
Two input modes, chosen explicitly by the physician — never inferred:

  - "ml_24h":   a measured cumulative 24h total. Used as-is.
  - "ml_kg_hr": a rate (mL/kg/hr), projected to a 24h total via
                rate x weight_kg x 24. This is an ESTIMATE, not a
                confirmed measurement — the projection note makes that
                explicit so it can be surfaced in the UI/interpretation
                rather than presented as equivalent to a real 24h total.

Fixes the original bug where a bare "15" typed into a single ambiguous
field was silently treated as a 24h total when it was actually an hourly
rate — inflating the renal SOFA component incorrectly.
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
