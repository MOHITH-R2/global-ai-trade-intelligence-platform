from __future__ import annotations

import os
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor

MODEL_VERSION = "2026.05-domain-risk-v2"
MODEL_PATH = os.path.join(os.path.dirname(__file__), "risk_model.joblib")
RANDOM_SEED = 42

FEATURE_COLUMNS = [
    "port_congestion",
    "route_danger",
    "weather_impact",
    "delay_probability",
    "cargo_importance",
    "geopolitical_risk",
]

FEATURE_LABELS = {
    "port_congestion": "Port congestion",
    "route_danger": "Route danger",
    "weather_impact": "Weather impact",
    "delay_probability": "Delay probability",
    "cargo_importance": "Cargo priority",
    "geopolitical_risk": "Geopolitical risk",
}

FEATURE_WEIGHTS = {
    "route_danger": 0.24,
    "geopolitical_risk": 0.19,
    "weather_impact": 0.17,
    "port_congestion": 0.16,
    "delay_probability": 0.15,
    "cargo_importance": 0.09,
}

PORT_PRESSURE = {
    "Shanghai": 6.4,
    "Singapore": 6.8,
    "Rotterdam": 5.9,
    "Los Angeles": 5.5,
    "Dubai": 5.7,
}

LANE_EXPOSURE = {
    ("Singapore", "Rotterdam"): 1.2,
    ("Los Angeles", "Dubai"): 1.0,
    ("Dubai", "Shanghai"): 1.5,
}

_model: GradientBoostingRegressor | None = None


def _clamp_score(value: float, minimum: float = 0.0, maximum: float = 10.0) -> float:
    return float(max(minimum, min(maximum, value)))


def _value(source: Any, key: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _route_name(route: Any) -> str:
    origin = _value(route, "origin_port", "Unknown")
    destination = _value(route, "destination_port", "Unknown")
    return f"{origin} to {destination}"


def _coerce_factor_values(factors: dict[str, Any]) -> dict[str, float]:
    raw_values = [float(factors.get(column, 0.0) or 0.0) for column in FEATURE_COLUMNS]
    scale = 10.0 if raw_values and max(abs(value) for value in raw_values) <= 1.0 else 1.0
    return {
        column: _clamp_score(float(factors.get(column, 0.0) or 0.0) * scale)
        for column in FEATURE_COLUMNS
    }


def _domain_target(data: pd.DataFrame) -> pd.Series:
    base_score = sum(data[column] * weight for column, weight in FEATURE_WEIGHTS.items())
    route_geo_interaction = (data["route_danger"] * data["geopolitical_risk"]) / 10.0
    weather_delay_interaction = (data["weather_impact"] * data["delay_probability"]) / 10.0
    congestion_delay_interaction = (data["port_congestion"] * data["delay_probability"]) / 10.0
    cargo_route_interaction = (data["cargo_importance"] * data["route_danger"]) / 10.0

    target = (
        base_score
        + (route_geo_interaction * 0.11)
        + (weather_delay_interaction * 0.08)
        + (congestion_delay_interaction * 0.05)
        + (cargo_route_interaction * 0.04)
        + 0.35
    )
    return target.clip(0, 10)


def _build_sample_data(n_samples: int = 1600, random_state: np.random.RandomState | None = None) -> pd.DataFrame:
    rng = random_state or np.random.RandomState(RANDOM_SEED)
    sample_data = pd.DataFrame({
        column: rng.uniform(0, 10, n_samples)
        for column in FEATURE_COLUMNS
    })
    sample_data["risk_score"] = _domain_target(sample_data)
    return sample_data


def train_risk_model(model_path: str = MODEL_PATH, n_samples: int = 1600) -> GradientBoostingRegressor:
    sample_data = _build_sample_data(
        n_samples=n_samples,
        random_state=np.random.RandomState(RANDOM_SEED),
    )
    model = GradientBoostingRegressor(
        n_estimators=130,
        learning_rate=0.05,
        max_depth=3,
        random_state=RANDOM_SEED,
    )
    model.fit(sample_data[FEATURE_COLUMNS], sample_data["risk_score"])

    try:
        os.makedirs(os.path.dirname(model_path), exist_ok=True)
        joblib.dump({"version": MODEL_VERSION, "model": model}, model_path)
    except PermissionError:
        # Some local/demo environments keep the bundled model artifact locked.
        # The freshly trained in-memory model is still returned for this process.
        pass
    return model


def load_risk_model(model_path: str = MODEL_PATH) -> GradientBoostingRegressor:
    if os.path.exists(model_path):
        try:
            bundle = joblib.load(model_path)
            if isinstance(bundle, dict) and bundle.get("version") == MODEL_VERSION:
                return bundle["model"]
        except Exception:
            pass
    return train_risk_model(model_path=model_path)


def get_risk_model() -> GradientBoostingRegressor:
    global _model
    if _model is None:
        _model = load_risk_model()
    return _model


def calculate_risk_score_ml(factors: dict[str, Any]) -> float:
    model = get_risk_model()
    normalized_factors = _coerce_factor_values(factors)
    input_df = pd.DataFrame([normalized_factors], columns=FEATURE_COLUMNS)
    return round(_clamp_score(float(model.predict(input_df)[0])), 2)


def route_alert_pressure(route: Any, alerts: list[Any] | None = None) -> tuple[float, list[Any]]:
    if not alerts:
        return 0.0, []

    route_text = _route_name(route).lower()
    pressure = 0.0
    matched_alerts = []
    severity_weight = {"high": 2.7, "medium": 1.6, "low": 0.8}

    for alert in alerts:
        severity = str(_value(alert, "severity", "")).lower()
        title = str(_value(alert, "title", "")).lower()
        location = str(_value(alert, "location", "")).lower()
        description = str(_value(alert, "description", "")).lower()
        weight = severity_weight.get(severity, 0.5)

        directly_related = location and any(token in route_text for token in location.split())
        systemic_risk = any(
            keyword in f"{title} {description} {location}"
            for keyword in ["piracy", "weather", "storm", "geopolitical", "cyber", "strike", "sanction"]
        )

        if directly_related:
            pressure += weight
            matched_alerts.append(alert)
        elif systemic_risk:
            pressure += weight * 0.45
            matched_alerts.append(alert)

    return _clamp_score(pressure), matched_alerts[:4]


def infer_route_factors(
    route: Any,
    alerts: list[Any] | None = None,
    alert_pressure: float | None = None,
) -> dict[str, float]:
    origin = str(_value(route, "origin_port", "Unknown"))
    destination = str(_value(route, "destination_port", "Unknown"))
    base_risk = _clamp_score(float(_value(route, "risk_level", 0.0) or 0.0))
    distance = max(0.0, float(_value(route, "distance", 0.0) or 0.0))
    alert_score, _ = route_alert_pressure(route, alerts)
    alert_score = alert_pressure if alert_pressure is not None else alert_score

    port_congestion = max(
        PORT_PRESSURE.get(origin, 4.6),
        PORT_PRESSURE.get(destination, 4.6),
    )
    distance_exposure = _clamp_score((distance / 14000.0) * 10.0)
    lane_exposure = LANE_EXPOSURE.get((origin, destination), LANE_EXPOSURE.get((destination, origin), 0.0))

    return {
        "port_congestion": _clamp_score(port_congestion + (alert_score * 0.25)),
        "route_danger": _clamp_score(base_risk + lane_exposure + (alert_score * 0.35)),
        "weather_impact": _clamp_score(2.2 + (distance_exposure * 0.28) + (alert_score * 0.45)),
        "delay_probability": _clamp_score((port_congestion * 0.42) + (distance_exposure * 0.34) + (alert_score * 0.24)),
        "cargo_importance": _clamp_score(4.4 + (distance_exposure * 0.28) + (base_risk * 0.16)),
        "geopolitical_risk": _clamp_score((base_risk * 0.48) + (alert_score * 0.62) + lane_exposure),
    }


def calculate_risk_score_rule_based(route: Any, factors: dict[str, Any] | None = None) -> float:
    normalized_factors = _coerce_factor_values(factors or infer_route_factors(route))
    base_risk = _clamp_score(float(_value(route, "risk_level", normalized_factors["route_danger"]) or 0.0))
    weighted_factor_score = sum(
        normalized_factors[column] * weight
        for column, weight in FEATURE_WEIGHTS.items()
    )
    interaction_boost = (
        normalized_factors["route_danger"] * normalized_factors["geopolitical_risk"] * 0.012
        + normalized_factors["weather_impact"] * normalized_factors["delay_probability"] * 0.008
    )
    return round(_clamp_score((base_risk * 0.34) + (weighted_factor_score * 0.58) + interaction_boost), 2)


def _risk_band(score: float) -> str:
    if score >= 8:
        return "Critical"
    if score >= 7:
        return "High"
    if score >= 5:
        return "Elevated"
    if score >= 4:
        return "Guarded"
    return "Stable"


def _decision_for_score(score: float) -> str:
    if score >= 8:
        return "Hold or reroute immediately"
    if score >= 7:
        return "Escalate before departure"
    if score >= 5:
        return "Proceed with controls"
    if score >= 4:
        return "Monitor closely"
    return "Proceed normally"


def _action_for_score(route_name: str, score: float, top_driver: str) -> str:
    if score >= 8:
        return f"Pause {route_name}, build an alternate routing option, and escalate to command."
    if score >= 7:
        return f"Escalate {route_name}, verify live alerts, and prepare a reroute threshold."
    if "Weather" in top_driver:
        return f"Keep {route_name} active with weather checks and a delayed-departure trigger."
    if "Port" in top_driver or "Delay" in top_driver:
        return f"Keep {route_name} active, add berth-delay buffer, and monitor terminal congestion."
    if score >= 5:
        return f"Proceed on {route_name} with tighter tracking and a contingency checkpoint."
    if score >= 4:
        return f"Monitor {route_name} for alert changes before releasing the next leg."
    return f"Proceed on {route_name} with standard monitoring."


def _driver_rows(factors: dict[str, float]) -> list[dict[str, Any]]:
    rows = []
    for column in FEATURE_COLUMNS:
        rows.append({
            "factor": column,
            "label": FEATURE_LABELS[column],
            "score": round(factors[column], 2),
            "contribution": round(factors[column] * FEATURE_WEIGHTS[column], 2),
        })
    return sorted(rows, key=lambda row: row["contribution"], reverse=True)


def _confidence(score: float, matched_alerts: list[Any], factors: dict[str, float]) -> float:
    factor_signal = max(factors.values()) - min(factors.values())
    alert_signal = min(12.0, len(matched_alerts) * 3.0)
    confidence = 64.0 + (score * 1.9) + alert_signal + min(10.0, factor_signal)
    return round(_clamp_score(confidence, 55.0, 96.0), 1)


def assess_route_risk(
    route: Any,
    alerts: list[Any] | None = None,
    factors: dict[str, Any] | None = None,
    alert_pressure: float | None = None,
    live_modifier: float = 0.0,
) -> dict[str, Any]:
    if factors is None:
        factors = infer_route_factors(route, alerts=alerts, alert_pressure=alert_pressure)
    normalized_factors = _coerce_factor_values(factors)
    matched_alert_pressure, matched_alerts = route_alert_pressure(route, alerts)
    ml_score = calculate_risk_score_ml(normalized_factors)
    rule_score = calculate_risk_score_rule_based(route, normalized_factors)
    final_score = round(_clamp_score((ml_score * 0.58) + (rule_score * 0.42) + live_modifier), 2)
    drivers = _driver_rows(normalized_factors)
    top_driver = drivers[0]["label"] if drivers else "Route baseline"
    route_name = _route_name(route)

    return {
        "route": route_name,
        "score": final_score,
        "band": _risk_band(final_score),
        "confidence": _confidence(final_score, matched_alerts, normalized_factors),
        "decision": _decision_for_score(final_score),
        "action": _action_for_score(route_name, final_score, top_driver),
        "top_drivers": drivers[:3],
        "factors": {column: round(value, 2) for column, value in normalized_factors.items()},
        "ml_score": ml_score,
        "rule_score": rule_score,
        "alert_pressure": round(alert_pressure if alert_pressure is not None else matched_alert_pressure, 2),
        "matched_alerts": [
            {
                "title": _value(alert, "title", "Alert"),
                "severity": _value(alert, "severity", "unknown"),
                "location": _value(alert, "location", "unknown"),
            }
            for alert in matched_alerts
        ],
        "explanation": (
            f"{route_name} is {_risk_band(final_score).lower()} because "
            f"{top_driver.lower()} is the strongest driver. "
            f"Model score {ml_score:.1f}, rule score {rule_score:.1f}, "
            f"confidence {_confidence(final_score, matched_alerts, normalized_factors):.1f}%."
        ),
    }


def build_route_assessments(routes: list[Any], alerts: list[Any] | None = None) -> list[dict[str, Any]]:
    assessments = [assess_route_risk(route, alerts=alerts) for route in routes]
    return sorted(assessments, key=lambda item: item["score"], reverse=True)


def calculate_risk_score(route: Any) -> float:
    return float(assess_route_risk(route)["score"])
