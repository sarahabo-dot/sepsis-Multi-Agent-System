from governance_policy import PolicyAction, evaluate_findings, rule_for_finding


def test_known_block_rule():
    action, rules = evaluate_findings(["dose_mismatch:2 g:expected=4.5 g"], [])
    assert action == PolicyAction.BLOCK
    assert rules[0].rule_id == "GOV-006"


def test_known_warning_rule():
    action, rules = evaluate_findings([], ["empty_rationale"])
    assert action == PolicyAction.WARNING
    assert rules[0].rule_id == "GOV-020"


def test_mixed_warning_and_block_is_block():
    action, _ = evaluate_findings(["case_id_mismatch"], ["empty_rationale"])
    assert action == PolicyAction.BLOCK


def test_unknown_finding_fails_closed():
    action, rules = evaluate_findings(["future_safety_condition"], [])
    assert action == PolicyAction.BLOCK
    assert rules[0].rule_id == "GOV-UNKNOWN"


def test_parameterized_findings_resolve_by_prefix():
    rule = rule_for_finding("kb_version_mismatch:response=kb-v0:active=kb-v1")
    assert rule is not None
    assert rule.rule_id == "GOV-004"
