from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from datetime import datetime

class Base(DeclarativeBase):
    pass

class Vessel(Base):
    __tablename__ = "vessels"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, index=True)
    position_lat: Mapped[float] = mapped_column(Float)
    position_lon: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String)

class TradeRoute(Base):
    __tablename__ = "trade_routes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    origin_port: Mapped[str] = mapped_column(String)
    destination_port: Mapped[str] = mapped_column(String)
    risk_level: Mapped[float] = mapped_column(Float)
    distance: Mapped[float] = mapped_column(Float)

class RiskLog(Base):
    __tablename__ = "risk_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    route_id: Mapped[int] = mapped_column(Integer, ForeignKey("trade_routes.id"))
    risk_score: Mapped[float] = mapped_column(Float)
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    route: Mapped["TradeRoute"] = relationship("TradeRoute")

class ThreatAlert(Base):
    __tablename__ = "threat_alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String)
    location: Mapped[str] = mapped_column(String)

class GeneratedReport(Base):
    __tablename__ = "generated_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    content: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime)


class AISPositionHistory(Base):
    __tablename__ = "ais_position_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    vessel_identifier: Mapped[str] = mapped_column(String, index=True)
    vessel_name: Mapped[str] = mapped_column(String, index=True)
    position_lat: Mapped[float] = mapped_column(Float)
    position_lon: Mapped[float] = mapped_column(Float)
    speed_knots: Mapped[float] = mapped_column(Float)
    heading: Mapped[float] = mapped_column(Float)
    nearest_port: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)


class CargoManifest(Base):
    __tablename__ = "cargo_manifests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    vessel_identifier: Mapped[str] = mapped_column(String, index=True)
    vessel_name: Mapped[str] = mapped_column(String, index=True)
    cargo: Mapped[str] = mapped_column(String)
    cargo_class: Mapped[str] = mapped_column(String)
    cargo_tons: Mapped[float] = mapped_column(Float)
    cargo_value: Mapped[str] = mapped_column(String)
    origin_port: Mapped[str] = mapped_column(String)
    destination_port: Mapped[str] = mapped_column(String)
    priority: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class AIAction(Base):
    __tablename__ = "ai_actions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    priority: Mapped[str] = mapped_column(String)
    subject: Mapped[str] = mapped_column(String, index=True)
    action_type: Mapped[str] = mapped_column(String)
    recommendation: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, index=True)
    owner: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class IncidentEvent(Base):
    __tablename__ = "incident_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String, index=True)
    category: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String)
    location: Mapped[str] = mapped_column(String)
    vessel_name: Mapped[str] = mapped_column(String)
    route: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    actor_role: Mapped[str] = mapped_column(String, index=True)
    actor_identity: Mapped[str] = mapped_column(String, index=True)
    action: Mapped[str] = mapped_column(String, index=True)
    resource: Mapped[str] = mapped_column(String, index=True)
    severity: Mapped[str] = mapped_column(String, index=True)
    detail: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)


class UserAccount(Base):
    __tablename__ = "user_accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, index=True)
    provider: Mapped[str] = mapped_column(String)
    password_hash: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
