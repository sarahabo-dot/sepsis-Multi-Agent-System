"""Deterministic SOFA calculator used by the five-agent architecture.
Clinical values are expected in the units documented by the caller.
Missing domains are reported rather than guessed.
"""
from dataclasses import dataclass
from typing import Optional

@dataclass
class ClinicalValue:
    value: Optional[float]
    unit: str = ""
    source: str = ""
    timestamp: object = None

@dataclass
class PressorState:
    drug: str = "none"
    dose_mcg_kg_min: Optional[float] = None

@dataclass
class SofaInput:
    pao2_fio2: Optional[ClinicalValue] = None
    platelets: Optional[ClinicalValue] = None
    bilirubin: Optional[ClinicalValue] = None
    map_mmhg: Optional[ClinicalValue] = None
    pressor: Optional[PressorState] = None
    gcs: Optional[ClinicalValue] = None
    creatinine: Optional[ClinicalValue] = None
    urine_output_24h: Optional[ClinicalValue] = None

@dataclass
class SofaResult:
    total: int
    components: dict
    completeness: float
    missing_domains: list[str]


def _v(x):
    return None if x is None else x.value


def _resp(pf):
    if pf is None: return None
    if pf >= 400: return 0
    if pf >= 300: return 1
    if pf >= 200: return 2
    if pf >= 100: return 3
    return 4


def _coag(p):
    if p is None: return None
    if p >= 150: return 0
    if p >= 100: return 1
    if p >= 50: return 2
    if p >= 20: return 3
    return 4


def _liver(b):
    if b is None: return None
    if b < 1.2: return 0
    if b < 2.0: return 1
    if b < 6.0: return 2
    if b < 12.0: return 3
    return 4


def _cardio(map_mmhg, pressor):
    drug = (pressor.drug if pressor else "none").lower()
    dose = pressor.dose_mcg_kg_min if pressor else None
    if drug in ("none", "") or dose is None:
        return None if map_mmhg is None else (0 if map_mmhg >= 70 else 1)
    if drug in ("dopamine", "dobutamine"):
        if drug == "dobutamine": return 2
        if dose <= 5: return 2
        if dose <= 15: return 3
        return 4
    if drug in ("epinephrine", "norepinephrine"):
        if dose <= 0.1: return 3
        return 4
    return 4


def _cns(gcs):
    if gcs is None: return None
    if gcs >= 15: return 0
    if gcs >= 13: return 1
    if gcs >= 10: return 2
    if gcs >= 6: return 3
    return 4


def _renal(cr, urine):
    if cr is None and urine is None: return None
    score = 0
    if cr is not None:
        if cr < 1.2: score = 0
        elif cr < 2.0: score = 1
        elif cr < 3.5: score = 2
        elif cr < 5.0: score = 3
        else: score = 4
    if urine is not None:
        if urine < 200: score = max(score, 4)
        elif urine < 500: score = max(score, 3)
    return score


def calculate_sofa(inp: SofaInput) -> SofaResult:
    vals = {
        "respiratory": _resp(_v(inp.pao2_fio2)),
        "coagulation": _coag(_v(inp.platelets)),
        "liver": _liver(_v(inp.bilirubin)),
        "cardiovascular": _cardio(_v(inp.map_mmhg), inp.pressor),
        "cns": _cns(_v(inp.gcs)),
        "renal": _renal(_v(inp.creatinine), _v(inp.urine_output_24h)),
    }
    missing = [k for k, v in vals.items() if v is None]
    total = sum(v for v in vals.values() if v is not None)
    return SofaResult(total=total, components=vals, completeness=(6-len(missing))/6, missing_domains=missing)
