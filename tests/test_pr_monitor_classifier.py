from pr_monitor.classifier import classify_pr


def test_classifier_tier1_contract():
    out = classify_pr("Company awarded government contract")
    assert out["tier"] == 1
    assert out["ping"] is True


def test_classifier_tier2_earnings():
    out = classify_pr("Company announces quarterly results")
    assert out["tier"] == 2
    assert out["ping"] is False


def test_classifier_tier3_other():
    out = classify_pr("Company attends conference")
    assert out["tier"] == 3
