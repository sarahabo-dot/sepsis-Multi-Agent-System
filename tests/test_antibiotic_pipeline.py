"""
test_antibiotic_pipeline.py
Comprehensive test suite for the Antibiotic Specialist Agent pipeline.
Run with: pytest test_antibiotic_pipeline.py -v

Covers, deliberately, more than the happy path:
  - deterministic regimen selection (same input -> same output, every time)
  - renal dose adjustment at threshold boundaries
  - out-of-range / missing input handling (not silently guessed)
  - unmapped source+severity combinations
  - orchestrator failure handling (SOFA must survive antibiotic-path failure)
  - immutable versioning (publish never overwrites, rollback works)
  - license gate (fetch is blocked unless explicitly VERIFIED)
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path

import pytest

from antibiotic_agent_schema import (
    AntibioticRequest,
    RequestType,
    Severity,
    SuspectedSource,
    RiskFactors,
)
from antibiotic_rules_engine import select_regimen, _validate_creatinine
import guideline_versioning as versioning
import guideline_surveillance_agent as surveillance


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_kb():
    """A small, self-contained KB so these tests don't depend on the real
    scaffold file changing over time."""
    return {
        "version": "test-kb-1",
        "entries": [
            {
                "source": "urinary",
                "severity": "septic_shock",
                "base_regimen": [
                    {"drug_name": "Piperacillin-tazobactam", "dose": "4.5 g", "route": "IV", "frequency": "every 6h"}
                ],
                "renal_adjustment_rules": [
                    {"creatinine_gte": 1.5, "adjusted_frequency": "every 8h", "note": "renal adj 1"},
                    {"creatinine_gte": 3.0, "adjusted_frequency": "every 12h", "note": "renal adj 2"},
                ],
            },
            {
                "source": "undifferentiated",
                "severity": "septic_shock",
                "base_regimen": [
                    {"drug_name": "Meropenem", "dose": "1 g", "route": "IV", "frequency": "every 8h"}
                ],
                "renal_adjustment_rules": [],
            },
        ],
        "modifier_rules": {
            "mdr": {"action": "broaden_or_switch", "note": "switch to carbapenem"},
            "mrsa": {"action": "add", "drug_options": [{"drug_name": "Vancomycin"}]},
            "anaerobic": {"action": "add", "drug_options": [{"drug_name": "Metronidazole"}]},
            "fungal": {"action": "flag_only", "note": "case-by-case review"},
        },
    }


def make_request(**overrides) -> AntibioticRequest:
    defaults = dict(
        case_id="TEST-CASE-1",
        request_type=RequestType.EMPIRICAL,
        severity=Severity.SEPTIC_SHOCK,
        suspected_source=SuspectedSource.URINARY,
        onset_timestamp=datetime.utcnow(),
        creatinine_mg_dl=1.0,
        risk_factors=RiskFactors(),
        documented_allergies=[],
    )
    defaults.update(overrides)
    return AntibioticRequest(**defaults)


# ---------------------------------------------------------------------------
# Rules engine: determinism
# ---------------------------------------------------------------------------

def test_same_input_produces_same_output(minimal_kb):
    """Core safety property: this is a deterministic system, not a
    generative one. Running it twice must give identical results."""
    request = make_request()
    result_a = select_regimen(request, minimal_kb)
    result_b = select_regimen(request, minimal_kb)
    assert result_a == result_b


# ---------------------------------------------------------------------------
# Rules engine: renal dosing boundaries
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("creatinine,expected_frequency", [
    (1.0, "every 6h"),    # below first threshold -> no adjustment
    (1.5, "every 8h"),    # exactly at first threshold -> first rule applies
    (2.9, "every 8h"),    # between thresholds -> first rule still applies
    (3.0, "every 12h"),   # exactly at second threshold -> second rule applies
    (10.0, "every 12h"),  # well above -> highest matching rule applies
])
def test_renal_adjustment_boundaries(minimal_kb, creatinine, expected_frequency):
    request = make_request(creatinine_mg_dl=creatinine)
    regimen, _, _, missing = select_regimen(request, minimal_kb)
    assert regimen[0].frequency == expected_frequency
    assert "creatinine" not in missing


def test_creatinine_out_of_range_is_flagged_not_used(minimal_kb):
    """A creatinine of 250 mg/dL is not a real value — almost certainly a
    unit error. It must be flagged, not fed into the dosing rule as-is."""
    request = make_request(creatinine_mg_dl=250.0)
    regimen, _, _, missing = select_regimen(request, minimal_kb)
    assert any("creatinine_out_of_range" in m for m in missing)
    assert regimen[0].renal_adjusted is False


def test_missing_creatinine_is_flagged(minimal_kb):
    request = make_request(creatinine_mg_dl=None)
    regimen, _, _, missing = select_regimen(request, minimal_kb)
    assert "creatinine" in missing
    assert regimen[0].renal_adjusted is False


# ---------------------------------------------------------------------------
# Rules engine: unmapped source/severity
# ---------------------------------------------------------------------------

def test_unmapped_source_falls_back_to_undifferentiated(minimal_kb):
    request = make_request(suspected_source=SuspectedSource.CNS)
    regimen, _, _, missing = select_regimen(request, minimal_kb)
    assert regimen[0].drug_name == "Meropenem"  # the undifferentiated entry
    assert any("no_kb_entry_for" in m for m in missing)


def test_no_kb_entry_at_all_is_loud_not_silent():
    """If neither the specific source nor 'undifferentiated' exists in the
    KB, the system must not return an empty regimen that looks like 'no
    antibiotics needed'. It must flag CRITICAL."""
    empty_kb = {
        "version": "empty",
        "entries": [],
        "modifier_rules": {
            "mdr": {"note": ""}, "mrsa": {"drug_options": []},
            "anaerobic": {"drug_options": []}, "fungal": {"note": ""},
        },
    }
    request = make_request()
    regimen, _, _, missing = select_regimen(request, empty_kb)
    assert regimen == []
    assert any(m.startswith("CRITICAL_") for m in missing)


# ---------------------------------------------------------------------------
# Rules engine: modifiers
# ---------------------------------------------------------------------------

def test_mdr_risk_factor_triggers_modifier(minimal_kb):
    request = make_request(risk_factors=RiskFactors(mdr_risk_factors=["prior_mdr_colonization"]))
    _, modifiers, _, _ = select_regimen(request, minimal_kb)
    assert any(m.modifier_type.value == "mdr" for m in modifiers)


def test_fungal_risk_never_auto_added_to_regimen(minimal_kb):
    """Fungal coverage must NEVER appear in recommended_regimen — only as
    a separate flag for manual ID/pharmacy review."""
    request = make_request(risk_factors=RiskFactors(fungal_risk_factors=["prolonged_broad_spectrum_use"]))
    regimen, modifiers, fungal_flag, _ = select_regimen(request, minimal_kb)
    assert fungal_flag is not None
    assert not any("fluconazole" in r.drug_name.lower() or "caspofungin" in r.drug_name.lower() for r in regimen)
    assert not any(m.modifier_type.value == "fungal" for m in modifiers)


def test_anaerobic_not_double_added_when_base_regimen_already_covers_it(minimal_kb):
    """Piperacillin-tazobactam already covers anaerobes — metronidazole
    should not be redundantly added on top of it."""
    request = make_request(
        suspected_source=SuspectedSource.URINARY,  # base regimen = pip-tazo
        risk_factors=RiskFactors(anaerobic_risk_factors=["bowel_perforation"]),
    )
    _, modifiers, _, _ = select_regimen(request, minimal_kb)
    assert not any(m.modifier_type.value == "anaerobic" for m in modifiers)


# ---------------------------------------------------------------------------
# Orchestrator: failure handling (the safety-critical property)
# ---------------------------------------------------------------------------

class DummySofaInput:
    """Stand-in for SofaInput to avoid depending on the real model import."""
    class _Val:
        def __init__(self, v): self.value = v
    def __init__(self, creatinine=1.0, bilirubin=1.0):
        self.creatinine = self._Val(creatinine)
        self.bilirubin = self._Val(bilirubin)


def test_antibiotic_failure_does_not_block_sofa(monkeypatch):
    """The single most important failure-handling property in the whole
    pipeline: if the Antibiotic Specialist Agent errors out, SOFA/Bundle
    results must still reach the physician."""
    import antibiotic_orchestrator as orch

    async def failing_agent(request):
        raise RuntimeError("simulated Antibiotic Specialist Agent outage")

    # calculate_sofa is SYNCHRONOUS in the real code (see sofa_calculator.py —
    # it's called via asyncio.to_thread, not awaited directly). The fake must
    # match that, or asyncio.to_thread ends up wrapping an unawaited
    # coroutine object, which would make the assertions below pass without
    # actually testing anything real.
    def fake_calculate_sofa(sofa_input):
        return {"total": 7, "components": {}, "completeness": 1.0, "missing_domains": []}

    monkeypatch.setattr(orch, "_call_antibiotic_agent", failing_agent)
    monkeypatch.setattr(orch, "calculate_sofa", fake_calculate_sofa)

    result = asyncio.run(orch.assess_case(
        case_id="TEST-CASE-FAILURE",
        sofa_input=DummySofaInput(),
        severity=Severity.SEPTIC_SHOCK,
        suspected_source=SuspectedSource.URINARY,
        onset_timestamp=datetime.utcnow(),
    ))

    assert result["sofa"] == {"total": 7, "components": {}, "completeness": 1.0, "missing_domains": []}
    assert result["antibiotic"] is None
    assert result["antibiotic_error"] == "antibiotic_agent_error"


def test_empty_case_id_is_rejected():
    import antibiotic_orchestrator as orch
    with pytest.raises(ValueError):
        orch.build_antibiotic_request(
            case_id="",
            sofa_input=DummySofaInput(),
            severity=Severity.SEPSIS,
            suspected_source=SuspectedSource.URINARY,
            onset_timestamp=datetime.utcnow(),
        )


# ---------------------------------------------------------------------------
# Versioning: immutability and rollback
# ---------------------------------------------------------------------------

def test_publish_never_overwrites_existing_version(tmp_path, monkeypatch):
    monkeypatch.setattr(versioning, "KB_VERSIONS_DIR", tmp_path)
    monkeypatch.setattr(versioning, "ACTIVE_POINTER_PATH", tmp_path / "active_pointer.json")

    v1 = versioning.publish_new_version({"entries": []}, version_id="test-v1")
    with pytest.raises(FileExistsError):
        versioning.publish_new_version({"entries": ["should not overwrite"]}, version_id="test-v1")

    # confirm original content is untouched
    content = versioning.load_version(v1)
    assert content["entries"] == []


def test_rollback_restores_previous_active_version(tmp_path, monkeypatch):
    monkeypatch.setattr(versioning, "KB_VERSIONS_DIR", tmp_path)
    monkeypatch.setattr(versioning, "ACTIVE_POINTER_PATH", tmp_path / "active_pointer.json")

    v1 = versioning.publish_new_version({"entries": ["v1 data"]}, version_id="v1")
    v2 = versioning.publish_new_version({"entries": ["v2 data"]}, version_id="v2")
    versioning.activate_version(v2, activated_by="tester")
    assert versioning.get_active_version_id() == "v2"

    versioning.rollback_to_version(v1, rolled_back_by="tester")
    assert versioning.get_active_version_id() == "v1"
    # v2 must still exist on disk — rollback does not delete anything
    assert "v2" in versioning.list_versions()


# ---------------------------------------------------------------------------
# License gate
# ---------------------------------------------------------------------------

def test_license_gate_blocks_unverified_source(tmp_path, monkeypatch):
    registry_path = tmp_path / "source_registry.json"
    registry_path.write_text(json.dumps({
        "sources": [{"id": "test_source", "license_status": "VERIFY_BEFORE_PRODUCTION_USE"}]
    }))
    monkeypatch.setattr(surveillance, "SOURCE_REGISTRY_PATH", registry_path)

    with pytest.raises(PermissionError):
        surveillance.check_license_gate("test_source")


def test_license_gate_allows_verified_source(tmp_path, monkeypatch):
    registry_path = tmp_path / "source_registry.json"
    registry_path.write_text(json.dumps({
        "sources": [{"id": "test_source", "license_status": "VERIFIED"}]
    }))
    monkeypatch.setattr(surveillance, "SOURCE_REGISTRY_PATH", registry_path)

    surveillance.check_license_gate("test_source")  # should not raise


def test_license_gate_unknown_source_raises(tmp_path, monkeypatch):
    registry_path = tmp_path / "source_registry.json"
    registry_path.write_text(json.dumps({"sources": []}))
    monkeypatch.setattr(surveillance, "SOURCE_REGISTRY_PATH", registry_path)

    with pytest.raises(ValueError):
        surveillance.check_license_gate("nonexistent_source")
