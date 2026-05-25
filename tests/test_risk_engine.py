from ml.risk_engine import (
    FEATURE_COLUMNS,
    assess_route_risk,
    build_route_assessments,
    calculate_risk_score,
    calculate_risk_score_ml,
)


class DummyRoute:
    origin_port = "Dubai"
    destination_port = "Shanghai"
    risk_level = 4.0
    distance = 6000


class HighRiskRoute:
    origin_port = "Singapore"
    destination_port = "Rotterdam"
    risk_level = 7.2
    distance = 10000


def test_calculate_risk_score_returns_float():
    value = calculate_risk_score(DummyRoute())
    assert isinstance(value, float)
    assert value >= 0.0
    assert value <= 10.0


def test_calculate_risk_score_ml_accepts_valid_factors():
    factors = {key: 0.5 for key in FEATURE_COLUMNS}
    score = calculate_risk_score_ml(factors)
    assert isinstance(score, float)
    assert score >= 0.0
    assert score <= 10.0


def test_route_assessment_is_explainable_and_deterministic():
    first = assess_route_risk(DummyRoute())
    second = assess_route_risk(DummyRoute())

    assert first["score"] == second["score"]
    assert first["decision"]
    assert first["action"]
    assert first["confidence"] >= 55.0
    assert len(first["top_drivers"]) == 3


def test_route_assessments_are_sorted_by_score():
    assessments = build_route_assessments([DummyRoute(), HighRiskRoute()])
    assert assessments[0]["score"] >= assessments[1]["score"]
