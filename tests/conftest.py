import datetime
import hashlib
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE_PATH = ROOT / ".runtime" / "pytest_trade_intelligence.db"
TEST_DATABASE_PATH.parent.mkdir(exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DATABASE_PATH.as_posix()}"

from database.connection import SessionLocal, engine  # noqa: E402
from database.models import (  # noqa: E402
    AIAction,
    AISPositionHistory,
    AuditLog,
    Base,
    CargoManifest,
    GeneratedReport,
    IncidentEvent,
    RiskLog,
    ThreatAlert,
    TradeRoute,
    UserAccount,
    Vessel,
)


TEST_ROUTES = [
    ("Singapore", "Rotterdam", 7.2, 10000.0),
    ("Dubai", "Shanghai", 6.8, 6000.0),
    ("Los Angeles", "Dubai", 6.1, 13000.0),
    ("Rotterdam", "Los Angeles", 5.4, 9000.0),
    ("Shanghai", "Singapore", 4.2, 3000.0),
]

TEST_VESSELS = [
    ("MV Aurora", 1.12, 103.55, "active"),
    ("MV Meridian", 25.2, 55.15, "active"),
    ("MV Pacific Star", 33.7, -118.2, "active"),
    ("MV Rotterdam Gate", 51.92, 4.48, "docked"),
    ("MV South China", 22.6, 114.0, "active"),
]

TEST_ALERTS = [
    ("Piracy Alert", "Increased piracy risk around Gulf of Aden convoy lanes.", "high", "Gulf of Aden"),
    ("Weather Warning", "Storm cell approaching Singapore and Malacca traffic.", "medium", "Singapore"),
    ("Port Congestion", "Rotterdam berth queue is delaying container arrivals.", "low", "Rotterdam"),
    ("Geopolitical Tension", "Security posture rising in South China Sea lanes.", "high", "South China Sea"),
    ("Cargo Theft Watch", "High-value cargo theft attempts reported near Los Angeles.", "medium", "Los Angeles"),
]

TEST_MANIFESTS = [
    ("MV Aurora", "MV Aurora", "Gold", "High value", 42.0, "$2.7B", "Singapore", "Rotterdam", "P1"),
    ("MV Meridian", "MV Meridian", "LNG", "Energy", 91000.0, "$118M", "Dubai", "Shanghai", "P2"),
    ("MV Pacific Star", "MV Pacific Star", "Electronics", "Priority", 12800.0, "$430M", "Los Angeles", "Dubai", "P2"),
    ("MV Rotterdam Gate", "MV Rotterdam Gate", "Medical Supplies", "Critical", 7200.0, "$210M", "Rotterdam", "Los Angeles", "P1"),
    ("MV South China", "MV South China", "Machinery", "General", 18000.0, "$65M", "Shanghai", "Singapore", "P3"),
]

DEMO_USERS = [
    ("admin@demo.app", "Command Admin", "Admin", "Admin Fingerprint", "admin-demo"),
    ("operator@demo.app", "Command Operator", "Operator", "Company SSO", "operator-demo"),
    ("public@demo.app", "Public Guest", "Public", "Email Magic Link", "public-demo"),
]


def password_digest(password: str) -> str:
    salt = os.getenv("AUTH_DEMO_SALT", "global-trade-intelligence-demo")
    return hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()


def seed_test_database():
    now = datetime.datetime.now(datetime.timezone.utc)
    db = SessionLocal()
    try:
        routes = []
        for origin, destination, risk_level, distance in TEST_ROUTES:
            route = TradeRoute(
                origin_port=origin,
                destination_port=destination,
                risk_level=risk_level,
                distance=distance,
            )
            db.add(route)
            routes.append(route)

        for name, lat, lon, status in TEST_VESSELS:
            db.add(Vessel(name=name, position_lat=lat, position_lon=lon, status=status))

        for title, description, severity, location in TEST_ALERTS:
            db.add(ThreatAlert(title=title, description=description, severity=severity, location=location))

        db.flush()

        for route_index, route in enumerate(routes):
            for day in range(4):
                db.add(
                    RiskLog(
                        route_id=route.id,
                        risk_score=max(1.0, min(10.0, route.risk_level + ((day - 1) * 0.25))),
                        timestamp=now - datetime.timedelta(days=(route_index * 2) + day),
                    )
                )

        for index, (identifier, name, _cargo, _cargo_class, _tons, _value, origin, destination, _priority) in enumerate(TEST_MANIFESTS):
            base_lat, base_lon, status = TEST_VESSELS[index][1], TEST_VESSELS[index][2], TEST_VESSELS[index][3]
            for step in range(3):
                db.add(
                    AISPositionHistory(
                        vessel_identifier=identifier,
                        vessel_name=name,
                        position_lat=base_lat + (step * 0.04),
                        position_lon=base_lon + (step * 0.05),
                        speed_knots=14.0 - step if status == "active" else 1.5,
                        heading=80.0 + (step * 12),
                        nearest_port=origin if step < 2 else destination,
                        source="pytest seed",
                        status=status,
                        timestamp=now - datetime.timedelta(minutes=(index * 7) + (step * 5)),
                    )
                )

        for identifier, name, cargo, cargo_class, tons, value, origin, destination, priority in TEST_MANIFESTS:
            db.add(
                CargoManifest(
                    vessel_identifier=identifier,
                    vessel_name=name,
                    cargo=cargo,
                    cargo_class=cargo_class,
                    cargo_tons=tons,
                    cargo_value=value,
                    origin_port=origin,
                    destination_port=destination,
                    priority=priority,
                    status="active",
                    updated_at=now - datetime.timedelta(minutes=3),
                )
            )

        db.add_all(
            [
                AIAction(
                    priority="P1",
                    subject="Singapore to Rotterdam",
                    action_type="Route release",
                    recommendation="Hold P1 cargo until piracy corridor controls are confirmed.",
                    evidence="High-severity piracy alert and verified high-value manifest.",
                    status="queued",
                    owner="Operations lead",
                    source="pytest seed",
                    created_at=now - datetime.timedelta(minutes=30),
                    updated_at=now - datetime.timedelta(minutes=30),
                ),
                AIAction(
                    priority="P2",
                    subject="MV Pacific Star",
                    action_type="Vessel control",
                    recommendation="Confirm ETA and customer notice before Dubai arrival.",
                    evidence="Priority electronics manifest and route delay exposure.",
                    status="queued",
                    owner="Fleet controller",
                    source="pytest seed",
                    created_at=now - datetime.timedelta(minutes=24),
                    updated_at=now - datetime.timedelta(minutes=24),
                ),
            ]
        )

        db.add_all(
            [
                IncidentEvent(
                    title="Piracy Alert",
                    category="Security",
                    severity="high",
                    location="Gulf of Aden",
                    vessel_name="MV Aurora",
                    route="Singapore to Rotterdam",
                    description="Suspicious activity reported near the high-value cargo corridor.",
                    source="pytest seed",
                    status="open",
                    timestamp=now - datetime.timedelta(minutes=18),
                ),
                IncidentEvent(
                    title="Port Congestion",
                    category="Port / Delay",
                    severity="medium",
                    location="Rotterdam",
                    vessel_name="MV Rotterdam Gate",
                    route="Rotterdam to Los Angeles",
                    description="Berth queue is increasing ETA uncertainty.",
                    source="pytest seed",
                    status="investigating",
                    timestamp=now - datetime.timedelta(minutes=12),
                ),
            ]
        )

        db.add(
            GeneratedReport(
                content="Daily Maritime Command Brief\nSeed report for isolated pytest database.",
                timestamp=now - datetime.timedelta(hours=2),
            )
        )
        db.add(
            AuditLog(
                actor_role="System",
                actor_identity="pytest",
                action="test_database_seeded",
                resource="pytest database",
                severity="info",
                detail="Isolated test database seeded with routes, vessels, alerts, manifests, and history.",
                timestamp=now,
            )
        )

        for email, display_name, role, provider, password in DEMO_USERS:
            db.add(
                UserAccount(
                    email=email,
                    display_name=display_name,
                    role=role,
                    provider=provider,
                    password_hash=password_digest(password),
                    status="active",
                    created_at=now - datetime.timedelta(days=1),
                    last_login_at=None,
                )
            )

        db.commit()
    finally:
        db.close()


def reset_test_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    seed_test_database()


@pytest.fixture(autouse=True)
def isolated_test_database():
    reset_test_database()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def seeded_ids():
    db = SessionLocal()
    try:
        route = db.query(TradeRoute).order_by(TradeRoute.id).first()
        alert = db.query(ThreatAlert).order_by(ThreatAlert.id).first()
        vessel_history = db.query(AISPositionHistory).order_by(AISPositionHistory.id).first()
        assert route is not None
        assert alert is not None
        assert vessel_history is not None
        return {
            "route_id": route.id,
            "alert_id": alert.id,
            "vessel_identifier": vessel_history.vessel_identifier,
        }
    finally:
        db.close()


def pytest_sessionfinish(session, exitstatus):
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    TEST_DATABASE_PATH.unlink(missing_ok=True)
