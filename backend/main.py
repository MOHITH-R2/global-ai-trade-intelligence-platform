from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Request
from sqlalchemy.orm import Session
from database.connection import get_db, SessionLocal, engine
from database.models import (
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
from ml.risk_engine import assess_route_risk, build_route_assessments
from backend.aisstream_client import get_aisstream_status, get_aisstream_vessels, start_aisstream_listener
import datetime
from reports.generate_pdf import generate_pdf_report
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import logging
from pydantic import BaseModel
from dotenv import load_dotenv
import math
import random
import threading
import time
import os
import re
import hashlib
import hmac
import base64
import json
import shutil
from collections import Counter
from contextlib import asynccontextmanager

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Pydantic models
class VesselCreate(BaseModel):
    name: str
    position_lat: float
    position_lon: float
    status: str

class AlertCreate(BaseModel):
    title: str
    description: str
    severity: str
    location: str


class ReportRequest(BaseModel):
    report_type: str = "Executive Summary"
    date_range: str | None = None
    include_routes: bool = True
    include_vessels: bool = True
    include_alerts: bool = True


class ActionStatusUpdate(BaseModel):
    status: str
    owner: str | None = None


class CargoManifestUpsert(BaseModel):
    vessel_identifier: str
    vessel_name: str
    cargo: str
    cargo_class: str = "General"
    cargo_tons: float = 0
    cargo_value: str = "Unknown"
    origin_port: str = "Unknown"
    destination_port: str = "Unknown"
    priority: str | None = None
    status: str = "active"


class ScenarioRequest(BaseModel):
    scenario_type: str = "Storm Surge"
    severity: str = "high"
    location: str = "Singapore / Malacca"
    duration_hours: int = 12
    affected_route_id: int | None = None


class CopilotRequest(BaseModel):
    question: str
    role: str = "Operator"


class ProblemSolverRequest(BaseModel):
    problem: str
    topic: str = "Auto"
    role: str = "Operator"


class RuntimeSettingsUpdate(BaseModel):
    max_vessels: int | None = None
    stale_seconds: int | None = None
    region: str | None = None


class AlertWorkflowUpdate(BaseModel):
    status: str = "investigating"
    owner: str = "Operations"
    note: str | None = None


class CommandActionRequest(BaseModel):
    action: str
    target: str = "Command"
    owner: str = "Operations"
    note: str | None = None
    priority: str = "P2"
    source: str = "War Room"
    incident_id: int | None = None
    action_id: int | None = None


class IncidentStatusUpdate(BaseModel):
    status: str = "resolved"
    owner: str = "Operations"
    note: str | None = None


class AuthLoginRequest(BaseModel):
    email: str
    password: str | None = None
    role: str | None = None
    provider: str | None = None
    mfa_code: str | None = None
    biometric_ok: bool = False
    phrase: str | None = None


class AuthRegisterRequest(BaseModel):
    email: str
    display_name: str
    password: str
    role: str = "Public"
    provider: str = "Email Magic Link"
    mfa_code: str | None = None


class AuthSocialRequest(BaseModel):
    provider: str
    identity: str | None = None


class AuthSessionValidateRequest(BaseModel):
    token: str


class NotificationActionRequest(BaseModel):
    target: str
    action: str = "investigate"
    owner: str = "Operations"
    note: str | None = None
    priority: str = "P2"


class InboxActionRequest(BaseModel):
    item_type: str = "notification"
    item_id: str | None = None
    target: str = "Command"
    action: str = "assign_owner"
    owner: str = "Operations"
    note: str | None = None
    priority: str = "P2"


class AutopilotExecuteRequest(BaseModel):
    intervention_id: str
    owner: str = "Strategic Autopilot"
    note: str | None = None


class ControlTowerActionRequest(BaseModel):
    target: str
    action: str = "queue_action"
    owner: str = "Control Tower"
    note: str | None = None
    priority: str = "P2"
    action_id: int | None = None


class RiskIntelligenceActionRequest(BaseModel):
    incident_type: str = "Natural Hazard"
    target: str = "Global network"
    owner: str = "AI Risk Brain"
    note: str | None = None
    priority: str = "P2"
    action: str = "queue_playbook"
    route_id: int | None = None


class CaptainActionRequest(BaseModel):
    order: str = "queue_captain_order"
    target: str = "Global network"
    owner: str = "AI Captain"
    note: str | None = None
    priority: str | None = None
    create_incident: bool = False
    origin: str | None = None
    destination: str | None = None


class DemoResetRequest(BaseModel):
    confirm: str = ""


class ProductionModeRequest(BaseModel):
    enabled: bool = True
    confirm: str = ""


class DataMaintenanceRequest(BaseModel):
    confirm: str = ""
    compact_manifests: bool = True
    demote_inferred_live_manifests: bool = True
    complete_old_actions: bool = False
    archive_resolved_incidents: bool = False
    archive_generated_workflow: bool = False


class AuditEventCreate(BaseModel):
    action: str
    resource: str = "platform"
    severity: str = "info"
    detail: str = ""
    actor_role: str = "System"
    actor_identity: str = "Backend"


class UserAccountAdminRequest(BaseModel):
    email: str
    display_name: str | None = None
    role: str = "Operator"
    provider: str | None = None
    status: str = "active"
    password: str | None = None
    mfa_code: str | None = None
    confirm: str = ""


class NotificationDeliveryRequest(BaseModel):
    channel: str = "outbox"
    severity: str = "critical"
    target: str | None = None
    include_digest: bool = True


class DatabaseBackupRequest(BaseModel):
    confirm: str = ""


PORT_COORDS = {
    "Shanghai": (31.2304, 121.4737),
    "Singapore": (1.3521, 103.8198),
    "Rotterdam": (51.9244, 4.4777),
    "Los Angeles": (33.7182, -118.1957),
    "Dubai": (25.2048, 55.2708),
}

AIS_REGIONS = {
    "Global default lanes": "Uses the AISSTREAM_BOUNDING_BOXES value from .env or the bundled major-port boxes.",
    "Singapore / Malacca": "[[[0.7,100.8],[1.8,104.4]]]",
    "Shanghai / South China Sea": "[[[22.0,113.0],[31.8,123.8]]]",
    "Dubai / Gulf Corridor": "[[[24.0,51.0],[26.8,57.5]]]",
    "Los Angeles": "[[[32.8,-119.2],[34.3,-117.6]]]",
    "Rotterdam": "[[[50.8,2.5],[52.4,5.3]]]",
}

AUTH_PROVIDER_CATALOG = {
    "Admin Fingerprint": {
        "provider_type": "biometric_fingerprint",
        "label": "Fingerprint access",
        "login_hint": "Admin uses fingerprint access. In production this should be backed by the device biometric API through WebAuthn.",
        "external_setup": "Register admin fingerprints with a WebAuthn identity provider before deployment.",
    },
    "Company SSO": {
        "provider_type": "enterprise_sso",
        "label": "Company SSO + MFA",
        "login_hint": "Best for fleet operators and analysts who need operational access.",
        "external_setup": "Connect Okta, Azure AD, Auth0, or another OIDC/SAML provider.",
    },
    "Security Key": {
        "provider_type": "hardware_key",
        "label": "Hardware security key",
        "login_hint": "Use as a strong second factor for analyst and operator approvals.",
        "external_setup": "Enable FIDO2 security keys in the production identity provider.",
    },
    "Email Magic Link": {
        "provider_type": "low_risk_viewer",
        "label": "Email magic link",
        "login_hint": "Read-only authenticated viewing without operational controls.",
        "external_setup": "Use short-lived signed email links behind HTTPS.",
    },
    "Google OAuth": {
        "provider_type": "public_oauth",
        "label": "Continue with Google",
        "login_hint": "Public read-only login for demos, students, or external observers.",
        "external_setup": "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in production.",
    },
    "Facebook Login": {
        "provider_type": "public_oauth",
        "label": "Continue with Facebook",
        "login_hint": "Public read-only social login. Never grant operational permissions from this provider.",
        "external_setup": "Set FACEBOOK_APP_ID and FACEBOOK_APP_SECRET in production.",
    },
    "Instagram Login": {
        "provider_type": "public_oauth",
        "label": "Continue with Instagram",
        "login_hint": "Public read-only social login for app-style demo access.",
        "external_setup": "Connect Meta OAuth and keep the role capped at Public.",
    },
    "Apple Sign In": {
        "provider_type": "public_oauth",
        "label": "Continue with Apple",
        "login_hint": "Privacy-forward public or viewer login.",
        "external_setup": "Set Apple Services ID, team ID, key ID, and private key in production.",
    },
    "Discord Login": {
        "provider_type": "community_oauth",
        "label": "Continue with Discord",
        "login_hint": "Game/community-style login for public demo sessions.",
        "external_setup": "Connect Discord OAuth and map it only to public-safe roles.",
    },
    "Game Center": {
        "provider_type": "gaming_identity",
        "label": "Continue with Game Center",
        "login_hint": "Game-like identity option for demo public accounts.",
        "external_setup": "Use platform identity APIs and keep this read-only.",
    },
    "Xbox Live": {
        "provider_type": "gaming_identity",
        "label": "Continue with Xbox Live",
        "login_hint": "Gaming identity option for public demo access.",
        "external_setup": "Use Microsoft identity platform and keep this read-only.",
    },
}

AUTH_PROVIDER_ENV_REQUIREMENTS = {
    "Google OAuth": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"],
    "Facebook Login": ["FACEBOOK_APP_ID", "FACEBOOK_APP_SECRET"],
    "Instagram Login": ["INSTAGRAM_CLIENT_ID", "INSTAGRAM_CLIENT_SECRET"],
    "Apple Sign In": ["APPLE_CLIENT_ID", "APPLE_TEAM_ID", "APPLE_KEY_ID"],
    "Discord Login": ["DISCORD_CLIENT_ID", "DISCORD_CLIENT_SECRET"],
    "Game Center": ["GAME_CENTER_TEAM_ID"],
    "Xbox Live": ["MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET"],
    "Company SSO": ["OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET"],
    "Security Key": ["WEBAUTHN_RP_ID", "WEBAUTHN_ORIGIN"],
    "Admin Fingerprint": ["WEBAUTHN_RP_ID", "WEBAUTHN_ORIGIN"],
    "Email Magic Link": ["EMAIL_FROM", "EMAIL_SMTP_HOST"],
}


ROLE_SECURITY_POLICIES = {
    "Admin": {
        "permissions": [
            "approve_actions",
            "edit_cargo",
            "create_alerts",
            "generate_reports",
            "manage_vessels",
            "tune_ais",
            "manage_alert_workflows",
            "run_scenarios",
            "view_quality",
            "view_predictions",
        ],
        "landing_page": "Command Center",
        "risk": "Full command authority for settings, AIS, approvals, users, data maintenance, reports, and production controls.",
        "auth": {
            "required_level": "critical",
            "required_methods": ["password", "fingerprint/passkey confirmation", "ADMIN ACCESS phrase"],
            "allowed_providers": ["Admin Fingerprint"],
            "session_minutes": 15,
            "idle_timeout_minutes": 5,
            "step_up_for": [
                "approve_actions",
                "tune_ais",
                "manage_alert_workflows",
                "generate_reports",
            ],
            "device_policy": "Trusted device plus fingerprint/passkey challenge for every critical action.",
            "fallback": "Break-glass access should require two admins and an immutable audit record.",
        },
        "data_scope": "all_routes_all_cargo_all_settings",
    },
    "Operator": {
        "permissions": [
            "approve_actions",
            "edit_cargo",
            "create_alerts",
            "generate_reports",
            "manage_vessels",
            "manage_alert_workflows",
            "run_scenarios",
            "view_quality",
            "view_predictions",
        ],
        "landing_page": "Command Center",
        "risk": "Unified operations role for fleet, cargo, risks, alerts, scenarios, reports, and Voyage Control Tower actions.",
        "auth": {
            "required_level": "elevated",
            "required_methods": ["password", "6-digit MFA/passkey code"],
            "allowed_providers": ["Company SSO", "Security Key"],
            "session_minutes": 30,
            "idle_timeout_minutes": 10,
            "step_up_for": ["approve_actions", "edit_cargo", "create_alerts", "manage_alert_workflows", "generate_reports"],
            "device_policy": "MFA/passkey required on sign-in and any high-risk approval.",
            "fallback": "Duty manager approval with incident note.",
        },
        "data_scope": "operational_routes_vessels_cargo_alerts_reports",
    },
    "Public": {
        "permissions": ["read_only"],
        "landing_page": "Dashboard",
        "risk": "Public read-only mode with no cargo edits, approvals, settings, alert creation, or command actions.",
        "auth": {
            "required_level": "public",
            "required_methods": ["social login or guest preview"],
            "allowed_providers": ["Email Magic Link", "Google OAuth", "Facebook Login", "Instagram Login", "Apple Sign In", "Discord Login", "Game Center", "Xbox Live"],
            "session_minutes": 20,
            "idle_timeout_minutes": 10,
            "step_up_for": [],
            "device_policy": "Public sessions only see sanitized demo views.",
            "fallback": "Continue as guest preview with limited public data.",
        },
        "data_scope": "public_demo_only",
    },
}


AUTH_HARDENING_CONTROLS = [
    "Default to Public until a role-specific sign-in flow succeeds.",
    "Block all write actions unless the active session role matches the required permission.",
    "Require fingerprint/passkey step-up for Admin and MFA/passkey step-up for Operator.",
    "Keep public Google/Facebook access read-only and isolated from cargo, settings, and approvals.",
    "Shorten admin sessions and require fresh verification for critical actions.",
]


DEMO_USER_ACCOUNTS = [
    {"email": "admin@demo.app", "display_name": "Command Admin", "role": "Admin", "provider": "Admin Fingerprint", "password": "admin-demo"},
    {"email": "operator@demo.app", "display_name": "Command Operator", "role": "Operator", "provider": "Company SSO", "password": "operator-demo"},
    {"email": "public@demo.app", "display_name": "Public Guest", "role": "Public", "provider": "Email Magic Link", "password": "public-demo"},
]

ROLE_ALIASES = {
    "admin": "Admin",
    "operator": "Operator",
    "fleet operator": "Operator",
    "fleet": "Operator",
    "risk analyst": "Operator",
    "risk": "Operator",
    "viewer": "Public",
    "public visitor": "Public",
    "public": "Public",
    "guest": "Public",
}

LEGACY_DEMO_ACCOUNT_UPGRADES = {
    "fleet@demo.app": {"display_name": "Fleet Captain", "role": "Operator", "provider": "Company SSO", "password": "fleet-demo"},
    "risk@demo.app": {"display_name": "Legacy Operator", "role": "Operator", "provider": "Company SSO", "password": "risk-demo"},
    "viewer@demo.app": {"display_name": "Legacy Public", "role": "Public", "provider": "Email Magic Link", "password": "viewer-demo"},
}


def normalize_role(role: str | None) -> str:
    return ROLE_ALIASES.get(str(role or "").strip().lower(), "Public")

SCENARIO_LOCATIONS = {
    **PORT_COORDS,
    "Singapore / Malacca": (1.12, 103.35),
    "Gulf of Aden": (12.0, 45.0),
    "South China Sea": (15.5, 114.5),
    "Suez / Red Sea": (24.0, 36.5),
    "Pacific Corridor": (24.0, -150.0),
    "North Sea": (55.0, 4.0),
    "Global Network": (22.0, 55.0),
}

SCENARIO_PROFILES = {
    "Storm Surge": {
        "category": "Weather",
        "route_modifier": 1.7,
        "readiness_penalty": 9,
        "delay_factor": 1.9,
        "alert_title": "Simulated storm disruption",
        "mission": "Protect crew, slow exposed vessels, and delay departures before weather closes the lane.",
    },
    "Piracy Swarm": {
        "category": "Security",
        "route_modifier": 2.0,
        "readiness_penalty": 12,
        "delay_factor": 1.4,
        "alert_title": "Simulated piracy swarm",
        "mission": "Move valuable cargo out of exposure, harden escorts, and create a safe corridor.",
    },
    "Hijack Attempt": {
        "category": "Security",
        "route_modifier": 2.18,
        "readiness_penalty": 15,
        "delay_factor": 1.7,
        "alert_title": "Simulated hijack attempt",
        "mission": "Protect crew, move to secure communications, notify maritime authorities, and divert away from unsafe boarding exposure.",
    },
    "War Conflict": {
        "category": "Geopolitical",
        "route_modifier": 2.35,
        "readiness_penalty": 18,
        "delay_factor": 2.2,
        "alert_title": "Simulated conflict-zone escalation",
        "mission": "Avoid contested corridors, hold exposed departures, protect insurance/legal compliance, and release only verified safe lanes.",
    },
    "Port Shutdown": {
        "category": "Port / Delay",
        "route_modifier": 1.55,
        "readiness_penalty": 10,
        "delay_factor": 2.5,
        "alert_title": "Simulated port shutdown",
        "mission": "Prevent berth gridlock by diverting arrivals and protecting priority cargo handoffs.",
    },
    "Cyber Blackout": {
        "category": "Cyber",
        "route_modifier": 1.3,
        "readiness_penalty": 14,
        "delay_factor": 1.6,
        "alert_title": "Simulated cyber blackout",
        "mission": "Preserve manual control, validate AIS integrity, and keep releases under human approval.",
    },
    "Fuel Shock": {
        "category": "Market",
        "route_modifier": 1.15,
        "readiness_penalty": 7,
        "delay_factor": 1.2,
        "alert_title": "Simulated fuel price shock",
        "mission": "Protect margins by prioritizing shorter safe alternatives and high-value cargo.",
    },
    "Cargo Theft Ring": {
        "category": "Cargo Security",
        "route_modifier": 1.85,
        "readiness_penalty": 11,
        "delay_factor": 1.1,
        "alert_title": "Simulated cargo theft ring",
        "mission": "Hide vulnerable manifests, change handoff timing, and protect high-value cargo.",
    },
}

SCENARIO_SEVERITY = {
    "low": 0.65,
    "medium": 1.0,
    "high": 1.35,
    "extreme": 1.75,
}

STRATEGIC_LOCATION_PORTS = {
    "singapore / malacca": {"Singapore", "Shanghai", "Dubai"},
    "gulf of aden": {"Dubai", "Rotterdam", "Singapore"},
    "south china sea": {"Shanghai", "Singapore", "Dubai"},
    "suez / red sea": {"Dubai", "Rotterdam"},
    "pacific corridor": {"Los Angeles", "Shanghai"},
    "north sea": {"Rotterdam"},
    "global network": set(PORT_COORDS),
}

GLOBAL_PORTS = {
    **PORT_COORDS,
    "Mumbai": (18.9388, 72.8354),
    "Chennai": (13.0827, 80.2707),
    "Colombo": (6.9271, 79.8612),
    "Karachi": (24.8607, 67.0011),
    "Chittagong": (22.3569, 91.7832),
    "Port Klang": (3.0, 101.4),
    "Tanjung Pelepas": (1.363, 103.548),
    "Jakarta": (-6.2088, 106.8456),
    "Ho Chi Minh City": (10.8231, 106.6297),
    "Manila": (14.5995, 120.9842),
    "Hong Kong": (22.3193, 114.1694),
    "Shenzhen": (22.5431, 114.0579),
    "Ningbo": (29.8683, 121.544),
    "Busan": (35.1796, 129.0756),
    "Tokyo": (35.6762, 139.6503),
    "Yokohama": (35.4437, 139.638),
    "Melbourne": (-37.8136, 144.9631),
    "Sydney": (-33.8688, 151.2093),
    "Auckland": (-36.8485, 174.7633),
    "Brisbane": (-27.4698, 153.0251),
    "Vancouver": (49.2827, -123.1207),
    "Seattle": (47.6062, -122.3321),
    "Oakland": (37.8044, -122.2712),
    "Long Beach": (33.7701, -118.1937),
    "New York": (40.7128, -74.006),
    "Norfolk": (36.8508, -76.2859),
    "Savannah": (32.0809, -81.0912),
    "Houston": (29.7604, -95.3698),
    "Panama": (8.9824, -79.5199),
    "Santos": (-23.9608, -46.3336),
    "Buenos Aires": (-34.6037, -58.3816),
    "Hamburg": (53.5511, 9.9937),
    "Antwerp": (51.2194, 4.4025),
    "Felixstowe": (51.9542, 1.3511),
    "Algeciras": (36.1408, -5.4562),
    "Tangier Med": (35.888, -5.506),
    "Piraeus": (37.942, 23.646),
    "Istanbul": (41.0082, 28.9784),
    "Port Said": (31.2653, 32.3019),
    "Suez": (29.9668, 32.5498),
    "Jeddah": (21.4858, 39.1925),
    "Mombasa": (-4.0435, 39.6682),
    "Durban": (-29.8587, 31.0218),
    "Cape Town": (-33.9249, 18.4241),
    "Lagos": (6.5244, 3.3792),
    "Honolulu": (21.3069, -157.8583),
}

GLOBAL_PORT_ALIASES = {
    "nyc": "New York",
    "new york city": "New York",
    "la": "Los Angeles",
    "los angeles": "Los Angeles",
    "long beach": "Long Beach",
    "jebel ali": "Dubai",
    "uae": "Dubai",
    "dubai": "Dubai",
    "bombay": "Mumbai",
    "mumbai": "Mumbai",
    "madras": "Chennai",
    "saigon": "Ho Chi Minh City",
    "hcmc": "Ho Chi Minh City",
    "hochiminh": "Ho Chi Minh City",
    "port klang": "Port Klang",
    "tanjung pelepas": "Tanjung Pelepas",
    "tpp": "Tanjung Pelepas",
    "hongkong": "Hong Kong",
    "busan": "Busan",
    "yokohama": "Yokohama",
    "tokyo": "Tokyo",
    "rotterdam": "Rotterdam",
    "hamburg": "Hamburg",
    "antwerp": "Antwerp",
    "felixstowe": "Felixstowe",
    "piraeus": "Piraeus",
    "istanbul": "Istanbul",
    "suez": "Suez",
    "port said": "Port Said",
    "jeddah": "Jeddah",
    "cape town": "Cape Town",
    "durban": "Durban",
    "mombasa": "Mombasa",
    "lagos": "Lagos",
    "panama canal": "Panama",
    "panama": "Panama",
    "santos": "Santos",
    "buenos aires": "Buenos Aires",
    "vancouver": "Vancouver",
    "seattle": "Seattle",
    "oakland": "Oakland",
    "houston": "Houston",
    "savannah": "Savannah",
    "norfolk": "Norfolk",
    "colombo": "Colombo",
    "singapore": "Singapore",
    "shanghai": "Shanghai",
    "shenzhen": "Shenzhen",
    "ningbo": "Ningbo",
    "karachi": "Karachi",
    "chittagong": "Chittagong",
    "jakarta": "Jakarta",
    "manila": "Manila",
    "melbourne": "Melbourne",
    "sydney": "Sydney",
    "auckland": "Auckland",
    "brisbane": "Brisbane",
    "honolulu": "Honolulu",
}

GLOBAL_ROUTE_HUBS = [
    "Singapore",
    "Port Klang",
    "Colombo",
    "Dubai",
    "Jeddah",
    "Suez",
    "Port Said",
    "Piraeus",
    "Tangier Med",
    "Algeciras",
    "Cape Town",
    "Durban",
    "Panama",
    "Honolulu",
    "Yokohama",
    "Busan",
    "Vancouver",
    "Los Angeles",
    "New York",
    "Rotterdam",
    "Hamburg",
]

GLOBAL_RISK_ZONES = [
    {
        "name": "Gulf of Aden / Bab el-Mandeb",
        "lat": 12.0,
        "lon": 45.0,
        "radius_nm": 950,
        "risk": 8.8,
        "type": "Security",
        "note": "High piracy/security and regional disruption exposure.",
    },
    {
        "name": "Red Sea / Suez approach",
        "lat": 21.5,
        "lon": 37.0,
        "radius_nm": 850,
        "risk": 8.4,
        "type": "Security",
        "note": "High disruption potential around the Red Sea/Suez corridor.",
    },
    {
        "name": "Black Sea",
        "lat": 44.2,
        "lon": 34.0,
        "radius_nm": 650,
        "risk": 8.0,
        "type": "Geopolitical",
        "note": "Geopolitical and conflict-related shipping exposure.",
    },
    {
        "name": "Strait of Hormuz",
        "lat": 26.6,
        "lon": 56.3,
        "radius_nm": 430,
        "risk": 7.2,
        "type": "Geopolitical",
        "note": "Energy chokepoint with escalation and congestion risk.",
    },
    {
        "name": "Gulf of Guinea",
        "lat": 3.5,
        "lon": 3.5,
        "radius_nm": 560,
        "risk": 5.4,
        "type": "Security",
        "note": "Security and theft exposure around West African approaches; usually less severe than Red Sea/Bab el-Mandeb routing.",
    },
    {
        "name": "South China Sea",
        "lat": 15.5,
        "lon": 114.5,
        "radius_nm": 900,
        "risk": 6.2,
        "type": "Geopolitical",
        "note": "Busy trade lane with geopolitical and weather exposure.",
    },
    {
        "name": "Malacca Strait",
        "lat": 1.2,
        "lon": 103.5,
        "radius_nm": 360,
        "risk": 5.8,
        "type": "Congestion",
        "note": "Dense chokepoint with congestion and collision risk.",
    },
    {
        "name": "Panama Canal",
        "lat": 9.0,
        "lon": -79.6,
        "radius_nm": 260,
        "risk": 4.9,
        "type": "Congestion",
        "note": "Canal scheduling and water-level constraints can affect reliability.",
    },
    {
        "name": "North Atlantic winter belt",
        "lat": 48.5,
        "lon": -35.0,
        "radius_nm": 1300,
        "risk": 5.4,
        "type": "Weather",
        "note": "Seasonal heavy-weather exposure on transatlantic crossings.",
    },
    {
        "name": "Cape of Good Hope",
        "lat": -34.5,
        "lon": 18.3,
        "radius_nm": 520,
        "risk": 5.1,
        "type": "Weather",
        "note": "Longer route with heavy-weather exposure but lower Red Sea security exposure.",
    },
]

AI_RISK_TAXONOMY = {
    "Natural Hazard": {
        "base_score": 24,
        "zone_types": ["Weather"],
        "keywords": ["weather", "storm", "cyclone", "typhoon", "monsoon", "wave", "wind", "surge", "earthquake", "tsunami", "natural"],
        "caution_window": "0-72 hours",
        "watch_phrase": "Weather and natural disruption can close lanes faster than commercial schedules can recover.",
        "defensive_goal": "Keep crews out of severe-weather lanes and protect cargo commitments with earlier holds.",
        "solutions": [
            "Hold departures crossing the affected lane until the next safe weather window is verified.",
            "Reroute via lower-sea-state corridors even if distance increases.",
            "Add port-arrival buffers and notify customers before the risk peak.",
            "Require manual release for P1/P2 cargo during the caution window.",
        ],
        "data_inputs": ["maritime weather score", "weather alerts", "route forecast", "vessel speed and ETA"],
    },
    "Hijack / Piracy": {
        "base_score": 30,
        "zone_types": ["Security"],
        "keywords": ["piracy", "pirate", "hijack", "boarding", "skiff", "armed", "security", "attack", "suspicious"],
        "caution_window": "0-24 hours",
        "watch_phrase": "Security risk is highest when slow vessels, valuable cargo, and known piracy corridors overlap.",
        "defensive_goal": "Protect crew, avoid unsafe boarding exposure, and coordinate with legitimate maritime authorities.",
        "solutions": [
            "Divert around the threat box and keep high-risk vessels outside slow-speed corridors.",
            "Increase check-in cadence and verify secure communications with the vessel master.",
            "Notify maritime security coordination channels and destination port authority.",
            "Restrict sensitive cargo details to verified operators only.",
        ],
        "data_inputs": ["security alerts", "global piracy zones", "cargo priority", "vessel speed and AIS freshness"],
    },
    "War / Geopolitical": {
        "base_score": 32,
        "zone_types": ["Geopolitical"],
        "keywords": ["war", "conflict", "geopolitical", "sanction", "missile", "naval", "blockade", "military", "country", "red sea", "black sea"],
        "caution_window": "0-7 days",
        "watch_phrase": "Conflict-zone risk can invalidate an otherwise efficient route through insurance, sanctions, or sudden closure.",
        "defensive_goal": "Avoid contested corridors and keep every release decision legally and operationally defensible.",
        "solutions": [
            "Freeze departures through contested corridors until route, insurance, and compliance checks pass.",
            "Compare safest-route alternatives, especially Cape/Panama/Cape of Good Hope detours when relevant.",
            "Escalate P1 cargo to Admin or command approval before release.",
            "Prepare customer notices with clear delay reason, not sensitive security details.",
        ],
        "data_inputs": ["geopolitical zones", "route alternatives", "risk forecast", "alerts and audit trail"],
    },
    "Port / Infrastructure": {
        "base_score": 22,
        "zone_types": ["Congestion"],
        "keywords": ["port", "shutdown", "strike", "berth", "congestion", "canal", "terminal", "infrastructure", "closure"],
        "caution_window": "6-96 hours",
        "watch_phrase": "Port disruption becomes expensive when vessels keep sailing into a berth queue with no recovery plan.",
        "defensive_goal": "Prevent gridlock and protect critical handoffs with staged arrivals.",
        "solutions": [
            "Stage arrivals outside congested ports and prioritize P1/P2 cargo slots.",
            "Move non-critical cargo to alternate terminals before the queue peaks.",
            "Hold low-priority departures until berth confidence improves.",
            "Publish one operations note for port, cargo, and customer teams.",
        ],
        "data_inputs": ["port congestion score", "cargo destination", "ETA prediction", "alert workflow"],
    },
    "Cyber / AIS Integrity": {
        "base_score": 26,
        "zone_types": [],
        "keywords": ["cyber", "ais", "spoof", "blackout", "gps", "signal", "api", "websocket", "stale", "tamper"],
        "caution_window": "0-12 hours",
        "watch_phrase": "Signal uncertainty should reduce automation confidence before it becomes a navigation or reporting failure.",
        "defensive_goal": "Keep route release under human control when AIS/API confidence drops.",
        "solutions": [
            "Switch affected releases to manual AIS verification.",
            "Cross-check vessel identity, speed, destination, and last signal time before acting.",
            "Reduce auto-refresh pressure if the feed is unstable and use cached registry fallback transparently.",
            "Require two-person approval for high-value cargo when signal integrity is uncertain.",
        ],
        "data_inputs": ["AIS reliability", "stale positions", "runtime provider state", "data quality checks"],
    },
    "Cargo Crime": {
        "base_score": 21,
        "zone_types": ["Security"],
        "keywords": ["cargo theft", "theft", "smuggling", "manifest", "gold", "high value", "tamper", "handoff", "custody"],
        "caution_window": "12-72 hours",
        "watch_phrase": "Cargo crime risk rises when valuable manifests, handoff timing, and route exposure become predictable.",
        "defensive_goal": "Reduce predictability and keep sensitive cargo visible only to verified roles.",
        "solutions": [
            "Mask sensitive cargo details from public views and verify custody handoff windows.",
            "Change handoff timing for high-value cargo when security pressure rises.",
            "Require Operator/Admin approval before releasing P1 manifests.",
            "Keep audit evidence for route, cargo, and owner decisions.",
        ],
        "data_inputs": ["cargo manifest priority", "custody chain", "security alerts", "user role audit"],
    },
    "Market / Fuel Shock": {
        "base_score": 18,
        "zone_types": [],
        "keywords": ["fuel", "market", "cost", "price", "bunker", "margin", "surcharge"],
        "caution_window": "1-14 days",
        "watch_phrase": "Market shocks can make the safest route commercially hard unless cargo priority is planned early.",
        "defensive_goal": "Balance safety, fuel exposure, and promised ETA without hiding the tradeoff.",
        "solutions": [
            "Compare safest, fastest, lowest-cost, and balanced route modes before release.",
            "Protect high-value cargo with safety-first routing and delay notes.",
            "Move low-priority cargo to lower-cost windows when possible.",
            "Update reports with cost/risk tradeoffs for leadership approval.",
        ],
        "data_inputs": ["route optimizer", "cargo priority", "forecast trend", "report intelligence"],
    },
}

LOWER_RISK_GLOBAL_CORRIDORS = [
    {
        "corridor": "North Atlantic container lane",
        "example": "Rotterdam to New York",
        "why": "Mature ports, strong reporting coverage, and no major piracy chokepoint.",
    },
    {
        "corridor": "North Pacific lane",
        "example": "Yokohama or Busan to Vancouver/Seattle",
        "why": "High infrastructure reliability; main risk is weather rather than piracy.",
    },
    {
        "corridor": "Australia/New Zealand lane",
        "example": "Sydney to Auckland",
        "why": "Shorter open-ocean exposure with comparatively low security risk.",
    },
    {
        "corridor": "Intra-Europe/North Sea lane",
        "example": "Rotterdam to Hamburg/Antwerp",
        "why": "Dense monitoring, short voyage distance, and strong port-state controls.",
    },
]

DEMO_INCIDENTS = [
    ("Weather Warning", "Storm cell affecting vessel movement", "medium", "Singapore"),
    ("Piracy Alert", "Suspicious activity reported near shipping corridor", "high", "Gulf of Aden"),
    ("Port Congestion", "Queue time increasing at container terminal", "medium", "Rotterdam"),
    ("Geopolitical Tension", "Regional disruption affecting route planning", "high", "South China Sea"),
    ("Mechanical Failure", "Vessel reported reduced engine performance", "low", "Pacific Ocean"),
]

LIVE_CARGO_MANIFESTS = [
    {"cargo": "Petrol", "tons": 82000, "value": "$74M", "class": "Energy"},
    {"cargo": "Gold", "tons": 42, "value": "$2.7B", "class": "High value"},
    {"cargo": "Electronics", "tons": 12800, "value": "$430M", "class": "Priority"},
    {"cargo": "LNG", "tons": 91000, "value": "$118M", "class": "Energy"},
    {"cargo": "Grain", "tons": 64000, "value": "$31M", "class": "Food"},
    {"cargo": "Medical Supplies", "tons": 7200, "value": "$210M", "class": "Critical"},
]

INFERRED_MANIFEST_STATUSES = {"inferred-live", "demo-inferred", "inferred demo cargo"}
GENERATED_WORKFLOW_SOURCES = ["Strategic Autopilot", "Auto Incident Commander", "Notification Center"]
FALLBACK_CARGO_NAMES = {item["cargo"].lower() for item in LIVE_CARGO_MANIFESTS}
DEMO_ACCOUNT_EMAILS = (
    {str(seed["email"]).strip().lower() for seed in DEMO_USER_ACCOUNTS}
    | set(LEGACY_DEMO_ACCOUNT_UPGRADES)
)


def env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def production_mode_enabled() -> bool:
    app_mode = os.getenv("APP_MODE", "demo").strip().lower()
    return app_mode in {"prod", "production"} or env_truthy("PRODUCTION_MODE")


def demo_accounts_allowed() -> bool:
    return not production_mode_enabled() or env_truthy("ALLOW_DEMO_ACCOUNTS_IN_PRODUCTION")


def auth_provider_connected(provider: str) -> bool:
    required = AUTH_PROVIDER_ENV_REQUIREMENTS.get(provider, [])
    return bool(required) and all(os.getenv(name) for name in required)


def unique_by(items, key_fn):
    seen = set()
    unique_items = []
    for item in items:
        key = key_fn(item)
        if key in seen:
            continue
        seen.add(key)
        unique_items.append(item)
    return unique_items


def bearing_angle(start_lat: float, start_lon: float, end_lat: float, end_lon: float) -> float:
    delta_lon = end_lon - start_lon
    delta_lat = end_lat - start_lat
    return math.degrees(math.atan2(delta_lon, delta_lat))


def safe_generate_pdf_report(content: str) -> str:
    try:
        return generate_pdf_report(content)
    except PermissionError:
        runtime_report_dir = os.path.join(".runtime", "reports")
        return generate_pdf_report(content, output_dir=runtime_report_dir)


def password_digest(password: str) -> str:
    salt = os.getenv("AUTH_DEMO_SALT", "global-trade-intelligence-demo")
    return hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()


def auth_session_secret() -> bytes:
    salt = os.getenv("AUTH_DEMO_SALT", "global-trade-intelligence-demo")
    return f"session:{salt}".encode("utf-8")


def encode_auth_session_payload(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    signature = hmac.new(auth_session_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def decode_auth_session_token(token: str) -> dict:
    try:
        body, signature = str(token or "").split(".", 1)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid session token") from exc
    expected = hmac.new(auth_session_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid session signature")
    padding = "=" * (-len(body) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(f"{body}{padding}".encode("ascii")).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid session payload") from exc
    expires_at = parse_iso_datetime(payload.get("exp"))
    if not expires_at or expires_at < datetime.datetime.now(datetime.timezone.utc):
        raise HTTPException(status_code=401, detail="Session expired")
    return payload


def issue_auth_session(account: UserAccount) -> dict:
    role = normalize_role(account.role)
    minutes = ROLE_SECURITY_POLICIES.get(role, {}).get("auth", {}).get("session_minutes", 20)
    now = datetime.datetime.now(datetime.timezone.utc)
    expires_at = now + datetime.timedelta(minutes=int(minutes or 20))
    token = encode_auth_session_payload({
        "email": account.email,
        "role": role,
        "provider": account.provider,
        "display_name": account.display_name,
        "iat": now.isoformat(),
        "exp": expires_at.isoformat(),
    })
    return {"session_token": token, "session_expires_at": expires_at.isoformat()}


def auth_response(account: UserAccount, method: str) -> dict:
    return {
        "account": serialize_user_account(account),
        "method": method,
        **issue_auth_session(account),
    }


def normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def serialize_user_account(account: UserAccount):
    role = normalize_role(account.role)
    return {
        "id": account.id,
        "email": account.email,
        "display_name": account.display_name,
        "role": role,
        "provider": account.provider,
        "status": account.status,
        "created_at": account.created_at.isoformat() if account.created_at else None,
        "last_login_at": account.last_login_at.isoformat() if account.last_login_at else None,
        "permissions": ROLE_SECURITY_POLICIES.get(role, {}).get("permissions", []),
        "landing_page": ROLE_SECURITY_POLICIES.get(role, {}).get("landing_page", "Dashboard"),
        "session_minutes": ROLE_SECURITY_POLICIES.get(role, {}).get("auth", {}).get("session_minutes", 20),
    }


def account_provider_for_role(role: str, requested: str | None = None) -> str:
    role = normalize_role(role)
    if requested and auth_provider_allowed(role, requested):
        return requested
    if role == "Admin":
        return "Admin Fingerprint"
    if role == "Operator":
        return "Company SSO"
    return "Email Magic Link"


def ensure_demo_user_accounts(db: Session):
    for account in db.query(UserAccount).all():
        normalized_role = normalize_role(account.role)
        if account.role != normalized_role:
            account.role = normalized_role
    for email, upgrade in LEGACY_DEMO_ACCOUNT_UPGRADES.items():
        account = db.query(UserAccount).filter(UserAccount.email == email).first()
        if account:
            account.role = upgrade["role"]
            account.provider = upgrade["provider"]
    if not demo_accounts_allowed():
        db.commit()
        return
    now = datetime.datetime.now(datetime.timezone.utc)
    for seed in DEMO_USER_ACCOUNTS:
        email = normalize_email(seed["email"])
        account = db.query(UserAccount).filter(UserAccount.email == email).first()
        if account:
            account.display_name = seed["display_name"]
            account.role = seed["role"]
            account.provider = seed["provider"]
            continue
        db.add(UserAccount(
            email=email,
            display_name=seed["display_name"],
            role=seed["role"],
            provider=seed["provider"],
            password_hash=password_digest(seed["password"]),
            status="active",
            created_at=now,
            last_login_at=None,
        ))
    db.commit()


def auth_provider_allowed(role: str, provider: str) -> bool:
    role = normalize_role(role)
    allowed = ROLE_SECURITY_POLICIES.get(role, {}).get("auth", {}).get("allowed_providers", [])
    return provider in allowed


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_demo_user_accounts(db)
    finally:
        db.close()
    start_ai_live_updates()
    yield


app = FastAPI(title="Global AI Trade Intelligence Platform API", version="1.0.0", lifespan=lifespan)
AI_LIVE_STATE = {"packet": None, "updated_at": None, "running": False}
AI_LIVE_LOCK = threading.Lock()
APP_STARTED_AT = datetime.datetime.now(datetime.timezone.utc)
LAST_OPERATIONAL_PERSIST_AT = 0.0
OPERATIONAL_PERSIST_LOCK = threading.Lock()
Base.metadata.create_all(bind=engine)
db = SessionLocal()
try:
    ensure_demo_user_accounts(db)
finally:
    db.close()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify allowed origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


def audit_actor(request: Request | None = None) -> tuple[str, str]:
    if request is None:
        return "System", "Backend"
    role = normalize_role(request.headers.get("x-user-role") or "Public")
    identity = request.headers.get("x-user-identity") or "Unknown"
    return role[:80], identity[:120]


def request_role(request: Request | None) -> str:
    if request is None:
        return "System"
    return normalize_role(request.headers.get("x-user-role") or "Public")


def require_role(request: Request | None, allowed_roles: set[str], action_name: str):
    if request is None:
        return
    role = request_role(request)
    allowed_roles = {normalize_role(item) for item in allowed_roles}
    if role not in allowed_roles:
        raise HTTPException(status_code=403, detail=f"{action_name} requires {', '.join(sorted(allowed_roles))} access")


def role_permissions(role: str) -> set[str]:
    role = normalize_role(role)
    return set(ROLE_SECURITY_POLICIES.get(role, {}).get("permissions", []))


def require_permission(request: Request | None, permission: str, action_name: str):
    if request is None:
        return
    role = request_role(request)
    if permission not in role_permissions(role):
        raise HTTPException(status_code=403, detail=f"{action_name} requires {permission} permission for a verified role")


def require_any_permission(request: Request | None, permissions: list[str], action_name: str):
    if request is None:
        return
    role = request_role(request)
    if not (role_permissions(role) & set(permissions)):
        joined = ", ".join(permissions)
        raise HTTPException(status_code=403, detail=f"{action_name} requires one of: {joined}")


def record_audit_event(
    db: Session,
    action: str,
    resource: str,
    detail: str,
    severity: str = "info",
    request: Request | None = None,
):
    actor_role, actor_identity = audit_actor(request)
    event = AuditLog(
        actor_role=actor_role,
        actor_identity=actor_identity,
        action=action[:120],
        resource=resource[:160],
        severity=severity[:40],
        detail=detail[:1200],
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    db.add(event)
    return event


def serialize_audit_log(event: AuditLog):
    return {
        "id": event.id,
        "actor_role": event.actor_role,
        "actor_identity": event.actor_identity,
        "action": event.action,
        "resource": event.resource,
        "severity": event.severity,
        "detail": event.detail,
        "timestamp": event.timestamp.isoformat() if event.timestamp else None,
    }


def parse_iso_datetime(value: str | None) -> datetime.datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed
    except (TypeError, ValueError):
        return None


@app.get("/health")
def health(db: Session = Depends(get_db)):
    checked_at = datetime.datetime.now(datetime.timezone.utc)
    uptime_seconds = int((checked_at - APP_STARTED_AT).total_seconds())
    try:
        counts = {
            "vessels": db.query(Vessel).count(),
            "routes": db.query(TradeRoute).count(),
            "alerts": db.query(ThreatAlert).count(),
            "risk_logs": db.query(RiskLog).count(),
            "reports": db.query(GeneratedReport).count(),
            "ais_history": db.query(AISPositionHistory).count(),
            "cargo_manifests": db.query(CargoManifest).count(),
            "ai_actions": db.query(AIAction).count(),
            "incidents": db.query(IncidentEvent).count(),
            "audit_logs": db.query(AuditLog).count(),
            "user_accounts": db.query(UserAccount).count(),
        }
        database_status = "operational"
    except Exception as exc:
        counts = {}
        database_status = f"error: {exc}"

    with AI_LIVE_LOCK:
        ai_running = AI_LIVE_STATE["running"]
        ai_updated_at = AI_LIVE_STATE["updated_at"]
    aisstream_status = get_aisstream_status()

    return {
        "status": "healthy" if database_status == "operational" else "degraded",
        "version": app.version,
        "checked_at": checked_at.isoformat(),
        "uptime_seconds": uptime_seconds,
        "database": {
            "status": database_status,
            "records": counts,
        },
        "services": {
            "api": "online",
            "ai_live_loop": "running" if ai_running else "starting",
            "ai_last_packet": ai_updated_at,
            "aisstream": aisstream_status,
            "reports": "ready",
        },
    }

@app.get("/")
def root():
    return {
        "message": "FastAPI backend is running.",
        "routes": [
            "/health",
            "/analytics/overview",
            "/analytics/operations",
            "/analytics/forecast",
            "/reports",
            "/routes",
            "/vessels",
            "/vessels/live",
            "/vessels/history",
            "/ais/reliability",
            "/cargo/manifests",
            "/ai/actions",
            "/ai/risk-intelligence",
            "/ai/incident-playbook",
            "/ai/incident-predictions",
            "/ai/captain",
            "/ai/captain/action",
            "/ai/mission-map-overlay",
            "/ai/strategic-autopilot",
            "/ai/voyage-control-tower",
            "/auth/roles",
            "/auth/accounts",
            "/auth/provider-status",
            "/auth/session/validate",
            "/admin/users",
            "/security/audit-summary",
            "/setup/checklist",
            "/database/operations",
            "/external-data/status",
            "/weather/maritime",
            "/copilot/ask",
            "/copilot/global-route",
            "/notifications",
            "/notifications/digest",
            "/notifications/action",
            "/notifications/delivery-status",
            "/operations/inbox",
            "/operations/inbox/action",
            "/system/reliability",
            "/settings/runtime",
            "/settings/production-mode",
            "/routes/alternatives",
            "/scenario/simulate",
            "/replay/timeline",
            "/reports/smart",
            "/vessels/predictions",
            "/alerts/workflows",
            "/executive/brief",
            "/data-quality",
            "/data-cleanup/summary",
            "/data-cleanup/run",
            "/deployment/readiness",
            "/deployment/hardening",
            "/operations/timeline",
            "/operations/intelligence",
            "/alerts",
            "/ai/live",
            "/ai/risk-assessments",
            "/docs",
        ]
    }

@app.get("/routes")
def get_routes(db: Session = Depends(get_db)):
    routes = db.query(TradeRoute).order_by(TradeRoute.id).all()
    return unique_by(routes, lambda route: (route.origin_port, route.destination_port))

@app.get("/vessels")
def get_vessels(db: Session = Depends(get_db)):
    vessels = db.query(Vessel).order_by(Vessel.id).all()
    return unique_by(vessels, lambda vessel: vessel.name)


@app.get("/vessels/live")
def get_live_vessels(db: Session = Depends(get_db)):
    vessels, source = get_operational_vessels(db)
    return {
        "source": source,
        "vessels": vessels,
        "aisstream": get_aisstream_status(),
    }


@app.get("/vessels/history")
def get_vessel_history(
    vessel_identifier: str | None = None,
    limit: int = 300,
    db: Session = Depends(get_db),
):
    limit = max(20, min(limit, 1000))
    query = db.query(AISPositionHistory).order_by(AISPositionHistory.timestamp.desc())
    if vessel_identifier:
        query = query.filter(AISPositionHistory.vessel_identifier == vessel_identifier)
    rows = list(reversed(query.limit(limit).all()))
    latest_by_vessel = {}
    for row in rows:
        latest_by_vessel[row.vessel_identifier] = row.vessel_name
    return {
        "rows": [serialize_ais_history(row) for row in rows],
        "vessels": [
            {"vessel_identifier": identifier, "vessel_name": name}
            for identifier, name in sorted(latest_by_vessel.items(), key=lambda item: item[1])
        ],
    }


@app.get("/cargo/manifests")
def get_cargo_manifests(limit: int = 100, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 500))
    manifests = db.query(CargoManifest).order_by(CargoManifest.updated_at.desc()).limit(limit).all()
    return [serialize_cargo_manifest(manifest) for manifest in manifests]


@app.post("/cargo/manifests")
def upsert_cargo_manifest(
    payload: CargoManifestUpsert,
    db: Session = Depends(get_db),
    request: Request = None,
):
    require_permission(request, "edit_cargo", "Cargo manifest updates")
    now = datetime.datetime.now(datetime.timezone.utc)
    manifest = (
        db.query(CargoManifest)
        .filter(CargoManifest.vessel_identifier == payload.vessel_identifier)
        .order_by(CargoManifest.id.desc())
        .first()
    )
    values = payload.model_dump()
    values["priority"] = payload.priority or manifest_priority(payload.cargo_class)
    values["updated_at"] = now
    if manifest:
        for key, value in values.items():
            setattr(manifest, key, value)
    else:
        manifest = CargoManifest(**values)
        db.add(manifest)
    db.commit()
    db.refresh(manifest)
    record_incident_once(
        db,
        title="Cargo manifest updated",
        category="Cargo",
        severity="low" if manifest.priority == "P3" else "medium",
        location=manifest.destination_port,
        vessel_name=manifest.vessel_name,
        description=f"{manifest.cargo} manifest set to {manifest.priority}.",
        source="Operator",
    )
    record_audit_event(
        db,
        action="cargo_manifest_upsert",
        resource=manifest.vessel_name,
        detail=f"{manifest.cargo} manifest set to {manifest.priority}.",
        severity="warning" if manifest.priority in {"P1", "P2"} else "info",
        request=request,
    )
    db.commit()
    return serialize_cargo_manifest(manifest)


@app.post("/vessels")
def create_vessel(vessel: VesselCreate, db: Session = Depends(get_db), request: Request = None):
    require_permission(request, "manage_vessels", "Vessel creation")
    db_vessel = Vessel(**vessel.model_dump())
    db.add(db_vessel)
    record_audit_event(
        db,
        action="vessel_created",
        resource=vessel.name,
        detail=f"Vessel created at {vessel.position_lat}, {vessel.position_lon} with status {vessel.status}.",
        severity="info",
        request=request,
    )
    db.commit()
    db.refresh(db_vessel)
    return db_vessel

@app.get("/alerts")
def get_alerts(db: Session = Depends(get_db)):
    alerts = db.query(ThreatAlert).order_by(ThreatAlert.id.desc()).all()
    return unique_by(alerts, lambda alert: (alert.title, alert.location, alert.severity))

@app.post("/alerts")
def create_alert(alert: AlertCreate, db: Session = Depends(get_db), request: Request = None):
    require_permission(request, "create_alerts", "Alert creation")
    db_alert = ThreatAlert(**alert.model_dump())
    db.add(db_alert)
    record_audit_event(
        db,
        action="alert_created",
        resource=alert.location,
        detail=f"{alert.title}: {alert.description}",
        severity="critical" if str(alert.severity).lower() == "high" else "warning",
        request=request,
    )
    db.commit()
    db.refresh(db_alert)
    return db_alert

@app.post("/risk-log")
def create_risk_log(route_id: int, db: Session = Depends(get_db), request: Request = None):
    require_any_permission(request, ["create_alerts", "manage_alert_workflows"], "Risk log creation")
    route = db.query(TradeRoute).filter(TradeRoute.id == route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    risk_score = assess_route_risk(route)["score"]
    risk_log = RiskLog(route_id=route_id, risk_score=risk_score, timestamp=datetime.datetime.now(datetime.timezone.utc))
    db.add(risk_log)
    record_audit_event(
        db,
        action="risk_log_created",
        resource=f"{route.origin_port} to {route.destination_port}",
        detail=f"Risk log created with score {risk_score}.",
        severity="warning" if risk_score >= 7 else "info",
        request=request,
    )
    db.commit()
    db.refresh(risk_log)
    return risk_log

@app.get("/risk-history")
def get_risk_history(db: Session = Depends(get_db)):
    logs = db.query(RiskLog).all()
    return logs

@app.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    vessels, source = get_operational_vessels(db)
    routes = unique_by(
        db.query(TradeRoute).order_by(TradeRoute.id).all(),
        lambda route: (route.origin_port, route.destination_port),
    )
    alerts = unique_by(
        db.query(ThreatAlert).order_by(ThreatAlert.id.desc()).all(),
        lambda alert: (alert.title, alert.location, alert.severity),
    )
    avg_risk = sum(route.risk_level for route in routes) / len(routes) if routes else 0
    return {
        "vessels": len(vessels),
        "routes": len(routes),
        "alerts": len(alerts),
        "average_risk": round(avg_risk, 2),
        "fleet_source": source,
    }


@app.get("/ai/risk-assessments")
def get_ai_route_assessments(db: Session = Depends(get_db)):
    routes = unique_by(
        db.query(TradeRoute).order_by(TradeRoute.id).all(),
        lambda route: (route.origin_port, route.destination_port),
    )
    alerts = unique_by(
        db.query(ThreatAlert).order_by(ThreatAlert.id.desc()).all(),
        lambda alert: (alert.title, alert.location, alert.severity),
    )
    assessments = build_route_assessments(routes, alerts)
    for item in assessments:
        item["model_trace"] = {
            "ml_score": item.get("ml_score"),
            "rule_score": item.get("rule_score"),
            "alert_pressure": item.get("alert_pressure"),
            "blend": "58% ML score, 42% rule score, plus live modifier when available",
        }
        item["missing_data"] = [
            label
            for label, present in {
                "live weather feed": bool(item.get("matched_alerts")),
                "real cargo priority": bool(item.get("factors", {}).get("cargo_importance")),
                "port congestion API": bool(item.get("factors", {}).get("port_congestion")),
            }.items()
            if not present
        ]
        item["human_checklist"] = [
            "Confirm latest AIS position for exposed vessels.",
            "Compare safest route option before approving departure.",
            "Escalate to command if confidence drops below 70%.",
        ]
    return assessments


@app.get("/ai/actions")
def get_ai_actions(status: str | None = None, limit: int = 50, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 200))
    query = db.query(AIAction).order_by(AIAction.id.desc())
    if status:
        query = query.filter(AIAction.status == status)
    return [serialize_ai_action(action) for action in query.limit(limit).all()]


@app.post("/ai/actions/{action_id}/status")
def update_ai_action_status(
    action_id: int,
    update: ActionStatusUpdate,
    db: Session = Depends(get_db),
    request: Request = None,
):
    require_permission(request, "approve_actions", "AI action status updates")
    allowed = {"queued", "approved", "rejected", "completed"}
    status = update.status.lower().strip()
    if status not in allowed:
        raise HTTPException(status_code=400, detail=f"Status must be one of {sorted(allowed)}")
    action = db.query(AIAction).filter(AIAction.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="AI action not found")
    action.status = status
    if update.owner:
        action.owner = update.owner
    action.updated_at = datetime.datetime.now(datetime.timezone.utc)
    record_audit_event(
        db,
        action=f"ai_action_{status}",
        resource=action.subject,
        detail=f"{action.priority} action moved to {status}: {action.recommendation}",
        severity="critical" if action.priority == "P1" else "warning",
        request=request,
    )
    db.commit()
    db.refresh(action)
    return serialize_ai_action(action)


@app.get("/operations/timeline")
def get_operations_timeline(limit: int = 100, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 300))
    incidents = db.query(IncidentEvent).order_by(IncidentEvent.timestamp.desc()).limit(limit).all()
    actions = db.query(AIAction).order_by(AIAction.updated_at.desc()).limit(limit).all()
    rows = []
    for event in incidents:
        rows.append({
            "timestamp": event.timestamp.isoformat() if event.timestamp else None,
            "type": "Incident",
            "severity": event.severity,
            "subject": event.vessel_name or event.route or event.location,
            "title": event.title,
            "status": event.status,
            "source": event.source,
        })
    for action in actions:
        rows.append({
            "timestamp": action.updated_at.isoformat() if action.updated_at else None,
            "type": "AI Action",
            "severity": action.priority,
            "subject": action.subject,
            "title": action.recommendation,
            "status": action.status,
            "source": action.source,
        })
    rows.sort(key=lambda row: row.get("timestamp") or "", reverse=True)
    return rows[:limit]


@app.get("/operations/intelligence")
def get_operations_intelligence_v2(db: Session = Depends(get_db)):
    manifests = db.query(CargoManifest).order_by(CargoManifest.updated_at.desc()).limit(200).all()
    actions = db.query(AIAction).order_by(AIAction.updated_at.desc()).limit(100).all()
    incidents = db.query(IncidentEvent).order_by(IncidentEvent.timestamp.desc()).limit(100).all()
    history_count = db.query(AISPositionHistory).count()
    open_actions = [action for action in actions if action.status in {"queued", "approved"}]
    p1_actions = [action for action in open_actions if action.priority == "P1"]
    cargo_counts = Counter(manifest.priority for manifest in manifests if manifest_is_verified(manifest))
    incident_counts = Counter(event.severity for event in incidents if event.status == "open")
    readiness = 100
    readiness -= len(p1_actions) * 8
    readiness -= cargo_counts.get("P1", 0) * 1.5
    readiness -= incident_counts.get("high", 0) * 12
    readiness = round(max(0, min(100, readiness)), 1)
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "readiness_score": readiness,
        "readiness_band": "Ready" if readiness >= 80 else "Watch" if readiness >= 65 else "At Risk",
        "summary": {
            "tracked_positions": history_count,
            "cargo_manifests": len(manifests),
            "open_actions": len(open_actions),
            "p1_actions": len(p1_actions),
            "open_incidents": sum(incident_counts.values()),
        },
        "cargo_priority_counts": dict(cargo_counts),
        "incident_severity_counts": dict(incident_counts),
        "top_actions": [serialize_ai_action(action) for action in open_actions[:8]],
        "top_cargo": [serialize_cargo_manifest(manifest) for manifest in manifests if manifest_is_verified(manifest)][:8],
        "timeline": get_operations_timeline(limit=30, db=db),
    }


@app.get("/notifications")
def get_notifications(limit: int = 50, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 200))
    rows = []
    ais_status = get_aisstream_status()
    now = datetime.datetime.now(datetime.timezone.utc)

    if not ais_status.get("enabled"):
        rows.append({
            "severity": "warning",
            "title": "AISStream API key not active",
            "message": "Set AIS_PROVIDER=aisstream and AISSTREAM_API_KEY in .env to enable live-vessel notifications.",
            "source": "AISStream API",
            "timestamp": now.isoformat(),
            "target": "Live feed",
        })
    elif ais_status.get("last_error"):
        rows.append({
            "severity": "critical" if not ais_status.get("connected") else "warning",
            "title": "AISStream connection warning",
            "message": str(ais_status.get("last_error")),
            "source": "AISStream API",
            "timestamp": now.isoformat(),
            "target": "Live feed",
        })
    elif ais_status.get("connected"):
        rows.append({
            "severity": "info",
            "title": "AISStream API key connected",
            "message": f"Receiving live AIS messages for {ais_status.get('vessel_count', 0)} cached vessel(s).",
            "source": "AISStream API",
            "timestamp": ais_status.get("last_message_at") or now.isoformat(),
            "target": "Live feed",
        })
    elif ais_status.get("enabled"):
        rows.append({
            "severity": "warning",
            "title": "AISStream listener waiting",
            "message": "API key is configured, but the websocket has not connected yet.",
            "source": "AISStream API",
            "timestamp": now.isoformat(),
            "target": "Live feed",
        })

    live_vessels = get_aisstream_vessels(limit=80) if ais_status.get("enabled") else []
    stale_seconds = max(60, int(float(os.getenv("AISSTREAM_STALE_SECONDS", "900") or 900)))
    for vessel in live_vessels[:60]:
        name = vessel.get("name") or vessel.get("mmsi") or "AIS vessel"
        last_signal = parse_iso_datetime(vessel.get("last_signal_at"))
        age_seconds = (now - last_signal).total_seconds() if last_signal else None
        speed = parse_float(vessel.get("speed_knots"), 0)
        cargo_class = str(vessel.get("cargo_class") or "").lower()
        cargo_priority = effective_vessel_cargo_priority(vessel)
        cargo = vessel.get("cargo") or "cargo"
        if age_seconds is not None and age_seconds > stale_seconds:
            rows.append({
                "severity": "warning",
                "title": "Live AIS signal stale",
                "message": f"{name} has not reported for {int(age_seconds // 60)} minutes.",
                "source": "AISStream API",
                "timestamp": vessel.get("last_signal_at"),
                "target": name,
            })
        if speed <= 0.5:
            rows.append({
                "severity": "warning",
                "title": "Live AIS vessel stopped",
                "message": f"{name} is reporting {speed:.1f} kn near {vessel.get('origin_port', 'unknown waters')}.",
                "source": "AISStream API",
                "timestamp": vessel.get("last_signal_at") or now.isoformat(),
                "target": name,
            })
        if cargo_class in {"critical", "high value"}:
            verified_cargo = cargo_is_verified_source(vessel)
            rows.append({
                "severity": "critical" if verified_cargo and cargo_priority == "P1" else "warning",
                "title": "Verified priority cargo watch" if verified_cargo else "Inferred cargo watch",
                "message": f"{name} is carrying {cargo} ({vessel.get('cargo_value', 'value unknown')}) via live AIS; source={vessel.get('cargo_source', 'Unknown')}.",
                "source": "AISStream API",
                "timestamp": vessel.get("last_signal_at") or now.isoformat(),
                "target": name,
            })

    actions = db.query(AIAction).filter(AIAction.status == "queued").order_by(AIAction.updated_at.desc()).limit(30).all()
    for action in actions:
        rows.append({
            "severity": "critical" if action.priority == "P1" else "warning",
            "title": f"{action.priority} action waiting",
            "message": f"{action.subject}: {action.recommendation}",
            "source": action.source,
            "timestamp": action.updated_at.isoformat() if action.updated_at else None,
            "target": action.subject,
        })

    incidents = db.query(IncidentEvent).filter(IncidentEvent.status == "open").order_by(IncidentEvent.timestamp.desc()).limit(30).all()
    for event in incidents:
        rows.append({
            "severity": "critical" if event.severity == "high" else "warning" if event.severity == "medium" else "info",
            "title": event.title,
            "message": event.description,
            "source": event.source,
            "timestamp": event.timestamp.isoformat() if event.timestamp else None,
            "target": event.vessel_name or event.route or event.location,
        })

    p1_cargo = [
        manifest
        for manifest in db.query(CargoManifest).filter(CargoManifest.priority == "P1").order_by(CargoManifest.updated_at.desc()).limit(80).all()
        if manifest_is_verified(manifest)
    ][:20]
    for manifest in p1_cargo:
        rows.append({
            "severity": "warning",
            "title": "Priority cargo exposure",
            "message": f"{manifest.vessel_name} carrying {manifest.cargo} toward {manifest.destination_port}.",
            "source": "Cargo manifest",
            "timestamp": manifest.updated_at.isoformat() if manifest.updated_at else None,
            "target": manifest.vessel_name,
        })

    stale_cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=15)
    latest_rows = (
        db.query(AISPositionHistory)
        .order_by(AISPositionHistory.vessel_identifier, AISPositionHistory.timestamp.desc())
        .limit(300)
        .all()
    )
    seen = set()
    for row in latest_rows:
        if row.vessel_identifier in seen:
            continue
        seen.add(row.vessel_identifier)
        row_timestamp = row.timestamp
        if row_timestamp and row_timestamp.tzinfo is None:
            row_timestamp = row_timestamp.replace(tzinfo=datetime.timezone.utc)
        if row_timestamp and row_timestamp < stale_cutoff:
            rows.append({
                "severity": "warning",
                "title": "Stale AIS signal",
                "message": f"{row.vessel_name} has not reported since {row_timestamp.isoformat()}.",
                "source": row.source,
                "timestamp": row_timestamp.isoformat(),
                "target": row.vessel_name,
            })

    rows.sort(key=lambda item: item.get("timestamp") or "", reverse=True)
    return rows[:limit]


def notification_priority(severity: str) -> str:
    severity = str(severity or "").lower()
    if severity == "critical":
        return "P1"
    if severity == "warning":
        return "P2"
    return "P3"


@app.get("/notifications/delivery-status")
def get_notification_delivery_status():
    channels = [
        {
            "channel": "outbox",
            "connected": True,
            "detail": "Writes delivery payloads to .runtime/notification_outbox.jsonl for local demos.",
        },
        {
            "channel": "webhook",
            "connected": bool(os.getenv("NOTIFICATION_WEBHOOK_URL")),
            "detail": "Set NOTIFICATION_WEBHOOK_URL to forward critical alert payloads from deployment middleware.",
        },
        {
            "channel": "email",
            "connected": bool(os.getenv("EMAIL_SMTP_HOST")),
            "detail": "Set EMAIL_SMTP_HOST and EMAIL_FROM before sending production email alerts.",
        },
        {
            "channel": "discord",
            "connected": bool(os.getenv("DISCORD_WEBHOOK_URL")),
            "detail": "Set DISCORD_WEBHOOK_URL for team-room alert delivery.",
        },
        {
            "channel": "telegram",
            "connected": bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")),
            "detail": "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID for mobile alert delivery.",
        },
    ]
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "channels": channels,
        "connected_channels": [channel["channel"] for channel in channels if channel["connected"]],
        "safe_default": "outbox",
        "production_note": "Outbound webhooks/email are environment-driven. Local demos always write an auditable outbox record.",
    }


@app.post("/notifications/deliver")
def deliver_notifications(
    payload: NotificationDeliveryRequest,
    db: Session = Depends(get_db),
    request: Request = None,
):
    require_any_permission(request, ["approve_actions", "manage_alert_workflows", "generate_reports"], "Notification delivery")
    severity_order = {"info": 0, "warning": 1, "critical": 2}
    threshold = severity_order.get(str(payload.severity or "critical").lower(), 2)
    rows = [
        row for row in get_notifications(limit=150, db=db)
        if severity_order.get(str(row.get("severity", "info")).lower(), 0) >= threshold
        and (not payload.target or payload.target.lower() in str(row.get("target", "")).lower())
    ]
    digest = notification_digest(limit=150, db=db) if payload.include_digest else {}
    delivery = {
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "channel": payload.channel,
        "severity_threshold": payload.severity,
        "target": payload.target or "all",
        "count": len(rows),
        "notifications": rows[:20],
        "digest": digest,
    }
    outbox_dir = ".runtime"
    os.makedirs(outbox_dir, exist_ok=True)
    outbox_path = os.path.join(outbox_dir, "notification_outbox.jsonl")
    with open(outbox_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(delivery, default=str) + "\n")
    channel_connected = payload.channel == "outbox" or bool(os.getenv(f"{payload.channel.upper()}_WEBHOOK_URL"))
    record_audit_event(
        db,
        action="notifications_delivered",
        resource=payload.channel,
        detail=f"Prepared {len(rows)} notification(s) at {payload.severity}+ for {payload.target or 'all targets'}.",
        severity="critical" if threshold >= 2 and rows else "warning",
        request=request,
    )
    db.commit()
    return {
        "status": "delivered_to_outbox" if payload.channel == "outbox" or not channel_connected else "prepared_for_external_channel",
        "channel": payload.channel,
        "connected": channel_connected,
        "outbox_path": outbox_path,
        "count": len(rows),
        "preview": rows[:5],
        "note": "External providers are intentionally environment-gated; the local outbox keeps a durable audit payload.",
    }


@app.get("/notifications/intelligence")
def get_notification_intelligence(limit: int = 120, db: Session = Depends(get_db)):
    rows = get_notifications(limit=limit, db=db)
    grouped: dict[str, dict] = {}
    for row in rows:
        target = row.get("target") or "Network"
        source = row.get("source") or "Unknown"
        key = f"{source}|{target}|{row.get('severity')}"
        entry = grouped.setdefault(key, {
            "target": target,
            "source": source,
            "severity": row.get("severity", "info"),
            "priority": notification_priority(row.get("severity")),
            "count": 0,
            "latest_title": row.get("title"),
            "latest_message": row.get("message"),
            "latest_timestamp": row.get("timestamp"),
            "group_key": key,
        })
        entry["count"] += 1
        if str(row.get("timestamp") or "") > str(entry.get("latest_timestamp") or ""):
            entry["latest_title"] = row.get("title")
            entry["latest_message"] = row.get("message")
            entry["latest_timestamp"] = row.get("timestamp")
    priority_weights = {"critical": 5, "warning": 2, "info": 0.5}
    pressure_score = min(100, round(sum(priority_weights.get(row.get("severity"), 0.5) for row in rows) * 4, 1))
    groups = sorted(grouped.values(), key=lambda item: ({"P1": 0, "P2": 1, "P3": 2}.get(item["priority"], 3), -item["count"]))
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "pressure_score": pressure_score,
        "pressure_band": "Critical" if pressure_score >= 70 else "Watch" if pressure_score >= 35 else "Normal",
        "total": len(rows),
        "counts": dict(Counter(row.get("severity", "info") for row in rows)),
        "groups": groups[:20],
        "top_actions": [
            {
                "priority": group["priority"],
                "target": group["target"],
                "action": "Escalate now" if group["priority"] == "P1" else "Keep on watch" if group["priority"] == "P2" else "Monitor",
                "why": f"{group['count']} signal(s) from {group['source']}: {group['latest_title']}",
            }
            for group in groups[:6]
        ],
    }


def inbox_priority_rank(priority: str) -> int:
    return {"P1": 0, "P2": 1, "P3": 2}.get(str(priority or "P3").upper(), 3)


def inbox_severity_score(severity: str) -> float:
    return {"critical": 92, "high": 84, "warning": 66, "medium": 58, "info": 34, "low": 28}.get(str(severity or "info").lower(), 34)


def inbox_item_id(*parts) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def build_inbox_item(
    item_type: str,
    priority: str,
    title: str,
    target: str,
    recommendation: str,
    why: str,
    source: str,
    page: str,
    severity: str = "warning",
    item_id: str | None = None,
    status: str = "open",
    owner: str = "Operations",
    impact_score: float | None = None,
    action_label: str = "Assign Owner",
) -> dict:
    impact = impact_score if impact_score is not None else inbox_severity_score(severity)
    priority = str(priority or "P3").upper()
    return {
        "item_id": item_id or inbox_item_id(item_type, priority, title, target, source),
        "item_type": item_type,
        "priority": priority,
        "severity": severity,
        "title": title,
        "target": target,
        "recommendation": recommendation,
        "why": why,
        "source": source,
        "page": page,
        "status": status,
        "owner": owner,
        "impact_score": round(float(impact), 1),
        "action_label": action_label,
    }


def build_operations_inbox(db: Session, limit: int = 60) -> dict:
    limit = max(10, min(limit, 150))
    generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    items: list[dict] = []

    notification_intel = get_notification_intelligence(limit=160, db=db)
    for group in notification_intel.get("groups", [])[:14]:
        priority = group.get("priority", "P3")
        severity = group.get("severity", "info")
        items.append(build_inbox_item(
            item_type="notification",
            priority=priority,
            severity=severity,
            title=group.get("latest_title") or "Notification cluster",
            target=group.get("target") or "Network",
            recommendation="Escalate now" if priority == "P1" else "Assign an owner and keep this on watch" if priority == "P2" else "Monitor",
            why=f"{group.get('count', 1)} signal(s) from {group.get('source', 'Unknown')}: {group.get('latest_message', '')}",
            source=group.get("source") or "Notifications",
            page="Notifications",
            item_id=group.get("group_key"),
            impact_score=inbox_severity_score(severity) + min(14, group.get("count", 1) * 2),
            action_label="Escalate" if priority == "P1" else "Assign Owner",
        ))

    actions = db.query(AIAction).filter(AIAction.status.in_(["queued", "approved"])).order_by(AIAction.updated_at.desc()).limit(40).all()
    for action in actions:
        severity = "critical" if action.priority == "P1" else "warning" if action.priority == "P2" else "info"
        items.append(build_inbox_item(
            item_type="ai_action",
            priority=action.priority,
            severity=severity,
            title=f"{action.priority} AI action waiting",
            target=action.subject,
            recommendation=action.recommendation,
            why=action.evidence or f"Queued by {action.source}.",
            source=action.source,
            page="Command Center",
            item_id=str(action.id),
            status=action.status,
            owner=action.owner,
            impact_score=inbox_severity_score(severity) + (8 if action.status == "approved" else 0),
            action_label="Complete" if action.status == "approved" else "Approve",
        ))

    incidents = db.query(IncidentEvent).filter(IncidentEvent.status.in_(["open", "investigating", "escalated"])).order_by(IncidentEvent.timestamp.desc()).limit(80).all()
    incident_groups: dict[str, dict] = {}
    for event in incidents:
        grouped_source = event.source in {"AI live feed", "Strategic Autopilot", "Auto Incident Commander"}
        key = f"{event.title}|{event.source}|{event.severity}" if grouped_source else f"incident-{event.id}"
        entry = incident_groups.setdefault(key, {
            "event": event,
            "count": 0,
            "targets": [],
            "latest_timestamp": event.timestamp,
        })
        entry["count"] += 1
        target = event.vessel_name or event.route or event.location
        if target and target not in entry["targets"]:
            entry["targets"].append(target)
        if event.timestamp and (entry.get("latest_timestamp") is None or event.timestamp > entry["latest_timestamp"]):
            entry["event"] = event
            entry["latest_timestamp"] = event.timestamp

    grouped_incidents = sorted(
        incident_groups.values(),
        key=lambda group: group.get("latest_timestamp") or datetime.datetime.min,
        reverse=True,
    )[:12]
    for group in grouped_incidents:
        event = group["event"]
        priority = "P1" if event.severity == "high" or event.status == "escalated" else "P2" if event.severity == "medium" else "P3"
        target = event.vessel_name or event.route or event.location
        if group["count"] > 1:
            target = ", ".join(group["targets"][:3]) + ("..." if len(group["targets"]) > 3 else "")
        items.append(build_inbox_item(
            item_type="incident",
            priority=priority,
            severity="critical" if priority == "P1" else "warning" if priority == "P2" else "info",
            title=event.title if group["count"] == 1 else f"{group['count']} related incidents: {event.title}",
            target=target,
            recommendation="Resolve or escalate the incident owner before release gates move forward.",
            why=event.description if group["count"] == 1 else f"{group['count']} open incident(s) from {event.source}; latest: {event.description}",
            source=event.source,
            page="Command Center",
            item_id=str(event.id) if group["count"] == 1 else inbox_item_id("incident-group", event.title, event.source, event.severity),
            status=event.status,
            owner="Incident commander",
            impact_score=inbox_severity_score("critical" if priority == "P1" else "warning") + (10 if event.status == "escalated" else 0),
            action_label="Resolve" if event.status == "escalated" else "Investigate",
        ))

    predictions = get_vessel_predictions(limit=80, db=db).get("predictions", [])
    for vessel in predictions[:12]:
        delay_risk = parse_float(vessel.get("delay_risk"), 0)
        if delay_risk < 6 and vessel.get("cargo_priority") != "P1":
            continue
        priority = "P1" if delay_risk >= 8 or vessel.get("cargo_priority") == "P1" else "P2"
        items.append(build_inbox_item(
            item_type="vessel",
            priority=priority,
            severity="critical" if priority == "P1" else "warning",
            title="Vessel delay / cargo exposure",
            target=vessel.get("vessel", "Vessel"),
            recommendation=vessel.get("recommended_action", "Assign fleet operator review."),
            why=f"Delay risk {delay_risk}/10 near {vessel.get('nearest_port')}; cargo {vessel.get('cargo')} ({vessel.get('cargo_priority')}).",
            source=vessel.get("source", "Fleet prediction"),
            page="Fleet & Operations",
            item_id=inbox_item_id("vessel", vessel.get("vessel"), vessel.get("route")),
            owner="Fleet controller",
            impact_score=delay_risk * 10,
            action_label="Review Vessel",
        ))

    quality = get_data_quality(db)
    for check in quality.get("checks", []):
        if check.get("status") == "pass":
            continue
        items.append(build_inbox_item(
            item_type="data_quality",
            priority="P2" if check.get("status") == "warn" else "P1",
            severity="warning" if check.get("status") == "warn" else "critical",
            title=f"Data quality: {check.get('name')}",
            target=check.get("name", "Data quality"),
            recommendation="Open Settings > Data and run maintenance or fix the provider before exporting reports.",
            why=check.get("detail", ""),
            source="Data Quality",
            page="Settings",
            owner="Platform admin",
            impact_score=100 - parse_float(quality.get("score"), 80),
            action_label="Open Data",
        ))

    production = get_production_mode(db)
    for check in production.get("checks", []):
        if check.get("status") == "pass":
            continue
        priority = "P1" if production.get("enabled") and check.get("status") == "fail" else "P2"
        items.append(build_inbox_item(
            item_type="security",
            priority=priority,
            severity="critical" if priority == "P1" else "warning",
            title=f"Production readiness: {check.get('name')}",
            target=check.get("name", "Production mode"),
            recommendation="Open Settings > Deployment and resolve the production hardening warning.",
            why=check.get("detail", ""),
            source="Production Mode",
            page="Settings",
            owner="Admin",
            impact_score=76 if priority == "P2" else 94,
            action_label="Harden",
        ))

    cleanup = get_data_cleanup_summary(db).get("summary", {})
    cleanup_pressure = cleanup.get("duplicate_manifest_groups", 0) + cleanup.get("generated_workflow_rows", 0) + min(25, cleanup.get("inferred_live_manifests", 0) // 250)
    if cleanup_pressure:
        items.append(build_inbox_item(
            item_type="maintenance",
            priority="P2",
            severity="warning",
            title="Database maintenance recommended",
            target="Data Stability",
            recommendation="Run Admin Data Maintenance with CLEAN DATA to reduce generated workflow and inferred cargo noise.",
            why=f"{cleanup.get('inferred_live_manifests', 0)} inferred cargo rows, {cleanup.get('generated_workflow_rows', 0)} generated workflow rows, {cleanup.get('duplicate_manifest_groups', 0)} duplicate groups.",
            source="Data Maintenance",
            page="Settings",
            owner="Admin",
            impact_score=60 + min(25, cleanup_pressure),
            action_label="Clean Data",
        ))

    items = sorted(items, key=lambda item: (inbox_priority_rank(item["priority"]), -item["impact_score"], item["title"]))[:limit]
    counts = Counter(item["priority"] for item in items)
    focus = items[0] if items else None
    inbox_score = max(
        0,
        100
        - min(70, counts.get("P1", 0) * 12)
        - min(24, counts.get("P2", 0) * 4)
        - min(8, counts.get("P3", 0) * 2),
    )
    return {
        "generated_at": generated_at,
        "summary": {
            "total": len(items),
            "p1": counts.get("P1", 0),
            "p2": counts.get("P2", 0),
            "p3": counts.get("P3", 0),
            "score": inbox_score,
            "band": "Clear" if inbox_score >= 85 else "Watch" if inbox_score >= 65 else "Command attention",
            "top_focus": focus.get("title") if focus else "No urgent focus",
        },
        "items": items,
        "quick_playbook": [
            "Handle P1 incidents/actions first, then stopped vessels carrying P1 cargo.",
            "Use Settings > Data before exporting if quality or cleanup items appear.",
            "Use Settings > Deployment before public demos if production/security warnings appear.",
            "Use Fleet & Operations for vessel-specific review and Risk & Alerts for route/watch-zone response.",
        ],
        "mobile_hint": "On phones, keep Mobile Command Mode on and work the top three cards only.",
    }


@app.get("/operations/inbox")
def get_operations_inbox(limit: int = 60, db: Session = Depends(get_db)):
    return build_operations_inbox(db, limit=limit)


@app.get("/settings/runtime")
def get_runtime_settings():
    return {
        "api_version": app.version,
        "app_mode": "production" if production_mode_enabled() else "demo",
        "ais_provider": os.getenv("AIS_PROVIDER", "demo"),
        "aisstream_enabled": get_aisstream_status().get("enabled"),
        "aisstream_status": get_aisstream_status(),
        "max_vessels": os.getenv("AISSTREAM_MAX_VESSELS", "12"),
        "stale_seconds": os.getenv("AISSTREAM_STALE_SECONDS", "900"),
        "configured_bounding_boxes": os.getenv("AISSTREAM_BOUNDING_BOXES", "default major-port boxes"),
        "available_regions": AIS_REGIONS,
        "runtime_note": "Update .env and restart backend to change AISStream provider, key, region boxes, or cache limits.",
    }


@app.get("/settings/production-mode")
def get_production_mode(db: Session = Depends(get_db)):
    enabled = production_mode_enabled()
    ais = get_aisstream_status()
    provider_status = get_auth_provider_status()
    connected_providers = [row["provider"] for row in provider_status.get("providers", []) if row.get("status") == "connected"]
    public_base_url = os.getenv("PUBLIC_BASE_URL", "")
    auth_mode = os.getenv("AUTH_MODE", "local role simulation")
    demo_count = db.query(UserAccount).filter(UserAccount.email.in_(DEMO_ACCOUNT_EMAILS)).count()
    ssl_status = ais.get("ssl_verification", "enabled")
    checks = [
        {
            "name": "Production flag",
            "status": "pass" if enabled else "warn",
            "detail": "APP_MODE/PRODUCTION_MODE is enforcing production controls." if enabled else "Running in local demo mode.",
        },
        {
            "name": "AIS SSL verification",
            "status": "pass" if ssl_status != "disabled-local-demo" else "fail" if enabled else "warn",
            "detail": "SSL verification is enforced." if ssl_status != "disabled-local-demo" else "Local demo SSL bypass is active.",
        },
        {
            "name": "Demo account login",
            "status": "pass" if enabled and not demo_accounts_allowed() else "warn" if enabled else "info",
            "detail": "Demo logins are blocked." if enabled and not demo_accounts_allowed() else f"{demo_count} demo account(s) remain usable.",
        },
        {
            "name": "External auth providers",
            "status": "pass" if connected_providers else "warn",
            "detail": ", ".join(connected_providers) if connected_providers else "No real OAuth/OIDC/WebAuthn provider env credentials found.",
        },
        {
            "name": "HTTPS public origin",
            "status": "pass" if public_base_url.startswith("https://") else "warn",
            "detail": public_base_url or "PUBLIC_BASE_URL is not set.",
        },
        {
            "name": "Auth mode",
            "status": "pass" if "external" in auth_mode.lower() or connected_providers else "warn",
            "detail": auth_mode,
        },
    ]
    warnings = [row["detail"] for row in checks if row["status"] in {"warn", "fail"}]
    return {
        "enabled": enabled,
        "app_mode": "production" if enabled else "demo",
        "runtime_only": True,
        "demo_accounts_allowed": demo_accounts_allowed(),
        "demo_accounts_count": demo_count,
        "auth_mode": auth_mode,
        "public_base_url": public_base_url,
        "ais_ssl_verification": ssl_status,
        "connected_auth_providers": connected_providers,
        "checks": checks,
        "warnings": warnings,
        "enforced_controls": [
            "Blocks built-in demo account login when production mode is enabled.",
            "Forces AISStream SSL verification even if the local demo bypass env var is present.",
            "Blocks public social-login simulation unless provider credentials are configured.",
            "Keeps live AIS cargo labeled as inferred until a verified manifest exists.",
        ],
        "persist_note": "Runtime switch updates this backend process. Set APP_MODE=production in .env or deployment secrets to persist after restart.",
    }


@app.post("/settings/production-mode")
def update_production_mode(
    payload: ProductionModeRequest,
    db: Session = Depends(get_db),
    request: Request = None,
):
    require_role(request, {"Admin"}, "Production mode")
    expected = "ENABLE PRODUCTION" if payload.enabled else "DISABLE PRODUCTION"
    if payload.confirm.strip().upper() != expected:
        raise HTTPException(status_code=400, detail=f"Type {expected} to apply this change")
    os.environ["APP_MODE"] = "production" if payload.enabled else "demo"
    os.environ["PRODUCTION_MODE"] = "true" if payload.enabled else "false"
    if payload.enabled:
        os.environ["AISSTREAM_ALLOW_INSECURE_SSL"] = "false"
    record_audit_event(
        db,
        action="production_mode_updated",
        resource="settings/production-mode",
        detail=f"Production mode set to {payload.enabled}.",
        severity="critical" if payload.enabled else "warning",
        request=request,
    )
    db.commit()
    return get_production_mode(db)


@app.get("/ais/reliability")
def get_ais_reliability(db: Session = Depends(get_db)):
    ais = get_aisstream_status()
    live_vessels = get_aisstream_vessels(limit=120) if ais.get("enabled") else []
    now = datetime.datetime.now(datetime.timezone.utc)
    stale_seconds = max(60, int(float(os.getenv("AISSTREAM_STALE_SECONDS", "900") or 900)))
    stale_count = 0
    stopped_count = 0
    newest_age = None
    ports = Counter()
    cargo = Counter()
    for vessel in live_vessels:
        ports[vessel.get("origin_port") or vessel.get("nearest_port") or "Unknown"] += 1
        cargo[vessel.get("cargo_class") or "Unknown"] += 1
        speed = parse_float(vessel.get("speed_knots"), 0)
        if speed <= 0.5:
            stopped_count += 1
        last_signal = parse_iso_datetime(vessel.get("last_signal_at"))
        if last_signal:
            age = max(0, (now - last_signal).total_seconds())
            newest_age = age if newest_age is None else min(newest_age, age)
            if age > stale_seconds:
                stale_count += 1
    checks = [
        {"name": "Provider selected", "status": "pass" if os.getenv("AIS_PROVIDER", "demo") == "aisstream" else "warn", "detail": os.getenv("AIS_PROVIDER", "demo")},
        {"name": "API key loaded", "status": "pass" if bool(os.getenv("AISSTREAM_API_KEY", "").strip()) else "fail", "detail": "Key present" if os.getenv("AISSTREAM_API_KEY", "").strip() else "Missing AISSTREAM_API_KEY"},
        {"name": "Websocket connected", "status": "pass" if ais.get("connected") else "warn", "detail": ais.get("last_error") or "Connected"},
        {"name": "Live vessel cache", "status": "pass" if ais.get("vessel_count", 0) > 0 else "warn", "detail": f"{ais.get('vessel_count', 0)} cached vessels"},
        {"name": "Signal freshness", "status": "pass" if not stale_count else "warn", "detail": f"{stale_count} stale live vessel(s)"},
        {"name": "SSL verification", "status": "warn" if ais.get("ssl_verification") == "disabled-local-demo" else "pass", "detail": ais.get("ssl_verification", "enabled")},
    ]
    score = 100
    score -= sum(28 for check in checks if check["status"] == "fail")
    score -= sum(9 for check in checks if check["status"] == "warn")
    score = max(0, score)
    return {
        "generated_at": now.isoformat(),
        "score": score,
        "status": "live" if score >= 85 else "watch" if score >= 65 else "fallback",
        "checks": checks,
        "summary": {
            "source": "AISStream" if live_vessels else "Fallback",
            "live_vessels": len(live_vessels),
            "stale_vessels": stale_count,
            "stopped_vessels": stopped_count,
            "newest_signal_age_seconds": round(newest_age, 1) if newest_age is not None else None,
            "ssl_verification": ais.get("ssl_verification", "enabled"),
        },
        "top_ports": [{"port": name, "vessels": count} for name, count in ports.most_common(8)],
        "cargo_classes": [{"cargo_class": name, "vessels": count} for name, count in cargo.most_common(8)],
        "recent_vessels": live_vessels[:12],
        "advice": [
            "Keep AISSTREAM_ALLOW_INSECURE_SSL=false in production.",
            "If vessel count drops to zero, confirm AISStream certificate status, network access, and bounding boxes.",
            "Use region presets to reduce websocket load on slow devices.",
        ],
    }


@app.post("/settings/runtime")
def update_runtime_settings(
    payload: RuntimeSettingsUpdate,
    db: Session = Depends(get_db),
    request: Request = None,
):
    require_permission(request, "tune_ais", "Runtime AIS tuning")
    applied = {}
    if payload.max_vessels is not None:
        max_vessels = max(1, min(int(payload.max_vessels), 100))
        os.environ["AISSTREAM_MAX_VESSELS"] = str(max_vessels)
        applied["AISSTREAM_MAX_VESSELS"] = max_vessels
    if payload.stale_seconds is not None:
        stale_seconds = max(60, min(int(payload.stale_seconds), 86400))
        os.environ["AISSTREAM_STALE_SECONDS"] = str(stale_seconds)
        applied["AISSTREAM_STALE_SECONDS"] = stale_seconds
    if payload.region:
        if payload.region not in AIS_REGIONS:
            raise HTTPException(status_code=400, detail="Unknown AIS region preset")
        if payload.region == "Global default lanes":
            os.environ.pop("AISSTREAM_BOUNDING_BOXES", None)
            applied["AISSTREAM_BOUNDING_BOXES"] = "default major-port boxes"
        else:
            os.environ["AISSTREAM_BOUNDING_BOXES"] = AIS_REGIONS[payload.region]
            applied["AISSTREAM_BOUNDING_BOXES"] = AIS_REGIONS[payload.region]
    if applied and hasattr(db, "add"):
        record_audit_event(
            db,
            action="runtime_settings_updated",
            resource="settings/runtime",
            detail=str(applied),
            severity="warning",
            request=request,
        )
        db.commit()
    return {
        "applied": applied,
        "restart_recommended": bool(payload.region),
        "settings": get_runtime_settings(),
    }


@app.get("/auth/roles")
def get_auth_roles():
    return {
        "roles": ROLE_SECURITY_POLICIES,
        "providers": AUTH_PROVIDER_CATALOG,
        "strict_mode": True,
        "production_mode": production_mode_enabled(),
        "default_role": "Public",
        "role_aliases": ROLE_ALIASES,
        "hardening_controls": AUTH_HARDENING_CONTROLS,
        "session_policy": {
            "admin_reauth_minutes": ROLE_SECURITY_POLICIES["Admin"]["auth"]["idle_timeout_minutes"],
            "max_public_session_minutes": ROLE_SECURITY_POLICIES["Public"]["auth"]["session_minutes"],
            "write_actions_require_verified_role": True,
            "production_auth_note": "Use HTTPS plus an external OIDC/WebAuthn provider before internet deployment.",
        },
        "auth_mode": os.getenv("AUTH_MODE", "local role simulation"),
        "recommendation": "Set AUTH_MODE=external_oidc_webauthn when connecting real Google/Facebook/OIDC/fingerprint providers.",
    }


@app.get("/auth/accounts")
def get_auth_accounts(db: Session = Depends(get_db)):
    ensure_demo_user_accounts(db)
    rows = db.query(UserAccount).order_by(UserAccount.role, UserAccount.email).all()
    demo_accounts_visible = demo_accounts_allowed()
    return {
        "accounts": [serialize_user_account(row) for row in rows],
        "demo_accounts": [
            {"email": seed["email"], "role": seed["role"], "password_hint": seed["password"]}
            for seed in DEMO_USER_ACCOUNTS
        ] if demo_accounts_visible else [],
        "production_mode": production_mode_enabled(),
        "demo_accounts_policy": "enabled for local demo" if demo_accounts_visible else "disabled in production mode",
    }


@app.post("/auth/register")
def register_auth_account(
    payload: AuthRegisterRequest,
    db: Session = Depends(get_db),
    request: Request = None,
):
    ensure_demo_user_accounts(db)
    email = normalize_email(payload.email)
    role = normalize_role(payload.role or "Public")
    provider = str(payload.provider or "Email Magic Link").strip()
    if role == "Admin":
        raise HTTPException(status_code=403, detail="Admin accounts are invite-only")
    if role not in ROLE_SECURITY_POLICIES:
        raise HTTPException(status_code=400, detail="Unknown role")
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Valid email required")
    if len(payload.password or "") < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if not auth_provider_allowed(role, provider):
        raise HTTPException(status_code=400, detail=f"{provider} is not allowed for {role}")
    if role == "Operator" and not (payload.mfa_code and payload.mfa_code.isdigit() and len(payload.mfa_code) == 6):
        raise HTTPException(status_code=400, detail="Operator role requires a 6-digit MFA/passkey code")
    if db.query(UserAccount).filter(UserAccount.email == email).first():
        raise HTTPException(status_code=409, detail="Account already exists")
    now = datetime.datetime.now(datetime.timezone.utc)
    account = UserAccount(
        email=email,
        display_name=(payload.display_name or email).strip(),
        role=role,
        provider=provider,
        password_hash=password_digest(payload.password),
        status="active",
        created_at=now,
        last_login_at=now,
    )
    db.add(account)
    record_audit_event(
        db,
        action="account_registered",
        resource=email,
        detail=f"{role} account registered with {provider}.",
        severity="info",
        request=request,
    )
    db.commit()
    db.refresh(account)
    return auth_response(account, f"created account with {provider}")


@app.post("/auth/login")
def login_auth_account(
    payload: AuthLoginRequest,
    db: Session = Depends(get_db),
    request: Request = None,
):
    ensure_demo_user_accounts(db)
    email = normalize_email(payload.email)
    account = db.query(UserAccount).filter(UserAccount.email == email).first()
    if not account or account.status != "active":
        raise HTTPException(status_code=401, detail="Account not found or inactive")
    account.role = normalize_role(account.role)
    if production_mode_enabled() and email in DEMO_ACCOUNT_EMAILS and not env_truthy("ALLOW_DEMO_ACCOUNTS_IN_PRODUCTION"):
        raise HTTPException(status_code=403, detail="Demo accounts are disabled in production mode")
    if payload.role and account.role != normalize_role(payload.role):
        raise HTTPException(status_code=403, detail=f"Account is registered as {account.role}")
    if payload.provider and payload.provider != account.provider and not auth_provider_allowed(account.role, payload.provider):
        raise HTTPException(status_code=403, detail=f"{payload.provider} is not allowed for {account.role}")
    if password_digest(payload.password or "") != account.password_hash:
        raise HTTPException(status_code=401, detail="Invalid password")
    if account.role == "Admin":
        if not payload.biometric_ok or str(payload.phrase or "").strip().upper() != "ADMIN ACCESS":
            raise HTTPException(status_code=403, detail="Admin login requires fingerprint and ADMIN ACCESS phrase")
    if account.role == "Operator":
        if not (payload.mfa_code and payload.mfa_code.isdigit() and len(payload.mfa_code) == 6):
            raise HTTPException(status_code=403, detail="Operator login requires 6-digit MFA/passkey")
    account.last_login_at = datetime.datetime.now(datetime.timezone.utc)
    record_audit_event(
        db,
        action="account_login",
        resource=email,
        detail=f"{account.role} logged in with {payload.provider or account.provider}.",
        severity="info",
        request=request,
    )
    db.commit()
    db.refresh(account)
    provider = payload.provider or account.provider
    method = f"{provider} + password"
    if account.role == "Admin":
        method += " + fingerprint + admin phrase"
    elif account.role == "Operator":
        method += " + MFA"
    return auth_response(account, method)


@app.post("/auth/social-login")
def social_auth_login(
    payload: AuthSocialRequest,
    db: Session = Depends(get_db),
    request: Request = None,
):
    provider = str(payload.provider or "").strip()
    if not auth_provider_allowed("Public", provider):
        raise HTTPException(status_code=403, detail="Provider is not allowed for public login")
    if production_mode_enabled() and not auth_provider_connected(provider):
        raise HTTPException(status_code=403, detail=f"{provider} is not connected for production login")
    identity = normalize_email(payload.identity or f"{provider.lower().replace(' ', '.')}@public.demo")
    now = datetime.datetime.now(datetime.timezone.utc)
    account = db.query(UserAccount).filter(UserAccount.email == identity).first()
    if not account:
        account = UserAccount(
            email=identity,
            display_name=provider,
            role="Public",
            provider=provider,
            password_hash=password_digest(f"social:{provider}:{identity}"),
            status="active",
            created_at=now,
            last_login_at=now,
        )
        db.add(account)
    else:
        account.last_login_at = now
        account.provider = provider
        account.role = "Public"
    record_audit_event(
        db,
        action="public_social_login",
        resource=identity,
        detail=f"Public logged in with {provider}.",
        severity="info",
        request=request,
    )
    db.commit()
    db.refresh(account)
    return auth_response(account, f"{provider} public login")


@app.post("/auth/session/validate")
def validate_auth_session(
    payload: AuthSessionValidateRequest,
    db: Session = Depends(get_db),
):
    session_payload = decode_auth_session_token(payload.token)
    account = db.query(UserAccount).filter(UserAccount.email == normalize_email(session_payload.get("email"))).first()
    if not account or account.status != "active":
        raise HTTPException(status_code=401, detail="Session account not found or inactive")
    account.role = normalize_role(account.role)
    if account.role != normalize_role(session_payload.get("role")):
        raise HTTPException(status_code=401, detail="Session role mismatch")
    return {
        "account": serialize_user_account(account),
        "method": "restored signed session",
        "session_token": payload.token,
        "session_expires_at": session_payload.get("exp"),
    }


@app.get("/auth/provider-status")
def get_auth_provider_status():
    rows = []
    for provider, meta in AUTH_PROVIDER_CATALOG.items():
        required = AUTH_PROVIDER_ENV_REQUIREMENTS.get(provider, [])
        missing = [name for name in required if not os.getenv(name)]
        rows.append({
            "provider": provider,
            "label": meta.get("label", provider),
            "type": meta.get("provider_type"),
            "status": "connected" if required and not missing else "demo-only" if missing else "local",
            "missing_env": ", ".join(missing) if missing else "",
            "production_setup": meta.get("external_setup", ""),
        })
    return {
        "auth_mode": os.getenv("AUTH_MODE", "local role simulation"),
        "production_mode": production_mode_enabled(),
        "providers": rows,
        "production_note": "Demo buttons simulate login. Real deployment needs provider credentials, HTTPS callback URLs, and server-side token verification.",
    }


@app.get("/admin/users")
def get_admin_users(db: Session = Depends(get_db), request: Request = None):
    require_role(request, {"Admin"}, "User management")
    ensure_demo_user_accounts(db)
    accounts = [serialize_user_account(row) for row in db.query(UserAccount).order_by(UserAccount.role, UserAccount.email).all()]
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "accounts": accounts,
        "summary": {
            "total": len(accounts),
            "active": sum(1 for account in accounts if account.get("status") == "active"),
            "disabled": sum(1 for account in accounts if account.get("status") != "active"),
            "roles": dict(Counter(account.get("role") for account in accounts)),
        },
        "rules": [
            "Only Admin can create, disable, promote, or demote accounts.",
            "New Admin accounts require the ADMIN USER confirmation phrase.",
            "Operator accounts require a password plus 6-digit MFA/passkey during login.",
            "Public accounts remain read-only even when social providers are connected.",
        ],
    }


@app.post("/admin/users")
def upsert_admin_user(
    payload: UserAccountAdminRequest,
    db: Session = Depends(get_db),
    request: Request = None,
):
    require_role(request, {"Admin"}, "User management")
    email = normalize_email(payload.email)
    role = normalize_role(payload.role)
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Valid email required")
    if role == "Admin" and payload.confirm.strip().upper() != "ADMIN USER":
        raise HTTPException(status_code=400, detail="Type ADMIN USER to create or promote Admin accounts")
    if role == "Operator" and payload.mfa_code and not (payload.mfa_code.isdigit() and len(payload.mfa_code) == 6):
        raise HTTPException(status_code=400, detail="Operator MFA/passkey must be 6 digits")
    if payload.status not in {"active", "disabled"}:
        raise HTTPException(status_code=400, detail="Status must be active or disabled")

    now = datetime.datetime.now(datetime.timezone.utc)
    account = db.query(UserAccount).filter(UserAccount.email == email).first()
    provider = account_provider_for_role(role, payload.provider)
    if account:
        account.display_name = (payload.display_name or account.display_name or email).strip()
        account.role = role
        account.provider = provider
        account.status = payload.status
        if payload.password:
            if len(payload.password) < 6:
                raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
            account.password_hash = password_digest(payload.password)
    else:
        if not payload.password or len(payload.password) < 6:
            raise HTTPException(status_code=400, detail="New users need a password with at least 6 characters")
        account = UserAccount(
            email=email,
            display_name=(payload.display_name or email).strip(),
            role=role,
            provider=provider,
            password_hash=password_digest(payload.password),
            status=payload.status,
            created_at=now,
            last_login_at=None,
        )
        db.add(account)
    record_audit_event(
        db,
        action="admin_user_upserted",
        resource=email,
        detail=f"User set to role={role}, provider={provider}, status={payload.status}.",
        severity="critical" if role == "Admin" else "warning",
        request=request,
    )
    db.commit()
    db.refresh(account)
    return serialize_user_account(account)


@app.get("/security/audit-summary")
def get_security_audit_summary(limit: int = 120, db: Session = Depends(get_db), request: Request = None):
    require_any_permission(request, ["view_quality", "tune_ais", "approve_actions"], "Security audit dashboard")
    limit = max(20, min(limit, 500))
    rows = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit).all()
    now = datetime.datetime.now(datetime.timezone.utc)
    last_day = now - datetime.timedelta(hours=24)
    recent = [row for row in rows if row.timestamp and (row.timestamp.replace(tzinfo=datetime.timezone.utc) if row.timestamp.tzinfo is None else row.timestamp) >= last_day]
    action_counts = Counter(row.action for row in rows)
    role_counts = Counter(row.actor_role for row in rows)
    severity_counts = Counter(row.severity for row in rows)
    risky_actions = [
        row for row in rows
        if row.severity in {"critical", "warning"} or any(token in row.action for token in ["login", "production", "cleanup", "user", "autopilot"])
    ]
    return {
        "generated_at": now.isoformat(),
        "summary": {
            "events_scanned": len(rows),
            "events_24h": len(recent),
            "critical": severity_counts.get("critical", 0),
            "warning": severity_counts.get("warning", 0),
            "unique_actors": len(role_counts),
        },
        "severity_counts": dict(severity_counts),
        "role_counts": dict(role_counts),
        "top_actions": [{"action": action, "count": count} for action, count in action_counts.most_common(10)],
        "risky_events": [serialize_audit_log(row) for row in risky_actions[:25]],
        "recommendations": [
            "Review critical Admin events before production demos.",
            "Disable stale accounts from Settings > Users.",
            "Keep production mode disabled until HTTPS and real providers are connected.",
            "Export a mission pack after major incident or role changes.",
        ],
    }


def database_runtime_path() -> str | None:
    url = str(engine.url)
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "", 1)
    return None


@app.get("/database/operations")
def get_database_operations(db: Session = Depends(get_db), request: Request = None):
    require_any_permission(request, ["view_quality", "tune_ais"], "Database operations")
    url = str(engine.url)
    sqlite_path = database_runtime_path()
    backup_dir = os.path.join(".runtime", "backups")
    latest_backup = None
    if os.path.isdir(backup_dir):
        backups = sorted(
            [os.path.join(backup_dir, name) for name in os.listdir(backup_dir) if name.endswith(".db")],
            key=lambda path: os.path.getmtime(path),
            reverse=True,
        )
        latest_backup = backups[0] if backups else None
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "database_type": "sqlite" if "sqlite" in url else "postgresql" if "postgres" in url else "other",
        "runtime_path": sqlite_path or "external database",
        "backup_supported": bool(sqlite_path and os.path.exists(sqlite_path)),
        "latest_backup": latest_backup,
        "records": health(db).get("database", {}).get("records", {}),
        "checks": [
            {"name": "Runtime database", "status": "pass" if db.query(TradeRoute).count() else "fail", "detail": "Seeded routes available."},
            {"name": "Migrations", "status": "pass" if os.path.exists("alembic.ini") else "warn", "detail": "Alembic scaffold present." if os.path.exists("alembic.ini") else "Add Alembic before production."},
            {"name": "Backup path", "status": "pass" if sqlite_path else "warn", "detail": sqlite_path or "Use managed PostgreSQL backups."},
            {"name": "PostgreSQL mode", "status": "pass" if "postgres" in url else "warn", "detail": "PostgreSQL configured." if "postgres" in url else "SQLite is fine for demo; use PostgreSQL for production."},
        ],
        "recommendations": [
            "Use PostgreSQL for production deployments.",
            "Run a backup before data cleanup or production-mode demos.",
            "Keep Alembic migrations in sync with model changes.",
        ],
    }


@app.post("/database/backup")
def create_database_backup(
    payload: DatabaseBackupRequest,
    db: Session = Depends(get_db),
    request: Request = None,
):
    require_role(request, {"Admin"}, "Database backup")
    if payload.confirm.strip().upper() != "BACKUP DATABASE":
        raise HTTPException(status_code=400, detail="Type BACKUP DATABASE to create a runtime backup")
    sqlite_path = database_runtime_path()
    if not sqlite_path or not os.path.exists(sqlite_path):
        raise HTTPException(status_code=400, detail="Automatic backup is only supported for local SQLite runtime database")
    backup_dir = os.path.join(".runtime", "backups")
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"trade_intelligence_{stamp}.db")
    shutil.copy2(sqlite_path, backup_path)
    record_audit_event(
        db,
        action="database_backup_created",
        resource="runtime_database",
        detail=f"Created SQLite backup at {backup_path}.",
        severity="warning",
        request=request,
    )
    db.commit()
    return {
        "status": "created",
        "backup_path": backup_path,
        "source_path": sqlite_path,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


@app.get("/external-data/status")
def get_external_data_status():
    providers = [
        {"name": "Weather API", "env": "WEATHER_API_KEY", "connected": bool(os.getenv("WEATHER_API_KEY")), "used_for": "Maritime weather risk"},
        {"name": "Port congestion API", "env": "PORT_CONGESTION_API_KEY", "connected": bool(os.getenv("PORT_CONGESTION_API_KEY")), "used_for": "Berth/queue pressure"},
        {"name": "Maritime security API", "env": "MARITIME_SECURITY_API_KEY", "connected": bool(os.getenv("MARITIME_SECURITY_API_KEY")), "used_for": "Piracy/geopolitical watch"},
        {"name": "Notification webhook", "env": "NOTIFICATION_WEBHOOK_URL", "connected": bool(os.getenv("NOTIFICATION_WEBHOOK_URL")), "used_for": "Outbound critical alert delivery"},
        {"name": "Email SMTP", "env": "EMAIL_SMTP_HOST", "connected": bool(os.getenv("EMAIL_SMTP_HOST")), "used_for": "Password reset / critical email"},
    ]
    connected = sum(1 for provider in providers if provider["connected"])
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "connected": connected,
        "total": len(providers),
        "mode": "external-ready" if connected else "demo-fallback",
        "providers": providers,
        "note": "Provider hooks are environment-driven. When keys are absent, the app keeps using transparent simulated fallback signals.",
    }


@app.get("/setup/checklist")
def get_setup_checklist(db: Session = Depends(get_db)):
    health_packet = health(db)
    ais = get_ais_reliability(db)
    providers = get_auth_provider_status()
    external = get_external_data_status()
    database = get_database_operations(db=db)
    delivery = get_notification_delivery_status()
    production = get_production_mode(db)
    rows = [
        {"area": "Backend", "status": "pass" if health_packet.get("status") == "healthy" else "fail", "detail": "FastAPI is healthy."},
        {"area": "Database", "status": "pass" if database.get("records", {}).get("routes", 0) else "fail", "detail": f"{database.get('database_type')} runtime with {database.get('records', {}).get('routes', 0)} routes."},
        {"area": "AIS", "status": "pass" if ais.get("status") == "live" else "warn", "detail": f"{ais.get('summary', {}).get('live_vessels', 0)} live AIS vessels."},
        {"area": "Roles", "status": "pass", "detail": "Admin, Operator, and Public roles are active."},
        {"area": "Auth providers", "status": "pass" if providers.get("connected_providers") else "warn", "detail": f"{len(providers.get('connected_providers', []))} external provider(s) connected."},
        {"area": "Notifications", "status": "pass" if delivery.get("connected_channels") else "warn", "detail": "Outbox is always available; connect webhook/email for production."},
        {"area": "External data", "status": "pass" if external.get("connected") else "warn", "detail": f"{external.get('connected')}/{external.get('total')} external data provider(s) connected."},
        {"area": "Production mode", "status": "pass" if production.get("enabled") else "warn", "detail": production.get("app_mode", "demo")},
    ]
    score = 100
    score -= sum(20 for row in rows if row["status"] == "fail")
    score -= sum(7 for row in rows if row["status"] == "warn")
    score = max(0, score)
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "score": score,
        "band": "Ready" if score >= 90 else "Demo ready" if score >= 75 else "Needs setup",
        "checks": rows,
        "quick_start": [
            "Sign in as Admin or Operator.",
            "Confirm AIS provider status in Settings > AIS.",
            "Open Command Center > Voyage Control Tower.",
            "Use Settings > Delivery to send a critical outbox digest.",
            "Generate Reports > Final Mission Pack when the operating picture is stable.",
        ],
    }


@app.get("/weather/maritime")
def get_maritime_weather(db: Session = Depends(get_db)):
    alerts = db.query(ThreatAlert).order_by(ThreatAlert.id.desc()).limit(50).all()
    rows = []
    for port, coords in PORT_COORDS.items():
        alert_pressure = sum(
            1 for alert in alerts
            if port.lower() in f"{alert.title} {alert.description} {alert.location}".lower()
            or any(token in f"{alert.title} {alert.description}".lower() for token in ["weather", "storm", "cyclone"])
        )
        wind = 12 + ((len(port) * 7) % 22) + (alert_pressure * 4)
        wave = round(1.2 + ((len(port) % 5) * 0.55) + (alert_pressure * 0.7), 1)
        score = clamp_percent((wind * 1.4) + (wave * 8) + (alert_pressure * 12))
        rows.append({
            "port": port,
            "lat": coords[0],
            "lon": coords[1],
            "wind_knots": round(wind, 1),
            "wave_meters": wave,
            "weather_score": score,
            "band": mission_band(score),
            "recommended_control": "Delay departure / reroute weather lane" if score >= 70 else "Add weather buffer" if score >= 40 else "Normal weather watch",
        })
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source": "External weather provider hook" if os.getenv("WEATHER_API_KEY") else "Simulated fallback from alerts and port profile",
        "provider_connected": bool(os.getenv("WEATHER_API_KEY")),
        "ports": sorted(rows, key=lambda row: row["weather_score"], reverse=True),
    }


@app.get("/deployment/hardening")
def get_deployment_hardening(db: Session = Depends(get_db)):
    readiness = get_deployment_readiness(db)
    provider_status = get_auth_provider_status()
    checks = list(readiness.get("checks", []))
    checks.extend([
        {
            "name": "Secret storage",
            "status": "pass" if os.getenv("AISSTREAM_API_KEY") and os.getenv("AUTH_DEMO_SALT") else "warn",
            "detail": "Move AIS/auth secrets to deployment secret storage.",
        },
        {
            "name": "External auth providers",
            "status": "pass" if any(row["status"] == "connected" for row in provider_status["providers"]) else "warn",
            "detail": "OAuth/WebAuthn providers are currently demo/local unless env credentials are set.",
        },
        {
            "name": "HTTPS boundary",
            "status": "pass" if os.getenv("PUBLIC_BASE_URL", "").startswith("https://") else "warn",
            "detail": "Set PUBLIC_BASE_URL to an HTTPS origin before internet deployment.",
        },
        {
            "name": "AIS SSL verification",
            "status": "warn" if get_aisstream_status().get("ssl_verification") == "disabled-local-demo" else "pass",
            "detail": "Local demo SSL verification bypass is enabled." if get_aisstream_status().get("ssl_verification") == "disabled-local-demo" else "AISStream SSL verification is enabled.",
        },
        {
            "name": "Production mode",
            "status": "pass" if production_mode_enabled() else "warn",
            "detail": "Production controls are enforced." if production_mode_enabled() else "Local demo controls are active; enable production mode before public deployment.",
        },
    ])
    hardening_score = 100
    hardening_score -= sum(20 for check in checks if check["status"] == "fail")
    hardening_score -= sum(8 for check in checks if check["status"] == "warn")
    hardening_score = max(0, hardening_score)
    return {
        "score": hardening_score,
        "status": "hardened" if hardening_score >= 90 else "needs secrets" if hardening_score >= 75 else "needs hardening",
        "checks": checks,
        "hardening_steps": [
            "Use Alembic migrations for schema changes.",
            "Put FastAPI behind HTTPS with trusted CORS origins.",
            "Store OAuth, AIS, and WebAuthn secrets outside the repo.",
            "Use real OIDC/WebAuthn token verification before production.",
            "Keep Public on sanitized read-only routes.",
        ],
    }


@app.get("/system/reliability")
def get_system_reliability(db: Session = Depends(get_db)):
    health_packet = health(db)
    ais = get_ais_reliability(db)
    quality = get_data_quality(db)
    readiness = get_deployment_readiness(db)
    hardening = get_deployment_hardening(db)
    production = get_production_mode(db)
    cleanup = get_data_cleanup_summary(db)
    inbox = build_operations_inbox(db, limit=30)
    database_records = health_packet.get("database", {}).get("records", {})
    checks = [
        {"name": "Backend API", "status": "pass" if health_packet.get("status") == "healthy" else "warn", "detail": health_packet.get("status")},
        {"name": "AIS live feed", "status": "pass" if ais.get("status") == "live" else "warn", "detail": f"{ais.get('summary', {}).get('live_vessels', 0)} live vessels"},
        {"name": "Data quality", "status": quality.get("status", "warn"), "detail": f"{quality.get('score', 0)}%"},
        {"name": "Deployment readiness", "status": "pass" if readiness.get("score", 0) >= 85 else "warn", "detail": f"{readiness.get('score', 0)}% {readiness.get('status')}"},
        {"name": "Security hardening", "status": "pass" if hardening.get("score", 0) >= 90 else "warn", "detail": f"{hardening.get('score', 0)}% {hardening.get('status')}"},
        {"name": "Production mode", "status": "pass" if production.get("enabled") else "warn", "detail": production.get("app_mode", "demo")},
        {"name": "Smart inbox", "status": "pass" if inbox.get("summary", {}).get("score", 0) >= 75 else "warn", "detail": f"{inbox.get('summary', {}).get('total', 0)} active item(s)"},
    ]
    score = 100
    score -= sum(18 for check in checks if check["status"] == "fail")
    score -= sum(7 for check in checks if check["status"] == "warn")
    score = max(0, score)
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "score": score,
        "band": "Excellent" if score >= 90 else "Stable" if score >= 75 else "Needs attention",
        "checks": checks,
        "records": database_records,
        "signals": {
            "ais": ais.get("summary", {}),
            "quality": {"score": quality.get("score"), "status": quality.get("status")},
            "deployment": {"readiness": readiness.get("score"), "hardening": hardening.get("score")},
            "production_mode": production.get("enabled"),
            "cleanup": cleanup.get("summary", {}),
            "inbox": inbox.get("summary", {}),
        },
        "recommendations": [
            "Work Smart Inbox P1/P2 items before switching pages.",
            "Keep Mobile Command Mode on for phones or slower laptops.",
            "Run Admin Data Maintenance before exporting final reports if cleanup warnings are present.",
            "Enable production mode only after real OAuth/WebAuthn providers and HTTPS are configured.",
        ],
    }


@app.post("/demo/reset")
def reset_demo_state(
    payload: DemoResetRequest | None = None,
    db: Session = Depends(get_db),
    request: Request = None,
):
    require_role(request, {"Admin"}, "Demo reset")
    if request is not None and (payload is None or payload.confirm.strip().upper() != "RESET DEMO"):
        raise HTTPException(status_code=400, detail="Type RESET DEMO to reset generated workflow state")
    ensure_demo_user_accounts(db)
    db.query(AIAction).filter(AIAction.source.in_(["War Room", "Incident workflow", "Command assignment"])).delete(synchronize_session=False)
    db.query(IncidentEvent).filter(IncidentEvent.source.in_(["War Room", "Auto Incident Commander", "Incident workflow"])).delete(synchronize_session=False)
    record_audit_event(
        db,
        action="demo_reset",
        resource="demo_state",
        detail="Demo command actions and generated incident workflow rows reset.",
        severity="warning",
        request=request,
    )
    db.commit()
    return {
        "status": "reset",
        "demo_accounts": [seed["email"] for seed in DEMO_USER_ACCOUNTS],
        "note": "Seed data remains; generated command workflow rows were cleared.",
    }


@app.get("/audit-log")
def get_audit_log(limit: int = 80, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 300))
    rows = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit).all()
    return {
        "events": [serialize_audit_log(row) for row in rows],
        "summary": {
            "total": db.query(AuditLog).count(),
            "critical": db.query(AuditLog).filter(AuditLog.severity == "critical").count(),
            "warning": db.query(AuditLog).filter(AuditLog.severity == "warning").count(),
        },
    }


@app.post("/audit-log")
def create_audit_log_event(
    payload: AuditEventCreate,
    db: Session = Depends(get_db),
    request: Request = None,
):
    event = record_audit_event(
        db,
        action=payload.action,
        resource=payload.resource,
        detail=payload.detail,
        severity=payload.severity,
        request=request,
    )
    if payload.actor_role != "System" or payload.actor_identity != "Backend":
        event.actor_role = payload.actor_role
        event.actor_identity = payload.actor_identity
    db.commit()
    db.refresh(event)
    return serialize_audit_log(event)


def active_alert_workflow(alert: ThreatAlert, events: list[IncidentEvent]) -> dict:
    prefix = f"Alert workflow #{alert.id}"
    related = [
        event for event in events
        if str(event.title or "").startswith(prefix)
    ]
    latest = sorted(related, key=lambda event: event.timestamp or datetime.datetime.min, reverse=True)
    if latest:
        event = latest[0]
        return {
            "alert_id": alert.id,
            "title": alert.title,
            "severity": alert.severity,
            "location": alert.location,
            "workflow_status": event.status,
            "owner": event.source,
            "note": event.description,
            "updated_at": event.timestamp.isoformat() if event.timestamp else None,
        }
    return {
        "alert_id": alert.id,
        "title": alert.title,
        "severity": alert.severity,
        "location": alert.location,
        "workflow_status": "new",
        "owner": "Unassigned",
        "note": alert.description,
        "updated_at": None,
    }


@app.get("/alerts/workflows")
def get_alert_workflows(db: Session = Depends(get_db)):
    alerts = get_alerts(db)
    events = db.query(IncidentEvent).order_by(IncidentEvent.timestamp.desc()).limit(300).all()
    return [active_alert_workflow(alert, events) for alert in alerts]


@app.post("/alerts/{alert_id}/workflow")
def update_alert_workflow(
    alert_id: int,
    payload: AlertWorkflowUpdate,
    db: Session = Depends(get_db),
    request: Request = None,
):
    require_permission(request, "manage_alert_workflows", "Alert workflow updates")
    allowed = {"new", "investigating", "escalated", "resolved"}
    status = payload.status.lower().strip()
    if status not in allowed:
        raise HTTPException(status_code=400, detail=f"Status must be one of {sorted(allowed)}")
    alert = db.query(ThreatAlert).filter(ThreatAlert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    now = datetime.datetime.now(datetime.timezone.utc)
    event = IncidentEvent(
        title=f"Alert workflow #{alert.id}: {alert.title}",
        category="Alert workflow",
        severity=alert.severity,
        location=alert.location,
        vessel_name="",
        route="",
        description=payload.note or f"Alert moved to {status}.",
        source=payload.owner,
        status=status,
        timestamp=now,
    )
    db.add(event)
    if status in {"investigating", "escalated"}:
        upsert_ai_action(
            db,
            subject=f"Alert #{alert.id}: {alert.title}",
            priority="P1" if alert.severity == "high" or status == "escalated" else "P2",
            action_type="Alert workflow",
            recommendation=f"{payload.owner} to handle alert workflow status: {status}.",
            evidence=payload.note or alert.description,
            owner=payload.owner,
            source="Alert escalation",
        )
    record_audit_event(
        db,
        action="alert_workflow_updated",
        resource=f"Alert #{alert.id}: {alert.title}",
        detail=f"{payload.owner} moved alert to {status}. {payload.note or alert.description}",
        severity="critical" if status == "escalated" or alert.severity == "high" else "warning",
        request=request,
    )
    db.commit()
    return active_alert_workflow(alert, [event])


def route_assessment_lookup(db: Session) -> dict[str, dict]:
    routes = unique_by(
        db.query(TradeRoute).order_by(TradeRoute.id).all(),
        lambda route: (route.origin_port, route.destination_port),
    )
    alerts = unique_by(
        db.query(ThreatAlert).order_by(ThreatAlert.id.desc()).all(),
        lambda alert: (alert.title, alert.location, alert.severity),
    )
    assessments = build_route_assessments(routes, alerts)
    return {item["route"]: item for item in assessments}


@app.get("/vessels/predictions")
def get_vessel_predictions(limit: int = 50, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 200))
    vessels, source = get_operational_vessels(db)
    assessments = route_assessment_lookup(db)
    rows = []
    for vessel in vessels[:limit]:
        speed = max(parse_float(vessel.get("speed_knots"), 12), 1)
        progress = max(0.0, min(1.0, parse_float(vessel.get("progress"), 0)))
        route_name = str(vessel.get("route") or f"{vessel.get('origin_port', 'Unknown')} to {vessel.get('destination_port', 'Unknown')}")
        route_assessment = assessments.get(route_name)
        base_distance = 900.0
        for candidate in db.query(TradeRoute).all():
            candidate_name = f"{candidate.origin_port} to {candidate.destination_port}"
            if candidate_name == route_name:
                base_distance = float(candidate.distance or base_distance)
                break
        remaining_nm = max(20.0, base_distance * (1 - progress))
        eta_hours = parse_float(vessel.get("eta_hours"), remaining_nm / speed)
        cargo_priority = effective_vessel_cargo_priority(vessel)
        route_risk = float(route_assessment["score"]) if route_assessment else 4.5
        delay_score = route_risk
        delay_score += {"P1": 1.5, "P2": 0.8, "P3": 0.2}.get(cargo_priority, 0.2)
        if speed <= 3:
            delay_score += 2.0
        if vessel_status(vessel) != "active":
            delay_score += 2.5
        delay_score = round(max(0.0, min(10.0, delay_score)), 2)
        rows.append({
            "vessel": str(vessel.get("name") or vessel_identifier(vessel)),
            "source": str(vessel.get("source") or source),
            "route": route_name,
            "nearest_port": nearest_port(vessel_display_lat(vessel), vessel_display_lon(vessel)),
            "speed_knots": round(speed, 1),
            "eta_hours": round(eta_hours, 1),
            "delay_risk": delay_score,
            "delay_band": risk_band(delay_score),
            "cargo": str(vessel.get("cargo") or "Unknown"),
            "cargo_priority": cargo_priority,
            "cargo_source": str(vessel.get("cargo_source") or "Unknown"),
            "cargo_verified": bool(vessel.get("cargo_verified", False)),
            "recommended_action": route_decision(delay_score),
            "position_lat": vessel_lat(vessel),
            "position_lon": vessel_lon(vessel),
            "display_position_lat": vessel_display_lat(vessel),
            "display_position_lon": vessel_display_lon(vessel),
            "api_position_lat": vessel.get("api_position_lat", vessel_lat(vessel)),
            "api_position_lon": vessel.get("api_position_lon", vessel_lon(vessel)),
            "motion_source": vessel.get("motion_source", source),
            "motion_trail": vessel.get("motion_trail", [[vessel_lon(vessel), vessel_lat(vessel)], [vessel_display_lon(vessel), vessel_display_lat(vessel)]]),
            "heading": parse_float(vessel.get("heading"), 0),
        })
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source": source,
        "predictions": sorted(rows, key=lambda row: row["delay_risk"], reverse=True),
    }


@app.get("/replay/timeline")
def get_replay_timeline(limit: int = 200, db: Session = Depends(get_db)):
    limit = max(20, min(limit, 500))
    rows = []
    for row in db.query(AISPositionHistory).order_by(AISPositionHistory.timestamp.desc()).limit(limit).all():
        rows.append({
            "timestamp": row.timestamp.isoformat() if row.timestamp else None,
            "type": "AIS position",
            "severity": "info",
            "subject": row.vessel_name,
            "description": f"{row.vessel_name} at {row.speed_knots:.1f} kn near {row.nearest_port}.",
            "lat": row.position_lat,
            "lon": row.position_lon,
            "source": row.source,
        })
    for event in db.query(IncidentEvent).order_by(IncidentEvent.timestamp.desc()).limit(limit).all():
        rows.append({
            "timestamp": event.timestamp.isoformat() if event.timestamp else None,
            "type": event.category or "Incident",
            "severity": event.severity,
            "subject": event.vessel_name or event.route or event.location,
            "description": event.description,
            "lat": SCENARIO_LOCATIONS.get(event.location, PORT_COORDS.get(event.location, (None, None)))[0],
            "lon": SCENARIO_LOCATIONS.get(event.location, PORT_COORDS.get(event.location, (None, None)))[1],
            "source": event.source,
        })
    for action in db.query(AIAction).order_by(AIAction.updated_at.desc()).limit(limit).all():
        rows.append({
            "timestamp": action.updated_at.isoformat() if action.updated_at else None,
            "type": "AI action",
            "severity": "high" if action.priority == "P1" else "medium" if action.priority == "P2" else "low",
            "subject": action.subject,
            "description": action.recommendation,
            "lat": None,
            "lon": None,
            "source": action.source,
        })
    rows = sorted(rows, key=lambda item: item.get("timestamp") or "", reverse=True)[:limit]
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "events": list(reversed(rows)),
    }


def quality_status(score: int) -> str:
    if score >= 90:
        return "pass"
    if score >= 70:
        return "warn"
    return "fail"


@app.get("/data-quality")
def get_data_quality(db: Session = Depends(get_db)):
    checks = []
    vessels, source = get_operational_vessels(db)
    vessel_names = [str(vessel.get("name") or "") for vessel in vessels]
    duplicate_vessels = len(vessel_names) - len(set(vessel_names))
    manifest_rows = db.query(CargoManifest).all()
    manifests = len(manifest_rows)
    verified_manifests = sum(1 for manifest in manifest_rows if manifest_is_verified(manifest))
    history_count = db.query(AISPositionHistory).count()
    stale_cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=15)
    stale_count = 0
    for row in db.query(AISPositionHistory).order_by(AISPositionHistory.timestamp.desc()).limit(300).all():
        timestamp = row.timestamp
        if timestamp and timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=datetime.timezone.utc)
        if timestamp and timestamp < stale_cutoff:
            stale_count += 1

    checks.append({"name": "Fleet feed", "status": "pass" if vessels else "fail", "detail": f"{len(vessels)} vessels from {source}."})
    checks.append({"name": "AIS history", "status": "pass" if history_count else "warn", "detail": f"{history_count} persisted position rows."})
    checks.append({"name": "Stale signals", "status": "warn" if stale_count else "pass", "detail": f"{stale_count} stale AIS rows in latest sample."})
    checks.append({"name": "Duplicate vessels", "status": "warn" if duplicate_vessels else "pass", "detail": f"{duplicate_vessels} duplicate vessel names."})
    checks.append({"name": "Cargo coverage", "status": "pass" if verified_manifests >= max(1, len(vessels) // 2) else "warn", "detail": f"{verified_manifests} verified manifest(s), {manifests} total rows for {len(vessels)} vessels."})
    checks.append({"name": "AISStream key", "status": "pass" if get_aisstream_status().get("enabled") else "warn", "detail": "AISStream configured." if get_aisstream_status().get("enabled") else "Using demo/local fallback."})
    checks.append({"name": "AISStream connected", "status": "pass" if get_aisstream_status().get("connected") else "warn", "detail": f"{get_aisstream_status().get('vessel_count', 0)} live vessel(s), ssl={get_aisstream_status().get('ssl_verification', 'enabled')}."})
    score = 100
    score -= sum(18 for check in checks if check["status"] == "fail")
    score -= sum(8 for check in checks if check["status"] == "warn")
    score = max(0, score)
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "score": score,
        "status": quality_status(score),
        "checks": checks,
    }


def cargo_manifest_cleanup_key(manifest: CargoManifest) -> tuple[str, str, str]:
    identifier = normalize_manifest_lookup_key(manifest.vessel_identifier)
    name = normalize_manifest_lookup_key(manifest.vessel_name)
    primary = identifier if identifier and identifier not in {"unknown", "none"} else name
    return (
        primary,
        normalize_manifest_lookup_key(manifest.cargo),
        normalize_manifest_lookup_key(manifest.destination_port),
    )


def cargo_manifest_duplicate_groups(db: Session) -> list[list[CargoManifest]]:
    rows = db.query(CargoManifest).order_by(CargoManifest.updated_at.desc(), CargoManifest.id.desc()).all()
    groups: dict[tuple[str, str, str], list[CargoManifest]] = {}
    for manifest in rows:
        groups.setdefault(cargo_manifest_cleanup_key(manifest), []).append(manifest)
    return [group for group in groups.values() if len(group) > 1]


def manifest_sort_epoch(manifest: CargoManifest) -> float:
    timestamp = manifest.updated_at
    if not timestamp:
        return 0
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=datetime.timezone.utc)
    return timestamp.timestamp()


@app.get("/data-cleanup/summary")
def get_data_cleanup_summary(db: Session = Depends(get_db)):
    manifest_total = db.query(CargoManifest).count()
    ai_total = db.query(AIAction).count()
    incident_total = db.query(IncidentEvent).count()
    duplicate_groups = cargo_manifest_duplicate_groups(db)
    duplicate_manifest_groups = [
        {
            "vessel_name": group[0].vessel_name,
            "vessel_identifier": group[0].vessel_identifier,
            "cargo": group[0].cargo,
            "destination_port": group[0].destination_port,
            "rows": len(group),
        }
        for group in duplicate_groups
    ]
    inferred_live_manifests = sum(1 for manifest in db.query(CargoManifest).all() if manifest_is_inferred(manifest))
    old_cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=14)
    old_actions = db.query(AIAction).filter(AIAction.updated_at < old_cutoff).count()
    resolved_incidents = db.query(IncidentEvent).filter(IncidentEvent.status == "resolved").count()
    generated_workflow_rows = db.query(IncidentEvent).filter(IncidentEvent.source.in_(GENERATED_WORKFLOW_SOURCES)).count()
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "summary": {
            "cargo_manifests": manifest_total,
            "ai_actions": ai_total,
            "incidents": incident_total,
            "duplicate_manifest_groups": len(duplicate_manifest_groups),
            "inferred_live_manifests": inferred_live_manifests,
            "old_actions": old_actions,
            "resolved_incidents": resolved_incidents,
            "generated_workflow_rows": generated_workflow_rows,
        },
        "duplicate_manifests": sorted(duplicate_manifest_groups, key=lambda row: row["rows"], reverse=True)[:25],
        "recommendations": [
            "Use Demo Reset before presentations if generated workflow rows become noisy.",
            "Keep live AIS cargo marked as inferred unless confirmed by manifest.",
            "Archive old AI actions before production migration.",
        ],
    }


@app.post("/data-cleanup/run")
def run_data_cleanup(
    payload: DataMaintenanceRequest | None = None,
    db: Session = Depends(get_db),
    request: Request = None,
):
    require_role(request, {"Admin"}, "Data cleanup")
    payload = payload or DataMaintenanceRequest()
    if payload.confirm.strip().upper() != "CLEAN DATA":
        raise HTTPException(status_code=400, detail="Type CLEAN DATA to run maintenance")

    before = get_data_cleanup_summary(db)
    now = datetime.datetime.now(datetime.timezone.utc)
    changes = {
        "duplicate_manifests_removed": 0,
        "inferred_manifests_demoted": 0,
        "old_actions_completed": 0,
        "resolved_incidents_removed": 0,
        "generated_workflow_rows_removed": 0,
    }

    if payload.demote_inferred_live_manifests:
        for manifest in db.query(CargoManifest).all():
            if manifest_is_inferred(manifest) and str(manifest.status or "").lower() != "inferred-live":
                manifest.status = "inferred-live"
                manifest.updated_at = now
                changes["inferred_manifests_demoted"] += 1

    if payload.compact_manifests:
        for group in cargo_manifest_duplicate_groups(db):
            keep = sorted(
                group,
                key=lambda manifest: (
                    1 if manifest_is_verified(manifest) else 0,
                    manifest_sort_epoch(manifest),
                    manifest.id or 0,
                ),
                reverse=True,
            )[0]
            for manifest in group:
                if manifest.id == keep.id:
                    continue
                db.delete(manifest)
                changes["duplicate_manifests_removed"] += 1

    if payload.complete_old_actions:
        old_cutoff = now - datetime.timedelta(days=14)
        old_actions = db.query(AIAction).filter(AIAction.updated_at < old_cutoff, AIAction.status != "completed").all()
        for action in old_actions:
            action.status = "completed"
            action.updated_at = now
            changes["old_actions_completed"] += 1

    if payload.archive_resolved_incidents:
        old_cutoff = now - datetime.timedelta(days=7)
        removed = db.query(IncidentEvent).filter(IncidentEvent.status == "resolved", IncidentEvent.timestamp < old_cutoff).delete(synchronize_session=False)
        changes["resolved_incidents_removed"] = int(removed or 0)

    if payload.archive_generated_workflow:
        removed = (
            db.query(IncidentEvent)
            .filter(IncidentEvent.source.in_(GENERATED_WORKFLOW_SOURCES), IncidentEvent.status == "resolved")
            .delete(synchronize_session=False)
        )
        changes["generated_workflow_rows_removed"] = int(removed or 0)

    record_audit_event(
        db,
        action="data_cleanup_run",
        resource="data-cleanup",
        detail=f"Data maintenance applied: {changes}",
        severity="warning",
        request=request,
    )
    db.commit()
    return {
        "status": "completed",
        "changes": changes,
        "before": before.get("summary", {}),
        "after": get_data_cleanup_summary(db).get("summary", {}),
    }


@app.get("/deployment/readiness")
def get_deployment_readiness(db: Session = Depends(get_db)):
    checks = [
        {"name": "Dockerfile", "status": "pass" if os.path.exists("Dockerfile") else "fail", "detail": "Container build file present."},
        {"name": "Docker Compose", "status": "pass" if os.path.exists("docker-compose.yml") else "warn", "detail": "Local multi-service runner."},
        {"name": "Environment example", "status": "pass" if os.path.exists(".env.example") else "warn", "detail": "Safe config template for demos."},
        {"name": "Tests", "status": "pass" if os.path.exists("tests") else "fail", "detail": "Automated test folder present."},
        {"name": "GitHub Actions", "status": "pass" if os.path.exists(".github/workflows/tests.yml") else "warn", "detail": "CI workflow check."},
        {"name": "Health endpoint", "status": "pass" if health(db).get("status") in {"healthy", "degraded"} else "fail", "detail": "Backend self-check responds."},
        {"name": "Runtime database", "status": "pass" if db.query(TradeRoute).count() else "fail", "detail": "Seeded trade routes are available."},
        {"name": "Audit trail", "status": "pass" if db.query(AuditLog).count() >= 0 else "fail", "detail": "Persistent audit table is available."},
        {"name": "Response compression", "status": "pass", "detail": "GZip middleware enabled for larger JSON responses."},
    ]
    score = 100
    score -= sum(20 for check in checks if check["status"] == "fail")
    score -= sum(8 for check in checks if check["status"] == "warn")
    score = max(0, score)
    return {
        "score": score,
        "status": "production-shaped" if score >= 85 else "demo-ready" if score >= 70 else "needs work",
        "checks": checks,
        "next_steps": [
            "Add Alembic migrations before production data changes.",
            "Move API keys into secret storage for deployed environments.",
            "Put the frontend and backend behind authenticated HTTPS.",
        ],
    }


@app.get("/executive/brief")
def get_executive_brief(db: Session = Depends(get_db)):
    operations = get_operations_intelligence_v2(db)
    assessments = get_ai_route_assessments(db)
    predictions = get_vessel_predictions(limit=20, db=db)["predictions"]
    quality = get_data_quality(db)
    notifications = get_notifications(limit=20, db=db)
    top_routes = assessments[:3]
    top_vessels = predictions[:3]
    critical_notifications = [item for item in notifications if item.get("severity") == "critical"]
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "readiness_score": operations.get("readiness_score", 0),
        "readiness_band": operations.get("readiness_band", "Unknown"),
        "data_quality_score": quality["score"],
        "critical_notifications": len(critical_notifications),
        "top_routes": top_routes,
        "top_vessels": top_vessels,
        "top_actions": operations.get("top_actions", [])[:3],
        "commander_summary": (
            f"Readiness is {operations.get('readiness_band')} at {operations.get('readiness_score')}%. "
            f"Top route risk is {top_routes[0]['route']} at {top_routes[0]['score']}/10. "
            f"Data quality is {quality['status']} at {quality['score']}%."
            if top_routes else
            f"Readiness is {operations.get('readiness_band')} at {operations.get('readiness_score')}%. No route risks available."
        ),
    }


def clamp_percent(value: float) -> float:
    return round(max(0.0, min(100.0, float(value or 0))), 1)


def mission_band(score: float) -> str:
    if score >= 75:
        return "Critical"
    if score >= 45:
        return "Watch"
    return "Stable"


def mission_priority(score: float) -> str:
    if score >= 75:
        return "P1"
    if score >= 45:
        return "P2"
    return "P3"


def notification_digest(limit: int = 150, db: Session = Depends(get_db)) -> dict:
    intelligence = get_notification_intelligence(limit=limit, db=db)
    groups = intelligence.get("groups", [])
    weights = {"critical": 5, "warning": 2, "info": 0.5}
    target_groups: dict[str, dict] = {}
    for group in groups:
        target = group.get("target") or "Network"
        severity = str(group.get("severity") or "info").lower()
        entry = target_groups.setdefault(target, {
            "target": target,
            "signals": 0,
            "sources": set(),
            "severity_score": 0.0,
            "highest_priority": "P3",
            "latest": "",
            "recommended_action": "Monitor",
        })
        count = int(group.get("count", 0) or 0)
        entry["signals"] += count
        entry["sources"].add(group.get("source") or "Unknown")
        entry["severity_score"] += count * weights.get(severity, 0.5)
        if group.get("priority") == "P1":
            entry["highest_priority"] = "P1"
            entry["recommended_action"] = "Escalate now"
        elif group.get("priority") == "P2" and entry["highest_priority"] != "P1":
            entry["highest_priority"] = "P2"
            entry["recommended_action"] = "Assign watch owner"
        entry["latest"] = group.get("latest_title") or entry["latest"]

    cards = []
    for entry in target_groups.values():
        score = clamp_percent(entry["severity_score"] * 7)
        cards.append({
            "target": entry["target"],
            "signals": entry["signals"],
            "sources": ", ".join(sorted(entry["sources"])),
            "priority": entry["highest_priority"],
            "pressure": score,
            "band": mission_band(score),
            "latest": entry["latest"],
            "recommended_action": entry["recommended_action"],
        })
    cards = sorted(cards, key=lambda item: ({"P1": 0, "P2": 1, "P3": 2}.get(item["priority"], 3), -item["pressure"], -item["signals"]))
    return {
        "generated_at": intelligence.get("generated_at"),
        "pressure_score": intelligence.get("pressure_score", 0),
        "pressure_band": intelligence.get("pressure_band", "Normal"),
        "raw_total": intelligence.get("total", 0),
        "compressed_total": len(cards),
        "noise_reduction": max(0, int(intelligence.get("total", 0) - len(cards))),
        "cards": cards[:12],
        "top_actions": intelligence.get("top_actions", []),
    }


@app.get("/notifications/digest")
def get_notifications_digest(limit: int = 150, db: Session = Depends(get_db)):
    return notification_digest(limit=limit, db=db)


def build_incident_commander_cards(db: Session, persist: bool = False) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc)
    cards = []
    assessments = get_ai_route_assessments(db)
    predictions = get_vessel_predictions(limit=40, db=db)["predictions"]
    operations = get_operations_intelligence_v2(db)
    digest = notification_digest(limit=160, db=db)
    ais_status = get_aisstream_status()

    if ais_status.get("enabled") and not ais_status.get("connected"):
        cards.append({
            "card_id": "ais-feed-disconnected",
            "priority": "P1",
            "severity": "high",
            "category": "AIS",
            "title": "Live AIS feed needs command attention",
            "target": "AISStream API",
            "summary": ais_status.get("last_error") or "AISStream is enabled but not connected.",
            "owner": "Platform admin",
            "checklist": [
                "Check AIS_PROVIDER and AISSTREAM_API_KEY.",
                "Confirm network access to the AIS websocket.",
                "Use local registry as fallback until live feed recovers.",
            ],
            "evidence": f"enabled={ais_status.get('enabled')} running={ais_status.get('running')} connected={ais_status.get('connected')}",
        })

    for route in assessments[:3]:
        score = float(route.get("score", 0) or 0)
        if score < 7:
            continue
        cards.append({
            "card_id": f"route-{str(route.get('route')).lower().replace(' ', '-')}",
            "priority": "P1" if score >= 8 else "P2",
            "severity": "high" if score >= 8 else "medium",
            "category": "Route release",
            "title": f"Route release review: {route.get('route')}",
            "target": route.get("route"),
            "summary": route.get("action") or route.get("explanation"),
            "owner": "Operations lead" if score >= 8 else "Risk analyst",
            "checklist": route.get("human_checklist", []) or [
                "Compare safest and balanced route options.",
                "Confirm latest AIS context for vessels on this lane.",
                "Record route-release decision in the risk log.",
            ],
            "evidence": f"AI score {score}/10, confidence {route.get('confidence')}%, band {route.get('band')}.",
        })

    for vessel in predictions[:5]:
        delay = float(vessel.get("delay_risk", 0) or 0)
        if delay < 7:
            continue
        cards.append({
            "card_id": f"vessel-{str(vessel.get('vessel')).lower().replace(' ', '-')}",
            "priority": "P1" if delay >= 8 else "P2",
            "severity": "high" if delay >= 8 else "medium",
            "category": "Vessel ETA",
            "title": f"ETA risk: {vessel.get('vessel')}",
            "target": vessel.get("vessel"),
            "summary": vessel.get("recommended_action"),
            "owner": "Fleet controller",
            "checklist": [
                "Confirm live speed and last AIS signal.",
                "Check cargo priority before changing ETA commitment.",
                "Notify destination port if delay risk remains above 7.",
            ],
            "evidence": f"Delay risk {delay}/10, ETA {vessel.get('eta_hours')}h, nearest port {vessel.get('nearest_port')}.",
        })

    readiness_raw = operations.get("readiness_score")
    readiness = float(readiness_raw if readiness_raw is not None else 100)
    if readiness < 65:
        cards.append({
            "card_id": "fleet-readiness-low",
            "priority": "P1",
            "severity": "high",
            "category": "Fleet operations",
            "title": "Fleet readiness is below release threshold",
            "target": "Fleet & Operations",
            "summary": f"Readiness is {readiness}% ({operations.get('readiness_band')}).",
            "owner": "Command desk",
            "checklist": [
                "Clear P1 action queue first.",
                "Confirm high-value cargo has fresh AIS.",
                "Use ETA Predictions before customer updates.",
            ],
            "evidence": f"{operations.get('summary', {}).get('open_actions', 0)} open action(s), {operations.get('summary', {}).get('p1_actions', 0)} P1 action(s).",
        })

    for item in digest.get("cards", [])[:4]:
        if item.get("priority") == "P3":
            continue
        cards.append({
            "card_id": f"digest-{str(item.get('target')).lower().replace(' ', '-')}",
            "priority": item.get("priority"),
            "severity": "high" if item.get("priority") == "P1" else "medium",
            "category": "Alert cluster",
            "title": f"Grouped alert cluster: {item.get('target')}",
            "target": item.get("target"),
            "summary": f"{item.get('signals')} signal(s) from {item.get('sources')}.",
            "owner": "Alert triage",
            "checklist": [
                item.get("recommended_action", "Review grouped alert."),
                "Resolve the grouped target before lower-priority alerts.",
                "Check whether the target appears in route, cargo, or AIS panels.",
            ],
            "evidence": item.get("latest") or "Grouped notification intelligence.",
        })

    cards = sorted(cards, key=lambda item: ({"P1": 0, "P2": 1, "P3": 2}.get(item["priority"], 3), item["title"]))[:10]
    if persist:
        for card in cards:
            record_incident_once(
                db,
                title=card["title"],
                category=card["category"],
                severity=card["severity"],
                location=str(card.get("target") or "Command"),
                vessel_name=str(card.get("target") or ""),
                route=str(card.get("target") or ""),
                description=card["summary"],
                source="Auto Incident Commander",
            )
        db.commit()

    open_events = db.query(IncidentEvent).filter(IncidentEvent.status == "open").order_by(IncidentEvent.timestamp.desc()).limit(20).all()
    return {
        "generated_at": now.isoformat(),
        "cards": cards,
        "open_incidents": [serialize_incident(event) for event in open_events],
        "sync_mode": "persisted" if persist else "preview",
    }


@app.get("/incidents/commander")
def get_incident_commander(persist: bool = False, db: Session = Depends(get_db)):
    return build_incident_commander_cards(db, persist=persist)


def build_mission_control(db: Session) -> dict:
    brief = get_executive_brief(db)
    operations = get_operations_intelligence_v2(db)
    assessments = get_ai_route_assessments(db)
    predictions = get_vessel_predictions(limit=30, db=db)["predictions"]
    quality = get_data_quality(db)
    forecast = get_risk_forecast(days=7, db=db)
    digest = notification_digest(limit=160, db=db)
    incidents = build_incident_commander_cards(db, persist=False)
    ais_status = get_aisstream_status()
    cargo_counts = operations.get("cargo_priority_counts", {})
    p1_cargo = int(cargo_counts.get("P1", 0) or 0)
    p2_cargo = int(cargo_counts.get("P2", 0) or 0)
    top_route = assessments[0] if assessments else {}
    top_vessel = predictions[0] if predictions else {}
    top_forecast = forecast.get("top_forecast", [{}])[0] if forecast.get("top_forecast") else {}

    ais_score = 0
    if ais_status.get("enabled") and not ais_status.get("connected"):
        ais_score = 82
    elif ais_status.get("last_error"):
        ais_score = 65
    elif ais_status.get("enabled"):
        ais_score = 18

    readiness_raw = operations.get("readiness_score")
    readiness_value = float(readiness_raw if readiness_raw is not None else 100)
    priorities = [
        {
            "lane": "Route safety",
            "score": clamp_percent(float(top_route.get("score", 0) or 0) * 10),
            "priority": mission_priority(float(top_route.get("score", 0) or 0) * 10),
            "signal": top_route.get("route", "No route signal"),
            "action": top_route.get("action", "No route action required."),
            "page": "Risk & Alerts",
        },
        {
            "lane": "Fleet operations",
            "score": clamp_percent(100 - readiness_value),
            "priority": mission_priority(100 - readiness_value),
            "signal": f"{operations.get('readiness_score', 0)}% readiness",
            "action": "Clear P1 action queue and confirm high-value cargo AIS.",
            "page": "Fleet & Operations",
        },
        {
            "lane": "Threat alerts",
            "score": clamp_percent(digest.get("pressure_score", 0)),
            "priority": mission_priority(digest.get("pressure_score", 0)),
            "signal": f"{digest.get('raw_total', 0)} raw alerts compressed to {digest.get('compressed_total', 0)} target(s)",
            "action": digest.get("top_actions", [{}])[0].get("action", "Monitor alert pressure."),
            "page": "Notifications",
        },
        {
            "lane": "Cargo exposure",
            "score": clamp_percent((p1_cargo * 18) + (p2_cargo * 7)),
            "priority": mission_priority((p1_cargo * 18) + (p2_cargo * 7)),
            "signal": f"{p1_cargo} P1 / {p2_cargo} P2 manifests",
            "action": "Release P1 cargo only after route and AIS checks pass.",
            "page": "Fleet & Operations",
        },
        {
            "lane": "AIS live feed",
            "score": clamp_percent(ais_score),
            "priority": mission_priority(ais_score),
            "signal": f"{ais_status.get('vessel_count', 0)} live vessels, connected={ais_status.get('connected')}",
            "action": "Keep live feed active; fall back to registry if connection drops.",
            "page": "Settings",
        },
        {
            "lane": "Forecast watch",
            "score": clamp_percent(float(top_forecast.get("forecast_score", 0) or 0) * 10),
            "priority": mission_priority(float(top_forecast.get("forecast_score", 0) or 0) * 10),
            "signal": top_forecast.get("route", "No forecast signal"),
            "action": "Review watch windows before new departure release.",
            "page": "Risk & Alerts",
        },
        {
            "lane": "Data quality",
            "score": clamp_percent(100 - float(quality.get("score", 100) or 100)),
            "priority": mission_priority(100 - float(quality.get("score", 100) or 100)),
            "signal": f"{quality.get('score')}% quality ({quality.get('status')})",
            "action": "Fix warning checks before executive reporting.",
            "page": "Reports",
        },
    ]
    priorities = sorted(priorities, key=lambda item: item["score"], reverse=True)
    top_problem = priorities[0] if priorities else {}
    mission_score = top_problem.get("score", 0)
    next_actions = [item["action"] for item in priorities if item.get("priority") in {"P1", "P2"}][:6]
    if top_vessel:
        next_actions.append(f"Check {top_vessel.get('vessel')} ETA risk {top_vessel.get('delay_risk')}/10.")
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "mission_state": mission_band(mission_score),
        "mission_score": mission_score,
        "top_problem": top_problem,
        "commander_summary": (
            f"{mission_band(mission_score)} mission state. Biggest pressure is {top_problem.get('lane')} "
            f"at {mission_score}/100: {top_problem.get('signal')}."
        ),
        "priorities": priorities,
        "incident_cards": incidents.get("cards", []),
        "noise_reduced_digest": digest,
        "next_best_actions": list(dict.fromkeys(next_actions))[:7],
        "daily_brief_hint": "Generate a daily brief after P1/P2 items are acknowledged.",
        "explainability": {
            "inputs": [
                "executive brief",
                "AI route assessments",
                "vessel ETA predictions",
                "AISStream status",
                "notification digest",
                "risk forecast",
                "data quality",
            ],
            "method": "Scores each operational lane from 0-100 and ranks the highest pressure as the next command focus.",
            "limits": [
                "External weather, port congestion, and security feeds are simulated unless connected separately.",
                "AISStream coverage depends on configured bounding boxes and live API availability.",
            ],
        },
        "brief": brief,
    }


def build_war_room(db: Session) -> dict:
    mission = build_mission_control(db)
    top_problem = mission.get("top_problem", {})
    lane = top_problem.get("lane", "Command")
    score = float(mission.get("mission_score", 0) or 0)
    operations = get_operations_intelligence_v2(db)
    assessments = get_ai_route_assessments(db)
    predictions = get_vessel_predictions(limit=20, db=db)["predictions"]
    digest_cards = mission.get("noise_reduced_digest", {}).get("cards", [])
    cargo_counts = operations.get("cargo_priority_counts", {})
    command_mode = "Lockdown" if score >= 85 else "Command Watch" if score >= 55 else "Normal Watch"
    response_window = "0-60 minutes" if score >= 75 else "0-4 hours" if score >= 45 else "Today"

    lane_actions = {
        "Fleet operations": [
            "Freeze non-essential route releases until P1 queue is reviewed.",
            "Assign a controller to every P1 vessel or cargo item.",
            "Confirm AIS freshness for high-value cargo before customer updates.",
        ],
        "Threat alerts": [
            "Group alerts by target and clear P1 clusters first.",
            "Cross-check alert targets against active routes and cargo manifests.",
            "Escalate repeated AIS/API threat signals to the command desk.",
        ],
        "Cargo exposure": [
            "Hold P1 cargo release until route and AIS checks pass.",
            "Validate manifest priority, destination, and owner.",
            "Prepare alternate routing for exposed high-value cargo.",
        ],
        "Route safety": [
            "Compare safest, fastest, lowest-cost, and balanced options.",
            "Record the release decision and human checklist.",
            "Notify destination port if the selected route stays above risk 7.",
        ],
        "Forecast watch": [
            "Identify the first day each route crosses the watch threshold.",
            "Run Scenario Lab against the highest forecast route.",
            "Pre-stage reroute and berth-delay buffers.",
        ],
        "AIS live feed": [
            "Verify AISStream connection and live vessel count.",
            "Fall back to registry if live feed becomes stale.",
            "Reduce mobile refresh if operators are monitoring by phone.",
        ],
        "Data quality": [
            "Review failing or warning data checks before exporting reports.",
            "Confirm latest AIS history and manifest coverage.",
            "Attach quality notes to the executive brief.",
        ],
    }
    actions = lane_actions.get(lane, ["Review mission focus.", "Assign an owner.", "Record the decision trail."])
    playbook = [
        {
            "phase": "Stabilize",
            "timebox": "0-5 min",
            "owner": "Command desk",
            "action": actions[0],
            "success_signal": "Top pressure has an owner and immediate hold/release rule.",
        },
        {
            "phase": "Verify",
            "timebox": "5-15 min",
            "owner": "Risk analyst",
            "action": actions[1] if len(actions) > 1 else actions[0],
            "success_signal": "Evidence is confirmed against live AIS, route risk, and notifications.",
        },
        {
            "phase": "Execute",
            "timebox": "15-35 min",
            "owner": "Fleet controller",
            "action": actions[2] if len(actions) > 2 else actions[-1],
            "success_signal": "Route, vessel, cargo, or alert action is queued or completed.",
        },
        {
            "phase": "Communicate",
            "timebox": "35-50 min",
            "owner": "Operations lead",
            "action": "Send the daily command brief with risk, owner, and decision gates.",
            "success_signal": "Stakeholders receive one consistent operating picture.",
        },
        {
            "phase": "Audit",
            "timebox": "50-60 min",
            "owner": "Admin",
            "action": "Record final action in audit trail and keep monitoring Mission Control.",
            "success_signal": "Decision is explainable and repeatable.",
        },
    ]

    impacted_routes = [
        {
            "route": item.get("route"),
            "score": item.get("score"),
            "band": item.get("band"),
            "action": item.get("action"),
        }
        for item in assessments[:5]
    ]
    impacted_vessels = [
        {
            "vessel": item.get("vessel"),
            "delay_risk": item.get("delay_risk"),
            "nearest_port": item.get("nearest_port"),
            "cargo": item.get("cargo"),
            "action": item.get("recommended_action"),
        }
        for item in predictions[:5]
    ]
    impacted_alerts = [
        {
            "target": item.get("target"),
            "priority": item.get("priority"),
            "signals": item.get("signals"),
            "action": item.get("recommended_action"),
        }
        for item in digest_cards[:6]
    ]
    automation_queue = []
    for card in mission.get("incident_cards", [])[:4]:
        automation_queue.append({
            "type": "Incident card",
            "target": card.get("target"),
            "priority": card.get("priority"),
            "automation": f"Assign {card.get('owner')} and track checklist.",
        })
    for action in operations.get("top_actions", [])[:4]:
        automation_queue.append({
            "type": action.get("action_type"),
            "target": action.get("subject"),
            "priority": action.get("priority"),
            "automation": action.get("recommendation"),
        })

    decision_gates = [
        {
            "gate": "Release hold",
            "pass_condition": "No selected route above risk 7 unless Admin/Risk owner accepts it.",
            "current_signal": top_problem.get("signal", "No active pressure signal."),
        },
        {
            "gate": "Cargo approval",
            "pass_condition": "P1/P2 cargo has route, AIS, and owner confirmation.",
            "current_signal": f"{cargo_counts.get('P1', 0)} P1 and {cargo_counts.get('P2', 0)} P2 manifests.",
        },
        {
            "gate": "Comms release",
            "pass_condition": "Daily brief generated after incident cards are reviewed.",
            "current_signal": f"{len(mission.get('incident_cards', []))} auto incident card(s).",
        },
    ]
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "command_mode": command_mode,
        "response_window": response_window,
        "active_focus": lane,
        "active_signal": top_problem.get("signal"),
        "mission_score": mission.get("mission_score"),
        "playbook": playbook,
        "decision_gates": decision_gates,
        "impacted_assets": {
            "routes": impacted_routes,
            "vessels": impacted_vessels,
            "alerts": impacted_alerts,
            "cargo_priority_counts": cargo_counts,
        },
        "automation_queue": automation_queue[:8],
        "explainability": {
            "method": "Builds a timed response room from the highest Mission Control pressure lane.",
            "inputs": ["mission-control ranking", "incident cards", "route assessments", "vessel ETA predictions", "notification digest", "cargo priorities"],
            "limits": ["This creates command guidance; final release/hold decisions remain role-controlled."],
        },
    }


@app.get("/ai/mission-control")
def get_mission_control(db: Session = Depends(get_db)):
    return build_mission_control(db)


@app.get("/ai/war-room")
def get_war_room(db: Session = Depends(get_db)):
    return build_war_room(db)


def captain_route_modes(plan: dict | None) -> dict:
    alternatives = list((plan or {}).get("alternatives", []) or [])
    if not alternatives:
        return {"modes": {}, "options": []}
    distances = [float(item.get("distance_nm", 0) or 0) for item in alternatives]
    min_distance = min(distances) if distances else 0
    max_distance = max(distances) if distances else min_distance
    distance_span = max(max_distance - min_distance, 1)
    enriched = []
    for option in alternatives:
        risk = float(option.get("risk_score", 0) or 0)
        distance = float(option.get("distance_nm", 0) or 0)
        distance_penalty = ((distance - min_distance) / distance_span) * 35
        safety_score = round(clamp_percent(102 - (risk * 9.4)), 1)
        speed_score = round(clamp_percent(100 - distance_penalty - (risk * 1.2)), 1)
        cost_index = round(34 + ((distance / max(min_distance, 1)) * 18) + (risk * 3.6), 1)
        balanced_score = round((safety_score * 0.52) + (speed_score * 0.28) + (max(0, 100 - cost_index) * 0.2), 1)
        enriched.append({
            **option,
            "safety_score": safety_score,
            "speed_score": speed_score,
            "cost_index": cost_index,
            "balanced_score": balanced_score,
        })

    safest = min(enriched, key=lambda item: item["risk_score"])
    fastest = max(enriched, key=lambda item: item["speed_score"])
    lowest_cost = min(enriched, key=lambda item: item["cost_index"])
    balanced = max(enriched, key=lambda item: item["balanced_score"])
    for option in enriched:
        option["captain_modes"] = [
            mode for mode, selected in {
                "Safest": safest,
                "Fastest": fastest,
                "Lowest cost": lowest_cost,
                "Balanced": balanced,
            }.items()
            if selected.get("route") == option.get("route")
        ]
    return {
        "modes": {
            "safest": safest,
            "fastest": fastest,
            "lowest_cost": lowest_cost,
            "balanced": balanced,
        },
        "options": enriched,
    }


def incident_eta_window(score: float) -> str:
    if score >= 85:
        return "Now to 6 hours"
    if score >= 70:
        return "6 to 24 hours"
    if score >= 50:
        return "24 to 72 hours"
    if score >= 30:
        return "This week watch"
    return "Normal monitoring"


def build_live_incident_predictions(db: Session, limit: int = 7) -> dict:
    intelligence = build_ai_risk_intelligence(db)
    categories = intelligence.get("categories", [])
    forecast_rows = intelligence.get("forecast", [])
    predictions = []
    for category in categories:
        score = float(category.get("risk_score", 0) or 0)
        timeline = [
            row for row in forecast_rows
            if row.get("category") == category.get("category")
        ]
        peak_no_action = max([float(row.get("score_no_action", 0) or 0) for row in timeline] or [score])
        controlled = min([float(row.get("score_with_controls", peak_no_action) or peak_no_action) for row in timeline] or [score])
        likelihood = clamp_percent((score * 0.72) + (peak_no_action * 0.28))
        predictions.append({
            "category": category.get("category"),
            "likelihood": likelihood,
            "priority": mission_priority(likelihood),
            "risk_level": category.get("risk_level"),
            "eta_window": incident_eta_window(likelihood),
            "no_action_peak": round(peak_no_action, 1),
            "controlled_floor": round(controlled, 1),
            "risk_reduction": round(max(0, peak_no_action - controlled), 1),
            "trigger": category.get("caution"),
            "captain_solution": category.get("ai_solution"),
            "affected_routes": len(category.get("impacted_routes", []) or []),
            "affected_vessels": len(category.get("impacted_vessels", []) or []),
            "evidence": category.get("evidence", [])[:4],
            "timeline": timeline,
            "playbook": category.get("playbook", {}),
        })
    predictions = sorted(predictions, key=lambda row: row["likelihood"], reverse=True)[:limit]
    return {
        "generated_at": intelligence.get("generated_at"),
        "summary": intelligence.get("summary", {}),
        "predictions": predictions,
        "map_layers": intelligence.get("map_layers", {}),
        "explainability": {
            "method": "Ranks incident categories by current AI Risk Brain score plus no-action forecast drift.",
            "inputs": ["AI Risk Brain categories", "risk forecast windows", "route assessments", "AIS health", "vessel delay risk", "cargo priority"],
            "limits": ["External security/weather providers are still fallback unless configured in Settings."],
        },
    }


@app.get("/ai/incident-predictions")
def get_live_incident_predictions(limit: int = 7, db: Session = Depends(get_db)):
    return build_live_incident_predictions(db, limit=max(1, min(limit, 10)))


def captain_verdict(score: float, route_plan: dict | None, top_incident: dict | None) -> tuple[str, str]:
    direct = (route_plan or {}).get("direct") or {}
    recommended = (route_plan or {}).get("recommended") or {}
    direct_risk = float(direct.get("risk_score", 0) or 0)
    recommended_risk = float(recommended.get("risk_score", direct_risk) or direct_risk)
    route_saves = direct_risk and (direct_risk - recommended_risk) >= 1.0
    incident_score = float((top_incident or {}).get("likelihood", 0) or 0)
    if score >= 88 or incident_score >= 92:
        return "STOP VOYAGE", "Stop or hold release until Admin and Operator clear the emergency gates."
    if score >= 76:
        return "ESCALATE", "Escalate to Emergency War Room and assign owners before the next sailing decision."
    if route_saves or score >= 62:
        return "REROUTE", "Use the safest route mode and keep high-risk cargo under verified-role control."
    if score >= 42:
        return "DELAY", "Delay release until AIS, route, cargo, and notification checks are refreshed."
    return "SAFE", "Proceed with normal watch, keep route and AIS signals refreshed, and maintain public-safe reporting."


def default_captain_ports(assessments: list[dict]) -> tuple[str | None, str | None]:
    for assessment in assessments:
        route = str(assessment.get("route") or "")
        if " to " in route:
            origin, destination = [part.strip() for part in route.split(" to ", 1)]
            return origin, destination
    return "Mumbai", "Rotterdam"


def build_ai_captain(db: Session, origin: str | None = None, destination: str | None = None) -> dict:
    mission = build_mission_control(db)
    war_room = build_war_room(db)
    autopilot = build_strategic_autopilot(db)
    incident_packet = build_live_incident_predictions(db)
    assessments = get_ai_route_assessments(db)
    predictions = get_vessel_predictions(limit=80, db=db).get("predictions", [])
    digest = notification_digest(limit=180, db=db)
    quality = get_data_quality(db)
    hardening = get_deployment_hardening(db)
    ais_status = get_aisstream_status()

    origin = origin or None
    destination = destination or None
    if not origin or not destination:
        origin, destination = default_captain_ports(assessments)

    route_plan = None
    route_error = None
    if origin and destination:
        try:
            route_plan = plan_global_route(origin, destination)
            route_modes = captain_route_modes(route_plan)
            route_plan["captain_modes"] = route_modes["modes"]
            route_plan["alternatives"] = route_modes["options"]
        except HTTPException as exc:
            route_error = str(exc.detail)
        except Exception as exc:
            route_error = str(exc)

    top_incident = (incident_packet.get("predictions") or [{}])[0]
    top_vessel = predictions[0] if predictions else {}
    projection = autopilot.get("risk_projection", {})
    p1_incidents = len([item for item in incident_packet.get("predictions", []) if item.get("priority") == "P1"])
    p1_notifications = len([item for item in get_notifications(limit=80, db=db) if item.get("severity") == "critical"])
    mission_score = float(mission.get("mission_score", 0) or 0)
    no_action = float(projection.get("without_autopilot", 0) or 0)
    incident_likelihood = float(top_incident.get("likelihood", 0) or 0)
    delay_pressure = float(top_vessel.get("delay_risk", 0) or 0) * 10
    notification_pressure = float(digest.get("pressure_score", 0) or 0)
    captain_score = clamp_percent(
        (mission_score * 0.25)
        + (no_action * 0.22)
        + (incident_likelihood * 0.2)
        + (delay_pressure * 0.12)
        + (notification_pressure * 0.1)
        + (p1_incidents * 4.5)
        + (p1_notifications * 2.5)
        + (max(0, 100 - float(quality.get("score", 100) or 100)) * 0.04)
    )
    verdict, order = captain_verdict(captain_score, route_plan, top_incident)
    priority = mission_priority(captain_score)
    recommended_route = (route_plan or {}).get("recommended") or {}

    order_reasons = [
        f"Mission pressure {mission_score}/100 from {mission.get('top_problem', {}).get('lane', 'Mission Control')}.",
        f"No-action risk {no_action}/100 versus controlled risk {projection.get('with_autopilot', 0)}/100.",
        f"Top incident prediction: {top_incident.get('category', 'None')} at {incident_likelihood}/100.",
        f"Highest vessel delay pressure: {top_vessel.get('vessel', 'None')} at {top_vessel.get('delay_risk', 0)}/10.",
        f"Notification pressure {notification_pressure}/100 with {p1_notifications} critical note(s).",
    ]
    if recommended_route:
        order_reasons.append(f"Safest global route candidate: {recommended_route.get('route')} at {recommended_route.get('risk_score')}/10.")
    if route_error:
        order_reasons.append(f"Route optimizer warning: {route_error}.")

    emergency_steps = [
        {"phase": "0-5 min", "owner": "AI Captain", "action": order, "success": "Every high-risk release has a hold/reroute decision."},
        {"phase": "5-15 min", "owner": "Operator", "action": "Open top vessel, route, and notification evidence.", "success": "Live AIS or fallback status is documented."},
        {"phase": "15-30 min", "owner": "Admin" if priority == "P1" else "Operator", "action": "Approve, reject, or escalate the captain order.", "success": "Audited decision is created."},
        {"phase": "30-60 min", "owner": "Command desk", "action": "Generate mission pack and send one consistent update.", "success": "Stakeholders receive route, cargo, and risk summary."},
    ]
    if priority == "P1":
        emergency_steps.insert(1, {"phase": "Immediate", "owner": "Admin", "action": "Freeze sensitive cargo visibility and stop public details.", "success": "Public role remains sanitized."})

    vessel_board = []
    for vessel in predictions[:10]:
        vessel_board.append({
            "vessel": vessel.get("vessel"),
            "identifier": vessel.get("vessel") or vessel.get("mmsi"),
            "route": vessel.get("route"),
            "nearest_port": vessel.get("nearest_port"),
            "delay_risk": vessel.get("delay_risk"),
            "priority": mission_priority(float(vessel.get("delay_risk", 0) or 0) * 10),
            "cargo": vessel.get("cargo"),
            "cargo_priority": vessel.get("cargo_priority"),
            "cargo_verified": vessel.get("cargo_verified"),
            "speed_knots": vessel.get("speed_knots"),
            "eta_hours": vessel.get("eta_hours"),
            "recommended_action": vessel.get("recommended_action"),
            "position_lat": vessel.get("position_lat"),
            "position_lon": vessel.get("position_lon"),
            "display_position_lat": vessel.get("display_position_lat"),
            "display_position_lon": vessel.get("display_position_lon"),
            "motion_trail": vessel.get("motion_trail", []),
            "motion_source": vessel.get("motion_source"),
        })

    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "verdict": verdict,
        "priority": priority,
        "captain_score": captain_score,
        "captain_band": mission_band(captain_score),
        "captain_order": order,
        "focus_target": recommended_route.get("route") or mission.get("top_problem", {}).get("signal") or "Global network",
        "origin": origin,
        "destination": destination,
        "order_reasons": order_reasons,
        "final_checks": [
            "Confirm AIS source and SSL mode before treating vessel movement as live.",
            "Use safest route mode for P1/P2 cargo unless Admin accepts the exception.",
            "Keep Public role read-only and hide sensitive cargo/security details.",
            "Generate Mission Pack after any Stop, Escalate, or Reroute decision.",
        ],
        "metrics": {
            "mission_score": mission_score,
            "no_action_risk": no_action,
            "controlled_risk": projection.get("with_autopilot", 0),
            "incident_likelihood": incident_likelihood,
            "notification_pressure": notification_pressure,
            "data_quality": quality.get("score"),
            "hardening": hardening.get("score"),
            "ais_connected": bool(ais_status.get("connected")),
            "live_vessels": ais_status.get("vessel_count", 0),
        },
        "global_route": route_plan,
        "route_error": route_error,
        "incident_predictions": incident_packet.get("predictions", []),
        "vessel_board": vessel_board,
        "emergency_war_room": {
            "mode": "Emergency War Room" if priority == "P1" else war_room.get("command_mode"),
            "response_window": war_room.get("response_window"),
            "steps": emergency_steps,
            "decision_gates": war_room.get("decision_gates", []),
            "communications": [
                "One message to fleet operators with route and AIS evidence.",
                "One message to cargo/customer teams with sanitized delivery impact.",
                "One admin audit note with exact decision, owner, and confidence.",
            ],
        },
        "map_overlay": autopilot.get("map_overlay", {}),
        "trust": {
            "data_quality": quality.get("score"),
            "deployment_hardening": hardening.get("score"),
            "ais_status": ais_status,
            "role_policy": {
                "Admin": "Can stop voyage, toggle production controls, and approve critical release.",
                "Operator": "Can investigate, reroute, queue actions, and generate operational reports.",
                "Public": "Read-only sanitized dashboard only.",
            },
        },
        "explainability": {
            "method": "AI Captain fuses Mission Control, Strategic Autopilot, AI Risk Brain, vessel ETA predictions, notification pressure, AIS health, data quality, and route optimizer output into one operational verdict.",
            "verdict_scale": ["SAFE", "DELAY", "REROUTE", "ESCALATE", "STOP VOYAGE"],
            "limits": [
                "This is decision support; verified operators/admins still approve real-world actions.",
                "Weather, port, and security feeds are fallback unless external providers are configured.",
            ],
        },
    }


@app.get("/ai/captain")
def get_ai_captain(
    origin: str | None = None,
    destination: str | None = None,
    db: Session = Depends(get_db),
):
    return build_ai_captain(db, origin=origin, destination=destination)


@app.post("/ai/captain/action")
def execute_ai_captain_action(
    payload: CaptainActionRequest,
    db: Session = Depends(get_db),
    request: Request = None,
):
    require_any_permission(
        request,
        ["approve_actions", "manage_alert_workflows", "manage_vessels", "generate_reports"],
        "AI Captain actions",
    )
    captain = build_ai_captain(db, origin=payload.origin, destination=payload.destination)
    action_name = command_action_label(payload.order or "queue_captain_order")
    priority = str(payload.priority or captain.get("priority") or "P2").upper()
    if priority not in {"P1", "P2", "P3"}:
        priority = "P2"
    target = payload.target or captain.get("focus_target") or "Global network"
    note = payload.note or captain.get("captain_order") or "AI Captain queued a command order."
    severity = "high" if priority == "P1" else "medium" if priority == "P2" else "low"

    if payload.create_incident or action_name in {"stop_voyage", "create_incident", "emergency_incident"}:
        incident = record_incident_once(
            db,
            title=f"AI Captain {captain.get('verdict')}: {target}",
            category="AI Captain",
            severity=severity,
            location=target,
            vessel_name="",
            route=target if " to " in str(target) else "",
            description=note,
            source=payload.owner or "AI Captain",
        )
        record_audit_event(
            db,
            action="ai_captain_incident_created",
            resource=target,
            detail=f"{priority} {captain.get('verdict')}: {note}",
            severity="critical" if priority == "P1" else "warning",
            request=request,
        )
        db.commit()
        db.refresh(incident)
        return {"status": "incident_created", "captain": captain, "record": serialize_incident(incident)}

    action = upsert_ai_action(
        db,
        subject=target,
        priority=priority,
        action_type=f"AI Captain: {action_name}",
        recommendation=note,
        evidence=" | ".join(captain.get("order_reasons", [])[:5]),
        owner=payload.owner or "AI Captain",
        source="AI Captain",
    )
    record_audit_event(
        db,
        action="ai_captain_action_queued",
        resource=target,
        detail=f"{priority} {captain.get('verdict')}: {note}",
        severity="critical" if priority == "P1" else "warning",
        request=request,
    )
    db.commit()
    db.refresh(action)
    return {"status": "queued", "captain": captain, "record": serialize_ai_action(action)}


def ai_risk_level(score: float) -> str:
    score = float(score or 0)
    if score >= 85:
        return "Level 5 - Critical"
    if score >= 70:
        return "Level 4 - High"
    if score >= 50:
        return "Level 3 - Elevated"
    if score >= 30:
        return "Level 2 - Watch"
    return "Level 1 - Normal"


def normalize_ai_incident_type(value: str | None) -> str:
    requested = str(value or "").strip().lower()
    if not requested:
        return "Natural Hazard"
    for category in AI_RISK_TAXONOMY:
        if category.lower() == requested or requested in category.lower():
            return category
    aliases = {
        "natural": "Natural Hazard",
        "weather": "Natural Hazard",
        "storm": "Natural Hazard",
        "cyclone": "Natural Hazard",
        "tsunami": "Natural Hazard",
        "piracy": "Hijack / Piracy",
        "pirate": "Hijack / Piracy",
        "hijack": "Hijack / Piracy",
        "boarding": "Hijack / Piracy",
        "war": "War / Geopolitical",
        "conflict": "War / Geopolitical",
        "country": "War / Geopolitical",
        "geopolitical": "War / Geopolitical",
        "sanction": "War / Geopolitical",
        "port": "Port / Infrastructure",
        "canal": "Port / Infrastructure",
        "congestion": "Port / Infrastructure",
        "cyber": "Cyber / AIS Integrity",
        "ais": "Cyber / AIS Integrity",
        "gps": "Cyber / AIS Integrity",
        "cargo": "Cargo Crime",
        "theft": "Cargo Crime",
        "fuel": "Market / Fuel Shock",
        "market": "Market / Fuel Shock",
    }
    for token, category in aliases.items():
        if token in requested:
            return category
    return "Natural Hazard"


def ai_category_for_zone(zone_type: str) -> str:
    zone_type = str(zone_type or "").lower()
    if "weather" in zone_type:
        return "Natural Hazard"
    if "geo" in zone_type:
        return "War / Geopolitical"
    if "security" in zone_type:
        return "Hijack / Piracy"
    if "congestion" in zone_type:
        return "Port / Infrastructure"
    return "Natural Hazard"


def ai_keyword_score(text: str, keywords: list[str]) -> int:
    lowered = str(text or "").lower()
    hits = 0
    for keyword in keywords:
        keyword = str(keyword or "").lower().strip()
        if not keyword:
            continue
        if len(keyword) <= 4 and keyword.replace("-", "").isalnum():
            hits += 1 if re.search(rf"\b{re.escape(keyword)}\b", lowered) else 0
        else:
            hits += 1 if keyword in lowered else 0
    return hits


def ai_alert_severity_weight(severity: str) -> float:
    return {"critical": 18, "high": 14, "warning": 9, "medium": 7, "low": 3, "info": 1}.get(str(severity or "").lower(), 4)


def ai_prediction_windows(category: str, score: float, alert_count: int, context_boost: float) -> list[dict]:
    profile = AI_RISK_TAXONOMY[category]
    windows = [
        ("Now", 0, 0.0),
        ("+6h", 6, 3.5),
        ("+24h", 24, 7.5),
        ("+72h", 72, 10.5),
    ]
    rows = []
    for label, hours, drift in windows:
        no_action = clamp_percent(score + drift + min(9, alert_count * 1.5) + min(6, context_boost * 0.08))
        control_gain = 10 + min(18, len(profile.get("solutions", [])) * 3.5) + (6 if score >= 70 else 0)
        with_controls = clamp_percent(no_action - control_gain)
        rows.append({
            "category": category,
            "horizon": label,
            "hours": hours,
            "score_no_action": no_action,
            "score_with_controls": with_controls,
            "priority_no_action": mission_priority(no_action),
            "caution": profile["watch_phrase"] if label in {"Now", "+6h"} else f"Keep {profile['caution_window']} caution window active.",
        })
    return rows


def ai_playbook_for_category(category: str, score: float, route: TradeRoute | None = None) -> dict:
    category = normalize_ai_incident_type(category)
    profile = AI_RISK_TAXONOMY[category]
    route_name = f"{route.origin_port} to {route.destination_port}" if route else "Network-wide"
    priority = mission_priority(score)
    release_rule = "Admin approval required" if priority == "P1" else "Operator approval required" if priority == "P2" else "Normal watch"
    route_controls = [
        "Compare safest, fastest, lowest-cost, and balanced route options before release.",
        "Hold the route if the no-action projection stays P1 after controls.",
        f"Apply release rule: {release_rule}.",
    ]
    if category == "War / Geopolitical":
        route_controls.insert(0, "Avoid conflict zones, contested chokepoints, and sanctioned corridors until verified safe.")
    elif category == "Hijack / Piracy":
        route_controls.insert(0, "Avoid slow transit through the threat box and keep crew check-ins frequent.")
    elif category == "Natural Hazard":
        route_controls.insert(0, "Select the next safe-weather window before committing departure.")
    elif category == "Port / Infrastructure":
        route_controls.insert(0, "Stage arrivals outside the affected port and reserve overflow capacity.")

    return {
        "incident_type": category,
        "target_route": route_name,
        "risk_score": clamp_percent(score),
        "risk_level": ai_risk_level(score),
        "priority": priority,
        "caution_window": profile["caution_window"],
        "objective": profile["defensive_goal"],
        "prediction": (
            f"If no controls are applied, {category} can remain {mission_band(score)} through "
            f"{profile['caution_window']}. Controls should lower the first response window by 10-25 points."
        ),
        "immediate_steps": profile["solutions"][:4],
        "route_controls": route_controls,
        "cargo_controls": [
            "Freeze public visibility of sensitive cargo and expose details only to verified roles.",
            "Require manual release for P1/P2 cargo while the incident is active.",
            "Attach cargo owner, route decision, and evidence to the audit trail.",
        ],
        "communications": [
            "Send one concise command update to fleet, port, cargo, and customer teams.",
            "Keep security-sensitive details out of public reports.",
            "Re-issue the update when the forecast window changes priority.",
        ],
        "escalation": [
            "P1: Admin/command approval and incident record.",
            "P2: Operator owner and timed reassessment.",
            "P3: Monitor in Risk & Alerts and keep evidence fresh.",
        ],
        "avoid": [
            "Do not release vessels only because the current ETA is commercially convenient.",
            "Do not expose sensitive cargo or security details to Public role views.",
            "Do not treat simulated or fallback feeds as verified live intelligence without the provider status check.",
        ],
        "data_inputs": profile["data_inputs"],
    }


def ai_decision_memory(db: Session) -> list[dict]:
    rows = []
    actions = db.query(AIAction).order_by(AIAction.updated_at.desc()).limit(18).all()
    incidents = db.query(IncidentEvent).order_by(IncidentEvent.timestamp.desc()).limit(12).all()
    risk_logs = db.query(RiskLog).order_by(RiskLog.timestamp.desc()).limit(12).all()

    for action in actions:
        if len(rows) >= 12:
            break
        rows.append({
            "time": action.updated_at.isoformat() if action.updated_at else None,
            "memory_type": "AI action",
            "subject": action.subject,
            "status": action.status,
            "priority": action.priority,
            "lesson": f"{action.source} recommended {action.recommendation[:110]}",
        })
    for event in incidents:
        if len(rows) >= 18:
            break
        rows.append({
            "time": event.timestamp.isoformat() if event.timestamp else None,
            "memory_type": "Incident",
            "subject": event.vessel_name or event.route or event.location,
            "status": event.status,
            "priority": "P1" if event.severity == "high" else "P2",
            "lesson": f"{event.category} incident: {event.description[:120]}",
        })
    for log in risk_logs:
        if len(rows) >= 22:
            break
        route_name = f"{log.route.origin_port} to {log.route.destination_port}" if getattr(log, "route", None) else f"Route #{log.route_id}"
        rows.append({
            "time": log.timestamp.isoformat() if log.timestamp else None,
            "memory_type": "Risk log",
            "subject": route_name,
            "status": "recorded",
            "priority": mission_priority(float(log.risk_score or 0) * 10),
            "lesson": f"Historical route score was {float(log.risk_score or 0):.1f}/10; compare against current forecast before release.",
        })
    rows.sort(key=lambda row: row.get("time") or "", reverse=True)
    if not rows:
        rows.append({
            "time": None,
            "memory_type": "Cold start",
            "subject": "AI Risk Brain",
            "status": "learning",
            "priority": "P3",
            "lesson": "No prior decisions found yet. New actions and incidents will become decision memory.",
        })
    return rows[:16]


def build_ai_risk_intelligence(db: Session) -> dict:
    generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    alerts = unique_by(
        db.query(ThreatAlert).order_by(ThreatAlert.id.desc()).limit(160).all(),
        lambda alert: (alert.title, alert.location, alert.severity),
    )
    assessments = get_ai_route_assessments(db)
    predictions = get_vessel_predictions(limit=80, db=db).get("predictions", [])
    weather = get_maritime_weather(db)
    ports = get_port_congestion(db)
    operations = get_operations_intelligence_v2(db)
    forecast = get_risk_forecast(days=7, db=db)
    ais_status = get_aisstream_status()
    manifests = db.query(CargoManifest).order_by(CargoManifest.updated_at.desc()).limit(220).all()

    top_route_score = max([float(item.get("score", 0) or 0) for item in assessments] or [0])
    top_forecast_score = max([float(item.get("forecast_score", 0) or 0) for item in forecast.get("forecast", [])] or [0])
    high_delay_vessels = [item for item in predictions if float(item.get("delay_risk", 0) or 0) >= 7]
    slow_or_stopped = [item for item in predictions if str(item.get("status", "")).lower() != "active" or float(item.get("speed_knots", 0) or 0) <= 1]
    cargo_counts = Counter(manifest.priority for manifest in manifests if manifest_is_verified(manifest))
    high_value_cargo = [
        manifest for manifest in manifests
        if manifest_is_verified(manifest) and str(manifest.cargo_class).lower() in {"critical", "high value", "energy", "priority"}
    ]
    max_weather = max(weather.get("ports", []), key=lambda row: row.get("weather_score", 0), default={})
    max_port = max(ports.get("ports", []), key=lambda row: row.get("congestion_score", 0), default={})

    categories = []
    forecast_rows = []
    for category, profile in AI_RISK_TAXONOMY.items():
        keywords = profile.get("keywords", [])
        matched_alerts = []
        alert_pressure = 0.0
        for alert in alerts:
            text = f"{alert.title} {alert.description} {alert.location}"
            if ai_keyword_score(text, keywords):
                matched_alerts.append(alert)
                alert_pressure += ai_alert_severity_weight(alert.severity)

        matched_zones = [
            zone for zone in GLOBAL_RISK_ZONES
            if zone.get("type") in profile.get("zone_types", [])
        ]
        zone_pressure = max([float(zone.get("risk", 0) or 0) * 3.35 for zone in matched_zones] or [0])
        route_pressure = max(0.0, top_route_score - 5.0) * 3.0
        forecast_pressure = max(0.0, top_forecast_score - 5.0) * 2.4
        context_boost = 0.0
        context_signals = []

        if category == "Natural Hazard":
            context_boost += float(max_weather.get("weather_score", 0) or 0) * 0.28
            if max_weather:
                context_signals.append(f"{max_weather.get('port')} weather score {max_weather.get('weather_score')}/100")
        elif category == "Hijack / Piracy":
            context_boost += min(22, len(slow_or_stopped) * 3.8) + min(9, cargo_counts.get("P1", 0) * 2.5)
            if slow_or_stopped:
                context_signals.append(f"{len(slow_or_stopped)} slow/stopped vessel signal(s)")
        elif category == "War / Geopolitical":
            context_boost += forecast_pressure + (7 if any(zone.get("risk", 0) >= 8 for zone in matched_zones) else 0)
            context_signals.append(f"{len([zone for zone in matched_zones if zone.get('risk', 0) >= 7])} high geopolitical chokepoint(s)")
        elif category == "Port / Infrastructure":
            context_boost += float(max_port.get("congestion_score", 0) or 0) * 0.3
            if max_port:
                context_signals.append(f"{max_port.get('port')} congestion score {max_port.get('congestion_score')}/100")
        elif category == "Cyber / AIS Integrity":
            if not ais_status.get("enabled"):
                context_boost += 10
                context_signals.append("AIS provider is not enabled")
            if ais_status.get("last_error"):
                context_boost += 18
                context_signals.append("AIS provider reports a connection warning")
            if ais_status.get("enabled") and not ais_status.get("connected"):
                context_boost += 14
                context_signals.append("AIS provider enabled but not connected")
        elif category == "Cargo Crime":
            context_boost += min(26, cargo_counts.get("P1", 0) * 5 + cargo_counts.get("P2", 0) * 2.4 + len(high_value_cargo) * 1.2)
            if high_value_cargo:
                context_signals.append(f"{len(high_value_cargo)} verified high-value/critical cargo record(s)")
        elif category == "Market / Fuel Shock":
            context_boost += forecast_pressure + min(8, len(operations.get("top_actions", [])) * 1.2)
            context_signals.append("Route optimizer should compare safety, distance, cost, and delay before release")

        score = clamp_percent(profile["base_score"] + alert_pressure + zone_pressure + route_pressure + context_boost)
        priority = mission_priority(score)
        level = ai_risk_level(score)
        evidence = []
        evidence.extend([
            f"{len(matched_alerts)} matched alert(s)" if matched_alerts else "No direct alert match yet",
            f"{len(matched_zones)} global watch zone(s)" if matched_zones else "No static global zone match",
        ])
        evidence.extend(context_signals[:3])
        if top_route_score:
            evidence.append(f"Peak route score {top_route_score:.1f}/10")
        if top_forecast_score:
            evidence.append(f"Peak 7-day forecast {top_forecast_score:.1f}/10")

        impacted_routes = [
            {
                "route": item.get("route"),
                "score": item.get("score"),
                "band": item.get("band"),
                "action": item.get("action"),
            }
            for item in assessments[:4]
        ]
        impacted_vessels = [
            {
                "vessel": item.get("vessel"),
                "delay_risk": item.get("delay_risk"),
                "nearest_port": item.get("nearest_port"),
                "cargo": item.get("cargo"),
                "action": item.get("recommended_action"),
                "position_lat": item.get("position_lat"),
                "position_lon": item.get("position_lon"),
                "display_position_lat": item.get("display_position_lat"),
                "display_position_lon": item.get("display_position_lon"),
                "motion_source": item.get("motion_source"),
                "motion_trail": item.get("motion_trail", []),
            }
            for item in (high_delay_vessels or predictions)[:4]
        ]
        windows = ai_prediction_windows(category, score, len(matched_alerts), context_boost)
        forecast_rows.extend(windows)
        categories.append({
            "category": category,
            "risk_score": score,
            "risk_level": level,
            "priority": priority,
            "band": mission_band(score),
            "caution_window": profile["caution_window"],
            "prediction": f"{level}. {windows[-1]['horizon']} no-action projection {windows[-1]['score_no_action']}/100; with controls {windows[-1]['score_with_controls']}/100.",
            "ai_solution": profile["solutions"][0],
            "solution_steps": profile["solutions"],
            "caution": profile["watch_phrase"],
            "evidence": evidence,
            "matched_alerts": [
                {
                    "title": alert.title,
                    "severity": alert.severity,
                    "location": alert.location,
                }
                for alert in matched_alerts[:5]
            ],
            "watch_zones": sorted(matched_zones, key=lambda zone: zone.get("risk", 0), reverse=True)[:5],
            "impacted_routes": impacted_routes,
            "impacted_vessels": impacted_vessels,
            "playbook": ai_playbook_for_category(category, score),
        })

    categories = sorted(categories, key=lambda row: row["risk_score"], reverse=True)
    overall = max([row["risk_score"] for row in categories] or [0])
    top_category = categories[0] if categories else {}
    caution_bullets = []
    for row in categories[:4]:
        caution_bullets.append(f"{row['priority']} {row['category']}: {row['ai_solution']}")

    map_zones = []
    for zone in GLOBAL_RISK_ZONES:
        score = clamp_percent(float(zone.get("risk", 0) or 0) * 10)
        category = ai_category_for_zone(zone.get("type"))
        map_zones.append({
            "name": zone.get("name"),
            "lat": zone.get("lat"),
            "lon": zone.get("lon"),
            "radius_nm": zone.get("radius_nm"),
            "risk_score": score,
            "priority": mission_priority(score),
            "category": category,
            "note": zone.get("note"),
        })

    return {
        "generated_at": generated_at,
        "summary": {
            "overall_score": overall,
            "overall_band": mission_band(overall),
            "overall_priority": mission_priority(overall),
            "top_category": top_category.get("category"),
            "top_caution": top_category.get("caution"),
            "source_mode": "live AIS + fallback intelligence" if ais_status.get("enabled") else "fallback intelligence until AIS provider is connected",
            "categories_monitored": len(categories),
            "actionable_categories": len([row for row in categories if row["priority"] in {"P1", "P2"}]),
        },
        "categories": categories,
        "forecast": forecast_rows,
        "cautions": caution_bullets,
        "decision_memory": ai_decision_memory(db),
        "map_layers": {
            "risk_zones": sorted(map_zones, key=lambda row: row["risk_score"], reverse=True),
            "focus_routes": [
                {
                    "route": item.get("route"),
                    "score": item.get("score"),
                    "priority": mission_priority(float(item.get("score", 0) or 0) * 10),
                    "action": item.get("action"),
                    "path": route_path_from_name(item.get("route")),
                }
                for item in assessments[:8]
            ],
            "vessels": [
                {
                    "name": item.get("vessel"),
                    "lat": item.get("display_position_lat", item.get("position_lat")),
                    "lon": item.get("display_position_lon", item.get("position_lon")),
                    "api_lat": item.get("api_position_lat", item.get("position_lat")),
                    "api_lon": item.get("api_position_lon", item.get("position_lon")),
                    "delay_risk": item.get("delay_risk"),
                    "priority": mission_priority(float(item.get("delay_risk", 0) or 0) * 10),
                    "cargo": item.get("cargo"),
                    "nearest_port": item.get("nearest_port"),
                    "motion_source": item.get("motion_source"),
                    "motion_trail": item.get("motion_trail", []),
                }
                for item in predictions[:12]
                if item.get("position_lat") is not None and item.get("position_lon") is not None
            ],
        },
        "explainability": {
            "method": "Classifies risk into maritime incident categories, scores them from live alerts, global chokepoints, route forecasts, AIS health, vessel delay, cargo priority, weather, and port congestion.",
            "risk_levels": ["Level 1 - Normal", "Level 2 - Watch", "Level 3 - Elevated", "Level 4 - High", "Level 5 - Critical"],
            "limits": [
                "External weather/security/port feeds remain simulated unless provider keys are configured.",
                "This is decision support; verified operators still approve release, reroute, and incident actions.",
            ],
        },
    }


@app.get("/ai/risk-intelligence")
def get_ai_risk_intelligence(db: Session = Depends(get_db)):
    return build_ai_risk_intelligence(db)


@app.get("/ai/incident-playbook")
def get_ai_incident_playbook(
    incident_type: str = "Natural Hazard",
    route_id: int | None = None,
    db: Session = Depends(get_db),
):
    route = db.query(TradeRoute).filter(TradeRoute.id == route_id).first() if route_id else None
    if route_id and not route:
        raise HTTPException(status_code=404, detail="Route not found")
    intelligence = build_ai_risk_intelligence(db)
    category = normalize_ai_incident_type(incident_type)
    category_row = next((row for row in intelligence.get("categories", []) if row["category"] == category), None)
    score = float(category_row.get("risk_score", 0) if category_row else 0)
    playbook = ai_playbook_for_category(category, score, route=route)
    playbook["evidence"] = category_row.get("evidence", []) if category_row else []
    playbook["forecast"] = [row for row in intelligence.get("forecast", []) if row.get("category") == category]
    return playbook


@app.post("/ai/risk-intelligence/action")
def run_ai_risk_intelligence_action(
    payload: RiskIntelligenceActionRequest,
    db: Session = Depends(get_db),
    request: Request = None,
):
    require_any_permission(request, ["approve_actions", "manage_alert_workflows", "run_scenarios"], "AI Risk Brain actions")
    category = normalize_ai_incident_type(payload.incident_type)
    route = db.query(TradeRoute).filter(TradeRoute.id == payload.route_id).first() if payload.route_id else None
    route_name = f"{route.origin_port} to {route.destination_port}" if route else payload.target or "Global network"
    intelligence = build_ai_risk_intelligence(db)
    category_row = next((row for row in intelligence.get("categories", []) if row["category"] == category), {})
    priority = str(payload.priority or category_row.get("priority") or "P2").upper()
    recommendation = payload.note or category_row.get("ai_solution") or f"Activate {category} defensive playbook."
    action_name = command_action_label(payload.action or "queue_playbook")

    if action_name in {"create_incident", "open_incident", "incident"}:
        record = record_incident_once(
            db,
            title=f"{category} AI caution: {route_name}",
            category=category,
            severity="high" if priority == "P1" else "medium",
            location=route_name,
            vessel_name="",
            route=route_name if route else "",
            description=recommendation,
            source="AI Risk Brain",
        )
        record_audit_event(
            db,
            action="ai_risk_incident_created",
            resource=route_name,
            detail=f"{priority} {category}: {recommendation}",
            severity="critical" if priority == "P1" else "warning",
            request=request,
        )
        db.commit()
        db.refresh(record)
        return {"status": "incident_created", "record": serialize_incident(record), "playbook": ai_playbook_for_category(category, category_row.get("risk_score", 0), route)}

    record = upsert_ai_action(
        db,
        subject=route_name,
        priority=priority if priority in {"P1", "P2", "P3"} else "P2",
        action_type=action_name,
        recommendation=recommendation,
        evidence=" | ".join(category_row.get("evidence", [])[:4]) or f"AI Risk Brain detected {category}.",
        owner=payload.owner or "AI Risk Brain",
        source="AI Risk Brain",
    )
    record_audit_event(
        db,
        action="ai_risk_action_queued",
        resource=route_name,
        detail=f"{priority} {category}: {recommendation}",
        severity="critical" if priority == "P1" else "warning",
        request=request,
    )
    db.commit()
    db.refresh(record)
    return {"status": "queued", "record": serialize_ai_action(record), "playbook": ai_playbook_for_category(category, category_row.get("risk_score", 0), route)}


def command_action_label(action: str) -> str:
    return str(action or "").strip().lower().replace(" ", "_").replace("-", "_")


def mission_overlay_color(score: float, priority: str | None = None) -> list[int]:
    priority = str(priority or "").upper()
    if priority == "P1" or score >= 75:
        return [239, 68, 68, 230]
    if priority == "P2" or score >= 45:
        return [245, 158, 11, 220]
    return [34, 211, 238, 210]


def route_path_from_name(route_name: str) -> list[list[float]]:
    parts = [part.strip() for part in str(route_name or "").split(" to ", 1)]
    if len(parts) != 2:
        return []
    origin = PORT_COORDS.get(parts[0])
    destination = PORT_COORDS.get(parts[1])
    if not origin or not destination:
        return []
    return [[origin[1], origin[0]], [destination[1], destination[0]]]


def overlay_point_for_label(label: str, index: int = 0) -> tuple[float, float]:
    text = str(label or "")
    for name, coords in {**PORT_COORDS, **SCENARIO_LOCATIONS}.items():
        if name.lower() in text.lower():
            return coords
    seed = sum(ord(char) for char in text) + (index * 97)
    lat = -35 + (seed % 70)
    lon = -165 + ((seed * 7) % 330)
    return float(lat), float(lon)


@app.get("/ai/mission-map-overlay")
def get_mission_map_overlay(db: Session = Depends(get_db)):
    war_room = build_war_room(db)
    predictions = get_vessel_predictions(limit=18, db=db)["predictions"]
    impacted = war_room.get("impacted_assets", {})

    route_lines = []
    for item in impacted.get("routes", [])[:8]:
        route_name = item.get("route")
        path = route_path_from_name(route_name)
        if not path:
            continue
        score = float(item.get("score", 0) or 0) * 10
        route_lines.append({
            "route": route_name,
            "score": item.get("score"),
            "band": item.get("band"),
            "action": item.get("action"),
            "path": path,
            "color": mission_overlay_color(score),
            "width": 5 if score >= 75 else 3,
        })

    vessel_points = []
    for vessel in predictions[:10]:
        risk = float(vessel.get("delay_risk", 0) or 0) * 10
        vessel_points.append({
            "name": vessel.get("vessel"),
            "route": vessel.get("route"),
            "lat": vessel.get("display_position_lat", vessel.get("position_lat")),
            "lon": vessel.get("display_position_lon", vessel.get("position_lon")),
            "api_lat": vessel.get("api_position_lat", vessel.get("position_lat")),
            "api_lon": vessel.get("api_position_lon", vessel.get("position_lon")),
            "risk": vessel.get("delay_risk"),
            "band": vessel.get("delay_band"),
            "cargo": vessel.get("cargo"),
            "action": vessel.get("recommended_action"),
            "heading": vessel.get("heading"),
            "motion_source": vessel.get("motion_source", "live feed"),
            "motion_trail": vessel.get("motion_trail", []),
            "color": mission_overlay_color(risk),
            "radius": 190000 if risk >= 75 else 130000,
        })

    alert_points = []
    for index, alert in enumerate(impacted.get("alerts", [])[:8]):
        lat, lon = overlay_point_for_label(alert.get("target"), index)
        priority = alert.get("priority", "P3")
        alert_points.append({
            "target": alert.get("target"),
            "priority": priority,
            "signals": alert.get("signals"),
            "action": alert.get("action"),
            "lat": lat,
            "lon": lon,
            "color": mission_overlay_color(80 if priority == "P1" else 52 if priority == "P2" else 20, priority),
            "radius": 250000 if priority == "P1" else 170000,
        })

    return {
        "generated_at": war_room.get("generated_at"),
        "summary": {
            "command_mode": war_room.get("command_mode"),
            "active_focus": war_room.get("active_focus"),
            "active_signal": war_room.get("active_signal"),
            "mission_score": war_room.get("mission_score"),
            "response_window": war_room.get("response_window"),
        },
        "routes": route_lines,
        "vessels": vessel_points,
        "alerts": alert_points,
        "decision_gates": war_room.get("decision_gates", []),
        "explainability": "Mission overlay fuses War Room impacted routes, ETA predictions, and notification clusters into one map layer.",
    }


def autopilot_slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return cleaned[:70] or "intervention"


def autopilot_owner_for_lane(lane: str) -> str:
    lane = str(lane or "").lower()
    if "route" in lane or "forecast" in lane:
        return "Risk analyst"
    if "fleet" in lane or "cargo" in lane:
        return "Fleet controller"
    if "alert" in lane:
        return "Alert triage"
    if "data" in lane or "ais" in lane:
        return "Platform admin"
    return "Command desk"


def autopilot_action_for_lane(lane: str) -> str:
    lane = str(lane or "").lower()
    if "route" in lane:
        return "create_incident"
    if "alert" in lane:
        return "escalate_notification"
    if "data" in lane:
        return "queue_action"
    if "forecast" in lane:
        return "queue_action"
    return "assign_owner"


def route_id_by_name(db: Session) -> dict[str, int]:
    routes = unique_by(
        db.query(TradeRoute).order_by(TradeRoute.id).all(),
        lambda route: (route.origin_port, route.destination_port),
    )
    return {f"{route.origin_port} to {route.destination_port}": route.id for route in routes}


def build_strategic_autopilot(db: Session) -> dict:
    mission = build_mission_control(db)
    war_room = build_war_room(db)
    overlay = get_mission_map_overlay(db=db)
    operations = get_operations_intelligence_v2(db)
    assessments = get_ai_route_assessments(db)
    predictions = get_vessel_predictions(limit=24, db=db)["predictions"]
    digest = notification_digest(limit=180, db=db)
    quality = get_data_quality(db)
    hardening = get_deployment_hardening(db)
    routes_by_name = route_id_by_name(db)

    mission_score = float(mission.get("mission_score", 0) or 0)
    readiness = float(operations.get("readiness_score", 0) or 0)
    quality_score = float(quality.get("score", 0) or 0)
    hardening_score = float(hardening.get("score", 0) or 0)
    p1_actions = int(operations.get("summary", {}).get("p1_actions", 0) or 0)
    open_incidents = int(operations.get("summary", {}).get("open_incidents", 0) or 0)
    top_route_score = float(assessments[0].get("score", 0) or 0) * 10 if assessments else 0
    top_delay_score = float(predictions[0].get("delay_risk", 0) or 0) * 10 if predictions else 0
    alert_pressure = float(digest.get("pressure_score", 0) or 0)

    no_action_risk = clamp_percent(
        (mission_score * 0.32)
        + (top_route_score * 0.18)
        + (top_delay_score * 0.14)
        + (alert_pressure * 0.14)
        + (max(0, 100 - readiness) * 0.12)
        + (p1_actions * 4)
        + (open_incidents * 1.4)
        + (max(0, 100 - quality_score) * 0.04)
    )

    interventions = []
    for priority in mission.get("priorities", [])[:7]:
        score = float(priority.get("score", 0) or 0)
        if score < 25:
            continue
        lane = priority.get("lane", "Command")
        target = priority.get("signal") or lane
        action = priority.get("action") or "Assign an owner and verify evidence."
        reduction = clamp_percent(8 + (score * 0.18))
        intervention_id = f"{autopilot_slug(lane)}-{autopilot_slug(target)}"
        interventions.append({
            "id": intervention_id,
            "priority": mission_priority(score),
            "lane": lane,
            "target": target,
            "owner": autopilot_owner_for_lane(lane),
            "action": action,
            "execute_action": autopilot_action_for_lane(lane),
            "expected_risk_reduction": reduction,
            "timebox": "0-15 min" if score >= 75 else "15-45 min" if score >= 45 else "Today",
            "success_metric": "Risk, alert pressure, or readiness improves on next refresh.",
            "evidence": f"Lane score {score}/100 from Mission Control.",
        })

    for vessel in predictions[:3]:
        delay = float(vessel.get("delay_risk", 0) or 0)
        if delay < 6:
            continue
        interventions.append({
            "id": f"vessel-delay-{autopilot_slug(vessel.get('vessel'))}",
            "priority": "P1" if delay >= 8 else "P2",
            "lane": "Vessel ETA",
            "target": vessel.get("vessel"),
            "owner": "Fleet controller",
            "action": vessel.get("recommended_action") or "Verify ETA and notify receiving port.",
            "execute_action": "assign_owner",
            "expected_risk_reduction": clamp_percent(6 + (delay * 2.1)),
            "timebox": "0-30 min",
            "success_metric": "ETA risk is acknowledged and owner assigned.",
            "evidence": f"Delay risk {delay}/10, route {vessel.get('route')}, cargo {vessel.get('cargo')}.",
        })

    if not interventions:
        interventions.append({
            "id": "autopilot-cruise-watch",
            "priority": "P3",
            "lane": "Autopilot cruise",
            "target": "Global network",
            "owner": "Command desk",
            "action": "Keep monitoring mission telemetry and refresh before the next route release.",
            "execute_action": "queue_action",
            "expected_risk_reduction": 5,
            "timebox": "Today",
            "success_metric": "Mission score remains stable.",
            "evidence": "No lane exceeded intervention threshold.",
        })

    interventions = sorted(
        {item["id"]: item for item in interventions}.values(),
        key=lambda item: ({"P1": 0, "P2": 1, "P3": 2}.get(item["priority"], 3), -item["expected_risk_reduction"]),
    )[:10]
    total_reduction = clamp_percent(sum(item["expected_risk_reduction"] for item in interventions[:5]) * 0.65)
    execute_plan_risk = clamp_percent(no_action_risk - total_reduction)

    route_shield = []
    for route in assessments[:4]:
        route_name = route.get("route")
        route_id = routes_by_name.get(route_name)
        alternatives = []
        if route_id:
            alternatives = get_route_alternatives(route_id=route_id, db=db).get("alternatives", [])[:3]
        route_shield.append({
            "route": route_name,
            "risk": route.get("score"),
            "band": route.get("band"),
            "decision": route.get("decision"),
            "best_mode": alternatives[0].get("mode") if alternatives else "monitor",
            "best_risk": alternatives[0].get("risk_score") if alternatives else route.get("score"),
            "alternatives": alternatives,
        })

    trajectory = [
        {"time": "Now", "without_autopilot": no_action_risk, "with_autopilot": no_action_risk, "event": "Current operating picture"},
        {"time": "+15m", "without_autopilot": clamp_percent(no_action_risk + 4), "with_autopilot": clamp_percent(no_action_risk - (total_reduction * 0.35)), "event": "Owners assigned"},
        {"time": "+45m", "without_autopilot": clamp_percent(no_action_risk + 7), "with_autopilot": clamp_percent(no_action_risk - (total_reduction * 0.62)), "event": "Route/vessel controls verified"},
        {"time": "+2h", "without_autopilot": clamp_percent(no_action_risk + 10), "with_autopilot": clamp_percent(execute_plan_risk), "event": "Command gates checked"},
        {"time": "+6h", "without_autopilot": clamp_percent(no_action_risk + 13), "with_autopilot": clamp_percent(execute_plan_risk + 2), "event": "Sustained watch"},
    ]

    blast_radius = {
        "p1_actions": p1_actions,
        "open_incidents": open_incidents,
        "critical_notifications": len([item for item in get_notifications(limit=80, db=db) if item.get("severity") == "critical"]),
        "high_risk_routes": len([route for route in assessments if float(route.get("score", 0) or 0) >= 7]),
        "delay_risk_vessels": len([vessel for vessel in predictions if float(vessel.get("delay_risk", 0) or 0) >= 7]),
        "p1_cargo": int(operations.get("cargo_priority_counts", {}).get("P1", 0) or 0),
    }

    confidence = clamp_percent((quality_score * 0.45) + (hardening_score * 0.2) + (35 if get_aisstream_status().get("connected") else 15))
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "mode": "Autonomous Lockdown" if no_action_risk >= 80 else "Autonomous Watch" if no_action_risk >= 45 else "Autonomous Cruise",
        "objective": "Reduce mission risk with the smallest safe set of human-approved interventions.",
        "summary": (
            f"Without intervention, projected command risk is {no_action_risk}/100. "
            f"Executing the top plan can lower it toward {execute_plan_risk}/100."
        ),
        "risk_projection": {
            "without_autopilot": no_action_risk,
            "with_autopilot": execute_plan_risk,
            "estimated_reduction": clamp_percent(no_action_risk - execute_plan_risk),
            "confidence": confidence,
        },
        "trajectory": trajectory,
        "interventions": interventions,
        "route_shield": route_shield,
        "blast_radius": blast_radius,
        "map_overlay": overlay,
        "war_room": {
            "command_mode": war_room.get("command_mode"),
            "response_window": war_room.get("response_window"),
            "decision_gates": war_room.get("decision_gates", []),
        },
        "trust": {
            "data_quality": quality_score,
            "deployment_hardening": hardening_score,
            "aisstream_connected": bool(get_aisstream_status().get("connected")),
            "explainability": [
                "Uses Mission Control lane pressure, route risk, ETA predictions, notification digest, data quality, and deployment hardening.",
                "Every execution path writes an audit event and queues human-owned action records.",
                "Public cannot see or execute this page.",
            ],
        },
    }


def latest_history_groups(db: Session, limit: int = 1200) -> dict[str, list[AISPositionHistory]]:
    groups: dict[str, list[AISPositionHistory]] = {}
    rows = db.query(AISPositionHistory).order_by(AISPositionHistory.timestamp.desc()).limit(limit).all()
    for row in rows:
        keys = {
            normalize_manifest_lookup_key(row.vessel_identifier),
            normalize_manifest_lookup_key(row.vessel_name),
        }
        for key in keys:
            if key and key not in {"unknown", "none"}:
                groups.setdefault(key, []).append(row)
    return groups


def signal_age_seconds(vessel: dict, history: list[AISPositionHistory], now: datetime.datetime) -> float | None:
    timestamp = parse_iso_datetime(vessel.get("last_signal_at"))
    if not timestamp and history:
        timestamp = history[0].timestamp
        if timestamp and timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=datetime.timezone.utc)
    if not timestamp:
        return None
    return max(0.0, (now - timestamp).total_seconds())


def anomaly_priority(score: float) -> str:
    if score >= 75:
        return "P1"
    if score >= 45:
        return "P2"
    return "P3"


def anomaly_band(score: float) -> str:
    if score >= 75:
        return "Critical"
    if score >= 45:
        return "Warning"
    if score >= 25:
        return "Watch"
    return "Normal"


def anomaly_action(types: list[str], vessel: dict, delay_risk: float) -> str:
    name = vessel.get("name") or vessel_identifier(vessel)
    joined = " ".join(types).lower()
    if "ais silence" in joined:
        return f"Open AIS verification for {name}, contact vessel or port agent, and hold automated release until signal freshness is confirmed."
    if "stopped" in joined or "speed collapse" in joined:
        return f"Assign fleet controller to {name}, verify engine/berth state, and update ETA before route release."
    if "damaged" in joined or "destroyed" in joined:
        return f"Escalate {name} to incident command and freeze dependent cargo/route decisions."
    if delay_risk >= 7:
        return f"Review {name} delay risk and notify receiving terminal with revised ETA controls."
    return f"Keep {name} on control-tower watch and refresh AIS/history before the next decision gate."


def build_vessel_anomaly_cards(
    db: Session,
    vessels: list[dict],
    predictions: list[dict],
    source: str,
    limit: int = 18,
) -> list[dict]:
    now = datetime.datetime.now(datetime.timezone.utc)
    stale_seconds = max(60, int(float(os.getenv("AISSTREAM_STALE_SECONDS", "900") or 900)))
    history_groups = latest_history_groups(db)
    prediction_lookup = {
        normalize_manifest_lookup_key(row.get("vessel")): row
        for row in predictions
        if row.get("vessel")
    }
    rows = []
    for vessel in vessels:
        identifier = vessel_identifier(vessel)
        name = str(vessel.get("name") or identifier)
        keys = [
            normalize_manifest_lookup_key(identifier),
            normalize_manifest_lookup_key(vessel.get("mmsi")),
            normalize_manifest_lookup_key(name),
        ]
        history = next((history_groups[key] for key in keys if key and key in history_groups), [])
        prediction = prediction_lookup.get(normalize_manifest_lookup_key(name), {})
        speed = parse_float(vessel.get("speed_knots"), 0)
        status = vessel_status(vessel)
        delay_risk = parse_float(prediction.get("delay_risk"), 0)
        cargo_priority = effective_vessel_cargo_priority(vessel)
        verified_cargo = cargo_is_verified_source(vessel)
        age_seconds = signal_age_seconds(vessel, history, now)
        score = 0.0
        types: list[str] = []
        evidence: list[str] = []

        if status in {"destroyed", "disabled"}:
            score += 82
            types.append("Critical vessel status")
            evidence.append(f"Status is {status}.")
        elif status == "damaged":
            score += 58
            types.append("Damaged vessel")
            evidence.append("Vessel status is damaged.")

        if age_seconds is not None:
            if age_seconds > stale_seconds * 2:
                score += 45
                types.append("AIS silence")
                evidence.append(f"Last signal is {int(age_seconds // 60)} minutes old.")
            elif age_seconds > stale_seconds:
                score += 30
                types.append("Stale AIS")
                evidence.append(f"Signal age {int(age_seconds)} seconds exceeds freshness policy.")

        previous_speeds = [parse_float(row.speed_knots, 0) for row in history[1:8]]
        if speed <= 0.5 and status == "active":
            score += 30
            types.append("Stopped vessel")
            evidence.append("Current speed is near zero while status is active.")
        elif speed <= 3 and status == "active":
            score += 15
            types.append("Slow movement")
            evidence.append(f"Current speed is {speed:.1f} kn.")
        if previous_speeds and speed <= 3 and max(previous_speeds) >= 8:
            score += 18
            types.append("Speed collapse")
            evidence.append(f"Recent speed dropped from {max(previous_speeds):.1f} kn to {speed:.1f} kn.")

        if history:
            latest_heading = parse_float(vessel.get("heading"), parse_float(history[0].heading, 0))
            older_headings = [parse_float(row.heading, latest_heading) for row in history[1:5]]
            if older_headings and max(abs(latest_heading - heading) for heading in older_headings) >= 105:
                score += 8
                types.append("Heading swing")
                evidence.append("Heading changed sharply across recent AIS samples.")

        if cargo_priority == "P1":
            score += 22 if verified_cargo else 12
            types.append("Priority cargo")
            evidence.append(f"Cargo priority {cargo_priority}; source {vessel.get('cargo_source', 'unknown')}.")
        elif cargo_priority == "P2":
            score += 10
            evidence.append(f"Cargo priority {cargo_priority}.")
        if not verified_cargo and str(vessel.get("cargo_source") or "").lower().startswith("inferred"):
            score += 4
            evidence.append("Cargo is inferred, not operator-verified.")

        if delay_risk >= 8:
            score += 24
            types.append("High delay risk")
            evidence.append(f"Predictive ETA delay risk is {delay_risk}/10.")
        elif delay_risk >= 6:
            score += 14
            types.append("Delay watch")
            evidence.append(f"Delay risk is {delay_risk}/10.")

        route_name = str(vessel.get("route") or "")
        nearest = nearest_port(vessel_lat(vessel), vessel_lon(vessel))
        if route_name and "ais corridor" not in route_name.lower() and nearest not in route_name:
            score += 7
            types.append("Route drift")
            evidence.append(f"Nearest port {nearest} is outside route label {route_name}.")

        score = clamp_percent(score)
        if score < 22 and status == "active":
            continue
        if not types:
            types.append("Operational watch")
        rows.append({
            "vessel": name,
            "vessel_identifier": identifier,
            "priority": anomaly_priority(score),
            "band": anomaly_band(score),
            "anomaly_score": score,
            "anomaly_type": ", ".join(dict.fromkeys(types)),
            "recommended_action": anomaly_action(types, vessel, delay_risk),
            "evidence": evidence[:5],
            "owner": "Fleet controller" if score >= 45 else "Watch desk",
            "source": str(vessel.get("source") or source),
            "route": route_name or prediction.get("route", "Unknown"),
            "nearest_port": nearest,
            "speed_knots": round(speed, 1),
            "heading": parse_float(vessel.get("heading"), 0),
            "last_signal_age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
            "cargo": str(vessel.get("cargo") or "Unknown"),
            "cargo_priority": cargo_priority,
            "cargo_verified": verified_cargo,
            "position_lat": vessel_lat(vessel),
            "position_lon": vessel_lon(vessel),
            "display_position_lat": vessel_display_lat(vessel),
            "display_position_lon": vessel_display_lon(vessel),
            "api_position_lat": vessel.get("api_position_lat", vessel_lat(vessel)),
            "api_position_lon": vessel.get("api_position_lon", vessel_lon(vessel)),
            "motion_source": vessel.get("motion_source", source),
            "motion_trail": vessel.get("motion_trail", [[vessel_lon(vessel), vessel_lat(vessel)], [vessel_display_lon(vessel), vessel_display_lat(vessel)]]),
        })
    return sorted(rows, key=lambda row: (-row["anomaly_score"], row["vessel"]))[:limit]


def build_route_mode_cards(db: Session, assessments: list[dict], limit: int = 5) -> list[dict]:
    routes_by_name = route_id_by_name(db)
    cards = []
    for route in assessments[:limit]:
        route_name = route.get("route")
        route_id = routes_by_name.get(route_name)
        if not route_id:
            continue
        try:
            optimizer = get_route_optimizer(route_id=route_id, db=db)
        except HTTPException:
            continue
        modes = optimizer.get("modes", {})
        safest = modes.get("safest", {})
        fastest = modes.get("fastest", {})
        cheapest = modes.get("lowest_cost", {})
        balanced = modes.get("balanced", {})
        current_risk = parse_float(route.get("score"), parse_float(optimizer.get("current_score"), 0))
        safest_risk = parse_float(safest.get("risk_score"), current_risk)
        cards.append({
            "route_id": route_id,
            "route": route_name,
            "current_risk": current_risk,
            "current_band": route.get("band"),
            "safest_route": safest.get("name", "Current route"),
            "safest_risk": safest_risk,
            "fastest_route": fastest.get("name", "Current route"),
            "fastest_distance_nm": fastest.get("distance_nm"),
            "lowest_cost_route": cheapest.get("name", "Current route"),
            "lowest_cost_index": cheapest.get("cost_index"),
            "balanced_route": balanced.get("name", "Current route"),
            "balanced_score": balanced.get("balanced_score"),
            "risk_delta_if_safest": round(safest_risk - current_risk, 2),
            "recommendation": (
                f"Use {safest.get('name', 'the safest option')} for P1 cargo or active alerts."
                if safest_risk < current_risk
                else "Current route remains acceptable; keep alert watch active."
            ),
            "geometry": safest.get("geometry") or [],
            "options": optimizer.get("options", [])[:4],
        })
    return cards


def build_control_tower_plan(autopilot: dict, anomalies: list[dict], route_modes: list[dict], digest: dict) -> list[dict]:
    plan = []
    for anomaly in anomalies[:4]:
        plan.append({
            "id": f"anomaly-{autopilot_slug(anomaly.get('vessel'))}",
            "lane": "Vessel anomaly",
            "target": anomaly.get("vessel"),
            "priority": anomaly.get("priority"),
            "owner": anomaly.get("owner"),
            "action": anomaly.get("recommended_action"),
            "evidence": "; ".join(anomaly.get("evidence", [])[:2]),
            "timebox": "0-15 min" if anomaly.get("priority") == "P1" else "15-45 min",
        })
    for route in route_modes[:3]:
        if parse_float(route.get("current_risk"), 0) >= 6 or parse_float(route.get("risk_delta_if_safest"), 0) < 0:
            plan.append({
                "id": f"route-{autopilot_slug(route.get('route'))}",
                "lane": "Route mode",
                "target": route.get("route"),
                "priority": "P1" if parse_float(route.get("current_risk"), 0) >= 8 else "P2",
                "owner": "Risk analyst",
                "action": route.get("recommendation"),
                "evidence": f"Safest risk {route.get('safest_risk')} vs current {route.get('current_risk')}.",
                "timebox": "0-30 min",
            })
    for intervention in autopilot.get("interventions", [])[:3]:
        plan.append({
            "id": intervention.get("id"),
            "lane": intervention.get("lane"),
            "target": intervention.get("target"),
            "priority": intervention.get("priority"),
            "owner": intervention.get("owner"),
            "action": intervention.get("action"),
            "evidence": intervention.get("evidence"),
            "timebox": intervention.get("timebox"),
        })
    for card in digest.get("cards", [])[:2]:
        plan.append({
            "id": f"digest-{autopilot_slug(card.get('target'))}",
            "lane": "Notification digest",
            "target": card.get("target"),
            "priority": card.get("priority"),
            "owner": "Alert triage",
            "action": card.get("recommended_action"),
            "evidence": f"{card.get('signals')} grouped signals from {card.get('sources')}.",
            "timebox": "Today",
        })
    unique = {item["id"]: item for item in plan if item.get("id")}
    return sorted(
        unique.values(),
        key=lambda item: ({"P1": 0, "P2": 1, "P3": 2}.get(item.get("priority"), 3), str(item.get("lane"))),
    )[:12]


def build_voyage_control_tower(db: Session) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc)
    vessels, vessel_source = get_operational_vessels(db)
    predictions_packet = get_vessel_predictions(limit=80, db=db)
    predictions = predictions_packet.get("predictions", [])
    assessments = get_ai_route_assessments(db)
    anomalies = build_vessel_anomaly_cards(db, vessels, predictions, vessel_source)
    route_modes = build_route_mode_cards(db, assessments)
    autopilot = build_strategic_autopilot(db)
    digest = notification_digest(limit=180, db=db)
    reliability = get_system_reliability(db)
    queued_actions = db.query(AIAction).filter(AIAction.status.in_(["queued", "approved"])).order_by(AIAction.updated_at.desc()).limit(8).all()
    open_incidents = db.query(IncidentEvent).filter(IncidentEvent.status.in_(["open", "investigating", "escalated"])).order_by(IncidentEvent.timestamp.desc()).limit(8).all()

    top_route_pressure = max([parse_float(route.get("score"), 0) * 10 for route in assessments] or [0])
    top_anomaly_pressure = max([parse_float(row.get("anomaly_score"), 0) for row in anomalies] or [0])
    autopilot_pressure = parse_float(autopilot.get("risk_projection", {}).get("without_autopilot"), 0)
    notification_pressure = parse_float(digest.get("pressure_score"), 0)
    reliability_gap = max(0, 100 - parse_float(reliability.get("score"), 0))
    control_score = clamp_percent(
        (autopilot_pressure * 0.34)
        + (top_route_pressure * 0.22)
        + (top_anomaly_pressure * 0.24)
        + (notification_pressure * 0.1)
        + (reliability_gap * 0.1)
    )
    if control_score >= 75:
        mode = "Intervene Now"
        watch_window = "0-15 min"
    elif control_score >= 55:
        mode = "Active Control"
        watch_window = "15-45 min"
    elif control_score >= 30:
        mode = "Command Watch"
        watch_window = "Today"
    else:
        mode = "Autonomous Cruise"
        watch_window = "Next refresh"

    plan = build_control_tower_plan(autopilot, anomalies, route_modes, digest)
    primary = plan[0] if plan else {}
    timeline = [
        {
            "time": "Now",
            "event": primary.get("action") or "Control tower has no urgent intervention.",
            "risk_if_idle": control_score,
            "risk_if_controlled": control_score,
        },
        {
            "time": "+15m",
            "event": "Owners assigned, AIS anomalies checked, and route mode chosen.",
            "risk_if_idle": clamp_percent(control_score + 5),
            "risk_if_controlled": clamp_percent(control_score - 12),
        },
        {
            "time": "+45m",
            "event": "Safest route or vessel control confirmed by verified role.",
            "risk_if_idle": clamp_percent(control_score + 9),
            "risk_if_controlled": clamp_percent(control_score - 20),
        },
        {
            "time": "+2h",
            "event": "Incident/alert queue compressed and report-ready command trail available.",
            "risk_if_idle": clamp_percent(control_score + 13),
            "risk_if_controlled": clamp_percent(control_score - 26),
        },
    ]
    return {
        "generated_at": now.isoformat(),
        "mode": mode,
        "watch_window": watch_window,
        "control_score": control_score,
        "summary": (
            f"{mode}: control score {control_score}/100 with {len(anomalies)} vessel anomaly watch item(s), "
            f"{len(route_modes)} route mode comparison(s), and {digest.get('compressed_total', 0)} compressed alert group(s)."
        ),
        "primary_decision": {
            "target": primary.get("target", "Global network"),
            "action": primary.get("action", "Maintain autonomous cruise watch."),
            "priority": primary.get("priority", "P3"),
            "owner": primary.get("owner", "Command desk"),
            "timebox": primary.get("timebox", watch_window),
        },
        "scores": {
            "autopilot_pressure": autopilot_pressure,
            "route_pressure": top_route_pressure,
            "vessel_anomaly_pressure": top_anomaly_pressure,
            "notification_pressure": notification_pressure,
            "reliability_score": reliability.get("score", 0),
        },
        "vessel_source": vessel_source,
        "vessels_tracked": len(vessels),
        "anomalies": anomalies,
        "route_modes": route_modes,
        "autonomous_plan": plan,
        "timeline": timeline,
        "approval_queue": [serialize_ai_action(action) for action in queued_actions],
        "open_incidents": [serialize_incident(event) for event in open_incidents],
        "alert_digest": digest.get("cards", [])[:8],
        "reliability": {
            "score": reliability.get("score"),
            "band": reliability.get("band"),
            "checks": reliability.get("checks", []),
            "signals": reliability.get("signals", {}),
        },
        "map": {
            "vessels": anomalies[:12],
            "routes": route_modes[:5],
        },
        "explainability": [
            "Scores fuse Strategic Autopilot pressure, route risk, vessel anomalies, notification pressure, and reliability gaps.",
            "Vessel anomalies use AIS freshness, speed collapse, status, cargo priority, ETA delay risk, and route drift signals.",
            "Actions are not silent automation: every execution requires a verified role and writes AI action, incident, or audit records.",
        ],
    }


@app.get("/ai/voyage-control-tower")
def get_voyage_control_tower(db: Session = Depends(get_db)):
    return build_voyage_control_tower(db)


@app.post("/ai/voyage-control-tower/action")
def execute_voyage_control_tower_action(
    payload: ControlTowerActionRequest,
    db: Session = Depends(get_db),
    request: Request = None,
):
    require_any_permission(
        request,
        ["approve_actions", "manage_alert_workflows", "manage_vessels", "generate_reports"],
        "Voyage Control Tower action",
    )
    action = str(payload.action or "queue_action").strip().lower()
    allowed = {"queue_action", "assign_owner", "reroute", "hold_route", "create_incident", "approve_action", "complete_action"}
    if action not in allowed:
        raise HTTPException(status_code=400, detail=f"Action must be one of {sorted(allowed)}")

    now = datetime.datetime.now(datetime.timezone.utc)
    target = (payload.target or "Global network").strip()
    priority = payload.priority if payload.priority in {"P1", "P2", "P3"} else "P2"
    note = payload.note or {
        "reroute": f"Compare safest route alternatives and prepare controlled reroute for {target}.",
        "hold_route": f"Hold release for {target} until AIS, cargo, and alert evidence is confirmed.",
        "create_incident": f"Create incident workflow for {target} from Voyage Control Tower.",
        "assign_owner": f"Assign {payload.owner} as control owner for {target}.",
        "queue_action": f"Queue control-tower action for {target}.",
        "approve_action": f"Approve existing AI action for {target}.",
        "complete_action": f"Complete existing AI action for {target}.",
    }.get(action, f"Queue control-tower action for {target}.")

    touched_record = None
    if payload.action_id and action in {"approve_action", "complete_action"}:
        existing = db.query(AIAction).filter(AIAction.id == payload.action_id).first()
        if not existing:
            raise HTTPException(status_code=404, detail="AI action not found")
        existing.status = "approved" if action == "approve_action" else "completed"
        existing.owner = payload.owner or existing.owner
        existing.updated_at = now
        touched_record = existing
    else:
        touched_record = upsert_ai_action(
            db,
            subject=target,
            priority=priority,
            action_type="Voyage Control Tower",
            recommendation=note,
            evidence=f"Action={action}; generated by autonomous control tower.",
            owner=payload.owner or "Control Tower",
            source="Voyage Control Tower",
        )

    incident = None
    if action in {"create_incident", "hold_route"} or priority == "P1":
        incident = record_incident_once(
            db,
            title=f"Control Tower: {target}",
            category="Voyage Control Tower",
            severity="high" if priority == "P1" else "medium",
            location=target,
            vessel_name=target,
            route=target,
            description=note,
            source="Voyage Control Tower",
        )

    record_audit_event(
        db,
        action=f"voyage_control_tower_{action}",
        resource=target,
        detail=note,
        severity="critical" if priority == "P1" else "warning",
        request=request,
    )
    db.commit()
    db.refresh(touched_record)
    result = {
        "status": "executed",
        "action": action,
        "record": serialize_ai_action(touched_record),
    }
    if incident:
        db.refresh(incident)
        result["incident"] = serialize_incident(incident)
    return result


@app.get("/ai/strategic-autopilot")
def get_strategic_autopilot(db: Session = Depends(get_db)):
    return build_strategic_autopilot(db)


@app.post("/ai/strategic-autopilot/execute")
def execute_strategic_autopilot(
    payload: AutopilotExecuteRequest,
    db: Session = Depends(get_db),
    request: Request = None,
):
    require_any_permission(request, ["approve_actions", "manage_alert_workflows", "generate_reports"], "Strategic Autopilot execution")
    plan = build_strategic_autopilot(db)
    intervention = next((item for item in plan.get("interventions", []) if item.get("id") == payload.intervention_id), None)
    if not intervention:
        raise HTTPException(status_code=404, detail="Autopilot intervention not found")

    owner = payload.owner or intervention.get("owner") or "Strategic Autopilot"
    note = payload.note or intervention.get("action") or "Strategic Autopilot intervention queued."
    target = intervention.get("target") or intervention.get("lane") or "Autopilot"
    priority = intervention.get("priority", "P2")
    execute_action = intervention.get("execute_action")
    record = None
    status = "queued"

    if execute_action in {"create_incident", "escalate_notification"} or priority == "P1":
        event = record_incident_once(
            db,
            title=f"Autopilot intervention: {intervention.get('lane')}",
            category="Strategic Autopilot",
            severity="high" if priority == "P1" else "medium",
            location=str(target),
            vessel_name=str(target),
            route=str(target),
            description=note,
            source="Strategic Autopilot",
        )
        record = event
        status = "incident_created"
    else:
        action = upsert_ai_action(
            db,
            subject=str(target),
            priority=priority,
            action_type="Strategic Autopilot",
            recommendation=note,
            evidence=intervention.get("evidence", "Generated by strategic autopilot."),
            owner=owner,
            source="Strategic Autopilot",
        )
        record = action

    record_audit_event(
        db,
        action="strategic_autopilot_executed",
        resource=str(target),
        detail=f"{owner} executed {payload.intervention_id}: {note}",
        severity="critical" if priority == "P1" else "warning",
        request=request,
    )
    db.commit()
    if isinstance(record, IncidentEvent):
        db.refresh(record)
        serialized = serialize_incident(record)
    else:
        db.refresh(record)
        serialized = serialize_ai_action(record)
    return {
        "status": status,
        "intervention": intervention,
        "record": serialized,
        "risk_projection": plan.get("risk_projection", {}),
    }


@app.post("/command/actions")
def run_command_action(
    payload: CommandActionRequest,
    db: Session = Depends(get_db),
    request: Request = None,
):
    action = command_action_label(payload.action)
    now = datetime.datetime.now(datetime.timezone.utc)
    target = payload.target or "Command"
    result: dict = {
        "action": action,
        "target": target,
        "owner": payload.owner,
        "status": "completed",
        "timestamp": now.isoformat(),
    }

    if action in {"generate_brief", "daily_brief", "mission_pack", "export_pack"}:
        require_permission(request, "generate_reports", "Command report generation")
    elif action in {"assign_owner", "assign", "queue_action", "create_incident", "incident", "mark_resolved", "resolve", "resolved"}:
        require_any_permission(request, ["approve_actions", "manage_alert_workflows"], "Command actions")

    if action in {"assign_owner", "assign", "queue_action"}:
        ai_action = upsert_ai_action(
            db,
            subject=target,
            priority=payload.priority or "P2",
            action_type="Command assignment",
            recommendation=payload.note or f"{payload.owner} assigned to handle {target}.",
            evidence=f"Created from {payload.source}.",
            owner=payload.owner,
            source=payload.source or "War Room",
        )
        record_audit_event(
            db,
            action="command_assignment_created",
            resource=target,
            detail=payload.note or f"{payload.owner} assigned to {target}.",
            severity="warning" if payload.priority in {"P1", "P2"} else "info",
            request=request,
        )
        db.commit()
        db.refresh(ai_action)
        result["record"] = serialize_ai_action(ai_action)

    elif action in {"create_incident", "incident"}:
        event = record_incident_once(
            db,
            title=f"Command action: {target}",
            category="Command",
            severity="high" if payload.priority == "P1" else "medium" if payload.priority == "P2" else "low",
            location=target,
            vessel_name=target,
            route=target,
            description=payload.note or f"Incident created from {payload.source}.",
            source=payload.source or "War Room",
        )
        record_audit_event(
            db,
            action="command_incident_created",
            resource=target,
            detail=payload.note or "Incident card created from command action.",
            severity="critical" if payload.priority == "P1" else "warning",
            request=request,
        )
        db.commit()
        db.refresh(event)
        result["record"] = serialize_incident(event)

    elif action in {"mark_resolved", "resolve", "resolved"}:
        event = None
        if payload.incident_id:
            event = db.query(IncidentEvent).filter(IncidentEvent.id == payload.incident_id).first()
        if event is None:
            event = (
                db.query(IncidentEvent)
                .filter(IncidentEvent.status == "open")
                .filter(
                    (IncidentEvent.title == target)
                    | (IncidentEvent.vessel_name == target)
                    | (IncidentEvent.route == target)
                    | (IncidentEvent.location == target)
                )
                .order_by(IncidentEvent.timestamp.desc())
                .first()
            )
        if not event:
            raise HTTPException(status_code=404, detail="Open incident not found for target")
        event.status = "resolved"
        event.description = f"{event.description}\nResolved by {payload.owner}: {payload.note or 'No note.'}"
        record_audit_event(
            db,
            action="incident_resolved",
            resource=target,
            detail=payload.note or f"{payload.owner} resolved incident.",
            severity="info",
            request=request,
        )
        db.commit()
        db.refresh(event)
        result["record"] = serialize_incident(event)

    elif action in {"generate_brief", "daily_brief"}:
        result["record"] = get_daily_brief(db=db, request=request)

    elif action in {"mission_pack", "export_pack"}:
        result["record"] = get_mission_pack(db=db, request=request)

    else:
        raise HTTPException(status_code=400, detail="Unsupported command action")

    return result


@app.post("/operations/inbox/action")
def act_on_operations_inbox(
    payload: InboxActionRequest,
    db: Session = Depends(get_db),
    request: Request = None,
):
    require_any_permission(request, ["approve_actions", "manage_alert_workflows", "generate_reports", "edit_cargo"], "Operations inbox actions")
    action = command_action_label(payload.action)
    item_type = command_action_label(payload.item_type)
    target = payload.target or "Command"
    note = payload.note or f"{payload.action.replace('_', ' ').title()} from Smart Operations Inbox."
    now = datetime.datetime.now(datetime.timezone.utc)

    if item_type == "ai_action" and payload.item_id and str(payload.item_id).isdigit():
        record = db.query(AIAction).filter(AIAction.id == int(payload.item_id)).first()
        if not record:
            raise HTTPException(status_code=404, detail="Inbox AI action not found")
        if action in {"resolve", "complete", "fix_now"}:
            record.status = "completed"
        elif action in {"escalate", "approve"}:
            record.status = "approved"
            record.priority = "P1"
        else:
            record.status = "approved"
        record.owner = payload.owner or record.owner
        record.updated_at = now
        record_audit_event(
            db,
            action="operations_inbox_ai_action",
            resource=record.subject,
            detail=note,
            severity="warning" if record.priority in {"P1", "P2"} else "info",
            request=request,
        )
        db.commit()
        db.refresh(record)
        return {"status": record.status, "record": serialize_ai_action(record), "inbox": build_operations_inbox(db, limit=25)["summary"]}

    if item_type == "incident" and payload.item_id and str(payload.item_id).isdigit():
        incident = db.query(IncidentEvent).filter(IncidentEvent.id == int(payload.item_id)).first()
        if not incident:
            raise HTTPException(status_code=404, detail="Inbox incident not found")
        if action in {"resolve", "complete", "fix_now"}:
            incident.status = "resolved"
        elif action == "escalate":
            incident.status = "escalated"
            incident.severity = "high"
        else:
            incident.status = "investigating"
        incident.description = f"{incident.description}\nSmart Inbox update by {payload.owner}: {note}"
        record_audit_event(
            db,
            action="operations_inbox_incident",
            resource=incident.vessel_name or incident.route or incident.location,
            detail=note,
            severity="critical" if incident.status == "escalated" else "warning",
            request=request,
        )
        db.commit()
        db.refresh(incident)
        return {"status": incident.status, "record": serialize_incident(incident), "inbox": build_operations_inbox(db, limit=25)["summary"]}

    command_action = "create_incident" if action == "escalate" else "assign_owner"
    if action in {"resolve", "complete"}:
        command_action = "resolve"
    result = run_command_action(
        CommandActionRequest(
            action=command_action,
            target=target,
            owner=payload.owner,
            note=note,
            priority=payload.priority,
            source="Smart Operations Inbox",
        ),
        db=db,
        request=request,
    )
    result["inbox"] = build_operations_inbox(db, limit=25)["summary"]
    return result


@app.post("/notifications/action")
def act_on_notification(
    payload: NotificationActionRequest,
    db: Session = Depends(get_db),
    request: Request = None,
):
    require_any_permission(request, ["approve_actions", "manage_alert_workflows"], "Notification triage actions")
    action = command_action_label(payload.action)
    target = (payload.target or "Notification target").strip()
    owner = (payload.owner or "Operations").strip()
    priority = str(payload.priority or "P2").upper()
    note = payload.note or f"{owner} triaged notification target: {target}."

    if action in {"investigate", "assign", "assign_owner", "watch", "monitor"}:
        if action in {"watch", "monitor"}:
            priority = "P3"
        ai_action = upsert_ai_action(
            db,
            subject=target,
            priority=priority,
            action_type="Notification triage",
            recommendation=note,
            evidence="Created from the notification digest/action center.",
            owner=owner,
            source="Notification Center",
        )
        record_audit_event(
            db,
            action="notification_triage_queued",
            resource=target,
            detail=note,
            severity="warning" if priority in {"P1", "P2"} else "info",
            request=request,
        )
        db.commit()
        db.refresh(ai_action)
        return {"status": "queued", "target": target, "record": serialize_ai_action(ai_action)}

    if action in {"escalate", "create_incident", "incident"}:
        event = record_incident_once(
            db,
            title=f"Notification escalation: {target}",
            category="Notification",
            severity="high" if priority == "P1" else "medium",
            location=target,
            vessel_name=target,
            route=target,
            description=note,
            source="Notification Center",
        )
        upsert_ai_action(
            db,
            subject=target,
            priority="P1" if priority == "P1" else "P2",
            action_type="Notification escalation",
            recommendation=note,
            evidence="Escalated from the notification digest/action center.",
            owner=owner,
            source="Notification Center",
        )
        record_audit_event(
            db,
            action="notification_escalated",
            resource=target,
            detail=note,
            severity="critical" if priority == "P1" else "warning",
            request=request,
        )
        db.commit()
        db.refresh(event)
        return {"status": "escalated", "target": target, "record": serialize_incident(event)}

    if action in {"resolve", "clear", "acknowledge"}:
        event = (
            db.query(IncidentEvent)
            .filter(IncidentEvent.status.in_(["open", "investigating", "escalated"]))
            .filter(
                (IncidentEvent.title.contains(target))
                | (IncidentEvent.vessel_name == target)
                | (IncidentEvent.route == target)
                | (IncidentEvent.location == target)
            )
            .order_by(IncidentEvent.timestamp.desc())
            .first()
        )
        if event:
            event.status = "resolved"
            event.description = f"{event.description}\nNotification resolved by {owner}: {note}"
        record_audit_event(
            db,
            action="notification_acknowledged",
            resource=target,
            detail=note,
            severity="info",
            request=request,
        )
        db.commit()
        return {
            "status": "resolved" if event else "acknowledged",
            "target": target,
            "record": serialize_incident(event) if event else None,
        }

    raise HTTPException(status_code=400, detail="Unsupported notification action")


@app.get("/incidents")
def get_incidents(status: str | None = None, limit: int = 80, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 300))
    query = db.query(IncidentEvent).order_by(IncidentEvent.timestamp.desc())
    if status:
        query = query.filter(IncidentEvent.status == status)
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "events": [serialize_incident(event) for event in query.limit(limit).all()],
    }


@app.post("/incidents/{incident_id}/status")
def update_incident_status(
    incident_id: int,
    payload: IncidentStatusUpdate,
    db: Session = Depends(get_db),
    request: Request = None,
):
    require_any_permission(request, ["approve_actions", "manage_alert_workflows"], "Incident workflow updates")
    allowed = {"open", "investigating", "escalated", "resolved"}
    status = str(payload.status or "").strip().lower()
    if status not in allowed:
        raise HTTPException(status_code=400, detail=f"Status must be one of {sorted(allowed)}")
    event = db.query(IncidentEvent).filter(IncidentEvent.id == incident_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Incident not found")
    event.status = status
    note = payload.note or f"{payload.owner} moved incident to {status}."
    event.description = f"{event.description}\nWorkflow update: {note}"
    if status in {"escalated", "investigating"}:
        upsert_ai_action(
            db,
            subject=event.vessel_name or event.route or event.location or event.title,
            priority="P1" if status == "escalated" or event.severity == "high" else "P2",
            action_type="Incident workflow",
            recommendation=note,
            evidence=event.description,
            owner=payload.owner,
            source="Incident workflow",
        )
    record_audit_event(
        db,
        action=f"incident_{status}",
        resource=event.title,
        detail=note,
        severity="critical" if status == "escalated" else "warning" if status == "investigating" else "info",
        request=request,
    )
    db.commit()
    db.refresh(event)
    return serialize_incident(event)


@app.get("/ai/decision-timeline")
def get_decision_timeline(limit: int = 120, db: Session = Depends(get_db)):
    limit = max(20, min(limit, 300))
    rows = []
    for event in db.query(IncidentEvent).order_by(IncidentEvent.timestamp.desc()).limit(limit).all():
        rows.append({
            "timestamp": event.timestamp.isoformat() if event.timestamp else None,
            "stage": "Incident",
            "subject": event.vessel_name or event.route or event.location or event.title,
            "status": event.status,
            "priority": "P1" if event.severity == "high" else "P2" if event.severity == "medium" else "P3",
            "decision": event.title,
            "evidence": event.description,
        })
    for action in db.query(AIAction).order_by(AIAction.updated_at.desc()).limit(limit).all():
        rows.append({
            "timestamp": action.updated_at.isoformat() if action.updated_at else None,
            "stage": "AI Action",
            "subject": action.subject,
            "status": action.status,
            "priority": action.priority,
            "decision": action.recommendation,
            "evidence": action.evidence,
        })
    for report in db.query(GeneratedReport).order_by(GeneratedReport.timestamp.desc()).limit(30).all():
        rows.append({
            "timestamp": report.timestamp.isoformat() if report.timestamp else None,
            "stage": "Report",
            "subject": "Mission brief",
            "status": "complete",
            "priority": "P3",
            "decision": "Report generated",
            "evidence": (report.content or "")[:180],
        })
    rows = sorted(rows, key=lambda item: item.get("timestamp") or "", reverse=True)[:limit]
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "events": list(reversed(rows)),
        "summary": {
            "events": len(rows),
            "p1": sum(1 for row in rows if row.get("priority") == "P1"),
            "open": sum(1 for row in rows if row.get("status") in {"open", "queued", "escalated"}),
        },
    }


@app.get("/ai/role-view")
def get_role_command_view(role: str = "Public", db: Session = Depends(get_db)):
    role = normalize_role(role or "Public")
    mission = build_mission_control(db)
    war_room = build_war_room(db)
    role_focus = {
        "Admin": ["approvals", "settings", "audit", "mission pack"],
        "Operator": ["fleet operations", "vessel ETA", "cargo handoff", "route safety", "forecast watch", "threat alerts", "reports"],
        "Public": ["sanitized summary", "public-safe status", "no sensitive cargo"],
    }.get(role, ["read-only summary"])
    priorities = mission.get("priorities", [])
    if role == "Operator":
        priorities = [
            item for item in priorities
            if item.get("lane") in {"Fleet operations", "Cargo exposure", "AIS live feed", "Route safety", "Threat alerts", "Forecast watch", "Data quality"}
        ] or priorities[:5]
    elif role == "Public":
        priorities = priorities[:4]
    response = {
        "role": role,
        "focus": role_focus,
        "mission_state": mission.get("mission_state"),
        "summary": mission.get("commander_summary"),
        "priorities": priorities,
        "actions": mission.get("next_best_actions", [])[:5],
        "war_room_mode": war_room.get("command_mode"),
    }
    if role == "Public":
        response["summary"] = f"Platform status: {mission.get('mission_state')}. Public view hides cargo, API, and incident details."
        response["priorities"] = [
            {
                "lane": item.get("lane"),
                "score": item.get("score"),
                "priority": item.get("priority"),
                "signal": "Sensitive details hidden",
                "action": "Public read-only monitoring",
                "page": item.get("page"),
            }
            for item in priorities
        ]
        response["actions"] = ["Public view is read-only.", "Sensitive cargo/API/incident details are hidden."]
    return response


@app.get("/ai/confidence-heatmap")
def get_confidence_heatmap(db: Session = Depends(get_db)):
    assessments = get_ai_route_assessments(db)
    quality = get_data_quality(db)
    predictions = get_vessel_predictions(limit=40, db=db)["predictions"]
    route_rows = []
    for item in assessments:
        confidence = float(item.get("confidence", 0) or 0)
        missing = item.get("missing_data", [])
        route_rows.append({
            "area": "Route",
            "name": item.get("route"),
            "confidence": confidence,
            "uncertainty": round(100 - confidence, 1),
            "missing_data": len(missing),
            "reason": ", ".join(missing) if missing else item.get("explanation", "No missing data."),
        })
    vessel_rows = []
    for item in predictions[:20]:
        speed = float(item.get("speed_knots", 0) or 0)
        confidence = 88
        if speed <= 1:
            confidence -= 12
        if item.get("cargo") == "Unknown":
            confidence -= 10
        vessel_rows.append({
            "area": "Vessel",
            "name": item.get("vessel"),
            "confidence": max(45, confidence),
            "uncertainty": 100 - max(45, confidence),
            "missing_data": 1 if item.get("cargo") == "Unknown" else 0,
            "reason": f"Speed {speed} kn, cargo {item.get('cargo')}.",
        })
    check_rows = [
        {
            "area": "Data Quality",
            "name": check.get("name"),
            "confidence": 95 if check.get("status") == "pass" else 70 if check.get("status") == "warn" else 40,
            "uncertainty": 5 if check.get("status") == "pass" else 30 if check.get("status") == "warn" else 60,
            "missing_data": 0 if check.get("status") == "pass" else 1,
            "reason": check.get("detail"),
        }
        for check in quality.get("checks", [])
    ]
    rows = route_rows + vessel_rows + check_rows
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "rows": rows,
        "summary": {
            "average_confidence": round(sum(row["confidence"] for row in rows) / len(rows), 1) if rows else 0,
            "lowest_confidence": min(rows, key=lambda row: row["confidence"]) if rows else None,
            "quality_score": quality.get("score"),
        },
    }


@app.get("/ports/congestion")
def get_port_congestion(db: Session = Depends(get_db)):
    vessels, source = get_operational_vessels(db)
    predictions = get_vessel_predictions(limit=120, db=db)["predictions"]
    manifests = db.query(CargoManifest).order_by(CargoManifest.updated_at.desc()).limit(300).all()
    manifest_by_destination = Counter(manifest.destination_port for manifest in manifests if manifest.priority in {"P1", "P2"})
    prediction_by_port: dict[str, list] = {}
    for prediction in predictions:
        prediction_by_port.setdefault(prediction.get("nearest_port", "Open Sea"), []).append(prediction)
    rows = []
    for port_name, coords in PORT_COORDS.items():
        local_vessels = [vessel for vessel in vessels if nearest_port(vessel_lat(vessel), vessel_lon(vessel)) == port_name]
        local_predictions = prediction_by_port.get(port_name, [])
        slow = sum(1 for vessel in local_vessels if parse_float(vessel.get("speed_knots"), 0) <= 1)
        avg_delay = sum(float(item.get("delay_risk", 0) or 0) for item in local_predictions) / len(local_predictions) if local_predictions else 0
        cargo_pressure = manifest_by_destination.get(port_name, 0)
        congestion = clamp_percent((len(local_vessels) * 8) + (slow * 12) + (avg_delay * 5) + (cargo_pressure * 3))
        rows.append({
            "port": port_name,
            "lat": coords[0],
            "lon": coords[1],
            "vessels": len(local_vessels),
            "slow_or_holding": slow,
            "priority_cargo_inbound": cargo_pressure,
            "avg_delay_risk": round(avg_delay, 1),
            "congestion_score": congestion,
            "band": mission_band(congestion),
            "recommended_staging": "Open overflow berth" if congestion >= 75 else "Stage arrivals" if congestion >= 45 else "Normal flow",
        })
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source": source,
        "ports": sorted(rows, key=lambda row: row["congestion_score"], reverse=True),
    }


@app.get("/cargo/custody")
def get_cargo_custody(limit: int = 80, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 200))
    manifests = db.query(CargoManifest).order_by(CargoManifest.updated_at.desc()).limit(limit).all()
    latest_history = {}
    for row in db.query(AISPositionHistory).order_by(AISPositionHistory.timestamp.desc()).limit(600).all():
        latest_history.setdefault(row.vessel_identifier, row)
        latest_history.setdefault(row.vessel_name, row)
    assessments = route_assessment_lookup(db)
    rows = []
    for manifest in manifests:
        ais = latest_history.get(manifest.vessel_identifier) or latest_history.get(manifest.vessel_name)
        route_name = f"{manifest.origin_port} to {manifest.destination_port}"
        route = assessments.get(route_name, {})
        custody_score = 100
        checkpoints = ["Manifest verified"]
        if ais:
            checkpoints.append("AIS confirmed")
        else:
            custody_score -= 25
            checkpoints.append("AIS missing")
        if manifest.priority == "P1":
            custody_score -= 10
            checkpoints.append("P1 command approval required")
        if float(route.get("score", 0) or 0) >= 7:
            custody_score -= 18
            checkpoints.append("Route risk review required")
        rows.append({
            "vessel": manifest.vessel_name,
            "cargo": manifest.cargo,
            "priority": manifest.priority,
            "origin": manifest.origin_port,
            "destination": manifest.destination_port,
            "custody_stage": "Destination handoff" if manifest.status == "delivered" else "In transit / monitored",
            "custody_score": max(0, custody_score),
            "route_risk": route.get("score", 0),
            "last_ais_port": ais.nearest_port if ais else "Unknown",
            "last_ais_time": ais.timestamp.isoformat() if ais and ais.timestamp else None,
            "checkpoints": " | ".join(checkpoints),
            "next_action": "Hold release until approval" if manifest.priority == "P1" else "Continue monitoring",
        })
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "chain": rows,
        "summary": {
            "tracked": len(rows),
            "p1": sum(1 for row in rows if row["priority"] == "P1"),
            "needs_ais": sum(1 for row in rows if row["last_ais_port"] == "Unknown"),
        },
    }


@app.get("/ai/self-check")
def get_ai_self_check(db: Session = Depends(get_db)):
    ais = get_aisstream_status()
    quality = get_data_quality(db)
    readiness = get_deployment_readiness(db)
    mission = build_mission_control(db)
    checks = [
        {"system": "AISStream live feed", "status": "pass" if ais.get("connected") else "warn" if ais.get("enabled") else "fail", "detail": f"{ais.get('vessel_count', 0)} live vessels."},
        {"system": "Route risk model", "status": "pass" if get_ai_route_assessments(db) else "fail", "detail": "Explainable route assessments available."},
        {"system": "Notification AI digest", "status": "pass" if mission.get("noise_reduced_digest") else "warn", "detail": "Grouping repeated alert pressure."},
        {"system": "Cargo intelligence", "status": "pass" if db.query(CargoManifest).count() else "warn", "detail": f"{db.query(CargoManifest).count()} manifests."},
        {"system": "Data quality", "status": quality.get("status"), "detail": f"{quality.get('score')}% quality score."},
        {"system": "Deployment readiness", "status": "pass" if readiness.get("score", 0) >= 85 else "warn", "detail": f"{readiness.get('score')}% readiness."},
    ]
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "overall": "pass" if all(check["status"] == "pass" for check in checks) else "warn",
        "checks": checks,
        "missing": [
            check["system"]
            for check in checks
            if check["status"] != "pass"
        ],
        "model_note": "AI uses live AIS when available, otherwise falls back to local/demo data with explicit status checks.",
    }


@app.get("/reports/mission-pack")
def get_mission_pack(db: Session = Depends(get_db), request: Request = None):
    mission = build_mission_control(db)
    war_room = build_war_room(db)
    self_check = get_ai_self_check(db)
    digest = notification_digest(db=db)
    autopilot = build_strategic_autopilot(db)
    ais_reliability = get_ais_reliability(db)
    lines = [
        "Exportable Mission Pack",
        f"Generated: {datetime.datetime.now(datetime.timezone.utc).isoformat()}",
        "",
        f"Mission: {mission.get('mission_state')} ({mission.get('mission_score')}/100)",
        mission.get("commander_summary", ""),
        "",
        "Strategic Autopilot",
        f"- Mode: {autopilot.get('mode')}",
        f"- Objective: {autopilot.get('objective')}",
        f"- Projection: no action {autopilot.get('risk_projection', {}).get('without_autopilot')}/100 -> plan {autopilot.get('risk_projection', {}).get('with_autopilot')}/100",
        "",
        f"War Room: {war_room.get('command_mode')} | Focus: {war_room.get('active_focus')} | Window: {war_room.get('response_window')}",
        "",
        "Priorities",
    ]
    for item in mission.get("priorities", [])[:6]:
        lines.append(f"- {item['priority']} {item['lane']}: {item['signal']} -> {item['action']}")
    lines.extend(["", "Timed Playbook"])
    for item in war_room.get("playbook", []):
        lines.append(f"- {item['timebox']} {item['phase']} ({item['owner']}): {item['action']}")
    lines.extend(["", "Decision Gates"])
    for item in war_room.get("decision_gates", []):
        lines.append(f"- {item['gate']}: {item['pass_condition']} Current: {item['current_signal']}")
    lines.extend(["", "Notification Digest"])
    lines.append(f"- Raw {digest.get('raw_total')} -> {digest.get('compressed_total')} targets, reduced {digest.get('noise_reduction')}.")
    lines.extend(["", "AIS Reliability"])
    lines.append(f"- {ais_reliability.get('status')} score {ais_reliability.get('score')}/100, live vessels {ais_reliability.get('summary', {}).get('live_vessels')}.")
    lines.append(f"- SSL verification: {ais_reliability.get('summary', {}).get('ssl_verification')}.")
    lines.extend(["", "Autopilot Interventions"])
    for item in autopilot.get("interventions", [])[:5]:
        lines.append(f"- {item['priority']} {item['lane']} / {item['target']}: {item['action']} ({item['timebox']})")
    lines.extend(["", "AI Self-Check"])
    for check in self_check.get("checks", []):
        lines.append(f"- {check['system']}: {check['status']} - {check['detail']}")
    content = "\n".join(lines)
    pdf_path = safe_generate_pdf_report(content)
    report = GeneratedReport(content=content, timestamp=datetime.datetime.now(datetime.timezone.utc))
    db.add(report)
    record_audit_event(
        db,
        action="mission_pack_generated",
        resource="Mission pack",
        detail="Mission pack generated from Mission Control and War Room.",
        severity="info",
        request=request,
    )
    db.commit()
    db.refresh(report)
    return {
        "report_id": report.id,
        "pdf_path": pdf_path,
        "content": content,
        "mission_state": mission.get("mission_state"),
        "command_mode": war_room.get("command_mode"),
    }


@app.get("/reports/daily-brief")
def get_daily_brief(db: Session = Depends(get_db), request: Request = None):
    mission = build_mission_control(db)
    lines = [
        "Daily Maritime Command Brief",
        f"Generated: {mission['generated_at']}",
        "",
        f"Mission state: {mission['mission_state']} ({mission['mission_score']}/100)",
        mission["commander_summary"],
        "",
        "Top command priorities",
    ]
    for item in mission.get("priorities", [])[:5]:
        lines.append(f"- {item['priority']} {item['lane']}: {item['signal']} -> {item['action']}")
    lines.extend(["", "Auto incident cards"])
    for card in mission.get("incident_cards", [])[:5]:
        lines.append(f"- {card['priority']} {card['title']}: {card['summary']}")
    lines.extend(["", "Next best actions"])
    for action in mission.get("next_best_actions", []):
        lines.append(f"- {action}")
    lines.extend(["", "Explainability", f"- {mission['explainability']['method']}"])
    content = "\n".join(lines)
    pdf_path = safe_generate_pdf_report(content)
    report = GeneratedReport(content=content, timestamp=datetime.datetime.now(datetime.timezone.utc))
    db.add(report)
    record_audit_event(
        db,
        action="daily_brief_generated",
        resource="Daily command brief",
        detail="Daily mission-control brief generated.",
        severity="info",
        request=request,
    )
    db.commit()
    db.refresh(report)
    return {
        "report_id": report.id,
        "pdf_path": pdf_path,
        "content": content,
        "mission_state": mission["mission_state"],
        "mission_score": mission["mission_score"],
    }


@app.get("/vessels/intelligence")
def get_vessel_intelligence(vessel_identifier: str, db: Session = Depends(get_db)):
    identifier = str(vessel_identifier or "").strip()
    if not identifier:
        raise HTTPException(status_code=400, detail="vessel_identifier is required")
    vessels, source = get_operational_vessels(db)
    selected = None
    lowered = identifier.lower()
    for vessel in vessels:
        aliases = {
            str(vessel.get("mmsi") or "").lower(),
            str(vessel.get("id") or "").lower(),
            str(vessel.get("name") or "").lower(),
            vessel_identifier and vessel_identifier.lower(),
        }
        if lowered in aliases:
            selected = vessel
            break
    if not selected:
        raise HTTPException(status_code=404, detail="Vessel not found")

    name = str(selected.get("name") or identifier)
    vessel_id = vessel_identifier if vessel_identifier else vessel_identifier
    history_rows = (
        db.query(AISPositionHistory)
        .filter(AISPositionHistory.vessel_identifier == identifier)
        .order_by(AISPositionHistory.timestamp.desc())
        .limit(80)
        .all()
    )
    if not history_rows:
        history_rows = (
            db.query(AISPositionHistory)
            .filter(AISPositionHistory.vessel_name == name)
            .order_by(AISPositionHistory.timestamp.desc())
            .limit(80)
            .all()
        )

    predictions = get_vessel_predictions(limit=200, db=db)["predictions"]
    prediction = next((row for row in predictions if str(row.get("vessel", "")).lower() == name.lower()), {})
    speed = parse_float(selected.get("speed_knots"), parse_float(prediction.get("speed_knots"), 0))
    status = str(selected.get("status") or "active")
    cargo_priority = effective_vessel_cargo_priority(selected) or prediction.get("cargo_priority") or "P3"
    last_signal = parse_iso_datetime(selected.get("last_signal_at"))
    age_seconds = (datetime.datetime.now(datetime.timezone.utc) - last_signal).total_seconds() if last_signal else None
    delay_risk = float(prediction.get("delay_risk", 4.5) or 4.5)
    score = delay_risk
    if cargo_priority == "P1":
        score += 1.2
    if speed <= 1 and status.lower() == "active":
        score += 1.1
    if age_seconds and age_seconds > 900:
        score += 1.0
    score = round(max(0, min(10, score)), 2)
    evidence = [
        f"Source {source}; status {status}; speed {speed:.1f} kn.",
        f"Cargo priority {cargo_priority}; cargo {selected.get('cargo') or prediction.get('cargo') or 'Unknown'}.",
        f"Nearest port {nearest_port(vessel_lat(selected), vessel_lon(selected))}; delay risk {delay_risk}/10.",
    ]
    if age_seconds is not None:
        evidence.append(f"Last AIS signal age {int(age_seconds)} seconds.")
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source": source,
        "vessel": selected,
        "risk_score": score,
        "risk_band": risk_band(score),
        "recommended_action": route_decision(score),
        "prediction": prediction,
        "evidence": evidence,
        "timeline": [serialize_ais_history(row) for row in reversed(history_rows)],
        "explainability": {
            "inputs": ["live AIS vessel row", "ETA prediction", "cargo priority", "AIS history"],
            "limits": ["Cargo can be inferred from manifest/demo enrichment if the AIS message does not include cargo."],
        },
    }


def canonical_global_port(name: str | None) -> str | None:
    if not name:
        return None
    normalized = " ".join(str(name).lower().replace("-", " ").split())
    if normalized in GLOBAL_PORT_ALIASES:
        return GLOBAL_PORT_ALIASES[normalized]
    for port in GLOBAL_PORTS:
        if port.lower() == normalized:
            return port
    return None


def extract_global_ports_from_question(question: str) -> list[str]:
    lowered = " " + re.sub(r"[^a-z0-9]+", " ", question.lower()) + " "
    matches = []
    for alias, canonical in GLOBAL_PORT_ALIASES.items():
        token = f" {alias.lower()} "
        index = lowered.find(token)
        if index >= 0:
            matches.append((index, canonical))
    for port in GLOBAL_PORTS:
        token = f" {port.lower()} "
        index = lowered.find(token)
        if index >= 0:
            matches.append((index, port))
    ordered = []
    for _, port in sorted(matches, key=lambda item: item[0]):
        if port not in ordered:
            ordered.append(port)
    return ordered[:2]


def distance_from_point_to_segment_nm(point_lat: float, point_lon: float, start: tuple[float, float], end: tuple[float, float]) -> float:
    samples = 14
    distances = []
    for index in range(samples + 1):
        ratio = index / samples
        lat = start[0] + ((end[0] - start[0]) * ratio)
        lon = start[1] + ((end[1] - start[1]) * ratio)
        distances.append(geo_distance_nm(point_lat, point_lon, lat, lon))
    return min(distances)


def route_distance_nm(path: list[str]) -> float:
    total = 0.0
    for index in range(len(path) - 1):
        start = GLOBAL_PORTS[path[index]]
        end = GLOBAL_PORTS[path[index + 1]]
        total += geo_distance_nm(start[0], start[1], end[0], end[1])
    return round(total, 1)


def route_zone_exposure(path: list[str]) -> list[dict]:
    exposures = []
    for zone in GLOBAL_RISK_ZONES:
        closest = float("inf")
        for index in range(len(path) - 1):
            start = GLOBAL_PORTS[path[index]]
            end = GLOBAL_PORTS[path[index + 1]]
            closest = min(closest, distance_from_point_to_segment_nm(zone["lat"], zone["lon"], start, end))
        if closest <= zone["radius_nm"]:
            strength = max(0.15, 1 - (closest / max(zone["radius_nm"], 1)))
            exposures.append({
                "zone": zone["name"],
                "type": zone["type"],
                "risk": zone["risk"],
                "distance_nm": round(closest, 1),
                "impact": round(zone["risk"] * strength, 2),
                "note": zone["note"],
            })
    return sorted(exposures, key=lambda item: item["impact"], reverse=True)


def global_port_region(port: str) -> str:
    lat, lon = GLOBAL_PORTS[port]
    if 35 <= lat <= 62 and -12 <= lon <= 35:
        return "Europe"
    if 10 <= lat <= 35 and 35 <= lon <= 62:
        return "Middle East"
    if -36 <= lat <= 35 and -20 <= lon <= 55:
        return "Africa"
    if 5 <= lat <= 30 and 60 <= lon <= 95:
        return "South Asia"
    if -12 <= lat <= 20 and 95 <= lon <= 125:
        return "Southeast Asia"
    if 20 <= lat <= 46 and 100 <= lon <= 145:
        return "East Asia"
    if -45 <= lat <= -10 and 110 <= lon <= 180:
        return "Oceania"
    if lon <= -30 and lat >= 5:
        return "North America"
    if lon <= -30 and lat < 5:
        return "South America"
    return "Global"


def maritime_plausibility_penalty(path: list[str]) -> tuple[float, list[str]]:
    origin_region = global_port_region(path[0])
    destination_region = global_port_region(path[-1])
    regions = {origin_region, destination_region}
    path_set = set(path)
    penalties = []
    penalty = 0.0

    asia_regions = {"South Asia", "Southeast Asia", "East Asia"}
    if "Europe" in regions and regions.intersection(asia_regions):
        if not path_set.intersection({"Suez", "Port Said", "Cape Town"}):
            penalty += 2.8
            penalties.append("Asia-Europe voyages need Suez/Port Said or Cape Town to stay maritime-plausible.")
    if regions == {"Europe", "Middle East"} and not path_set.intersection({"Suez", "Port Said", "Cape Town"}):
        penalty += 2.1
        penalties.append("Europe-Middle East routing normally needs Suez/Port Said or a Cape detour.")
    if "Piraeus" in path_set and not path_set.intersection({"Suez", "Port Said"}) and regions.intersection(asia_regions | {"Middle East"}):
        penalty += 1.4
        penalties.append("Mediterranean routing without Suez/Port Said is incomplete.")
    if "Europe" in regions and regions.intersection(asia_regions | {"Middle East"}) and path_set.intersection({"Suez", "Port Said"}):
        if path[0] and global_port_region(path[0]) in asia_regions | {"Middle East"}:
            med_indexes = [path.index(port) for port in ["Piraeus", "Tangier Med", "Algeciras"] if port in path_set]
            canal_indexes = [path.index(port) for port in ["Suez", "Port Said"] if port in path_set]
            if med_indexes and canal_indexes and min(med_indexes) < min(canal_indexes):
                penalty += 2.4
                penalties.append("Mediterranean hubs must come after the Suez/Port Said passage on Asia-Europe routes.")
        if path[-1] and global_port_region(path[-1]) in asia_regions | {"Middle East"}:
            med_indexes = [path.index(port) for port in ["Piraeus", "Tangier Med", "Algeciras"] if port in path_set]
            canal_indexes = [path.index(port) for port in ["Suez", "Port Said"] if port in path_set]
            if med_indexes and canal_indexes and max(med_indexes) > max(canal_indexes):
                penalty += 2.4
                penalties.append("Mediterranean hubs must come before Suez/Port Said when returning from Europe to Asia.")
    if regions.intersection(asia_regions) and regions.intersection({"North America", "South America"}):
        if not path_set.intersection({"Yokohama", "Busan", "Honolulu", "Vancouver", "Los Angeles", "Panama"}):
            penalty += 2.2
            penalties.append("Trans-Pacific/Americas routing needs Pacific or Panama waypoints.")
    return penalty, penalties


def global_route_risk_score(path: list[str], direct_distance: float) -> dict:
    distance = route_distance_nm(path)
    exposures = route_zone_exposure(path)
    plausibility_penalty, plausibility_notes = maritime_plausibility_penalty(path)
    detour_ratio = distance / max(direct_distance, 1)
    zone_pressure = 0.0
    if exposures:
        zone_pressure = (exposures[0]["impact"] * 0.46) + (sum(item["impact"] for item in exposures[1:4]) * 0.12)
    distance_pressure = min(1.45, distance / 6800)
    detour_pressure = max(0, detour_ratio - 1.0) * 0.7
    hub_complexity = max(0, len(path) - 2) * 0.28
    monitored_hub_bonus = 0.35 if any(hub in path for hub in ["Rotterdam", "Singapore", "Yokohama", "Busan", "Vancouver", "New York"]) else 0
    score = 2.0 + zone_pressure + distance_pressure + detour_pressure + hub_complexity + plausibility_penalty - monitored_hub_bonus
    score = round(max(1.0, min(10.0, score)), 2)
    return {
        "risk_score": score,
        "risk_band": risk_band(score),
        "distance_nm": distance,
        "detour_ratio": round(detour_ratio, 2),
        "zone_exposures": exposures[:5],
        "plausibility_notes": plausibility_notes,
    }


def corridor_global_paths(origin: str, destination: str) -> list[list[str]]:
    origin_region = global_port_region(origin)
    destination_region = global_port_region(destination)
    regions = {origin_region, destination_region}
    paths = []

    asia_regions = {"South Asia", "Southeast Asia", "East Asia"}
    if "Europe" in regions and regions.intersection(asia_regions | {"Middle East"}):
        asia_port = origin if origin_region in asia_regions | {"Middle East"} else destination
        europe_port = destination if destination_region == "Europe" else origin
        asia_prefix = []
        if global_port_region(asia_port) == "East Asia":
            asia_prefix = ["Singapore", "Colombo"]
        elif global_port_region(asia_port) == "Southeast Asia":
            asia_prefix = ["Colombo"]
        elif global_port_region(asia_port) == "South Asia" and asia_port != "Colombo":
            asia_prefix = ["Colombo"]
        elif global_port_region(asia_port) == "Middle East":
            asia_prefix = ["Jeddah"]
        suez_path = [asia_port, *asia_prefix, "Jeddah", "Suez", "Port Said", "Piraeus", europe_port]
        cape_path = [asia_port, *([asia_prefix[0]] if asia_prefix else []), "Cape Town", "Tangier Med", europe_port]
        if origin == europe_port:
            suez_path = list(reversed(suez_path))
            cape_path = list(reversed(cape_path))
        paths.extend([suez_path, cape_path])

    if regions.intersection(asia_regions) and regions.intersection({"North America", "South America"}):
        asia_port = origin if origin_region in asia_regions else destination
        americas_port = destination if destination_region in {"North America", "South America"} else origin
        pacific_path = [asia_port, "Yokohama", "Honolulu", americas_port]
        if americas_port in {"New York", "Norfolk", "Savannah", "Houston", "Santos", "Buenos Aires"}:
            pacific_path = [asia_port, "Yokohama", "Honolulu", "Panama", americas_port]
        if origin == americas_port:
            pacific_path = list(reversed(pacific_path))
        paths.append(pacific_path)

    if regions == {"Europe", "North America"}:
        north_america_port = origin if origin_region == "North America" else destination
        europe_port = destination if destination_region == "Europe" else origin
        atlantic_path = [europe_port, "New York", north_america_port] if north_america_port != "New York" else [europe_port, "New York"]
        if north_america_port in {"Los Angeles", "Long Beach", "Oakland", "Seattle", "Vancouver"}:
            atlantic_path = [europe_port, "New York", "Panama", north_america_port]
        if origin == north_america_port:
            atlantic_path = list(reversed(atlantic_path))
        paths.append(atlantic_path)

    clean_paths = []
    for path in paths:
        cleaned = []
        for port in path:
            if port not in GLOBAL_PORTS:
                continue
            if cleaned and cleaned[-1] == port:
                continue
            cleaned.append(port)
        if len(cleaned) >= 2 and cleaned[0] == origin and cleaned[-1] == destination:
            clean_paths.append(cleaned)
    return clean_paths


def candidate_global_paths(origin: str, destination: str) -> list[list[str]]:
    direct_distance = geo_distance_nm(*GLOBAL_PORTS[origin], *GLOBAL_PORTS[destination])
    corridors = corridor_global_paths(origin, destination)
    candidates = [*corridors, [origin, destination]]
    if corridors:
        unique_paths = []
        seen = set()
        for path in candidates:
            key = tuple(path)
            if key in seen:
                continue
            seen.add(key)
            unique_paths.append(path)
        return unique_paths

    usable_hubs = [hub for hub in GLOBAL_ROUTE_HUBS if hub not in {origin, destination} and hub in GLOBAL_PORTS]

    for hub in usable_hubs:
        path = [origin, hub, destination]
        if route_distance_nm(path) <= direct_distance * 1.95:
            candidates.append(path)

    for first_hub in usable_hubs:
        for second_hub in usable_hubs:
            if first_hub == second_hub:
                continue
            path = [origin, first_hub, second_hub, destination]
            distance = route_distance_nm(path)
            if distance <= direct_distance * 2.05:
                candidates.append(path)

    unique_paths = []
    seen = set()
    for path in candidates:
        key = tuple(path)
        if key in seen:
            continue
        seen.add(key)
        unique_paths.append(path)
    return unique_paths


def plan_global_route(origin: str, destination: str) -> dict:
    origin_port = canonical_global_port(origin)
    destination_port = canonical_global_port(destination)
    if not origin_port or not destination_port:
        missing = origin if not origin_port else destination
        raise HTTPException(status_code=404, detail=f"Unknown global port: {missing}")
    if origin_port == destination_port:
        raise HTTPException(status_code=400, detail="Origin and destination must be different")

    alternatives = []
    candidates = candidate_global_paths(origin_port, destination_port)
    corridor_candidates = corridor_global_paths(origin_port, destination_port)
    baseline_distance = min(
        [route_distance_nm(path) for path in corridor_candidates] or
        [geo_distance_nm(*GLOBAL_PORTS[origin_port], *GLOBAL_PORTS[destination_port])]
    )
    for path in candidates:
        scoring = global_route_risk_score(path, baseline_distance)
        top_zone_names = [item["zone"] for item in scoring["zone_exposures"][:2]]
        plausibility_notes = scoring.get("plausibility_notes", [])
        alternatives.append({
            "name": "Direct route" if len(path) == 2 else "Via " + " / ".join(path[1:-1]),
            "ports": path,
            "route": " -> ".join(path),
            "risk_score": scoring["risk_score"],
            "risk_band": scoring["risk_band"],
            "distance_nm": scoring["distance_nm"],
            "detour_ratio": scoring["detour_ratio"],
            "zone_exposures": scoring["zone_exposures"],
            "why": (
                f"Maritime realism warning: {plausibility_notes[0]}" if plausibility_notes else
                "Avoids major high-risk zones." if not top_zone_names else
                f"Primary exposure: {', '.join(top_zone_names)}."
            ),
            "plausibility_notes": plausibility_notes,
            "geometry": [[GLOBAL_PORTS[port][1], GLOBAL_PORTS[port][0]] for port in path],
            "recommended": False,
        })
    alternatives = sorted(alternatives, key=lambda item: (item["risk_score"], item["detour_ratio"], item["distance_nm"]))[:8]
    if alternatives:
        alternatives[0]["recommended"] = True
    direct = next((item for item in alternatives if item["name"] == "Direct route"), None)
    recommended = alternatives[0] if alternatives else None
    return {
        "origin": origin_port,
        "destination": destination_port,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model_note": "Heuristic maritime route intelligence using global ports, distance, chokepoint exposure, and onboard risk zones. Connect live maritime advisories for production-grade current intelligence.",
        "recommended": recommended,
        "direct": direct,
        "alternatives": alternatives,
        "global_context": {
            "lower_risk_corridors": LOWER_RISK_GLOBAL_CORRIDORS,
            "highest_watch_zones": sorted(GLOBAL_RISK_ZONES, key=lambda item: item["risk"], reverse=True)[:5],
        },
    }


@app.get("/copilot/global-route")
def get_global_route_plan(origin: str, destination: str):
    return plan_global_route(origin, destination)


def global_route_answer(question: str) -> dict | None:
    ports = extract_global_ports_from_question(question)
    if len(ports) < 2:
        return None
    return plan_global_route(ports[0], ports[1])


def global_corridor_answer_lines() -> list[str]:
    lines = [
        "Global safe-routing mode is active. Ask with two ports, for example: 'safest route from Mumbai to Rotterdam'.",
        "Lower-risk global corridors I currently prefer:",
    ]
    for corridor in LOWER_RISK_GLOBAL_CORRIDORS:
        lines.append(f"- {corridor['corridor']} ({corridor['example']}): {corridor['why']}")
    lines.append("High-watch zones to treat carefully: Gulf of Aden/Bab el-Mandeb, Red Sea/Suez approach, Black Sea, Strait of Hormuz, Gulf of Guinea.")
    return lines


PROBLEM_SOLVER_TOPICS = {
    "route_safety": {
        "label": "Route safety",
        "keywords": ["route", "safe", "safest", "reroute", "corridor", "voyage", "port"],
        "page": "AI Risk Decisions",
    },
    "vessel_eta": {
        "label": "Vessel ETA / delay",
        "keywords": ["vessel", "ship", "eta", "delay", "late", "speed", "stopped"],
        "page": "ETA Predictions",
    },
    "cargo_exposure": {
        "label": "Cargo exposure",
        "keywords": ["cargo", "gold", "petrol", "lng", "medical", "priority", "manifest"],
        "page": "Operations",
    },
    "threat_alerts": {
        "label": "Threat alerts",
        "keywords": ["threat", "pirate", "storm", "alert", "attack", "weather", "geopolitical"],
        "page": "Threat Alerts",
    },
    "risk_forecast": {
        "label": "Risk forecast",
        "keywords": ["forecast", "future", "tomorrow", "days", "trend", "watch"],
        "page": "Risk Forecast",
    },
    "ais_data": {
        "label": "AIS / live data",
        "keywords": ["ais", "api", "key", "signal", "live", "stale", "stream", "websocket"],
        "page": "Settings / AIS",
    },
    "notifications": {
        "label": "Notifications",
        "keywords": ["notification", "bell", "p1", "p2", "queue", "pressure"],
        "page": "Notifications",
    },
    "settings_access": {
        "label": "Settings / access",
        "keywords": ["login", "admin", "role", "settings", "permission", "access", "fingerprint"],
        "page": "Settings",
    },
    "fleet_operations": {
        "label": "Fleet operations",
        "keywords": ["fleet", "operation", "queue", "workflow", "dispatch", "berth", "readiness", "handoff"],
        "page": "Fleet & Operations",
    },
    "reports_quality": {
        "label": "Reports / data quality",
        "keywords": ["report", "brief", "quality", "audit", "export", "data", "missing", "deployment", "readiness"],
        "page": "Reports",
    },
}


def classify_problem_topic(problem: str, requested_topic: str = "Auto") -> str | None:
    requested = str(requested_topic or "Auto").strip().lower().replace(" ", "_").replace("/", "_")
    if requested and requested != "auto":
        for key, meta in PROBLEM_SOLVER_TOPICS.items():
            if requested == key or requested == meta["label"].lower().replace(" ", "_").replace("/", "_"):
                return key
    lowered = problem.lower()
    scores = []
    for key, meta in PROBLEM_SOLVER_TOPICS.items():
        score = sum(1 for keyword in meta["keywords"] if keyword in lowered)
        if score:
            scores.append((score, key))
    if not scores:
        return None
    return sorted(scores, reverse=True)[0][1]


def off_topic_problem_response(problem: str, role: str) -> dict:
    return {
        "status": "off_topic",
        "topic": "Unsupported",
        "role": role,
        "severity": "none",
        "confidence": 0,
        "answer": "This AI is restricted to maritime trade intelligence problems only.",
        "diagnosis": [
            "Ask about route safety, AIS live data, cargo exposure, vessel delays, threat alerts, risk forecast, notifications, settings, or access roles.",
        ],
        "evidence": [],
        "action_plan": [
            "Rephrase the problem using a supported maritime operations topic.",
        ],
        "open_page": "Command Copilot",
        "allowed_topics": [meta["label"] for meta in PROBLEM_SOLVER_TOPICS.values()],
        "original_problem": problem,
        "explainability": {
            "inputs": ["problem text", "allowed topic list"],
            "method": "The request had no matching maritime operations topic, so the assistant refused instead of hallucinating.",
            "limits": ["Ask about supported maritime trade-intelligence topics to unlock live evidence."],
        },
    }


def solve_domain_problem(payload: ProblemSolverRequest, db: Session) -> dict:
    problem = payload.problem.strip()
    topic_key = classify_problem_topic(problem, payload.topic)
    if not topic_key:
        return off_topic_problem_response(problem, payload.role)

    meta = PROBLEM_SOLVER_TOPICS[topic_key]
    brief = get_executive_brief(db)
    assessments = get_ai_route_assessments(db)
    predictions = get_vessel_predictions(limit=10, db=db)["predictions"]
    notifications = get_notification_intelligence(limit=120, db=db)
    operations = get_operations_intelligence_v2(db)
    quality = get_data_quality(db)
    ais_status = get_aisstream_status()
    diagnosis = []
    evidence = []
    action_plan = []
    severity = "watch"
    confidence = 72

    if topic_key == "route_safety":
        ports = extract_global_ports_from_question(problem)
        global_plan = plan_global_route(ports[0], ports[1]) if len(ports) >= 2 else None
        top_route = assessments[0] if assessments else {}
        if global_plan and global_plan.get("recommended"):
            recommended = global_plan["recommended"]
            diagnosis.append(f"Recommended safest global route is {recommended.get('route')}.")
            evidence.append(f"Global route risk {recommended.get('risk_score')}/10, distance {recommended.get('distance_nm')} nm.")
            action_plan.append("Use the recommended route unless schedule or cost constraints override it.")
            action_plan.append("Review watch zones before release and compare alternatives.")
            severity = "critical" if recommended.get("risk_score", 0) >= 7 else "watch"
            confidence = 88
        elif top_route:
            diagnosis.append(f"Highest current route concern is {top_route['route']} at {top_route['score']}/10.")
            evidence.append(top_route.get("explanation", "No explanation returned."))
            action_plan.extend(top_route.get("human_checklist", []))
            action_plan.append(top_route.get("action", "Review route before departure."))
            severity = "critical" if top_route.get("score", 0) >= 7 else "watch"
            confidence = top_route.get("confidence", 75)

    elif topic_key == "vessel_eta":
        top_vessels = predictions[:3]
        diagnosis.append("Delay risk is concentrated in the highest ETA-risk vessels.")
        for vessel in top_vessels:
            evidence.append(f"{vessel['vessel']} near {vessel['nearest_port']}: delay risk {vessel['delay_risk']}/10, ETA {vessel['eta_hours']}h.")
        action_plan.extend([
            "Prioritize vessels with delay risk above 7.",
            "Check stopped or slow AIS notifications before changing ETA commitments.",
            "Use Fleet & Operations > ETA Predictions for full ranking.",
        ])
        severity = "critical" if top_vessels and top_vessels[0].get("delay_risk", 0) >= 7 else "watch"
        confidence = 82

    elif topic_key == "cargo_exposure":
        cargo_counts = operations.get("cargo_priority_counts", {})
        p1 = int(cargo_counts.get("P1", 0) or 0)
        diagnosis.append(f"Cargo exposure currently has {p1} P1 manifest(s).")
        for cargo in operations.get("top_cargo", [])[:4]:
            evidence.append(f"{cargo['vessel_name']} carries {cargo['cargo']} toward {cargo['destination_port']} ({cargo['priority']}).")
        action_plan.extend([
            "Escalate P1 cargo before route release.",
            "Confirm destination port and vessel AIS signal for exposed manifests.",
            "Update cargo priority if manifest data is stale.",
        ])
        severity = "critical" if p1 else "watch"
        confidence = 78

    elif topic_key == "threat_alerts":
        pressure = notifications.get("pressure_score", 0)
        diagnosis.append(f"Notification pressure is {pressure}/100 ({notifications.get('pressure_band')}).")
        for item in notifications.get("top_actions", [])[:4]:
            evidence.append(f"{item['priority']} {item['target']}: {item['why']}")
            action_plan.append(item["action"])
        if not action_plan:
            action_plan.append("Keep monitoring threat alerts; no grouped escalation is currently dominant.")
        severity = "critical" if pressure >= 70 else "watch"
        confidence = 84

    elif topic_key == "risk_forecast":
        forecast = get_risk_forecast(days=14, db=db)
        top_forecast = forecast.get("top_forecast", [])
        diagnosis.append("Forecast watch windows are based on route risk drift and route-level AI assessments.")
        for item in top_forecast[:4]:
            evidence.append(f"{item['route']} on {item['date']}: {item['forecast_score']}/10 ({item['band']}).")
        action_plan.extend([
            "Watch any route forecast above 7 before departure release.",
            "Run Scenario Lab for the highest forecast route.",
            "Generate a risk brief if the watch window crosses P1 threshold.",
        ])
        severity = "critical" if top_forecast and top_forecast[0].get("forecast_score", 0) >= 7 else "watch"
        confidence = 76

    elif topic_key == "ais_data":
        diagnosis.append("AISStream API key is connected." if ais_status.get("connected") else "AISStream is not fully connected.")
        evidence.append(f"Enabled={ais_status.get('enabled')}, running={ais_status.get('running')}, connected={ais_status.get('connected')}, vessels={ais_status.get('vessel_count')}.")
        if ais_status.get("last_error"):
            evidence.append(f"Last error: {ais_status.get('last_error')}")
        action_plan.extend([
            "Open Settings > AIS to inspect connection state.",
            "Open Notifications and filter source to AISStream API for live feed alerts.",
            "If disconnected, check AIS_PROVIDER, AISSTREAM_API_KEY, bounding boxes, and network access.",
        ])
        severity = "critical" if ais_status.get("enabled") and not ais_status.get("connected") else "normal"
        confidence = 90

    elif topic_key == "notifications":
        diagnosis.append(f"Notification pressure is {notifications.get('pressure_band')} at {notifications.get('pressure_score')}/100.")
        for item in notifications.get("top_actions", [])[:5]:
            evidence.append(f"{item['priority']} {item['target']}: {item['why']}")
        action_plan.extend([
            "Filter Notifications by Critical first.",
            "Resolve repeated grouped targets before scanning lower-priority items.",
            "Use AIS API metric to confirm live-feed notification volume.",
        ])
        severity = "critical" if notifications.get("pressure_score", 0) >= 70 else "watch"
        confidence = 86

    elif topic_key == "settings_access":
        diagnosis.append(f"Current role request is being evaluated for {payload.role}.")
        evidence.append(f"Data quality {quality['score']}%, backend readiness {brief.get('readiness_score')}%.")
        action_plan.extend([
            "Use Admin only for runtime settings, approvals, and access-sensitive changes.",
            "Use Operator for vessel, cargo, risks, scenarios, reports, and alert workflows.",
            "Use Public or Guest for read-only presentation.",
        ])
        severity = "normal"
        confidence = 80

    elif topic_key == "fleet_operations":
        summary = operations.get("summary", {})
        readiness = operations.get("readiness_score", brief.get("readiness_score", 0))
        diagnosis.append(f"Fleet operations readiness is {readiness}% ({operations.get('readiness_band', 'Unknown')}).")
        evidence.append(
            f"{summary.get('open_actions', 0)} open action(s), "
            f"{summary.get('p1_actions', 0)} P1 action(s), "
            f"{summary.get('cargo_manifests', 0)} cargo manifest(s), "
            f"{summary.get('tracked_positions', 0)} tracked position rows."
        )
        for action in operations.get("top_actions", [])[:4]:
            evidence.append(f"{action['priority']} {action['subject']}: {action['recommendation']}")
            action_plan.append(action["recommendation"])
        action_plan.extend([
            "Open Fleet & Operations and handle P1 actions before lower-priority work.",
            "Confirm every high-value cargo row has a current AIS signal.",
            "Use ETA Predictions before committing customer-facing arrival promises.",
        ])
        severity = "critical" if float(readiness or 0) < 65 else "watch" if float(readiness or 0) < 80 else "normal"
        confidence = 83

    elif topic_key == "reports_quality":
        deployment = get_deployment_readiness(db)
        checks = deployment.get("checks", [])
        failed_checks = [check for check in checks if str(check.get("status", "")).lower() in {"fail", "warn"}]
        diagnosis.append(f"Data quality is {quality.get('score')}% with status {quality.get('status')}.")
        evidence.append(f"Deployment readiness {deployment.get('score')}%, report engine status {deployment.get('status')}.")
        for check in failed_checks[:5]:
            evidence.append(f"{check.get('name')}: {check.get('status')} - {check.get('detail')}")
        action_plan.extend([
            "Generate an executive brief only after critical quality warnings are reviewed.",
            "Use Reports for exportable summaries and Audit Trail for proof of decisions.",
            "If a chart looks empty, check Data Quality before treating it as a true zero-risk signal.",
        ])
        severity = "critical" if quality.get("status") == "fail" else "watch" if quality.get("status") == "warn" else "normal"
        confidence = 81

    if not diagnosis:
        diagnosis.append(brief.get("commander_summary", "No commander summary available."))
    if not evidence:
        evidence.append(f"Readiness {brief.get('readiness_score')}%, data quality {quality.get('score')}%.")
    if not action_plan:
        action_plan.append("Keep monitoring; no immediate corrective action was generated.")

    return {
        "status": "answered",
        "topic": meta["label"],
        "topic_key": topic_key,
        "role": payload.role,
        "severity": severity,
        "confidence": round(float(confidence), 1),
        "answer": diagnosis[0],
        "diagnosis": diagnosis,
        "evidence": evidence[:8],
        "action_plan": list(dict.fromkeys(action_plan))[:8],
        "open_page": meta["page"],
        "allowed_topics": [item["label"] for item in PROBLEM_SOLVER_TOPICS.values()],
        "original_problem": problem,
        "explainability": {
            "inputs": [
                "executive brief",
                "route assessments",
                "vessel predictions",
                "notification intelligence",
                "operations intelligence",
                "AISStream status",
                "data quality",
            ],
            "method": f"Classified the problem as {meta['label']} and selected the highest-confidence evidence available for that topic.",
            "limits": [
                "External weather, piracy, and port APIs are not live unless connected separately.",
                "AIS evidence is limited to configured live-feed bounding boxes and cached history.",
            ],
        },
    }


@app.post("/copilot/problem-solver")
def problem_solver(payload: ProblemSolverRequest, db: Session = Depends(get_db)):
    return solve_domain_problem(payload, db)


@app.post("/copilot/ask")
def ask_copilot(payload: CopilotRequest, db: Session = Depends(get_db)):
    question = payload.question.strip()
    lowered = question.lower()
    brief = get_executive_brief(db)
    predictions = get_vessel_predictions(limit=10, db=db)["predictions"]
    quality = get_data_quality(db)
    routes = brief.get("top_routes", [])
    actions = brief.get("top_actions", [])
    inbox = build_operations_inbox(db, limit=10)
    reliability = get_system_reliability(db) if any(word in lowered for word in ["health", "reliability", "system", "backend", "api", "smooth"]) else None
    answer_lines = [f"Copilot answer for {payload.role}: {question}"]

    global_plan = global_route_answer(question) if any(word in lowered for word in ["safe", "safest", "route", "world", "global", "from", "to"]) else None
    if any(phrase in lowered for phrase in ["fix first", "what should i fix", "priority", "top issue", "smart inbox", "urgent", "do first"]):
        summary = inbox.get("summary", {})
        answer_lines.append(
            f"Smart Operations Inbox is {summary.get('band')} with {summary.get('p1', 0)} P1 and {summary.get('p2', 0)} P2 item(s)."
        )
        for item in inbox.get("items", [])[:5]:
            answer_lines.append(
                f"- {item['priority']} {item['title']} -> {item['target']}: {item['recommendation']} ({item['why']})"
            )
        answer_lines.append("Open Command Center > Smart Inbox and work the cards from top to bottom.")
    elif reliability:
        answer_lines.append(f"System reliability is {reliability.get('score')}/100 ({reliability.get('band')}).")
        for check in reliability.get("checks", []):
            answer_lines.append(f"- {check['name']}: {check['status']} - {check['detail']}")
        answer_lines.append("Use Settings > Deployment for production warnings and Settings > Data for maintenance warnings.")
    elif any(phrase in lowered for phrase in ["why is", "why alert", "critical alert", "critical notification", "alert critical"]):
        intel = get_notification_intelligence(limit=120, db=db)
        critical_groups = [group for group in intel.get("groups", []) if group.get("priority") == "P1"]
        if critical_groups:
            answer_lines.append("Critical alerts are ranked P1 because they combine severe source signals with operational targets:")
            for group in critical_groups[:4]:
                answer_lines.append(f"- {group['target']}: {group['latest_title']} from {group['source']} ({group['count']} signal(s)). {group['latest_message']}")
        else:
            answer_lines.append("No P1 notification cluster is active right now. The current notification pressure is below critical.")
    elif global_plan:
        recommended = global_plan.get("recommended", {})
        answer_lines.append(f"Recommended safest global route: {recommended.get('route')}")
        answer_lines.append(
            f"Risk {recommended.get('risk_score')}/10 ({recommended.get('risk_band')}), "
            f"distance {recommended.get('distance_nm')} nm, detour ratio {recommended.get('detour_ratio')}."
        )
        answer_lines.append(f"Why: {recommended.get('why')}")
        exposures = recommended.get("zone_exposures", [])
        if exposures:
            answer_lines.append("Main watch zones on the recommended path:")
            for exposure in exposures[:3]:
                answer_lines.append(f"- {exposure['zone']} ({exposure['type']}): {exposure['note']}")
        answer_lines.append("Best alternatives:")
        for item in global_plan.get("alternatives", [])[:3]:
            answer_lines.append(f"- {item['route']}: {item['risk_score']}/10, {item['distance_nm']} nm.")
        answer_lines.append(global_plan.get("model_note", ""))
    elif any(word in lowered for word in ["world", "global", "safest routes", "safe routes"]):
        answer_lines.extend(global_corridor_answer_lines())
    elif any(word in lowered for word in ["safe", "safest", "route"]):
        safest = sorted(get_ai_route_assessments(db), key=lambda item: item["score"])[:3]
        answer_lines.append("Safest current routes:")
        for item in safest:
            answer_lines.append(f"- {item['route']}: {item['score']}/10 ({item['band']}); {item['decision']}.")
    elif any(word in lowered for word in ["ship", "vessel", "exposed", "delay", "eta"]):
        answer_lines.append("Most exposed vessels by delay/ETA risk:")
        for vessel in predictions[:3]:
            answer_lines.append(
                f"- {vessel['vessel']} near {vessel['nearest_port']}: delay risk {vessel['delay_risk']}/10, ETA {vessel['eta_hours']}h, action: {vessel['recommended_action']}."
            )
    elif any(word in lowered for word in ["quality", "data", "broken", "stale"]):
        answer_lines.append(f"Data quality is {quality['status']} at {quality['score']}%.")
        for check in quality["checks"][:4]:
            answer_lines.append(f"- {check['name']}: {check['status']} - {check['detail']}")
    elif any(word in lowered for word in ["action", "what should", "next", "do"]):
        answer_lines.append("Recommended next actions:")
        if actions:
            for action in actions:
                answer_lines.append(f"- {action['priority']} {action['subject']}: {action['recommendation']}")
        elif routes:
            answer_lines.append(f"- Review {routes[0]['route']}: {routes[0]['action']}")
        else:
            answer_lines.append("- Keep monitoring; no queued action is currently higher than the baseline.")
    else:
        answer_lines.append(brief["commander_summary"])
        if routes:
            answer_lines.append(f"Highest-risk route: {routes[0]['route']} at {routes[0]['score']}/10.")
        if predictions:
            answer_lines.append(f"Most exposed vessel: {predictions[0]['vessel']} with delay risk {predictions[0]['delay_risk']}/10.")

    return {
        "answer": "\n".join(answer_lines),
        "evidence": {
            "readiness": brief.get("readiness_score"),
            "data_quality": quality.get("score"),
            "top_routes": routes[:3],
            "top_vessels": predictions[:3],
            "global_route": global_plan,
            "smart_inbox": inbox.get("summary"),
            "system_reliability": reliability,
        },
    }


def smart_report_content(brief_type: str, db: Session) -> str:
    brief = get_executive_brief(db)
    quality = get_data_quality(db)
    deployment = get_deployment_readiness(db)
    inbox = build_operations_inbox(db, limit=8)
    reliability = get_system_reliability(db)
    lines = [
        f"Global AI Trade Intelligence - {brief_type}",
        f"Generated: {datetime.datetime.now(datetime.timezone.utc).isoformat()}",
        "",
        "Executive signal",
        brief["commander_summary"],
        "",
        "Top routes",
    ]
    for route in brief.get("top_routes", []):
        lines.append(f"- {route['route']}: {route['score']}/10 ({route['band']}) - {route['action']}")
    lines.extend(["", "Top vessels"])
    for vessel in brief.get("top_vessels", []):
        lines.append(f"- {vessel['vessel']}: delay risk {vessel['delay_risk']}/10, ETA {vessel['eta_hours']}h, cargo {vessel['cargo']}")
    lines.extend(["", "Open AI actions"])
    for action in brief.get("top_actions", []):
        lines.append(f"- {action['priority']} {action['subject']}: {action['recommendation']}")
    lines.extend(["", "Smart Operations Inbox"])
    inbox_summary = inbox.get("summary", {})
    lines.append(f"- Inbox health: {inbox_summary.get('score')}% ({inbox_summary.get('band')}) with {inbox_summary.get('p1')} P1 and {inbox_summary.get('p2')} P2 item(s).")
    for item in inbox.get("items", [])[:5]:
        lines.append(f"- {item['priority']} {item['title']} -> {item['target']}: {item['recommendation']}")
    lines.extend([
        "",
        "Quality and deployment",
        f"- Data quality: {quality['score']}% ({quality['status']})",
        f"- Deployment readiness: {deployment['score']}% ({deployment['status']})",
        f"- System reliability: {reliability['score']}% ({reliability['band']})",
        "",
        "Recommendations",
        "- Work Smart Operations Inbox P1/P2 cards before switching pages.",
        "- Re-run Scenario Lab for the highest-risk route before departure.",
        "- Keep data quality above 90% before executive reporting.",
    ])
    return "\n".join(lines)


@app.get("/reports/smart")
def generate_smart_report(
    brief_type: str = "CEO brief",
    db: Session = Depends(get_db),
    request: Request = None,
):
    content = smart_report_content(brief_type, db)
    pdf_path = safe_generate_pdf_report(content)
    report = GeneratedReport(content=content, timestamp=datetime.datetime.now(datetime.timezone.utc))
    db.add(report)
    record_audit_event(
        db,
        action="smart_report_generated",
        resource=brief_type,
        detail=f"Smart report generated: {brief_type}.",
        severity="info",
        request=request,
    )
    db.commit()
    db.refresh(report)
    return {
        "report_id": report.id,
        "brief_type": brief_type,
        "pdf_path": pdf_path,
        "content": content,
    }


@app.get("/reports/intelligence")
def get_report_intelligence(db: Session = Depends(get_db)):
    reports = db.query(GeneratedReport).order_by(GeneratedReport.timestamp.desc()).limit(5).all()
    latest = reports[0] if reports else None
    previous = reports[1] if len(reports) > 1 else None
    latest_lines = set((latest.content or "").splitlines()) if latest else set()
    previous_lines = set((previous.content or "").splitlines()) if previous else set()
    new_lines = [line for line in latest_lines - previous_lines if line.strip()][:12]
    removed_lines = [line for line in previous_lines - latest_lines if line.strip()][:12]
    mission = build_mission_control(db)
    quality = get_data_quality(db)
    digest = notification_digest(db=db)
    readiness = get_deployment_readiness(db)
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "reports_available": len(reports),
        "latest_report_id": latest.id if latest else None,
        "previous_report_id": previous.id if previous else None,
        "what_changed": new_lines,
        "removed_or_resolved": removed_lines,
        "report_health": {
            "mission_score": mission.get("mission_score"),
            "data_quality": quality.get("score"),
            "notification_pressure": digest.get("pressure_score"),
            "deployment_readiness": readiness.get("score"),
        },
        "recommendations": [
            "Generate a Mission Pack after major role, route, or incident changes.",
            "Use Smart Briefs for stakeholders and Daily Command Brief for operator handoff.",
            "If data quality falls below 90%, run Settings > Data checks before exporting.",
        ],
    }


def nautical_distance_between(port_a: str, port_b: str) -> float:
    a = PORT_COORDS.get(port_a)
    b = PORT_COORDS.get(port_b)
    if not a or not b:
        return 0.0
    lat_nm = (b[0] - a[0]) * 60
    lon_nm = (b[1] - a[1]) * 60 * max(0.25, math.cos(math.radians((a[0] + b[0]) / 2)))
    return round(math.sqrt((lat_nm ** 2) + (lon_nm ** 2)), 1)


def route_alert_modifier(route_name: str, alerts: list[ThreatAlert]) -> float:
    text = route_name.lower()
    modifier = 0.0
    for alert in alerts:
        location = str(alert.location or "").lower()
        title = str(alert.title or "").lower()
        if location and any(token in text for token in location.split()):
            modifier += {"high": 1.8, "medium": 1.0, "low": 0.4}.get(str(alert.severity).lower(), 0.2)
        elif any(keyword in title for keyword in ["piracy", "weather", "geopolitical", "congestion"]):
            modifier += {"high": 0.8, "medium": 0.45, "low": 0.2}.get(str(alert.severity).lower(), 0.1)
    return modifier


def geo_distance_nm(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    radius_nm = 3440.065
    lat1 = math.radians(lat_a)
    lat2 = math.radians(lat_b)
    delta_lat = math.radians(lat_b - lat_a)
    delta_lon = math.radians(lon_b - lon_a)
    h = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return radius_nm * (2 * math.atan2(math.sqrt(h), math.sqrt(max(0.0, 1 - h))))


def normalize_scenario_type(value: str) -> str:
    requested = str(value or "").strip().lower()
    for scenario_name in SCENARIO_PROFILES:
        if scenario_name.lower() == requested:
            return scenario_name
    aliases = {
        "storm": "Storm Surge",
        "weather": "Storm Surge",
        "piracy": "Piracy Swarm",
        "pirate": "Piracy Swarm",
        "hijack": "Hijack Attempt",
        "boarding": "Hijack Attempt",
        "war": "War Conflict",
        "conflict": "War Conflict",
        "geopolitical": "War Conflict",
        "country": "War Conflict",
        "port": "Port Shutdown",
        "shutdown": "Port Shutdown",
        "cyber": "Cyber Blackout",
        "fuel": "Fuel Shock",
        "cargo": "Cargo Theft Ring",
        "theft": "Cargo Theft Ring",
    }
    for token, scenario_name in aliases.items():
        if token in requested:
            return scenario_name
    return "Storm Surge"


def normalize_severity(value: str) -> str:
    severity = str(value or "high").strip().lower()
    return severity if severity in SCENARIO_SEVERITY else "high"


def scenario_location_coords(location: str):
    lowered = str(location or "").strip().lower()
    for name, coords in SCENARIO_LOCATIONS.items():
        if name.lower() == lowered:
            return coords
    for name, coords in SCENARIO_LOCATIONS.items():
        if lowered and (lowered in name.lower() or name.lower() in lowered):
            return coords
    return SCENARIO_LOCATIONS["Global Network"]


def route_geometry(route: TradeRoute) -> list[list[float]]:
    origin = PORT_COORDS.get(route.origin_port)
    destination = PORT_COORDS.get(route.destination_port)
    if not origin or not destination:
        return []
    return [[origin[1], origin[0]], [destination[1], destination[0]]]


def scenario_route_affinity(route: TradeRoute, location: str, coords: tuple[float, float], selected_route_id: int | None) -> float:
    if selected_route_id and route.id == selected_route_id:
        return 1.0

    route_ports = {route.origin_port, route.destination_port}
    location_key = str(location or "").strip().lower()
    strategic_ports = STRATEGIC_LOCATION_PORTS.get(location_key, set())
    if strategic_ports and route_ports.intersection(strategic_ports):
        return 0.86

    route_text = f"{route.origin_port} {route.destination_port}".lower()
    if location_key and any(token in route_text for token in location_key.split() if len(token) > 3):
        return 0.92

    distances = []
    for port in route_ports:
        if port in PORT_COORDS:
            port_lat, port_lon = PORT_COORDS[port]
            distances.append(geo_distance_nm(coords[0], coords[1], port_lat, port_lon))
    if not distances:
        return 0.25 if location_key == "global network" else 0.0
    nearest = min(distances)
    return round(max(0.0, min(1.0, 1 - (nearest / 2800))), 3)


def scenario_vessel_exposure(vessel: dict, location: str, coords: tuple[float, float], severity_multiplier: float) -> dict | None:
    lat = vessel_display_lat(vessel)
    lon = vessel_display_lon(vessel)
    distance = geo_distance_nm(coords[0], coords[1], lat, lon) if lat or lon else 9999.0
    nearest = nearest_port(lat, lon)
    location_key = str(location or "").lower()
    strategic_ports = STRATEGIC_LOCATION_PORTS.get(location_key, set())
    port_match = nearest in strategic_ports or nearest.lower() in location_key
    distance_exposure = max(0.0, 1 - (distance / 1800))
    cargo_priority = effective_vessel_cargo_priority(vessel)
    cargo_boost = {"P1": 2.2, "P2": 1.2, "P3": 0.4}.get(cargo_priority, 0.3)
    status_boost = 1.2 if vessel_status(vessel) != "active" else 0
    exposure = (distance_exposure * 7.0) + cargo_boost + status_boost
    if port_match:
        exposure += 2.0
    exposure = round(max(0.0, min(10.0, exposure * severity_multiplier / 1.25)), 2)
    if exposure < 3.5 and not port_match:
        return None
    recommendation = "Hold position and confirm safety window"
    if exposure >= 8:
        recommendation = "Escalate to command, reroute or shelter immediately"
    elif exposure >= 6:
        recommendation = "Move to controlled corridor and increase check-ins"
    elif cargo_priority == "P1":
        recommendation = "Protect priority cargo with manual release approval"
    return {
        "vessel": str(vessel.get("name") or vessel_identifier(vessel)),
        "status": str(vessel.get("status") or "unknown"),
        "nearest_port": nearest,
        "distance_nm": round(distance, 1) if distance < 9999 else None,
        "cargo": str(vessel.get("cargo") or "Unknown"),
        "cargo_class": str(vessel.get("cargo_class") or "Unknown"),
        "priority": cargo_priority,
        "exposure_score": exposure,
        "recommendation": recommendation,
        "position_lat": lat,
        "position_lon": lon,
        "api_position_lat": vessel.get("api_position_lat", vessel_lat(vessel)),
        "api_position_lon": vessel.get("api_position_lon", vessel_lon(vessel)),
        "display_position_lat": lat,
        "display_position_lon": lon,
        "motion_source": vessel.get("motion_source", "scenario live feed"),
        "motion_trail": vessel.get("motion_trail", [[vessel_lon(vessel), vessel_lat(vessel)], [lon, lat]]),
    }


def scenario_cargo_exposure(
    manifests: list[CargoManifest],
    impacted_routes: list[dict],
    location: str,
    severity_multiplier: float,
) -> list[dict]:
    impacted_route_text = " ".join(route["route"].lower() for route in impacted_routes[:5])
    location_key = str(location or "").lower()
    rows = []
    for manifest in manifests:
        corridor = f"{manifest.origin_port} {manifest.destination_port}".lower()
        location_match = any(token in corridor for token in location_key.split() if len(token) > 3)
        route_match = manifest.origin_port.lower() in impacted_route_text or manifest.destination_port.lower() in impacted_route_text
        priority_boost = {"P1": 4.0, "P2": 2.4, "P3": 1.0}.get(manifest.priority, 1.0)
        class_boost = 1.5 if str(manifest.cargo_class).lower() in {"critical", "high value", "energy"} else 0.5
        score = priority_boost + class_boost + (2.5 if location_match else 0) + (1.6 if route_match else 0)
        score = round(max(0.0, min(10.0, score * severity_multiplier / 1.2)), 2)
        if score < 4.0:
            continue
        rows.append({
            "vessel_name": manifest.vessel_name,
            "cargo": manifest.cargo,
            "cargo_class": manifest.cargo_class,
            "cargo_value": manifest.cargo_value,
            "origin_port": manifest.origin_port,
            "destination_port": manifest.destination_port,
            "priority": manifest.priority,
            "exposure_score": score,
            "control": "Manual release only" if score >= 7 else "Monitor handoff window",
        })
    return sorted(rows, key=lambda row: row["exposure_score"], reverse=True)[:12]


def scenario_response_plan(
    scenario_name: str,
    profile: dict,
    impacted_routes: list[dict],
    impacted_vessels: list[dict],
    cargo_rows: list[dict],
    duration_hours: int,
) -> list[dict]:
    route_count = len([route for route in impacted_routes if route["after_score"] >= 6])
    vessel_count = len(impacted_vessels)
    p1_cargo = len([row for row in cargo_rows if row.get("priority") == "P1"])
    plan = [
        {
            "priority": "P1" if impacted_routes and impacted_routes[0]["after_score"] >= 8 else "P2",
            "owner": "Command lead",
            "action": f"Activate {scenario_name} playbook for {duration_hours}h window.",
            "why": profile["mission"],
        },
        {
            "priority": "P1" if route_count else "P2",
            "owner": "Route desk",
            "action": f"Review {route_count or 'all'} exposed route releases and prepare alternate lanes.",
            "why": "Digital twin shows route risk rising under the simulated condition.",
        },
        {
            "priority": "P1" if vessel_count >= 3 else "P2",
            "owner": "Fleet controller",
            "action": f"Increase check-in cadence for {vessel_count} exposed vessels.",
            "why": "Vessel proximity and cargo priority create near-term operational exposure.",
        },
        {
            "priority": "P1" if p1_cargo else "P2",
            "owner": "Cargo security",
            "action": f"Lock release approvals for {p1_cargo} priority cargo records.",
            "why": "High-value or critical manifests should not move automatically during the scenario.",
        },
    ]
    if scenario_name == "Cyber Blackout":
        plan.append({
            "priority": "P1",
            "owner": "Cyber watch",
            "action": "Switch to manual AIS verification and require two-person approval for route release.",
            "why": "The scenario assumes signal integrity may be degraded.",
        })
    if scenario_name == "Hijack Attempt":
        plan.append({
            "priority": "P1",
            "owner": "Maritime security",
            "action": "Move the vessel to secure check-ins, divert away from boarding exposure, and notify legitimate maritime authorities.",
            "why": "The scenario assumes crew safety and defensive coordination are the first constraints.",
        })
    if scenario_name == "War Conflict":
        plan.append({
            "priority": "P1",
            "owner": "Command and compliance",
            "action": "Freeze conflict-zone releases until insurance, sanctions, and safest-route checks are confirmed.",
            "why": "The scenario assumes geopolitical escalation can close corridors or invalidate commercial permissions.",
        })
    if scenario_name == "Fuel Shock":
        plan.append({
            "priority": "P2",
            "owner": "Commercial desk",
            "action": "Rank alternatives by fuel exposure before committing long detours.",
            "why": "The safest route may not be commercially acceptable without cargo prioritization.",
        })
    return plan


def scenario_timeline(scenario_name: str, severity: str, duration_hours: int, max_after_risk: float) -> list[dict]:
    return [
        {
            "time": "T+0h",
            "phase": "Detect",
            "event": f"{severity.title()} {scenario_name} signal injected into digital twin.",
            "trigger": "Operator simulation",
        },
        {
            "time": "T+2h",
            "phase": "Contain",
            "event": "Freeze risky releases, increase vessel check-ins, and validate active cargo handoffs.",
            "trigger": "Initial risk surge",
        },
        {
            "time": "T+6h",
            "phase": "Adapt",
            "event": "Select alternate route package if exposed routes remain above High risk.",
            "trigger": f"Projected peak risk {max_after_risk:.1f}/10",
        },
        {
            "time": f"T+{duration_hours}h",
            "phase": "Recover",
            "event": "Return held routes to normal release after alerts, berth slots, and cargo security are verified.",
            "trigger": "Scenario window closes",
        },
    ]


@app.post("/scenario/simulate")
def simulate_scenario(payload: ScenarioRequest, db: Session = Depends(get_db)):
    scenario_name = normalize_scenario_type(payload.scenario_type)
    severity = normalize_severity(payload.severity)
    severity_multiplier = SCENARIO_SEVERITY[severity]
    duration_hours = max(1, min(int(payload.duration_hours or 1), 168))
    profile = SCENARIO_PROFILES[scenario_name]
    location = payload.location or "Global Network"
    coords = scenario_location_coords(location)
    virtual_alert = {
        "title": profile["alert_title"],
        "description": f"{severity.title()} {scenario_name} for {duration_hours}h near {location}.",
        "severity": "high" if severity in {"high", "extreme"} else severity,
        "location": location,
    }

    routes = unique_by(db.query(TradeRoute).order_by(TradeRoute.id).all(), lambda route: (route.origin_port, route.destination_port))
    live_alerts = unique_by(
        db.query(ThreatAlert).order_by(ThreatAlert.id.desc()).all(),
        lambda alert: (alert.title, alert.location, alert.severity),
    )
    vessels, vessel_source = get_operational_vessels(db)
    manifests = db.query(CargoManifest).order_by(CargoManifest.updated_at.desc()).limit(200).all()
    operations = get_operations_intelligence_v2(db)

    impacted_routes = []
    for route in routes:
        affinity = scenario_route_affinity(route, location, coords, payload.affected_route_id)
        systemic = 0.45 if scenario_name in {"Cyber Blackout", "Fuel Shock"} else 0.0
        route_modifier = round((profile["route_modifier"] * severity_multiplier * max(affinity, systemic)), 2)
        before = assess_route_risk(route, alerts=live_alerts)
        after = assess_route_risk(route, alerts=[*live_alerts, virtual_alert], live_modifier=route_modifier)
        delta = round(after["score"] - before["score"], 2)
        if delta < 0.35 and affinity < 0.25 and scenario_name not in {"Cyber Blackout", "Fuel Shock"}:
            continue
        impacted_routes.append({
            "route_id": route.id,
            "route": f"{route.origin_port} to {route.destination_port}",
            "before_score": before["score"],
            "before_band": before["band"],
            "after_score": after["score"],
            "after_band": after["band"],
            "risk_delta": delta,
            "decision": after["decision"],
            "action": after["action"],
            "affinity": round(max(affinity, systemic), 2),
            "geometry": route_geometry(route),
        })
    impacted_routes = sorted(impacted_routes, key=lambda row: (row["after_score"], row["risk_delta"]), reverse=True)

    impacted_vessels = [
        exposure for vessel in vessels
        if (exposure := scenario_vessel_exposure(vessel, location, coords, severity_multiplier))
    ]
    impacted_vessels = sorted(impacted_vessels, key=lambda row: row["exposure_score"], reverse=True)[:16]
    cargo_rows = scenario_cargo_exposure(manifests, impacted_routes, location, severity_multiplier)

    readiness_before = float(operations.get("readiness_score", 100) or 100)
    max_after_risk = max([row["after_score"] for row in impacted_routes] or [0])
    readiness_penalty = (
        profile["readiness_penalty"] * severity_multiplier
        + len([row for row in impacted_routes if row["after_score"] >= 7]) * 2.2
        + len([row for row in impacted_vessels if row["exposure_score"] >= 7]) * 1.8
        + len([row for row in cargo_rows if row["exposure_score"] >= 7]) * 1.2
    )
    readiness_after = round(max(0.0, readiness_before - readiness_penalty), 1)
    projected_delay = round(duration_hours * profile["delay_factor"] * severity_multiplier, 1)
    confidence = round(min(96.0, 62 + (len(impacted_routes) * 3.5) + (len(impacted_vessels) * 1.2) + (severity_multiplier * 6)), 1)

    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scenario": {
            "type": scenario_name,
            "category": profile["category"],
            "severity": severity,
            "location": location,
            "duration_hours": duration_hours,
            "mission": profile["mission"],
            "center": {"lat": coords[0], "lon": coords[1]},
        },
        "readiness": {
            "before": readiness_before,
            "after": readiness_after,
            "delta": round(readiness_after - readiness_before, 1),
            "band": "Ready" if readiness_after >= 80 else "Watch" if readiness_after >= 65 else "At Risk",
        },
        "impact_summary": {
            "routes_impacted": len(impacted_routes),
            "vessels_impacted": len(impacted_vessels),
            "cargo_records_exposed": len(cargo_rows),
            "max_projected_risk": round(max_after_risk, 2),
            "projected_delay_hours": projected_delay,
            "confidence": confidence,
            "vessel_source": vessel_source,
        },
        "impacted_routes": impacted_routes[:12],
        "impacted_vessels": impacted_vessels,
        "cargo_exposure": cargo_rows,
        "response_plan": scenario_response_plan(scenario_name, profile, impacted_routes, impacted_vessels, cargo_rows, duration_hours),
        "timeline": scenario_timeline(scenario_name, severity, duration_hours, max_after_risk),
        "map_layers": {
            "center": {"lat": coords[0], "lon": coords[1]},
            "blast_radius_nm": round(650 * severity_multiplier),
            "routes": impacted_routes[:8],
            "vessels": impacted_vessels,
        },
    }


@app.get("/routes/alternatives")
def get_route_alternatives(route_id: int, db: Session = Depends(get_db)):
    route = db.query(TradeRoute).filter(TradeRoute.id == route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    alerts = unique_by(
        db.query(ThreatAlert).order_by(ThreatAlert.id.desc()).all(),
        lambda alert: (alert.title, alert.location, alert.severity),
    )
    current_assessment = assess_route_risk(route, alerts=alerts)
    origin = route.origin_port
    destination = route.destination_port
    alternatives = [{
        "name": "Current route",
        "legs": [origin, destination],
        "distance_nm": route.distance,
        "risk_score": current_assessment["score"],
        "risk_band": current_assessment["band"],
        "delta_vs_current": 0,
        "why": current_assessment["explanation"],
        "geometry": [[PORT_COORDS[origin][1], PORT_COORDS[origin][0]], [PORT_COORDS[destination][1], PORT_COORDS[destination][0]]],
        "recommended": False,
    }]
    for hub in PORT_COORDS:
        if hub in {origin, destination}:
            continue
        leg_distance = nautical_distance_between(origin, hub) + nautical_distance_between(hub, destination)
        detour_ratio = leg_distance / max(float(route.distance or leg_distance or 1), 1)
        route_name = f"{origin} to {hub} to {destination}"
        alert_modifier = route_alert_modifier(route_name, alerts)
        hub_relief = 0.65 if hub not in {"Dubai", "Singapore"} else 0.25
        score = max(1, min(10, (float(route.risk_level or 0) * 0.72) + (detour_ratio * 1.1) + alert_modifier - hub_relief))
        alternatives.append({
            "name": f"Via {hub}",
            "legs": [origin, hub, destination],
            "distance_nm": round(leg_distance, 1),
            "risk_score": round(score, 2),
            "risk_band": risk_band(score),
            "delta_vs_current": round(score - float(current_assessment["score"]), 2),
            "why": f"Detour ratio {detour_ratio:.2f}, alert modifier {alert_modifier:.1f}, hub relief {hub_relief:.1f}.",
            "geometry": [
                [PORT_COORDS[origin][1], PORT_COORDS[origin][0]],
                [PORT_COORDS[hub][1], PORT_COORDS[hub][0]],
                [PORT_COORDS[destination][1], PORT_COORDS[destination][0]],
            ],
            "recommended": False,
        })
    alternatives = sorted(alternatives, key=lambda item: item["risk_score"])
    if alternatives:
        alternatives[0]["recommended"] = True
    return {
        "route_id": route.id,
        "route": f"{origin} to {destination}",
        "current_score": current_assessment["score"],
        "alternatives": alternatives,
    }


@app.get("/routes/optimizer")
def get_route_optimizer(route_id: int, db: Session = Depends(get_db)):
    packet = get_route_alternatives(route_id=route_id, db=db)
    alternatives = packet["alternatives"]
    if not alternatives:
        raise HTTPException(status_code=404, detail="No route options available")
    enriched = []
    for option in alternatives:
        risk = float(option.get("risk_score", 0) or 0)
        distance = float(option.get("distance_nm", 0) or 0)
        cost_index = round((distance / 100) * (1 + (risk * 0.045)), 2)
        delay_index = round((distance / 450) + (risk * 0.18), 2)
        safety_index = round(max(0, 100 - (risk * 9.2)), 1)
        balanced_score = round((safety_index * 0.5) - (delay_index * 4.5) - (cost_index * 0.45), 2)
        enriched.append({
            **option,
            "cost_index": cost_index,
            "delay_index": delay_index,
            "safety_index": safety_index,
            "balanced_score": balanced_score,
        })

    safest = min(enriched, key=lambda item: item["risk_score"])
    fastest = min(enriched, key=lambda item: item["distance_nm"])
    cheapest = min(enriched, key=lambda item: item["cost_index"])
    balanced = max(enriched, key=lambda item: item["balanced_score"])
    for option in enriched:
        option["recommended_for"] = [
            name for name, chosen in {
                "Safest": safest,
                "Fastest": fastest,
                "Lowest cost": cheapest,
                "Balanced": balanced,
            }.items()
            if chosen["name"] == option["name"]
        ]
    return {
        "route_id": packet["route_id"],
        "route": packet["route"],
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "modes": {
            "safest": safest,
            "fastest": fastest,
            "lowest_cost": cheapest,
            "balanced": balanced,
        },
        "options": enriched,
        "decision_note": "Use safest for critical cargo, fastest for low-risk schedules, lowest cost for routine cargo, and balanced for default operations.",
    }


def serialize_vessel(vessel: Vessel):
    if isinstance(vessel, dict):
        return vessel
    return {
        "id": vessel.id,
        "name": vessel.name,
        "position_lat": vessel.position_lat,
        "position_lon": vessel.position_lon,
        "status": vessel.status,
    }


def vessel_field(vessel, field: str, default=None):
    if isinstance(vessel, dict):
        return vessel.get(field, default)
    return getattr(vessel, field, default)


def vessel_status(vessel):
    return str(vessel_field(vessel, "status", "unknown")).lower()


def vessel_lat(vessel):
    return float(vessel_field(vessel, "position_lat", 0) or 0)


def vessel_lon(vessel):
    return float(vessel_field(vessel, "position_lon", 0) or 0)


def vessel_display_lat(vessel):
    return float(vessel_field(vessel, "display_position_lat", vessel_lat(vessel)) or 0)


def vessel_display_lon(vessel):
    return float(vessel_field(vessel, "display_position_lon", vessel_lon(vessel)) or 0)


def get_registered_vessels(db: Session):
    vessels = unique_by(db.query(Vessel).order_by(Vessel.id).all(), lambda vessel: vessel.name)
    return [serialize_vessel(vessel) for vessel in vessels]


def normalize_manifest_lookup_key(value) -> str:
    return str(value or "").strip().lower()


def manifest_is_inferred(manifest: CargoManifest) -> bool:
    status = str(manifest.status or "").strip().lower()
    if status in INFERRED_MANIFEST_STATUSES:
        return True
    cargo = str(manifest.cargo or "").strip().lower()
    identifier = str(manifest.vessel_identifier or "").strip()
    vessel_name = str(manifest.vessel_name or "").strip().lower()
    destination = str(manifest.destination_port or "").strip().lower()
    return bool(
        identifier.isdigit()
        and cargo in FALLBACK_CARGO_NAMES
        and (destination in {"live ais destination", "unknown"} or vessel_name.startswith("mmsi "))
    )


def manifest_is_verified(manifest: CargoManifest) -> bool:
    return not manifest_is_inferred(manifest)


def build_verified_manifest_lookup(db: Session) -> dict[str, CargoManifest]:
    manifests = db.query(CargoManifest).order_by(CargoManifest.updated_at.desc(), CargoManifest.id.desc()).limit(1000).all()
    lookup: dict[str, CargoManifest] = {}
    for manifest in manifests:
        if not manifest_is_verified(manifest):
            continue
        for raw_key in (manifest.vessel_identifier, manifest.vessel_name):
            key = normalize_manifest_lookup_key(raw_key)
            if key and key not in {"unknown", "none"} and key not in lookup:
                lookup[key] = manifest
    return lookup


def apply_manifest_context(vessel: dict, manifest: CargoManifest | None, source: str) -> dict:
    enriched = dict(vessel)
    if manifest:
        enriched.update({
            "cargo": manifest.cargo,
            "cargo_class": manifest.cargo_class,
            "cargo_tons": manifest.cargo_tons,
            "cargo_value": manifest.cargo_value,
            "origin_port": manifest.origin_port or enriched.get("origin_port"),
            "destination_port": manifest.destination_port or enriched.get("destination_port"),
            "priority": manifest.priority,
            "cargo_source": "Verified Manifest",
            "cargo_verified": True,
            "manifest_status": manifest.status,
            "manifest_updated_at": manifest.updated_at.isoformat() if manifest.updated_at else None,
        })
        return enriched
    enriched["cargo_source"] = enriched.get("cargo_source") or ("Inferred Demo Cargo" if source == "AISStream" else "Registry / Demo")
    enriched["cargo_verified"] = bool(enriched.get("cargo_verified", False))
    return enriched


def enrich_vessels_with_cargo_context(vessels: list[dict], db: Session, source: str) -> list[dict]:
    lookup = build_verified_manifest_lookup(db)
    enriched = []
    for vessel in vessels:
        keys = [
            normalize_manifest_lookup_key(vessel.get("mmsi")),
            normalize_manifest_lookup_key(vessel.get("id")),
            normalize_manifest_lookup_key(vessel.get("name")),
        ]
        manifest = next((lookup[key] for key in keys if key and key in lookup), None)
        enriched.append(apply_manifest_context(vessel, manifest, source))
    return enriched


def get_operational_vessels(db: Session):
    real_vessels = get_aisstream_vessels()
    if real_vessels:
        return enrich_vessels_with_cargo_context(real_vessels, db, "AISStream"), "AISStream"
    return enrich_vessels_with_cargo_context(get_registered_vessels(db), db, "Local fleet registry"), "Local fleet registry"


def serialize_route(route: TradeRoute):
    return {
        "id": route.id,
        "origin_port": route.origin_port,
        "destination_port": route.destination_port,
        "risk_level": route.risk_level,
        "distance": route.distance,
    }


def serialize_alert(alert: ThreatAlert):
    return {
        "id": alert.id,
        "title": alert.title,
        "description": alert.description,
        "severity": alert.severity,
        "location": alert.location,
    }


def route_decision(score: float):
    if score >= 8:
        return "Hold or reroute immediately"
    if score >= 7:
        return "Escalate before departure"
    if score >= 5:
        return "Proceed with controls"
    if score >= 4:
        return "Monitor closely"
    return "Proceed normally"


def route_action(route: TradeRoute, score: float):
    route_name = f"{route.origin_port} to {route.destination_port}"
    if score >= 8:
        return f"Pause {route_name}, review alternate routing, and notify port operations."
    if score >= 7:
        return f"Escalate {route_name}, confirm active alerts, and prepare a reroute option."
    if score >= 5:
        return f"Keep {route_name} active with delay buffer and closer vessel tracking."
    if score >= 4:
        return f"Monitor {route_name} for alert changes and port congestion."
    return f"Proceed on {route_name} with standard monitoring."


def risk_type_from_text(text: str):
    lowered = text.lower()
    if any(word in lowered for word in ["piracy", "suspicious", "theft"]):
        return "Security"
    if any(word in lowered for word in ["weather", "storm"]):
        return "Weather"
    if any(word in lowered for word in ["congestion", "queue", "delay", "strike"]):
        return "Port / Delay"
    if any(word in lowered for word in ["geopolitical", "sanction", "tension"]):
        return "Geopolitical"
    if any(word in lowered for word in ["mechanical", "engine", "breakdown"]):
        return "Mechanical"
    if "cyber" in lowered:
        return "Cyber"
    return "Operational"


def confidence_for_score(score: float, evidence_count: int):
    confidence = 58 + (score * 4) + (evidence_count * 5)
    return round(max(55, min(96, confidence)), 1)


def nearest_port(lat: float, lon: float):
    best_name = "Open Sea"
    best_distance = float("inf")
    for name, (port_lat, port_lon) in PORT_COORDS.items():
        distance = abs(lat - port_lat) + abs(lon - port_lon)
        if distance < best_distance:
            best_name = name
            best_distance = distance
    return best_name


def parse_float(value, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def vessel_identifier(vessel: dict) -> str:
    return str(vessel.get("mmsi") or vessel.get("id") or vessel.get("name") or "unknown")


def manifest_priority(cargo_class: str) -> str:
    cargo_class = str(cargo_class or "").lower()
    if cargo_class in {"critical", "high value"}:
        return "P1"
    if cargo_class in {"energy", "priority"}:
        return "P2"
    return "P3"


def cargo_is_verified_source(vessel: dict) -> bool:
    if vessel.get("cargo_verified") is True:
        return True
    return str(vessel.get("cargo_source") or "").strip().lower() == "verified manifest"


def effective_vessel_cargo_priority(vessel: dict) -> str:
    priority = manifest_priority(vessel.get("cargo_class", ""))
    if cargo_is_verified_source(vessel):
        return priority
    if str(vessel.get("source") or "").lower() == "aisstream" or str(vessel.get("cargo_source") or "").lower().startswith("inferred"):
        return "P2" if priority == "P1" else priority
    return priority


def vessel_operational_priority(vessel: dict) -> int:
    status = str(vessel.get("status", "active")).lower()
    cargo_priority = effective_vessel_cargo_priority(vessel)
    score = 0
    if status in {"destroyed", "damaged"}:
        score += 45
    if parse_float(vessel.get("speed_knots")) <= 1 and status == "active":
        score += 14
    if cargo_priority == "P1":
        score += 24
    elif cargo_priority == "P2":
        score += 14
    return score


def serialize_ai_action(action: AIAction):
    return {
        "id": action.id,
        "priority": action.priority,
        "subject": action.subject,
        "action_type": action.action_type,
        "recommendation": action.recommendation,
        "evidence": action.evidence,
        "status": action.status,
        "owner": action.owner,
        "source": action.source,
        "created_at": action.created_at.isoformat() if action.created_at else None,
        "updated_at": action.updated_at.isoformat() if action.updated_at else None,
    }


def serialize_cargo_manifest(manifest: CargoManifest):
    verified = manifest_is_verified(manifest)
    return {
        "id": manifest.id,
        "vessel_identifier": manifest.vessel_identifier,
        "vessel_name": manifest.vessel_name,
        "cargo": manifest.cargo,
        "cargo_class": manifest.cargo_class,
        "cargo_tons": manifest.cargo_tons,
        "cargo_value": manifest.cargo_value,
        "origin_port": manifest.origin_port,
        "destination_port": manifest.destination_port,
        "priority": manifest.priority,
        "status": manifest.status,
        "cargo_source": "Verified Manifest" if verified else "Inferred Demo Cargo",
        "cargo_verified": verified,
        "updated_at": manifest.updated_at.isoformat() if manifest.updated_at else None,
    }


def serialize_incident(event: IncidentEvent):
    return {
        "id": event.id,
        "title": event.title,
        "category": event.category,
        "severity": event.severity,
        "location": event.location,
        "vessel_name": event.vessel_name,
        "route": event.route,
        "description": event.description,
        "source": event.source,
        "status": event.status,
        "timestamp": event.timestamp.isoformat() if event.timestamp else None,
    }


def serialize_ais_history(row: AISPositionHistory):
    return {
        "id": row.id,
        "vessel_identifier": row.vessel_identifier,
        "vessel_name": row.vessel_name,
        "position_lat": row.position_lat,
        "position_lon": row.position_lon,
        "speed_knots": row.speed_knots,
        "heading": row.heading,
        "nearest_port": row.nearest_port,
        "source": row.source,
        "status": row.status,
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
    }


def risk_band(score: float):
    if score >= 8:
        return "Critical"
    if score >= 7:
        return "High"
    if score >= 5:
        return "Elevated"
    if score >= 4:
        return "Guarded"
    return "Stable"


def region_for_port(port_name: str):
    return {
        "Shanghai": "Asia-Pacific",
        "Singapore": "Asia-Pacific",
        "Dubai": "Middle East",
        "Rotterdam": "Europe",
        "Los Angeles": "Americas",
    }.get(port_name, "Global")


def build_port_summary(vessels: list[dict], assessments: list[dict]):
    vessel_counts = Counter(nearest_port(vessel_lat(vessel), vessel_lon(vessel)) for vessel in vessels)
    rows = []
    for port_name, (lat, lon) in PORT_COORDS.items():
        related_scores = [
            item["score"]
            for item in assessments
            if port_name in item.get("route", "")
        ]
        average_risk = sum(related_scores) / len(related_scores) if related_scores else 0
        rows.append({
            "port": port_name,
            "region": region_for_port(port_name),
            "lat": lat,
            "lon": lon,
            "vessels": vessel_counts.get(port_name, 0),
            "average_risk": round(average_risk, 2),
            "status": risk_band(average_risk),
        })
    return sorted(rows, key=lambda row: row["average_risk"], reverse=True)


def build_regional_risk(port_summary: list[dict]):
    regions = {}
    for port in port_summary:
        region = port["region"]
        regions.setdefault(region, {"scores": [], "vessels": 0, "ports": 0})
        regions[region]["scores"].append(port["average_risk"])
        regions[region]["vessels"] += port["vessels"]
        regions[region]["ports"] += 1
    rows = []
    for region, data in regions.items():
        average_risk = sum(data["scores"]) / len(data["scores"]) if data["scores"] else 0
        rows.append({
            "region": region,
            "risk_level": round(average_risk, 2),
            "vessels": data["vessels"],
            "ports": data["ports"],
            "status": risk_band(average_risk),
        })
    return sorted(rows, key=lambda row: row["risk_level"], reverse=True)


def record_incident_once(
    db: Session,
    title: str,
    category: str,
    severity: str,
    location: str,
    vessel_name: str = "",
    route: str = "",
    description: str = "",
    source: str = "system",
):
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)
    existing = (
        db.query(IncidentEvent)
        .filter(
            IncidentEvent.title == title,
            IncidentEvent.vessel_name == vessel_name,
            IncidentEvent.location == location,
            IncidentEvent.timestamp >= since,
        )
        .first()
    )
    if existing:
        return existing
    event = IncidentEvent(
        title=title,
        category=category,
        severity=severity,
        location=location,
        vessel_name=vessel_name,
        route=route,
        description=description,
        source=source,
        status="open",
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    db.add(event)
    return event


def upsert_ai_action(
    db: Session,
    subject: str,
    priority: str,
    action_type: str,
    recommendation: str,
    evidence: str,
    owner: str,
    source: str,
):
    existing = (
        db.query(AIAction)
        .filter(AIAction.subject == subject, AIAction.action_type == action_type, AIAction.status.in_(["queued", "approved"]))
        .order_by(AIAction.id.desc())
        .first()
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    if existing:
        existing.priority = priority
        existing.recommendation = recommendation
        existing.evidence = evidence
        existing.owner = owner
        existing.source = source
        existing.updated_at = now
        return existing
    action = AIAction(
        priority=priority,
        subject=subject,
        action_type=action_type,
        recommendation=recommendation,
        evidence=evidence,
        status="queued",
        owner=owner,
        source=source,
        created_at=now,
        updated_at=now,
    )
    db.add(action)
    return action


def persist_operational_snapshot(packet: dict):
    snapshot = packet.get("snapshot", {})
    vessels = snapshot.get("vessels", [])
    decisions = snapshot.get("route_assessments") or snapshot.get("decisions", [])
    threats = snapshot.get("threats", [])
    incident = snapshot.get("incident")
    now = datetime.datetime.now(datetime.timezone.utc)
    db = SessionLocal()
    try:
        for vessel in vessels[:30]:
            identifier = vessel_identifier(vessel)
            lat = parse_float(vessel.get("position_lat"))
            lon = parse_float(vessel.get("position_lon"))
            db.add(AISPositionHistory(
                vessel_identifier=identifier,
                vessel_name=str(vessel.get("name") or identifier),
                position_lat=lat,
                position_lon=lon,
                speed_knots=parse_float(vessel.get("speed_knots")),
                heading=parse_float(vessel.get("heading")),
                nearest_port=nearest_port(lat, lon),
                source=str(vessel.get("source") or snapshot.get("source") or "Demo"),
                status=str(vessel.get("status") or "active"),
                timestamp=now,
            ))

            cargo_name = str(vessel.get("cargo") or "").strip()
            cargo_source = str(vessel.get("cargo_source") or "").strip().lower()
            snapshot_source = str(vessel.get("source") or snapshot.get("source") or "").strip().lower()
            should_persist_manifest = bool(
                cargo_name
                and cargo_name.lower() != "unknown"
                and (
                    vessel.get("cargo_verified")
                    or cargo_source == "verified manifest"
                    or (snapshot_source != "aisstream" and cargo_source != "inferred demo cargo")
                )
            )
            if should_persist_manifest:
                existing_manifest = (
                    db.query(CargoManifest)
                    .filter(CargoManifest.vessel_identifier == identifier)
                    .order_by(CargoManifest.id.desc())
                    .first()
                )
                cargo_class = str(vessel.get("cargo_class") or "General")
                manifest_values = {
                    "vessel_name": str(vessel.get("name") or identifier),
                    "cargo": cargo_name,
                    "cargo_class": cargo_class,
                    "cargo_tons": parse_float(vessel.get("cargo_tons")),
                    "cargo_value": str(vessel.get("cargo_value") or "Unknown"),
                    "origin_port": str(vessel.get("origin_port") or nearest_port(lat, lon)),
                    "destination_port": str(vessel.get("destination_port") or vessel.get("ais_destination") or "Unknown"),
                    "priority": manifest_priority(cargo_class),
                    "status": "active",
                    "updated_at": now,
                }
                if existing_manifest:
                    for key, value in manifest_values.items():
                        setattr(existing_manifest, key, value)
                else:
                    db.add(CargoManifest(vessel_identifier=identifier, **manifest_values))

            priority_score = vessel_operational_priority(vessel)
            if priority_score >= 35:
                upsert_ai_action(
                    db,
                    subject=str(vessel.get("name") or identifier),
                    priority="P1" if priority_score >= 55 else "P2",
                    action_type="Vessel control",
                    recommendation=(
                        f"Review {vessel.get('name') or identifier}: cargo {vessel.get('cargo', 'Unknown')}, "
                        f"status {vessel.get('status', 'active')}, speed {vessel.get('speed_knots', 0)} kn."
                    ),
                    evidence=f"Operational priority score {priority_score}; nearest port {nearest_port(lat, lon)}.",
                    owner="Fleet controller",
                    source=str(vessel.get("source") or snapshot.get("source") or "Live feed"),
                )

        for decision in decisions[:6]:
            score = parse_float(decision.get("risk_score", decision.get("score")))
            if score >= 6.5:
                upsert_ai_action(
                    db,
                    subject=str(decision.get("route") or "Unknown route"),
                    priority="P1" if score >= 8 else "P2",
                    action_type="Route release",
                    recommendation=str(decision.get("action") or decision.get("decision") or "Review route."),
                    evidence=str(decision.get("explanation") or f"Risk score {score:.1f}/10."),
                    owner="Operations lead" if score >= 7 else "Fleet monitoring desk",
                    source="AI risk engine",
                )

        for threat in threats:
            record_incident_once(
                db,
                title=str(threat.get("name") or threat.get("type") or "Moving threat"),
                category=str(threat.get("type") or "Threat"),
                severity=str(threat.get("severity") or "medium"),
                location=nearest_port(parse_float(threat.get("position_lat")), parse_float(threat.get("position_lon"))),
                vessel_name=str(threat.get("target") or ""),
                description=f"{threat.get('status', 'moving')} toward {threat.get('target', 'unknown target')}",
                source="AI live feed",
            )

        if incident:
            record_incident_once(
                db,
                title=str(incident.get("title") or "Live incident"),
                category="Incident",
                severity=str(incident.get("severity") or "medium"),
                location=str(incident.get("location") or "Unknown"),
                vessel_name=str(incident.get("vessel") or ""),
                description=f"Live incident status: {incident.get('status', 'open')}",
                source="AI live feed",
            )

        cutoff = now - datetime.timedelta(hours=24)
        db.query(AISPositionHistory).filter(AISPositionHistory.timestamp < cutoff).delete()
        db.commit()
    finally:
        db.close()


def persist_operational_snapshot_if_due(packet: dict, interval_seconds: int = 20):
    global LAST_OPERATIONAL_PERSIST_AT
    now_ts = time.time()
    with OPERATIONAL_PERSIST_LOCK:
        if now_ts - LAST_OPERATIONAL_PERSIST_AT < interval_seconds:
            return
        LAST_OPERATIONAL_PERSIST_AT = now_ts
    try:
        persist_operational_snapshot(packet)
    except Exception as exc:
        logger.exception("Operational snapshot persistence failed: %s", exc)


def serialize_report(report: GeneratedReport):
    content = report.content or ""
    return {
        "id": report.id,
        "timestamp": report.timestamp.isoformat() if report.timestamp else None,
        "status": "Complete",
        "summary": content.splitlines()[0] if content else "Generated report",
        "content_preview": content[:240],
    }


def build_operations_intelligence(
    vessels: list[dict],
    routes: list[TradeRoute],
    alerts: list[ThreatAlert],
    assessments: list[dict],
    report_count: int,
    fleet_source: str = "Local fleet registry",
):
    high_alerts = [alert for alert in alerts if str(alert.severity).lower() == "high"]
    active_vessels = sum(1 for vessel in vessels if vessel_status(vessel) == "active")
    critical_routes = [item for item in assessments if float(item.get("score", 0)) >= 8]
    high_routes = [item for item in assessments if float(item.get("score", 0)) >= 7]
    average_risk = sum(item["score"] for item in assessments) / len(assessments) if assessments else 0

    readiness = 100
    readiness -= len(high_alerts) * 8
    readiness -= len(critical_routes) * 12
    readiness -= max(0, len(vessels) - active_vessels) * 4
    readiness -= max(0, average_risk - 5) * 5
    readiness = round(max(0, min(100, readiness)), 1)

    bottlenecks = []
    if high_alerts:
        bottlenecks.append(f"{len(high_alerts)} high-severity alerts require review.")
    if high_routes:
        bottlenecks.append(f"{len(high_routes)} routes are in high or critical risk bands.")
    if active_vessels < len(vessels):
        bottlenecks.append(f"{len(vessels) - active_vessels} vessels are not active in {fleet_source}.")
    if not bottlenecks:
        bottlenecks.append("No major operational bottlenecks detected.")

    next_actions = []
    for item in assessments[:3]:
        next_actions.append({
            "priority": "P1" if item["score"] >= 8 else "P2" if item["score"] >= 7 else "P3",
            "route": item["route"],
            "action": item["action"],
            "owner": "Operations lead" if item["score"] >= 7 else "Fleet monitor",
        })
    if high_alerts:
        next_actions.insert(0, {
            "priority": "P1",
            "route": "Threat desk",
            "action": f"Validate {high_alerts[0].title} at {high_alerts[0].location} and update route release decision.",
            "owner": "Security analyst",
        })

    checklist = [
        {
            "control": "Route release review",
            "status": "Required" if high_routes else "Ready",
            "evidence": f"{len(high_routes)} high-risk routes",
        },
        {
            "control": "Threat watch handoff",
            "status": "Required" if high_alerts else "Ready",
            "evidence": f"{len(high_alerts)} high-severity alerts",
        },
        {
            "control": "Fleet availability",
            "status": "Review" if active_vessels < len(vessels) else "Ready",
            "evidence": f"{active_vessels}/{len(vessels)} vessels active via {fleet_source}",
        },
        {
            "control": "Report archive",
            "status": "Ready" if report_count else "Review",
            "evidence": f"{report_count} generated reports",
        },
    ]

    return {
        "readiness_score": readiness,
        "readiness_band": "Ready" if readiness >= 80 else "Watch" if readiness >= 65 else "At Risk",
        "average_risk": round(average_risk, 2),
        "fleet_source": fleet_source,
        "fleet_summary": {
            "vessels": len(vessels),
            "active": active_vessels,
            "aisstream": get_aisstream_status(),
        },
        "bottlenecks": bottlenecks,
        "next_actions": next_actions[:6],
        "checklist": checklist,
    }


@app.get("/analytics/overview")
def get_analytics_overview(db: Session = Depends(get_db)):
    vessels, fleet_source = get_operational_vessels(db)
    routes = unique_by(
        db.query(TradeRoute).order_by(TradeRoute.id).all(),
        lambda route: (route.origin_port, route.destination_port),
    )
    alerts = unique_by(
        db.query(ThreatAlert).order_by(ThreatAlert.id.desc()).all(),
        lambda alert: (alert.title, alert.location, alert.severity),
    )
    assessments = build_route_assessments(routes, alerts)
    port_summary = build_port_summary(vessels, assessments)
    severity_counts = Counter(str(alert.severity).lower() for alert in alerts)
    fleet_counts = Counter(vessel_status(vessel) for vessel in vessels)
    average_risk = sum(item["score"] for item in assessments) / len(assessments) if assessments else 0
    critical_alerts = severity_counts.get("high", 0)
    mission_status = "Critical" if critical_alerts or average_risk >= 7 else "Controlled"
    if average_risk < 4 and not critical_alerts:
        mission_status = "Normal"

    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "mission_status": mission_status,
        "fleet_source": fleet_source,
        "aisstream": get_aisstream_status(),
        "summary": {
            "vessels": len(vessels),
            "routes": len(routes),
            "alerts": len(alerts),
            "average_risk": round(average_risk, 2),
            "critical_alerts": critical_alerts,
            "active_vessels": fleet_counts.get("active", 0),
        },
        "severity_counts": {
            "high": severity_counts.get("high", 0),
            "medium": severity_counts.get("medium", 0),
            "low": severity_counts.get("low", 0),
        },
        "fleet_status": dict(fleet_counts),
        "live_vessels": vessels[:8],
        "top_routes": assessments[:5],
        "port_summary": port_summary,
        "regional_risk": build_regional_risk(port_summary),
        "latest_alerts": [serialize_alert(alert) for alert in alerts[:8]],
    }


@app.get("/analytics/operations")
def get_operations_intelligence(db: Session = Depends(get_db)):
    vessels, fleet_source = get_operational_vessels(db)
    routes = unique_by(
        db.query(TradeRoute).order_by(TradeRoute.id).all(),
        lambda route: (route.origin_port, route.destination_port),
    )
    alerts = unique_by(
        db.query(ThreatAlert).order_by(ThreatAlert.id.desc()).all(),
        lambda alert: (alert.title, alert.location, alert.severity),
    )
    assessments = build_route_assessments(routes, alerts)
    report_count = db.query(GeneratedReport).count()
    return build_operations_intelligence(vessels, routes, alerts, assessments, report_count, fleet_source)


@app.get("/analytics/forecast")
def get_risk_forecast(days: int = 14, db: Session = Depends(get_db)):
    days = max(3, min(days, 30))
    routes = unique_by(
        db.query(TradeRoute).order_by(TradeRoute.id).all(),
        lambda route: (route.origin_port, route.destination_port),
    )
    alerts = unique_by(
        db.query(ThreatAlert).order_by(ThreatAlert.id.desc()).all(),
        lambda alert: (alert.title, alert.location, alert.severity),
    )
    assessments = build_route_assessments(routes, alerts)
    logs = db.query(RiskLog).order_by(RiskLog.timestamp).all()
    history = [
        {
            "id": log.id,
            "route_id": log.route_id,
            "risk_score": round(log.risk_score, 2),
            "timestamp": log.timestamp.isoformat() if log.timestamp else None,
        }
        for log in logs
    ]

    today = datetime.datetime.now(datetime.timezone.utc).date()
    forecast = []
    for index, assessment in enumerate(assessments):
        base_score = float(assessment["score"])
        for day in range(1, days + 1):
            drift = (base_score - 5) * 0.035 * day
            seasonal = math.sin((day + index) / 2.7) * 0.38
            score = max(1, min(10, base_score + drift + seasonal))
            forecast.append({
                "date": (today + datetime.timedelta(days=day)).isoformat(),
                "route": assessment["route"],
                "forecast_score": round(score, 2),
                "band": risk_band(score),
                "confidence": max(55, round(float(assessment["confidence"]) - (day * 0.8), 1)),
            })

    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "history": history,
        "forecast": forecast,
        "top_forecast": sorted(forecast, key=lambda item: item["forecast_score"], reverse=True)[:5],
    }


@app.get("/reports")
def list_reports(limit: int = 10, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 50))
    reports = db.query(GeneratedReport).order_by(GeneratedReport.id.desc()).limit(limit).all()
    return [serialize_report(report) for report in reports]


def move_vessel_toward_route(vessel: Vessel, route: TradeRoute, tick: int):
    origin = PORT_COORDS.get(route.origin_port)
    destination = PORT_COORDS.get(route.destination_port)
    if not origin or not destination or vessel.status in {"destroyed", "maintenance"}:
        return
    progress = ((tick + vessel.id) % 100) / 100
    wave = math.sin((tick + vessel.id) / 3) * 0.35
    vessel.position_lat = origin[0] + ((destination[0] - origin[0]) * progress) + (wave * 0.1)
    vessel.position_lon = origin[1] + ((destination[1] - origin[1]) * progress) + wave
    if vessel.status == "damaged" and tick % 4 == 0:
        vessel.status = "active"


def build_live_vessel_payload(vessel: Vessel, route: TradeRoute, index: int, now: datetime.datetime):
    origin = PORT_COORDS.get(route.origin_port, (vessel.position_lat, vessel.position_lon))
    destination = PORT_COORDS.get(route.destination_port, origin)
    now_ts = now.timestamp()
    distance = float(route.distance or 1)
    visual_cycle_seconds = max(140.0, min(420.0, distance / 32.0))
    progress = ((now_ts / visual_cycle_seconds) + (index * 0.173) + (vessel.id * 0.031)) % 1
    wave = math.sin((now_ts / 5.0) + vessel.id) * 0.28
    lat = origin[0] + ((destination[0] - origin[0]) * progress) + (wave * 0.08)
    lon = origin[1] + ((destination[1] - origin[1]) * progress) + wave
    heading = bearing_angle(origin[0], origin[1], destination[0], destination[1])
    speed_knots = round(16 + ((index * 2.7) % 9) + (math.sin(now_ts / 13 + index) * 1.4), 1)
    remaining_nm = max(0.0, distance * (1 - progress))
    eta_hours = round(remaining_nm / max(speed_knots, 1), 1)
    cargo = LIVE_CARGO_MANIFESTS[index % len(LIVE_CARGO_MANIFESTS)]

    return {
        "id": vessel.id,
        "name": vessel.name,
        "position_lat": round(lat, 5),
        "position_lon": round(lon, 5),
        "api_position_lat": round(lat, 5),
        "api_position_lon": round(lon, 5),
        "display_position_lat": round(lat, 5),
        "display_position_lon": round(lon, 5),
        "motion_source": "Demo route simulation",
        "motion_projected_nm": 0,
        "motion_age_seconds": 0,
        "motion_trail": [[round(lon - (math.sin(math.radians(heading)) * 1.8), 5), round(lat - (math.cos(math.radians(heading)) * 0.65), 5)], [round(lon, 5), round(lat, 5)]],
        "status": vessel.status,
        "route": f"{route.origin_port} to {route.destination_port}",
        "origin_port": route.origin_port,
        "destination_port": route.destination_port,
        "origin_lat": origin[0],
        "origin_lon": origin[1],
        "destination_lat": destination[0],
        "destination_lon": destination[1],
        "cargo": cargo["cargo"],
        "cargo_class": cargo["class"],
        "cargo_tons": cargo["tons"],
        "cargo_value": cargo["value"],
        "progress": round(progress, 4),
        "speed_knots": speed_knots,
        "eta_hours": eta_hours,
        "heading": round(heading, 1),
        "last_signal_at": now.isoformat(),
    }


def build_live_threats(tick: int, vessels: list[dict], now_ts: float | None = None):
    if not vessels:
        return []

    phase = now_ts if now_ts is not None else float(tick)
    pirate_target = vessels[(tick + 1) % len(vessels)]
    pirate_progress = (phase % 48) / 48
    pirate_start_lat = pirate_target["position_lat"] + 4.8
    pirate_start_lon = pirate_target["position_lon"] - 7.2
    pirate_lat = pirate_start_lat + ((pirate_target["position_lat"] - pirate_start_lat) * pirate_progress)
    pirate_lon = pirate_start_lon + ((pirate_target["position_lon"] - pirate_start_lon) * pirate_progress)

    storm_target = vessels[(tick + 3) % len(vessels)]
    storm_progress = (phase % 72) / 72
    storm_start_lat = storm_target["position_lat"] - 5.2
    storm_start_lon = storm_target["position_lon"] + 5.8
    storm_lat = storm_start_lat + ((storm_target["position_lat"] - storm_start_lat) * storm_progress)
    storm_lon = storm_start_lon + ((storm_target["position_lon"] - storm_start_lon) * storm_progress)

    return [
        {
            "id": "pirate-skiff-1",
            "type": "Pirate skiff",
            "name": "Pirate Skiff",
            "position_lat": pirate_lat,
            "position_lon": pirate_lon,
            "target": pirate_target["name"],
            "target_lat": pirate_target["position_lat"],
            "target_lon": pirate_target["position_lon"],
            "severity": "high",
            "status": "approaching",
            "eta_minutes": max(2, int((1 - pirate_progress) * 42)),
        },
        {
            "id": "storm-cell-1",
            "type": "Storm cell",
            "name": "Storm Cell",
            "position_lat": storm_lat,
            "position_lon": storm_lon,
            "target": storm_target["name"],
            "target_lat": storm_target["position_lat"],
            "target_lon": storm_target["position_lon"],
            "severity": "medium",
            "status": "moving",
            "eta_minutes": max(5, int((1 - storm_progress) * 65)),
        },
    ]


@app.post("/demo/tick")
def run_demo_tick(db: Session = Depends(get_db)):
    vessels = unique_by(db.query(Vessel).order_by(Vessel.id).all(), lambda vessel: vessel.name)
    routes = unique_by(
        db.query(TradeRoute).order_by(TradeRoute.id).all(),
        lambda route: (route.origin_port, route.destination_port),
    )
    if not vessels or not routes:
        raise HTTPException(status_code=400, detail="Seed data is required before running the demo")

    now = datetime.datetime.now(datetime.timezone.utc)
    now_ts = now.timestamp()
    tick = int(now_ts)
    real_vessels = get_aisstream_vessels()
    simulated_vessels = real_vessels
    live_source = "AISStream" if real_vessels else "Demo simulation"

    incident = None
    if not simulated_vessels:
        incident_index = int(now_ts // 14) % len(vessels)
        incident_active = int(now_ts // 18) % 4 == 0
        incident_template = DEMO_INCIDENTS[int(now_ts // 22) % len(DEMO_INCIDENTS)]

        for index, vessel in enumerate(vessels):
            route = routes[index % len(routes)]
            live_vessel = build_live_vessel_payload(vessel, route, index, now)
            if incident_active and index == incident_index:
                severity = incident_template[2]
                status = "destroyed" if severity == "high" else "damaged"
                incident_location = nearest_port(live_vessel["position_lat"], live_vessel["position_lon"])
                live_vessel["status"] = status
                live_vessel["incident"] = incident_template[0]
                incident = {
                    "title": incident_template[0],
                    "severity": severity,
                    "vessel": vessel.name,
                    "location": incident_template[3] if incident_template[3] != "Pacific Ocean" else incident_location,
                    "status": status,
                }
            simulated_vessels.append(live_vessel)

    threats = build_live_threats(tick, simulated_vessels, now_ts)

    alerts = unique_by(
        db.query(ThreatAlert).order_by(ThreatAlert.id.desc()).all(),
        lambda alert: (alert.title, alert.location, alert.severity),
    )[:8]

    decisions = []
    for route in routes:
        pulse = math.sin((now_ts / 9) + route.id) * 1.25
        incident_boost = 1.4 if incident and incident["location"] in {route.origin_port, route.destination_port, "South China Sea", "Gulf of Aden"} else 0
        live_alert_pressure = incident_boost * 2.0 if incident_boost else None
        assessment = assess_route_risk(
            route,
            alerts=alerts,
            alert_pressure=live_alert_pressure,
            live_modifier=(pulse * 0.35) + incident_boost,
        )
        risk_score = assessment["score"]
        decisions.append({
            "route": assessment["route"],
            "risk_score": round(risk_score, 2),
            "band": assessment["band"],
            "confidence": assessment["confidence"],
            "decision": assessment["decision"],
            "action": assessment["action"],
            "top_drivers": assessment["top_drivers"],
            "explanation": assessment["explanation"],
        })

    simulated_alerts = [serialize_alert(alert) for alert in alerts]
    if incident:
        simulated_alerts.insert(0, {
            "id": f"demo-{tick}",
            "title": incident["title"],
            "description": f"Live demo incident affecting {incident['vessel']}",
            "severity": incident["severity"],
            "location": incident["location"],
        })
    avg_risk = sum(item["risk_score"] for item in decisions) / len(decisions)
    destroyed = sum(1 for vessel in simulated_vessels if vessel["status"] == "destroyed")
    damaged = sum(1 for vessel in simulated_vessels if vessel["status"] == "damaged")

    return {
        "tick": tick,
        "timestamp": now.isoformat(),
        "source": live_source,
        "aisstream": get_aisstream_status(),
        "summary": {
            "average_risk": round(avg_risk, 2),
            "active_vessels": sum(1 for vessel in simulated_vessels if vessel["status"] == "active"),
            "damaged_vessels": damaged,
            "destroyed_vessels": destroyed,
            "open_alerts": len(simulated_alerts),
        },
        "incident": incident,
        "vessels": simulated_vessels,
        "threats": threats,
        "routes": [serialize_route(route) for route in routes],
        "alerts": simulated_alerts[:8],
        "decisions": sorted(decisions, key=lambda item: item["risk_score"], reverse=True),
        "route_assessments": sorted(decisions, key=lambda item: item["risk_score"], reverse=True),
    }


def build_ai_intelligence(snapshot: dict):
    detections = []
    predictions = []
    action_plan = []
    alerts = snapshot.get("alerts", [])
    vessels = snapshot.get("vessels", [])
    threats = snapshot.get("threats", [])
    decisions = snapshot.get("decisions", [])
    incident = snapshot.get("incident")

    for threat in threats:
        threat_type = threat.get("type", "Threat")
        severity = "critical" if threat.get("severity") == "high" else "warning"
        detections.append({
            "where": nearest_port(threat.get("position_lat", 0), threat.get("position_lon", 0)),
            "what": f"{threat_type} approaching",
            "evidence": f"{threat.get('name')} is {threat.get('status')} toward {threat.get('target')} with ETA {threat.get('eta_minutes')} min",
            "severity": severity,
            "confidence": confidence_for_score(8.8 if severity == "critical" else 6.6, 3),
        })
        predictions.append({
            "where": threat.get("target", "Unknown vessel"),
            "prediction": f"{threat_type} may intercept target in about {threat.get('eta_minutes')} minutes",
            "predicted_score": 8.7 if severity == "critical" else 6.3,
            "confidence": confidence_for_score(8.2 if severity == "critical" else 6.1, 3),
            "why": "Moving threat position is converging with vessel track.",
        })
        action_plan.append({
            "priority": "P1" if severity == "critical" else "P2",
            "decision": "Intercept avoidance" if severity == "critical" else "Weather avoidance",
            "where": threat.get("target"),
            "action": f"Change course or speed for {threat.get('target')} before {threat.get('name')} closes distance.",
            "owner": "AI fleet controller",
            "automation": "Highlight threat on map, raise route risk, and alert operator",
        })

    for vessel in vessels:
        status = str(vessel.get("status", "active")).lower()
        if status in {"damaged", "destroyed"}:
            severity = "critical" if status == "destroyed" else "warning"
            detections.append({
                "where": nearest_port(vessel.get("position_lat", 0), vessel.get("position_lon", 0)),
                "what": f"Vessel {status}",
                "evidence": f"{vessel.get('name')} reported as {status}",
                "severity": severity,
                "confidence": confidence_for_score(8.6 if status == "destroyed" else 6.4, 2),
            })

    for alert in alerts:
        severity = str(alert.get("severity", "")).lower()
        if severity in {"high", "medium"}:
            alert_text = f"{alert.get('title', '')} {alert.get('description', '')}"
            score = 8.4 if severity == "high" else 5.8
            detections.append({
                "where": alert.get("location", "Unknown"),
                "what": f"{risk_type_from_text(alert_text)} risk",
                "evidence": alert.get("description", alert.get("title", "")),
                "severity": "critical" if severity == "high" else "warning",
                "confidence": confidence_for_score(score, 1),
            })

    for decision in decisions:
        score = float(decision.get("risk_score", 0) or 0)
        route = decision.get("route", "Unknown route")
        trend = "rising" if score >= 6 else "stable"
        predicted_score = max(1, min(10, score + (1.1 if trend == "rising" else 0.35)))
        predictions.append({
            "where": route,
            "prediction": f"Risk likely {trend} over the next 2-6 hours",
            "predicted_score": round(predicted_score, 1),
            "confidence": confidence_for_score(predicted_score, len(alerts[:3])),
            "why": "Driven by active alerts, route exposure, and live vessel status.",
        })
        if score >= 7:
            action_plan.append({
                "priority": "P1",
                "decision": decision.get("decision"),
                "where": route,
                "action": decision.get("action"),
                "owner": "Operations lead",
                "automation": "Prepare reroute and notify port authority",
            })
        elif score >= 5:
            action_plan.append({
                "priority": "P2",
                "decision": decision.get("decision"),
                "where": route,
                "action": decision.get("action"),
                "owner": "Fleet monitoring desk",
                "automation": "Increase tracking frequency and watch alert feed",
            })

    if incident:
        action_plan.insert(0, {
            "priority": "P1",
            "decision": "Incident response",
            "where": incident.get("location"),
            "action": f"Respond to {incident.get('title')} affecting {incident.get('vessel')}.",
            "owner": "Emergency response",
            "automation": "Flag vessel, update map status, and escalate alert",
        })

    top_decision = decisions[0] if decisions else {}
    watchlist = []
    for decision in decisions[:5]:
        driver_text = ", ".join(
            driver.get("label", driver.get("factor", "driver"))
            for driver in decision.get("top_drivers", [])[:2]
        ) or "route baseline"
        watchlist.append({
            "route": decision.get("route"),
            "risk_score": decision.get("risk_score"),
            "band": decision.get("band"),
            "confidence": decision.get("confidence"),
            "why": driver_text,
            "next_best_action": decision.get("action"),
        })

    escalation_level = "P1" if any(item.get("priority") == "P1" for item in action_plan) else "P2"
    if snapshot.get("summary", {}).get("average_risk", 0) < 4:
        escalation_level = "Watch"

    strategic_playbooks = [
        {
            "name": "Reroute corridor",
            "trigger": "Any route reaches critical band or a moving security threat converges.",
            "steps": "Freeze departure, compare alternate lane, notify port authority, then release only after risk drops below 7.",
        },
        {
            "name": "Weather hold",
            "trigger": "Storm ETA is under 60 minutes or weather impact is a top driver.",
            "steps": "Reduce speed, shift waypoint, increase tracking cadence, and notify receiving terminal.",
        },
        {
            "name": "Cyber / operations hardening",
            "trigger": "Global cyber, geopolitical, or port disruption alert enters the feed.",
            "steps": "Verify EDI/API access, lock manual fallback, and confirm customs documentation availability.",
        },
    ]
    mission_status = "Critical" if any(item.get("priority") == "P1" for item in action_plan) else "Controlled"
    if snapshot.get("summary", {}).get("average_risk", 0) < 4:
        mission_status = "Normal"

    brief = (
        f"AI status: {mission_status}. "
        f"Highest route concern is {top_decision.get('route', 'not available')} "
        f"with decision: {top_decision.get('decision', 'monitor')} "
        f"at {top_decision.get('confidence', 0)}% confidence. "
        f"{len(detections)} active detections and {len(predictions)} predictions were generated."
    )

    return {
        "mission_status": mission_status,
        "brief": brief,
        "detections": detections[:8],
        "predictions": sorted(predictions, key=lambda item: item["predicted_score"], reverse=True)[:8],
        "action_plan": action_plan[:8],
        "watchlist": watchlist,
        "strategic_playbooks": strategic_playbooks,
        "escalation_level": escalation_level,
        "confidence": confidence_for_score(snapshot.get("summary", {}).get("average_risk", 0), len(detections)),
        "mode": "Local explainable AI decision engine",
    }


def build_ai_command_packet(db: Session):
    snapshot = run_demo_tick(db)
    intelligence = build_ai_intelligence(snapshot)
    return {
        "snapshot": snapshot,
        "intelligence": intelligence,
    }


def refresh_ai_live_state():
    db = SessionLocal()
    try:
        packet = build_ai_command_packet(db)
    finally:
        db.close()
    persist_operational_snapshot_if_due(packet)
    with AI_LIVE_LOCK:
        AI_LIVE_STATE["packet"] = packet
        AI_LIVE_STATE["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return packet


def ai_live_update_loop():
    while True:
        try:
            refresh_ai_live_state()
        except Exception as exc:
            logger.exception("AI live update failed: %s", exc)
        time.sleep(1)


def start_ai_live_updates():
    start_aisstream_listener()
    with AI_LIVE_LOCK:
        if AI_LIVE_STATE["running"]:
            return
        AI_LIVE_STATE["running"] = True
    thread = threading.Thread(target=ai_live_update_loop, daemon=True)
    thread.start()


@app.post("/ai/command")
def ai_command_center():
    return refresh_ai_live_state()


@app.get("/ai/live")
def ai_live_feed():
    with AI_LIVE_LOCK:
        packet = AI_LIVE_STATE["packet"]
        updated_at = AI_LIVE_STATE["updated_at"]
    if packet is None:
        packet = refresh_ai_live_state()
        with AI_LIVE_LOCK:
            updated_at = AI_LIVE_STATE["updated_at"]
    return {
        **packet,
        "live_updated_at": updated_at,
        "backend_live_loop": True,
    }

def generate_report_background(report_id: int):
    logger.info(f"Starting background report generation for report {report_id}")
    time.sleep(2)
    db = SessionLocal()
    try:
        report = db.query(GeneratedReport).filter(GeneratedReport.id == report_id).first()
        if report:
            report.content += " (Processed in background)"
            db.commit()
    finally:
        db.close()
    logger.info(f"Completed background report generation for report {report_id}")

@app.post("/generate-report")
def generate_report(
    background_tasks: BackgroundTasks,
    request: ReportRequest | None = None,
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    request = request or ReportRequest()
    alerts = unique_by(
        db.query(ThreatAlert).order_by(ThreatAlert.id.desc()).all(),
        lambda alert: (alert.title, alert.location, alert.severity),
    )
    routes = unique_by(
        db.query(TradeRoute).order_by(TradeRoute.id).all(),
        lambda route: (route.origin_port, route.destination_port),
    )
    assessments = build_route_assessments(routes, alerts)
    current_risk = sum(item["score"] for item in assessments) / len(assessments) if assessments else 0
    high_alerts = [alert for alert in alerts if str(alert.severity).lower() == "high"]
    priority_routes = assessments[:3]

    report_lines = [
        f"Global AI Trade Intelligence Report - {request.report_type}",
        f"Generated: {datetime.datetime.now(datetime.timezone.utc).isoformat()}",
        f"Report window: {request.date_range or 'Current operating picture'}",
        f"AI average route risk: {current_risk:.2f}/10",
        f"Critical alert count: {len(high_alerts)}",
    ]

    if request.include_routes:
        report_lines.extend(["", "Priority routes"])
        for item in priority_routes:
            drivers = ", ".join(driver["label"] for driver in item["top_drivers"])
            report_lines.append(
                f"- {item['route']}: {item['score']}/10 ({item['band']}), confidence {item['confidence']}%, drivers: {drivers}"
            )
            report_lines.append(f"  Action: {item['action']}")

    if request.include_vessels:
        vessels, fleet_source = get_operational_vessels(db)
        fleet_counts = Counter(vessel_status(vessel) for vessel in vessels)
        report_lines.extend(["", f"Fleet status ({fleet_source})"])
        for status, count in sorted(fleet_counts.items()):
            report_lines.append(f"- {status.title()}: {count}")
        if vessels:
            report_lines.extend(["", "Live vessel sample"])
            for vessel in vessels[:6]:
                report_lines.append(
                    f"- {vessel_field(vessel, 'name', 'Unknown vessel')}: "
                    f"{vessel_field(vessel, 'speed_knots', 'n/a')} kn near "
                    f"{nearest_port(vessel_lat(vessel), vessel_lon(vessel))} "
                    f"({vessel_field(vessel, 'source', fleet_source)})"
                )

        queued_actions = db.query(AIAction).filter(AIAction.status == "queued").order_by(AIAction.id.desc()).limit(6).all()
        report_lines.extend(["", "AI action queue"])
        if queued_actions:
            for action in queued_actions:
                report_lines.append(f"- {action.priority} {action.subject}: {action.recommendation} ({action.owner})")
        else:
            report_lines.append("- No AI actions are currently queued.")

        recent_incidents = db.query(IncidentEvent).order_by(IncidentEvent.timestamp.desc()).limit(6).all()
        report_lines.extend(["", "Recent operational timeline"])
        if recent_incidents:
            for event in recent_incidents:
                report_lines.append(f"- {event.severity.title()} {event.title} at {event.location}: {event.description}")
        else:
            report_lines.append("- No recent incidents recorded.")

    if request.include_alerts:
        report_lines.extend(["", "Active high-severity alerts"])
        if high_alerts:
            for alert in high_alerts[:6]:
                report_lines.append(f"- {alert.title} at {alert.location}: {alert.description}")
        else:
            report_lines.append("- No high-severity alerts are active.")

    report_lines.extend([
        "",
        "Recommendations",
        "- Review the top route before departure release.",
        "- Keep backend AI live feed open during active scenarios.",
        "- Re-run the report after any new high-severity alert or incident.",
    ])
    report_content = "\n".join(report_lines)
    pdf_path = safe_generate_pdf_report(report_content)
    report = GeneratedReport(content=report_content, timestamp=datetime.datetime.now(datetime.timezone.utc))
    db.add(report)
    record_audit_event(
        db,
        action="pdf_report_generated",
        resource=request.report_type,
        detail=f"Generated report with routes={request.include_routes}, vessels={request.include_vessels}, alerts={request.include_alerts}.",
        severity="info",
        request=http_request,
    )
    db.commit()
    db.refresh(report)
    
    # Add background task
    background_tasks.add_task(generate_report_background, report.id)
    
    return {
        "report_id": report.id,
        "pdf_path": pdf_path,
        "message": "Report generation started",
        "report_type": request.report_type,
    }
