"""
antibiotic_rules_engine.py
Deterministic regimen selection from the knowledge base. Same philosophy as
sofa_calculator.py: fixed rules produce the regimen and modifiers; the LLM
layer (antibiotic_specialist_agent.py) only narrates what this engine
already decided. It never invents a drug, dose, or modifier on its own.
"""

from typing import Optional

import guideline_versioning as versioning
from antibiotic_agent_schema import (
    AntibioticRequest,
    RegimenOption,
    AppliedModifier,
    FungalFlag,
    ModifierType,
    CultureResult,
    DeescalationAdvice,
)


def load_knowledge_base() -> dict:
    """Reads the currently ACTIVE, approved knowledge base version.
    See guideline_versioning.py — versions are immutable and only change
    via guideline_surveillance_agent.approve_pending_review(). Run
    guideline_versioning.bootstrap_initial_version() once to register the
    scaffold antibiotic_knowledge_base.json as the first version."""
    return versioning.load_active_knowledge_base()


def _find_entry(kb: dict, source: str, severity: str) -> Optional[dict]:
    for entry in kb["entries"]:
        if entry["source"] == source and entry["severity"] == severity:
            return entry
    return None


def _apply_renal_adjustment(
    regimen: list[dict], rules: list[dict], creatinine: Optional[float]
) -> list[RegimenOption]:
    options = []
    for drug in regimen:
        adjusted = False
        note = None
        frequency = drug["frequency"]
        if creatinine is not None:
            # apply the highest-threshold rule the creatinine value satisfies
            matching = [r for r in rules if creatinine >= r["creatinine_gte"]]
            if matching:
                rule = max(matching, key=lambda r: r["creatinine_gte"])
                frequency = rule["adjusted_frequency"]
                note = rule["note"]
                adjusted = True
        options.append(RegimenOption(
            drug_name=drug["drug_name"],
            drug_class=drug.get("drug_class"),
            spectrum_rank=drug.get("spectrum_rank"),
            dose=drug["dose"],
            route=drug["route"],
            frequency=frequency,
            renal_adjusted=adjusted,
            renal_adjustment_note=note,
        ))
    return options


def _covers_anaerobes(regimen: list[dict]) -> bool:
    """Piperacillin-tazobactam and meropenem already have anaerobic activity —
    don't double-add metronidazole on top of them."""
    covered_drugs = {"piperacillin-tazobactam", "meropenem"}
    return any(d["drug_name"].lower() in covered_drugs for d in regimen)


# Sane physiological bounds for creatinine (mg/dL). Values outside this range
# are almost always a data-entry error (unit mismatch, e.g. µmol/L entered
# where mg/dL was expected) rather than a real patient value, and applying
# a renal adjustment rule to a nonsense value is worse than flagging it.
CREATININE_MIN_MG_DL = 0.1
CREATININE_MAX_MG_DL = 20.0


def _validate_creatinine(value: Optional[float]) -> tuple[Optional[float], Optional[str]]:
    """Returns (usable_value, missing_input_flag). If the value is out of
    physiological range, it is NOT used for dosing — we'd rather flag it as
    missing than silently apply a renal adjustment to a bad number."""
    if value is None:
        return None, "creatinine"
    if value < CREATININE_MIN_MG_DL or value > CREATININE_MAX_MG_DL:
        return None, f"creatinine_out_of_range:{value}"
    return value, None


def select_regimen(
    request: AntibioticRequest, kb: Optional[dict] = None
) -> tuple[list[RegimenOption], list[AppliedModifier], Optional[FungalFlag], list[str]]:
    """Returns (regimen, applied_modifiers, fungal_flag, missing_inputs).
    Deterministic — same inputs always produce the same outputs."""
    kb = kb or load_knowledge_base()
    missing_inputs = []

    entry = _find_entry(kb, request.suspected_source.value, request.severity.value)
    if entry is None:
        # Fall back to the undifferentiated/highest-severity path rather than
        # guessing — an unmapped source+severity combination must be visible,
        # not silently defaulted.
        entry = _find_entry(kb, "undifferentiated", request.severity.value)
        missing_inputs.append(f"no_kb_entry_for:{request.suspected_source.value}")
        if entry is None:
            # Both the specific lookup and the fallback failed — there is
            # NO regimen to propose. This must be loud, not an empty list
            # that looks like "no antibiotics needed".
            missing_inputs.append("CRITICAL_no_regimen_available_manual_selection_required")

    base_regimen = entry["base_regimen"] if entry else []
    renal_rules = entry["renal_adjustment_rules"] if entry else []

    validated_creatinine, creatinine_flag = _validate_creatinine(request.creatinine_mg_dl)
    if creatinine_flag:
        missing_inputs.append(creatinine_flag)

    regimen = _apply_renal_adjustment(base_regimen, renal_rules, validated_creatinine)

    modifiers: list[AppliedModifier] = []
    modifier_rules = kb["modifier_rules"]

    if request.risk_factors.mdr_risk_factors:
        modifiers.append(AppliedModifier(
            modifier_type=ModifierType.MDR,
            triggered_by=request.risk_factors.mdr_risk_factors,
            action_taken=modifier_rules["mdr"]["note"],
        ))

    if request.risk_factors.mrsa_risk_factors:
        drug_names = ", ".join(d["drug_name"] for d in modifier_rules["mrsa"]["drug_options"])
        modifiers.append(AppliedModifier(
            modifier_type=ModifierType.MRSA,
            triggered_by=request.risk_factors.mrsa_risk_factors,
            action_taken=f"added MRSA coverage option(s): {drug_names}",
        ))

    if request.risk_factors.anaerobic_risk_factors and not _covers_anaerobes(base_regimen):
        drug_names = ", ".join(d["drug_name"] for d in modifier_rules["anaerobic"]["drug_options"])
        modifiers.append(AppliedModifier(
            modifier_type=ModifierType.ANAEROBIC,
            triggered_by=request.risk_factors.anaerobic_risk_factors,
            action_taken=f"added anaerobic coverage: {drug_names}",
        ))

    fungal_flag = None
    if request.risk_factors.fungal_risk_factors:
        fungal_flag = FungalFlag(
            risk_factors_present=request.risk_factors.fungal_risk_factors,
        )

    return regimen, modifiers, fungal_flag, missing_inputs


# ---------------------------------------------------------------------------
# De-escalation: empirical regimen -> culture-guided narrower regimen.
# Deterministic — the LLM narration layer only explains this, never decides it.
# ---------------------------------------------------------------------------

REASSESSMENT_WINDOW_HOURS = 48  # empirical regimen without a culture result yet


def _drug_catalog(kb: dict) -> dict[str, dict]:
    """Every drug the KB knows about (base regimens + modifier options),
    deduplicated by lowercased name. Used to look up spectrum_rank/drug_class
    for any drug shown as susceptible in a culture result, even if it wasn't
    part of this case's original empirical regimen."""
    catalog: dict[str, dict] = {}
    for entry in kb["entries"]:
        for d in entry["base_regimen"]:
            catalog.setdefault(d["drug_name"].lower(), d)
    for mod in kb["modifier_rules"].values():
        for d in mod.get("drug_options", []):
            catalog.setdefault(d["drug_name"].lower(), d)
    return catalog


def evaluate_deescalation(
    request: AntibioticRequest, kb: Optional[dict] = None
) -> DeescalationAdvice:
    """Deterministic de-escalation decision from a culture result.

    Priority, in order:
    1. If NO current regimen drug shows S/I against the organism, this is a
       resistant_alert — none of what's running works. Highest priority,
       surfaced regardless of anything else.
    2. Otherwise, if the narrowest-spectrum drug among all S-rated options
       (by KB spectrum_rank, excluding documented allergies) is narrower
       than every drug in the current regimen, propose it as narrower_regimen.
    3. Otherwise, current regimen already is (or is as narrow as) an
       appropriate covering choice — no change proposed.
    """
    kb = kb or load_knowledge_base()
    culture: Optional[CultureResult] = request.culture_result
    if culture is None:
        # Nothing to de-escalate against yet.
        return DeescalationAdvice(
            organism_covered_by_current_regimen=False,
            resistant_alert=False,
            narrower_regimen=None,
            reassessment_window_hours=REASSESSMENT_WINDOW_HOURS,
        )

    catalog = _drug_catalog(kb)
    current_names = {d.drug_name.lower() for d in request.current_regimen}
    allergy_names = {a.lower() for a in request.documented_allergies}
    # Culture sensitivities come in with whatever casing the lab report used
    # (e.g. "Piperacillin-tazobactam"); match case-insensitively against it.
    sensitivities_lower = {name.lower(): rating for name, rating in culture.sensitivities.items()}

    def sensitivity(drug_name: str) -> Optional[str]:
        return sensitivities_lower.get(drug_name.lower())

    current_ratings = {name: sensitivity(name) for name in current_names}
    organism_covered = any(r in ("S", "I") for r in current_ratings.values())
    resistant_alert = not organism_covered

    narrower_regimen = None
    if not resistant_alert:
        current_min_rank = min(
            (catalog.get(name, {}).get("spectrum_rank", 99) for name in current_names),
            default=99,
        )
        susceptible_candidates = [
            (name, rating) for name, rating in culture.sensitivities.items()
            if rating == "S" and name.lower() not in allergy_names
        ]
        ranked = sorted(
            susceptible_candidates,
            key=lambda nc: catalog.get(nc[0].lower(), {}).get("spectrum_rank", 99),
        )
        if ranked:
            best_name, _ = ranked[0]
            best_entry = catalog.get(best_name.lower())
            best_rank = best_entry.get("spectrum_rank", 99) if best_entry else 99
            if best_entry is not None and best_rank < current_min_rank:
                narrower_regimen = [RegimenOption(
                    drug_name=best_entry["drug_name"],
                    drug_class=best_entry.get("drug_class"),
                    spectrum_rank=best_entry.get("spectrum_rank"),
                    dose=best_entry["dose"],
                    route=best_entry["route"],
                    frequency=best_entry["frequency"],
                    renal_adjusted=False,
                    renal_adjustment_note=(
                        "Renal adjustment not re-evaluated for de-escalation — "
                        "confirm against current creatinine before administering."
                    ),
                )]

    return DeescalationAdvice(
        organism_covered_by_current_regimen=organism_covered,
        resistant_alert=resistant_alert,
        narrower_regimen=narrower_regimen,
        reassessment_window_hours=REASSESSMENT_WINDOW_HOURS,
    )

