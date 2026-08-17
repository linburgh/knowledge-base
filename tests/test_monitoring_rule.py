from app.core.services.monitoring.rule import evaluate_rule


def test_critical_threshold_fires():
    decision = evaluate_rule(
        {
            "enabled": True,
            "minimum_sample_count": 10,
            "warning_threshold": 0.8,
            "critical_threshold": 0.95,
            "recovery_threshold": 0.5,
        },
        0.98,
        10,
    )
    assert decision.action == "fire"
    assert decision.severity == "critical"


def test_insufficient_samples_are_ignored():
    decision = evaluate_rule({"minimum_sample_count": 10, "warning_threshold": 0.8}, 0.99, 2)
    assert decision.action == "ignore"
    assert decision.reason == "insufficient_sample"


def test_recovery_is_returned_when_value_is_safe():
    decision = evaluate_rule(
        {"warning_threshold": 0.8, "recovery_threshold": 0.5}, 0.3, 20
    )
    assert decision.action == "recover"


def test_disabled_rule_does_not_trigger():
    decision = evaluate_rule({"enabled": False, "warning_threshold": 0.1}, 1, 100)
    assert decision.action == "ignore"
    assert decision.reason == "rule_disabled"
