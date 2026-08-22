"""
antibiotic_agent_schema.py
Request/response contract between the Sepsis Bundle Agent (orchestrator)
and the Antibiotic Specialist Agent (separate agent, separate model/KB).

Design principles carried over from sofa_calculator.py:
- Structured fields in, structured fields out. The LLM narration layer
  explains the `rationale` field; it never invents the regimen itself.
- Every modifier (MDR/MRSA/anaerobic/fungal) is reported independently so
  the physician can confirm or reject each one separately, not the whole
  regimen as a block.
- Missing/unknown inputs are represented explicitly (None), never guessed.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    SEPSIS = "sepsis"
    SEPTIC_SHOCK = "septic_shock"


class SuspectedSource(str, Enum):
    URINARY = "urinary"
    RESPIRATORY = "respiratory"
    ABDOMINAL = "abdominal"
    SKIN_SOFT_TISSUE = "skin_soft_tissue"
    CNS = "cns"
    BLOODSTREAM_UNKNOWN = "bloodstream_unknown"
    OTHER = "other"
    UNDIFFERENTIATED = "undifferentiated"  # source not yet identified


class RequestType(str, Enum):
    EMPIRICAL = "empirical"          # no culture result yet
    DEESCALATION = "deescalation"    # culture/sensitivity available


class ModifierType(str, Enum):
    MDR = "mdr"
    MRSA = "mrsa"
    ANAEROBIC = "anaerobic"
    FUNGAL = "fungal"


# ---------------------------------------------------------------------------
# Request: Sepsis Bundle Agent -> Antibiotic Specialist Agent
# ---------------------------------------------------------------------------

class RiskFactors(BaseModel):
    """Each list holds the *specific* factors present, not just a bool —
    this feeds directly into the rationale text and the audit log."""
    mdr_risk_factors: list[str] = Field(default_factory=list)
    mrsa_risk_factors: list[str] = Field(default_factory=list)
    anaerobic_risk_factors: list[str] = Field(default_factory=list)
    fungal_risk_factors: list[str] = Field(default_factory=list)


class ActiveDrug(BaseModel):
    """Used only for de-escalation requests, to describe what's already running."""
    drug_name: str
    started_at: datetime


class CultureResult(BaseModel):
    """Present only when request_type == DEESCALATION."""
    organism: str
    sensitivities: dict[str, str]  # drug_name -> "S" / "I" / "R"
    collected_at: datetime
    resulted_at: datetime


class AntibioticRequest(BaseModel):
    case_id: str  # links back to the Sepsis Bundle Agent's audit record
    request_type: RequestType

    severity: Severity
    suspected_source: SuspectedSource
    onset_timestamp: datetime  # used to compute time-to-antibiotics against target

    # Reused from the existing SOFA input — do not re-collect from the physician
    creatinine_mg_dl: Optional[float] = None
    bilirubin_mg_dl: Optional[float] = None
    weight_kg: Optional[float] = None

    risk_factors: RiskFactors = Field(default_factory=RiskFactors)
    documented_allergies: list[str] = Field(default_factory=list)

    # Only populated for DEESCALATION requests
    current_regimen: list[ActiveDrug] = Field(default_factory=list)
    culture_result: Optional[CultureResult] = None


# ---------------------------------------------------------------------------
# Response: Antibiotic Specialist Agent -> Sepsis Bundle Agent
# ---------------------------------------------------------------------------

class RegimenOption(BaseModel):
    drug_name: str
    dose: str                 # e.g. "4.5 g"
    route: str                # e.g. "IV"
    frequency: str            # e.g. "every 6h"
    renal_adjusted: bool
    renal_adjustment_note: Optional[str] = None


class AppliedModifier(BaseModel):
    """One entry per coverage decision — physician confirms/rejects each
    independently, per the ADR decision on modifier granularity."""
    modifier_type: ModifierType
    triggered_by: list[str]        # which specific risk factors caused this
    action_taken: str              # e.g. "added vancomycin for MRSA coverage"
    requires_confirmation: bool = True


class FungalFlag(BaseModel):
    """Fungal coverage is never auto-added — flagged for case-by-case
    ID/pharmacy review only, per the ADR."""
    risk_factors_present: list[str]
    recommendation: str = "case-by-case ID/pharmacy review — not auto-added"


class DeescalationAdvice(BaseModel):
    """Present only when request_type == DEESCALATION."""
    organism_covered_by_current_regimen: bool
    resistant_alert: bool          # True = highest priority, surface immediately
    narrower_regimen: Optional[list[RegimenOption]] = None
    reassessment_window_hours: int = 48


class AntibioticResponse(BaseModel):
    case_id: str
    request_type: RequestType
    knowledge_base_version: str    # ties to the versioned KB from Agent 3's updates

    timing_target_hours: int       # 1 for septic shock, 3 for sepsis without shock
    recommended_regimen: list[RegimenOption] = Field(default_factory=list)
    applied_modifiers: list[AppliedModifier] = Field(default_factory=list)
    fungal_flag: Optional[FungalFlag] = None

    deescalation: Optional[DeescalationAdvice] = None  # only for DEESCALATION requests

    warnings: list[str] = Field(default_factory=list)  # e.g. allergy conflicts
    rationale: str = ""            # LLM narration, grounded in the fields above only

    generated_at: datetime = Field(default_factory=datetime.utcnow)
    missing_inputs: list[str] = Field(default_factory=list)  # e.g. ["creatinine"]
