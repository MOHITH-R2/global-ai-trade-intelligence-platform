import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import pydeck as pdk
import datetime
import os
import math
import time
import html
from urllib.parse import quote
from dotenv import load_dotenv
import streamlit.components.v1 as components

load_dotenv()

API_BASE = os.getenv("API_BASE", "http://localhost:8000")
API_TIMEOUT = 8
STATUS_TIMEOUT = 1.5
MAP_STYLE = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"
PROJECT_TITLE = "Global AI Trade Intelligence Platform"
PROJECT_SUBTITLE = "AI maritime risk, route, cargo, and fleet command center"
HTTP = requests.Session()
SESSION_QUERY_PARAM = "session_token"

SECTION_SUMMARIES = {
    "Dashboard": "mission overview, route pressure, live/fallback vessels, alerts, and readiness",
    "Command Center": "AI Captain, problem solver, control tower, smart inbox, and strategic decisions",
    "Fleet & Operations": "vessel tracking, AIS movement, cargo exposure, operations, and ETA prediction",
    "Risk & Alerts": "risk levels, threat alerts, forecasts, incidents, and defensive playbooks",
    "Scenario Lab": "digital twin simulations for storms, piracy, port shutdowns, cyber, fuel, and cargo risks",
    "Reports": "PDF exports, smart briefs, report history, and project intelligence summaries",
}

PORT_COORDS = {
    "Shanghai": (31.2304, 121.4737),
    "Singapore": (1.3521, 103.8198),
    "Rotterdam": (51.9244, 4.4777),
    "Los Angeles": (33.7182, -118.1957),
    "Dubai": (25.2048, 55.2708),
}

MARITIME_WATCH_ZONES = [
    {"name": "Gulf of Aden", "lat": 12.0, "lon": 45.0, "score": 8.8, "type": "Piracy / Security"},
    {"name": "Red Sea Approach", "lat": 21.5, "lon": 37.0, "score": 8.4, "type": "War / Disruption"},
    {"name": "Strait of Hormuz", "lat": 26.6, "lon": 56.2, "score": 8.1, "type": "Geopolitical"},
    {"name": "Gulf of Guinea", "lat": 2.5, "lon": 5.5, "score": 7.6, "type": "Cargo / Hijack"},
    {"name": "Black Sea", "lat": 44.5, "lon": 34.5, "score": 8.2, "type": "War / Geopolitical"},
]


def _configure_page():
    st.set_page_config(page_title=PROJECT_TITLE, layout="wide", page_icon="ship")


def api_cache_ttl(path):
    if path.startswith(("/health", "/notifications")):
        return 18 if bool(st.session_state.get("mobile_performance_mode", False)) else 12
    if path.startswith(("/weather/maritime", "/ports/congestion")):
        return 90 if bool(st.session_state.get("mobile_performance_mode", False)) else 45
    if path.startswith("/ai/live"):
        return 8 if bool(st.session_state.get("mobile_performance_mode", False)) else 4
    heavy_live_paths = (
        "/ai/captain",
        "/ai/risk-intelligence",
        "/ai/strategic-autopilot",
        "/ai/voyage-control-tower",
        "/operations/inbox",
    )
    live_paths = (
        "/ai/mission-map-overlay",
        "/ai/incident-predictions",
        "/vessels/live",
    )
    static_paths = (
        "/auth/roles",
        "/auth/provider-status",
        "/ais/reliability",
        "/settings/runtime",
        "/settings/production-mode",
        "/production/upgrade-hub",
        "/notifications/delivery-plan",
        "/routes/sea-lane-engine",
        "/deployment/hardening",
        "/deployment/readiness",
        "/data-quality",
        "/data-cleanup/summary",
        "/system/reliability",
    )
    if path.startswith(heavy_live_paths):
        return 20 if bool(st.session_state.get("mobile_performance_mode", False)) else 12
    if path.startswith(live_paths):
        if bool(st.session_state.get("mobile_performance_mode", False)):
            return max(14, int(st.session_state.get("ui_refresh_seconds", 10)))
        return max(10, int(st.session_state.get("ui_refresh_seconds", 10)))
    if path.startswith(static_paths):
        return 60
    if any(token in path for token in ["history", "timeline", "reports", "forecast", "predictions"]):
        return 20 if bool(st.session_state.get("mobile_performance_mode", False)) else 12
    return 8


@st.cache_data(show_spinner=False, max_entries=256)
def cached_api_get(api_base, path, cache_bucket):
    response = requests.get(f"{api_base}{path}", timeout=API_TIMEOUT)
    response.raise_for_status()
    return response.json()


def api_get(path, fresh=False):
    if fresh:
        response = HTTP.get(f"{API_BASE}{path}", timeout=API_TIMEOUT)
        response.raise_for_status()
        return response.json()
    ttl = api_cache_ttl(path)
    cache_bucket = int(time.time() // max(1, ttl))
    return cached_api_get(API_BASE, path, cache_bucket)


def auth_headers():
    ensure_user_context()
    return {
        "X-User-Role": str(st.session_state.user_role),
        "X-User-Identity": str(st.session_state.auth_identity),
    }


def api_post(path, payload=None):
    response = HTTP.post(f"{API_BASE}{path}", json=payload, headers=auth_headers(), timeout=API_TIMEOUT)
    response.raise_for_status()
    cached_api_get.clear()
    return response


def query_param_value(key):
    try:
        value = st.query_params.get(key)
        if isinstance(value, list):
            return value[0] if value else None
        return value
    except Exception:
        return None


def set_session_token(token):
    if not token:
        return
    st.session_state.auth_session_token = token
    try:
        st.query_params[SESSION_QUERY_PARAM] = token
    except Exception:
        pass


def clear_session_token():
    st.session_state.auth_session_token = None
    st.session_state.auth_expires_at = None
    try:
        if SESSION_QUERY_PARAM in st.query_params:
            del st.query_params[SESSION_QUERY_PARAM]
    except Exception:
        pass


def normalize_browser_time(value):
    try:
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo:
            parsed = parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return parsed
    except Exception:
        return None


def restore_session_from_query():
    if st.session_state.get("auth_restore_attempted"):
        return
    token = query_param_value(SESSION_QUERY_PARAM) or st.session_state.get("auth_session_token")
    if not token:
        return
    st.session_state.auth_restore_attempted = True
    try:
        response = HTTP.post(f"{API_BASE}/auth/session/validate", json={"token": token}, timeout=API_TIMEOUT)
        response.raise_for_status()
        apply_auth_result(response.json())
    except Exception:
        clear_session_token()


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


def normalize_role_name(role):
    return ROLE_ALIASES.get(str(role or "").strip().lower(), "Public")


ROLE_PERMISSIONS = {
    "Admin": {"approve_actions", "edit_cargo", "create_alerts", "generate_reports", "manage_vessels", "tune_ais", "manage_alert_workflows", "run_scenarios", "view_quality", "view_predictions"},
    "Operator": {"approve_actions", "edit_cargo", "create_alerts", "generate_reports", "manage_vessels", "manage_alert_workflows", "run_scenarios", "view_quality", "view_predictions"},
    "Public": {"read_only"},
}

ROLE_DEMO_LOGINS = {
    "Admin": {
        "email": "admin@demo.app",
        "password": "admin-demo",
        "provider": "Admin Fingerprint",
        "payload": {"biometric_ok": True, "phrase": "ADMIN ACCESS"},
    },
    "Operator": {
        "email": "operator@demo.app",
        "password": "operator-demo",
        "provider": "Company SSO",
        "payload": {"mfa_code": "123456"},
    },
}

ROLE_SESSION_LIMITS = {
    "Admin": 15,
    "Operator": 30,
    "Public": 20,
}

DEFAULT_AUTH_META = {
    "roles": {
        "Admin": {
            "permissions": sorted(ROLE_PERMISSIONS["Admin"]),
            "landing_page": "Command Center",
            "risk": "Full command authority for settings, AIS, approvals, users, data maintenance, reports, and production controls.",
            "auth": {
                "required_level": "critical",
                "required_methods": ["password", "fingerprint/passkey confirmation", "ADMIN ACCESS phrase"],
                "allowed_providers": ["Admin Fingerprint"],
                "session_minutes": 15,
                "idle_timeout_minutes": 5,
                "step_up_for": ["approve_actions", "tune_ais", "manage_alert_workflows", "generate_reports"],
                "device_policy": "Trusted device plus fingerprint/passkey challenge for every critical action.",
            },
            "data_scope": "all_routes_all_cargo_all_settings",
        },
        "Operator": {
            "permissions": sorted(ROLE_PERMISSIONS["Operator"]),
            "landing_page": "Command Center",
            "risk": "Unified operations access for fleet, cargo, risks, alerts, scenarios, reports, and Voyage Control Tower actions.",
            "auth": {
                "required_level": "elevated",
                "required_methods": ["password", "6-digit MFA/passkey code"],
                "allowed_providers": ["Company SSO", "Security Key"],
                "session_minutes": 30,
                "idle_timeout_minutes": 10,
                "step_up_for": ["approve_actions", "edit_cargo", "create_alerts", "manage_alert_workflows", "generate_reports"],
                "device_policy": "MFA/passkey required on sign-in and any high-risk approval.",
            },
            "data_scope": "operational_routes_vessels_cargo_alerts_reports",
        },
        "Public": {
            "permissions": sorted(ROLE_PERMISSIONS["Public"]),
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
            },
            "data_scope": "public_demo_only",
        },
    },
    "providers": {
        "Admin Fingerprint": {"label": "Fingerprint access", "provider_type": "biometric_fingerprint"},
        "Company SSO": {"label": "Company SSO + MFA", "provider_type": "enterprise_sso"},
        "Security Key": {"label": "Hardware security key", "provider_type": "hardware_key"},
        "Email Magic Link": {"label": "Email magic link", "provider_type": "low_risk_viewer"},
        "Google OAuth": {"label": "Continue with Google", "provider_type": "public_oauth"},
        "Facebook Login": {"label": "Continue with Facebook", "provider_type": "public_oauth"},
        "Instagram Login": {"label": "Continue with Instagram", "provider_type": "public_oauth"},
        "Apple Sign In": {"label": "Continue with Apple", "provider_type": "public_oauth"},
        "Discord Login": {"label": "Continue with Discord", "provider_type": "community_oauth"},
        "Game Center": {"label": "Continue with Game Center", "provider_type": "gaming_identity"},
        "Xbox Live": {"label": "Continue with Xbox Live", "provider_type": "gaming_identity"},
    },
    "strict_mode": True,
    "default_role": "Public",
    "role_aliases": ROLE_ALIASES,
    "hardening_controls": [
        "Default to Public until a role-specific sign-in flow succeeds.",
        "Block all write actions unless the active session role matches the required permission.",
        "Require fingerprint/passkey step-up for Admin and MFA/passkey step-up for Operator.",
    ],
}


def ensure_user_context():
    if "user_role" not in st.session_state:
        st.session_state.user_role = "Public"
    st.session_state.user_role = normalize_role_name(st.session_state.user_role)
    if st.session_state.user_role not in ROLE_PERMISSIONS:
        st.session_state.user_role = "Public"
    if "authenticated_role" not in st.session_state:
        st.session_state.authenticated_role = st.session_state.user_role if st.session_state.user_role == "Public" else None
    elif st.session_state.authenticated_role:
        st.session_state.authenticated_role = normalize_role_name(st.session_state.authenticated_role)
    if "auth_verified" not in st.session_state:
        st.session_state.auth_verified = st.session_state.user_role == "Public"
    if "auth_provider" not in st.session_state:
        st.session_state.auth_provider = "Guest preview"
    if "auth_method" not in st.session_state:
        st.session_state.auth_method = "public preview"
    if "auth_identity" not in st.session_state:
        st.session_state.auth_identity = "Public Guest"
    if "auth_started_at" not in st.session_state:
        st.session_state.auth_started_at = datetime.datetime.now().isoformat(timespec="seconds")
    if "auth_expires_at" not in st.session_state:
        st.session_state.auth_expires_at = None
    if "auth_session_token" not in st.session_state:
        st.session_state.auth_session_token = query_param_value(SESSION_QUERY_PARAM)
    if "auth_restore_attempted" not in st.session_state:
        st.session_state.auth_restore_attempted = False
    if "biometric_scan_ok" not in st.session_state:
        st.session_state.biometric_scan_ok = False
    if "security_audit" not in st.session_state:
        st.session_state.security_audit = []
    if "auth_entry_completed" not in st.session_state:
        st.session_state.auth_entry_completed = False
    if "auth_entry_mode" not in st.session_state:
        st.session_state.auth_entry_mode = "Admin"
    if "auth_flow_mode" not in st.session_state:
        st.session_state.auth_flow_mode = "Sign In"
    if "demo_accounts" not in st.session_state:
        st.session_state.demo_accounts = {
            "admin@demo.app": {"name": "Command Admin", "role": "Admin", "provider": "Admin Fingerprint", "password": "admin-demo"},
            "operator@demo.app": {"name": "Command Operator", "role": "Operator", "provider": "Company SSO", "password": "operator-demo"},
            "public@demo.app": {"name": "Public Guest", "role": "Public", "provider": "Email Magic Link", "password": "public-demo"},
        }
    if "ui_refresh_seconds" not in st.session_state:
        st.session_state.ui_refresh_seconds = 10
    if st.session_state.get("refresh_stability_version") != 4:
        st.session_state.live_command_refresh = False
        st.session_state.ui_refresh_seconds = max(10, int(st.session_state.get("ui_refresh_seconds", 10) or 10))
        st.session_state.refresh_stability_version = 4
    if "mobile_performance_mode" not in st.session_state:
        st.session_state.mobile_performance_mode = False
    if "map_region" not in st.session_state:
        st.session_state.map_region = "Global default lanes"
    if "utility_page" not in st.session_state:
        st.session_state.utility_page = None
    if not st.session_state.auth_entry_completed:
        restore_session_from_query()


def current_role():
    ensure_user_context()
    return st.session_state.user_role


def can(permission):
    return is_role_authenticated() and permission in ROLE_PERMISSIONS.get(current_role(), set())


def role_gate(permission, action_name):
    if can(permission):
        return True
    if not is_role_authenticated():
        st.warning(f"{action_name} requires verified sign-in for {current_role()}. Open Settings and complete the role security check.")
    else:
        st.warning(f"{action_name} requires a higher access level. Current role: {current_role()}.")
    return False


def is_role_authenticated(role=None):
    ensure_user_context()
    role = normalize_role_name(role or st.session_state.user_role)
    if role == "Public":
        return True
    if auth_is_expired(role):
        return False
    return bool(st.session_state.auth_verified) and st.session_state.authenticated_role == role


def auth_status_label():
    if current_role() != "Public" and auth_is_expired():
        return "Expired"
    if is_role_authenticated():
        return "Verified"
    return "Locked"


def auth_age_minutes():
    try:
        started = datetime.datetime.fromisoformat(st.session_state.auth_started_at)
        return max(0, int((datetime.datetime.now() - started).total_seconds() // 60))
    except Exception:
        return 0


def auth_session_limit_minutes(role=None):
    role = role or current_role()
    return ROLE_SESSION_LIMITS.get(role, 20)


def auth_remaining_minutes(role=None):
    role = normalize_role_name(role or current_role())
    if role == "Public":
        return ROLE_SESSION_LIMITS["Public"]
    if not bool(st.session_state.get("auth_verified")):
        return 0
    expires_at = normalize_browser_time(st.session_state.get("auth_expires_at"))
    if expires_at:
        return max(0, int((expires_at - datetime.datetime.utcnow()).total_seconds() // 60))
    return max(0, auth_session_limit_minutes(role) - auth_age_minutes())


def auth_is_expired(role=None):
    ensure_user_context()
    role = normalize_role_name(role or st.session_state.user_role)
    if role == "Public":
        return False
    if st.session_state.authenticated_role != role:
        return False
    expires_at = normalize_browser_time(st.session_state.get("auth_expires_at"))
    if expires_at:
        return expires_at <= datetime.datetime.utcnow()
    return auth_age_minutes() >= auth_session_limit_minutes(role)


def sign_in_role(role, provider, method, identity, session_expires_at=None):
    ensure_user_context()
    role = normalize_role_name(role)
    st.session_state.user_role = role
    st.session_state.authenticated_role = role
    st.session_state.auth_verified = True
    st.session_state.auth_entry_completed = True
    st.session_state.auth_provider = provider
    st.session_state.auth_method = method
    st.session_state.auth_identity = identity or role
    st.session_state.auth_started_at = datetime.datetime.now().isoformat(timespec="seconds")
    st.session_state.auth_expires_at = session_expires_at
    st.session_state.biometric_scan_ok = role == "Admin"
    st.session_state.security_audit.insert(0, {
        "Time": st.session_state.auth_started_at,
        "Event": f"{role} session verified",
        "Provider": provider,
        "Method": method,
    })
    st.session_state.security_audit = st.session_state.security_audit[:8]


def sign_out_to_public():
    clear_session_token()
    st.session_state.user_role = "Public"
    st.session_state.authenticated_role = "Public"
    st.session_state.auth_verified = True
    st.session_state.auth_entry_completed = True
    st.session_state.auth_provider = "Guest preview"
    st.session_state.auth_method = "public preview"
    st.session_state.auth_identity = "Public Guest"
    st.session_state.auth_started_at = datetime.datetime.now().isoformat(timespec="seconds")
    st.session_state.biometric_scan_ok = False


def return_to_login_gate():
    clear_session_token()
    st.session_state.auth_entry_completed = False
    st.session_state.user_role = "Public"
    st.session_state.authenticated_role = None
    st.session_state.auth_verified = False
    st.session_state.auth_provider = "Locked"
    st.session_state.auth_method = "Awaiting login"
    st.session_state.auth_identity = "Not signed in"
    st.session_state.biometric_scan_ok = False


def display_setting_value(value):
    if value is None:
        return "Not reported"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (list, tuple, set, dict)):
        return str(value)
    return str(value)


def compact_badge_count(rows, severity="critical"):
    return sum(1 for row in rows or [] if row.get("severity") == severity)


def safe_html(value):
    return html.escape(str(value or ""))


def notification_rank(severity):
    return {"critical": 0, "warning": 1, "info": 2}.get(str(severity).lower(), 3)


def notification_age(timestamp):
    try:
        clean_value = str(timestamp).replace("Z", "+00:00")
        event_time = datetime.datetime.fromisoformat(clean_value)
        if event_time.tzinfo:
            event_time = event_time.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        delta = datetime.datetime.utcnow() - event_time
        seconds = max(0, int(delta.total_seconds()))
        if seconds < 60:
            return f"{seconds}s ago"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m ago"
        return f"{minutes // 60}h ago"
    except Exception:
        return "time unknown"


def severity_tone(severity):
    severity = str(severity).lower()
    if severity == "critical":
        return "#ef4444", "P1"
    if severity == "warning":
        return "#f59e0b", "P2"
    return "#38bdf8", "INFO"


def incident_color(priority):
    priority = str(priority).upper()
    if priority == "P1":
        return "#ef4444"
    if priority == "P2":
        return "#f59e0b"
    return "#22d3ee"


def render_incident_card(card, key_prefix="incident"):
    color = incident_color(card.get("priority"))
    checklist = card.get("checklist", []) or []
    checklist_html = "<br>".join(f"- {safe_html(item)}" for item in checklist[:3])
    st.markdown(
        f"""
        <div class="incident-card" style="--incident-color:{color};">
            <span class="severity-chip" style="--chip-color:{color};">{safe_html(card.get('priority', 'P3'))}</span>
            <b>{safe_html(card.get('title', 'Incident card'))}</b>
            <div>{safe_html(card.get('summary', 'No summary returned.'))}</div>
            <div class="notification-meta">
                Target: {safe_html(card.get('target', 'Command'))} | Owner: {safe_html(card.get('owner', 'Operations'))}
            </div>
            <div class="notification-meta">{checklist_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def admin_step_up_ready(key, label="critical action"):
    if current_role() != "Admin":
        return True
    st.caption(f"Admin step-up required for {label}: confirm passkey and type `APPROVE`.")
    
    components.html(
        """
        <button onclick="triggerWebAuthn()" style="background: rgba(20, 184, 166, 0.12); border: 1px solid rgba(20, 184, 166, 0.4); color: #99f6e4; padding: 8px 16px; border-radius: 6px; cursor: pointer; width: 100%; font-family: sans-serif; font-weight: bold; transition: all 0.2s;">
            Scan WebAuthn Passkey
        </button>
        <script>
            async function triggerWebAuthn() {
                const btn = document.querySelector('button');
                btn.innerText = "Scanning...";
                try {
                    const challenge = new Uint8Array(32);
                    window.crypto.getRandomValues(challenge);
                    await navigator.credentials.get({
                        publicKey: { challenge: challenge, userVerification: "discouraged", timeout: 60000 }
                    });
                    btn.innerText = "Passkey Verified";
                    btn.style.background = "rgba(16, 185, 129, 0.3)";
                } catch (err) {
                    btn.innerText = "Scan WebAuthn Passkey";
                    alert("Passkey prompt cancelled or unavailable. Use fallback checkbox.");
                }
            }
        </script>
        """,
        height=45,
    )

    c1, c2 = st.columns([0.7, 1])
    with c1:
        scan_ok = st.checkbox("Passkey confirmed", key=f"{key}_fingerprint")
    with c2:
        phrase = st.text_input("Approval phrase", type="password", key=f"{key}_phrase", placeholder="APPROVE")
    return bool(scan_ok and phrase.strip().upper() == "APPROVE")


def run_command_action(action, target, owner, note="", priority="P2", source="Executive Command"):
    return api_post(
        "/command/actions",
        {
            "action": action,
            "target": target or "Command",
            "owner": owner or current_role(),
            "note": note or f"{action.replace('_', ' ').title()} from {source}.",
            "priority": priority,
            "source": source,
        },
    ).json()


@st.dialog("Notifications", width="large")
def dialog_notifications():
    show_notifications()

@st.dialog("Settings", width="large")
def dialog_settings():
    show_settings()


def render_top_utility_bar(notifications=None, health=None):
    notifications = notifications or []
    health = health or {}
    critical = compact_badge_count(notifications, "critical")
    api_status = health.get("status", "offline").title() if isinstance(health, dict) else "Offline"
    active_utility = st.session_state.get("utility_page")

    st.markdown(
        """
<style>
.app-topbar-anchor {
    margin-top: -1.1rem;
}
.topbar-glass {
    background: rgba(15, 23, 42, 0.78);
    border: 1px solid rgba(148, 163, 184, 0.2);
    border-radius: 8px;
    padding: 0.58rem 0.78rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    box-shadow: none;
    margin-bottom: 0.75rem;
}
.topbar-branding {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
}
.topbar-pill-status {
    background: rgba(20, 184, 166, 0.14);
    color: #99f6e4;
    border: 1px solid rgba(45, 212, 191, 0.34);
    padding: 2px 10px;
    border-radius: 6px;
    font-size: 0.75rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0;
    box-shadow: none;
}
.topbar-pill-offline {
    background: rgba(239, 68, 68, 0.12);
    color: #f87171;
    border: 1px solid rgba(239, 68, 68, 0.4);
    padding: 2px 10px;
    border-radius: 6px;
    font-size: 0.75rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0;
    box-shadow: none;
}
.topbar-title {
    font-size: 1rem;
    font-weight: 800;
    color: #f8fafc;
    letter-spacing: 0;
    text-shadow: none;
    line-height: 1.2;
}
.topbar-title-stack {
    display: flex;
    flex-direction: column;
    gap: 0.08rem;
    min-width: 15rem;
}
.topbar-subtitle {
    color: rgba(226, 232, 240, 0.68);
    font-size: 0.76rem;
    line-height: 1.2;
}
.topbar-meta {
    color: #94a3b8;
    font-size: 0.82rem;
    display: flex;
    gap: 0.48rem;
    align-items: center;
    flex-wrap: wrap;
}
.meta-divider {
    color: rgba(148, 163, 184, 0.3);
}
</style>
<div class="app-topbar-anchor"></div>
        """,
        unsafe_allow_html=True,
    )

    left, spacer, notify_col, settings_col, close_col = st.columns([5, 0.5, 1.2, 1.2, 0.7])
    
    with left:
        status_class = "topbar-pill-status" if api_status.lower() == "online" else "topbar-pill-offline"
        st.markdown(
            f"""
<div class="topbar-glass">
<div class="topbar-branding">
<span class="{status_class}">{safe_html(api_status)}</span>
<span class="topbar-title-stack">
    <span class="topbar-title">{safe_html(PROJECT_TITLE)}</span>
    <span class="topbar-subtitle">{safe_html(PROJECT_SUBTITLE)}</span>
</span>
<div class="topbar-meta">
<span class="meta-divider">|</span>
<span style="color: #38bdf8; font-weight: 600;">{safe_html(current_role())}</span>
<span class="meta-divider">|</span>
<span>{safe_html(auth_status_label())}</span>
</div>
</div>
</div>
            """,
            unsafe_allow_html=True,
        )

    with notify_col:
        notify_label = f"Alerts ({len(notifications)})"
        alert_type = "primary" if critical else "secondary"
        if st.button(notify_label, key="utility_open_notifications", type=alert_type, use_container_width=True, icon=":material/notifications_active:", help="Open notification center"):
            dialog_notifications()
    with settings_col:
        if st.button("Settings", key="utility_open_settings", use_container_width=True, icon=":material/settings:", help="Open settings"):
            dialog_settings()
    with close_col:
        if active_utility and st.button("Close", key="utility_close", use_container_width=True, icon=":material/close:"):
            close_utility_page()
            st.rerun()


def close_utility_page():
    st.session_state.utility_page = None


def show_api_error(section, error):
    st.error(f"{section} could not connect to the backend at {API_BASE}.")
    st.caption(f"Details: {error}")
    retry_col, cache_col = st.columns(2)
    with retry_col:
        if st.button("Retry", key=f"retry_{section}", use_container_width=True, icon=":material/refresh:"):
            st.rerun()
    with cache_col:
        if st.button("Clear cache", key=f"clear_cache_{section}", use_container_width=True, icon=":material/cached:"):
            cached_api_get.clear()
            st.rerun()


def clamp_score(value):
    return max(0.0, min(10.0, float(value)))


def risk_label(score):
    if score >= 7:
        return "High"
    if score >= 4:
        return "Medium"
    return "Low"


def risk_color(score):
    if score >= 7:
        return "#d62728"
    if score >= 4:
        return "#f59e0b"
    return "#16a34a"


def severity_weight(severity):
    return {"high": 2.6, "medium": 1.5, "low": 0.7}.get(str(severity).lower(), 0.4)


def route_alert_pressure(route, alerts):
    route_text = f"{route.get('origin_port', '')} {route.get('destination_port', '')}".lower()
    pressure = 0
    matched_alerts = []
    for alert in alerts:
        location = str(alert.get("location", "")).lower()
        title = str(alert.get("title", "")).lower()
        if location and any(token in route_text for token in location.split()):
            pressure += severity_weight(alert.get("severity"))
            matched_alerts.append(alert)
        elif any(keyword in title for keyword in ["piracy", "weather", "geopolitical", "delay"]):
            pressure += severity_weight(alert.get("severity")) * 0.35
            matched_alerts.append(alert)
    return clamp_score(pressure), matched_alerts[:3]


def explain_route_risk(route, alerts):
    base_risk = clamp_score(route.get("risk_level", 0))
    distance = float(route.get("distance", 0) or 0)
    distance_pressure = clamp_score(distance / 1800)
    alert_pressure, matched_alerts = route_alert_pressure(route, alerts)
    congestion_pressure = clamp_score((base_risk * 0.45) + (alert_pressure * 0.35))
    operational_pressure = clamp_score((distance_pressure * 0.4) + (base_risk * 0.35) + (alert_pressure * 0.25))
    final_score = clamp_score((base_risk * 0.45) + (alert_pressure * 0.25) + (distance_pressure * 0.18) + (congestion_pressure * 0.12))
    factors = {
        "Existing model risk": base_risk,
        "Alert pressure": alert_pressure,
        "Distance exposure": distance_pressure,
        "Port congestion proxy": congestion_pressure,
        "Operational complexity": operational_pressure,
    }
    top_factor = max(factors, key=factors.get)
    return {
        "score": final_score,
        "label": risk_label(final_score),
        "factors": factors,
        "top_factor": top_factor,
        "alerts": matched_alerts,
    }


def risk_type_from_explanation(explanation):
    top_factor = explanation["top_factor"]
    if top_factor == "Alert pressure":
        alert_titles = " ".join(str(alert.get("title", "")).lower() for alert in explanation["alerts"])
        if "piracy" in alert_titles:
            return "Security / piracy risk"
        if "weather" in alert_titles or "storm" in alert_titles:
            return "Weather disruption risk"
        if "geopolitical" in alert_titles or "sanction" in alert_titles:
            return "Geopolitical risk"
        return "Active alert risk"
    if top_factor == "Distance exposure":
        return "Long-route exposure risk"
    if top_factor == "Port congestion proxy":
        return "Port congestion risk"
    if top_factor == "Operational complexity":
        return "Operational delay risk"
    return "Route baseline risk"


def decision_for_risk(score):
    if score >= 8:
        return "Hold / reroute"
    if score >= 7:
        return "Escalate before departure"
    if score >= 5:
        return "Proceed with controls"
    if score >= 4:
        return "Monitor"
    return "Proceed"


def action_for_risk(route, explanation):
    route_name = f"{route.get('origin_port')} to {route.get('destination_port')}"
    risk_type = risk_type_from_explanation(explanation)
    score = explanation["score"]
    if score >= 8:
        return f"Pause {route_name}, review alternate routing, and notify port operations before release."
    if score >= 7:
        return f"Escalate {route_name} to the operations lead, confirm alerts, and prepare a reroute option."
    if "congestion" in risk_type.lower():
        return f"Keep {route_name} active, but check berth availability and add delay buffer."
    if "weather" in risk_type.lower():
        return f"Keep {route_name} under weather watch and delay departure if conditions worsen."
    if "security" in risk_type.lower():
        return f"Use enhanced tracking for {route_name} and avoid high-risk corridors where possible."
    if score >= 4:
        return f"Proceed on {route_name} with closer monitoring and a contingency checkpoint."
    return f"Proceed on {route_name} with standard monitoring."


def build_risk_decision_rows(routes, alerts):
    rows = []
    for route in routes:
        explanation = explain_route_risk(route, alerts)
        related_alerts = explanation["alerts"]
        rows.append({
            "Where": f"{route.get('origin_port')} to {route.get('destination_port')}",
            "What Risk": risk_type_from_explanation(explanation),
            "Severity": explanation["label"],
            "Score": round(explanation["score"], 1),
            "Decision": decision_for_risk(explanation["score"]),
            "What To Do": action_for_risk(route, explanation),
            "Evidence": "; ".join(
                f"{alert.get('title')} at {alert.get('location')}" for alert in related_alerts
            ) or f"Model risk {route.get('risk_level', 0):.1f}, distance {route.get('distance', 0)} nm",
            "Primary Driver": explanation["top_factor"],
        })
    return rows


def simulated_risk_score(base_risk, congestion, weather, cargo_importance, delay_probability, geopolitical_risk):
    return clamp_score(
        (base_risk * 0.35)
        + (congestion * 0.18)
        + (weather * 0.16)
        + (delay_probability * 0.14)
        + (geopolitical_risk * 0.12)
        + (cargo_importance * 0.05)
    )


def bearing_angle(start_lat, start_lon, end_lat, end_lon):
    delta_lon = end_lon - start_lon
    delta_lat = end_lat - start_lat
    return math.degrees(math.atan2(delta_lon, delta_lat))


def route_visual_data(routes, decisions=None):
    decision_scores = {
        decision.get("route"): float(decision.get("risk_score", 0) or 0)
        for decision in decisions or []
    }
    route_rows = []
    for route in routes or []:
        origin = PORT_COORDS.get(route.get("origin_port"))
        destination = PORT_COORDS.get(route.get("destination_port"))
        if not origin or not destination:
            continue
        route_name = f"{route.get('origin_port')} to {route.get('destination_port')}"
        risk = decision_scores.get(route_name, float(route.get("risk_level", 0) or 0))
        if risk >= 7:
            color = [239, 68, 68, 185]
        elif risk >= 5:
            color = [245, 158, 11, 170]
        else:
            color = [45, 212, 191, 160]
        route_rows.append({
            "name": route_name,
            "route": route_name,
            "status": f"Risk {round(risk, 1)}",
            "target": "",
            "eta": "",
            "path": [[origin[1], origin[0]], [destination[1], destination[0]]],
            "risk": round(risk, 1),
            "risk_text": f"{round(risk, 1)} RISK",
            "mid_lat": (origin[0] + destination[0]) / 2,
            "mid_lon": (origin[1] + destination[1]) / 2,
            "color": color,
            "glow_color": [color[0], color[1], color[2], 45],
        })
    return route_rows


def port_visual_data(routes):
    names = set()
    for route in routes or []:
        names.add(route.get("origin_port"))
        names.add(route.get("destination_port"))
    rows = []
    for name in sorted(names):
        coords = PORT_COORDS.get(name)
        if coords:
            rows.append({
                "name": name,
                "lat": coords[0],
                "lon": coords[1],
                "color": [255, 255, 255, 220],
                "halo": [14, 165, 233, 70],
            })
    return rows


def numeric_value(value, default=0.0):
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return float(default)


def score_to_map_color(score, alpha=210):
    score = numeric_value(score)
    if score > 10:
        score = score / 10
    if score >= 8:
        return [220, 38, 38, alpha]
    if score >= 6:
        return [245, 158, 11, alpha]
    if score >= 4:
        return [250, 204, 21, alpha]
    return [45, 212, 191, alpha]


def weather_cell_rows(weather_packet):
    rows = []
    for item in (weather_packet or {}).get("ports", []):
        lat = item.get("lat")
        lon = item.get("lon")
        if lat is None or lon is None:
            coords = PORT_COORDS.get(item.get("port"))
            if not coords:
                continue
            lat, lon = coords
        score = numeric_value(item.get("weather_score"))
        color = score_to_map_color(score, 95)
        rows.append({
            "name": f"{item.get('port', 'Weather cell')} weather",
            "detail": "Weather overlay",
            "lat": lat,
            "lon": lon,
            "risk": round(score / 10, 1),
            "status": item.get("band", "Weather watch"),
            "source": (weather_packet or {}).get("source", "Weather model"),
            "wind": f"{item.get('wind_knots', 0)} kn",
            "wave": f"{item.get('wave_meters', 0)} m",
            "control": item.get("recommended_control", "Normal watch"),
            "radius": 260000 + (score * 6200),
            "elevation": 650 + (score * 92),
            "color": color,
            "line": color[:3] + [175],
            "label": f"WX {score:.0f}",
        })
    return rows


def congestion_zone_rows(congestion_packet, fallback_ports=None):
    rows = []
    source_rows = (congestion_packet or {}).get("ports", []) or fallback_ports or []
    for item in source_rows:
        name = item.get("port") or item.get("name")
        coords = PORT_COORDS.get(name, (item.get("lat"), item.get("lon")))
        if coords[0] is None or coords[1] is None:
            continue
        score = numeric_value(item.get("congestion_score", item.get("berth_load", item.get("risk", 0))))
        color = score_to_map_color(score, 150)
        rows.append({
            "name": f"{name} congestion",
            "detail": "Port congestion zone",
            "lat": coords[0],
            "lon": coords[1],
            "risk": round(score / 10, 1),
            "status": item.get("band", item.get("status", "Port flow")),
            "source": (congestion_packet or {}).get("source", "Port analytics"),
            "vessels": item.get("vessels", 0),
            "control": item.get("recommended_staging", "Normal flow"),
            "radius": 190000 + (score * 4300),
            "elevation": 900 + (score * 130),
            "color": color,
            "line": color[:3] + [210],
            "label": f"{name}\n{score:.0f}% flow",
        })
    return rows


def route_comparison_rows(routes, assessment_by_route=None):
    rows = []
    assessment_by_route = assessment_by_route or {}
    for index, route in enumerate(routes or []):
        origin = PORT_COORDS.get(route.get("origin_port"))
        destination = PORT_COORDS.get(route.get("destination_port"))
        if not origin or not destination:
            continue
        route_name = f"{route.get('origin_port')} to {route.get('destination_port')}"
        assessment = assessment_by_route.get(route_name, {})
        risk = numeric_value(assessment.get("risk_score", assessment.get("score", route.get("risk_level", 0))))
        offset = ((index % 3) - 1) * 0.8
        color = score_to_map_color(risk, 180)
        mode = "Safest lane" if risk < 5 else "Watch lane" if risk < 7 else "Avoid if possible"
        rows.append({
            "name": route_name,
            "detail": "Route comparison layer",
            "route": route_name,
            "path": [[origin[1] + offset, origin[0]], [destination[1] + offset, destination[0]]],
            "mid_lat": (origin[0] + destination[0]) / 2,
            "mid_lon": ((origin[1] + destination[1]) / 2) + offset,
            "risk": round(risk, 2),
            "status": mode,
            "source": "Route comparison model",
            "color": color,
            "glow": color[:3] + [38],
            "width": 2.5 + risk,
            "label": f"{mode}: {risk:.1f}",
        })
    return sorted(rows, key=lambda row: row["risk"])


def threat_heat_rows(overview=None, routes=None, vessels=None, assessment_by_route=None):
    rows = []
    for zone in MARITIME_WATCH_ZONES:
        score = numeric_value(zone.get("score"))
        rows.append({
            "name": zone["name"],
            "detail": zone["type"],
            "lat": zone["lat"],
            "lon": zone["lon"],
            "risk": score,
            "status": "Global watch zone",
            "source": "Global maritime risk model",
            "weight": round(score * 12, 1),
            "radius": 430000 + (score * 78000),
            "color": score_to_map_color(score, 62),
            "line": score_to_map_color(score, 165),
            "label": f"{zone['name']}\n{score:.1f}",
        })
    assessment_by_route = assessment_by_route or {}
    for route in routes or []:
        origin = PORT_COORDS.get(route.get("origin_port"))
        destination = PORT_COORDS.get(route.get("destination_port"))
        if not origin or not destination:
            continue
        route_name = f"{route.get('origin_port')} to {route.get('destination_port')}"
        assessment = assessment_by_route.get(route_name, {})
        risk = numeric_value(assessment.get("risk_score", assessment.get("score", route.get("risk_level", 0))))
        if risk < 4:
            continue
        rows.append({
            "name": f"{route_name} heat",
            "detail": "Route pressure",
            "lat": (origin[0] + destination[0]) / 2,
            "lon": (origin[1] + destination[1]) / 2,
            "risk": round(risk, 2),
            "status": risk_label(risk),
            "source": "Route risk model",
            "weight": round(risk * 10, 1),
            "radius": 280000 + (risk * 52000),
            "color": score_to_map_color(risk, 50),
            "line": score_to_map_color(risk, 135),
            "label": f"Risk {risk:.1f}",
        })
    for vessel in vessels or []:
        risk = numeric_value(vessel.get("risk", vessel_priority_score(vessel) / 10))
        if risk < 4:
            continue
        rows.append({
            "name": f"{vessel.get('name', 'Vessel')} heat",
            "detail": "Vessel pressure",
            "lat": vessel.get("lat", vessel_map_lat(vessel)),
            "lon": vessel.get("lon", vessel_map_lon(vessel)),
            "risk": round(risk, 2),
            "status": vessel.get("status", "Vessel watch"),
            "source": "AIS/cargo risk",
            "weight": round(risk * 8, 1),
            "radius": 180000 + (risk * 42000),
            "color": score_to_map_color(risk, 42),
            "line": score_to_map_color(risk, 120),
            "label": f"{risk:.1f}",
        })
    return rows


def course_vector_rows(ship_rows):
    rows = []
    for row in ship_rows or []:
        lat = numeric_value(row.get("lat"))
        lon = numeric_value(row.get("lon"))
        heading = numeric_value(row.get("angle", 90))
        angle = math.radians(heading)
        strength = max(1.4, min(4.8, numeric_value(row.get("risk", 3)) * 0.38 + 1.6))
        rows.append({
            "name": f"{row.get('name', 'Ship')} projected track",
            "detail": "Projected course vector",
            "path": [[lon, lat], [lon + (math.sin(angle) * strength), lat + (math.cos(angle) * strength * 0.45)]],
            "risk": row.get("risk", ""),
            "status": row.get("status", ""),
            "source": row.get("source", "Course projection"),
            "color": row.get("color", [34, 211, 238, 210])[:3] + [150],
            "width": 3,
        })
    return rows


def vessel_map_lat(vessel):
    return float(vessel.get("display_position_lat", vessel.get("map_lat", vessel.get("lat", vessel.get("position_lat", 0)))) or 0)


def vessel_map_lon(vessel):
    return float(vessel.get("display_position_lon", vessel.get("map_lon", vessel.get("lon", vessel.get("position_lon", 0)))) or 0)


def vessel_api_lat(vessel):
    return float(vessel.get("api_position_lat", vessel.get("position_lat", vessel.get("lat", vessel_map_lat(vessel)))) or 0)


def vessel_api_lon(vessel):
    return float(vessel.get("api_position_lon", vessel.get("position_lon", vessel.get("lon", vessel_map_lon(vessel)))) or 0)


def vessel_motion_trail(vessel, index=0, routes=None):
    trail = vessel.get("motion_trail")
    if isinstance(trail, list) and len(trail) >= 2:
        return trail
    lat = vessel_map_lat(vessel)
    lon = vessel_map_lon(vessel)
    heading = float(vessel.get("heading", 90) or 90)
    if routes:
        route = routes[index % len(routes)]
        origin = PORT_COORDS.get(route.get("origin_port"), (lat, lon))
        destination = PORT_COORDS.get(route.get("destination_port"), (lat, lon))
        heading = bearing_angle(origin[0], origin[1], destination[0], destination[1])
    angle = math.radians(heading)
    tail_lon = lon - (math.sin(angle) * 2.4)
    tail_lat = lat - (math.cos(angle) * 0.9)
    return [[tail_lon, tail_lat], [lon, lat]]


def vessel_wake_path(vessel, index, routes):
    trail = vessel_motion_trail(vessel, index, routes)
    if trail:
        return trail
    lat = vessel_map_lat(vessel)
    lon = vessel_map_lon(vessel)
    if not routes:
        return [[lon - 1.2, lat - 0.2], [lon, lat]]
    route = routes[index % len(routes)]
    origin = PORT_COORDS.get(route.get("origin_port"), (lat, lon))
    destination = PORT_COORDS.get(route.get("destination_port"), (lat, lon))
    angle = math.radians(bearing_angle(origin[0], origin[1], destination[0], destination[1]))
    tail_lon = lon - (math.sin(angle) * 2.4)
    tail_lat = lat - (math.cos(angle) * 0.9)
    return [[tail_lon, tail_lat], [lon, lat]]


def threat_visual_data(threats):
    rows = []
    paths = []
    for threat in threats or []:
        threat_type = str(threat.get("type", "Threat")).lower()
        if "pirate" in threat_type:
            color = [248, 113, 113, 235]
            effect = [239, 68, 68, 88]
            symbol = "ðŸ´â€â˜ ï¸"
            radius = 165000
        elif "storm" in threat_type:
            color = [96, 165, 250, 225]
            effect = [59, 130, 246, 78]
            symbol = "â›ˆï¸"
            radius = 220000
        else:
            color = [250, 204, 21, 230]
            effect = [250, 204, 21, 72]
            symbol = "âš ï¸"
            radius = 160000
        row = {
            "name": threat.get("name", "Threat"),
            "type": threat.get("type", "Threat"),
            "route": "",
            "lat": threat.get("position_lat", 0),
            "lon": threat.get("position_lon", 0),
            "target": threat.get("target", "Unknown"),
            "status": threat.get("status", "active").title(),
            "severity": threat.get("severity", "medium"),
            "eta": f"{threat.get('eta_minutes', '?')} min",
            "color": color,
            "effect_color": effect,
            "symbol": symbol,
            "radius": radius,
            "effect_radius": radius * 2.7,
            "text_color": [255, 255, 255, 255],
        }
        rows.append(row)
        paths.append({
            "name": row["name"],
            "path": [[row["lon"], row["lat"]], [threat.get("target_lon", row["lon"]), threat.get("target_lat", row["lat"])]],
            "color": [248, 113, 113, 160] if "pirate" in threat_type else [96, 165, 250, 145],
        })
    return rows, paths


def radar_ring_data(vessel_rows, threat_rows):
    rows = []
    scan_tick = int(datetime.datetime.now().timestamp()) % 3
    for row in vessel_rows:
        if row["status"] in {"Active", "Damaged"}:
            rows.append({
                "name": f"Radar sweep {row['name']}",
                "lat": row["lat"],
                "lon": row["lon"],
                "radius": 420000 + (scan_tick * 130000),
                "color": [34, 211, 238, 26],
                "line": [103, 232, 249, 125],
            })
    for row in threat_rows:
        rows.append({
            "name": f"Threat radar {row['name']}",
            "lat": row["lat"],
            "lon": row["lon"],
            "radius": row["effect_radius"] * 1.25,
            "color": [248, 113, 113, 30] if row["symbol"] == "ðŸ´â€â˜ ï¸" else [96, 165, 250, 26],
            "line": [248, 113, 113, 160] if row["symbol"] == "ðŸ´â€â˜ ï¸" else [96, 165, 250, 150],
        })
    return rows


def radar_beam_data(vessel_rows, threat_rows):
    rows = []
    sweep = (datetime.datetime.now().timestamp() * 42) % 360
    for index, row in enumerate(vessel_rows + threat_rows):
        if row.get("status") in {"Destroyed", "Maintenance"}:
            continue
        angle = math.radians(sweep + (index * 35))
        reach = 5.2 if row in threat_rows else 3.6
        rows.append({
            "name": f"Radar beam {row['name']}",
            "path": [
                [row["lon"], row["lat"]],
                [row["lon"] + math.sin(angle) * reach, row["lat"] + math.cos(angle) * reach],
            ],
            "color": [103, 232, 249, 115] if row in vessel_rows else [248, 113, 113, 130],
        })
    return rows


def map_radar_overlay_data():
    center_lat = 21.5
    center_lon = 55.0
    sweep = (datetime.datetime.now().timestamp() * 32) % 360
    rings = []
    for radius in [900000, 1800000, 2700000, 3600000, 4800000, 6200000, 7600000]:
        rings.append({
            "name": f"Command radar {radius}",
            "lat": center_lat,
            "lon": center_lon,
            "radius": radius,
            "color": [34, 211, 238, 7],
            "line": [103, 232, 249, 72],
        })

    beams = []
    for offset, alpha, width in [(0, 160, 10), (-7, 90, 7), (7, 90, 7), (-15, 38, 4), (15, 38, 4)]:
        angle = math.radians(sweep + offset)
        beams.append({
            "name": "Global radar sweep",
            "path": [
                [center_lon, center_lat],
                [
                    center_lon + (math.sin(angle) * 108),
                    center_lat + (math.cos(angle) * 54),
                ],
            ],
            "color": [34, 211, 238, alpha],
            "width": width,
        })
    return rings, beams


def map_threat_scan_data(threat_rows, route_rows):
    scan_phase = int(datetime.datetime.now().timestamp()) % 4
    center_lat = 21.5
    center_lon = 55.0
    lock_rings = []
    scan_paths = []
    labels = [{
        "name": "RADAR SWEEP ACTIVE",
        "lat": center_lat + 3.4,
        "lon": center_lon,
        "text": "SCANNING FOR THREATS",
        "color": [103, 232, 249, 235],
        "size": 15,
    }]

    for row in threat_rows or []:
        severity = str(row.get("severity", "medium")).lower()
        is_high = severity == "high"
        lock_color = [248, 113, 113, 54] if is_high else [96, 165, 250, 42]
        line_color = [248, 113, 113, 230] if is_high else [96, 165, 250, 205]
        lock_rings.append({
            "name": f"Threat scan lock {row['name']}",
            "lat": row["lat"],
            "lon": row["lon"],
            "radius": row["effect_radius"] * (1.1 + (scan_phase * 0.18)),
            "color": lock_color,
            "line": line_color,
        })
        scan_paths.append({
            "name": f"Radar track {row['name']}",
            "path": [[center_lon, center_lat], [row["lon"], row["lat"]]],
            "color": line_color[:3] + [135],
            "width": 4 if is_high else 3,
        })
        labels.append({
            "name": row["name"],
            "lat": row["lat"],
            "lon": row["lon"],
            "text": "SCAN LOCK" if is_high else "TRACKING",
            "color": line_color,
            "size": 13,
        })

    for row in route_rows or []:
        if float(row.get("risk", 0) or 0) >= 7:
            lock_rings.append({
                "name": f"Route watch {row['name']}",
                "lat": row["mid_lat"],
                "lon": row["mid_lon"],
                "radius": 360000 + (scan_phase * 85000),
                "color": [245, 158, 11, 36],
                "line": [245, 158, 11, 190],
            })
            labels.append({
                "name": row["name"],
                "lat": row["mid_lat"],
                "lon": row["mid_lon"],
                "text": "ROUTE WATCH",
                "color": [253, 186, 116, 230],
                "size": 12,
            })

    return lock_rings, scan_paths, labels


def build_nautical_layers(vessels, routes, status_key="status", threats=None, decisions=None):
    vessel_rows = []
    wake_rows = []
    route_rows = route_visual_data(routes, decisions)
    port_rows = port_visual_data(routes)
    threat_rows, threat_paths = threat_visual_data(threats)
    wave_tick = datetime.datetime.now().timestamp()
    for index, vessel in enumerate(vessels or []):
        status = str(vessel.get(status_key, vessel.get("status", "active"))).lower()
        lat = vessel_map_lat(vessel)
        lon = vessel_map_lon(vessel)
        uses_api_projection = vessel.get("display_position_lat") is not None or vessel.get("display_position_lon") is not None
        if status not in {"destroyed", "maintenance"} and not uses_api_projection:
            lat += math.sin(wave_tick + index) * 0.04
            lon += math.cos(wave_tick + index) * 0.12
        if status == "destroyed":
            color = [220, 38, 38, 235]
            effect = [220, 38, 38, 92]
            symbol = "ðŸ’¥"
            size = 30
        elif status == "damaged":
            color = [245, 158, 11, 235]
            effect = [245, 158, 11, 86]
            symbol = "âš ï¸"
            size = 28
        elif status == "maintenance":
            color = [148, 163, 184, 215]
            effect = [148, 163, 184, 45]
            symbol = "ðŸ”§"
            size = 24
        else:
            color = [34, 211, 238, 235]
            effect = [34, 211, 238, 52]
            symbol = "ðŸš¢"
            size = 28

        route = routes[index % len(routes)] if routes else None
        if route:
            origin = PORT_COORDS.get(route.get("origin_port"), (lat, lon))
            destination = PORT_COORDS.get(route.get("destination_port"), (lat, lon))
            angle = bearing_angle(origin[0], origin[1], destination[0], destination[1])
            route_name = f"{route.get('origin_port')} to {route.get('destination_port')}"
        else:
            angle = 90
            route_name = "Open sea"
        row = {
            "name": vessel.get("name", f"Vessel {index + 1}"),
            "lat": lat,
            "lon": lon,
            "status": status.title(),
            "route": route_name,
            "target": "",
            "eta": "",
            "speed": f"{float(vessel.get('speed_knots', 0) or 0):.1f} kn" if vessel.get("speed_knots") is not None else "",
            "motion_source": vessel.get("motion_source", "map projection"),
            "api_position": f"{vessel_api_lat(vessel):.4f}, {vessel_api_lon(vessel):.4f}",
            "color": color,
            "effect_color": effect,
            "radius": 145000 if status == "active" else 170000,
            "effect_radius": 330000 if status == "destroyed" else 240000,
            "symbol": symbol,
            "size": size,
            "angle": angle,
            "text_color": [5, 15, 30, 255] if status == "damaged" else [255, 255, 255, 255],
        }
        vessel_rows.append(row)
        if status not in {"destroyed", "maintenance"}:
            wake_rows.append({
                "name": row["name"],
                "path": vessel_wake_path({**vessel, "lat": lat, "lon": lon}, index, routes),
                "color": [191, 219, 254, 95] if status == "active" else [251, 191, 36, 120],
            })
    incident_rows = [row for row in vessel_rows if row["status"] in {"Damaged", "Destroyed"}]
    radar_rows = radar_ring_data(vessel_rows, threat_rows)
    radar_beams = radar_beam_data(vessel_rows, threat_rows)
    map_radar_rings, map_radar_beams = map_radar_overlay_data()
    scan_lock_rows, scan_paths, scan_labels = map_threat_scan_data(threat_rows, route_rows)
    layers = []
    if map_radar_rings:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=map_radar_rings,
            get_position="[lon, lat]",
            get_fill_color="color",
            get_radius="radius",
            stroked=True,
            get_line_color="line",
            line_width_min_pixels=1,
            pickable=False,
        ))
    if map_radar_beams:
        layers.append(pdk.Layer(
            "PathLayer",
            data=map_radar_beams,
            get_path="path",
            get_color="color",
            get_width="width",
            width_min_pixels=1,
            rounded=True,
            pickable=False,
        ))
    if scan_paths:
        layers.append(pdk.Layer(
            "PathLayer",
            data=scan_paths,
            get_path="path",
            get_color="color",
            get_width="width",
            width_min_pixels=1,
            rounded=True,
            pickable=False,
        ))
    if scan_lock_rows:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=scan_lock_rows,
            get_position="[lon, lat]",
            get_fill_color="color",
            get_radius="radius",
            stroked=True,
            get_line_color="line",
            line_width_min_pixels=2,
            pickable=True,
        ))
    if scan_labels:
        layers.append(pdk.Layer(
            "TextLayer",
            data=scan_labels,
            get_position="[lon, lat]",
            get_text="text",
            get_color="color",
            get_size="size",
            get_pixel_offset=[0, -48],
            get_alignment_baseline="'bottom'",
            get_text_anchor="'middle'",
            pickable=False,
        ))
    if route_rows:
        layers.append(pdk.Layer(
            "PathLayer",
            data=route_rows,
            get_path="path",
            get_color="glow_color",
            get_width=18,
            width_min_pixels=3,
            rounded=True,
        ))
        layers.append(pdk.Layer(
            "PathLayer",
            data=route_rows,
            get_path="path",
            get_color="color",
            get_width=6,
            width_min_pixels=2,
            rounded=True,
            pickable=True,
        ))
        layers.append(pdk.Layer(
            "TextLayer",
            data=route_rows,
            get_position="[mid_lon, mid_lat]",
            get_text="risk_text",
            get_color=[255, 255, 255, 235],
            get_size=13,
            get_pixel_offset=[0, -10],
            get_alignment_baseline="'bottom'",
            get_text_anchor="'middle'",
            pickable=True,
        ))
    if threat_paths:
        layers.append(pdk.Layer(
            "PathLayer",
            data=threat_paths,
            get_path="path",
            get_color="color",
            get_width=7,
            width_min_pixels=2,
            dash_size=3,
            gap_size=2,
            rounded=True,
        ))
    if radar_beams:
        layers.append(pdk.Layer(
            "PathLayer",
            data=radar_beams,
            get_path="path",
            get_color="color",
            get_width=4,
            width_min_pixels=1,
            rounded=True,
        ))
    if wake_rows:
        layers.append(pdk.Layer(
            "PathLayer",
            data=wake_rows,
            get_path="path",
            get_color="color",
            get_width=5,
            width_min_pixels=2,
            rounded=True,
        ))
    if port_rows:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=port_rows,
            get_position="[lon, lat]",
            get_fill_color="halo",
            get_radius=260000,
            stroked=True,
            get_line_color=[125, 211, 252, 140],
            line_width_min_pixels=1,
        ))
        layers.append(pdk.Layer(
            "TextLayer",
            data=port_rows,
            get_position="[lon, lat]",
            get_text="name",
            get_color=[226, 232, 240, 235],
            get_size=14,
            get_pixel_offset=[0, -28],
            get_alignment_baseline="'bottom'",
            get_text_anchor="'middle'",
        ))
    if incident_rows:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=incident_rows,
            get_position="[lon, lat]",
            get_fill_color="effect_color",
            get_radius="effect_radius",
            stroked=True,
            get_line_color=[255, 255, 255, 170],
            line_width_min_pixels=2,
        ))
    if threat_rows:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=threat_rows,
            get_position="[lon, lat]",
            get_fill_color="effect_color",
            get_radius="effect_radius",
            stroked=True,
            get_line_color=[255, 255, 255, 150],
            line_width_min_pixels=2,
            pickable=True,
        ))
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=threat_rows,
            get_position="[lon, lat]",
            get_fill_color="color",
            get_radius="radius",
            stroked=True,
            get_line_color=[255, 255, 255, 220],
            line_width_min_pixels=2,
            pickable=True,
        ))
        layers.append(pdk.Layer(
            "TextLayer",
            data=threat_rows,
            get_position="[lon, lat]",
            get_text="symbol",
            get_color="text_color",
            get_size=24,
            get_alignment_baseline="'center'",
            get_text_anchor="'middle'",
        ))
        layers.append(pdk.Layer(
            "TextLayer",
            data=threat_rows,
            get_position="[lon, lat]",
            get_text="eta",
            get_color=[254, 226, 226, 245],
            get_size=12,
            get_pixel_offset=[0, -34],
            get_alignment_baseline="'bottom'",
            get_text_anchor="'middle'",
        ))
    if radar_rows:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=radar_rows,
            get_position="[lon, lat]",
            get_fill_color="color",
            get_radius="radius",
            stroked=True,
            get_line_color="line",
            line_width_min_pixels=2,
            pickable=False,
        ))
    layers.append(pdk.Layer(
        "ScatterplotLayer",
        data=vessel_rows,
        get_position="[lon, lat]",
        get_fill_color="color",
        get_radius="radius",
        stroked=True,
        get_line_color=[255, 255, 255, 220],
        line_width_min_pixels=2,
        pickable=True,
    ))
    layers.append(pdk.Layer(
        "TextLayer",
        data=vessel_rows,
        get_position="[lon, lat]",
        get_text="symbol",
        get_color="text_color",
        get_size="size",
        get_angle="angle",
        get_alignment_baseline="'center'",
        get_text_anchor="'middle'",
        pickable=True,
    ))
    layers.append(pdk.Layer(
        "TextLayer",
        data=vessel_rows,
        get_position="[lon, lat]",
        get_text="name",
        get_color=[226, 232, 240, 240],
        get_size=12,
        get_pixel_offset=[0, 26],
        get_alignment_baseline="'top'",
        get_text_anchor="'middle'",
    ))
    return layers


def nautical_deck(vessels, routes, threats=None, decisions=None):
    layers = build_nautical_layers(vessels, routes, threats=threats, decisions=decisions)
    return pdk.Deck(
        map_style=MAP_STYLE,
        layers=layers,
        initial_view_state=pdk.ViewState(latitude=22, longitude=55, zoom=1.35, pitch=35, bearing=-12),
        tooltip={
            "html": "<b>{name}</b><br/>Status: {status}<br/>Route/Target: {route}{target}<br/>Speed: {speed}<br/>API point: {api_position}<br/>Motion: {motion_source}<br/>ETA: {eta}",
            "style": {"backgroundColor": "#07111f", "color": "#e5f7ff"},
        },
    )


def render_nautical_legend():
    st.markdown(
        """
        <div style="display:flex; gap:14px; flex-wrap:wrap; font-size:13px; margin:4px 0 10px 0;">
            <span><b style="color:#22d3ee;">â–² Active ship</b></span>
            <span><b style="color:#f59e0b;">! Damaged</b></span>
            <span><b style="color:#ef4444;">X Demolished</b></span>
            <span><b style="color:#f87171;">P Pirate approaching</b></span>
            <span><b style="color:#60a5fa;">S Storm cell</b></span>
            <span><b style="color:#67e8f9;">Radar rings/beams</b> live scan</span>
            <span><b style="color:#2dd4bf;">Teal route</b> low risk</span>
            <span><b style="color:#f59e0b;">Amber route</b> medium risk</span>
            <span><b style="color:#ef4444;">Red route</b> high risk</span>
            <span><b style="color:#bfdbfe;">Light trail</b> vessel wake</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_radar_scope(threats):
    threat_items = []
    for index, threat in enumerate(threats or []):
        threat_type = str(threat.get("type", "Threat")).lower()
        dot_class = "pirate" if "pirate" in threat_type else "storm"
        left = 22 + ((index * 31) % 58)
        top = 28 + ((index * 23) % 45)
        label = f"{threat.get('name')} -> {threat.get('target')} ({threat.get('eta_minutes')}m)"
        threat_items.append(
            f'<span class="radar-dot {dot_class}" style="left:{left}%; top:{top}%;" title="{label}"></span>'
        )
    html = f"""
    <style>
        .radar-card {{
            height: 300px;
            border-radius: 8px;
            border: 1px solid rgba(103, 232, 249, .35);
            background: radial-gradient(circle, rgba(8, 47, 73, .96), #020617 72%);
            position: relative;
            overflow: hidden;
            box-shadow: inset 0 0 34px rgba(34, 211, 238, .18);
        }}
        .radar-card:before {{
            content: "";
            position: absolute;
            width: 86%;
            aspect-ratio: 1;
            left: 7%;
            top: 7%;
            border-radius: 50%;
            background:
                repeating-radial-gradient(circle, transparent 0 28px, rgba(103,232,249,.18) 30px 31px),
                linear-gradient(90deg, transparent 49.5%, rgba(103,232,249,.25) 50%, transparent 50.5%),
                linear-gradient(0deg, transparent 49.5%, rgba(103,232,249,.25) 50%, transparent 50.5%);
        }}
        .radar-card:after {{
            content: "";
            position: absolute;
            width: 43%;
            height: 43%;
            left: 50%;
            top: 50%;
            transform-origin: 0 0;
            background: linear-gradient(35deg, rgba(34,211,238,.55), transparent 58%);
            animation: radarSweep 2.8s linear infinite;
            border-radius: 100% 0 0 0;
        }}
        .radar-title {{
            position: absolute;
            left: 16px;
            top: 12px;
            z-index: 2;
            color: #e0f2fe;
            font: 700 13px/1.2 Segoe UI, sans-serif;
            letter-spacing: 0;
        }}
        .radar-dot {{
            position: absolute;
            z-index: 3;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            transform: translate(-50%, -50%);
            box-shadow: 0 0 18px currentColor;
            animation: radarPulse 1.2s ease-in-out infinite;
        }}
        .radar-dot.pirate {{ background: #ef4444; color: #ef4444; }}
        .radar-dot.storm {{ background: #60a5fa; color: #60a5fa; }}
        .radar-list {{
            position: absolute;
            left: 14px;
            right: 14px;
            bottom: 12px;
            z-index: 4;
            color: #bae6fd;
            font: 12px/1.35 Segoe UI, sans-serif;
            background: rgba(2, 6, 23, .68);
            border: 1px solid rgba(103,232,249,.2);
            border-radius: 6px;
            padding: 8px;
        }}
        @keyframes radarSweep {{
            from {{ transform: rotate(0deg); }}
            to {{ transform: rotate(360deg); }}
        }}
        @keyframes radarPulse {{
            0%, 100% {{ transform: translate(-50%, -50%) scale(.8); opacity: .7; }}
            50% {{ transform: translate(-50%, -50%) scale(1.35); opacity: 1; }}
        }}
    </style>
    <div class="radar-card">
        <div class="radar-title">LIVE RADAR SCAN</div>
        {''.join(threat_items)}
        <div class="radar-list">
            {('<br>'.join(f"{threat.get('type')}: {threat.get('target')} ETA {threat.get('eta_minutes')} min" for threat in threats) if threats else 'No active moving threats')}
        </div>
    </div>
    """
    components.html(html, height=320)


def threat_scan_summary(threats, decisions=None):
    rows = []
    for threat in threats or []:
        severity = str(threat.get("severity", "medium")).lower()
        rows.append({
            "Signal": threat.get("name", threat.get("type", "Threat")),
            "Type": threat.get("type", "Threat"),
            "Target": threat.get("target", "Unknown"),
            "ETA": f"{threat.get('eta_minutes', '?')} min",
            "Severity": severity.title(),
            "Scan Status": "Locked" if severity == "high" else "Tracking",
        })

    for decision in decisions or []:
        score = float(decision.get("risk_score", decision.get("score", 0)) or 0)
        if score >= 7:
            rows.append({
                "Signal": decision.get("route", "High-risk route"),
                "Type": "Route Risk",
                "Target": decision.get("decision", "Review"),
                "ETA": "Live",
                "Severity": "High" if score < 8 else "Critical",
                "Scan Status": "Escalate",
            })
    return rows


def render_live_scan_hud(threats=None, decisions=None):
    scan_rows = threat_scan_summary(threats, decisions)
    locked = sum(1 for row in scan_rows if row["Scan Status"] in {"Locked", "Escalate"})
    tracking = max(len(scan_rows) - locked, 0)
    now_text = datetime.datetime.now().strftime("%H:%M:%S")
    status_text = (
        f"{locked} locked / {tracking} tracking"
        if scan_rows
        else "No active threat lock - sweep continuing"
    )
    html = f"""
    <style>
        .scan-hud {{
            position: relative;
            overflow: hidden;
            border: 1px solid rgba(103, 232, 249, .34);
            border-radius: 12px;
            padding: 14px 16px;
            margin: 6px 0 12px 0;
            background:
                linear-gradient(115deg, rgba(8, 47, 73, .84), rgba(2, 6, 23, .94)),
                repeating-linear-gradient(0deg, rgba(103,232,249,.08) 0 1px, transparent 1px 18px);
            box-shadow: 0 18px 42px rgba(2, 6, 23, .28), inset 0 0 28px rgba(34, 211, 238, .13);
            color: #dff9ff;
            font-family: Segoe UI, sans-serif;
        }}
        .scan-hud:before {{
            content: "";
            position: absolute;
            inset: -45% -10%;
            background: conic-gradient(from 0deg, transparent 0deg, rgba(34,211,238,.4) 18deg, transparent 42deg);
            animation: commandSweep 2.6s linear infinite;
            opacity: .7;
        }}
        .scan-hud:after {{
            content: "";
            position: absolute;
            left: -30%;
            top: 0;
            width: 30%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(125, 211, 252, .24), transparent);
            animation: scanLine 1.45s ease-in-out infinite;
        }}
        .scan-content {{
            position: relative;
            z-index: 2;
            display: flex;
            justify-content: space-between;
            gap: 16px;
            align-items: center;
        }}
        .scan-title {{
            font-weight: 800;
            letter-spacing: .08em;
            text-transform: uppercase;
            color: #67e8f9;
            font-size: 13px;
        }}
        .scan-status {{
            font-size: 22px;
            font-weight: 800;
            margin-top: 4px;
        }}
        .scan-meta {{
            color: #bae6fd;
            font-size: 13px;
            text-align: right;
        }}
        @keyframes commandSweep {{
            from {{ transform: rotate(0deg); }}
            to {{ transform: rotate(360deg); }}
        }}
        @keyframes scanLine {{
            0% {{ transform: translateX(0); opacity: 0; }}
            20%, 80% {{ opacity: 1; }}
            100% {{ transform: translateX(460%); opacity: 0; }}
        }}
    </style>
    <div class="scan-hud">
        <div class="scan-content">
            <div>
                <div class="scan-title">Continuous Radar Threat Scan</div>
                <div class="scan-status">{status_text}</div>
            </div>
            <div class="scan-meta">
                Sweep refresh: {now_text}<br>
                Radar mode: map + vessel proximity + route risk
            </div>
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)
    if scan_rows:
        st.dataframe(pd.DataFrame(scan_rows), use_container_width=True, hide_index=True)


def _apply_global_styles():
    st.markdown("""
    <style>
        :root {
            --shell-bg: #06111f;
            --panel-bg: rgba(8, 19, 34, 0.72);
            --panel-border: rgba(148, 163, 184, 0.2);
            --accent: #22d3ee;
            --accent-2: #facc15;
            --ink: #f8fafc;
            --muted: rgba(226, 232, 240, 0.72);
        }
        .stApp {
            background:
                radial-gradient(circle at 8% 8%, rgba(34, 211, 238, 0.2), transparent 28rem),
                radial-gradient(circle at 86% 12%, rgba(250, 204, 21, 0.14), transparent 24rem),
                radial-gradient(circle at 50% 92%, rgba(20, 184, 166, 0.13), transparent 30rem),
                linear-gradient(135deg, #06111f 0%, #0b1628 46%, #111827 100%);
            color: var(--ink);
        }
        .stApp::before {
            content: "";
            position: fixed;
            inset: 0;
            pointer-events: none;
            opacity: 0.28;
            background-image:
                linear-gradient(rgba(148, 163, 184, 0.05) 1px, transparent 1px),
                linear-gradient(90deg, rgba(148, 163, 184, 0.05) 1px, transparent 1px);
            background-size: 42px 42px;
            mask-image: linear-gradient(to bottom, black, transparent 88%);
            z-index: 0;
        }
        .block-container {
            max-width: 1440px;
            padding-top: 1.05rem;
            padding-bottom: 2rem;
            position: relative;
            z-index: 1;
        }
        [data-testid="stSidebar"] {
            background:
                radial-gradient(circle at top, rgba(34, 211, 238, 0.12), transparent 16rem),
                linear-gradient(180deg, rgba(2, 6, 23, 0.96), rgba(15, 23, 42, 0.92));
            border-right: 1px solid rgba(125, 211, 252, 0.16);
            box-shadow: 18px 0 55px rgba(2, 6, 23, 0.28);
        }
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3 {
            color: #e0f2fe;
        }
        h1, h2, h3 {
            letter-spacing: -0.035em;
            color: #f8fafc;
        }
        h1 {
            font-weight: 900 !important;
            text-shadow: 0 16px 38px rgba(14, 165, 233, 0.22);
        }
        [data-testid="stMetric"] {
            background:
                radial-gradient(circle at top right, rgba(34, 211, 238, 0.12), transparent 12rem),
                rgba(8, 19, 34, 0.72);
            border: 1px solid rgba(125, 211, 252, 0.16);
            border-radius: 18px;
            padding: 0.78rem;
            box-shadow: 0 16px 42px rgba(2, 6, 23, 0.18);
        }
        [data-testid="stMetricValue"] {
            color: #f8fafc;
            font-weight: 850;
        }
        [data-testid="stMetricLabel"] {
            color: rgba(226, 232, 240, 0.7);
        }
        [data-testid="stDataFrame"] {
            border-radius: 16px;
            overflow: hidden;
            border: 1px solid rgba(148, 163, 184, 0.12);
            box-shadow: 0 18px 45px rgba(2, 6, 23, 0.16);
        }
        [data-testid="stExpander"] {
            border: 1px solid rgba(125, 211, 252, 0.14);
            border-radius: 16px;
            background: rgba(15, 23, 42, 0.38);
            box-shadow: 0 12px 34px rgba(2, 6, 23, 0.12);
        }
        iframe {
            border-radius: 20px;
            border: 1px solid rgba(125, 211, 252, 0.12);
            box-shadow: 0 18px 55px rgba(2, 6, 23, 0.24);
        }
        div[data-testid="stHorizontalBlock"] {
            gap: 0.65rem;
        }
        .stButton > button {
            border-radius: 999px;
            min-height: 2.45rem;
            border: 1px solid rgba(125, 211, 252, 0.26);
            background:
                linear-gradient(135deg, rgba(14, 165, 233, 0.16), rgba(15, 23, 42, 0.62));
            box-shadow: 0 12px 30px rgba(2, 6, 23, 0.18);
            transition: transform 140ms ease, border-color 140ms ease, box-shadow 140ms ease;
        }
        .stButton > button:hover {
            transform: translateY(-1px);
            border-color: rgba(34, 211, 238, 0.72);
            box-shadow: 0 18px 38px rgba(14, 165, 233, 0.18);
        }
        [data-baseweb="tab-list"] {
            gap: 0.35rem;
            border-bottom: 1px solid rgba(148, 163, 184, 0.14);
        }
        [data-baseweb="tab"] {
            border-radius: 999px 999px 0 0;
            padding: 0.45rem 0.8rem;
            color: rgba(226, 232, 240, 0.76);
        }
        [aria-selected="true"][data-baseweb="tab"] {
            color: #f8fafc;
            background: rgba(34, 211, 238, 0.1);
            border: 1px solid rgba(125, 211, 252, 0.18);
            border-bottom-color: transparent;
        }
        [data-baseweb="input"] > div,
        [data-baseweb="select"] > div,
        textarea {
            border-radius: 14px !important;
            border-color: rgba(125, 211, 252, 0.18) !important;
            background-color: rgba(15, 23, 42, 0.5) !important;
        }
        .app-topbar-anchor {
            margin-top: -0.4rem;
        }
        .topbar-card {
            border-radius: 999px;
            border: 1px solid rgba(125, 211, 252, 0.2);
            background:
                linear-gradient(135deg, rgba(8, 47, 73, 0.56), rgba(15, 23, 42, 0.72));
            padding: 0.48rem 0.72rem;
            box-shadow: 0 14px 35px rgba(2, 6, 23, 0.2);
            color: rgba(226, 232, 240, 0.78);
        }
        .topbar-card b {
            color: #f8fafc;
        }
        .topbar-pill {
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 0.12rem 0.48rem;
            margin-right: 0.42rem;
            background: rgba(34, 197, 94, 0.13);
            border: 1px solid rgba(74, 222, 128, 0.26);
            color: #bbf7d0;
            font-size: 0.75rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.045em;
        }
        .sidebar-brand {
            border-radius: 20px;
            border: 1px solid rgba(125, 211, 252, 0.18);
            background:
                radial-gradient(circle at top left, rgba(34, 211, 238, 0.18), transparent 14rem),
                rgba(15, 23, 42, 0.62);
            padding: 0.85rem;
            margin: 0.3rem 0 0.9rem 0;
        }
        .sidebar-brand b {
            color: #f8fafc;
            display: block;
            font-size: 1.02rem;
        }
        .sidebar-brand span {
            color: rgba(226, 232, 240, 0.68);
            font-size: 0.8rem;
        }
        .dashboard-hero {
            position: relative;
            overflow: hidden;
            border-radius: 30px;
            border: 1px solid rgba(125, 211, 252, 0.22);
            background:
                radial-gradient(circle at 18% 8%, rgba(34, 211, 238, 0.26), transparent 18rem),
                radial-gradient(circle at 92% 10%, rgba(250, 204, 21, 0.16), transparent 20rem),
                linear-gradient(135deg, rgba(2, 6, 23, 0.92), rgba(8, 47, 73, 0.7));
            padding: 1.15rem;
            margin: 0.25rem 0 1rem 0;
            box-shadow: 0 28px 75px rgba(2, 6, 23, 0.34);
        }
        .dashboard-hero::after,
        .captain-hero::after,
        .tower-hero::after {
            content: "";
            position: absolute;
            inset: auto -18% -46% auto;
            width: 34rem;
            height: 34rem;
            border-radius: 50%;
            background: radial-gradient(circle, rgba(34, 211, 238, 0.12), transparent 65%);
            animation: commandFloat 8s ease-in-out infinite alternate;
        }
        .dashboard-hero h2 {
            margin: 0.25rem 0 0.35rem 0;
            font-size: clamp(1.75rem, 3.8vw, 3.25rem);
            letter-spacing: -0.05em;
        }
        .dashboard-hero p {
            margin: 0;
            max-width: 920px;
            color: rgba(226, 232, 240, 0.76);
        }
        .hero-kicker {
            display: inline-flex;
            border-radius: 999px;
            padding: 0.18rem 0.62rem;
            border: 1px solid rgba(125, 211, 252, 0.24);
            background: rgba(14, 165, 233, 0.12);
            color: #bae6fd;
            font-size: 0.78rem;
            font-weight: 850;
            text-transform: uppercase;
            letter-spacing: 0.055em;
        }
        @keyframes commandFloat {
            from { transform: translate3d(0, 0, 0) scale(1); opacity: 0.78; }
            to { transform: translate3d(-2rem, -1.2rem, 0) scale(1.08); opacity: 1; }
        }
        [data-testid="stChatMessage"] {
            border-radius: 18px;
            border: 1px solid rgba(148, 163, 184, 0.14);
        }
        .main-header {
            font-size: 2.5em;
            color: #e0f2fe;
            text-align: center;
            margin-bottom: 20px;
        }
        .metric-card {
            background:
                radial-gradient(circle at top right, rgba(34, 211, 238, 0.12), transparent 12rem),
                rgba(15, 23, 42, 0.66);
            border: 1px solid rgba(125, 211, 252, 0.18);
            padding: 10px;
            border-radius: 16px;
            text-align: center;
        }
        .security-card {
            background:
                linear-gradient(135deg, rgba(15, 23, 42, 0.86), rgba(8, 47, 73, 0.58)),
                radial-gradient(circle at top right, rgba(56, 189, 248, 0.18), transparent 18rem);
            border: 1px solid rgba(125, 211, 252, 0.22);
            border-radius: 22px;
            padding: 1rem;
            box-shadow: 0 18px 45px rgba(0, 0, 0, 0.18);
        }
        .security-card h3 {
            margin: 0 0 0.35rem 0;
        }
        .security-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            border-radius: 999px;
            padding: 0.28rem 0.7rem;
            margin: 0.15rem 0.2rem 0.15rem 0;
            background: rgba(14, 165, 233, 0.12);
            border: 1px solid rgba(125, 211, 252, 0.2);
            color: #e0f2fe;
            font-size: 0.83rem;
        }
        .security-warning {
            border-left: 3px solid #f97316;
            padding: 0.7rem 0.9rem;
            border-radius: 14px;
            background: rgba(249, 115, 22, 0.1);
        }
        .utility-panel {
            border: 1px solid rgba(148, 163, 184, 0.18);
            background: rgba(15, 23, 42, 0.58);
            border-radius: 8px;
            padding: 0.85rem;
            margin: 0.4rem 0 0.85rem 0;
        }
        .notification-card {
            border-left: 4px solid var(--note-color);
            border-radius: 8px;
            border-top: 1px solid rgba(148, 163, 184, 0.16);
            border-right: 1px solid rgba(148, 163, 184, 0.16);
            border-bottom: 1px solid rgba(148, 163, 184, 0.16);
            background: rgba(15, 23, 42, 0.62);
            padding: 0.82rem 0.95rem;
            margin-bottom: 0.65rem;
        }
        .notification-card b {
            color: #f8fafc;
        }
        .inbox-card {
            border-radius: 18px;
            border: 1px solid rgba(125, 211, 252, 0.18);
            background:
                radial-gradient(circle at top right, rgba(56, 189, 248, 0.12), transparent 18rem),
                linear-gradient(135deg, rgba(15, 23, 42, 0.82), rgba(8, 47, 73, 0.56));
            padding: 0.95rem;
            margin-bottom: 0.78rem;
            box-shadow: 0 14px 35px rgba(2, 6, 23, 0.18);
        }
        .inbox-card h4 {
            margin: 0.35rem 0;
        }
        .inbox-route {
            color: rgba(226, 232, 240, 0.72);
            font-size: 0.83rem;
            margin-top: 0.28rem;
        }
        .notification-meta {
            color: rgba(226, 232, 240, 0.68);
            font-size: 0.82rem;
            margin-top: 0.3rem;
        }
        .severity-chip {
            display: inline-block;
            border: 1px solid var(--chip-color);
            color: #f8fafc;
            background: color-mix(in srgb, var(--chip-color) 22%, transparent);
            border-radius: 999px;
            padding: 0.12rem 0.5rem;
            margin-right: 0.35rem;
            font-size: 0.76rem;
            font-weight: 700;
        }
        .settings-band {
            border-radius: 8px;
            border: 1px solid rgba(125, 211, 252, 0.2);
            background: linear-gradient(135deg, rgba(8, 47, 73, 0.54), rgba(15, 23, 42, 0.7));
            padding: 0.9rem;
            margin: 0.35rem 0 0.9rem 0;
        }
        .solver-hero {
            border: 1px solid rgba(125, 211, 252, 0.24);
            border-radius: 18px;
            padding: 1rem;
            margin: 0.25rem 0 1rem 0;
            background:
                radial-gradient(circle at top left, rgba(34, 211, 238, 0.18), transparent 18rem),
                linear-gradient(135deg, rgba(8, 47, 73, 0.84), rgba(15, 23, 42, 0.76));
            box-shadow: 0 18px 42px rgba(2, 6, 23, 0.22);
        }
        .solver-hero b {
            color: #f8fafc;
        }
        .solver-hero span {
            color: rgba(226, 232, 240, 0.76);
            display: block;
            margin-top: 0.25rem;
        }
        .solver-answer {
            border-radius: 18px;
            border: 1px solid rgba(148, 163, 184, 0.18);
            background: rgba(15, 23, 42, 0.64);
            padding: 1rem;
            margin: 0.8rem 0;
        }
        .solver-answer h3 {
            margin: 0.25rem 0 0 0;
        }
        .solver-chip {
            display: inline-block;
            border-radius: 999px;
            padding: 0.16rem 0.58rem;
            background: rgba(34, 211, 238, 0.13);
            border: 1px solid rgba(125, 211, 252, 0.22);
            color: #bae6fd;
            font-size: 0.78rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        .action-step {
            border-left: 3px solid #22d3ee;
            background: rgba(8, 47, 73, 0.34);
            border-radius: 12px;
            padding: 0.62rem 0.75rem;
            margin-bottom: 0.48rem;
        }
        .mission-card {
            position: relative;
            overflow: hidden;
            border-radius: 18px;
            border: 1px solid rgba(125, 211, 252, 0.22);
            background:
                radial-gradient(circle at top right, rgba(34, 211, 238, 0.16), transparent 16rem),
                linear-gradient(135deg, rgba(15, 23, 42, 0.82), rgba(8, 47, 73, 0.58));
            padding: 0.9rem;
            min-height: 8.2rem;
        }
        .mission-card b {
            color: #f8fafc;
        }
        .mission-card small {
            display: block;
            color: rgba(226, 232, 240, 0.7);
            margin-top: 0.25rem;
        }
        .mission-score {
            font-size: 1.9rem;
            font-weight: 850;
            color: #67e8f9;
            margin-top: 0.35rem;
        }
        .incident-card {
            border-left: 4px solid var(--incident-color);
            border-radius: 14px;
            border-top: 1px solid rgba(148, 163, 184, 0.16);
            border-right: 1px solid rgba(148, 163, 184, 0.16);
            border-bottom: 1px solid rgba(148, 163, 184, 0.16);
            background: rgba(15, 23, 42, 0.58);
            padding: 0.75rem 0.9rem;
            margin-bottom: 0.6rem;
        }
        .vessel-intel-card {
            border-radius: 18px;
            border: 1px solid rgba(45, 212, 191, 0.24);
            background:
                linear-gradient(135deg, rgba(20, 184, 166, 0.14), rgba(15, 23, 42, 0.72));
            padding: 0.9rem;
            margin: 0.65rem 0;
        }
        .tower-hero {
            position: relative;
            overflow: hidden;
            border-radius: 26px;
            border: 1px solid rgba(45, 212, 191, 0.24);
            background:
                radial-gradient(circle at 14% 12%, rgba(34, 211, 238, 0.24), transparent 20rem),
                radial-gradient(circle at 86% 18%, rgba(250, 204, 21, 0.14), transparent 18rem),
                linear-gradient(135deg, rgba(2, 6, 23, 0.92), rgba(8, 47, 73, 0.72));
            padding: 1.1rem;
            margin-bottom: 1rem;
            box-shadow: 0 24px 65px rgba(2, 6, 23, 0.32);
        }
        .tower-hero h2 {
            margin: 0.2rem 0 0.35rem 0;
            font-size: clamp(1.55rem, 3vw, 2.7rem);
        }
        .tower-hero p {
            margin: 0;
            color: rgba(226, 232, 240, 0.76);
            max-width: 860px;
        }
        .tower-badge {
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 0.18rem 0.58rem;
            background: rgba(20, 184, 166, 0.13);
            border: 1px solid rgba(94, 234, 212, 0.28);
            color: #99f6e4;
            font-weight: 800;
            font-size: 0.76rem;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }
        .tower-decision {
            border-radius: 18px;
            border: 1px solid rgba(250, 204, 21, 0.22);
            background:
                radial-gradient(circle at top right, rgba(250, 204, 21, 0.14), transparent 15rem),
                rgba(15, 23, 42, 0.68);
            padding: 0.95rem;
            margin-bottom: 0.85rem;
        }
        .tower-plan-card {
            border-left: 4px solid var(--tower-color);
            border-radius: 16px;
            border-top: 1px solid rgba(148, 163, 184, 0.16);
            border-right: 1px solid rgba(148, 163, 184, 0.16);
            border-bottom: 1px solid rgba(148, 163, 184, 0.16);
            background: rgba(15, 23, 42, 0.62);
            padding: 0.85rem 0.95rem;
            margin-bottom: 0.65rem;
        }
        .tower-plan-card b {
            color: #f8fafc;
        }
        .tower-plan-meta {
            color: rgba(226, 232, 240, 0.68);
            font-size: 0.82rem;
            margin-top: 0.28rem;
        }
        .captain-hero {
            position: relative;
            overflow: hidden;
            border-radius: 30px;
            border: 1px solid rgba(250, 204, 21, 0.26);
            background:
                radial-gradient(circle at 12% 18%, rgba(250, 204, 21, 0.24), transparent 18rem),
                radial-gradient(circle at 88% 14%, rgba(14, 165, 233, 0.22), transparent 20rem),
                linear-gradient(135deg, rgba(2, 6, 23, 0.94), rgba(30, 41, 59, 0.76));
            padding: 1.15rem;
            margin: 0.35rem 0 1rem 0;
            box-shadow: 0 26px 70px rgba(2, 6, 23, 0.36);
        }
        .captain-hero h2 {
            margin: 0.24rem 0 0.35rem 0;
            font-size: clamp(1.8rem, 4vw, 3.4rem);
            letter-spacing: -0.04em;
        }
        .captain-hero p {
            margin: 0;
            max-width: 920px;
            color: rgba(226, 232, 240, 0.78);
        }
        .captain-badge {
            display: inline-flex;
            border-radius: 999px;
            padding: 0.2rem 0.68rem;
            border: 1px solid rgba(250, 204, 21, 0.36);
            background: rgba(250, 204, 21, 0.12);
            color: #fde68a;
            font-weight: 850;
            font-size: 0.78rem;
            letter-spacing: 0.055em;
            text-transform: uppercase;
        }
        .captain-order-card {
            border-left: 4px solid var(--captain-color);
            border-radius: 18px;
            border-top: 1px solid rgba(148, 163, 184, 0.16);
            border-right: 1px solid rgba(148, 163, 184, 0.16);
            border-bottom: 1px solid rgba(148, 163, 184, 0.16);
            background:
                radial-gradient(circle at top right, color-mix(in srgb, var(--captain-color) 13%, transparent), transparent 15rem),
                rgba(15, 23, 42, 0.66);
            padding: 0.9rem 1rem;
            margin-bottom: 0.7rem;
        }
        .captain-order-card b {
            color: #f8fafc;
        }
        .captain-meta {
            margin-top: 0.28rem;
            color: rgba(226, 232, 240, 0.68);
            font-size: 0.83rem;
        }
        .fingerprint-panel {
            display: flex;
            align-items: center;
            gap: 0.85rem;
            margin: 0.4rem 0 0.7rem 0;
            padding: 0.8rem;
            border-radius: 8px;
            border: 1px solid rgba(20, 184, 166, 0.28);
            background:
                linear-gradient(135deg, rgba(20, 184, 166, 0.12), rgba(15, 23, 42, 0.55));
        }
        .fingerprint-ring {
            display: grid;
            place-items: center;
            width: 3.5rem;
            height: 3.5rem;
            border-radius: 50%;
            border: 2px solid rgba(45, 212, 191, 0.72);
            color: #99f6e4;
            font-size: 0.72rem;
            letter-spacing: 0;
            box-shadow: 0 0 22px rgba(20, 184, 166, 0.2) inset;
        }
        .login-shell {
            max-width: 1120px;
            margin: 4vh auto 0 auto;
            padding: 2rem 0;
            position: relative;
        }
        .login-shell::before {
            content: "";
            position: absolute;
            top: -20%;
            left: 50%;
            transform: translateX(-50%);
            width: 60%;
            height: 140%;
            background: radial-gradient(ellipse at top, rgba(34, 211, 238, 0.15), transparent 70%);
            z-index: -1;
            pointer-events: none;
        }
        .login-title {
            font-size: clamp(2.5rem, 5vw, 4rem);
            font-weight: 900;
            line-height: 1.1;
            margin-bottom: 0.8rem;
            background: linear-gradient(to right, #e0f2fe, #38bdf8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            text-shadow: 0 4px 24px rgba(56, 189, 248, 0.25);
        }
        .login-subtitle {
            color: rgba(226, 232, 240, 0.85);
            max-width: 760px;
            margin-bottom: 1.5rem;
            font-size: 1.1rem;
            line-height: 1.6;
        }
        .login-badge {
            display: inline-flex;
            border-radius: 999px;
            padding: 0.35rem 0.85rem;
            border: 1px solid rgba(125, 211, 252, 0.3);
            background: rgba(14, 165, 233, 0.15);
            color: #bae6fd;
            font-size: 0.85rem;
            font-weight: 800;
            margin-bottom: 1rem;
            box-shadow: 0 0 15px rgba(14, 165, 233, 0.2);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        .login-panel {
            border-radius: 24px;
            border: 1px solid rgba(125, 211, 252, 0.3);
            background:
                radial-gradient(circle at top left, rgba(34, 211, 238, 0.25), transparent 22rem),
                linear-gradient(135deg, rgba(15, 23, 42, 0.9), rgba(8, 47, 73, 0.7));
            padding: 1.5rem;
            box-shadow: 0 28px 65px rgba(2, 6, 23, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.1);
            position: relative;
            overflow: hidden;
        }
        .login-panel::after {
            content: "";
            position: absolute;
            inset: 0;
            background: linear-gradient(120deg, transparent, rgba(255, 255, 255, 0.03), transparent);
            transform: translateX(-100%);
            animation: shimmer 3s infinite;
        }
        @keyframes shimmer {
            100% { transform: translateX(100%); }
        }
        .login-panel h3 {
            margin: 0.15rem 0 0.5rem 0;
            color: #f8fafc;
            font-size: 1.4rem;
        }
        .login-panel p {
            color: rgba(226, 232, 240, 0.8);
            margin: 0.2rem 0 0.9rem 0;
            font-size: 1.05rem;
            line-height: 1.5;
        }
        .login-kpi {
            border-radius: 18px;
            border: 1px solid rgba(148, 163, 184, 0.2);
            background: rgba(15, 23, 42, 0.6);
            padding: 1rem;
            min-height: 6.5rem;
            transition: transform 0.2s, box-shadow 0.2s;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
        }
        .login-kpi:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(34, 211, 238, 0.15);
            border-color: rgba(125, 211, 252, 0.4);
        }
        .login-kpi b {
            color: #f8fafc;
            font-size: 1.1rem;
            display: block;
            margin-bottom: 0.3rem;
        }
        .login-kpi span {
            display: block;
            color: rgba(226, 232, 240, 0.75);
            font-size: 0.9rem;
            margin-top: 0.25rem;
            line-height: 1.4;
        }
        .login-choice {
            border-radius: 12px;
            border: 1px solid rgba(148, 163, 184, 0.25);
            background: rgba(15, 23, 42, 0.65);
            padding: 1.2rem;
            min-height: 8.5rem;
            transition: all 0.2s;
        }
        .login-choice:hover {
            border-color: rgba(125, 211, 252, 0.4);
            background: rgba(15, 23, 42, 0.8);
        }
        .login-choice b {
            color: #f8fafc;
        }
        .login-choice p {
            color: rgba(226, 232, 240, 0.72);
            margin: 0.35rem 0 0 0;
            font-size: 0.92rem;
        }
        .footer {
            text-align: center;
            margin-top: 2.25rem;
            color: rgba(226, 232, 240, 0.56);
            border-top: 1px solid rgba(148, 163, 184, 0.12);
            padding-top: 1rem;
        }
        /* Submission polish: calmer, sharper operational UI */
        .stApp {
            background:
                linear-gradient(rgba(148, 163, 184, 0.035) 1px, transparent 1px),
                linear-gradient(90deg, rgba(148, 163, 184, 0.035) 1px, transparent 1px),
                linear-gradient(135deg, #06111f 0%, #101923 54%, #141827 100%) !important;
            background-size: 40px 40px, 40px 40px, auto !important;
        }
        .stApp::before,
        .dashboard-hero::after,
        .captain-hero::after,
        .tower-hero::after,
        .login-shell::before {
            display: none !important;
        }
        .block-container {
            max-width: 1360px !important;
            padding-top: 0.85rem !important;
        }
        h1, h2, h3 {
            letter-spacing: 0 !important;
            text-shadow: none !important;
        }
        h1 {
            font-size: 1.9rem !important;
            font-weight: 820 !important;
            margin-bottom: 0.45rem !important;
        }
        h2 {
            font-size: 1.35rem !important;
        }
        h3 {
            font-size: 1.08rem !important;
        }
        .project-identity {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            align-items: center;
            gap: 1rem;
            border: 1px solid rgba(45, 212, 191, 0.24);
            background: linear-gradient(135deg, rgba(15, 23, 42, 0.9), rgba(8, 47, 73, 0.55));
            border-radius: 8px;
            padding: 1rem 1.1rem;
            margin: 0.2rem 0 0.9rem 0;
        }
        .project-identity h1 {
            margin: 0.18rem 0 0.24rem 0 !important;
            font-size: 1.72rem !important;
            line-height: 1.15 !important;
            color: #f8fafc !important;
        }
        .project-identity p {
            margin: 0 !important;
            color: rgba(226, 232, 240, 0.78);
            line-height: 1.45;
        }
        .project-kicker {
            display: inline-flex;
            width: fit-content;
            border-radius: 6px;
            padding: 0.14rem 0.48rem;
            color: #99f6e4;
            border: 1px solid rgba(45, 212, 191, 0.3);
            background: rgba(20, 184, 166, 0.12);
            font-size: 0.73rem;
            font-weight: 850;
            text-transform: uppercase;
            letter-spacing: 0;
        }
        .project-section-chip {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 8rem;
            border-radius: 8px;
            padding: 0.7rem 0.85rem;
            border: 1px solid rgba(148, 163, 184, 0.18);
            background: rgba(2, 6, 23, 0.28);
            color: #e2e8f0;
            text-align: center;
            font-weight: 780;
        }
        [data-testid="stSidebar"] {
            background: #07111f !important;
            border-right: 1px solid rgba(148, 163, 184, 0.18) !important;
            box-shadow: none !important;
        }
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
        [data-testid="stSidebar"] label {
            color: rgba(226, 232, 240, 0.78) !important;
        }
        [data-testid="stAlert"] {
            border-radius: 8px !important;
            border: 1px solid rgba(148, 163, 184, 0.18) !important;
            box-shadow: none !important;
        }
        [data-testid="stVerticalBlock"] {
            gap: 0.72rem !important;
        }
        div[data-testid="stHorizontalBlock"] {
            align-items: stretch !important;
        }
        .sidebar-brand,
        .topbar-card,
        .topbar-glass,
        .project-identity,
        .project-section-chip,
        [data-testid="stMetric"],
        [data-testid="stExpander"],
        [data-testid="stDataFrame"],
        iframe,
        .dashboard-hero,
        .captain-hero,
        .tower-hero,
        .security-card,
        .metric-card,
        .utility-panel,
        .notification-card,
        .inbox-card,
        .settings-band,
        .solver-hero,
        .solver-answer,
        .action-step,
        .mission-card,
        .incident-card,
        .vessel-intel-card,
        .tower-decision,
        .tower-plan-card,
        .captain-order-card,
        .login-panel,
        .login-kpi,
        .login-choice,
        .role-entry-card,
        .form-container,
        .settings-band-new,
        .fleet-map {
            border-radius: 8px !important;
            box-shadow: none !important;
        }
        .dashboard-hero,
        .captain-hero,
        .tower-hero,
        .security-card,
        .inbox-card,
        .solver-hero,
        .mission-card,
        .vessel-intel-card,
        .login-panel,
        .role-entry-card,
        .form-container {
            background: linear-gradient(135deg, rgba(15, 23, 42, 0.86), rgba(8, 47, 73, 0.5)) !important;
            border-color: rgba(148, 163, 184, 0.2) !important;
        }
        .topbar-glass,
        .topbar-card,
        .settings-band,
        .settings-band-new,
        .utility-panel {
            background: rgba(15, 23, 42, 0.66) !important;
            border-color: rgba(148, 163, 184, 0.2) !important;
        }
        [data-testid="stMetric"] {
            background: rgba(15, 23, 42, 0.62) !important;
            border-color: rgba(148, 163, 184, 0.18) !important;
            padding: 0.65rem 0.7rem !important;
            height: 100% !important;
        }
        [data-testid="stMetricLabel"] {
            font-size: 0.76rem !important;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.38rem !important;
            line-height: 1.15 !important;
        }
        .stButton > button {
            border-radius: 8px !important;
            min-height: 2.3rem !important;
            box-shadow: none !important;
            background: rgba(15, 23, 42, 0.72) !important;
            border: 1px solid rgba(125, 211, 252, 0.28) !important;
            justify-content: center !important;
            white-space: normal !important;
        }
        .stButton > button:hover {
            transform: none !important;
            border-color: rgba(45, 212, 191, 0.7) !important;
            background: rgba(8, 47, 73, 0.76) !important;
            box-shadow: none !important;
        }
        [data-baseweb="tab"] {
            border-radius: 8px 8px 0 0 !important;
            letter-spacing: 0 !important;
        }
        [data-testid="stSegmentedControl"] label {
            border-radius: 8px !important;
            min-height: 2.15rem !important;
        }
        [data-testid="stSegmentedControl"] label[data-baseweb="radio"] {
            background: rgba(15, 23, 42, 0.58) !important;
            border: 1px solid rgba(148, 163, 184, 0.18) !important;
        }
        [data-baseweb="input"] > div,
        [data-baseweb="select"] > div,
        textarea {
            border-radius: 8px !important;
            background-color: rgba(15, 23, 42, 0.7) !important;
        }
        .topbar-pill,
        .security-pill,
        .severity-chip,
        .project-kicker,
        .hero-kicker,
        .captain-badge,
        .tower-badge,
        .solver-chip,
        .login-badge,
        .login-badge-new,
        .role-kicker,
        .login-status-pill {
            border-radius: 6px !important;
            letter-spacing: 0 !important;
        }
        .dashboard-hero h2,
        .captain-hero h2,
        .tower-hero h2 {
            font-size: 1.75rem !important;
            letter-spacing: 0 !important;
        }
        .dashboard-hero p,
        .captain-hero p,
        .tower-hero p {
            max-width: 980px !important;
            color: rgba(226, 232, 240, 0.82) !important;
        }
        .mission-score {
            font-size: 1.45rem !important;
        }
        .footer {
            margin-top: 1.4rem !important;
        }
        .sidebar .sidebar-content {
            background-color: transparent;
        }
        @media (max-width: 760px) {
            .block-container {
                padding-left: 0.75rem;
                padding-right: 0.75rem;
                padding-top: 0.75rem;
            }
            .project-identity {
                grid-template-columns: 1fr;
                gap: 0.65rem;
                padding: 0.8rem;
            }
            .project-identity h1 {
                font-size: 1.42rem !important;
            }
            .project-section-chip {
                width: 100%;
                min-width: 0;
                justify-content: flex-start;
                text-align: left;
            }
            h1 {
                font-size: 1.65rem !important;
                line-height: 1.15 !important;
            }
            h2, h3 {
                font-size: 1.1rem !important;
            }
            [data-testid="stMetric"] {
                padding: 0.55rem;
            }
            [data-testid="stMetricValue"] {
                font-size: 1.25rem !important;
            }
            .stButton > button {
                min-height: 2.15rem;
                padding-left: 0.55rem;
                padding-right: 0.55rem;
                font-size: 0.82rem;
            }
            .login-shell {
                margin-top: 0.4rem;
            }
            .login-choice, .utility-panel, .settings-band, .notification-card {
                padding: 0.7rem;
            }
            .topbar-glass {
                padding: 0.55rem 0.65rem;
            }
            .topbar-title-stack {
                width: 100%;
                min-width: 0;
            }
            .topbar-title {
                font-size: 0.95rem;
            }
            .topbar-subtitle {
                font-size: 0.72rem;
            }
            .topbar-meta {
                font-size: 0.76rem;
                gap: 0.35rem;
            }
            .login-panel {
                padding: 0.75rem;
                border-radius: 16px;
            }
            .login-kpi {
                min-height: auto;
            }
            .solver-hero, .solver-answer {
                padding: 0.75rem;
            }
            .mission-card, .incident-card, .vessel-intel-card {
                padding: 0.7rem;
            }
            .tower-hero, .tower-decision, .tower-plan-card, .captain-hero, .captain-order-card {
                padding: 0.75rem;
                border-radius: 16px;
            }
            .notification-card {
                font-size: 0.9rem;
            }
            .security-pill {
                font-size: 0.76rem;
                padding: 0.22rem 0.55rem;
            }
            .fingerprint-panel {
                align-items: flex-start;
            }
            .fingerprint-ring {
                width: 3rem;
                height: 3rem;
                flex: 0 0 3rem;
            }
            [data-testid="stDataFrame"] {
                font-size: 0.78rem;
            }
            .stTabs [data-baseweb="tab-list"] {
                overflow-x: auto;
                white-space: nowrap;
            }
            iframe {
                max-height: 68vh;
            }
            .footer {
                margin-top: 1.5rem;
                font-size: 0.8rem;
            }
        }
    </style>
    """, unsafe_allow_html=True)

def init_fleet_incident_state():
    if "destroyed_ship_ids" not in st.session_state:
        st.session_state.destroyed_ship_ids = set()
    if "damaged_ship_ids" not in st.session_state:
        st.session_state.damaged_ship_ids = set()
    if "fleet_incident_log" not in st.session_state:
        st.session_state.fleet_incident_log = []


def vessel_key(vessel, index):
    return vessel.get("id", index)


def vessel_condition(vessel, index):
    key = vessel_key(vessel, index)
    if key in st.session_state.destroyed_ship_ids:
        return "destroyed"
    if key in st.session_state.damaged_ship_ids:
        return "damaged"
    return vessel.get("status", "active")


def apply_fleet_incident(vessels, incident_type, target_index):
    if not vessels:
        return
    target = vessels[target_index]
    key = vessel_key(target, target_index)
    name = target.get("name", f"Vessel {target_index + 1}")
    if incident_type == "Storm":
        st.session_state.damaged_ship_ids.add(key)
        message = f"Storm impact near {name}: vessel damaged, speed reduced, monitoring required."
    elif incident_type == "Pirate Attack":
        st.session_state.destroyed_ship_ids.add(key)
        st.session_state.damaged_ship_ids.discard(key)
        message = f"Pirate attack near {name}: vessel demolished, stop route and alert port security."
    else:
        st.session_state.destroyed_ship_ids.add(key)
        st.session_state.damaged_ship_ids.discard(key)
        message = f"Collision reported for {name}: vessel demolished, trigger rescue and port alerts."
    st.session_state.fleet_incident_log.insert(0, {
        "Time": datetime.datetime.now().strftime("%H:%M:%S"),
        "Incident": incident_type,
        "Vessel": name,
        "Action": message,
    })


def prepare_fleet_map_data(vessels):
    map_data = []
    wave_tick = datetime.datetime.now().timestamp()
    for index, vessel in enumerate(vessels):
        condition = vessel_condition(vessel, index)
        if condition == "destroyed":
            color = [220, 38, 38, 230]
            text_color = [255, 255, 255, 255]
            radius = 180000
            symbol = "X"
        elif condition == "damaged":
            color = [245, 158, 11, 230]
            text_color = [17, 24, 39, 255]
            radius = 145000
            symbol = "!"
        elif condition == "maintenance":
            color = [107, 114, 128, 190]
            text_color = [255, 255, 255, 255]
            radius = 115000
            symbol = "M"
        else:
            color = [37, 99, 235, 220]
            text_color = [255, 255, 255, 255]
            radius = 125000
            symbol = "SHIP"
        base_lat = vessel_map_lat(vessel)
        base_lon = vessel_map_lon(vessel)
        uses_api_projection = vessel.get("display_position_lat") is not None or vessel.get("display_position_lon") is not None
        drift = 0 if condition == "destroyed" or uses_api_projection else math.sin(wave_tick + index) * 0.18
        map_data.append({
            "name": vessel.get("name", f"Vessel {index + 1}"),
            "lat": base_lat + (drift * 0.25),
            "lon": base_lon + drift,
            "condition": condition.title(),
            "color": color,
            "text_color": text_color,
            "radius": radius,
            "effect_radius": radius * (2.6 if condition == "destroyed" else 1.8),
            "effect_color": [220, 38, 38, 85] if condition == "destroyed" else [245, 158, 11, 70],
            "symbol": symbol,
        })
    return map_data


def fleet_operations_deck(vessels, routes=None, selected_name=None, weather=None, congestion=None):
    route_rows = route_visual_data(routes or [])
    vessel_rows = []
    selected_rows = []
    berth_arcs = []
    wake_rows = []
    wave_phase = datetime.datetime.now().timestamp() % 6

    for index, vessel in enumerate(vessels or []):
        status = str(vessel.get("status", "active")).lower()
        lat = vessel_map_lat(vessel)
        lon = vessel_map_lon(vessel)
        route = routes[index % len(routes)] if routes else None
        route_name = vessel.get("route") or (f"{route.get('origin_port')} to {route.get('destination_port')}" if route else "Unassigned")
        is_selected = vessel.get("name") == selected_name
        nearest_port = nearest_known_port_name(lat, lon)
        priority = vessel_priority_score(vessel)
        signal_age = vessel_signal_age(vessel)
        speed = vessel_speed(vessel)
        cargo = vessel.get("cargo", "Unknown")
        cargo_class = vessel.get("cargo_class", "Unknown")
        cargo_value = vessel.get("cargo_value", vessel.get("value", "Unknown"))
        cargo_source = vessel.get("cargo_source", "Unknown")
        destination = vessel.get("destination_port") or vessel.get("ais_destination") or vessel.get("destination") or "Unknown"
        mmsi = vessel.get("mmsi") or vessel.get("id") or "Unknown"
        heading = float(vessel.get("heading", 0) or 0)
        eta = _format_eta_hours(vessel.get("eta_hours")) if vessel.get("eta_hours") is not None else "Calculating"
        slot = f"F{index + 1:02d}"
        if priority >= 55 or status in {"damaged", "destroyed"}:
            color = [248, 113, 113, 235]
            slot_color = [15, 23, 42, 255]
            command = "HOLD"
        elif priority >= 30:
            color = [251, 191, 36, 235]
            slot_color = [15, 23, 42, 255]
            command = "WATCH"
        elif status == "docked":
            color = [56, 189, 248, 225]
            slot_color = [255, 255, 255, 255]
            command = "BERTH"
        elif status == "maintenance":
            color = [148, 163, 184, 220]
            slot_color = [255, 255, 255, 255]
            command = "MAINT"
        else:
            color = [45, 212, 191, 235]
            slot_color = [15, 23, 42, 255]
            command = "FLOW"
        radius = 155000 + (priority * 2200)

        row = {
            "name": vessel.get("name", f"Vessel {index + 1}"),
            "lat": lat,
            "lon": lon,
            "slot": slot,
            "status": status.title(),
            "route": route_name,
            "cargo": cargo,
            "cargo_class": cargo_class,
            "cargo_value": cargo_value,
            "cargo_source": cargo_source,
            "verified_manifest": "Yes" if vessel.get("cargo_verified") else "No",
            "mmsi": mmsi,
            "destination": destination,
            "command": command,
            "speed": f"{speed:.1f} kn",
            "heading": f"{heading:.0f} deg",
            "eta": eta,
            "nearest_port": nearest_port,
            "priority": priority,
            "signal": f"{signal_age:.0f}s" if signal_age is not None else "Unknown",
            "api_position": f"{vessel_api_lat(vessel):.4f}, {vessel_api_lon(vessel):.4f}",
            "display_position": f"{lat:.4f}, {lon:.4f}",
            "motion_source": vessel.get("motion_source", "map projection"),
            "motion_nm": vessel.get("motion_projected_nm", 0),
            "angle": heading,
            "risk": round(max(priority / 10, float(vessel.get("risk_score", 0) or 0)), 2),
            "color": color,
            "slot_color": slot_color,
            "radius": radius,
            "ring_color": color[:3] + [55],
            "ring_radius": radius * (2.35 if is_selected else 1.65),
            "pulse_color": color[:3] + [30],
            "pulse_radius": radius * (2.15 + ((wave_phase + index) % 3) * 0.28),
            "selection_color": [250, 204, 21, 58],
            "selection_line": [250, 204, 21, 240],
            "selection_radius": 430000,
            "heading_label": f"{heading:.0f} deg",
            "ai_recommendation": vessel.get("recommended_action", "Open ship intelligence card"),
        }
        vessel_rows.append(row)
        if is_selected:
            selected_rows.append(row)
        if status not in {"destroyed", "maintenance"}:
            wake_rows.append({
                "name": row["name"],
                "path": vessel_motion_trail(vessel, index, routes or []),
                "color": color[:3] + [120],
                "width": 7 if speed > 5 else 4,
            })
        port_coords = PORT_COORDS.get(nearest_port)
        if port_coords:
            berth_arcs.append({
                "name": row["name"],
                "nearest_port": nearest_port,
                "source_lat": port_coords[0],
                "source_lon": port_coords[1],
                "target_lat": lat,
                "target_lon": lon,
                "priority": priority,
                "source_color": [96, 165, 250, 90],
                "target_color": color[:3] + [175],
                "width": max(2, 1.8 + (priority / 18)),
            })

    port_rows = []
    for port_name, coords in PORT_COORDS.items():
        local_vessels = [row for row in vessel_rows if row["nearest_port"] == port_name]
        priority_load = sum(float(row.get("priority", 0) or 0) for row in local_vessels)
        berth_load = min(100, 25 + (len(local_vessels) * 12) + (priority_load * 0.28))
        if berth_load >= 80:
            color = [239, 68, 68, 220]
            status = "Constrained"
        elif berth_load >= 58:
            color = [245, 158, 11, 220]
            status = "Busy"
        else:
            color = [14, 165, 233, 220]
            status = "Open"
        port_rows.append({
            "name": port_name,
            "lat": coords[0],
            "lon": coords[1],
            "vessels": len(local_vessels),
            "berth_load": round(berth_load, 1),
            "status": status,
            "color": color,
            "halo": color[:3] + [42],
            "column": 1100 + (berth_load * 240),
            "label": f"{port_name}\n{berth_load:.0f}% load\n{len(local_vessels)} ships",
        })

    weather_rows = weather_cell_rows(weather)
    congestion_rows = congestion_zone_rows(congestion, port_rows)
    comparison_rows = route_comparison_rows(routes or [])
    heat_rows = threat_heat_rows(routes=routes or [], vessels=vessel_rows)
    course_rows = course_vector_rows(vessel_rows)

    layers = []
    if heat_rows:
        layers.append(pdk.Layer(
            "HeatmapLayer",
            data=heat_rows,
            get_position="[lon, lat]",
            get_weight="weight",
            radiusPixels=70,
            intensity=1.25,
            threshold=0.03,
            colorRange=[
                [14, 116, 144, 0],
                [45, 212, 191, 70],
                [250, 204, 21, 105],
                [245, 158, 11, 145],
                [220, 38, 38, 190],
            ],
            pickable=False,
        ))
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=heat_rows,
            get_position="[lon, lat]",
            get_fill_color="color",
            get_radius="radius",
            stroked=True,
            get_line_color="line",
            line_width_min_pixels=1,
            pickable=True,
        ))
    if comparison_rows:
        layers.append(pdk.Layer(
            "PathLayer",
            data=comparison_rows,
            get_path="path",
            get_color="glow",
            get_width=22,
            width_min_pixels=2,
            rounded=True,
            pickable=False,
        ))
        layers.append(pdk.Layer(
            "PathLayer",
            data=comparison_rows,
            get_path="path",
            get_color="color",
            get_width="width",
            width_min_pixels=2,
            rounded=True,
            pickable=True,
        ))
    if weather_rows:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=weather_rows,
            get_position="[lon, lat]",
            get_fill_color="color",
            get_radius="radius",
            stroked=True,
            get_line_color="line",
            line_width_min_pixels=2,
            pickable=True,
        ))
        layers.append(pdk.Layer(
            "ColumnLayer",
            data=weather_rows,
            get_position="[lon, lat]",
            get_elevation="elevation",
            elevation_scale=45,
            radius=80000,
            get_fill_color="line",
            pickable=True,
        ))
    if congestion_rows:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=congestion_rows,
            get_position="[lon, lat]",
            get_fill_color="color",
            get_radius="radius",
            stroked=True,
            get_line_color="line",
            line_width_min_pixels=2,
            pickable=True,
        ))
    if route_rows:
        layers.append(pdk.Layer(
            "PathLayer",
            data=route_rows,
            get_path="path",
            get_color=[30, 64, 175, 58],
            get_width=3,
            width_min_pixels=1,
            rounded=True,
            pickable=True,
        ))
    if berth_arcs:
        layers.append(pdk.Layer(
            "ArcLayer",
            data=berth_arcs,
            get_source_position="[source_lon, source_lat]",
            get_target_position="[target_lon, target_lat]",
            get_source_color="source_color",
            get_target_color="target_color",
            get_width="width",
            pickable=True,
        ))
    if course_rows:
        layers.append(pdk.Layer(
            "PathLayer",
            data=course_rows,
            get_path="path",
            get_color="color",
            get_width="width",
            width_min_pixels=2,
            rounded=True,
            pickable=True,
        ))
    if wake_rows:
        layers.append(pdk.Layer(
            "PathLayer",
            data=wake_rows,
            get_path="path",
            get_color="color",
            get_width="width",
            width_min_pixels=2,
            rounded=True,
            pickable=True,
        ))
    if port_rows:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=port_rows,
            get_position="[lon, lat]",
            get_fill_color="halo",
            get_radius=430000,
            stroked=True,
            get_line_color="color",
            line_width_min_pixels=2,
            pickable=True,
        ))
        layers.append(pdk.Layer(
            "ColumnLayer",
            data=port_rows,
            get_position="[lon, lat]",
            get_elevation="column",
            elevation_scale=35,
            radius=120000,
            get_fill_color="color",
            pickable=True,
        ))
        layers.append(pdk.Layer(
            "TextLayer",
            data=port_rows,
            get_position="[lon, lat]",
            get_text="label",
            get_color=[226, 232, 240, 245],
            get_size=12,
            get_pixel_offset=[0, -38],
            get_alignment_baseline="'bottom'",
            get_text_anchor="'middle'",
        ))
    if vessel_rows:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=vessel_rows,
            get_position="[lon, lat]",
            get_fill_color="pulse_color",
            get_radius="pulse_radius",
            stroked=True,
            get_line_color="color",
            line_width_min_pixels=1,
            pickable=False,
        ))
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=vessel_rows,
            get_position="[lon, lat]",
            get_fill_color="ring_color",
            get_radius="ring_radius",
            stroked=True,
            get_line_color="color",
            line_width_min_pixels=2,
            pickable=True,
            auto_highlight=True,
        ))
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=vessel_rows,
            get_position="[lon, lat]",
            get_fill_color="color",
            get_radius="radius",
            stroked=True,
            get_line_color=[255, 255, 255, 235],
            line_width_min_pixels=2,
            pickable=True,
            auto_highlight=True,
        ))
    if selected_rows:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=selected_rows,
            get_position="[lon, lat]",
            get_fill_color="selection_color",
            get_radius="selection_radius",
            stroked=True,
            get_line_color="selection_line",
            line_width_min_pixels=3,
        ))
    if vessel_rows:
        layers.append(pdk.Layer(
            "TextLayer",
            data=vessel_rows,
            get_position="[lon, lat]",
            get_text="slot",
            get_color="slot_color",
            get_size=12,
            get_alignment_baseline="'center'",
            get_text_anchor="'middle'",
        ))
        layers.append(pdk.Layer(
            "TextLayer",
            data=vessel_rows,
            get_position="[lon, lat]",
            get_text="command",
            get_color=[226, 232, 240, 245],
            get_size=10,
            get_pixel_offset=[0, 30],
            get_alignment_baseline="'top'",
            get_text_anchor="'middle'",
        ))
        layers.append(pdk.Layer(
            "TextLayer",
            data=vessel_rows,
            get_position="[lon, lat]",
            get_text="heading_label",
            get_color=[191, 219, 254, 230],
            get_size=9,
            get_pixel_offset=[0, -32],
            get_alignment_baseline="'bottom'",
            get_text_anchor="'middle'",
        ))

    return pdk.Deck(
        map_style=MAP_STYLE,
        layers=layers,
        initial_view_state=pdk.ViewState(latitude=22, longitude=55, zoom=1.3, pitch=48, bearing=-18),
        tooltip={
            "html": (
                "<b>{name}</b><br/>MMSI/ID: {mmsi}<br/>Status: {status}<br/>"
                "Route: {route}<br/>Destination: {destination}<br/>Nearest port: {nearest_port}<br/>"
                "Cargo: {cargo} ({cargo_class})<br/>Cargo value: {cargo_value}<br/>"
                "Cargo source: {cargo_source} | Verified: {verified_manifest}<br/>"
                "Speed: {speed}<br/>Heading: {heading}<br/>ETA: {eta}<br/>Signal age: {signal}<br/>"
                "Priority: {priority}<br/>Command: {command}<br/>AI: {ai_recommendation}<br/>"
                "Wind/Wave: {wind} / {wave}<br/>Control: {control}<br/>"
                "API point: {api_position}<br/>Map point: {display_position}<br/>"
                "Motion: {motion_source} ({motion_nm} nm)"
            ),
            "style": {"backgroundColor": "#07111f", "color": "#e5f7ff"},
        },
    )


def render_fleet_operations_legend():
    st.caption(
        "3D maritime map: animated AIS ships, course vectors, wake trails, weather cells, threat heat, "
        "port congestion zones, route comparison lanes, and hover details."
    )


def render_fleet_live_map_panel(vessels, routes, selected_name, map_height, weather=None, congestion=None):
    live_vessels = vessels
    source = "current page data"
    updated_at = None
    try:
        live = api_get("/ai/live")
        snapshot = live.get("snapshot", {})
        api_vessels = snapshot.get("vessels", [])
        if api_vessels:
            limit = max(1, len(vessels or api_vessels))
            live_vessels = api_vessels[:limit]
            source = snapshot.get("source", "API live feed")
            updated_at = live.get("live_updated_at") or snapshot.get("timestamp")
    except Exception as error:
        st.caption(f"Live map refresh using current page data because API refresh failed: {error}")

    st.caption(
        f"Animated API map: {len(live_vessels or [])} ships | Source: {source}"
        + (f" | Last signal: {updated_at}" if updated_at else "")
        + " | Hover any ship for details"
    )
    st.pydeck_chart(
        fleet_operations_deck(live_vessels, routes or [], selected_name=selected_name, weather=weather, congestion=congestion),
        use_container_width=True,
        height=map_height,
    )


if hasattr(st, "fragment"):
    render_fleet_live_map_panel = st.fragment(run_every="5s")(render_fleet_live_map_panel)


def fleet_port_workload_rows(vessels):
    rows = []
    for port_name in PORT_COORDS:
        local_vessels = [
            vessel for vessel in vessels or []
            if nearest_known_port_name(vessel_map_lat(vessel), vessel_map_lon(vessel)) == port_name
        ]
        priority_load = sum(vessel_priority_score(vessel) for vessel in local_vessels)
        slow = sum(1 for vessel in local_vessels if vessel_speed(vessel) <= 1)
        berth_load = min(100, 25 + (len(local_vessels) * 12) + (priority_load * 0.28))
        rows.append({
            "Port": port_name,
            "AIS Vessels": len(local_vessels),
            "Slow / Holding": slow,
            "Avg Priority": round(priority_load / len(local_vessels), 1) if local_vessels else 0,
            "Berth Load": round(berth_load, 1),
            "Control Move": "Open overflow berth" if berth_load >= 80 else "Stage arrivals" if berth_load >= 58 else "Normal flow",
        })
    return sorted(rows, key=lambda row: row["Berth Load"], reverse=True)


def render_fleet_control_tower(vessels):
    port_rows = fleet_port_workload_rows(vessels)
    dispatch_rows = fleet_triage_rows(vessels)
    if not port_rows:
        return

    st.markdown("### Fleet Control Tower")
    st.caption("This section is now about fleet dispatch: port workload, berth pressure, cargo exposure, and which AIS vessels need a controller decision.")

    port_df = pd.DataFrame(port_rows)
    dispatch_df = pd.DataFrame(dispatch_rows)
    busiest = port_rows[0]
    critical_cargo = sum(1 for vessel in vessels or [] if str(vessel.get("cargo_class", "")).lower() in {"critical", "high value", "energy"})
    slow_vessels = sum(1 for vessel in vessels or [] if vessel_speed(vessel) <= 1 and str(vessel.get("status", "active")).lower() == "active")
    stale_vessels = sum(1 for vessel in vessels or [] if (vessel_signal_age(vessel) or 0) > 600)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Busiest Port", busiest["Port"], f"{busiest['Berth Load']:.0f}% load")
    with c2:
        st.metric("Priority Cargo", critical_cargo)
    with c3:
        st.metric("Slow / Holding", slow_vessels)
    with c4:
        st.metric("Stale Signals", stale_vessels)

    chart_col, table_col = st.columns([1.05, 1])
    with chart_col:
        fig = px.bar(
            port_df,
            x="Port",
            y="Berth Load",
            color="Berth Load",
            color_continuous_scale="Tealrose",
            range_y=[0, 100],
            title="Port Workload From Live AIS",
        )
        st.plotly_chart(fig, use_container_width=True)
    with table_col:
        st.markdown("### Dispatch Queue")
        if dispatch_df.empty:
            st.success("No fleet dispatch actions are queued.")
        else:
            st.dataframe(
                dispatch_df[["Vessel", "Nearest Port", "Cargo", "Speed", "Signal Age", "Priority", "Action"]].head(7),
                use_container_width=True,
                hide_index=True,
            )


def render_floating_ship_map(vessels):
    if not vessels:
        return
    lats = [vessel_map_lat(vessel) for vessel in vessels]
    lons = [vessel_map_lon(vessel) for vessel in vessels]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    lat_span = max(max_lat - min_lat, 1)
    lon_span = max(max_lon - min_lon, 1)
    ship_nodes = []
    for index, vessel in enumerate(vessels):
        condition = vessel_condition(vessel, index)
        lat = vessel_map_lat(vessel)
        lon = vessel_map_lon(vessel)
        left = 8 + ((lon - min_lon) / lon_span) * 84
        top = 82 - ((lat - min_lat) / lat_span) * 68
        label = vessel.get("name", f"Vessel {index + 1}")
        marker = "X" if condition == "destroyed" else "!" if condition == "damaged" else ">"
        ship_nodes.append(
            f'<button class="ship {condition}" style="left:{left:.1f}%; top:{top:.1f}%;" '
            f'title="{label} - {condition.title()}"><span>{marker}</span><small>{label}</small></button>'
        )
    html = f"""
    <style>
        .fleet-map {{
            height: 360px;
            position: relative;
            overflow: hidden;
            border: 1px solid #1f2937;
            border-radius: 8px;
            background:
                linear-gradient(rgba(255,255,255,.08) 1px, transparent 1px),
                linear-gradient(90deg, rgba(255,255,255,.08) 1px, transparent 1px),
                radial-gradient(circle at 30% 20%, #1d4ed8 0, transparent 24%),
                linear-gradient(135deg, #082f49 0%, #0f766e 54%, #155e75 100%);
            background-size: 46px 46px, 46px 46px, auto, auto;
        }}
        .fleet-map:after {{
            content: "";
            position: absolute;
            inset: 0;
            background: linear-gradient(120deg, transparent 0 45%, rgba(255,255,255,.18) 50%, transparent 55% 100%);
            animation: scan 5s linear infinite;
        }}
        .ship {{
            position: absolute;
            z-index: 2;
            transform: translate(-50%, -50%);
            border: 0;
            background: transparent;
            color: white;
            display: grid;
            justify-items: center;
            gap: 4px;
            cursor: pointer;
            animation: float 2.4s ease-in-out infinite;
        }}
        .ship span {{
            width: 34px;
            height: 24px;
            border-radius: 14px 14px 8px 8px;
            display: grid;
            place-items: center;
            font-weight: 800;
            background: #2563eb;
            box-shadow: 0 10px 22px rgba(0,0,0,.28);
        }}
        .ship small {{
            padding: 2px 6px;
            border-radius: 999px;
            background: rgba(8, 47, 73, .82);
            font: 11px/1.2 Segoe UI, sans-serif;
            white-space: nowrap;
        }}
        .ship.damaged span {{
            background: #f59e0b;
            animation: alertPulse 1s ease-in-out infinite;
        }}
        .ship.destroyed {{
            animation: none;
        }}
        .ship.destroyed span {{
            background: #111827;
            outline: 3px solid #dc2626;
            transform: rotate(-18deg);
        }}
        .ship.destroyed:before {{
            content: "";
            position: absolute;
            width: 58px;
            height: 58px;
            top: -15px;
            border-radius: 50%;
            background: radial-gradient(circle, rgba(220,38,38,.85), transparent 62%);
            animation: demolition 1.4s ease-out infinite;
        }}
        @keyframes float {{
            0%, 100% {{ margin-top: 0; }}
            50% {{ margin-top: -10px; }}
        }}
        @keyframes alertPulse {{
            0%, 100% {{ transform: scale(1); }}
            50% {{ transform: scale(1.18); }}
        }}
        @keyframes demolition {{
            0% {{ transform: scale(.4); opacity: .95; }}
            100% {{ transform: scale(1.45); opacity: 0; }}
        }}
        @keyframes scan {{
            0% {{ transform: translateX(-100%); }}
            100% {{ transform: translateX(100%); }}
        }}
    </style>
    <div class="fleet-map">{''.join(ship_nodes)}</div>
    """
    components.html(html, height=380)


def render_interactive_fleet_map(vessels, routes=None, weather=None, congestion=None):
    init_fleet_incident_state()
    st.markdown("### Fleet Operations Map")
    if not vessels:
        st.info("No vessels available for incident mapping.")
        return

    vessel_names = [vessel.get("name", f"Vessel {index + 1}") for index, vessel in enumerate(vessels)]
    control_col1, control_col2, control_col3, control_col4 = st.columns(4)
    with control_col1:
        target_name = st.selectbox("Target vessel", vessel_names)
        target_index = vessel_names.index(target_name)
    with control_col2:
        if st.button("Simulate storm"):
            apply_fleet_incident(vessels, "Storm", target_index)
            st.rerun()
    with control_col3:
        if st.button("Pirate attack"):
            apply_fleet_incident(vessels, "Pirate Attack", target_index)
            st.rerun()
    with control_col4:
        if st.button("Repair fleet"):
            st.session_state.destroyed_ship_ids = set()
            st.session_state.damaged_ship_ids = set()
            st.session_state.fleet_incident_log = []
            st.rerun()

    visual_vessels = []
    for index, vessel in enumerate(vessels):
        row = dict(vessel)
        row["status"] = vessel_condition(vessel, index)
        visual_vessels.append(row)
    selected_vessel = visual_vessels[target_index]
    default_map_limit = 18 if st.session_state.get("mobile_performance_mode") else 36
    if len(visual_vessels) > default_map_limit:
        map_limit = st.slider("Map detail limit", 8, min(len(visual_vessels), 100), min(default_map_limit, len(visual_vessels)), 4)
        visual_vessels_for_map = visual_vessels[:map_limit]
        if selected_vessel not in visual_vessels_for_map:
            visual_vessels_for_map = [selected_vessel] + visual_vessels_for_map[:-1]
        st.caption(f"Performance mode: rendering {len(visual_vessels_for_map)} of {len(visual_vessels)} vessels on the map. Full fleet remains in the registry below.")
    else:
        visual_vessels_for_map = visual_vessels
    assigned_route = routes[target_index % len(routes)] if routes else None
    route_name = (
        selected_vessel.get("route")
        or (f"{assigned_route.get('origin_port')} to {assigned_route.get('destination_port')}" if assigned_route else "Unassigned")
    )
    route_distance = float(assigned_route.get("distance", 0) or 0) if assigned_route else 0
    eta_days = max(1, round(route_distance / 520, 1)) if route_distance else "N/A"

    detail_col1, detail_col2, detail_col3, detail_col4, detail_col5 = st.columns(5)
    with detail_col1:
        st.metric("Selected Vessel", selected_vessel.get("name", target_name))
    with detail_col2:
        st.metric("Condition", selected_vessel.get("status", "active").title())
    with detail_col3:
        st.metric("Nearest Port", nearest_known_port_name(vessel_map_lat(selected_vessel), vessel_map_lon(selected_vessel)))
    with detail_col4:
        st.metric("Speed", f"{vessel_speed(selected_vessel):.1f} kn")
    with detail_col5:
        st.metric("Priority", vessel_priority_score(selected_vessel), route_name)

    st.markdown("### Live Vessel Intelligence Card")
    vessel_identifier_value = str(selected_vessel.get("mmsi") or selected_vessel.get("id") or selected_vessel.get("name") or target_name)
    try:
        vessel_intel = api_get(f"/vessels/intelligence?vessel_identifier={quote(vessel_identifier_value)}")
        intel_col1, intel_col2 = st.columns([0.75, 1.25])
        with intel_col1:
            st.markdown(
                f"""
                <div class="vessel-intel-card">
                    <b>{safe_html(selected_vessel.get('name', target_name))}</b>
                    <div class="mission-score">{safe_html(vessel_intel.get('risk_score', 0))}/10</div>
                    <small>{safe_html(vessel_intel.get('risk_band', 'Unknown'))} | {safe_html(vessel_intel.get('recommended_action', 'Monitor'))}</small>
                </div>
                """,
                unsafe_allow_html=True,
            )
            prediction = vessel_intel.get("prediction", {})
            st.metric("ETA Risk", f"{prediction.get('delay_risk', vessel_intel.get('risk_score', 0))}/10", prediction.get("delay_band", ""))
            st.metric("Cargo", selected_vessel.get("cargo", prediction.get("cargo", "Unknown")))
        with intel_col2:
            evidence = pd.DataFrame({"Evidence": vessel_intel.get("evidence", [])})
            if not evidence.empty:
                st.dataframe(evidence, use_container_width=True, hide_index=True)
            timeline = pd.DataFrame(vessel_intel.get("timeline", []))
            if not timeline.empty and {"timestamp", "speed_knots"} <= set(timeline.columns):
                timeline["timestamp"] = pd.to_datetime(timeline["timestamp"], errors="coerce")
                fig = px.line(timeline, x="timestamp", y="speed_knots", title="Selected Vessel Speed Timeline")
                st.plotly_chart(fig, use_container_width=True)
        with st.expander("Vessel AI Explainability"):
            explain = vessel_intel.get("explainability", {})
            st.caption(explain.get("limits", ["No limits reported."])[0] if explain.get("limits") else "No limits reported.")
            st.dataframe(pd.DataFrame({"Inputs": explain.get("inputs", [])}), use_container_width=True, hide_index=True)
    except Exception as e:
        st.caption(f"Vessel intelligence unavailable for this selection: {e}")

    render_fleet_operations_legend()
    map_height = 380 if st.session_state.get("mobile_performance_mode") else 520
    render_fleet_live_map_panel(visual_vessels_for_map, routes or [], target_name, map_height, weather=weather, congestion=congestion)

    destroyed_count = len(st.session_state.destroyed_ship_ids)
    damaged_count = len(st.session_state.damaged_ship_ids)
    active_count = max(len(vessels) - destroyed_count - damaged_count, 0)
    status_col1, status_col2, status_col3 = st.columns(3)
    with status_col1:
        st.metric("Floating / Active", active_count)
    with status_col2:
        st.metric("Damaged", damaged_count)
    with status_col3:
        st.metric("Demolished", destroyed_count)

    if st.session_state.fleet_incident_log:
        st.markdown("### Incident Log")
        st.dataframe(pd.DataFrame(st.session_state.fleet_incident_log), use_container_width=True, hide_index=True)


def render_demo_map(vessels, routes=None, threats=None, decisions=None):
    render_nautical_legend()
    st.pydeck_chart(
        nautical_deck(vessels, routes or [], threats=threats or [], decisions=decisions or []),
        use_container_width=True,
        height=520,
    )
    return
    map_data = []
    for index, vessel in enumerate(vessels):
        status = vessel.get("status", "active")
        if status == "destroyed":
            color = [220, 38, 38, 230]
            symbol = "X"
            radius = 190000
        elif status == "damaged":
            color = [245, 158, 11, 230]
            symbol = "!"
            radius = 155000
        elif status == "maintenance":
            color = [107, 114, 128, 210]
            symbol = "M"
            radius = 130000
        else:
            color = [37, 99, 235, 220]
            symbol = "SHIP"
            radius = 130000
        map_data.append({
            "name": vessel.get("name", f"Vessel {index + 1}"),
            "lat": vessel.get("position_lat", 0),
            "lon": vessel.get("position_lon", 0),
            "status": status.title(),
            "color": color,
            "symbol": symbol,
            "radius": radius,
            "effect_radius": radius * 2.4,
            "effect_color": [220, 38, 38, 80] if status == "destroyed" else [245, 158, 11, 65],
            "text_color": [255, 255, 255, 255],
        })
    incident_data = [item for item in map_data if item["status"] in {"Damaged", "Destroyed"}]
    deck = pdk.Deck(
        layers=[
            pdk.Layer(
                "ScatterplotLayer",
                data=incident_data,
                get_position="[lon, lat]",
                get_fill_color="effect_color",
                get_radius="effect_radius",
                stroked=True,
                get_line_color=[255, 255, 255, 150],
                line_width_min_pixels=2,
            ),
            pdk.Layer(
                "ScatterplotLayer",
                data=map_data,
                get_position="[lon, lat]",
                get_fill_color="color",
                get_radius="radius",
                stroked=True,
                get_line_color=[255, 255, 255, 190],
                line_width_min_pixels=1,
                pickable=True,
            ),
            pdk.Layer(
                "TextLayer",
                data=map_data,
                get_position="[lon, lat]",
                get_text="symbol",
                get_color="text_color",
                get_size=18,
                get_alignment_baseline="'center'",
                get_text_anchor="'middle'",
            ),
        ],
        initial_view_state=pdk.ViewState(latitude=20, longitude=45, zoom=1.4, pitch=25),
        tooltip={"text": "{name}\nStatus: {status}"},
    )
    st.pydeck_chart(deck, use_container_width=True)


def _clean_status_counts(counts):
    return [{"Status": key.title(), "Count": value} for key, value in sorted((counts or {}).items())]


def _route_decisions_from_assessments(assessments):
    return [
        {
            "route": item.get("route"),
            "risk_score": item.get("score", item.get("risk_score", 0)),
            "decision": item.get("decision"),
            "action": item.get("action"),
        }
        for item in assessments or []
    ]


def show_threat_center():
    st.title("Threat Center")
    try:
        alerts = api_get("/alerts")
        overview = api_get("/analytics/overview")
        live = api_get("/ai/live")
    except Exception as e:
        show_api_error("Alerts", e)
        return

    df = pd.DataFrame(alerts)
    severity_counts = overview.get("severity_counts", {})
    snapshot = live.get("snapshot", {})
    live_threats = snapshot.get("threats", [])

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Critical", severity_counts.get("high", 0))
    with col2:
        st.metric("Warning", severity_counts.get("medium", 0))
    with col3:
        st.metric("Info", severity_counts.get("low", 0))
    with col4:
        st.metric("Total Threats", len(alerts))
    with col5:
        st.metric("AIS Vessels", snapshot.get("summary", {}).get("active_vessels", 0), snapshot.get("source", "Live feed"))

    response_rows = threat_response_rows(alerts, snapshot.get("vessels", []))
    if response_rows:
        st.markdown("### Threat Response Desk")
        st.caption("Connects each alert to nearby AIS vessels and gives the operator a practical first response.")
        response_df = pd.DataFrame(response_rows)
        st.dataframe(response_df, use_container_width=True, hide_index=True)

    try:
        workflows = api_get("/alerts/workflows")
    except Exception:
        workflows = []
    workflow_df = pd.DataFrame(workflows)
    if not workflow_df.empty:
        st.markdown("### Alert Escalation Workflow")
        st.caption("Turn alerts into owned workflows: new, investigating, escalated, or resolved.")
        st.dataframe(workflow_df, use_container_width=True, hide_index=True)
        selected_alert_id = st.selectbox(
            "Workflow alert",
            workflow_df["alert_id"].tolist(),
            format_func=lambda alert_id: f"#{alert_id} - {workflow_df[workflow_df['alert_id'] == alert_id].iloc[0]['title']}",
        )
        wf_col1, wf_col2, wf_col3 = st.columns([1, 1, 2])
        with wf_col1:
            workflow_status = st.selectbox("New status", ["investigating", "escalated", "resolved", "new"])
        with wf_col2:
            workflow_owner = st.text_input("Owner", value=current_role())
        with wf_col3:
            workflow_note = st.text_input("Workflow note", value="Operator reviewed and updated alert workflow.")
        if st.button("Update Alert Workflow", use_container_width=True, disabled=not can("manage_alert_workflows")):
            api_post(f"/alerts/{selected_alert_id}/workflow", {
                "status": workflow_status,
                "owner": workflow_owner,
                "note": workflow_note,
            })
            st.success("Alert workflow updated.")
            st.rerun()
        if not can("manage_alert_workflows"):
            st.caption(f"Alert workflow updates are disabled for role: {current_role()}.")

    with st.expander("Create new threat alert"):
        alert_col1, alert_col2 = st.columns(2)
        with alert_col1:
            title = st.text_input("Title", value="New Threat Signal")
            severity = st.selectbox("Severity", ["high", "medium", "low"], index=1)
        with alert_col2:
            location = st.text_input("Location", value="Singapore")
            description = st.text_area("Description", value="Describe the observed trade disruption.")
        if st.button("Add Threat Alert", use_container_width=True, disabled=not can("create_alerts")):
            try:
                api_post("/alerts", {
                    "title": title,
                    "description": description,
                    "severity": severity,
                    "location": location,
                })
                st.success("Threat alert created.")
                st.rerun()
            except Exception as e:
                st.error(f"Could not create alert: {e}")
        if not can("create_alerts"):
            st.caption(f"Creating alerts is disabled for role: {current_role()}.")

    if df.empty:
        st.info("No active alerts.")
        return

    df["risk_type"] = df["title"].fillna("").str.lower().map(
        lambda text: "Security" if "piracy" in text or "theft" in text else
        "Weather" if "weather" in text or "storm" in text else
        "Cyber" if "cyber" in text else
        "Geopolitical" if "geopolitical" in text or "sanction" in text else
        "Operational"
    )

    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        severity_filter = st.multiselect("Severity", sorted(df["severity"].dropna().unique()), default=sorted(df["severity"].dropna().unique()))
    with filter_col2:
        type_filter = st.multiselect("Risk Type", sorted(df["risk_type"].dropna().unique()), default=sorted(df["risk_type"].dropna().unique()))
    with filter_col3:
        search = st.text_input("Search", placeholder="port, title, description")

    filtered_df = df[df["severity"].isin(severity_filter) & df["risk_type"].isin(type_filter)]
    if search:
        search_text = search.lower()
        filtered_df = filtered_df[
            filtered_df.apply(lambda row: search_text in " ".join(str(value).lower() for value in row.values), axis=1)
        ]

    st.markdown(f"### Active Threats ({len(filtered_df)})")
    st.dataframe(filtered_df, use_container_width=True, hide_index=True)

    if not filtered_df.empty:
        csv = filtered_df.to_csv(index=False)
        st.download_button("Download Filtered Alerts CSV", data=csv, file_name="threat_alerts.csv", mime="text/csv")

    st.markdown("### Live Moving Threat Signals")
    if live_threats:
        st.dataframe(pd.DataFrame(live_threats), use_container_width=True, hide_index=True)
    else:
        st.info("No moving live threat signals returned by the current AIS packet.")

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        fig = px.histogram(filtered_df, x="severity", color="severity", title="Alerts by Severity")
        st.plotly_chart(fig, use_container_width=True)
    with chart_col2:
        fig = px.histogram(filtered_df, x="risk_type", color="risk_type", title="Alerts by Risk Type")
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Operational Response Guidance")
    top_routes = pd.DataFrame(overview.get("top_routes", []))
    if not top_routes.empty:
        st.dataframe(top_routes[["route", "score", "band", "decision", "action"]], use_container_width=True, hide_index=True)
    else:
        st.info("No route guidance available yet.")


def _driver_text(item):
    return ", ".join(driver.get("label", driver.get("factor", "")) for driver in item.get("top_drivers", []))


def _status_badge(score):
    if score >= 80:
        return "Ready"
    if score >= 65:
        return "Watch"
    return "At Risk"


def _flatten_routes_for_csv(routes):
    rows = []
    for item in routes or []:
        rows.append({
            "route": item.get("route"),
            "score": item.get("score"),
            "band": item.get("band"),
            "confidence": item.get("confidence"),
            "drivers": _driver_text(item),
            "decision": item.get("decision"),
            "action": item.get("action"),
        })
    return pd.DataFrame(rows)


def _risk_rgba(score, alpha=205):
    score = float(score or 0)
    if score >= 8:
        return [220, 38, 38, alpha]
    if score >= 7:
        return [248, 113, 113, alpha]
    if score >= 5:
        return [245, 158, 11, alpha]
    if score >= 4:
        return [250, 204, 21, alpha]
    return [45, 212, 191, alpha]


CARGO_MANIFESTS = [
    {"cargo": "Petrol", "tons": 82000, "value": "$74M", "class": "Energy", "color": [251, 191, 36, 235]},
    {"cargo": "Gold", "tons": 42, "value": "$2.7B", "class": "High value", "color": [250, 204, 21, 245]},
    {"cargo": "Electronics", "tons": 12800, "value": "$430M", "class": "Priority", "color": [96, 165, 250, 235]},
    {"cargo": "LNG", "tons": 91000, "value": "$118M", "class": "Energy", "color": [34, 211, 238, 235]},
    {"cargo": "Grain", "tons": 64000, "value": "$31M", "class": "Food", "color": [132, 204, 22, 235]},
    {"cargo": "Medical Supplies", "tons": 7200, "value": "$210M", "class": "Critical", "color": [244, 114, 182, 235]},
]


def _cargo_manifest(index):
    return CARGO_MANIFESTS[index % len(CARGO_MANIFESTS)]


def _format_eta_hours(hours):
    try:
        hours = float(hours)
    except (TypeError, ValueError):
        return "Calculating"
    if hours >= 48:
        return f"{hours / 24:.1f} days"
    return f"{hours:.1f} hours"


def _seconds_since_iso(value):
    if not value:
        return None
    try:
        timestamp = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=datetime.timezone.utc)
        return max(0, (datetime.datetime.now(datetime.timezone.utc) - timestamp).total_seconds())
    except ValueError:
        return None


def _ship_color_for_status(status, fallback):
    status = str(status or "active").lower()
    if status == "destroyed":
        return [239, 68, 68, 245]
    if status == "damaged":
        return [249, 115, 22, 245]
    if status == "maintenance":
        return [148, 163, 184, 220]
    if status == "docked":
        return [129, 140, 248, 220]
    return fallback


def nearest_known_port_name(lat, lon):
    try:
        lat = float(lat or 0)
        lon = float(lon or 0)
    except (TypeError, ValueError):
        return "Unknown"
    return min(PORT_COORDS, key=lambda port: abs(lat - PORT_COORDS[port][0]) + abs(lon - PORT_COORDS[port][1]))


def vessel_signal_age(vessel):
    return _seconds_since_iso(vessel.get("last_signal_at") or vessel.get("last_signal"))


def vessel_speed(vessel):
    try:
        return float(vessel.get("speed_knots", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def vessel_priority_score(vessel):
    status = str(vessel.get("status", "active")).lower()
    cargo_class = str(vessel.get("cargo_class", "")).lower()
    age = vessel_signal_age(vessel)
    score = 0
    if status in {"destroyed", "damaged"}:
        score += 45
    elif status in {"maintenance", "docked"}:
        score += 18
    if age is not None and age > 600:
        score += 28
    if vessel_speed(vessel) <= 1 and status == "active":
        score += 16
    if cargo_class in {"critical", "high value", "energy"}:
        score += 18
    return score


def fleet_triage_rows(vessels):
    rows = []
    for vessel in vessels or []:
        age = vessel_signal_age(vessel)
        lat = vessel_map_lat(vessel)
        lon = vessel_map_lon(vessel)
        priority = vessel_priority_score(vessel)
        if priority >= 55:
            action = "Escalate to operations lead"
        elif priority >= 30:
            action = "Watch closely and confirm next signal"
        else:
            action = "Keep normal monitoring"
        rows.append({
            "Vessel": vessel.get("name", "Unknown vessel"),
            "MMSI": vessel.get("mmsi", ""),
            "Status": str(vessel.get("status", "active")).title(),
            "Nearest Port": nearest_known_port_name(lat, lon),
            "Cargo": vessel.get("cargo", "Unknown"),
            "Speed": f"{vessel_speed(vessel):.1f} kn",
            "Signal Age": f"{age:.0f}s" if age is not None else "Unknown",
            "Priority": priority,
            "Action": action,
        })
    return sorted(rows, key=lambda row: row["Priority"], reverse=True)


def route_vessel_exposure(route_name, vessels):
    route_text = str(route_name or "").lower()
    ports = [port for port in PORT_COORDS if port.lower() in route_text]
    if not ports:
        return []
    exposed = []
    for vessel in vessels or []:
        vessel_ports = {
            str(vessel.get("origin_port", "")).lower(),
            str(vessel.get("destination_port", "")).lower(),
            nearest_known_port_name(vessel_map_lat(vessel), vessel_map_lon(vessel)).lower(),
        }
        if any(port.lower() in vessel_ports for port in ports):
            exposed.append(vessel)
    return exposed


def decision_command_rows(assessments, vessels):
    rows = []
    for item in assessments or []:
        exposed = route_vessel_exposure(item.get("route"), vessels)
        max_vessel_priority = max([vessel_priority_score(vessel) for vessel in exposed] or [0])
        score = float(item.get("score", item.get("risk_score", 0)) or 0)
        urgency = min(100, round((score * 8) + (len(exposed) * 5) + (max_vessel_priority * 0.35), 1))
        if urgency >= 80:
            command = "Hold release and prepare reroute"
        elif urgency >= 60:
            command = "Escalate before departure"
        elif urgency >= 40:
            command = "Add controls and monitor"
        else:
            command = "Proceed with standard watch"
        rows.append({
            "Route": item.get("route"),
            "Risk": score,
            "Band": item.get("band"),
            "Confidence": item.get("confidence"),
            "AIS Vessels": len(exposed),
            "Urgency": urgency,
            "Command": command,
            "Reason": item.get("explanation", "")[:120],
        })
    return sorted(rows, key=lambda row: row["Urgency"], reverse=True)


def threat_response_rows(alerts, vessels):
    rows = []
    for alert in alerts or []:
        location = str(alert.get("location", "")).lower()
        matched = []
        for vessel in vessels or []:
            nearest = nearest_known_port_name(vessel.get("position_lat"), vessel.get("position_lon")).lower()
            route = str(vessel.get("route", "")).lower()
            if location and (location in nearest or location in route or nearest in location):
                matched.append(vessel)
        severity = str(alert.get("severity", "low")).lower()
        if severity == "high" or len(matched) >= 3:
            action = "Open incident bridge"
        elif severity == "medium" or matched:
            action = "Issue fleet advisory"
        else:
            action = "Monitor intelligence feed"
        rows.append({
            "Threat": alert.get("title"),
            "Severity": severity.title(),
            "Location": alert.get("location"),
            "AIS Vessels Nearby": len(matched),
            "Response": action,
            "Why It Matters": alert.get("description", "")[:120],
        })
    return sorted(rows, key=lambda row: (row["Severity"] != "High", -row["AIS Vessels Nearby"]))


def forecast_watch_windows(forecast_df, threshold):
    rows = []
    if forecast_df.empty:
        return rows
    for route, group in forecast_df.groupby("route"):
        risky = group[group["forecast_score"] >= threshold].sort_values("date")
        if risky.empty:
            continue
        peak_row = group.loc[group["forecast_score"].idxmax()]
        rows.append({
            "Route": route,
            "First Watch Date": risky.iloc[0]["date"].date().isoformat(),
            "Watch Days": len(risky),
            "Peak Forecast": round(float(peak_row["forecast_score"]), 2),
            "Recommended Move": "Pre-book alternate corridor" if len(risky) >= 3 else "Add monitoring checkpoint",
        })
    return sorted(rows, key=lambda row: row["Peak Forecast"], reverse=True)


def _route_lookup(routes):
    return {
        f"{route.get('origin_port')} to {route.get('destination_port')}": route
        for route in routes or []
    }


def dashboard_cargo_ship_rows(routes, live=None):
    snapshot = (live or {}).get("snapshot", {})
    live_vessels = snapshot.get("vessels", [])
    live_decisions = snapshot.get("route_assessments") or snapshot.get("decisions", [])
    decision_by_route = {item.get("route"): item for item in live_decisions}
    route_by_name = _route_lookup(routes)
    if live_vessels:
        ship_rows = []
        wake_rows = []
        for index, vessel in enumerate(live_vessels):
            route = route_by_name.get(vessel.get("route")) or (routes[index % len(routes)] if routes else {})
            cargo = _cargo_manifest(index)
            cargo_name = vessel.get("cargo") or cargo["cargo"]
            cargo_class = vessel.get("cargo_class") or cargo["class"]
            cargo_tons = vessel.get("cargo_tons") or cargo["tons"]
            cargo_value = vessel.get("cargo_value") or cargo["value"]
            origin = vessel.get("origin_port") or route.get("origin_port", "Origin")
            destination = vessel.get("destination_port") or route.get("destination_port", "Destination")
            origin_coords = PORT_COORDS.get(origin, (vessel.get("origin_lat"), vessel.get("origin_lon")))
            destination_coords = PORT_COORDS.get(destination, (vessel.get("destination_lat"), vessel.get("destination_lon")))
            lat = vessel_map_lat({**vessel, "position_lat": vessel.get("position_lat", origin_coords[0]), "position_lon": vessel.get("position_lon", origin_coords[1])})
            lon = vessel_map_lon({**vessel, "position_lat": vessel.get("position_lat", origin_coords[0]), "position_lon": vessel.get("position_lon", origin_coords[1])})
            route_name = vessel.get("route") or f"{origin} to {destination}"
            decision = decision_by_route.get(route_name, {})
            risk = float(decision.get("risk_score", decision.get("score", route.get("risk_level", 0))) or 0)
            progress_value = float(vessel.get("progress", 0) or 0)
            heading = float(vessel.get("heading", bearing_angle(origin_coords[0], origin_coords[1], destination_coords[0], destination_coords[1])) or 0)
            color = _ship_color_for_status(vessel.get("status"), cargo.get("color", [34, 211, 238, 235]))
            angle = math.radians(heading)
            trail = vessel_motion_trail(vessel, index, routes)

            ship_rows.append({
                "name": vessel.get("name", f"Cargo Ship {index + 1}"),
                "mmsi": vessel.get("mmsi") or vessel.get("id") or "Unknown",
                "lat": lat,
                "lon": lon,
                "api_lat": vessel_api_lat(vessel),
                "api_lon": vessel_api_lon(vessel),
                "display_position": f"{lat:.4f}, {lon:.4f}",
                "route": route_name,
                "origin": origin,
                "destination": destination,
                "cargo": cargo_name,
                "cargo_class": cargo_class,
                "tons": f"{int(cargo_tons):,} tons" if isinstance(cargo_tons, (int, float)) else str(cargo_tons),
                "value": cargo_value,
                "cargo_source": vessel.get("cargo_source", "Unknown"),
                "verified_manifest": "Yes" if vessel.get("cargo_verified") else "No",
                "eta": _format_eta_hours(vessel.get("eta_hours")),
                "progress": f"{progress_value * 100:.0f}%",
                "progress_value": round(progress_value * 100, 1),
                "speed": f"{vessel.get('speed_knots', 0)} kn",
                "heading": f"{heading:.0f} deg",
                "status": str(vessel.get("status", "active")).title(),
                "last_signal": vessel.get("last_signal_at") or (live or {}).get("live_updated_at", ""),
                "color": color,
                "halo": color[:3] + [65],
                "label": f"{vessel.get('name', 'Vessel')} | {cargo_name}",
                "marker": ">",
                "angle": heading,
                "risk": round(risk, 2),
                "band": decision.get("band", risk_label(risk)),
                "detail": f"Live vessel telemetry from {API_BASE}/ai/live",
                "source": vessel.get("source", "Backend live feed"),
                "motion_source": vessel.get("motion_source", "AIS/API map projection"),
                "motion_nm": vessel.get("motion_projected_nm", 0),
            })
            wake_rows.append({
                "name": f"{vessel.get('name', 'Vessel')} wake",
                "path": trail,
                "color": color[:3] + [105],
            })
        return ship_rows, wake_rows

    now = datetime.datetime.now().timestamp()
    ship_rows = []
    wake_rows = []

    for index, route in enumerate(routes or []):
        origin = route.get("origin_port")
        destination = route.get("destination_port")
        origin_coords = PORT_COORDS.get(origin)
        destination_coords = PORT_COORDS.get(destination)
        if not origin_coords or not destination_coords:
            continue

        cargo = CARGO_MANIFESTS[index % len(CARGO_MANIFESTS)]
        distance = float(route.get("distance", 0) or 0)
        progress = ((now / 24) + (index * 0.17)) % 1
        bob = math.sin((now / 2.6) + index) * 0.18
        lat = origin_coords[0] + ((destination_coords[0] - origin_coords[0]) * progress) + (bob * 0.08)
        lon = origin_coords[1] + ((destination_coords[1] - origin_coords[1]) * progress) + bob
        angle = bearing_angle(origin_coords[0], origin_coords[1], destination_coords[0], destination_coords[1])
        remaining_days = max(0.2, ((1 - progress) * distance) / 520) if distance else 0
        route_name = f"{origin} to {destination}"

        ship_rows.append({
            "name": f"Cargo Ship {index + 1}",
            "mmsi": "Simulated",
            "lat": lat,
            "lon": lon,
            "api_lat": lat,
            "api_lon": lon,
            "display_position": f"{lat:.4f}, {lon:.4f}",
            "route": route_name,
            "origin": origin,
            "destination": destination,
            "cargo": cargo["cargo"],
            "cargo_class": cargo["class"],
            "tons": f"{cargo['tons']:,} tons",
            "value": cargo["value"],
            "cargo_source": "Fallback manifest",
            "verified_manifest": "Demo",
            "eta": f"{remaining_days:.1f} days",
            "progress": f"{progress * 100:.0f}%",
            "progress_value": round(progress * 100, 1),
            "speed": "Simulated",
            "heading": f"{angle:.0f} deg",
            "status": "Simulated",
            "last_signal": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "color": cargo["color"],
            "halo": cargo["color"][:3] + [55],
            "label": f"{cargo['cargo']} -> {destination}",
            "marker": ">",
            "angle": angle,
            "risk": route.get("risk_level", 0),
            "band": risk_label(route.get("risk_level", 0)),
            "detail": f"Carrying {cargo['cargo']} from {origin} to {destination}",
            "source": "Local fallback simulation",
            "motion_source": "Fallback route animation",
            "motion_nm": round(progress * float(route.get("distance", 0) or 0), 1),
        })
        wake_rows.append({
            "name": f"Wake {index + 1}",
            "path": [[origin_coords[1], origin_coords[0]], [lon, lat]],
            "color": cargo["color"][:3] + [95],
        })

    return ship_rows, wake_rows


def dashboard_trade_pulse_deck(overview, routes, live=None, weather=None, congestion=None):
    assessment_by_route = {
        item.get("route"): item
        for item in overview.get("top_routes", [])
    }
    snapshot = (live or {}).get("snapshot", {})
    for item in snapshot.get("route_assessments", []) or snapshot.get("decisions", []):
        assessment_by_route[item.get("route")] = item
    port_risk = {
        item.get("port"): item
        for item in overview.get("port_summary", [])
    }

    arc_rows = []
    for route in routes or []:
        origin = route.get("origin_port")
        destination = route.get("destination_port")
        origin_coords = PORT_COORDS.get(origin)
        destination_coords = PORT_COORDS.get(destination)
        if not origin_coords or not destination_coords:
            continue

        route_name = f"{origin} to {destination}"
        assessment = assessment_by_route.get(route_name, {})
        risk = float(assessment.get("risk_score", assessment.get("score", route.get("risk_level", 0))) or 0)
        arc_rows.append({
            "name": route_name,
            "detail": "Trade corridor",
            "cargo": "",
            "tons": "",
            "value": "",
            "route": route_name,
            "eta": "",
            "speed": "",
            "progress": "",
            "last_signal": "",
            "source": "Route model",
            "source_lat": origin_coords[0],
            "source_lon": origin_coords[1],
            "target_lat": destination_coords[0],
            "target_lon": destination_coords[1],
            "risk": round(risk, 2),
            "band": assessment.get("band", risk_label(risk)),
            "status": "",
            "decision": assessment.get("decision", "Monitor"),
            "source_color": _risk_rgba(risk, 185),
            "target_color": _risk_rgba(risk, 235),
            "width": max(2, risk * 1.25),
        })

    port_rows = []
    for port, coords in PORT_COORDS.items():
        summary = port_risk.get(port, {})
        risk = float(summary.get("average_risk", 0) or 0)
        vessels = int(summary.get("vessels", 0) or 0)
        port_rows.append({
            "name": port,
            "detail": "Port exposure column",
            "cargo": "",
            "tons": "",
            "value": "",
            "route": "",
            "eta": "",
            "speed": "",
            "progress": "",
            "last_signal": "",
            "source": "Port analytics",
            "lat": coords[0],
            "lon": coords[1],
            "risk": round(risk, 2),
            "vessels": vessels,
            "status": summary.get("status", risk_label(risk)),
            "band": "",
            "halo_color": _risk_rgba(risk, 55),
            "line_color": _risk_rgba(risk, 190),
            "column_color": _risk_rgba(risk, 210),
            "radius": 180000 + (risk * 26000),
            "elevation": 1200 + (risk * 950) + (vessels * 380),
            "label": f"{port}\n{risk:.1f}",
        })

    region_rows = []
    for index, region in enumerate(overview.get("regional_risk", [])):
        anchor = {
            "Asia-Pacific": (13, 106),
            "Middle East": (24, 54),
            "Europe": (50, 12),
            "Americas": (31, -105),
        }.get(region.get("region"), (8 + index * 8, 20 + index * 25))
        risk = float(region.get("risk_level", 0) or 0)
        region_rows.append({
            "name": region.get("region", "Region"),
            "detail": "Regional exposure halo",
            "cargo": "",
            "tons": "",
            "value": "",
            "route": "",
            "eta": "",
            "speed": "",
            "progress": "",
            "last_signal": "",
            "source": "Regional analytics",
            "lat": anchor[0],
            "lon": anchor[1],
            "risk": round(risk, 2),
            "status": "",
            "band": risk_label(risk),
            "color": _risk_rgba(risk, 42),
            "line": _risk_rgba(risk, 150),
            "radius": 650000 + (risk * 120000),
            "label": f"{region.get('region')}: {risk:.1f}",
        })

    ship_rows, ship_wake_rows = dashboard_cargo_ship_rows(routes, live)
    weather_rows = weather_cell_rows(weather)
    congestion_rows = congestion_zone_rows(congestion, port_rows)
    comparison_rows = route_comparison_rows(routes, assessment_by_route)
    heat_rows = threat_heat_rows(overview=overview, routes=routes, vessels=ship_rows, assessment_by_route=assessment_by_route)
    course_rows = course_vector_rows(ship_rows)
    layers = []
    if heat_rows:
        layers.append(pdk.Layer(
            "HeatmapLayer",
            data=heat_rows,
            get_position="[lon, lat]",
            get_weight="weight",
            radiusPixels=80,
            intensity=1.35,
            threshold=0.035,
            colorRange=[
                [14, 116, 144, 0],
                [45, 212, 191, 65],
                [250, 204, 21, 105],
                [245, 158, 11, 145],
                [220, 38, 38, 205],
            ],
            pickable=False,
        ))
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=heat_rows,
            get_position="[lon, lat]",
            get_fill_color="color",
            get_radius="radius",
            stroked=True,
            get_line_color="line",
            line_width_min_pixels=1,
            pickable=True,
        ))
    if region_rows:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=region_rows,
            get_position="[lon, lat]",
            get_fill_color="color",
            get_radius="radius",
            stroked=True,
            get_line_color="line",
            line_width_min_pixels=2,
            pickable=True,
        ))
    if comparison_rows:
        layers.append(pdk.Layer(
            "PathLayer",
            data=comparison_rows,
            get_path="path",
            get_color="glow",
            get_width=24,
            width_min_pixels=3,
            rounded=True,
            pickable=False,
        ))
        layers.append(pdk.Layer(
            "PathLayer",
            data=comparison_rows,
            get_path="path",
            get_color="color",
            get_width="width",
            width_min_pixels=2,
            rounded=True,
            pickable=True,
            auto_highlight=True,
        ))
    if arc_rows:
        layers.append(pdk.Layer(
            "ArcLayer",
            data=arc_rows,
            get_source_position="[source_lon, source_lat]",
            get_target_position="[target_lon, target_lat]",
            get_source_color="source_color",
            get_target_color="target_color",
            get_width="width",
            pickable=True,
            auto_highlight=True,
        ))
    if weather_rows:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=weather_rows,
            get_position="[lon, lat]",
            get_fill_color="color",
            get_radius="radius",
            stroked=True,
            get_line_color="line",
            line_width_min_pixels=2,
            pickable=True,
        ))
        layers.append(pdk.Layer(
            "ColumnLayer",
            data=weather_rows,
            get_position="[lon, lat]",
            get_elevation="elevation",
            elevation_scale=55,
            radius=85000,
            get_fill_color="line",
            pickable=True,
            auto_highlight=True,
        ))
    if ship_wake_rows:
        layers.append(pdk.Layer(
            "PathLayer",
            data=ship_wake_rows,
            get_path="path",
            get_color="color",
            get_width=4,
            width_min_pixels=1,
            rounded=True,
        ))
    if course_rows:
        layers.append(pdk.Layer(
            "PathLayer",
            data=course_rows,
            get_path="path",
            get_color="color",
            get_width="width",
            width_min_pixels=2,
            rounded=True,
            pickable=True,
        ))
    if congestion_rows:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=congestion_rows,
            get_position="[lon, lat]",
            get_fill_color="color",
            get_radius="radius",
            stroked=True,
            get_line_color="line",
            line_width_min_pixels=2,
            pickable=True,
        ))
    if port_rows:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=port_rows,
            get_position="[lon, lat]",
            get_fill_color="halo_color",
            get_radius="radius",
            stroked=True,
            get_line_color="line_color",
            line_width_min_pixels=2,
            pickable=True,
        ))
        layers.append(pdk.Layer(
            "ColumnLayer",
            data=port_rows,
            get_position="[lon, lat]",
            get_elevation="elevation",
            elevation_scale=60,
            radius=90000,
            get_fill_color="column_color",
            pickable=True,
            auto_highlight=True,
        ))
        layers.append(pdk.Layer(
            "TextLayer",
            data=port_rows,
            get_position="[lon, lat]",
            get_text="label",
            get_color=[226, 232, 240, 245],
            get_size=13,
            get_pixel_offset=[0, -34],
            get_alignment_baseline="'bottom'",
            get_text_anchor="'middle'",
        ))
    if ship_rows:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=ship_rows,
            get_position="[lon, lat]",
            get_fill_color="halo",
            get_radius=260000,
            stroked=True,
            get_line_color="color",
            line_width_min_pixels=2,
            pickable=True,
        ))
        layers.append(pdk.Layer(
            "TextLayer",
            data=ship_rows,
            get_position="[lon, lat]",
            get_text="marker",
            get_color="color",
            get_size=24,
            get_angle="angle",
            get_alignment_baseline="'center'",
            get_text_anchor="'middle'",
            pickable=True,
        ))
        layers.append(pdk.Layer(
            "TextLayer",
            data=ship_rows,
            get_position="[lon, lat]",
            get_text="label",
            get_color=[248, 250, 252, 245],
            get_size=11,
            get_pixel_offset=[0, 28],
            get_alignment_baseline="'top'",
            get_text_anchor="'middle'",
        ))

    return pdk.Deck(
        map_style=MAP_STYLE,
        layers=layers,
        initial_view_state=pdk.ViewState(latitude=24, longitude=48, zoom=1.25, pitch=48, bearing=-18),
        tooltip={
            "html": (
                "<b>{name}</b><br/>{detail}<br/>MMSI/ID: {mmsi}<br/>Route: {route}<br/>"
                "Origin: {origin}<br/>Destination: {destination}<br/>"
                "Cargo: {cargo} ({cargo_class})<br/>Tonnage: {tons}<br/>Value: {value}<br/>"
                "Cargo source: {cargo_source} | Verified: {verified_manifest}<br/>"
                "Speed: {speed}<br/>Heading: {heading}<br/>ETA: {eta}<br/>Progress: {progress}<br/>"
                "Risk: {risk}<br/>Status/Band: {status}{band}<br/>"
                "Wind/Wave: {wind} / {wave}<br/>Control: {control}<br/>"
                "Last signal: {last_signal}<br/>Source: {source}<br/>"
                "API point: {api_lat}, {api_lon}<br/>Map point: {display_position}<br/>"
                "Motion: {motion_source} ({motion_nm} nm)"
            ),
            "style": {"backgroundColor": "#07111f", "color": "#e5f7ff"},
        },
    )


def render_dashboard_trade_pulse_map(overview, routes):
    live = None
    live_error = None
    weather = {}
    congestion = {}
    try:
        live = api_get("/ai/live")
    except Exception as error:
        live_error = error
    try:
        weather = api_get("/weather/maritime")
        congestion = api_get("/ports/congestion")
    except Exception as overlay_error:
        st.caption(f"Advanced map overlays are using built-in fallback context: {overlay_error}")

    snapshot = (live or {}).get("snapshot", {})
    live_summary = snapshot.get("summary", {})
    live_updated_at = (live or {}).get("live_updated_at") or snapshot.get("timestamp")
    signal_age = _seconds_since_iso(live_updated_at)
    source_label = snapshot.get("source", "Backend live feed") if live else "Fallback"

    pulse_col, signal_col, vessel_col, risk_col = st.columns(4)
    with pulse_col:
        st.metric("Live Feed", source_label, "optimized refresh" if live else "local animation")
    with signal_col:
        st.metric("Signal Age", f"{signal_age:.0f}s" if signal_age is not None else "Unknown")
    with vessel_col:
        st.metric("Moving Vessels", live_summary.get("active_vessels", len(routes or [])))
    with risk_col:
        st.metric("Live Avg Risk", f"{live_summary.get('average_risk', overview.get('summary', {}).get('average_risk', 0)):.1f}/10")

    if live_error:
        st.warning(f"Live vessel feed is unavailable, so the map is using local fallback motion. Details: {live_error}")

    st.caption("Layers: animated ships, weather cells, threat heatmap, port congestion columns, and route comparison lanes.")
    st.pydeck_chart(dashboard_trade_pulse_deck(overview, routes, live, weather=weather, congestion=congestion), use_container_width=True, height=520)
    ship_rows, _ = dashboard_cargo_ship_rows(routes, live)
    manifest_df = pd.DataFrame(ship_rows)
    if not manifest_df.empty:
        st.markdown("### Live Cargo Manifest")
        if live_updated_at:
            st.caption(f"Backend signal: {live_updated_at}")
        st.dataframe(
            manifest_df[[
                "name",
                "status",
                "route",
                "cargo",
                "cargo_class",
                "tons",
                "value",
                "speed",
                "eta",
                "progress",
                "last_signal",
            ]],
            use_container_width=True,
            hide_index=True,
        )


def mission_overlay_deck(overlay):
    route_rows = overlay.get("routes", [])
    vessel_rows = [row for row in overlay.get("vessels", []) if row.get("lat") is not None and row.get("lon") is not None]
    vessel_trails = [
        {
            "name": f"{row.get('name', 'Vessel')} API motion trail",
            "path": row.get("motion_trail"),
            "color": [191, 219, 254, 110],
        }
        for row in vessel_rows
        if isinstance(row.get("motion_trail"), list) and len(row.get("motion_trail")) >= 2
    ]
    alert_rows = [row for row in overlay.get("alerts", []) if row.get("lat") is not None and row.get("lon") is not None]
    layers = []
    if route_rows:
        layers.append(pdk.Layer(
            "PathLayer",
            data=route_rows,
            get_path="path",
            get_color="color",
            get_width="width",
            width_min_pixels=3,
            rounded=True,
            pickable=True,
            auto_highlight=True,
        ))
    if vessel_trails:
        layers.append(pdk.Layer(
            "PathLayer",
            data=vessel_trails,
            get_path="path",
            get_color="color",
            get_width=4,
            width_min_pixels=1,
            rounded=True,
        ))
    if vessel_rows:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=vessel_rows,
            get_position="[lon, lat]",
            get_fill_color="color",
            get_radius="radius",
            stroked=True,
            get_line_color=[248, 250, 252, 220],
            line_width_min_pixels=2,
            pickable=True,
        ))
        layers.append(pdk.Layer(
            "TextLayer",
            data=vessel_rows,
            get_position="[lon, lat]",
            get_text="name",
            get_color=[226, 232, 240, 245],
            get_size=12,
            get_pixel_offset=[0, 24],
            get_alignment_baseline="'top'",
            get_text_anchor="'middle'",
        ))
    if alert_rows:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=alert_rows,
            get_position="[lon, lat]",
            get_fill_color="color",
            get_radius="radius",
            stroked=True,
            get_line_color=[15, 23, 42, 230],
            line_width_min_pixels=2,
            pickable=True,
        ))
        layers.append(pdk.Layer(
            "TextLayer",
            data=alert_rows,
            get_position="[lon, lat]",
            get_text="priority",
            get_color=[255, 255, 255, 245],
            get_size=15,
            get_alignment_baseline="'center'",
            get_text_anchor="'middle'",
        ))
    return pdk.Deck(
        map_style=MAP_STYLE,
        layers=layers,
        initial_view_state=pdk.ViewState(latitude=18, longitude=35, zoom=1.1, pitch=42, bearing=-22),
        tooltip={
            "html": (
                "<b>{route}{name}{target}</b><br/>"
                "Risk/Score: {risk}{score}<br/>Band/Priority: {band}{priority}<br/>"
                "Signals: {signals}<br/>Cargo: {cargo}<br/>Action: {action}<br/>Motion: {motion_source}"
            ),
            "style": {"backgroundColor": "#07111f", "color": "#e5f7ff"},
        },
    )


def render_mission_overlay(overlay):
    summary = overlay.get("summary", {})
    st.markdown("### AI Mission Overlay")
    st.caption("War Room overlay: route pressure, delay-risk vessels, and alert clusters fused into one command layer.")
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Command Mode", summary.get("command_mode", "Unknown"))
    with m2:
        st.metric("Focus", summary.get("active_focus", "Command"))
    with m3:
        st.metric("Mission Score", f"{summary.get('mission_score', 0)}/100")
    with m4:
        st.metric("Response Window", summary.get("response_window", "Today"))
    map_height = 330 if st.session_state.get("mobile_performance_mode") else 430
    st.pydeck_chart(mission_overlay_deck(overlay), use_container_width=True, height=map_height)
    gates = pd.DataFrame(overlay.get("decision_gates", []))
    if not gates.empty:
        with st.expander("Decision Gates"):
            st.dataframe(gates, use_container_width=True, hide_index=True)


if hasattr(st, "fragment"):
    render_dashboard_trade_pulse_map = st.fragment(run_every="5s")(render_dashboard_trade_pulse_map)


def show_global_dashboard():
    st.title("Global Mission Dashboard")
    try:
        overview = api_get("/analytics/overview")
        operations = api_get("/analytics/operations")
        routes = api_get("/routes")
    except Exception as e:
        show_api_error("Dashboard data", e)
        return
    overview = sanitize_public_overview(overview)

    summary = overview.get("summary", {})
    readiness = operations.get("readiness_score", 0)
    mission_status = overview.get("mission_status", "Unknown")

    hero_tone = "Critical response required" if readiness < 65 or mission_status == "Critical" else "Watch mode active" if readiness < 80 else "Ready for command demo"
    st.markdown(
        f"""
        <div class="dashboard-hero">
            <span class="hero-kicker">{safe_html(PROJECT_TITLE)}</span>
            <h2>{safe_html(mission_status)} mission dashboard</h2>
            <p>{safe_html(hero_tone)}. Tracking routes, live/fallback vessels, cargo pressure, AI risk, alerts, and readiness in one submission-ready command view.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if readiness < 65 or mission_status == "Critical":
        st.error(f"Mission posture: {mission_status}. Operational readiness is {readiness:.1f}% ({operations.get('readiness_band')}).")
    elif readiness < 80:
        st.warning(f"Mission posture: {mission_status}. Readiness is in watch mode at {readiness:.1f}%.")
    else:
        st.success(f"Mission posture: {mission_status}. Readiness is strong at {readiness:.1f}%.")

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Readiness", f"{readiness:.1f}%", operations.get("readiness_band", _status_badge(readiness)))
    with col2:
        st.metric("Avg AI Risk", f"{summary.get('average_risk', 0):.1f}/10")
    with col3:
        st.metric("Critical Alerts", summary.get("critical_alerts", 0))
    with col4:
        st.metric("Active Vessels", summary.get("active_vessels", 0), overview.get("fleet_source", "Live feed"))
    with col5:
        st.metric("Routes", summary.get("routes", 0))

    st.markdown("### Global Trade Pulse Map")
    if is_public_access():
        st.caption("Public-safe trade pulse: cargo value, API internals, incident controls, and sensitive manifests are hidden.")
    else:
        st.caption(
            "Real-time cargo-flow view: ships stream from the backend live feed, arcs are trade corridors, "
            "columns are port exposure, and each ship carries a visible manifest."
        )
    render_dashboard_trade_pulse_map(overview, routes)
    if is_public_access():
        st.caption("AI Mission Overlay is hidden in public mode because it can expose incident/cargo decision context.")
    else:
        try:
            render_mission_overlay(api_get("/ai/mission-map-overlay"))
        except Exception as e:
            st.caption(f"AI Mission Overlay unavailable: {e}")

    action_col, risk_col = st.columns([1.1, 1])
    with action_col:
        st.markdown("### Operator Next Actions")
        if is_public_access():
            st.info("Public mode hides operator action queues.")
        else:
            actions_df = pd.DataFrame(operations.get("next_actions", []))
            if actions_df.empty:
                st.success("No operator actions are queued.")
            else:
                st.dataframe(actions_df, use_container_width=True, hide_index=True)
    with risk_col:
        st.markdown("### Priority Routes")
        routes_df = _flatten_routes_for_csv(overview.get("top_routes", []))
        if not routes_df.empty:
            st.dataframe(routes_df[["route", "score", "band", "confidence", "drivers"]], use_container_width=True, hide_index=True)

    port_col, region_col = st.columns(2)
    with port_col:
        st.markdown("### Port Readiness")
        st.dataframe(pd.DataFrame(overview.get("port_summary", [])), use_container_width=True, hide_index=True)
    with region_col:
        st.markdown("### Regional Risk")
        region_df = pd.DataFrame(overview.get("regional_risk", []))
        if not region_df.empty:
            fig = px.bar(region_df, x="region", y="risk_level", color="risk_level", color_continuous_scale="RdYlGn_r", range_y=[0, 10])
            st.plotly_chart(fig, use_container_width=True)

    if not is_public_access():
        st.markdown("### Control Checklist")
        st.dataframe(pd.DataFrame(operations.get("checklist", [])), use_container_width=True, hide_index=True)


def show_fleet_tracking():
    st.title("Fleet Tracking")
    try:
        registry_vessels = api_get("/vessels")
        routes = api_get("/routes")
        operations = api_get("/analytics/operations")
        live = api_get("/ai/live")
        weather = api_get("/weather/maritime")
        congestion = api_get("/ports/congestion")
    except Exception as e:
        show_api_error("Fleet data", e)
        return

    snapshot = live.get("snapshot", {})
    live_vessels = snapshot.get("vessels", [])
    vessels = live_vessels or registry_vessels
    data_source = snapshot.get("source", "Local fleet registry") if live_vessels else "Local fleet registry"
    last_signal = live.get("live_updated_at") or snapshot.get("timestamp")

    with st.expander("Add vessel to monitored fleet"):
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            name = st.text_input("Vessel name", value=f"Vessel {len(registry_vessels) + 1}")
        with col2:
            status = st.selectbox("Status", ["active", "docked", "maintenance"], key="new_vessel_status")
        with col3:
            lat = st.number_input("Latitude", value=1.3521, min_value=-90.0, max_value=90.0)
        with col4:
            lon = st.number_input("Longitude", value=103.8198, min_value=-180.0, max_value=180.0)
        if st.button("Add Vessel", use_container_width=True, disabled=not can("manage_vessels")):
            try:
                api_post("/vessels", {"name": name, "position_lat": lat, "position_lon": lon, "status": status})
                st.success(f"{name} added to fleet.")
                st.rerun()
            except Exception as e:
                st.error(f"Could not add vessel: {e}")
        if not can("manage_vessels"):
            st.caption(f"Adding vessels is disabled for role: {current_role()}.")

    active = sum(1 for vessel in vessels if vessel.get("status") == "active")
    maintenance = sum(1 for vessel in vessels if vessel.get("status") == "maintenance")
    docked = sum(1 for vessel in vessels if vessel.get("status") == "docked")
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Active", active)
    with col2:
        st.metric("Docked", docked)
    with col3:
        st.metric("Maintenance", maintenance)
    with col4:
        st.metric("Readiness", f"{operations.get('readiness_score', 0):.1f}%")
    with col5:
        st.metric("Source", data_source)

    if last_signal:
        st.caption(f"Live fleet signal: {last_signal}")

    if data_source == "AISStream":
        try:
            reliability = api_get("/ais/reliability")
            summary = reliability.get("summary", {})
            rel_col1, rel_col2, rel_col3, rel_col4 = st.columns(4)
            with rel_col1:
                st.metric("AIS Reliability", f"{reliability.get('score', 0)}/100", reliability.get("status", "unknown"))
            with rel_col2:
                st.metric("Live AIS Ships", summary.get("live_vessels", 0))
            with rel_col3:
                st.metric("Stopped / Stale", f"{summary.get('stopped_vessels', 0)} / {summary.get('stale_vessels', 0)}")
            with rel_col4:
                st.metric("SSL Mode", summary.get("ssl_verification", "enabled"))
            if summary.get("ssl_verification") == "disabled-local-demo":
                st.warning("AISStream SSL verification is disabled for this local demo because the provider certificate failed verification. Do not use this mode in production.")
        except Exception as e:
            st.caption(f"AIS reliability snapshot unavailable: {e}")

    render_fleet_control_tower(vessels)
    render_interactive_fleet_map(vessels, routes, weather=weather, congestion=congestion)

    if vessels:
        st.markdown("### Real Vessel Detail")
        detail_names = [str(vessel.get("name") or vessel.get("mmsi") or vessel.get("id") or f"Vessel {index + 1}") for index, vessel in enumerate(vessels)]
        selected_detail = st.selectbox("Inspect vessel", detail_names, key="fleet_vessel_detail_select")
        selected_vessel = vessels[detail_names.index(selected_detail)]
        detail_col1, detail_col2 = st.columns([0.75, 1.25])
        with detail_col1:
            st.metric("Speed", f"{float(selected_vessel.get('speed_knots') or 0):.1f} kn")
            st.metric("Heading", selected_vessel.get("heading", "Unknown"))
            st.metric("Nearest Port", selected_vessel.get("origin_port") or nearest_known_port_name(vessel_map_lat(selected_vessel), vessel_map_lon(selected_vessel)))
            st.metric("Cargo", selected_vessel.get("cargo", "Unknown"), selected_vessel.get("cargo_class", ""))
        with detail_col2:
            detail_rows = [
                {"Field": "MMSI / ID", "Value": selected_vessel.get("mmsi") or selected_vessel.get("id")},
                {"Field": "Route", "Value": selected_vessel.get("route")},
                {"Field": "Destination", "Value": selected_vessel.get("destination_port") or selected_vessel.get("ais_destination")},
                {"Field": "Cargo value", "Value": selected_vessel.get("cargo_value")},
                {"Field": "Cargo source", "Value": selected_vessel.get("cargo_source", "Unknown")},
                {"Field": "Verified manifest", "Value": display_setting_value(selected_vessel.get("cargo_verified", False))},
                {"Field": "Last AIS signal", "Value": selected_vessel.get("last_signal_at")},
                {"Field": "Source", "Value": selected_vessel.get("source", data_source)},
            ]
            st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)
            try:
                vessel_identifier_value = str(selected_vessel.get("mmsi") or selected_vessel.get("id") or selected_vessel.get("name") or selected_detail)
                intel = api_get(f"/vessels/intelligence?vessel_identifier={quote(vessel_identifier_value)}")
                st.info(f"AI recommendation: {intel.get('recommended_action')} | risk {intel.get('risk_score')}/10 ({intel.get('risk_band')})")
            except Exception as e:
                st.caption(f"Vessel AI recommendation unavailable: {e}")

    st.markdown("### Fleet Importance")
    st.info(
        "This page is for fleet operations: real AIS availability when connected, route assignment, "
        "maintenance impact, and manual registry fallback. The AI Command Center remains the place for autonomous threat scanning."
    )

    action_df = pd.DataFrame(operations.get("next_actions", []))
    if not action_df.empty:
        st.markdown("### Fleet-Related Actions")
        st.dataframe(action_df, use_container_width=True, hide_index=True)

    fleet_df = pd.DataFrame(vessels)
    if not fleet_df.empty:
        fleet_df["nearest_port"] = [
            nearest_known_port_name(vessel_map_lat(vessel), vessel_map_lon(vessel))
            for vessel in vessels
        ]
        fleet_df["incident_condition"] = [vessel_condition(vessel, index).title() for index, vessel in enumerate(vessels)]
        st.markdown("### Fleet Registry")
        if data_source == "AISStream":
            st.caption("Showing live AIS vessels. Manually added vessels remain saved in the local registry and appear when the AIS feed is unavailable.")
        st.dataframe(fleet_df, use_container_width=True, hide_index=True)


def show_ai_risk_engine():
    st.title("AI Risk Decisions")
    try:
        ai_assessments = api_get("/ai/risk-assessments")
        forecast = api_get("/analytics/forecast?days=14")
        live = api_get("/ai/live")
    except Exception as e:
        show_api_error("Risk data", e)
        return

    snapshot = live.get("snapshot", {})
    live_summary = snapshot.get("summary", {})
    assessment_df = _flatten_routes_for_csv(ai_assessments)
    if assessment_df.empty:
        st.info("No route assessments available.")
        return

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("High / Critical", len(assessment_df[assessment_df["score"] >= 7]))
    with col2:
        st.metric("Avg Confidence", f"{assessment_df['confidence'].mean():.1f}%")
    with col3:
        st.metric("Peak Risk", f"{assessment_df['score'].max():.1f}/10")
    with col4:
        st.metric("Live AIS Context", live_summary.get("active_vessels", 0), snapshot.get("source", "Live feed"))

    command_rows = decision_command_rows(ai_assessments, snapshot.get("vessels", []))
    if command_rows:
        st.markdown("### Decision Command Queue")
        st.caption("Ranks route decisions by AI risk plus live AIS exposure, so the top row is the next operational decision to make.")
        command_df = pd.DataFrame(command_rows)
        st.dataframe(command_df, use_container_width=True, hide_index=True)
        top_command = command_rows[0]
        if top_command["Urgency"] >= 80:
            st.error(f"Highest urgency: {top_command['Route']} - {top_command['Command']}")
        elif top_command["Urgency"] >= 60:
            st.warning(f"Watch closely: {top_command['Route']} - {top_command['Command']}")
        else:
            st.success("No route requires immediate escalation from the command queue.")

    st.markdown("### Explainable Ranking")
    st.dataframe(assessment_df, use_container_width=True, hide_index=True)

    route_options = {
        f"{item.get('origin_port')} to {item.get('destination_port')}": item.get("id")
        for item in api_get("/routes")
        if item.get("origin_port") and item.get("destination_port")
    }
    selected_route = st.selectbox("Inspect route", assessment_df["route"].tolist())
    selected = next(item for item in ai_assessments if item.get("route") == selected_route)
    detail_col1, detail_col2, detail_col3 = st.columns(3)
    with detail_col1:
        st.metric("AI Score", f"{selected.get('score', 0):.1f}/10", selected.get("band"))
    with detail_col2:
        st.metric("Confidence", f"{selected.get('confidence', 0):.1f}%")
    with detail_col3:
        st.metric("Model Cross-Check", f"ML {selected.get('ml_score', 0):.1f}", f"Rules {selected.get('rule_score', 0):.1f}")
    st.warning(selected.get("action", "No action returned."))
    st.caption(selected.get("explanation", "No explanation returned."))
    trace = selected.get("model_trace", {})
    if trace:
        with st.expander("AI Model Trace", expanded=False):
            trace_col1, trace_col2, trace_col3 = st.columns(3)
            with trace_col1:
                st.metric("ML Score", trace.get("ml_score", "n/a"))
            with trace_col2:
                st.metric("Rule Score", trace.get("rule_score", "n/a"))
            with trace_col3:
                st.metric("Alert Pressure", trace.get("alert_pressure", "n/a"))
            st.caption(trace.get("blend", ""))
            checklist = pd.DataFrame({"Human checklist": selected.get("human_checklist", [])})
            if not checklist.empty:
                st.dataframe(checklist, use_container_width=True, hide_index=True)
            missing = selected.get("missing_data", [])
            if missing:
                st.warning(f"Missing data to improve confidence: {', '.join(missing)}")

    driver_df = pd.DataFrame(selected.get("top_drivers", []))
    if not driver_df.empty:
        fig = px.bar(driver_df, x="contribution", y="label", orientation="h", color="score", color_continuous_scale="Viridis", title="Driver Contribution")
        st.plotly_chart(fig, use_container_width=True)

    if selected_route in route_options:
        st.markdown("### Smart Route Compare")
        st.caption("Compares the selected lane as four operational choices: safest, fastest, lowest cost, and balanced. Use this when cargo priority or schedule pressure changes the decision.")
        try:
            optimizer = api_get(f"/routes/optimizer?route_id={route_options[selected_route]}")
            mode_cols = st.columns(4)
            for index, (mode_name, option) in enumerate(optimizer.get("modes", {}).items()):
                with mode_cols[index % 4]:
                    st.metric(mode_name.replace("_", " ").title(), option.get("name"), f"Risk {option.get('risk_score')}/10")
                    st.caption(f"{option.get('distance_nm')} nm | Cost {option.get('cost_index')}")
            alternative_df = pd.DataFrame(optimizer.get("options", []))
            if not alternative_df.empty:
                compare_cols = st.columns([1, 1])
                with compare_cols[0]:
                    fig = px.scatter(
                        alternative_df,
                        x="distance_nm",
                        y="risk_score",
                        size="cost_index",
                        color="risk_band",
                        hover_name="name",
                        title="Risk vs Distance vs Cost",
                    )
                    st.plotly_chart(fig, use_container_width=True)
                with compare_cols[1]:
                    mode_rows = []
                    for mode_name, option in optimizer.get("modes", {}).items():
                        mode_rows.append({
                            "Mode": mode_name.replace("_", " ").title(),
                            "Route": option.get("name"),
                            "Risk": option.get("risk_score"),
                            "Distance": option.get("distance_nm"),
                            "Use When": ", ".join(option.get("recommended_for", [])) or mode_name.replace("_", " "),
                        })
                    st.dataframe(pd.DataFrame(mode_rows), use_container_width=True, hide_index=True)
                st.dataframe(
                    alternative_df[["name", "distance_nm", "risk_score", "risk_band", "cost_index", "delay_index", "safety_index", "recommended_for", "why"]],
                    use_container_width=True,
                    hide_index=True,
                )
                st.info(optimizer.get("decision_note", ""))
        except Exception as e:
            st.caption(f"Route optimizer unavailable: {e}")

    live_vessel_df = pd.DataFrame(snapshot.get("vessels", [])[:8])
    if not live_vessel_df.empty:
        st.markdown("### Live AIS Context Feeding Operations")
        columns = [column for column in ["name", "mmsi", "route", "speed_knots", "cargo", "last_signal_at"] if column in live_vessel_df.columns]
        st.dataframe(live_vessel_df[columns], use_container_width=True, hide_index=True)

    forecast_df = pd.DataFrame(forecast.get("forecast", []))
    if not forecast_df.empty:
        route_forecast = forecast_df[forecast_df["route"] == selected_route].copy()
        route_forecast["date"] = pd.to_datetime(route_forecast["date"])
        fig = px.line(route_forecast, x="date", y="forecast_score", range_y=[0, 10], title=f"14-Day Forecast for {selected_route}")
        st.plotly_chart(fig, use_container_width=True)

    if selected_route in route_options and st.button("Create Risk Log For Selected Route", use_container_width=True):
        try:
            api_post(f"/risk-log?route_id={route_options[selected_route]}")
            st.success("Risk log created.")
        except Exception as e:
            st.error(f"Could not create risk log: {e}")


def show_risk_forecast():
    st.title("Risk Forecast")
    days = st.slider("Forecast horizon", 3, 30, 14)
    threshold = st.slider("Watch threshold", 1.0, 10.0, 7.0, 0.5)
    try:
        forecast_packet = api_get(f"/analytics/forecast?days={days}")
        operations = api_get("/analytics/operations")
    except Exception as e:
        show_api_error("Risk forecast", e)
        return

    forecast_df = pd.DataFrame(forecast_packet.get("forecast", []))
    history_df = pd.DataFrame(forecast_packet.get("history", []))
    if forecast_df.empty:
        st.info("No forecast rows available.")
        return
    forecast_df["date"] = pd.to_datetime(forecast_df["date"])
    watch_df = forecast_df[forecast_df["forecast_score"] >= threshold]

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Peak Forecast", f"{forecast_df['forecast_score'].max():.1f}/10")
    with col2:
        st.metric("Watch Days", len(watch_df))
    with col3:
        st.metric("Routes", forecast_df["route"].nunique())
    with col4:
        st.metric("Fleet Source", operations.get("fleet_source", "Live feed"), f"{operations.get('fleet_summary', {}).get('vessels', 0)} vessels")

    fig = px.line(forecast_df, x="date", y="forecast_score", color="route", range_y=[0, 10], title="Route Risk Forecast")
    st.plotly_chart(fig, use_container_width=True)

    watch_windows = forecast_watch_windows(forecast_df, threshold)
    if watch_windows:
        st.markdown("### Early Warning Windows")
        st.caption("Shows when each route first crosses your watch threshold and what to do before the risk window opens.")
        st.dataframe(pd.DataFrame(watch_windows), use_container_width=True, hide_index=True)

    heat_df = forecast_df.copy()
    heat_df["day"] = heat_df["date"].dt.strftime("%b %d")
    heat_pivot = heat_df.pivot_table(index="route", columns="day", values="forecast_score", aggfunc="mean")
    if not heat_pivot.empty:
        st.markdown("### Forecast Heatmap")
        fig = px.imshow(
            heat_pivot,
            aspect="auto",
            color_continuous_scale="RdYlGn_r",
            zmin=0,
            zmax=10,
            title="Route Risk Heatmap",
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Threshold Watchlist")
    st.dataframe(watch_df.sort_values("forecast_score", ascending=False), use_container_width=True, hide_index=True)

    if not history_df.empty:
        history_df["timestamp"] = pd.to_datetime(history_df["timestamp"])
        fig = px.scatter(history_df, x="timestamp", y="risk_score", color="route_id", title="Historical Risk Logs")
        st.plotly_chart(fig, use_container_width=True)


def show_report_export():
    st.title("Report Export")
    try:
        overview = api_get("/analytics/overview")
        operations = api_get("/analytics/operations")
    except Exception as e:
        show_api_error("Report setup", e)
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        report_type = st.selectbox("Report Type", ["Executive Summary", "Detailed Analysis", "Risk Assessment", "Compliance Report"])
    with col2:
        date_range = st.date_input("Report Date", value=datetime.date.today())
    with col3:
        st.metric("Readiness", f"{operations.get('readiness_score', 0):.1f}%")

    section_cols = st.columns(3)
    with section_cols[0]:
        include_routes = st.checkbox("Route Analysis", value=True)
    with section_cols[1]:
        include_vessels = st.checkbox("Fleet Status", value=True)
    with section_cols[2]:
        include_alerts = st.checkbox("Threat Alerts", value=True)

    st.markdown("### Smart Auto-Reports")
    smart_col1, smart_col2, smart_col3, smart_col4 = st.columns([1, 1, 1.05, 1.05])
    with smart_col1:
        smart_type = st.selectbox("Smart brief", ["CEO brief", "Security brief", "Fleet operator brief", "Risk analyst brief"])
    with smart_col2:
        if st.button("Generate Smart Brief", use_container_width=True, disabled=not can("generate_reports")):
            try:
                safe_type = smart_type.replace(" ", "%20")
                smart = api_get(f"/reports/smart?brief_type={safe_type}")
                st.success(f"Smart report #{smart.get('report_id')} generated.")
                st.info(f"Saved to {smart.get('pdf_path')}")
                st.text_area("Smart brief content", value=smart.get("content", ""), height=260)
            except Exception as e:
                st.error(f"Could not generate smart report: {e}")
    with smart_col3:
        if st.button("Generate Daily Command Brief", use_container_width=True, disabled=not can("generate_reports"), icon=":material/today:"):
            try:
                daily = api_get("/reports/daily-brief", fresh=True)
                st.success(f"Daily brief #{daily.get('report_id')} generated.")
                st.text_area("Daily brief content", value=daily.get("content", ""), height=260)
            except Exception as e:
                st.error(f"Could not generate daily brief: {e}")
    with smart_col4:
        if st.button("Generate Final Mission Pack", use_container_width=True, disabled=not can("generate_reports"), icon=":material/folder_zip:"):
            try:
                pack = api_get("/reports/mission-pack", fresh=True)
                st.success(f"Mission pack #{pack.get('report_id')} generated.")
                st.info(f"Saved to {pack.get('pdf_path')}")
                st.text_area("Mission pack content", value=pack.get("content", ""), height=300)
            except Exception as e:
                st.error(f"Could not generate mission pack: {e}")

    with st.expander("AI Report Intelligence: What Changed", expanded=True):
        try:
            intel = api_get("/reports/intelligence", fresh=True)
            r1, r2, r3, r4 = st.columns(4)
            health = intel.get("report_health", {})
            with r1:
                st.metric("Reports", intel.get("reports_available", 0))
            with r2:
                st.metric("Mission", health.get("mission_score", 0))
            with r3:
                st.metric("Data Quality", f"{health.get('data_quality', 0)}%")
            with r4:
                st.metric("Alert Pressure", health.get("notification_pressure", 0))
            change_col, resolved_col = st.columns(2)
            with change_col:
                st.markdown("#### New / Changed Signals")
                st.dataframe(pd.DataFrame({"Signal": intel.get("what_changed", [])}), use_container_width=True, hide_index=True)
            with resolved_col:
                st.markdown("#### Removed / Resolved Signals")
                st.dataframe(pd.DataFrame({"Signal": intel.get("removed_or_resolved", [])}), use_container_width=True, hide_index=True)
            st.dataframe(pd.DataFrame({"Recommendation": intel.get("recommendations", [])}), use_container_width=True, hide_index=True)
        except Exception as e:
            st.caption(f"Report intelligence unavailable: {e}")

    st.markdown("### Report Preview")
    preview_rows = [
        {"Section": "Average risk", "Value": f"{overview.get('summary', {}).get('average_risk', 0):.1f}/10"},
        {"Section": "Critical alerts", "Value": overview.get("summary", {}).get("critical_alerts", 0)},
        {"Section": "Fleet source", "Value": overview.get("fleet_source", operations.get("fleet_source", "Live feed"))},
        {"Section": "Live vessels", "Value": overview.get("summary", {}).get("vessels", 0)},
        {"Section": "Top route", "Value": overview.get("top_routes", [{}])[0].get("route", "None") if overview.get("top_routes") else "None"},
        {"Section": "Readiness", "Value": f"{operations.get('readiness_score', 0):.1f}%"},
    ]
    st.dataframe(pd.DataFrame(preview_rows), use_container_width=True, hide_index=True)

    live_vessels = pd.DataFrame(overview.get("live_vessels", []))
    if not live_vessels.empty:
        st.markdown("### Live AIS Vessels Included In Report")
        columns = [column for column in ["name", "mmsi", "status", "route", "speed_knots", "cargo", "last_signal_at"] if column in live_vessels.columns]
        st.dataframe(live_vessels[columns], use_container_width=True, hide_index=True)

    payload = {
        "report_type": report_type,
        "date_range": str(date_range),
        "include_routes": include_routes,
        "include_vessels": include_vessels,
        "include_alerts": include_alerts,
    }
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("Generate PDF Report", use_container_width=True, disabled=not can("generate_reports")):
            try:
                result = api_post("/generate-report", payload).json()
                st.success(f"Report #{result.get('report_id')} generated.")
                st.info(f"Saved to {result.get('pdf_path')}")
            except Exception as e:
                st.error(f"Error generating report: {e}")
        if not can("generate_reports"):
            st.caption(f"Report generation is disabled for role: {current_role()}.")
    with col_b:
        export_df = _flatten_routes_for_csv(overview.get("top_routes", []))
        st.download_button("Download Route Risk CSV", data=export_df.to_csv(index=False), file_name="route_risk_export.csv", mime="text/csv", use_container_width=True)

    st.markdown("### Recent Reports")
    reports_df = pd.DataFrame(api_get("/reports"))
    if reports_df.empty:
        st.info("No reports generated yet.")
    else:
        st.dataframe(reports_df, use_container_width=True, hide_index=True)


def operations_signal_deck(history_rows, timeline_rows=None):
    latest_by_vessel = {}
    for row in sorted(history_rows or [], key=lambda item: item.get("timestamp") or ""):
        latest_by_vessel[row.get("vessel_identifier", row.get("vessel_name", "unknown"))] = row

    vessel_rows = []
    vessel_trails = []
    port_counts = {}
    for row in latest_by_vessel.values():
        api_lat = float(row.get("position_lat", 0) or 0)
        api_lon = float(row.get("position_lon", 0) or 0)
        speed = float(row.get("speed_knots", 0) or 0)
        heading = float(row.get("heading", 90) or 90)
        signal_age = _seconds_since_iso(row.get("timestamp")) or 0
        visual_seconds = min(signal_age, 90) + (datetime.datetime.now().timestamp() % 12)
        projected_nm = min(28, speed * (visual_seconds / 3600) * 75)
        if speed > 0.5 and projected_nm > 0.02:
            angle = math.radians(heading)
            lat = api_lat + (math.cos(angle) * projected_nm / 60)
            lon = api_lon + (math.sin(angle) * projected_nm / (60 * max(0.2, abs(math.cos(math.radians(api_lat))))))
        else:
            lat, lon = api_lat, api_lon
        nearest = row.get("nearest_port") or nearest_known_port_name(lat, lon)
        port_counts[nearest] = port_counts.get(nearest, 0) + 1
        vessel_rows.append({
            "name": row.get("vessel_name", "Unknown vessel"),
            "lat": lat,
            "lon": lon,
            "api_position": f"{api_lat:.4f}, {api_lon:.4f}",
            "speed": round(speed, 1),
            "nearest_port": nearest,
            "status": row.get("status", "active"),
            "signal": row.get("timestamp", "unknown"),
            "motion": "AIS history projected from speed, heading, and timestamp",
            "color": [45, 212, 191, 220] if speed > 3 else [251, 191, 36, 220],
            "radius": 52000 if speed > 3 else 72000,
        })
        vessel_trails.append({
            "name": row.get("vessel_name", "Unknown vessel"),
            "path": [[api_lon, api_lat], [lon, lat]],
            "color": [191, 219, 254, 95],
        })

    port_rows = []
    for port, count in port_counts.items():
        coords = PORT_COORDS.get(port)
        if not coords:
            continue
        port_rows.append({
            "name": port,
            "lat": coords[0],
            "lon": coords[1],
            "count": count,
            "radius": 85000 + (count * 26000),
        })

    layers = []
    if port_rows:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=port_rows,
            get_position="[lon, lat]",
            get_radius="radius",
            get_fill_color=[56, 189, 248, 42],
            get_line_color=[125, 211, 252, 170],
            line_width_min_pixels=2,
            stroked=True,
            filled=True,
            pickable=True,
        ))
        layers.append(pdk.Layer(
            "TextLayer",
            data=port_rows,
            get_position="[lon, lat]",
            get_text="name",
            get_color=[226, 232, 240, 230],
            get_size=12,
            get_pixel_offset=[0, -22],
            get_alignment_baseline="'bottom'",
            get_text_anchor="'middle'",
        ))
    if vessel_trails:
        layers.append(pdk.Layer(
            "PathLayer",
            data=vessel_trails,
            get_path="path",
            get_color="color",
            get_width=4,
            width_min_pixels=1,
            rounded=True,
        ))
    if vessel_rows:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=vessel_rows,
            get_position="[lon, lat]",
            get_radius="radius",
            get_fill_color="color",
            get_line_color=[248, 250, 252, 220],
            line_width_min_pixels=1,
            stroked=True,
            pickable=True,
        ))

    return pdk.Deck(
        map_style=MAP_STYLE,
        layers=layers,
        initial_view_state=pdk.ViewState(latitude=21, longitude=58, zoom=1.45, pitch=18, bearing=-8),
        tooltip={
            "html": "<b>{name}</b><br/>Nearest port: {nearest_port}<br/>Speed: {speed} kn<br/>Signal: {signal}<br/>API point: {api_position}<br/>Motion: {motion}<br/>Vessels: {count}",
            "style": {"backgroundColor": "#07111f", "color": "#e5f7ff"},
        },
    )


def show_operations_center():
    st.title("Operations Center")
    try:
        intelligence = api_get("/operations/intelligence")
        actions = api_get("/ai/actions?limit=80")
        manifests = api_get("/cargo/manifests?limit=100")
        history_packet = api_get("/vessels/history?limit=500")
        timeline = api_get("/operations/timeline?limit=120")
    except Exception as e:
        show_api_error("Operations center", e)
        return

    summary = intelligence.get("summary", {})
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("Ops Readiness", f"{intelligence.get('readiness_score', 0):.1f}%", intelligence.get("readiness_band"))
    with c2:
        st.metric("Tracked Positions", summary.get("tracked_positions", 0))
    with c3:
        st.metric("Cargo Manifests", summary.get("cargo_manifests", 0))
    with c4:
        st.metric("Open AI Actions", summary.get("open_actions", 0))
    with c5:
        st.metric("Open Incidents", summary.get("open_incidents", 0))

    action_df = pd.DataFrame(actions)
    st.markdown("### AI Approval Queue")
    if action_df.empty:
        st.success("No AI actions have been queued yet. The live backend will create actions as risk and vessel conditions require them.")
    else:
        status_filter = st.multiselect("Action status", sorted(action_df["status"].dropna().unique()), default=["queued"] if "queued" in action_df["status"].values else sorted(action_df["status"].dropna().unique()))
        filtered_actions = action_df[action_df["status"].isin(status_filter)] if status_filter else action_df
        st.dataframe(
            filtered_actions[["id", "priority", "subject", "action_type", "recommendation", "status", "owner", "source"]].head(20),
            use_container_width=True,
            hide_index=True,
        )
        queued = filtered_actions[filtered_actions["status"] == "queued"]
        if not queued.empty:
            selected_action = st.selectbox("Approve/reject action", queued["id"].tolist(), format_func=lambda action_id: f"#{action_id} - {queued[queued['id'] == action_id].iloc[0]['subject']}")
            decision_col1, decision_col2 = st.columns(2)
            with decision_col1:
                if st.button("Approve Selected Action", use_container_width=True, disabled=not can("approve_actions")):
                    api_post(f"/ai/actions/{selected_action}/status", {"status": "approved", "owner": "Operator"})
                    st.success("AI action approved.")
                    st.rerun()
            with decision_col2:
                if st.button("Reject Selected Action", use_container_width=True, disabled=not can("approve_actions")):
                    api_post(f"/ai/actions/{selected_action}/status", {"status": "rejected", "owner": "Operator"})
                    st.warning("AI action rejected.")
                    st.rerun()
            if not can("approve_actions"):
                st.caption(f"Action approval is disabled for role: {current_role()}.")

    cargo_df = pd.DataFrame(manifests)
    cargo_col, timeline_col = st.columns([1, 1])
    with cargo_col:
        st.markdown("### Cargo Exposure")
        if cargo_df.empty:
            st.info("Cargo manifests will populate after live AIS packets are persisted.")
        else:
            priority_counts = cargo_df["priority"].value_counts().reset_index()
            priority_counts.columns = ["Priority", "Count"]
            fig = px.bar(priority_counts, x="Priority", y="Count", color="Priority", title="Cargo Priority Mix")
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(
                cargo_df[["vessel_name", "cargo", "cargo_class", "cargo_value", "origin_port", "destination_port", "priority", "updated_at"]].head(12),
                use_container_width=True,
                hide_index=True,
            )
            with st.expander("Cargo Manifest Editor"):
                if not can("edit_cargo"):
                    st.warning(f"Cargo editing is disabled for role: {current_role()}.")
                vessel_names = cargo_df["vessel_name"].dropna().tolist()
                selected_name = st.selectbox("Manifest vessel", vessel_names, disabled=not can("edit_cargo"))
                selected_manifest = cargo_df[cargo_df["vessel_name"] == selected_name].iloc[0].to_dict()
                edit_col1, edit_col2, edit_col3 = st.columns(3)
                with edit_col1:
                    cargo = st.text_input("Cargo", value=str(selected_manifest.get("cargo", "Unknown")), disabled=not can("edit_cargo"))
                    cargo_class = st.selectbox(
                        "Cargo class",
                        ["General", "Food", "Energy", "Priority", "High value", "Critical"],
                        index=["General", "Food", "Energy", "Priority", "High value", "Critical"].index(str(selected_manifest.get("cargo_class", "General"))) if str(selected_manifest.get("cargo_class", "General")) in ["General", "Food", "Energy", "Priority", "High value", "Critical"] else 0,
                        disabled=not can("edit_cargo"),
                    )
                with edit_col2:
                    cargo_tons = st.number_input("Tons", value=float(selected_manifest.get("cargo_tons", 0) or 0), min_value=0.0, disabled=not can("edit_cargo"))
                    cargo_value = st.text_input("Value", value=str(selected_manifest.get("cargo_value", "Unknown")), disabled=not can("edit_cargo"))
                with edit_col3:
                    origin_port = st.text_input("Origin", value=str(selected_manifest.get("origin_port", "Unknown")), disabled=not can("edit_cargo"))
                    destination_port = st.text_input("Destination", value=str(selected_manifest.get("destination_port", "Unknown")), disabled=not can("edit_cargo"))
                if st.button("Save Cargo Manifest", use_container_width=True, disabled=not can("edit_cargo")):
                    api_post("/cargo/manifests", {
                        "vessel_identifier": str(selected_manifest.get("vessel_identifier")),
                        "vessel_name": selected_name,
                        "cargo": cargo,
                        "cargo_class": cargo_class,
                        "cargo_tons": cargo_tons,
                        "cargo_value": cargo_value,
                        "origin_port": origin_port,
                        "destination_port": destination_port,
                        "status": str(selected_manifest.get("status", "active")),
                    })
                    st.success("Cargo manifest saved.")
                    st.rerun()
    with timeline_col:
        st.markdown("### Incident Timeline")
        timeline_df = pd.DataFrame(timeline)
        if timeline_df.empty:
            st.success("No incident or AI-action timeline entries yet.")
        else:
            st.dataframe(timeline_df, use_container_width=True, hide_index=True)

    history_rows = history_packet.get("rows", [])
    st.markdown("### Operations Signal Map")
    st.caption("Cleaner operational map: latest vessel positions and port concentration only. Detailed trails stay out of this tab so the map remains readable.")
    if history_rows:
        map_col, signal_col = st.columns([1.35, 0.65])
        with map_col:
            st.pydeck_chart(operations_signal_deck(history_rows, timeline), use_container_width=True, height=430)
        with signal_col:
            latest_by_vessel = {}
            for row in sorted(history_rows, key=lambda item: item.get("timestamp") or ""):
                latest_by_vessel[row.get("vessel_identifier", row.get("vessel_name", "unknown"))] = row
            latest_df = pd.DataFrame(latest_by_vessel.values())
            if not latest_df.empty:
                port_counts = latest_df["nearest_port"].fillna("Unknown").value_counts().reset_index()
                port_counts.columns = ["Port", "Signals"]
                st.markdown("#### Port Signal Load")
                st.dataframe(port_counts.head(8), use_container_width=True, hide_index=True)
                slow_count = len(latest_df[pd.to_numeric(latest_df["speed_knots"], errors="coerce").fillna(0) <= 3])
                st.metric("Low-Speed Signals", slow_count)
            timeline_df = pd.DataFrame(timeline)
            if not timeline_df.empty:
                st.markdown("#### Latest Timeline")
                st.dataframe(timeline_df.head(6), use_container_width=True, hide_index=True)
    else:
        st.info("Operations signals will appear after the backend has persisted live vessel snapshots for a short while.")


def scenario_lab_deck(result):
    layers = []
    map_layers = result.get("map_layers", {})
    center = map_layers.get("center", {})
    radius_nm = float(map_layers.get("blast_radius_nm", 650) or 650)
    center_lat = float(center.get("lat", 20) or 20)
    center_lon = float(center.get("lon", 55) or 55)

    layers.append(pdk.Layer(
        "ScatterplotLayer",
        data=[{
            "name": result.get("scenario", {}).get("location", "Scenario center"),
            "lat": center_lat,
            "lon": center_lon,
            "radius_m": radius_nm * 1852,
        }],
        get_position="[lon, lat]",
        get_radius="radius_m",
        get_fill_color=[255, 85, 64, 46],
        get_line_color=[255, 224, 130, 210],
        line_width_min_pixels=2,
        stroked=True,
        filled=True,
        pickable=True,
    ))

    route_rows = []
    for route in map_layers.get("routes", []):
        if not route.get("geometry"):
            continue
        after_score = float(route.get("after_score", 0) or 0)
        color = [255, 71, 87, 230] if after_score >= 8 else [255, 184, 77, 230] if after_score >= 6 else [92, 225, 230, 220]
        route_rows.append({
            **route,
            "name": route.get("route", "Impacted route"),
            "vessel": "",
            "color": color,
            "width": max(3, min(11, after_score)),
        })
    if route_rows:
        layers.append(pdk.Layer(
            "PathLayer",
            data=route_rows,
            get_path="geometry",
            get_color="color",
            get_width="width",
            width_min_pixels=3,
            rounded=True,
            pickable=True,
        ))

    vessel_rows = []
    for vessel in map_layers.get("vessels", []):
        if vessel.get("position_lat") is None or vessel.get("position_lon") is None:
            continue
        exposure_score = float(vessel.get("exposure_score", 0) or 0)
        lat = vessel.get("display_position_lat", vessel.get("position_lat"))
        lon = vessel.get("display_position_lon", vessel.get("position_lon"))
        vessel_rows.append({
            **vessel,
            "position_lat": lat,
            "position_lon": lon,
            "name": vessel.get("vessel", "Exposed vessel"),
            "route": "",
            "color": [255, max(60, int(255 - exposure_score * 16)), 80, 215],
        })
    vessel_trails = [
        {"name": row.get("name"), "path": row.get("motion_trail"), "color": [191, 219, 254, 115]}
        for row in vessel_rows
        if isinstance(row.get("motion_trail"), list) and len(row.get("motion_trail")) >= 2
    ]
    if vessel_trails:
        layers.append(pdk.Layer(
            "PathLayer",
            data=vessel_trails,
            get_path="path",
            get_color="color",
            get_width=4,
            width_min_pixels=1,
            rounded=True,
        ))
    if vessel_rows:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=vessel_rows,
            get_position="[position_lon, position_lat]",
            get_radius=28000,
            get_fill_color="color",
            get_line_color=[255, 255, 255, 220],
            line_width_min_pixels=1,
            stroked=True,
            pickable=True,
        ))

    return pdk.Deck(
        map_style=MAP_STYLE,
        layers=layers,
        initial_view_state=pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=2.2, pitch=45, bearing=-18),
        tooltip={
            "html": "<b>{name}{vessel}{route}</b><br/>Risk: {after_score}{exposure_score}<br/>{recommendation}{action}",
            "style": {"backgroundColor": "#07111f", "color": "#f8fafc"},
        },
    )


def show_scenario_lab():
    st.title("Scenario Lab")
    st.caption("Run a digital-twin crisis simulation before it happens: routes, vessels, cargo, readiness, and response plan are recalculated together.")

    try:
        routes = api_get("/routes")
    except Exception as e:
        show_api_error("Scenario Lab", e)
        return

    scenario_types = ["Storm Surge", "Piracy Swarm", "Hijack Attempt", "War Conflict", "Port Shutdown", "Cyber Blackout", "Fuel Shock", "Cargo Theft Ring"]
    locations = [
        "Singapore / Malacca",
        "Gulf of Aden",
        "South China Sea",
        "Suez / Red Sea",
        "Pacific Corridor",
        "North Sea",
        "Global Network",
        *PORT_COORDS.keys(),
    ]
    route_choices = {"Auto-detect all affected routes": None}
    for route in routes:
        route_choices[f"#{route.get('id')} {route.get('origin_port')} to {route.get('destination_port')}"] = route.get("id")

    st.markdown("### Crisis Simulator")
    c1, c2, c3, c4 = st.columns([1.1, 0.85, 1.1, 0.85])
    with c1:
        scenario_type = st.selectbox("Scenario", scenario_types)
    with c2:
        severity = st.selectbox("Severity", ["medium", "high", "extreme", "low"], index=1)
    with c3:
        location = st.selectbox("Location / corridor", locations)
    with c4:
        duration_hours = st.slider("Duration hours", 1, 72, 12)
    selected_route_label = st.selectbox("Focus route", list(route_choices.keys()))

    payload = {
        "scenario_type": scenario_type,
        "severity": severity,
        "location": location,
        "duration_hours": duration_hours,
        "affected_route_id": route_choices[selected_route_label],
    }
    if st.button("Run Digital Twin Simulation", type="primary", use_container_width=True):
        try:
            st.session_state.scenario_lab_result = api_post("/scenario/simulate", payload).json()
        except Exception as e:
            show_api_error("Scenario Lab", e)
            return

    result = st.session_state.get("scenario_lab_result")
    if not result:
        st.info("Choose a crisis and run the simulation. The platform will produce a predictive operating picture without changing live data.")
        st.markdown("### What makes this unique")
        st.write(
            "This is not just a map. It acts like a mini digital twin: it injects a simulated disruption into live routes, AIS/local vessels, cargo manifests, and AI readiness, then produces a response plan."
        )
        return

    scenario = result.get("scenario", {})
    readiness = result.get("readiness", {})
    summary = result.get("impact_summary", {})

    st.markdown(f"### Twin Verdict: {scenario.get('type')} near {scenario.get('location')}")
    verdict = f"{scenario.get('mission')} Confidence: {summary.get('confidence', 0):.1f}%."
    if readiness.get("band") == "At Risk":
        st.error(verdict)
    elif readiness.get("band") == "Watch":
        st.warning(verdict)
    else:
        st.success(verdict)

    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.metric("Readiness", f"{readiness.get('after', 0):.1f}%", f"{readiness.get('delta', 0):.1f}")
        st.progress(max(0, min(100, int(readiness.get("after", 0)))) / 100)
    with m2:
        st.metric("Max Risk", f"{summary.get('max_projected_risk', 0):.1f}/10")
    with m3:
        st.metric("Delay", f"{summary.get('projected_delay_hours', 0):.1f}h")
    with m4:
        st.metric("Routes Hit", summary.get("routes_impacted", 0))
    with m5:
        st.metric("Ships / Cargo", f"{summary.get('vessels_impacted', 0)} / {summary.get('cargo_records_exposed', 0)}")

    impact_tab, plan_tab, cargo_tab, timeline_tab = st.tabs(["Impact Map", "Response Plan", "Cargo & Vessels", "Timeline"])
    with impact_tab:
        st.pydeck_chart(scenario_lab_deck(result), use_container_width=True, height=520)
        route_df = pd.DataFrame(result.get("impacted_routes", []))
        if route_df.empty:
            st.success("No routes crossed the impact threshold for this simulation.")
        else:
            st.dataframe(
                route_df[["route_id", "route", "before_score", "after_score", "risk_delta", "after_band", "decision", "action"]],
                use_container_width=True,
                hide_index=True,
            )
            fingerprint = route_df[["route", "before_score", "after_score"]].melt(
                id_vars="route",
                value_vars=["before_score", "after_score"],
                var_name="State",
                value_name="Risk Score",
            )
            fig = px.bar(fingerprint, x="route", y="Risk Score", color="State", barmode="group", title="Digital Twin Risk Shift")
            st.plotly_chart(fig, use_container_width=True)

    with plan_tab:
        plan_df = pd.DataFrame(result.get("response_plan", []))
        if plan_df.empty:
            st.info("No response plan returned.")
        else:
            st.dataframe(plan_df, use_container_width=True, hide_index=True)
            p1_count = len(plan_df[plan_df["priority"] == "P1"]) if "priority" in plan_df else 0
            if p1_count:
                st.warning(f"{p1_count} P1 response actions need commander attention.")
            else:
                st.success("No P1 action required in this simulation.")

    with cargo_tab:
        v_col, c_col = st.columns(2)
        with v_col:
            st.markdown("#### Exposed Vessels")
            vessel_df = pd.DataFrame(result.get("impacted_vessels", []))
            if vessel_df.empty:
                st.success("No exposed vessels crossed the threshold.")
            else:
                st.dataframe(
                    vessel_df[["vessel", "nearest_port", "distance_nm", "cargo", "priority", "exposure_score", "recommendation"]],
                    use_container_width=True,
                    hide_index=True,
                )
        with c_col:
            st.markdown("#### Exposed Cargo")
            cargo_df = pd.DataFrame(result.get("cargo_exposure", []))
            if cargo_df.empty:
                st.success("No cargo records crossed the exposure threshold.")
            else:
                st.dataframe(
                    cargo_df[["vessel_name", "cargo", "cargo_value", "origin_port", "destination_port", "priority", "exposure_score", "control"]],
                    use_container_width=True,
                    hide_index=True,
                )

    with timeline_tab:
        timeline_df = pd.DataFrame(result.get("timeline", []))
        if timeline_df.empty:
            st.info("No timeline returned.")
        else:
            st.dataframe(timeline_df, use_container_width=True, hide_index=True)


def captain_order_color(verdict):
    verdict = str(verdict or "").upper()
    if "STOP" in verdict:
        return "#ef4444"
    if "ESCALATE" in verdict:
        return "#f97316"
    if "REROUTE" in verdict:
        return "#facc15"
    if "DELAY" in verdict:
        return "#38bdf8"
    return "#22c55e"


def captain_route_deck(plan):
    alternatives = list((plan or {}).get("alternatives", []) or [])
    route_rows = []
    for option in alternatives:
        geometry = option.get("geometry") or []
        if len(geometry) < 2:
            continue
        risk = float(option.get("risk_score", 0) or 0)
        recommended = bool(option.get("recommended"))
        route_rows.append({
            **option,
            "path": geometry,
            "color": [34, 197, 94, 235] if recommended else [239, 68, 68, 205] if risk >= 7 else [245, 158, 11, 190] if risk >= 5 else [56, 189, 248, 170],
            "width": 7 if recommended else 3,
        })
    zone_rows = []
    for zone in (plan or {}).get("global_context", {}).get("highest_watch_zones", []):
        if zone.get("lat") is None or zone.get("lon") is None:
            continue
        risk = float(zone.get("risk", 0) or 0)
        zone_rows.append({
            **zone,
            "radius": max(65000, float(zone.get("radius_nm", 80) or 80) * 1852),
            "color": [239, 68, 68, 58] if risk >= 8 else [245, 158, 11, 46],
            "line_color": [239, 68, 68, 165] if risk >= 8 else [245, 158, 11, 140],
        })
    layers = []
    if zone_rows:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=zone_rows,
            get_position="[lon, lat]",
            get_radius="radius",
            get_fill_color="color",
            get_line_color="line_color",
            line_width_min_pixels=2,
            stroked=True,
            filled=True,
            pickable=True,
        ))
    if route_rows:
        layers.append(pdk.Layer(
            "PathLayer",
            data=route_rows,
            get_path="path",
            get_color="color",
            get_width="width",
            width_min_pixels=2,
            rounded=True,
            pickable=True,
        ))
    recommended = (plan or {}).get("recommended") or {}
    geometry = recommended.get("geometry") or []
    if geometry:
        center_lon = sum(point[0] for point in geometry) / len(geometry)
        center_lat = sum(point[1] for point in geometry) / len(geometry)
    else:
        center_lat, center_lon = 17, 58
    return pdk.Deck(
        map_style=MAP_STYLE,
        layers=layers,
        initial_view_state=pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=1.15, pitch=28, bearing=-12),
        tooltip={
            "html": "<b>{route}{name}</b><br/>Risk: {risk_score}{risk}/10<br/>Distance: {distance_nm} nm<br/>{why}{note}",
            "style": {"backgroundColor": "#07111f", "color": "#f8fafc"},
        },
    )


def show_ai_captain():
    st.title("AI Captain")
    st.caption("The top command brain: one verdict, safest route, incident prediction, vessel drill-down, emergency war room, and audited actions.")
    if "captain_origin" not in st.session_state:
        st.session_state.captain_origin = "Mumbai"
    if "captain_destination" not in st.session_state:
        st.session_state.captain_destination = "Rotterdam"

    input_col1, input_col2, input_col3 = st.columns([1, 1, 0.72])
    with input_col1:
        origin = st.text_input("Origin port", key="captain_origin")
    with input_col2:
        destination = st.text_input("Destination port", key="captain_destination")
    with input_col3:
        st.write("")
        st.write("")
        refresh_captain = st.button("Refresh Captain", use_container_width=True, icon=":material/radar:")

    try:
        captain = api_get(f"/ai/captain?origin={quote(origin)}&destination={quote(destination)}", fresh=refresh_captain)
    except Exception as e:
        show_api_error("AI Captain", e)
        return

    verdict = captain.get("verdict", "UNKNOWN")
    color = captain_order_color(verdict)
    st.markdown(
        f"""
        <div class="captain-hero" style="--captain-color:{color};">
            <span class="captain-badge">AI CAPTAIN VERDICT</span>
            <h2>{safe_html(verdict)} - {safe_html(captain.get('captain_band', 'Unknown'))}</h2>
            <p>{safe_html(captain.get('captain_order', 'No captain order returned.'))}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    metrics = captain.get("metrics", {})
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    with m1:
        st.metric("Captain Score", f"{captain.get('captain_score', 0)}/100", captain.get("priority", "P3"))
    with m2:
        st.metric("No Action", f"{metrics.get('no_action_risk', 0)}/100")
    with m3:
        st.metric("With Controls", f"{metrics.get('controlled_risk', 0)}/100")
    with m4:
        st.metric("Incident", f"{metrics.get('incident_likelihood', 0)}/100")
    with m5:
        st.metric("AIS", "Live" if metrics.get("ais_connected") else "Fallback", f"{metrics.get('live_vessels', 0)} ships")
    with m6:
        st.metric("Data Quality", f"{metrics.get('data_quality', 0)}%")

    allow_captain_action = can("approve_actions") or can("manage_alert_workflows") or can("manage_vessels") or can("generate_reports")
    order_col, action_col = st.columns([1.25, 0.75])
    with order_col:
        st.markdown("### Why The Captain Chose This")
        for reason in captain.get("order_reasons", []):
            st.markdown(
                f"""
                <div class="captain-order-card" style="--captain-color:{color};">
                    <b>{safe_html(reason)}</b>
                </div>
                """,
                unsafe_allow_html=True,
            )
    with action_col:
        st.markdown("### Captain Controls")
        owner = st.text_input("Decision owner", value=current_role(), key="captain_owner")
        note = st.text_area("Decision note", value=captain.get("captain_order", ""), height=110, key="captain_note")
        if not allow_captain_action:
            st.warning(f"{current_role()} can review AI Captain output, but cannot execute command actions.")
        if st.button("Queue Captain Order", use_container_width=True, disabled=not allow_captain_action, icon=":material/bolt:"):
            try:
                result = api_post("/ai/captain/action", {
                    "order": verdict.lower().replace(" ", "_"),
                    "target": captain.get("focus_target"),
                    "owner": owner,
                    "note": note,
                    "priority": captain.get("priority"),
                    "origin": origin,
                    "destination": destination,
                }).json()
                st.success(f"Queued: {result.get('record', {}).get('subject', captain.get('focus_target'))}")
            except Exception as e:
                st.error(f"Could not queue captain order: {e}")
        if st.button("Create Emergency Incident", use_container_width=True, disabled=not allow_captain_action, icon=":material/report:"):
            try:
                result = api_post("/ai/captain/action", {
                    "order": "create_incident",
                    "target": captain.get("focus_target"),
                    "owner": owner,
                    "note": note,
                    "priority": captain.get("priority"),
                    "create_incident": True,
                    "origin": origin,
                    "destination": destination,
                }).json()
                st.warning(f"Incident created: {result.get('record', {}).get('title', captain.get('focus_target'))}")
            except Exception as e:
                st.error(f"Could not create emergency incident: {e}")
        if st.button("Generate Mission Pack", use_container_width=True, disabled=not can("generate_reports"), icon=":material/folder_zip:"):
            try:
                pack = api_get("/reports/mission-pack", fresh=True)
                st.success(f"Mission pack #{pack.get('report_id')} generated.")
                st.text_area("Mission pack", value=pack.get("content", ""), height=220)
            except Exception as e:
                st.error(f"Could not generate mission pack: {e}")

    route_tab, incident_tab, vessel_tab, war_tab, map_tab = st.tabs([
        "Global Route Optimizer",
        "Live Incident Prediction",
        "Ship Intelligence",
        "Emergency War Room",
        "Map & Trust",
    ])

    with route_tab:
        route_plan = captain.get("global_route")
        if not route_plan:
            st.warning(captain.get("route_error", "No route plan returned."))
        else:
            recommended = route_plan.get("recommended", {})
            st.success(
                f"Recommended route: {recommended.get('route')} | "
                f"Risk {recommended.get('risk_score')}/10 | {recommended.get('distance_nm')} nm"
            )
            st.caption(recommended.get("why", route_plan.get("model_note", "")))
            mode_rows = []
            for mode_name, option in (route_plan.get("captain_modes") or {}).items():
                mode_rows.append({
                    "Mode": mode_name.replace("_", " ").title(),
                    "Route": option.get("route"),
                    "Risk": option.get("risk_score"),
                    "Safety": option.get("safety_score"),
                    "Speed": option.get("speed_score"),
                    "Cost": option.get("cost_index"),
                })
            if mode_rows:
                st.dataframe(pd.DataFrame(mode_rows), use_container_width=True, hide_index=True)
            alternatives = pd.DataFrame(route_plan.get("alternatives", []))
            if not alternatives.empty:
                visible = [col for col in ["recommended", "route", "risk_score", "risk_band", "distance_nm", "detour_ratio", "safety_score", "speed_score", "cost_index", "captain_modes", "why"] if col in alternatives.columns]
                st.dataframe(alternatives[visible], use_container_width=True, hide_index=True)
            st.pydeck_chart(captain_route_deck(route_plan), use_container_width=True, height=420 if not st.session_state.get("mobile_performance_mode") else 310)

    with incident_tab:
        predictions = captain.get("incident_predictions", [])
        if not predictions:
            st.success("No incident prediction crossed the watch threshold.")
        else:
            pred_df = pd.DataFrame([
                {
                    "Priority": item.get("priority"),
                    "Category": item.get("category"),
                    "Likelihood": item.get("likelihood"),
                    "ETA Window": item.get("eta_window"),
                    "No Action Peak": item.get("no_action_peak"),
                    "With Controls": item.get("controlled_floor"),
                    "Reduction": item.get("risk_reduction"),
                    "Captain Solution": item.get("captain_solution"),
                }
                for item in predictions
            ])
            st.dataframe(pred_df, use_container_width=True, hide_index=True)
            timeline_rows = []
            for item in predictions[:5]:
                for point in item.get("timeline", []):
                    timeline_rows.append({
                        "Category": item.get("category"),
                        "Horizon": point.get("horizon"),
                        "No Action": point.get("score_no_action"),
                        "With Controls": point.get("score_with_controls"),
                    })
            if timeline_rows:
                line_df = pd.DataFrame(timeline_rows).melt(id_vars=["Category", "Horizon"], value_vars=["No Action", "With Controls"], var_name="Path", value_name="Risk")
                fig = px.line(line_df, x="Horizon", y="Risk", color="Category", line_dash="Path", markers=True, range_y=[0, 100], title="Incident Risk If Nobody Acts vs With Captain Controls")
                st.plotly_chart(fig, use_container_width=True)
            selected_prediction = st.selectbox("Open playbook", [item.get("category") for item in predictions], key="captain_prediction_select")
            selected = next((item for item in predictions if item.get("category") == selected_prediction), {})
            st.info(selected.get("trigger", "No trigger returned."))
            st.dataframe(pd.DataFrame({"Evidence": selected.get("evidence", [])}), use_container_width=True, hide_index=True)

    with vessel_tab:
        vessel_board = captain.get("vessel_board", [])
        vessel_df = pd.DataFrame(vessel_board)
        if vessel_df.empty:
            st.info("No vessel board returned.")
        else:
            visible = [col for col in ["priority", "vessel", "route", "nearest_port", "delay_risk", "cargo", "cargo_priority", "speed_knots", "eta_hours", "recommended_action"] if col in vessel_df.columns]
            st.dataframe(vessel_df[visible], use_container_width=True, hide_index=True)
            selected_vessel = st.selectbox("Inspect ship intelligence", vessel_df["vessel"].dropna().astype(str).tolist(), key="captain_vessel_select")
            try:
                intel = api_get(f"/vessels/intelligence?vessel_identifier={quote(selected_vessel)}", fresh=refresh_captain)
                st.markdown(
                    f"""
                    <div class="vessel-intel-card">
                        <b>{safe_html(selected_vessel)}</b>
                        <div>AI recommendation: {safe_html(intel.get('recommended_action'))}</div>
                        <div class="captain-meta">Risk {safe_html(intel.get('risk_score'))}/10 ({safe_html(intel.get('risk_band'))}) | Source: {safe_html(intel.get('source'))}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.dataframe(pd.DataFrame({"Evidence": intel.get("evidence", [])}), use_container_width=True, hide_index=True)
                timeline = pd.DataFrame(intel.get("timeline", []))
                if not timeline.empty:
                    st.dataframe(timeline.tail(20), use_container_width=True, hide_index=True)
            except Exception as e:
                st.caption(f"Ship drill-down unavailable: {e}")

    with war_tab:
        war_room = captain.get("emergency_war_room", {})
        st.metric("War Room Mode", war_room.get("mode", "Unknown"), war_room.get("response_window", "Today"))
        step_df = pd.DataFrame(war_room.get("steps", []))
        if not step_df.empty:
            st.dataframe(step_df, use_container_width=True, hide_index=True)
        gate_df = pd.DataFrame(war_room.get("decision_gates", []))
        if not gate_df.empty:
            st.markdown("### Release Gates")
            st.dataframe(gate_df, use_container_width=True, hide_index=True)
        st.markdown("### Communications")
        st.dataframe(pd.DataFrame({"Message": war_room.get("communications", [])}), use_container_width=True, hide_index=True)
        st.markdown("### Final Checks")
        st.dataframe(pd.DataFrame({"Check": captain.get("final_checks", [])}), use_container_width=True, hide_index=True)

    with map_tab:
        map_col, trust_col = st.columns([1.25, 0.75])
        with map_col:
            render_mission_overlay(captain.get("map_overlay", {}))
        with trust_col:
            trust = captain.get("trust", {})
            t1, t2 = st.columns(2)
            with t1:
                st.metric("Hardening", f"{trust.get('deployment_hardening', 0)}%")
            with t2:
                st.metric("Quality", f"{trust.get('data_quality', 0)}%")
            ais_status = trust.get("ais_status", {})
            st.metric("AIS Provider", ais_status.get("status", "unknown"), f"{ais_status.get('vessel_count', 0)} vessels")
            policy_rows = [{"Role": role, "Policy": policy} for role, policy in trust.get("role_policy", {}).items()]
            st.dataframe(pd.DataFrame(policy_rows), use_container_width=True, hide_index=True)
            explain = captain.get("explainability", {})
            st.caption(explain.get("method", "No captain explainability returned."))


def show_executive_command():
    st.title("Executive Command")
    try:
        brief = api_get("/executive/brief")
        mission = api_get("/ai/mission-control")
        war_room = api_get("/ai/war-room")
    except Exception as e:
        show_api_error("Executive command", e)
        return

    st.info(mission.get("commander_summary") or brief.get("commander_summary", "No command summary available."))
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Readiness", f"{brief.get('readiness_score', 0):.1f}%", brief.get("readiness_band"))
    with c2:
        st.metric("Data Quality", f"{brief.get('data_quality_score', 0)}%")
    with c3:
        st.metric("Critical Notes", brief.get("critical_notifications", 0))
    with c4:
        top_routes = brief.get("top_routes", [])
        st.metric("Peak Route", f"{top_routes[0].get('score', 0):.1f}/10" if top_routes else "n/a")

    st.markdown("### AI Mission Control")
    top_problem = mission.get("top_problem", {})
    mission_cols = st.columns(4)
    with mission_cols[0]:
        st.markdown(
            f"""
            <div class="mission-card">
                <b>Mission State</b>
                <div class="mission-score">{safe_html(mission.get('mission_state', 'Unknown'))}</div>
                <small>{safe_html(mission.get('mission_score', 0))}/100 pressure</small>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with mission_cols[1]:
        st.markdown(
            f"""
            <div class="mission-card">
                <b>Biggest Problem</b>
                <div class="mission-score">{safe_html(top_problem.get('lane', 'None'))}</div>
                <small>{safe_html(top_problem.get('signal', 'No signal'))}</small>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with mission_cols[2]:
        digest = mission.get("noise_reduced_digest", {})
        st.markdown(
            f"""
            <div class="mission-card">
                <b>Alert Noise Cut</b>
                <div class="mission-score">{safe_html(digest.get('noise_reduction', 0))}</div>
                <small>{safe_html(digest.get('raw_total', 0))} raw -> {safe_html(digest.get('compressed_total', 0))} targets</small>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with mission_cols[3]:
        st.markdown(
            f"""
            <div class="mission-card">
                <b>Incident Cards</b>
                <div class="mission-score">{len(mission.get('incident_cards', []))}</div>
                <small>Auto commander generated</small>
            </div>
            """,
            unsafe_allow_html=True,
        )

    priority_df = pd.DataFrame(mission.get("priorities", []))
    if not priority_df.empty:
        st.dataframe(priority_df[["priority", "lane", "score", "signal", "action", "page"]], use_container_width=True, hide_index=True)

    incident_col, action_col = st.columns([1, 1])
    with incident_col:
        st.markdown("### Auto Incident Commander")
        cards = mission.get("incident_cards", [])[:4]
        if cards:
            for card in cards:
                render_incident_card(card, key_prefix="executive")
        else:
            st.success("No auto incident cards need escalation.")
    with action_col:
        st.markdown("### Next Best Actions")
        for index, action in enumerate(mission.get("next_best_actions", []), start=1):
            st.markdown(f'<div class="action-step"><b>{index}.</b> {safe_html(action)}</div>', unsafe_allow_html=True)
        with st.expander("Why the AI chose this"):
            explain = mission.get("explainability", {})
            st.caption(explain.get("method", "No explainability returned."))
            st.dataframe(pd.DataFrame({"Inputs": explain.get("inputs", [])}), use_container_width=True, hide_index=True)

    st.markdown("### Autonomous War Room")
    wr1, wr2, wr3, wr4 = st.columns(4)
    with wr1:
        st.metric("Command Mode", war_room.get("command_mode", "Unknown"))
    with wr2:
        st.metric("Active Focus", war_room.get("active_focus", "Unknown"))
    with wr3:
        st.metric("Response Window", war_room.get("response_window", "Today"))
    with wr4:
        st.metric("Mission Score", f"{war_room.get('mission_score', 0)}/100")
    st.caption(war_room.get("active_signal", "No active signal."))

    playbook_df = pd.DataFrame(war_room.get("playbook", []))
    gate_df = pd.DataFrame(war_room.get("decision_gates", []))
    play_col, gate_col = st.columns([1.2, 0.8])
    with play_col:
        st.markdown("#### Timed Response Playbook")
        if not playbook_df.empty:
            st.dataframe(playbook_df, use_container_width=True, hide_index=True)
    with gate_col:
        st.markdown("#### Decision Gates")
        if not gate_df.empty:
            st.dataframe(gate_df, use_container_width=True, hide_index=True)

    with st.expander("War Room Impact Radius"):
        impacted = war_room.get("impacted_assets", {})
        impact_tabs = st.tabs(["Routes", "Vessels", "Alerts", "Automation"])
        with impact_tabs[0]:
            routes_df = pd.DataFrame(impacted.get("routes", []))
            st.dataframe(routes_df, use_container_width=True, hide_index=True)
        with impact_tabs[1]:
            vessels_df = pd.DataFrame(impacted.get("vessels", []))
            st.dataframe(vessels_df, use_container_width=True, hide_index=True)
        with impact_tabs[2]:
            alerts_df = pd.DataFrame(impacted.get("alerts", []))
            st.dataframe(alerts_df, use_container_width=True, hide_index=True)
        with impact_tabs[3]:
            automation_df = pd.DataFrame(war_room.get("automation_queue", []))
            st.dataframe(automation_df, use_container_width=True, hide_index=True)
        explain = war_room.get("explainability", {})
        st.caption(explain.get("method", "No War Room explainability returned."))

    st.markdown("### Command Action Console")
    command_tabs = st.tabs(["Actions", "Replay", "Role View", "Confidence", "Ports", "Cargo", "Self-Check"])
    with command_tabs[0]:
        automation_targets = [
            row.get("target")
            for row in war_room.get("automation_queue", [])
            if row.get("target")
        ]
        if top_problem.get("signal"):
            automation_targets.insert(0, top_problem.get("signal"))
        target_options = list(dict.fromkeys(automation_targets or ["Command"]))
        action_col1, action_col2, action_col3 = st.columns([1, 1, 1])
        with action_col1:
            command_target = st.selectbox("Action target", target_options, key="command_action_target")
            command_owner = st.text_input("Owner", value=current_role(), key="command_action_owner")
        with action_col2:
            command_priority = st.selectbox("Priority", ["P1", "P2", "P3"], index=0, key="command_action_priority")
            command_note = st.text_input("Action note", value="Owner assigned from War Room.", key="command_action_note")
        with action_col3:
            st.caption("Actions write to incidents, AI actions, reports, and audit logs.")
            allow_command_action = can("approve_actions") or can("manage_alert_workflows") or can("generate_reports")
            if not allow_command_action:
                st.warning(f"Command actions are disabled for role: {current_role()}.")
        b1, b2, b3, b4 = st.columns(4)
        with b1:
            if st.button("Assign Owner", use_container_width=True, disabled=not allow_command_action, icon=":material/person_add:"):
                result = run_command_action("assign_owner", command_target, command_owner, command_note, command_priority)
                st.success(f"Assigned: {result.get('target')}")
        with b2:
            if st.button("Create Incident", use_container_width=True, disabled=not allow_command_action, icon=":material/report:"):
                result = run_command_action("create_incident", command_target, command_owner, command_note, command_priority)
                st.success(f"Incident created: {result.get('target')}")
        with b3:
            if st.button("Daily Brief", use_container_width=True, disabled=not can("generate_reports"), icon=":material/article:"):
                result = run_command_action("generate_brief", "Daily command brief", command_owner, command_note, command_priority)
                st.success(f"Brief generated: #{result.get('record', {}).get('report_id')}")
        with b4:
            if st.button("Mission Pack", use_container_width=True, disabled=not can("generate_reports"), icon=":material/folder_zip:"):
                result = run_command_action("mission_pack", "Mission pack", command_owner, command_note, command_priority)
                st.success(f"Mission pack generated: #{result.get('record', {}).get('report_id')}")

        try:
            incident_packet = api_get("/incidents?status=open&limit=25")
            incident_df = pd.DataFrame(incident_packet.get("events", []))
            if not incident_df.empty:
                st.markdown("#### Resolve / Escalate Incident")
                incident_labels = [
                    f"#{row['id']} {row['title']} ({row['status']})"
                    for _, row in incident_df.iterrows()
                ]
                selected_label = st.selectbox("Open incident", incident_labels, key="incident_workflow_select")
                selected_id = int(selected_label.split(" ", 1)[0].replace("#", ""))
                status_col1, status_col2, status_col3 = st.columns([0.8, 1, 0.8])
                with status_col1:
                    next_status = st.selectbox("Status", ["investigating", "escalated", "resolved", "open"], key="incident_workflow_status")
                with status_col2:
                    workflow_note = st.text_input("Workflow note", value="Updated from command console.", key="incident_workflow_note")
                with status_col3:
                    st.write("")
                    if st.button("Update Incident", use_container_width=True, disabled=not allow_command_action, icon=":material/task_alt:"):
                        response = api_post(
                            f"/incidents/{selected_id}/status",
                            {"status": next_status, "owner": command_owner, "note": workflow_note},
                        ).json()
                        st.success(f"Incident #{response.get('id')} moved to {response.get('status')}.")
        except Exception as e:
            st.caption(f"Incident workflow unavailable: {e}")

    with command_tabs[1]:
        try:
            timeline = api_get("/ai/decision-timeline?limit=120")
            st.metric("Replay Events", timeline.get("summary", {}).get("events", 0), f"{timeline.get('summary', {}).get('p1', 0)} P1")
            timeline_df = pd.DataFrame(timeline.get("events", []))
            if not timeline_df.empty:
                st.dataframe(timeline_df, use_container_width=True, hide_index=True)
        except Exception as e:
            st.caption(f"Decision timeline unavailable: {e}")

    with command_tabs[2]:
        try:
            role_view = api_get(f"/ai/role-view?role={quote(current_role())}")
            st.info(role_view.get("summary", "No role summary returned."))
            st.caption("Focus: " + ", ".join(role_view.get("focus", [])))
            role_df = pd.DataFrame(role_view.get("priorities", []))
            if not role_df.empty:
                st.dataframe(role_df, use_container_width=True, hide_index=True)
        except Exception as e:
            st.caption(f"Role view unavailable: {e}")

    with command_tabs[3]:
        try:
            heatmap = api_get("/ai/confidence-heatmap")
            st.metric("Average AI Confidence", f"{heatmap.get('summary', {}).get('average_confidence', 0)}%")
            heat_df = pd.DataFrame(heatmap.get("rows", []))
            if not heat_df.empty:
                fig = px.density_heatmap(
                    heat_df,
                    x="area",
                    y="name",
                    z="confidence",
                    color_continuous_scale="Viridis",
                    title="AI Confidence Heatmap",
                )
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(heat_df, use_container_width=True, hide_index=True)
        except Exception as e:
            st.caption(f"Confidence heatmap unavailable: {e}")

    with command_tabs[4]:
        try:
            ports = api_get("/ports/congestion")
            port_df = pd.DataFrame(ports.get("ports", []))
            if not port_df.empty:
                st.metric("Congestion Source", ports.get("source", "unknown"))
                fig = px.bar(
                    port_df,
                    x="port",
                    y="congestion_score",
                    color="band",
                    title="Port Congestion Control",
                    range_y=[0, 100],
                )
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(port_df, use_container_width=True, hide_index=True)
        except Exception as e:
            st.caption(f"Port congestion unavailable: {e}")

    with command_tabs[5]:
        try:
            custody = api_get("/cargo/custody?limit=80")
            summary = custody.get("summary", {})
            cst1, cst2, cst3 = st.columns(3)
            with cst1:
                st.metric("Tracked Cargo", summary.get("tracked", 0))
            with cst2:
                st.metric("P1 Custody", summary.get("p1", 0))
            with cst3:
                st.metric("Needs AIS", summary.get("needs_ais", 0))
            custody_df = pd.DataFrame(custody.get("chain", []))
            if not custody_df.empty:
                st.dataframe(custody_df, use_container_width=True, hide_index=True)
        except Exception as e:
            st.caption(f"Cargo custody unavailable: {e}")

    with command_tabs[6]:
        try:
            self_check = api_get("/ai/self-check")
            st.metric("AI Self-Check", self_check.get("overall", "unknown").title())
            check_df = pd.DataFrame(self_check.get("checks", []))
            if not check_df.empty:
                st.dataframe(check_df, use_container_width=True, hide_index=True)
            if self_check.get("missing"):
                st.warning("Needs attention: " + ", ".join(self_check.get("missing", [])))
            st.caption(self_check.get("model_note", ""))
        except Exception as e:
            st.caption(f"AI self-check unavailable: {e}")

    route_col, vessel_col = st.columns(2)
    with route_col:
        st.markdown("### Top Strategic Routes")
        route_df = pd.DataFrame(brief.get("top_routes", []))
        if route_df.empty:
            st.info("No route assessment available.")
        else:
            st.dataframe(route_df[["route", "score", "band", "confidence", "decision", "action"]], use_container_width=True, hide_index=True)
    with vessel_col:
        st.markdown("### Most Exposed Vessels")
        vessel_df = pd.DataFrame(brief.get("top_vessels", []))
        if vessel_df.empty:
            st.info("No vessel predictions available.")
        else:
            st.dataframe(vessel_df[["vessel", "nearest_port", "eta_hours", "delay_risk", "delay_band", "recommended_action"]], use_container_width=True, hide_index=True)

    action_df = pd.DataFrame(brief.get("top_actions", []))
    st.markdown("### Commander Action Stack")
    if action_df.empty:
        st.success("No high-priority AI actions are queued.")
    else:
        st.dataframe(action_df[["priority", "subject", "action_type", "recommendation", "owner", "status"]], use_container_width=True, hide_index=True)

    if st.button("Generate Executive Daily Brief", use_container_width=True, disabled=not can("generate_reports"), icon=":material/article:"):
        try:
            daily = api_get("/reports/daily-brief", fresh=True)
            st.success(f"Daily brief #{daily.get('report_id')} generated.")
            st.text_area("Daily command brief", value=daily.get("content", ""), height=260)
        except Exception as e:
            st.error(f"Could not generate daily brief: {e}")


def voyage_control_tower_deck(tower):
    route_rows = []
    for route in tower.get("map", {}).get("routes", []):
        geometry = route.get("geometry") or []
        if len(geometry) < 2:
            continue
        current_risk = float(route.get("current_risk", 0) or 0)
        route_rows.append({
            **route,
            "name": route.get("route", "Route"),
            "path": geometry,
            "risk": current_risk,
            "color": [239, 68, 68, 220] if current_risk >= 8 else [245, 158, 11, 210] if current_risk >= 6 else [34, 211, 238, 190],
            "width": 7 if current_risk >= 8 else 5 if current_risk >= 6 else 3,
        })
    vessel_rows = []
    for vessel in tower.get("map", {}).get("vessels", []):
        lat = vessel.get("display_position_lat", vessel.get("position_lat"))
        lon = vessel.get("display_position_lon", vessel.get("position_lon"))
        if lat is None or lon is None:
            continue
        priority = str(vessel.get("priority", "P3"))
        score = float(vessel.get("anomaly_score", 0) or 0)
        vessel_rows.append({
            **vessel,
            "lat": lat,
            "lon": lon,
            "name": vessel.get("vessel", "Vessel"),
            "score": score,
            "motion_source": vessel.get("motion_source", "live feed"),
            "color": [239, 68, 68, 235] if priority == "P1" else [245, 158, 11, 225] if priority == "P2" else [45, 212, 191, 210],
            "radius": max(26000, min(105000, 23000 + score * 900)),
        })
    vessel_trails = [
        {"name": row.get("name"), "path": row.get("motion_trail"), "color": [191, 219, 254, 115]}
        for row in vessel_rows
        if isinstance(row.get("motion_trail"), list) and len(row.get("motion_trail")) >= 2
    ]
    layers = []
    if route_rows:
        layers.append(pdk.Layer(
            "PathLayer",
            data=route_rows,
            get_path="path",
            get_color="color",
            get_width="width",
            width_min_pixels=2,
            rounded=True,
            pickable=True,
        ))
    if vessel_trails:
        layers.append(pdk.Layer(
            "PathLayer",
            data=vessel_trails,
            get_path="path",
            get_color="color",
            get_width=4,
            width_min_pixels=1,
            rounded=True,
        ))
    if vessel_rows:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=vessel_rows,
            get_position="[lon, lat]",
            get_fill_color="color",
            get_radius="radius",
            stroked=True,
            get_line_color=[248, 250, 252, 230],
            line_width_min_pixels=2,
            pickable=True,
        ))
        layers.append(pdk.Layer(
            "TextLayer",
            data=vessel_rows,
            get_position="[lon, lat]",
            get_text="priority",
            get_color=[255, 255, 255, 245],
            get_size=14,
            get_pixel_offset=[0, 0],
            get_alignment_baseline="'center'",
            get_text_anchor="'middle'",
        ))
    return pdk.Deck(
        map_style=MAP_STYLE,
        layers=layers,
        initial_view_state=pdk.ViewState(latitude=19, longitude=38, zoom=1.05, pitch=48, bearing=-24),
        tooltip={
            "html": (
                "<b>{name}</b><br/>"
                "Risk/Score: {risk}{score}<br/>"
                "Priority/Band: {priority}{band}<br/>"
                "Action: {recommended_action}{recommendation}<br/>Motion: {motion_source}"
            ),
            "style": {"backgroundColor": "#020617", "color": "#e0f2fe"},
        },
    )


def control_tower_action(target, action, owner, note, priority="P2", action_id=None):
    payload = {
        "target": target,
        "action": action,
        "owner": owner,
        "note": note,
        "priority": priority,
    }
    if action_id:
        payload["action_id"] = action_id
    return api_post("/ai/voyage-control-tower/action", payload).json()


def render_control_tower_plan(plan, allow_control, owner, note):
    if not plan:
        st.success("Control Tower is in cruise mode. No intervention is currently required.")
        return
    for index, item in enumerate(plan):
        priority = str(item.get("priority", "P3")).upper()
        color = incident_color(priority)
        card_col, action_col = st.columns([1.4, 0.42])
        with card_col:
            st.markdown(
                f"""
                <div class="tower-plan-card" style="--tower-color:{color};">
                    <span class="severity-chip" style="--chip-color:{color};">{safe_html(priority)}</span>
                    <b>{safe_html(item.get('lane'))}: {safe_html(item.get('target'))}</b>
                    <div>{safe_html(item.get('action'))}</div>
                    <div class="tower-plan-meta">
                        Owner: {safe_html(item.get('owner'))} | Timebox: {safe_html(item.get('timebox'))}
                    </div>
                    <div class="tower-plan-meta">{safe_html(item.get('evidence'))}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with action_col:
            st.write("")
            st.write("")
            if st.button("Queue", key=f"tower_queue_{index}", use_container_width=True, disabled=not allow_control):
                try:
                    result = control_tower_action(
                        item.get("target", "Global network"),
                        "queue_action",
                        owner,
                        note or item.get("action", ""),
                        priority,
                    )
                    st.success(f"Queued: {result.get('record', {}).get('subject', item.get('target'))}")
                except Exception as e:
                    st.error(f"Could not queue action: {e}")


def show_voyage_control_tower():
    st.title("Voyage Control Tower")
    st.caption("Autonomous Maritime Command OS: anomaly detection, route-mode choice, AI action approval, timeline, and reliability in one brain.")
    try:
        tower = api_get("/ai/voyage-control-tower", fresh=True)
    except Exception as e:
        show_api_error("Voyage Control Tower", e)
        return

    primary = tower.get("primary_decision", {})
    st.markdown(
        f"""
        <div class="tower-hero">
            <span class="tower-badge">{safe_html(tower.get('mode'))}</span>
            <h2>{safe_html(primary.get('target', 'Global network'))}</h2>
            <p>{safe_html(tower.get('summary'))}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("Control Score", f"{tower.get('control_score', 0)}/100")
    with c2:
        st.metric("Watch Window", tower.get("watch_window", "Now"))
    with c3:
        st.metric("Vessels", tower.get("vessels_tracked", 0), tower.get("vessel_source", "feed"))
    with c4:
        st.metric("Anomalies", len(tower.get("anomalies", [])))
    with c5:
        st.metric("Reliability", f"{tower.get('reliability', {}).get('score', 0)}%", tower.get("reliability", {}).get("band", ""))

    allow_control = can("approve_actions") or can("manage_alert_workflows") or can("manage_vessels") or can("generate_reports")
    owner_default = current_role() if current_role() != "Public" else "Command desk"
    action_col, map_col = st.columns([0.78, 1.25])
    with action_col:
        st.markdown(
            f"""
            <div class="tower-decision">
                <span class="severity-chip" style="--chip-color:{incident_color(primary.get('priority', 'P3'))};">{safe_html(primary.get('priority', 'P3'))}</span>
                <b>{safe_html(primary.get('action', 'Maintain control watch.'))}</b>
                <div class="tower-plan-meta">Owner: {safe_html(primary.get('owner'))} | Timebox: {safe_html(primary.get('timebox'))}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        owner = st.text_input("Control owner", value=owner_default, key="tower_owner")
        note = st.text_area("Command note", value=primary.get("action", ""), height=90, key="tower_note")
        btn1, btn2 = st.columns(2)
        with btn1:
            if st.button("Queue Action", use_container_width=True, disabled=not allow_control):
                try:
                    result = control_tower_action(primary.get("target", "Global network"), "queue_action", owner, note, primary.get("priority", "P2"))
                    st.success(f"Queued: {result.get('record', {}).get('subject')}")
                except Exception as e:
                    st.error(f"Control action failed: {e}")
        with btn2:
            if st.button("Hold / Incident", use_container_width=True, disabled=not allow_control):
                try:
                    result = control_tower_action(primary.get("target", "Global network"), "hold_route", owner, note, primary.get("priority", "P1"))
                    st.warning(f"Incident created: {result.get('incident', {}).get('title', primary.get('target'))}")
                except Exception as e:
                    st.error(f"Hold failed: {e}")
        if not allow_control:
            st.info(f"{current_role()} can review Control Tower output, but cannot execute command actions.")
    with map_col:
        st.pydeck_chart(voyage_control_tower_deck(tower), use_container_width=True, height=360 if st.session_state.get("mobile_performance_mode") else 500)

    scores = pd.DataFrame([tower.get("scores", {})])
    if not scores.empty:
        st.caption("Control score components")
        st.dataframe(scores, use_container_width=True, hide_index=True)

    plan_tab, anomaly_tab, route_tab, timeline_tab, queue_tab = st.tabs([
        "Autonomous Plan",
        "Vessel Anomalies",
        "Route Modes",
        "Timeline",
        "Queue & Trust",
    ])
    with plan_tab:
        render_control_tower_plan(tower.get("autonomous_plan", []), allow_control, owner, note)
    with anomaly_tab:
        anomalies = pd.DataFrame(tower.get("anomalies", []))
        if anomalies.empty:
            st.success("No vessel anomaly crossed the control threshold.")
        else:
            visible = [col for col in ["priority", "vessel", "anomaly_score", "anomaly_type", "speed_knots", "nearest_port", "cargo", "cargo_priority", "cargo_verified", "recommended_action"] if col in anomalies.columns]
            st.dataframe(anomalies[visible], use_container_width=True, hide_index=True)
    with route_tab:
        route_modes = pd.DataFrame(tower.get("route_modes", []))
        if route_modes.empty:
            st.info("No route-mode comparisons are available yet.")
        else:
            visible = [col for col in ["route", "current_risk", "safest_route", "safest_risk", "fastest_route", "lowest_cost_route", "balanced_route", "risk_delta_if_safest", "recommendation"] if col in route_modes.columns]
            st.dataframe(route_modes[visible], use_container_width=True, hide_index=True)
            selected = st.selectbox("Inspect route options", route_modes["route"].tolist(), key="tower_route_options")
            selected_row = next((row for row in tower.get("route_modes", []) if row.get("route") == selected), {})
            options_df = pd.DataFrame(selected_row.get("options", []))
            if not options_df.empty:
                st.dataframe(options_df, use_container_width=True, hide_index=True)
    with timeline_tab:
        timeline = pd.DataFrame(tower.get("timeline", []))
        if not timeline.empty:
            plot_df = timeline.melt(id_vars=["time", "event"], value_vars=["risk_if_idle", "risk_if_controlled"], var_name="Path", value_name="Risk")
            fig = px.line(plot_df, x="time", y="Risk", color="Path", markers=True, title="If Nobody Acts vs Control Tower Plan", range_y=[0, 100])
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(timeline, use_container_width=True, hide_index=True)
    with queue_tab:
        q1, q2 = st.columns(2)
        with q1:
            st.markdown("### Approval Queue")
            queue = tower.get("approval_queue", [])
            if not queue:
                st.success("No active AI actions waiting.")
            for item in queue[:6]:
                color = incident_color(item.get("priority"))
                st.markdown(
                    f"""
                    <div class="tower-plan-card" style="--tower-color:{color};">
                        <span class="severity-chip" style="--chip-color:{color};">{safe_html(item.get('priority'))}</span>
                        <b>{safe_html(item.get('subject'))}</b>
                        <div>{safe_html(item.get('recommendation'))}</div>
                        <div class="tower-plan-meta">{safe_html(item.get('owner'))} | {safe_html(item.get('status'))}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                approve_col, complete_col = st.columns(2)
                with approve_col:
                    if st.button("Approve", key=f"tower_approve_{item.get('id')}", use_container_width=True, disabled=not can("approve_actions")):
                        try:
                            control_tower_action(item.get("subject"), "approve_action", owner, "Approved from Voyage Control Tower.", item.get("priority"), item.get("id"))
                            st.success("Approved.")
                        except Exception as e:
                            st.error(f"Could not approve: {e}")
                with complete_col:
                    if st.button("Complete", key=f"tower_complete_{item.get('id')}", use_container_width=True, disabled=not can("approve_actions")):
                        try:
                            control_tower_action(item.get("subject"), "complete_action", owner, "Completed from Voyage Control Tower.", item.get("priority"), item.get("id"))
                            st.success("Completed.")
                        except Exception as e:
                            st.error(f"Could not complete: {e}")
        with q2:
            st.markdown("### Trust & Explainability")
            reliability_checks = pd.DataFrame(tower.get("reliability", {}).get("checks", []))
            if not reliability_checks.empty:
                st.dataframe(reliability_checks, use_container_width=True, hide_index=True)
            st.dataframe(pd.DataFrame({"Explainability": tower.get("explainability", [])}), use_container_width=True, hide_index=True)


def show_strategic_autopilot():
    st.title("Strategic Autopilot")
    st.caption("The final command brain: predicts what happens if nobody acts, recommends the smallest safe intervention plan, and writes audited actions for verified roles.")
    try:
        autopilot = api_get("/ai/strategic-autopilot")
    except Exception as e:
        show_api_error("Strategic Autopilot", e)
        return

    projection = autopilot.get("risk_projection", {})
    st.info(autopilot.get("summary", "No strategic summary returned."))
    a1, a2, a3, a4, a5 = st.columns(5)
    with a1:
        st.metric("Mode", autopilot.get("mode", "Unknown"))
    with a2:
        st.metric("No Action Risk", f"{projection.get('without_autopilot', 0)}/100")
    with a3:
        st.metric("With Plan", f"{projection.get('with_autopilot', 0)}/100", f"-{projection.get('estimated_reduction', 0)}")
    with a4:
        st.metric("Confidence", f"{projection.get('confidence', 0)}%")
    with a5:
        st.metric("Interventions", len(autopilot.get("interventions", [])))

    trajectory = pd.DataFrame(autopilot.get("trajectory", []))
    if not trajectory.empty:
        plot_df = trajectory.melt(
            id_vars=["time", "event"],
            value_vars=["without_autopilot", "with_autopilot"],
            var_name="Path",
            value_name="Projected Risk",
        )
        fig = px.line(
            plot_df,
            x="time",
            y="Projected Risk",
            color="Path",
            markers=True,
            title="Autopilot Risk Trajectory",
            range_y=[0, 100],
        )
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(trajectory, use_container_width=True, hide_index=True)

    allow_execute = can("approve_actions") or can("manage_alert_workflows") or can("generate_reports")
    owner = st.text_input("Execution owner", value=current_role(), key="strategic_autopilot_owner")
    note = st.text_input("Execution note", value="Queued from Strategic Autopilot.", key="strategic_autopilot_note")
    if not allow_execute:
        st.warning(f"Autopilot execution is disabled for role: {current_role()}. You can still review the plan.")

    st.markdown("### Intervention Plan")
    interventions = autopilot.get("interventions", [])
    if not interventions:
        st.success("No intervention required. Autopilot is in cruise mode.")
    for index, intervention in enumerate(interventions):
        color, label = severity_tone("critical" if intervention.get("priority") == "P1" else "warning" if intervention.get("priority") == "P2" else "info")
        card_col, execute_col = st.columns([1.45, 0.45])
        with card_col:
            st.markdown(
                f"""
                <div class="notification-card" style="--note-color:{color}; --chip-color:{color};">
                    <span class="severity-chip">{label}</span>
                    <b>{safe_html(intervention.get('lane'))}: {safe_html(intervention.get('target'))}</b>
                    <div>{safe_html(intervention.get('action'))}</div>
                    <div class="notification-meta">
                        Owner: {safe_html(intervention.get('owner'))} | Timebox: {safe_html(intervention.get('timebox'))} |
                        Expected risk reduction: {safe_html(intervention.get('expected_risk_reduction'))}/100
                    </div>
                    <div class="notification-meta">{safe_html(intervention.get('evidence'))}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with execute_col:
            st.write("")
            st.write("")
            if st.button("Execute", key=f"autopilot_execute_{index}", use_container_width=True, disabled=not allow_execute, icon=":material/bolt:"):
                try:
                    result = api_post("/ai/strategic-autopilot/execute", {
                        "intervention_id": intervention.get("id"),
                        "owner": owner,
                        "note": note,
                    }).json()
                    st.success(f"{result.get('status', 'queued').replace('_', ' ').title()}: {intervention.get('target')}")
                except Exception as e:
                    st.error(f"Autopilot execution failed: {e}")

    shield_tab, blast_tab, trust_tab, map_tab = st.tabs(["Route Shield", "Blast Radius", "Trust", "Command Map"])
    with shield_tab:
        shield = pd.DataFrame([
            {
                "route": item.get("route"),
                "risk": item.get("risk"),
                "band": item.get("band"),
                "decision": item.get("decision"),
                "best_mode": item.get("best_mode"),
                "best_risk": item.get("best_risk"),
            }
            for item in autopilot.get("route_shield", [])
        ])
        if shield.empty:
            st.info("No route shield recommendations returned.")
        else:
            st.dataframe(shield, use_container_width=True, hide_index=True)
            route_names = shield["route"].dropna().astype(str).tolist()
            selected_route = st.selectbox("Inspect alternatives", route_names, key="autopilot_route_shield_select") if route_names else None
            if selected_route:
                selected = next((item for item in autopilot.get("route_shield", []) if item.get("route") == selected_route), {})
                alt_df = pd.DataFrame(selected.get("alternatives", []))
                if not alt_df.empty:
                    st.dataframe(alt_df, use_container_width=True, hide_index=True)

    with blast_tab:
        blast = autopilot.get("blast_radius", {})
        b1, b2, b3, b4, b5, b6 = st.columns(6)
        with b1:
            st.metric("P1 Actions", blast.get("p1_actions", 0))
        with b2:
            st.metric("Incidents", blast.get("open_incidents", 0))
        with b3:
            st.metric("Critical Notes", blast.get("critical_notifications", 0))
        with b4:
            st.metric("High Routes", blast.get("high_risk_routes", 0))
        with b5:
            st.metric("Delay Vessels", blast.get("delay_risk_vessels", 0))
        with b6:
            st.metric("P1 Cargo", blast.get("p1_cargo", 0))

    with trust_tab:
        trust = autopilot.get("trust", {})
        t1, t2, t3 = st.columns(3)
        with t1:
            st.metric("Data Quality", f"{trust.get('data_quality', 0)}%")
        with t2:
            st.metric("Hardening", f"{trust.get('deployment_hardening', 0)}%")
        with t3:
            st.metric("AISStream", "Connected" if trust.get("aisstream_connected") else "Fallback")
        st.dataframe(pd.DataFrame({"Explainability": trust.get("explainability", [])}), use_container_width=True, hide_index=True)

    with map_tab:
        render_mission_overlay(autopilot.get("map_overlay", {}))


def show_command_copilot():
    st.markdown(
        """
<style>
.copilot-header {
    background: rgba(15, 23, 42, 0.74);
    border: 1px solid rgba(148, 163, 184, 0.22);
    border-radius: 8px;
    padding: 1.08rem;
    margin-bottom: 1rem;
    box-shadow: none;
    position: relative;
    overflow: hidden;
}
.copilot-header::before {
    display: none;
}
.copilot-header > div {
    position: relative;
    z-index: 1;
}
.copilot-title {
    font-size: 1.65rem;
    font-weight: 820;
    color: #f8fafc;
    text-shadow: none;
    margin-bottom: 0.35rem;
    letter-spacing: 0;
}
.copilot-subtitle {
    color: #cbd5e1;
    font-size: 0.98rem;
    line-height: 1.5;
}
.solver-hero {
    background: rgba(15, 23, 42, 0.58);
    border-left: 3px solid #14b8a6;
    padding: 0.78rem 0.9rem;
    border-radius: 8px;
    margin-top: 0.85rem;
}
.solver-hero b {
    color: #99f6e4;
    display: block;
    margin-bottom: 0.25rem;
    font-size: 1rem;
}
.solver-hero span {
    color: #94a3b8;
}
.action-step {
    background: rgba(15, 23, 42, 0.5);
    border: 1px solid rgba(148, 163, 184, 0.18);
    border-radius: 8px;
    padding: 0.72rem;
    margin-bottom: 0.58rem;
    color: #e2e8f0;
}
.action-step b {
    color: #99f6e4;
    margin-right: 0.5rem;
}
.solver-answer {
    background: rgba(15, 23, 42, 0.68);
    border: 1px solid rgba(45, 212, 191, 0.28);
    border-radius: 8px;
    padding: 1rem;
    margin: 1rem 0;
    box-shadow: none;
}
.solver-chip {
    display: inline-block;
    background: rgba(20, 184, 166, 0.14);
    color: #99f6e4;
    padding: 0.22rem 0.62rem;
    border-radius: 6px;
    font-size: 0.75rem;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0;
    margin-bottom: 0.65rem;
    border: 1px solid rgba(45, 212, 191, 0.28);
}
.solver-answer h3 {
    color: #f8fafc;
    margin: 0;
    font-size: 1.08rem;
    line-height: 1.45;
}
</style>
<div class="copilot-header">
<div>
<div class="copilot-title">AI Problem Solver</div>
<div class="copilot-subtitle">Role-aware maritime Copilot for route safety, AIS/API issues, cargo exposure, war-zone risk, hijack/piracy risk, alerts, and deployment readiness.</div>
<div class="solver-hero">
<b>Strictly Operational Intelligence.</b>
<span>Describe the operational problem. The AI returns a decision, risk levels, evidence, and an execution plan without drifting into unrelated chat.</span>
</div>
</div>
</div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("🌍 Global Safest Route Planner", expanded=True):
        st.caption("Try: Mumbai to Rotterdam, Singapore to New York, Shanghai to Los Angeles, Busan to Vancouver, Sydney to Auckland.")
        route_col1, route_col2, route_col3 = st.columns([1, 1, 0.8])
        with route_col1:
            global_origin = st.text_input("Origin port", value="Mumbai")
        with route_col2:
            global_destination = st.text_input("Destination port", value="Rotterdam")
        with route_col3:
            st.write("")
            st.write("")
            run_global_route = st.button("Find Safest Route", use_container_width=True)
        if run_global_route:
            try:
                with st.spinner("AI calculating safest global route..."):
                    plan = api_get(f"/copilot/global-route?origin={quote(global_origin)}&destination={quote(global_destination)}")
                recommended = plan.get("recommended", {})
                if recommended:
                    st.success(
                        f"Safest route: {recommended.get('route')} | "
                        f"Risk {recommended.get('risk_score')}/10 ({recommended.get('risk_band')}) | "
                        f"{recommended.get('distance_nm')} nm"
                    )
                    st.info(f"**AI Reasoning:** {recommended.get('why', 'No explanation returned.')}")
                alternatives = pd.DataFrame(plan.get("alternatives", []))
                if not alternatives.empty:
                    st.markdown("#### Alternative Routes Evaluated")
                    st.dataframe(
                        alternatives[["recommended", "route", "risk_score", "risk_band", "distance_nm", "detour_ratio", "why"]],
                        use_container_width=True,
                        hide_index=True,
                    )
                st.caption(plan.get("model_note", ""))
            except Exception as e:
                st.error(f"Could not plan global route: {e}")

    topic_options = [
        "Auto",
        "Route safety",
        "Vessel ETA / delay",
        "Cargo exposure",
        "Threat alerts",
        "Risk forecast",
        "AIS / live data",
        "Notifications",
        "Settings / access",
        "Fleet operations",
        "Reports / data quality",
    ]
    examples = [
        ("Route safety", "Find the safest route from Mumbai to Rotterdam and explain the watch zones."),
        ("War risk", "War risk is rising near the Red Sea. Which safer corridor and controls should we use?"),
        ("Hijack risk", "A high-value cargo vessel may cross a piracy or hijack watch zone. What should command do?"),
        ("Natural risk", "A storm may hit the route before arrival. Predict the risk level and safest action."),
        ("AIS live data", "AIS feed is connected but some vessels look stale or stopped. What should I check?"),
        ("Deploy readiness", "Before deploying this project, what reliability, data quality, and security issues should I review?"),
    ]
    if "problem_solver_prompt" not in st.session_state:
        st.session_state.problem_solver_prompt = examples[0][1]
    if "problem_solver_topic" not in st.session_state:
        st.session_state.problem_solver_topic = "Auto"

    st.markdown("### 🧠 Scenario Templates")
    template_cols = st.columns(3)
    for index, (label, text) in enumerate(examples):
        with template_cols[index % 3]:
            if st.button(label, key=f"problem_template_{index}", use_container_width=True):
                st.session_state.problem_solver_prompt = text
                st.session_state.problem_solver_topic = "Auto"
                st.rerun()

    input_col, guide_col = st.columns([1.2, 0.8])
    with input_col:
        selected_topic = st.selectbox("Topic Boundary Restriction", topic_options, key="problem_solver_topic")
        problem = st.text_area(
            "Operational Problem Description",
            key="problem_solver_prompt",
            height=150,
            placeholder="Example: AIS vessels near Rotterdam are stale and cargo P1 route release is due in 2 hours.",
        )
        solve_now = st.button("Initialize AI Diagnostics", type="primary", use_container_width=True, icon=":material/psychology:")
    with guide_col:
        st.info("Capabilities: route choices, safest corridors, AIS/API issues, cargo exposure, natural risk, hijack/piracy, war/geopolitical problems, notifications, deployment, and access roles.")
        st.warning("Strict rule: general small talk and non-maritime questions are rejected by the Copilot API.")

    if solve_now:
        if not problem.strip():
            st.warning("Describe the operational problem first.")
        else:
            try:
                with st.spinner("AI Copilot is analyzing live intelligence data..."):
                    st.session_state.problem_solver_result = api_post(
                        "/copilot/problem-solver",
                        {
                            "problem": problem,
                            "topic": selected_topic,
                            "role": current_role(),
                        },
                    ).json()
            except Exception as e:
                show_api_error("AI Problem Solver", e)
                return

    result = st.session_state.get("problem_solver_result")
    if not result:
        return

    st.markdown("<hr style='border-color: rgba(56, 189, 248, 0.2); margin: 2rem 0;'>", unsafe_allow_html=True)
    st.markdown("### 🤖 Intelligence Report")

    severity = str(result.get("severity", "info")).lower()
    if result.get("status") == "off_topic":
        st.warning(result.get("answer", "This problem is outside the configured maritime topics."))
    elif severity == "critical":
        st.error(f"🚨 **CRITICAL ALERT:** {result.get('answer', 'Critical issue detected.')}")
    elif severity == "watch":
        st.warning(f"⚠️ **WATCH ITEM:** {result.get('answer', 'Watch issue detected.')}")
    elif severity == "normal":
        st.success(f"✅ **ALL CLEAR:** {result.get('answer', 'No critical issue detected.')}")
    else:
        st.info(f"ℹ️ **ANALYSIS:** {result.get('answer', 'Problem reviewed.')}")

    metric_cols = st.columns(4)
    with metric_cols[0]:
        st.metric("Subject Domain", result.get("topic", "Unknown"))
    with metric_cols[1]:
        st.metric("Assessed Severity", severity.title())
    with metric_cols[2]:
        st.metric("AI Confidence", f"{result.get('confidence', 0)}%")
    with metric_cols[3]:
        st.metric("Recommended View", result.get("open_page", "Command Copilot"))

    decision = result.get("recommended_decision")
    if decision:
        st.markdown(
            f"""
<div class="solver-answer">
<span class="solver-chip">Recommended Command Decision</span>
<h3>{safe_html(decision)}</h3>
</div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown(
        f"""
<div class="solver-answer">
<span class="solver-chip">AI Field Decision</span>
<h3>{safe_html(result.get("answer", "No decision returned."))}</h3>
</div>
        """,
        unsafe_allow_html=True,
    )

    risk_levels = pd.DataFrame(result.get("risk_levels", []))
    if not risk_levels.empty:
        st.markdown("#### Risk Levels & AI Playbook")
        display_cols = [column for column in ["category", "level", "score", "trigger", "owner", "solution"] if column in risk_levels.columns]
        st.dataframe(risk_levels[display_cols], use_container_width=True, hide_index=True)

    route_intelligence = result.get("route_intelligence") or {}
    if route_intelligence:
        recommended = route_intelligence.get("recommended") or {}
        st.markdown("#### API Route Intelligence")
        st.success(
            f"{route_intelligence.get('origin')} to {route_intelligence.get('destination')}: "
            f"{recommended.get('route')} | Risk {recommended.get('risk_score')}/10 "
            f"({recommended.get('risk_band')}) | {recommended.get('distance_nm')} nm"
        )
        st.caption(route_intelligence.get("model_note", "Route intelligence combines platform API data and route risk controls."))
        alternatives = pd.DataFrame(route_intelligence.get("alternatives", []))
        if not alternatives.empty:
            visible = [
                column for column in [
                    "recommended", "route", "risk_score", "risk_band", "distance_nm",
                    "detour_ratio", "objective_score", "captain_rule", "why"
                ]
                if column in alternatives.columns
            ]
            st.dataframe(alternatives[visible], use_container_width=True, hide_index=True)
        zone_df = pd.DataFrame(route_intelligence.get("watch_zones", []))
        if not zone_df.empty:
            zone_cols = [column for column in ["zone", "type", "impact", "note"] if column in zone_df.columns]
            st.markdown("#### Watch Zones")
            st.dataframe(zone_df[zone_cols], use_container_width=True, hide_index=True)
        controls = route_intelligence.get("controls", [])
        if controls:
            st.markdown("#### Route Controls")
            st.dataframe(pd.DataFrame({"Control": list(dict.fromkeys(controls))[:8]}), use_container_width=True, hide_index=True)

    diag_col, action_col = st.columns([1, 1])
    with diag_col:
        st.markdown("#### Diagnosis & Live Evidence")
        diagnosis = result.get("diagnosis", [])
        evidence = result.get("evidence", [])
        if diagnosis:
            st.dataframe(pd.DataFrame({"Diagnostic Markers": diagnosis}), use_container_width=True, hide_index=True)
        if evidence:
            st.dataframe(pd.DataFrame({"Corroborating Evidence": evidence}), use_container_width=True, hide_index=True)
    with action_col:
        st.markdown("#### Suggested Execution Plan")
        for index, action in enumerate(result.get("action_plan", []), start=1):
            st.markdown(
                f"""
<div class="action-step">
<b>STEP {index}</b> {safe_html(action)}
</div>
                """,
                unsafe_allow_html=True,
            )
        if result.get("status") == "off_topic":
            st.caption("Allowed topics: " + ", ".join(result.get("allowed_topics", [])))

    with st.expander("📋 Export Copy-Ready Response"):
        st.code(
            "\n".join(
                [
                    f"Topic: {result.get('topic')}",
                    f"Severity: {severity}",
                    f"Confidence: {result.get('confidence')}%",
                    f"Decision: {result.get('answer')}",
                    "Actions:",
                    *[f"- {item}" for item in result.get("action_plan", [])],
                ]
            ),
            language="text",
        )
    with st.expander("🔍 AI Explainability & Audit Constraints"):
        explain = result.get("explainability", {})
        st.caption(f"**Analysis Engine:** {explain.get('method', 'No explainability returned.')}")
        inputs = pd.DataFrame({"Data Inputs Considered": explain.get("inputs", [])})
        limits = pd.DataFrame({"Known Blindspots/Limits": explain.get("limits", [])})
        ex_col1, ex_col2 = st.columns(2)
        with ex_col1:
            if not inputs.empty:
                st.dataframe(inputs, use_container_width=True, hide_index=True)
        with ex_col2:
            if not limits.empty:
                st.dataframe(limits, use_container_width=True, hide_index=True)


def show_vessel_predictions():
    st.title("Predictive ETA & Delay Engine")
    try:
        packet = api_get("/vessels/predictions?limit=100")
    except Exception as e:
        show_api_error("Vessel predictions", e)
        return

    df = pd.DataFrame(packet.get("predictions", []))
    if df.empty:
        st.info("No vessel predictions available.")
        return
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Prediction Source", packet.get("source", "Unknown"))
    with c2:
        st.metric("Tracked Vessels", len(df))
    with c3:
        st.metric("Peak Delay Risk", f"{df['delay_risk'].max():.1f}/10")
    with c4:
        st.metric("Avg ETA", f"{df['eta_hours'].mean():.1f}h")
    fig = px.scatter(df, x="eta_hours", y="delay_risk", color="delay_band", hover_name="vessel", size="speed_knots", title="ETA vs Delay Risk")
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Prediction Timeline")
    selected_vessel = st.selectbox("Timeline vessel", df["vessel"].tolist(), key="eta_timeline_vessel")
    try:
        history_packet = api_get(f"/vessels/history?vessel_identifier={quote(selected_vessel)}&limit=220")
        history_df = pd.DataFrame(history_packet.get("rows", []))
        if history_df.empty:
            history_packet = api_get("/vessels/history?limit=220")
            history_df = pd.DataFrame(history_packet.get("rows", []))
            if not history_df.empty:
                history_df = history_df[history_df["vessel_name"].astype(str) == str(selected_vessel)]
        if history_df.empty:
            st.caption("No persisted AIS timeline yet for this vessel. Keep the backend running while AIS messages arrive.")
        else:
            history_df["timestamp"] = pd.to_datetime(history_df["timestamp"], errors="coerce")
            timeline_col1, timeline_col2 = st.columns(2)
            with timeline_col1:
                fig = px.line(history_df, x="timestamp", y="speed_knots", title=f"Speed History: {selected_vessel}")
                st.plotly_chart(fig, use_container_width=True)
            with timeline_col2:
                if "nearest_port" in history_df.columns:
                    port_counts = history_df["nearest_port"].value_counts().reset_index()
                    port_counts.columns = ["Nearest Port", "Signals"]
                    st.dataframe(port_counts, use_container_width=True, hide_index=True)
    except Exception as e:
        st.caption(f"Prediction timeline unavailable: {e}")

    st.dataframe(df, use_container_width=True, hide_index=True)


def show_notifications():
    st.title("Notifications")
    try:
        refresh_col, status_col = st.columns([0.22, 0.78])
        with refresh_col:
            refresh_now = st.button("Refresh", icon=":material/refresh:", use_container_width=True)
        if refresh_now:
            cached_api_get.clear()
        notifications = api_get("/notifications?limit=150", fresh=refresh_now)
        intelligence = api_get("/notifications/intelligence?limit=150", fresh=refresh_now)
        digest = api_get("/notifications/digest?limit=150", fresh=refresh_now)
        with status_col:
            st.caption(f"Last checked {datetime.datetime.now().strftime('%H:%M:%S')} | Role {current_role()} | {auth_status_label()}")
    except Exception as e:
        show_api_error("Notifications", e)
        return

    df = pd.DataFrame(notifications or [])
    if df.empty:
        st.success("No active notifications. The operating picture is quiet.")
        return
    for col in ["severity", "title", "message", "source", "timestamp", "target"]:
        if col not in df.columns:
            df[col] = ""
    df["severity"] = df["severity"].fillna("info").astype(str).str.lower()
    df["rank"] = df["severity"].apply(notification_rank)
    df["age"] = df["timestamp"].apply(notification_age)
    df["timestamp_sort"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df = df.sort_values(["rank", "timestamp_sort"], ascending=[True, False])

    critical = len(df[df["severity"] == "critical"])
    warning = len(df[df["severity"] == "warning"])
    info = len(df[df["severity"] == "info"])
    ais_rows = len(df[df["source"].astype(str).str.contains("AISStream", case=False, na=False)])
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("Critical", critical)
    with c2:
        st.metric("Warning", warning)
    with c3:
        st.metric("Info", info)
    with c4:
        st.metric("Total", len(df))
    with c5:
        st.metric("AIS API", ais_rows, "live-key signals")

    st.markdown("### AI Noise-Reduced Digest")
    d1, d2, d3 = st.columns(3)
    with d1:
        st.metric("Raw Signals", digest.get("raw_total", len(df)))
    with d2:
        st.metric("Compressed Targets", digest.get("compressed_total", 0))
    with d3:
        st.metric("Noise Reduced", digest.get("noise_reduction", 0), digest.get("pressure_band", "Normal"))
    digest_df = pd.DataFrame(digest.get("cards", []))
    if not digest_df.empty:
        st.dataframe(
            digest_df[["priority", "target", "signals", "pressure", "band", "recommended_action", "latest"]],
            use_container_width=True,
            hide_index=True,
        )
        triage_allowed = can("approve_actions") or can("manage_alert_workflows")
        st.markdown("#### One-Click Notification Triage")
        triage_col1, triage_col2, triage_col3, triage_col4 = st.columns([1.1, 0.8, 0.8, 1.1])
        with triage_col1:
            triage_target = st.selectbox("Digest target", digest_df["target"].astype(str).tolist(), key="notification_triage_target")
        with triage_col2:
            triage_action_label = st.selectbox("Action", ["Investigate", "Escalate", "Resolve", "Watch"], key="notification_triage_action")
        with triage_col3:
            triage_priority = st.selectbox("Priority", ["P1", "P2", "P3"], index=1, key="notification_triage_priority")
        with triage_col4:
            triage_owner = st.text_input("Owner", value=current_role(), key="notification_triage_owner")
        triage_note = st.text_input("Triage note", value="Actioned from notification digest.", key="notification_triage_note")
        if st.button(
            "Apply Notification Action",
            use_container_width=True,
            disabled=not triage_allowed,
            icon=":material/rule:",
        ):
            try:
                result = api_post("/notifications/action", {
                    "target": triage_target,
                    "action": triage_action_label.lower(),
                    "owner": triage_owner,
                    "note": triage_note,
                    "priority": triage_priority,
                }).json()
                st.success(f"{result.get('status', 'updated').title()}: {result.get('target')}")
            except Exception as e:
                st.error(f"Could not apply notification action: {e}")
        if not triage_allowed:
            st.caption(f"Notification triage is read-only for role: {current_role()}.")

    control_col1, control_col2, control_col3 = st.columns([0.9, 1.1, 1.3])
    with control_col1:
        priority_view = render_workspace_switch("Priority", ["All", "Critical", "Warning", "Info"], "notification_priority_filter")
    with control_col2:
        sources = ["All sources"] + sorted(source for source in df["source"].dropna().astype(str).unique() if source)
        source_filter = st.selectbox("Source", sources)
    with control_col3:
        query = st.text_input("Search", placeholder="Route, vessel, target, action...")

    filtered = df.copy()
    if priority_view != "All":
        filtered = filtered[filtered["severity"] == priority_view.lower()]
    if source_filter != "All sources":
        filtered = filtered[filtered["source"] == source_filter]
    if query.strip():
        text = query.strip().lower()
        haystack = (
            filtered["title"].astype(str) + " "
            + filtered["message"].astype(str) + " "
            + filtered["target"].astype(str) + " "
            + filtered["source"].astype(str)
        ).str.lower()
        filtered = filtered[haystack.str.contains(text, na=False)]

    queue_col, insight_col = st.columns([1.35, 0.8])
    with queue_col:
        st.markdown("### Priority Queue")
        if filtered.empty:
            st.info("No notifications match the current filters.")
        for _, row in filtered.head(8).iterrows():
            color, label = severity_tone(row["severity"])
            st.markdown(
                f"""
                <div class="notification-card" style="--note-color:{color}; --chip-color:{color};">
                    <span class="severity-chip">{label}</span>
                    <b>{safe_html(row['title'])}</b>
                    <div>{safe_html(row['message'])}</div>
                    <div class="notification-meta">
                        {safe_html(row['source'])} | Target: {safe_html(row['target'] or 'Network')} | {safe_html(row['age'])}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with insight_col:
        st.markdown("### Triage Lens")
        pressure = intelligence.get("pressure_score", 0)
        st.metric("Alert Pressure", f"{pressure}/100", intelligence.get("pressure_band", "Normal"))
        hottest_targets = (
            df[df["severity"].isin(["critical", "warning"])]["target"]
            .replace("", pd.NA)
            .dropna()
            .astype(str)
            .value_counts()
            .head(5)
        )
        if critical:
            st.error(f"{critical} critical item(s) need command review.")
        elif warning:
            st.warning(f"{warning} warning item(s) should stay on watch.")
        else:
            st.success("No priority pressure in the notification queue.")
        if not hottest_targets.empty:
            st.markdown("#### Most Mentioned Targets")
            st.dataframe(
                pd.DataFrame({"Target": hottest_targets.index, "Signals": hottest_targets.values}),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("No target concentration detected.")
        grouped_actions = pd.DataFrame(intelligence.get("top_actions", []))
        if not grouped_actions.empty:
            st.markdown("#### Grouped Next Actions")
            st.dataframe(grouped_actions, use_container_width=True, hide_index=True)

    with st.expander("Notification Log"):
        visible_cols = ["severity", "title", "message", "source", "target", "age", "timestamp"]
        st.dataframe(filtered[visible_cols], use_container_width=True, hide_index=True)


def get_auth_metadata():
    try:
        return api_get("/auth/roles")
    except Exception:
        return DEFAULT_AUTH_META


def security_policy_for(auth_meta, role):
    roles = auth_meta.get("roles", {}) if isinstance(auth_meta, dict) else {}
    role = normalize_role_name(role)
    return roles.get(role, DEFAULT_AUTH_META["roles"].get(role, {}))


def render_security_pills(items):
    safe_items = [str(item) for item in items or []]
    if not safe_items:
        st.caption("None")
        return
    st.markdown(
        " ".join(f'<span class="security-pill">{safe_html(item)}</span>' for item in safe_items),
        unsafe_allow_html=True,
    )


def provider_options_for(auth_meta, role):
    providers = auth_meta.get("providers", DEFAULT_AUTH_META["providers"])
    role = normalize_role_name(role)
    policy = security_policy_for(auth_meta, role)
    auth_policy = policy.get("auth", {})
    return auth_policy.get("allowed_providers", []) or list(providers.keys())


def provider_label(auth_meta, provider):
    providers = auth_meta.get("providers", DEFAULT_AUTH_META["providers"])
    meta = providers.get(provider, {})
    return meta.get("label", provider)


def public_provider_options(auth_meta):
    return provider_options_for(auth_meta, "Public")


def demo_account_for(email):
    ensure_user_context()
    return st.session_state.demo_accounts.get(str(email or "").strip().lower())


def apply_auth_result(result):
    account = result.get("account", {})
    role = normalize_role_name(account.get("role", "Public"))
    provider = account.get("provider", "Guest preview")
    method = result.get("method", provider)
    identity = account.get("display_name") or account.get("email") or role
    sign_in_role(role, provider, method, identity, result.get("session_expires_at"))
    if result.get("session_token"):
        set_session_token(result.get("session_token"))
    landing = account.get("landing_page")
    if landing and landing in pages:
        st.session_state.selected_page = landing


def login_account_lookup():
    try:
        packet = api_get("/auth/accounts")
        return {
            str(account.get("email", "")).strip().lower(): account
            for account in packet.get("accounts", [])
            if account.get("email")
        }
    except Exception:
        return {}


def detected_login_role(email):
    normalized = str(email or "").strip().lower()
    account = login_account_lookup().get(normalized)
    if account:
        return normalize_role_name(account.get("role", "Public")), account
    demo = demo_account_for(normalized)
    if demo:
        return normalize_role_name(demo.get("role", "Public")), demo
    if normalized.startswith("admin"):
        return "Admin", {}
    if normalized.startswith(("fleet", "operator", "ops", "risk")):
        return "Operator", {}
    return "Public", {}


def quick_role_login(role):
    role = normalize_role_name(role)
    if role == "Public":
        sign_in_role("Public", "Guest preview", "read-only guest", "Public Guest")
        return {"account": {"role": "Public", "display_name": "Public Guest"}}

    profile = ROLE_DEMO_LOGINS.get(role)
    if not profile:
        raise ValueError(f"Unsupported role: {role}")
    payload = {
        "email": profile["email"],
        "password": profile["password"],
        "role": role,
        "provider": profile["provider"],
        **profile.get("payload", {}),
    }
    result = api_post("/auth/login", payload).json()
    apply_auth_result(result)
    return result


def access_label_for_role(role):
    return normalize_role_name(role)


def login_status_snapshot():
    status = {
        "backend_online": False,
        "backend_label": "Backend offline",
        "backend_detail": f"API: {API_BASE}",
        "production_enabled": False,
        "demo_accounts_allowed": True,
        "app_mode": "demo",
    }
    try:
        response = HTTP.get(f"{API_BASE}/health", timeout=STATUS_TIMEOUT)
        response.raise_for_status()
        health = response.json()
        status["backend_online"] = True
        status["backend_label"] = str(health.get("status", "online")).title()
        status["backend_detail"] = f"API: {API_BASE}"
    except Exception as exc:
        status["backend_detail"] = f"API unreachable at {API_BASE}: {exc}"

    if status["backend_online"]:
        try:
            response = HTTP.get(f"{API_BASE}/settings/production-mode", timeout=STATUS_TIMEOUT)
            response.raise_for_status()
            production = response.json()
            status["production_enabled"] = bool(production.get("enabled", False))
            status["demo_accounts_allowed"] = bool(production.get("demo_accounts_allowed", True))
            status["app_mode"] = production.get("app_mode", "demo")
        except Exception:
            pass
    return status


def render_login_gate(auth_meta):
    status = login_status_snapshot()
    backend_tone = "ok" if status["backend_online"] else "bad"
    mode_tone = "warn" if status["production_enabled"] else "ok"
    demo_blocked = status["production_enabled"] and not status["demo_accounts_allowed"]
    demo_tone = "bad" if demo_blocked else "ok"
    demo_label = "Demo logins blocked" if demo_blocked else "Demo logins allowed"

    st.markdown(
        """
        <style>
        .login-wrapper { max-width: 1050px; margin: 0 auto; padding: 1.4rem 0.5rem 0.6rem; }
        .login-header { text-align: center; margin-bottom: 1.15rem; }
        .login-badge-new { display: inline-block; background: rgba(20, 184, 166, 0.14); color: #99f6e4; padding: 0.34rem 0.78rem; border-radius: 999px; font-size: 0.78rem; font-weight: 800; letter-spacing: 0; border: 1px solid rgba(45, 212, 191, 0.28); margin-bottom: 0.75rem; text-transform: uppercase; }
        .login-title-new { color: #f8fafc; font-size: clamp(1.85rem, 4vw, 2.45rem); font-weight: 850; max-width: 860px; margin: 0 auto 0.45rem; line-height: 1.15; }
        .login-subtitle-new { color: #cbd5e1; font-size: 1rem; max-width: 690px; margin: 0 auto; line-height: 1.5; }
        .login-status-row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.6rem; max-width: 900px; margin: 1rem auto 0; }
        .login-status-pill { border-radius: 8px; border: 1px solid rgba(148, 163, 184, 0.2); background: rgba(15, 23, 42, 0.56); padding: 0.62rem 0.72rem; color: #e2e8f0; text-align: left; }
        .login-status-pill b { display: block; color: #f8fafc; font-size: 0.9rem; }
        .login-status-pill span { color: #94a3b8; font-size: 0.78rem; }
        .login-status-pill.ok { border-color: rgba(45, 212, 191, 0.34); }
        .login-status-pill.warn { border-color: rgba(250, 204, 21, 0.42); }
        .login-status-pill.bad { border-color: rgba(248, 113, 113, 0.46); }
        .role-entry-card { min-height: 214px; background: rgba(15, 23, 42, 0.68); border: 1px solid rgba(148, 163, 184, 0.2); border-radius: 8px; padding: 1rem; box-shadow: none; }
        .role-kicker { color: #99f6e4; font-size: 0.75rem; font-weight: 850; letter-spacing: 0; text-transform: uppercase; }
        .role-entry-card h3 { color: #f8fafc; margin: 0.42rem 0; font-size: 1.22rem; }
        .role-entry-card p { color: #cbd5e1; margin: 0.2rem 0 0.8rem; line-height: 1.45; min-height: 66px; }
        .role-access-list { color: #94a3b8; font-size: 0.84rem; line-height: 1.55; }
        .login-note { background: rgba(34, 197, 94, 0.1); border: 1px solid rgba(34, 197, 94, 0.25); color: #bbf7d0; border-radius: 8px; padding: 0.78rem 0.88rem; margin: 0.95rem 0; }
        .settings-band-new { background: rgba(34, 211, 238, 0.05); border-left: 4px solid #22d3ee; padding: 1rem 1.25rem; border-radius: 0 8px 8px 0; margin: 1.5rem 0; color: #e2e8f0; }
        .settings-band-new b { color: #22d3ee; }
        .form-container { background: rgba(15, 23, 42, 0.4); border: 1px solid rgba(148, 163, 184, 0.15); border-radius: 8px; padding: 1.25rem; box-shadow: none; }
        @media (max-width: 760px) {
            .login-title-new { font-size: 1.9rem; }
            .login-status-row { grid-template-columns: 1fr; }
            .role-entry-card { min-height: auto; }
            .role-entry-card p { min-height: auto; }
        }
        </style>
        <div class="login-wrapper"><div class="login-header"><div class="login-badge-new">Secure Command Access</div><div class="login-title-new">Global AI Trade Intelligence Platform</div><div class="login-subtitle-new">AI maritime command system for routes, vessels, cargo, risks, reports, and role-based operations.</div></div></div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
<div class="login-status-row">
    <div class="login-status-pill {backend_tone}">
        <b>Backend {safe_html(status["backend_label"])}</b>
        <span>{safe_html(status["backend_detail"])}</span>
    </div>
    <div class="login-status-pill {mode_tone}">
        <b>{safe_html(str(status["app_mode"]).title())} Mode</b>
        <span>{'Production controls active' if status["production_enabled"] else 'Local academic demo mode'}</span>
    </div>
    <div class="login-status-pill {demo_tone}">
        <b>{safe_html(demo_label)}</b>
        <span>Admin and Operator shortcuts use local demo accounts.</span>
    </div>
</div>
        """,
        unsafe_allow_html=True,
    )
    if not status["backend_online"]:
        st.error("Backend is offline. Start the demo with `.\run_demo.ps1 -Restart` before using Admin or Operator login.")
    elif demo_blocked:
        st.warning("Production mode is active, so demo Admin and Operator shortcuts are disabled. Use a real configured provider or switch back to demo mode from Settings.")

    role_cards = [
        {
            "role": "Admin",
            "title": "Admin Command",
            "copy": "Full platform control for settings, users, deployment, AIS tuning, reports, and approvals.",
            "access": ["Fingerprint confirmation", "ADMIN ACCESS phrase", "All sections unlocked"],
            "button": "Enter Admin Demo",
        },
        {
            "role": "Operator",
            "title": "Operator Desk",
            "copy": "Daily control room access for fleet maps, cargo exposure, risk alerts, scenarios, and reports.",
            "access": ["Company SSO", "6-digit MFA", "Operational sections unlocked"],
            "button": "Enter Operator Demo",
        },
        {
            "role": "Public",
            "title": "Public Viewer",
            "copy": "Read-only presentation mode for sanitized dashboards without command actions or private cargo controls.",
            "access": ["Google-style login", "No write access", "Dashboard only"],
            "button": "Continue Public",
        },
    ]

    st.markdown('<div class="login-note">Simple demo path: click a role card. Manual sign-in and account creation are still available below.</div>', unsafe_allow_html=True)
    columns = st.columns(3)
    for index, card in enumerate(role_cards):
        role = card["role"]
        is_public = role == "Public"
        role_disabled = (not status["backend_online"] and not is_public) or (demo_blocked and not is_public)
        icon = {
            "Admin": ":material/admin_panel_settings:",
            "Operator": ":material/radar:",
            "Public": ":material/visibility:",
        }.get(role)
        with columns[index]:
            st.markdown(
                f"""
<div class="role-entry-card">
    <div class="role-kicker">{safe_html(role)} role</div>
    <h3>{safe_html(card["title"])}</h3>
    <p>{safe_html(card["copy"])}</p>
    <div class="role-access-list">
        {'<br>'.join(f'- {safe_html(item)}' for item in card["access"])}
    </div>
</div>
                """,
                unsafe_allow_html=True,
            )
            if st.button(
                card["button"],
                key=f"quick_login_{role}",
                use_container_width=True,
                type="primary" if role == "Admin" else "secondary",
                icon=icon,
                disabled=role_disabled,
            ):
                try:
                    with st.spinner(f"Opening {role} session..."):
                        quick_role_login(role)
                    st.rerun()
                except Exception as e:
                    st.error(f"{role} login failed: {e}")

    entry_options = ["Manual Sign In", "Create Account", "Public Provider"]
    if st.session_state.get("auth_flow_mode") not in entry_options:
        st.session_state.auth_flow_mode = "Manual Sign In"

    with st.expander("Advanced access tools", expanded=False):
        flow = render_workspace_switch("Access tool", entry_options, "auth_flow_mode")

        if flow == "Manual Sign In":
            if "login_email" not in st.session_state:
                st.session_state.login_email = ""
            if "login_password" not in st.session_state:
                st.session_state.login_password = ""

            fill_admin, fill_operator, fill_public = st.columns(3)
            with fill_admin:
                if st.button("Fill Admin Demo", use_container_width=True, icon=":material/admin_panel_settings:"):
                    st.session_state.login_email = "admin@demo.app"
                    st.session_state.login_password = "admin-demo"
                    st.rerun()
            with fill_operator:
                if st.button("Fill Operator Demo", use_container_width=True, icon=":material/radar:"):
                    st.session_state.login_email = "operator@demo.app"
                    st.session_state.login_password = "operator-demo"
                    st.rerun()
            with fill_public:
                if st.button("Guest Viewer", use_container_width=True, icon=":material/visibility:"):
                    quick_role_login("Public")
                    st.rerun()

            email = st.text_input("Email address", key="login_email", placeholder="admin@demo.app or operator@demo.app")
            detected_role, _account = detected_login_role(email)
            policy = security_policy_for(auth_meta, detected_role)
            st.markdown(
                f"""
<div class="settings-band-new">
    <b>Detected clearance:</b> {safe_html(access_label_for_role(detected_role))}<br>
    <span style="font-size: 0.9em; opacity: 0.8;">{safe_html(policy.get('risk', 'Enter an email to evaluate access policy.'))}</span>
</div>
                """,
                unsafe_allow_html=True,
            )

            with st.form("manual_account_login", clear_on_submit=False):
                password = st.text_input("Password", key="login_password", type="password")
                biometric_ok = False
                phrase = ""
                mfa_code = ""
                responsibility = True

                if detected_role == "Admin":
                    biometric_ok = st.checkbox("Fingerprint/passkey confirmed on this trusted device")
                    phrase = st.text_input("Admin phrase", type="password", placeholder="ADMIN ACCESS")
                    responsibility = st.checkbox("I accept responsibility for Admin command actions.", value=False)
                elif detected_role == "Operator":
                    mfa_code = st.text_input("Operator MFA code", type="password", max_chars=6, placeholder="123456")

                remember_device = st.checkbox("Keep session active on this terminal", value=True)
                submitted = st.form_submit_button("Sign In", use_container_width=True, type="primary")

            if submitted:
                if not email.strip() or not password:
                    st.error("Email and password are required.")
                elif detected_role == "Admin" and (not biometric_ok or phrase.strip().upper() != "ADMIN ACCESS" or not responsibility):
                    st.error("Admin requires fingerprint confirmation, the exact phrase ADMIN ACCESS, and responsibility acknowledgement.")
                elif detected_role == "Operator" and not (mfa_code.isdigit() and len(mfa_code) == 6):
                    st.error("Operator requires a 6-digit MFA/passkey code.")
                else:
                    try:
                        result = api_post("/auth/login", {
                            "email": email,
                            "password": password,
                            "biometric_ok": biometric_ok,
                            "phrase": phrase,
                            "mfa_code": mfa_code,
                        }).json()
                        apply_auth_result(result)
                        if not remember_device:
                            clear_session_token()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Sign in failed: {e}")

        elif flow == "Create Account":
            st.info("Admin accounts are invite-only. New self-service accounts can be Operator or Public only.")
            account_type = st.selectbox("Requested role", ["Operator", "Public"], key="signup_account_type")
            new_role = "Operator" if account_type == "Operator" else "Public"
            provider = st.selectbox("Provider", provider_options_for(auth_meta, new_role), key="signup_provider")
            render_security_pills(sorted(ROLE_PERMISSIONS.get(new_role, set())) or ["read only"])

            with st.form("create_access_account", clear_on_submit=False):
                name = st.text_input("Display name / callsign")
                email = st.text_input("Email", placeholder="user@domain.com")
                password = st.text_input("Password", type="password")
                confirm_password = st.text_input("Confirm password", type="password")
                mfa_code = ""
                if new_role == "Operator":
                    mfa_code = st.text_input("Register 6-digit MFA code", type="password", max_chars=6)
                accept_policy = st.checkbox("I accept the assigned role limits.", value=False)
                submitted = st.form_submit_button("Create Account", use_container_width=True, type="primary")

            if submitted:
                normalized = email.strip().lower()
                if "@" not in normalized or "." not in normalized.split("@")[-1]:
                    st.error("Enter a valid email.")
                elif len(password) < 6 or password != confirm_password:
                    st.error("Passwords must match and contain at least 6 characters.")
                elif new_role == "Operator" and not (mfa_code.isdigit() and len(mfa_code) == 6):
                    st.error("Operator accounts require a numeric 6-digit MFA code.")
                elif not accept_policy:
                    st.error("Accept the role limits before creating the account.")
                else:
                    try:
                        result = api_post("/auth/register", {
                            "email": normalized,
                            "display_name": name,
                            "password": password,
                            "role": new_role,
                            "provider": provider,
                            "mfa_code": mfa_code,
                        }).json()
                        apply_auth_result(result)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Registration failed: {e}")

        else:
            st.info("Public provider access is always read-only. Real deployment requires OAuth secrets and HTTPS callbacks.")
            providers = public_provider_options(auth_meta)
            provider_cols = st.columns(2)
            for index, provider in enumerate(providers):
                with provider_cols[index % 2]:
                    if st.button(provider_label(auth_meta, provider), key=f"login_social_{provider}", use_container_width=True):
                        try:
                            result = api_post("/auth/social-login", {"provider": provider}).json()
                            apply_auth_result(result)
                            st.rerun()
                        except Exception as e:
                            st.error(f"{provider} login failed: {e}")
            if st.button("Continue as Anonymous Guest", use_container_width=True):
                sign_in_role("Public", "Guest preview", "guest read-only", "Anonymous User")
                st.rerun()


def show_setup_checklist_panel():
    st.markdown("### First-Time Setup Wizard")
    try:
        setup = api_get("/setup/checklist", fresh=True)
    except Exception as e:
        st.caption(f"Setup checklist unavailable: {e}")
        return
    s1, s2, s3 = st.columns(3)
    with s1:
        st.metric("Setup Score", f"{setup.get('score', 0)}%", setup.get("band", "unknown"))
    with s2:
        checks = setup.get("checks", [])
        st.metric("Pass", sum(1 for row in checks if row.get("status") == "pass"))
    with s3:
        st.metric("Needs Work", sum(1 for row in checks if row.get("status") != "pass"))
    st.dataframe(pd.DataFrame(setup.get("checks", [])), use_container_width=True, hide_index=True)
    st.markdown("#### Quick Start")
    st.dataframe(pd.DataFrame({"Step": setup.get("quick_start", [])}), use_container_width=True, hide_index=True)


def show_user_management_panel():
    st.markdown("### Admin User Management")
    if current_role() != "Admin":
        st.info("Only Admin can manage users. Operators can use the rest of Settings, but user promotion/disable stays locked.")
        return
    try:
        packet = api_get("/admin/users", fresh=True)
    except Exception as e:
        st.error(f"User management unavailable: {e}")
        return
    summary = packet.get("summary", {})
    u1, u2, u3 = st.columns(3)
    with u1:
        st.metric("Accounts", summary.get("total", 0))
    with u2:
        st.metric("Active", summary.get("active", 0))
    with u3:
        st.metric("Disabled", summary.get("disabled", 0))
    accounts = pd.DataFrame(packet.get("accounts", []))
    if not accounts.empty:
        st.dataframe(accounts[["email", "display_name", "role", "provider", "status", "last_login_at"]], use_container_width=True, hide_index=True)

    st.markdown("#### Create / Update User")
    with st.form("admin_user_upsert", clear_on_submit=False):
        email = st.text_input("Email", placeholder="operator@example.com")
        display_name = st.text_input("Display name", placeholder="Command Operator")
        role = st.selectbox("Role", ["Operator", "Public", "Admin"])
        provider = st.selectbox("Provider", provider_options_for(get_auth_metadata(), role))
        status = st.selectbox("Status", ["active", "disabled"])
        password = st.text_input("New password", type="password", help="Required for new accounts. Leave blank to keep existing password.")
        mfa_code = ""
        if role == "Operator":
            mfa_code = st.text_input("Operator MFA/passkey", type="password", max_chars=6, placeholder="123456")
        confirm = ""
        if role == "Admin":
            confirm = st.text_input("Type ADMIN USER", type="password")
        submitted = st.form_submit_button("Save User", use_container_width=True)
    if submitted:
        try:
            result = api_post("/admin/users", {
                "email": email,
                "display_name": display_name,
                "role": role,
                "provider": provider,
                "status": status,
                "password": password,
                "mfa_code": mfa_code,
                "confirm": confirm,
            }).json()
            st.success(f"Saved {result.get('email')} as {result.get('role')} / {result.get('status')}.")
        except Exception as e:
            st.error(f"Could not save user: {e}")
    st.dataframe(pd.DataFrame({"Rule": packet.get("rules", [])}), use_container_width=True, hide_index=True)


def show_delivery_panel():
    st.markdown("### Notification Delivery")
    try:
        status = api_get("/notifications/delivery-status")
        channels = pd.DataFrame(status.get("channels", []))
        if not channels.empty:
            st.dataframe(channels, use_container_width=True, hide_index=True)
        st.caption(status.get("production_note", ""))
    except Exception as e:
        st.caption(f"Delivery status unavailable: {e}")
    d1, d2, d3, d4 = st.columns(4)
    with d1:
        channel = st.selectbox("Channel", ["outbox", "webhook", "email", "discord", "telegram"])
    with d2:
        severity = st.selectbox("Minimum severity", ["critical", "warning", "info"])
    with d3:
        target = st.text_input("Target filter", placeholder="optional")
    with d4:
        include_digest = st.checkbox("Include digest", value=True)
    if st.button("Deliver Notification Digest", use_container_width=True, disabled=not (can("approve_actions") or can("manage_alert_workflows") or can("generate_reports"))):
        try:
            result = api_post("/notifications/deliver", {
                "channel": channel,
                "severity": severity,
                "target": target or None,
                "include_digest": include_digest,
            }).json()
            st.success(f"{result.get('count', 0)} notification(s) prepared via {result.get('channel')}.")
            st.caption(result.get("note", ""))
            st.dataframe(pd.DataFrame(result.get("preview", [])), use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Delivery failed: {e}")


def show_security_dashboard_panel():
    st.markdown("### Security Audit Dashboard")
    try:
        packet = api_get("/security/audit-summary?limit=180", fresh=True)
    except Exception as e:
        st.error(f"Security audit unavailable: {e}")
        return
    summary = packet.get("summary", {})
    a1, a2, a3, a4, a5 = st.columns(5)
    with a1:
        st.metric("Events", summary.get("events_scanned", 0))
    with a2:
        st.metric("24h", summary.get("events_24h", 0))
    with a3:
        st.metric("Critical", summary.get("critical", 0))
    with a4:
        st.metric("Warning", summary.get("warning", 0))
    with a5:
        st.metric("Actors", summary.get("unique_actors", 0))
    tab1, tab2, tab3 = st.tabs(["Risky Events", "Top Actions", "Recommendations"])
    with tab1:
        risky = pd.DataFrame(packet.get("risky_events", []))
        if risky.empty:
            st.success("No risky audit events in the scanned window.")
        else:
            st.dataframe(risky, use_container_width=True, hide_index=True)
    with tab2:
        st.dataframe(pd.DataFrame(packet.get("top_actions", [])), use_container_width=True, hide_index=True)
    with tab3:
        st.dataframe(pd.DataFrame({"Recommendation": packet.get("recommendations", [])}), use_container_width=True, hide_index=True)


def show_database_panel():
    st.markdown("### Production Database Mode")
    try:
        packet = api_get("/database/operations", fresh=True)
    except Exception as e:
        st.error(f"Database operations unavailable: {e}")
        return
    d1, d2, d3 = st.columns(3)
    with d1:
        st.metric("Database", packet.get("database_type", "unknown"))
    with d2:
        st.metric("Backup", "Supported" if packet.get("backup_supported") else "Managed/External")
    with d3:
        st.metric("Latest Backup", "Yes" if packet.get("latest_backup") else "None")
    st.caption(packet.get("runtime_path", ""))
    st.dataframe(pd.DataFrame(packet.get("checks", [])), use_container_width=True, hide_index=True)
    st.dataframe(pd.DataFrame({"Recommendation": packet.get("recommendations", [])}), use_container_width=True, hide_index=True)
    if current_role() == "Admin":
        confirm = st.text_input("Type BACKUP DATABASE", type="password", key="backup_db_confirm")
        if st.button("Create SQLite Backup", use_container_width=True):
            try:
                result = api_post("/database/backup", {"confirm": confirm}).json()
                st.success(f"Backup created: {result.get('backup_path')}")
            except Exception as e:
                st.error(f"Backup failed: {e}")


def show_external_data_panel():
    st.markdown("### External Data Integrations")
    try:
        status = api_get("/external-data/status")
        weather = api_get("/weather/maritime")
        ports = api_get("/ports/congestion")
    except Exception as e:
        st.error(f"External data center unavailable: {e}")
        return
    e1, e2, e3 = st.columns(3)
    with e1:
        st.metric("Connected Providers", f"{status.get('connected', 0)}/{status.get('total', 0)}", status.get("mode"))
    with e2:
        st.metric("Weather Source", "Live hook" if weather.get("provider_connected") else "Fallback")
    with e3:
        st.metric("Port Source", ports.get("source", "platform"))
    st.dataframe(pd.DataFrame(status.get("providers", [])), use_container_width=True, hide_index=True)
    weather_df = pd.DataFrame(weather.get("ports", []))
    if not weather_df.empty:
        st.markdown("#### Maritime Weather Risk")
        st.dataframe(weather_df, use_container_width=True, hide_index=True)
    ports_df = pd.DataFrame(ports.get("ports", []))
    if not ports_df.empty:
        st.markdown("#### Port Congestion Risk")
        st.dataframe(ports_df, use_container_width=True, hide_index=True)


def show_upgrade_hub_panel():
    st.markdown("### Production Upgrade Hub")
    try:
        hub = api_get("/production/upgrade-hub", fresh=True)
        delivery = api_get("/notifications/delivery-plan?severity=critical", fresh=True)
    except Exception as e:
        st.error(f"Upgrade hub unavailable: {e}")
        return

    u1, u2, u3, u4 = st.columns(4)
    with u1:
        st.metric("Upgrade Score", f"{hub.get('score', 0)}%", hub.get("status", "unknown"))
    with u2:
        external = hub.get("external_data", {})
        st.metric("Real APIs", f"{external.get('connected', 0)}/{external.get('total', 0)}", external.get("mode", "demo"))
    with u3:
        readiness = hub.get("readiness", {})
        st.metric("Deployment", f"{readiness.get('score', 0)}%", readiness.get("band", "unknown"))
    with u4:
        reliability = hub.get("reliability", {})
        st.metric("Reliability", f"{reliability.get('score', 0)}%", reliability.get("band", "unknown"))

    st.info(hub.get("summary", "Upgrade hub is active."))
    module_rows = pd.DataFrame(hub.get("modules", []))
    if not module_rows.empty:
        st.markdown("#### Big Upgrade Roadmap")
        st.dataframe(module_rows, use_container_width=True, hide_index=True)

    st.markdown("#### Sea-Lane Decision Engine")
    route_col1, route_col2, route_col3, route_col4 = st.columns(4)
    with route_col1:
        route_origin = st.text_input("Origin port", value="Mumbai", key="upgrade_route_origin")
    with route_col2:
        route_destination = st.text_input("Destination port", value="Rotterdam", key="upgrade_route_destination")
    with route_col3:
        objective = st.selectbox("Objective", ["safest", "balanced", "fastest", "lowest_cost"], key="upgrade_route_objective")
    with route_col4:
        cargo_priority = st.selectbox("Cargo priority", ["P1", "P2", "P3"], index=1, key="upgrade_route_priority")
    avoid = st.text_input("Avoid zones / risks", value="war,piracy,security,geopolitical", key="upgrade_route_avoid")
    try:
        engine = api_get(
            f"/routes/sea-lane-engine?origin={quote(route_origin)}&destination={quote(route_destination)}"
            f"&objective={quote(objective)}&cargo_priority={quote(cargo_priority)}&avoid={quote(avoid)}",
            fresh=True,
        )
        recommended = engine.get("recommended") or {}
        if recommended:
            st.success(
                f"Recommended: {recommended.get('name')} | risk {recommended.get('risk_score')}/10 | "
                f"{recommended.get('distance_nm')} nm | rule: {recommended.get('captain_rule')}"
            )
        option_rows = pd.DataFrame(engine.get("options", []))
        if not option_rows.empty:
            display_columns = [
                column for column in [
                    "name",
                    "risk_score",
                    "risk_band",
                    "distance_nm",
                    "detour_ratio",
                    "objective_score",
                    "avoid_penalty",
                    "captain_rule",
                    "recommended",
                ]
                if column in option_rows.columns
            ]
            st.dataframe(option_rows[display_columns], use_container_width=True, hide_index=True)
        st.caption(engine.get("decision_note", "Sea-lane engine returned no note."))
    except Exception as e:
        st.warning(f"Sea-lane engine could not calculate this route yet: {e}")

    st.markdown("#### Live Alert Delivery Plan")
    d1, d2 = st.columns([0.65, 0.35])
    with d1:
        channels = pd.DataFrame(delivery.get("channels", []))
        if not channels.empty:
            st.dataframe(channels, use_container_width=True, hide_index=True)
    with d2:
        st.metric("Critical Items", delivery.get("notification_count", 0))
        st.write(" -> ".join(delivery.get("recommended_sequence", [])))
        st.caption("Alert rule: " + " ".join(delivery.get("rules", [])[:1]))

    next_steps = pd.DataFrame({"Next best step": hub.get("next_best_steps", [])})
    if not next_steps.empty:
        st.markdown("#### Final Production Steps")
        st.dataframe(next_steps, use_container_width=True, hide_index=True)


def show_settings():
    st.title("Settings")
    try:
        settings = api_get("/settings/runtime")
        health = api_get("/health")
        auth_meta = get_auth_metadata()
    except Exception as e:
        show_api_error("Settings", e)
        return

    role = current_role()
    policy = security_policy_for(auth_meta, role)
    auth_policy = policy.get("auth", {})
    st.markdown(
        f"""
        <div class="settings-band">
            <b>{safe_html(role)}</b> | {safe_html(auth_status_label())} | {safe_html(st.session_state.auth_provider)}
            <br>Identity: {safe_html(st.session_state.auth_identity)} | Method: {safe_html(st.session_state.auth_method)}
        </div>
        """,
        unsafe_allow_html=True,
    )

    a1, a2, a3, a4 = st.columns(4)
    with a1:
        st.metric("Current Role", role)
    with a2:
        st.metric("Session", auth_status_label(), f"{auth_remaining_minutes()} min left")
    with a3:
        st.metric("Backend", health.get("status", "unknown").title())
    with a4:
        st.metric("Auth Level", auth_policy.get("required_level", "public"))

    if not is_role_authenticated():
        st.markdown('<div class="security-warning">This role is locked until its required sign-in flow is completed. Write actions stay disabled.</div>', unsafe_allow_html=True)

    setting_options = (
        ["Account", "Interface"]
        if is_read_only_access()
        else ["Setup", "Upgrade Hub", "Account", "Users", "Delivery", "Security", "Database", "External Data", "Runtime", "Interface", "AIS", "Providers", "Data", "Deployment"]
    )
    section = render_workspace_switch("Settings panel", setting_options, "settings_panel")

    if section == "Setup":
        show_setup_checklist_panel()

    elif section == "Upgrade Hub":
        show_upgrade_hub_panel()

    elif section == "Account":
        st.markdown("### Account Control")
        render_security_pills(sorted(ROLE_PERMISSIONS.get(role, set())) or ["read only"])
        account_col1, account_col2 = st.columns(2)
        with account_col1:
            if st.button("Switch Account", use_container_width=True, icon=":material/login:"):
                return_to_login_gate()
                st.rerun()
        with account_col2:
            if st.button("Continue as Guest", use_container_width=True, icon=":material/person:"):
                sign_out_to_public()
                st.rerun()
        if st.session_state.security_audit:
            st.markdown("### Recent Access")
            st.dataframe(pd.DataFrame(st.session_state.security_audit), use_container_width=True, hide_index=True)
        try:
            audit_packet = api_get("/audit-log?limit=40")
            audit_events = pd.DataFrame(audit_packet.get("events", []))
            if not audit_events.empty:
                st.markdown("### Backend Audit Trail")
                st.dataframe(
                    audit_events[["timestamp", "actor_role", "actor_identity", "action", "resource", "severity", "detail"]],
                    use_container_width=True,
                    hide_index=True,
                )
        except Exception as e:
            st.caption(f"Audit trail unavailable: {e}")
        st.caption(policy.get("risk", "No role risk note available."))

    elif section == "Users":
        show_user_management_panel()

    elif section == "Delivery":
        show_delivery_panel()

    elif section == "Security":
        show_security_dashboard_panel()

    elif section == "Database":
        show_database_panel()

    elif section == "External Data":
        show_external_data_panel()

    elif section == "Runtime":
        st.markdown("### Runtime Control")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("AIS Provider", settings.get("ais_provider", "demo"))
        with c2:
            st.metric("Max Vessels", settings.get("max_vessels"))
        with c3:
            st.metric("Stale Seconds", settings.get("stale_seconds"))
        with c4:
            st.metric("API Version", settings.get("api_version", "n/a"))

        st.caption("Admin-only runtime tuning. Other roles can view this panel but cannot apply changes.")
        control_col1, control_col2, control_col3 = st.columns(3)
        with control_col1:
            ais_max_vessels = st.number_input("AIS max vessels", min_value=1, max_value=100, value=int(settings.get("max_vessels", 12)))
        with control_col2:
            ais_stale_seconds = st.number_input("Stale signal seconds", min_value=60, max_value=86400, value=int(settings.get("stale_seconds", 900)))
        with control_col3:
            region_options = list(settings.get("available_regions", {}).keys()) or ["Global default lanes"]
            ais_region = st.selectbox("AIS region preset", region_options, key="ais_runtime_region")
        runtime_step_up = admin_step_up_ready("runtime_ais_settings", "AIS runtime tuning") if can("tune_ais") else False
        if st.button("Apply Runtime AIS Settings", use_container_width=True, disabled=not can("tune_ais") or not runtime_step_up, icon=":material/tune:"):
            result = api_post("/settings/runtime", {
                "max_vessels": int(ais_max_vessels),
                "stale_seconds": int(ais_stale_seconds),
                "region": ais_region,
            }).json()
            st.success(f"Applied: {result.get('applied', {})}")
            if result.get("restart_recommended"):
                st.warning("Region updated. Restart backend if the live websocket is already connected.")
        if not can("tune_ais"):
            st.caption(f"AIS runtime tuning is disabled for role: {current_role()}.")

    elif section == "Interface":
        st.markdown("### Interface")
        try:
            refresh_default = int(st.session_state.ui_refresh_seconds)
        except (TypeError, ValueError):
            refresh_default = 10
        refresh_default = max(5, min(24, refresh_default))
        st.session_state.ui_refresh_seconds = st.slider("Live panel refresh seconds", 5, 24, refresh_default)
        st.session_state.mobile_performance_mode = st.toggle(
            "Mobile Performance Mode",
            value=bool(st.session_state.get("mobile_performance_mode", False)),
            help="Reduces live refresh pressure and lowers map rendering density for phones.",
        )
        if st.session_state.mobile_performance_mode and st.session_state.ui_refresh_seconds < 12:
            st.session_state.ui_refresh_seconds = 12
            st.info("Mobile mode raised live refresh to 12 seconds to keep phones smoother.")
        regions = list(settings.get("available_regions", {}).keys()) or ["Global default lanes"]
        selected_region = st.selectbox("Preferred AIS region preset", regions, index=regions.index(st.session_state.map_region) if st.session_state.map_region in regions else 0)
        st.session_state.map_region = selected_region
        if st.button("Clear Local API Cache", use_container_width=True, icon=":material/cached:"):
            cached_api_get.clear()
            st.success("Local API cache cleared.")
        st.info(settings.get("runtime_note", "Update environment variables and restart backend to change server settings."))

    elif section == "AIS":
        st.markdown("### AIS Reliability Center")
        ais = settings.get("aisstream_status", {})
        try:
            reliability = api_get("/ais/reliability")
        except Exception:
            reliability = {}
        summary = reliability.get("summary", {})
        s1, s2, s3, s4, s5 = st.columns(5)
        with s1:
            st.metric("Reliability", f"{reliability.get('score', 0)}/100", reliability.get("status", "unknown"))
        with s2:
            st.metric("Connected", display_setting_value(ais.get("connected")))
        with s3:
            st.metric("Tracked", ais.get("vessel_count", 0), f"{summary.get('live_vessels', 0)} live")
        with s4:
            st.metric("Newest Signal", display_setting_value(summary.get("newest_signal_age_seconds")), "seconds")
        with s5:
            st.metric("SSL", ais.get("ssl_verification", "enabled"))
        if ais.get("ssl_verification") == "disabled-local-demo":
            st.warning("Local demo SSL bypass is enabled for AISStream. This fixes the current certificate issue locally, but must be disabled before production.")

        check_rows = pd.DataFrame(reliability.get("checks", []))
        if not check_rows.empty:
            st.dataframe(check_rows, use_container_width=True, hide_index=True)
        status_rows = [{"Signal": key, "Value": display_setting_value(value)} for key, value in ais.items()]
        st.dataframe(pd.DataFrame(status_rows), use_container_width=True, hide_index=True)
        rv = pd.DataFrame(reliability.get("recent_vessels", []))
        if not rv.empty:
            st.markdown("### Recent Live AIS Vessels")
            columns = [column for column in ["name", "mmsi", "origin_port", "speed_knots", "heading", "cargo", "cargo_source", "cargo_verified", "last_signal_at"] if column in rv.columns]
            st.dataframe(rv[columns], use_container_width=True, hide_index=True)
        st.markdown("### Region Presets")
        region_rows = [{"Region": key, "Bounding Boxes / Note": value} for key, value in settings.get("available_regions", {}).items()]
        st.dataframe(pd.DataFrame(region_rows), use_container_width=True, hide_index=True)
    elif section == "Providers":
        st.markdown("### Auth Provider Setup")
        try:
            provider_status = api_get("/auth/provider-status")
            provider_rows = pd.DataFrame(provider_status.get("providers", []))
            if not provider_rows.empty:
                st.dataframe(provider_rows, use_container_width=True, hide_index=True)
            st.info(provider_status.get("production_note", "Connect external providers before public deployment."))
        except Exception as e:
            st.caption(f"Provider setup unavailable: {e}")
    elif section == "Data":
        st.markdown("### Data Stability")
        try:
            quality = api_get("/data-quality")
            cleanup = api_get("/data-cleanup/summary")
            q1, q2, q3, q4, q5 = st.columns(5)
            with q1:
                st.metric("Quality", f"{quality.get('score', 0)}%", quality.get("status"))
            with q2:
                st.metric("Cargo Rows", cleanup.get("summary", {}).get("cargo_manifests", 0))
            with q3:
                st.metric("Duplicate Groups", cleanup.get("summary", {}).get("duplicate_manifest_groups", 0))
            with q4:
                st.metric("Inferred Cargo", cleanup.get("summary", {}).get("inferred_live_manifests", 0))
            with q5:
                st.metric("Generated Rows", cleanup.get("summary", {}).get("generated_workflow_rows", 0))
            checks = pd.DataFrame(quality.get("checks", []))
            if not checks.empty:
                st.dataframe(checks, use_container_width=True, hide_index=True)
            duplicates = pd.DataFrame(cleanup.get("duplicate_manifests", []))
            if not duplicates.empty:
                with st.expander("Duplicate manifest groups"):
                    st.dataframe(duplicates, use_container_width=True, hide_index=True)
            st.dataframe(pd.DataFrame({"Recommendation": cleanup.get("recommendations", [])}), use_container_width=True, hide_index=True)
            if current_role() == "Admin":
                st.markdown("#### Admin Maintenance")
                st.caption("Safe defaults compact duplicate manifests and demote old live-AIS inferred cargo so it no longer appears verified.")
                clean_col1, clean_col2, clean_col3 = st.columns(3)
                with clean_col1:
                    compact_manifests = st.checkbox("Compact duplicate manifests", value=True, key="cleanup_compact_manifests")
                    demote_inferred = st.checkbox("Demote inferred live cargo", value=True, key="cleanup_demote_inferred")
                with clean_col2:
                    complete_old_actions = st.checkbox("Complete old AI actions", value=False, key="cleanup_complete_old_actions")
                    archive_resolved = st.checkbox("Remove old resolved incidents", value=False, key="cleanup_archive_resolved")
                with clean_col3:
                    archive_generated = st.checkbox("Remove resolved generated workflow rows", value=False, key="cleanup_archive_generated")
                    cleanup_confirm = st.text_input("Type CLEAN DATA", type="password", key="cleanup_confirm")
                cleanup_step_up = admin_step_up_ready("data_cleanup", "data cleanup")
                if st.button("Run Data Maintenance", use_container_width=True, disabled=not cleanup_step_up, icon=":material/cleaning_services:"):
                    if cleanup_confirm.strip().upper() != "CLEAN DATA":
                        st.error("Type CLEAN DATA before running maintenance.")
                    else:
                        try:
                            result = api_post("/data-cleanup/run", {
                                "confirm": cleanup_confirm,
                                "compact_manifests": compact_manifests,
                                "demote_inferred_live_manifests": demote_inferred,
                                "complete_old_actions": complete_old_actions,
                                "archive_resolved_incidents": archive_resolved,
                                "archive_generated_workflow": archive_generated,
                            }).json()
                            st.success("Data maintenance completed.")
                            st.dataframe(pd.DataFrame([result.get("changes", {})]), use_container_width=True, hide_index=True)
                        except Exception as cleanup_error:
                            st.error(f"Data maintenance failed: {cleanup_error}")
            else:
                st.caption("Data maintenance is Admin-only.")
        except Exception as e:
            st.caption(f"Data stability unavailable: {e}")
    else:
        st.markdown("### Deployment Hardening")
        try:
            production = api_get("/settings/production-mode")
            reliability = api_get("/system/reliability")
            hardening = api_get("/deployment/hardening")
            h1, h2, h3, h4, h5 = st.columns(5)
            with h1:
                st.metric("Hardening Score", hardening.get("score", 0), hardening.get("status", "unknown"))
            with h2:
                warnings = len([row for row in hardening.get("checks", []) if row.get("status") == "warn"])
                st.metric("Warnings", warnings)
            with h3:
                st.metric("App Mode", production.get("app_mode", "demo").title())
            with h4:
                st.metric("Demo Logins", "Allowed" if production.get("demo_accounts_allowed") else "Blocked")
            with h5:
                st.metric("System Reliability", f"{reliability.get('score', 0)}%", reliability.get("band", "unknown"))

            st.markdown("#### Production Mode Control")
            prod_cols = st.columns(3)
            with prod_cols[0]:
                st.metric("AIS SSL", production.get("ais_ssl_verification", "enabled"))
            with prod_cols[1]:
                st.metric("Auth Providers", len(production.get("connected_auth_providers", [])))
            with prod_cols[2]:
                st.metric("Demo Accounts", production.get("demo_accounts_count", 0))
            prod_checks = pd.DataFrame(production.get("checks", []))
            if not prod_checks.empty:
                st.dataframe(prod_checks, use_container_width=True, hide_index=True)
            with st.expander("System Reliability Checks", expanded=False):
                reliability_checks = pd.DataFrame(reliability.get("checks", []))
                if not reliability_checks.empty:
                    st.dataframe(reliability_checks, use_container_width=True, hide_index=True)
            st.caption(production.get("persist_note", "Set APP_MODE=production in deployment secrets for permanent production mode."))
            if current_role() == "Admin":
                desired_production = st.toggle("Enable production controls", value=bool(production.get("enabled", False)), key="production_mode_toggle")
                expected_phrase = "ENABLE PRODUCTION" if desired_production else "DISABLE PRODUCTION"
                production_confirm = st.text_input(f"Type {expected_phrase}", type="password", key="production_mode_confirm")
                production_step_up = admin_step_up_ready("production_mode", "production mode")
                if st.button("Apply Production Mode", use_container_width=True, disabled=not production_step_up, icon=":material/admin_panel_settings:"):
                    if production_confirm.strip().upper() != expected_phrase:
                        st.error(f"Type {expected_phrase} before applying.")
                    else:
                        try:
                            updated = api_post("/settings/production-mode", {
                                "enabled": desired_production,
                                "confirm": production_confirm,
                            }).json()
                            st.success(f"Production mode is now {updated.get('app_mode', 'demo')}.")
                        except Exception as prod_error:
                            st.error(f"Production mode update failed: {prod_error}")
            else:
                st.caption("Production mode changes are Admin-only.")

            checks_df = pd.DataFrame(hardening.get("checks", []))
            if not checks_df.empty:
                st.dataframe(checks_df, use_container_width=True, hide_index=True)
            st.markdown("#### Production Steps")
            st.dataframe(pd.DataFrame({"Step": hardening.get("hardening_steps", [])}), use_container_width=True, hide_index=True)
        except Exception as e:
            st.caption(f"Deployment hardening unavailable: {e}")

        if current_role() == "Admin":
            st.markdown("#### Demo Reset")
            confirm = st.text_input("Type RESET DEMO to clear generated command workflow rows", type="password", key="demo_reset_confirm")
            if st.button("Reset Generated Demo Workflow", use_container_width=True, icon=":material/restart_alt:"):
                if confirm.strip().upper() != "RESET DEMO":
                    st.error("Type RESET DEMO before resetting.")
                else:
                    try:
                        result = api_post("/demo/reset", {"confirm": confirm}).json()
                        st.success(result.get("note", "Demo state reset."))
                    except Exception as e:
                        st.error(f"Demo reset failed: {e}")
        else:
            st.caption("Demo reset is Admin-only.")


def render_workspace_switch(label, options, key):
    if hasattr(st, "segmented_control"):
        choice = st.segmented_control(label, options, default=options[0], key=key)
        return choice or options[0]
    return st.radio(label, options, index=0, horizontal=True, key=key)


def show_fleet_operations_hub():
    st.title("Fleet & Operations")
    st.caption("Combined working area for live fleet tracking, operations queue, cargo exposure, and ETA/delay predictions.")
    section = render_workspace_switch("Fleet workspace", ["Fleet Map", "Operations", "ETA Predictions"], "fleet_operations_section")
    if section == "Fleet Map":
        show_fleet_tracking()
    elif section == "Operations":
        show_operations_center()
    else:
        show_vessel_predictions()


def risk_brain_deck(packet):
    zones = []
    color_by_priority = {
        "P1": [239, 68, 68, 120],
        "P2": [245, 158, 11, 105],
        "P3": [34, 211, 238, 95],
    }
    line_color_by_priority = {
        "P1": [255, 255, 255, 230],
        "P2": [255, 236, 179, 220],
        "P3": [186, 230, 253, 210],
    }
    for zone in packet.get("map_layers", {}).get("risk_zones", []):
        priority = zone.get("priority", "P3")
        zones.append({
            **zone,
            "radius_m": float(zone.get("radius_nm", 200) or 200) * 1852,
            "fill_color": color_by_priority.get(priority, color_by_priority["P3"]),
            "line_color": line_color_by_priority.get(priority, line_color_by_priority["P3"]),
        })

    route_rows = []
    for route in packet.get("map_layers", {}).get("focus_routes", []):
        if route.get("path"):
            priority = route.get("priority", "P3")
            route_rows.append({
                **route,
                "color": line_color_by_priority.get(priority, line_color_by_priority["P3"]),
                "width": 5 if priority == "P1" else 4 if priority == "P2" else 2,
            })
    vessel_rows = []
    for vessel in packet.get("map_layers", {}).get("vessels", []):
        if vessel.get("lat") is None or vessel.get("lon") is None:
            continue
        priority = vessel.get("priority", "P3")
        vessel_rows.append({
            **vessel,
            "color": line_color_by_priority.get(priority, line_color_by_priority["P3"]),
            "halo": color_by_priority.get(priority, color_by_priority["P3"]),
            "radius": 115000 if priority == "P1" else 85000,
        })
    vessel_trails = [
        {"name": row.get("name"), "path": row.get("motion_trail"), "color": [191, 219, 254, 110]}
        for row in vessel_rows
        if isinstance(row.get("motion_trail"), list) and len(row.get("motion_trail")) >= 2
    ]

    layers = []
    if zones:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=zones,
            get_position="[lon, lat]",
            get_radius="radius_m",
            get_fill_color="fill_color",
            get_line_color="line_color",
            line_width_min_pixels=2,
            stroked=True,
            filled=True,
            pickable=True,
        ))
    if route_rows:
        layers.append(pdk.Layer(
            "PathLayer",
            data=route_rows,
            get_path="path",
            get_color="color",
            width_scale=1,
            width_min_pixels=2,
            get_width="width",
            pickable=True,
        ))
    if vessel_trails:
        layers.append(pdk.Layer(
            "PathLayer",
            data=vessel_trails,
            get_path="path",
            get_color="color",
            get_width=4,
            width_min_pixels=1,
            rounded=True,
        ))
    if vessel_rows:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=vessel_rows,
            get_position="[lon, lat]",
            get_fill_color="halo",
            get_radius="radius",
            stroked=True,
            get_line_color="color",
            line_width_min_pixels=2,
            pickable=True,
        ))
        layers.append(pdk.Layer(
            "TextLayer",
            data=vessel_rows,
            get_position="[lon, lat]",
            get_text="name",
            get_color=[248, 250, 252, 245],
            get_size=11,
            get_pixel_offset=[0, 24],
            get_alignment_baseline="'top'",
            get_text_anchor="'middle'",
        ))

    focus = zones[0] if zones else {"lat": 20, "lon": 15}
    return pdk.Deck(
        map_style=MAP_STYLE,
        layers=layers,
        initial_view_state=pdk.ViewState(latitude=focus.get("lat", 20), longitude=focus.get("lon", 15), zoom=1.45, pitch=42, bearing=-18),
        tooltip={
            "html": "<b>{name}{route}</b><br/>Category: {category}<br/>Risk: {risk_score}{score}{delay_risk}<br/>{note}{action}<br/>Motion: {motion_source}",
            "style": {"backgroundColor": "#06111f", "color": "#f8fafc"},
        },
    )


def show_ai_risk_brain():
    st.title("AI Risk Brain")
    st.caption("AI-oriented risk intelligence for natural hazards, hijack/piracy, war/geopolitical disruption, port failures, cyber/AIS integrity, cargo crime, and fuel shocks.")
    try:
        packet = api_get("/ai/risk-intelligence", fresh=True)
        routes = api_get("/routes")
    except Exception as e:
        show_api_error("AI Risk Brain", e)
        return

    summary = packet.get("summary", {})
    categories = packet.get("categories", [])
    overall = float(summary.get("overall_score", 0) or 0)
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Overall AI Risk", f"{overall:.1f}/100", summary.get("overall_band", "Stable"))
        st.progress(max(0, min(100, int(overall))) / 100)
    with m2:
        st.metric("Priority", summary.get("overall_priority", "P3"), summary.get("top_category", "No active category"))
    with m3:
        st.metric("Categories", summary.get("categories_monitored", 0), f"{summary.get('actionable_categories', 0)} actionable")
    with m4:
        st.metric("Source Mode", summary.get("source_mode", "fallback")[:24])

    top_caution = summary.get("top_caution")
    if summary.get("overall_priority") == "P1":
        st.error(top_caution or "Critical caution active.")
    elif summary.get("overall_priority") == "P2":
        st.warning(top_caution or "Watch caution active.")
    else:
        st.success(top_caution or "No major caution active.")

    if categories:
        card_cols = st.columns(min(3, len(categories)))
        for index, row in enumerate(categories[:3]):
            color = incident_color(row.get("priority"))
            steps = "<br>".join(f"- {safe_html(step)}" for step in row.get("solution_steps", [])[:3])
            with card_cols[index % len(card_cols)]:
                st.markdown(
                    f"""
                    <div class="inbox-card" style="--note-color:{color}; --chip-color:{color};">
                        <span class="severity-chip">{safe_html(row.get('priority'))}</span>
                        <span class="severity-chip">{safe_html(row.get('risk_level'))}</span>
                        <h4>{safe_html(row.get('category'))}</h4>
                        <b>{safe_html(row.get('risk_score'))}/100 | {safe_html(row.get('caution_window'))}</b>
                        <div>{safe_html(row.get('prediction'))}</div>
                        <div class="notification-meta">{steps}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    map_tab, levels_tab, predictions_tab, playbook_tab, memory_tab = st.tabs(["Threat Constellation", "Risk Levels", "Predictions", "AI Solutions", "Decision Memory"])
    with map_tab:
        st.pydeck_chart(risk_brain_deck(packet), use_container_width=True, height=500)
        st.caption("The map shows global watch zones and the top current route-pressure lines. Larger circles mean wider caution radius, not exact danger boundaries.")

    with levels_tab:
        level_df = pd.DataFrame(categories)
        if level_df.empty:
            st.info("No AI risk levels returned yet.")
        else:
            table_cols = ["category", "risk_score", "risk_level", "priority", "band", "caution_window", "ai_solution"]
            st.dataframe(level_df[table_cols], use_container_width=True, hide_index=True)
            fig = px.bar(
                level_df.sort_values("risk_score"),
                x="risk_score",
                y="category",
                color="priority",
                orientation="h",
                range_x=[0, 100],
                title="AI Risk Level by Incident Type",
            )
            st.plotly_chart(fig, use_container_width=True)
            selected_level = st.selectbox("Inspect evidence", level_df["category"].tolist(), key="risk_brain_evidence")
            selected_row = next((row for row in categories if row.get("category") == selected_level), {})
            st.markdown("#### Evidence")
            evidence_df = pd.DataFrame({"Evidence": selected_row.get("evidence", [])})
            st.dataframe(evidence_df, use_container_width=True, hide_index=True)
            alert_df = pd.DataFrame(selected_row.get("matched_alerts", []))
            if not alert_df.empty:
                st.markdown("#### Matched Alerts")
                st.dataframe(alert_df, use_container_width=True, hide_index=True)

    with predictions_tab:
        forecast_df = pd.DataFrame(packet.get("forecast", []))
        if forecast_df.empty:
            st.info("No prediction windows available.")
        else:
            forecast_long = forecast_df.melt(
                id_vars=["category", "horizon", "hours", "priority_no_action"],
                value_vars=["score_no_action", "score_with_controls"],
                var_name="projection",
                value_name="score",
            )
            forecast_long["projection"] = forecast_long["projection"].str.replace("_", " ").str.title()
            fig = px.line(
                forecast_long,
                x="hours",
                y="score",
                color="category",
                line_dash="projection",
                markers=True,
                range_y=[0, 100],
                title="No-Action vs Controlled Risk Projection",
            )
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(forecast_df, use_container_width=True, hide_index=True)

    with playbook_tab:
        category_options = [row.get("category") for row in categories] or ["Natural Hazard", "Hijack / Piracy", "War / Geopolitical"]
        route_choices = {"Network-wide": None}
        for route in routes:
            if route.get("origin_port") and route.get("destination_port"):
                route_choices[f"#{route.get('id')} {route.get('origin_port')} to {route.get('destination_port')}"] = route.get("id")

        p1, p2 = st.columns([1, 1])
        with p1:
            selected_category = st.selectbox("Incident type", category_options, key="risk_brain_category")
        with p2:
            selected_route_label = st.selectbox("Target route", list(route_choices.keys()), key="risk_brain_route")
        route_id = route_choices[selected_route_label]
        route_query = f"&route_id={route_id}" if route_id else ""
        try:
            playbook = api_get(f"/ai/incident-playbook?incident_type={quote(selected_category)}{route_query}")
        except Exception as e:
            show_api_error("AI playbook", e)
            return

        st.warning(playbook.get("prediction", "No prediction returned."))
        pcols = st.columns(3)
        with pcols[0]:
            st.metric("Playbook Risk", f"{playbook.get('risk_score', 0)}/100", playbook.get("risk_level"))
        with pcols[1]:
            st.metric("Priority", playbook.get("priority", "P3"), playbook.get("caution_window"))
        with pcols[2]:
            st.metric("Route", playbook.get("target_route", "Network-wide")[:24])

        solution_cols = st.columns(3)
        with solution_cols[0]:
            st.markdown("#### Immediate Steps")
            st.dataframe(pd.DataFrame({"Step": playbook.get("immediate_steps", [])}), use_container_width=True, hide_index=True)
        with solution_cols[1]:
            st.markdown("#### Route Controls")
            st.dataframe(pd.DataFrame({"Control": playbook.get("route_controls", [])}), use_container_width=True, hide_index=True)
        with solution_cols[2]:
            st.markdown("#### Communications")
            st.dataframe(pd.DataFrame({"Message Rule": playbook.get("communications", [])}), use_container_width=True, hide_index=True)

        allow_actions = can("approve_actions") or can("manage_alert_workflows") or can("run_scenarios")
        if not allow_actions:
            st.caption("Sign in as Admin or Operator to queue AI Risk Brain actions.")
        action_note = st.text_area("Action note", value=playbook.get("immediate_steps", ["Activate defensive playbook."])[0], key="risk_brain_action_note")
        cta_cols = st.columns(2)
        with cta_cols[0]:
            if st.button("Queue Defensive Playbook", type="primary", disabled=not allow_actions, use_container_width=True):
                result = api_post("/ai/risk-intelligence/action", {
                    "incident_type": selected_category,
                    "target": playbook.get("target_route", "Global network"),
                    "owner": current_role(),
                    "note": action_note,
                    "priority": playbook.get("priority", "P2"),
                    "action": "queue_playbook",
                    "route_id": route_id,
                }).json()
                st.success(f"Queued: {result.get('status')}")
                st.rerun()
        with cta_cols[1]:
            if st.button("Create Incident Record", disabled=not allow_actions, use_container_width=True):
                result = api_post("/ai/risk-intelligence/action", {
                    "incident_type": selected_category,
                    "target": playbook.get("target_route", "Global network"),
                    "owner": current_role(),
                    "note": action_note,
                    "priority": playbook.get("priority", "P2"),
                    "action": "create_incident",
                    "route_id": route_id,
                }).json()
                st.success(f"Created: {result.get('status')}")
                st.rerun()

    with memory_tab:
        caution_df = pd.DataFrame({"Caution": packet.get("cautions", [])})
        if not caution_df.empty:
            st.markdown("#### AI Cautions")
            st.dataframe(caution_df, use_container_width=True, hide_index=True)
        memory_df = pd.DataFrame(packet.get("decision_memory", []))
        if memory_df.empty:
            st.info("No decision memory yet.")
        else:
            st.markdown("#### Decision Memory")
            st.dataframe(memory_df, use_container_width=True, hide_index=True)
        with st.expander("How the AI Risk Brain thinks", expanded=False):
            st.write(packet.get("explainability", {}).get("method", "No explanation returned."))
            st.dataframe(pd.DataFrame({"Limits": packet.get("explainability", {}).get("limits", [])}), use_container_width=True, hide_index=True)


def show_risk_alerts_hub():
    st.title("Risk & Alerts")
    st.caption("Combined risk workspace for AI risk brain, route decisions, threat workflows, and forecast watch windows.")
    section = render_workspace_switch("Risk workspace", ["AI Risk Brain", "AI Risk Decisions", "Threat Alerts", "Risk Forecast"], "risk_alerts_section")
    if section == "AI Risk Brain":
        show_ai_risk_brain()
    elif section == "AI Risk Decisions":
        show_ai_risk_engine()
    elif section == "Threat Alerts":
        show_threat_center()
    else:
        show_risk_forecast()


def smart_inbox_action_for(item):
    item_type = str(item.get("item_type", "notification"))
    label = str(item.get("action_label", "")).lower()
    if item_type == "incident" and "resolve" in label:
        return "resolve"
    if item_type == "ai_action" and ("complete" in label or "approve" in label):
        return "complete" if "complete" in label else "approve"
    if "escalate" in label:
        return "escalate"
    return "assign_owner"


def render_smart_inbox_card(item, index, allow_actions):
    priority = item.get("priority", "P3")
    color, label = severity_tone("critical" if priority == "P1" else "warning" if priority == "P2" else "info")
    st.markdown(
        f"""
        <div class="inbox-card" style="--note-color:{color}; --chip-color:{color};">
            <span class="severity-chip">{safe_html(priority)}</span>
            <span class="severity-chip">{safe_html(item.get('item_type', 'item'))}</span>
            <h4>{safe_html(item.get('title', 'Inbox item'))}</h4>
            <b>{safe_html(item.get('target', 'Target'))}</b>
            <div>{safe_html(item.get('recommendation', 'Review this item.'))}</div>
            <div class="inbox-route">
                {safe_html(item.get('why', 'No evidence returned.'))}<br>
                Source: {safe_html(item.get('source', 'Unknown'))} | Page: {safe_html(item.get('page', 'Command Center'))} |
                Owner: {safe_html(item.get('owner', 'Operations'))} | Impact: {safe_html(item.get('impact_score', 0))}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    action_col1, action_col2, action_col3 = st.columns([0.85, 0.85, 1.2])
    with action_col1:
        if st.button(item.get("action_label", "Assign Owner"), key=f"inbox_primary_{index}_{item.get('item_id')}", disabled=not allow_actions, use_container_width=True):
            result = api_post("/operations/inbox/action", {
                "item_type": item.get("item_type"),
                "item_id": str(item.get("item_id", "")),
                "target": item.get("target"),
                "action": smart_inbox_action_for(item),
                "owner": current_role(),
                "note": f"Handled from Smart Inbox: {item.get('title')}",
                "priority": priority,
            }).json()
            st.success(f"Updated: {result.get('status', 'queued')}")
            st.rerun()
    with action_col2:
        if st.button("Escalate", key=f"inbox_escalate_{index}_{item.get('item_id')}", disabled=not allow_actions, use_container_width=True):
            result = api_post("/operations/inbox/action", {
                "item_type": item.get("item_type"),
                "item_id": str(item.get("item_id", "")),
                "target": item.get("target"),
                "action": "escalate",
                "owner": current_role(),
                "note": f"Escalated from Smart Inbox: {item.get('why')}",
                "priority": "P1",
            }).json()
            st.success(f"Escalated: {result.get('status', 'queued')}")
            st.rerun()
    with action_col3:
        st.caption(f"Open next: {item.get('page', 'Command Center')}")


def show_smart_operations_inbox():
    st.markdown("### Smart Operations Inbox")
    st.caption("One ranked queue for notifications, incidents, AI actions, vessel delay risk, cargo exposure, data quality, production readiness, and report stability.")
    try:
        inbox = api_get("/operations/inbox")
        reliability = api_get("/system/reliability")
    except Exception as e:
        show_api_error("Smart Operations Inbox", e)
        return

    mobile_mode = st.toggle(
        "Mobile Command Mode",
        value=bool(st.session_state.get("mobile_performance_mode", False)),
        help="Uses fewer cards, slower refresh, and less table rendering for phones.",
        key="smart_inbox_mobile_mode",
    )
    st.session_state.mobile_performance_mode = bool(mobile_mode)
    if mobile_mode and st.session_state.get("ui_refresh_seconds", 3) < 12:
        st.session_state.ui_refresh_seconds = 12

    refresh_col, owner_col = st.columns([0.8, 1.2])
    with refresh_col:
        live_refresh = st.toggle("Live Command Refresh", value=bool(st.session_state.get("live_command_refresh", False)), key="live_command_refresh")
    with owner_col:
        st.caption("When enabled, this page reloads on your selected refresh interval so live AIS and inbox pressure stay current.")
    if live_refresh:
        seconds = max(12 if mobile_mode else 10, int(st.session_state.get("ui_refresh_seconds", 10)))
        components.html(
            f"<script>setTimeout(() => window.parent.location.reload(), {seconds * 1000});</script>",
            height=0,
        )

    summary = inbox.get("summary", {})
    reliability_signals = reliability.get("signals", {})
    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.metric("Inbox Score", f"{summary.get('score', 0)}%", summary.get("band", "Unknown"))
    with m2:
        st.metric("P1", summary.get("p1", 0))
    with m3:
        st.metric("P2", summary.get("p2", 0))
    with m4:
        st.metric("System", f"{reliability.get('score', 0)}%", reliability.get("band", "Unknown"))
    with m5:
        st.metric("AIS Vessels", reliability_signals.get("ais", {}).get("live_vessels", 0))

    st.info(f"Top focus: {summary.get('top_focus', 'No urgent focus')}")
    allow_actions = can("approve_actions") or can("manage_alert_workflows") or can("edit_cargo") or can("generate_reports")
    if not allow_actions:
        st.warning(f"Your role can review the inbox, but cannot execute inbox actions: {current_role()}.")

    items = inbox.get("items", [])
    top_count = 6 if mobile_mode else 12
    if not items:
        st.success("Smart Inbox is clear. No active operations item needs command attention.")
    for index, item in enumerate(items[:top_count]):
        render_smart_inbox_card(item, index, allow_actions)

    if not mobile_mode and items:
        with st.expander("Full ranked inbox table"):
            st.dataframe(pd.DataFrame(items), use_container_width=True, hide_index=True)

    reliability_tabs = st.tabs(["Reliability", "Playbook", "Records"])
    with reliability_tabs[0]:
        checks = pd.DataFrame(reliability.get("checks", []))
        if not checks.empty:
            st.dataframe(checks, use_container_width=True, hide_index=True)
    with reliability_tabs[1]:
        st.dataframe(pd.DataFrame({"Step": inbox.get("quick_playbook", []) + reliability.get("recommendations", [])}), use_container_width=True, hide_index=True)
    with reliability_tabs[2]:
        records = reliability.get("records", {})
        if records:
            st.dataframe(pd.DataFrame([records]), use_container_width=True, hide_index=True)


def show_command_center_hub():
    st.title("Command Center")
    st.caption("One focused command brain for AI verdicts, problem solving, live control, inbox pressure, and audited command actions.")
    section = render_workspace_switch(
        "Command workspace",
        ["AI Captain", "Problem Solver", "Voyage Control Tower", "Smart Inbox", "Executive Command", "Strategic Autopilot"],
        "command_center_section",
    )
    if section == "AI Captain":
        show_ai_captain()
    elif section == "Problem Solver":
        show_command_copilot()
    elif section == "Voyage Control Tower":
        show_voyage_control_tower()
    elif section == "Smart Inbox":
        show_smart_operations_inbox()
    elif section == "Executive Command":
        show_executive_command()
    else:
        show_strategic_autopilot()


pages = {
    "Command Center": show_command_center_hub,
    "Fleet & Operations": show_fleet_operations_hub,
    "Scenario Lab": show_scenario_lab,
    "Risk & Alerts": show_risk_alerts_hub,
    "Reports": show_report_export,
    "Dashboard": show_global_dashboard,
}


ROLE_PAGE_ACCESS = {
    "Admin": ["Dashboard", "Command Center", "Fleet & Operations", "Risk & Alerts", "Scenario Lab", "Reports"],
    "Operator": ["Dashboard", "Command Center", "Fleet & Operations", "Risk & Alerts", "Scenario Lab", "Reports"],
    "Public": ["Dashboard"],
}


def pages_for_current_role():
    allowed = ROLE_PAGE_ACCESS.get(current_role(), ["Dashboard"])
    return {name: pages[name] for name in allowed if name in pages}


def is_public_access():
    return current_role() == "Public"


def is_read_only_access():
    return current_role() == "Public"


def sanitize_public_overview(overview):
    if not is_public_access():
        return overview
    safe = dict(overview or {})
    safe["live_vessels"] = [
        {
            **vessel,
            "cargo": "Public cargo",
            "cargo_class": "Public",
            "cargo_value": "Hidden",
            "value": "Hidden",
        }
        for vessel in safe.get("live_vessels", [])
    ]
    safe["public_mode"] = True
    return safe


def render_project_identity_bar(section):
    summary = SECTION_SUMMARIES.get(section, "AI-powered maritime intelligence, operations, and reporting")
    st.markdown(
        f"""
        <div class="project-identity">
            <div>
                <span class="project-kicker">Academic Project</span>
                <h1>{safe_html(PROJECT_TITLE)}</h1>
                <p><b>{safe_html(section)}</b> section: {safe_html(summary)}.</p>
            </div>
            <div class="project-section-chip">{safe_html(current_role())} View</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def main():
    _configure_page()
    _apply_global_styles()
    ensure_user_context()

    if auth_is_expired():
        st.warning("Session expired. Please sign in again.")
        return_to_login_gate()

    if not st.session_state.auth_entry_completed or not is_role_authenticated():
        render_login_gate(get_auth_metadata())
        return

    st.sidebar.title("Project Navigation")
    st.sidebar.markdown(
        f"""
        <div class="sidebar-brand">
            <b>{safe_html(PROJECT_TITLE)}</b>
            <span>{safe_html(PROJECT_SUBTITLE)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    allowed_pages = pages_for_current_role()
    st.sidebar.caption("Clean mode: main sections only. Alerts and Settings stay in the top bar.")
    st.sidebar.caption(f"{current_role()} | {auth_status_label()} | {st.session_state.auth_provider}")
    if st.sidebar.button("Security / Sign in", use_container_width=True, icon=":material/admin_panel_settings:"):
        st.session_state.utility_page = "Settings"
        st.rerun()
    health = {}
    notifications = []
    try:
        health = api_get("/health")
        notifications = api_get("/notifications?limit=25")
        aisstream = health.get("services", {}).get("aisstream", {})
        if isinstance(aisstream, dict) and aisstream.get("connected"):
            st.sidebar.success(f"AISStream connected: {aisstream.get('vessel_count', 0)} vessels")
        else:
            st.sidebar.caption("AISStream fallback mode")
        critical_notifications = sum(1 for item in notifications if item.get("severity") == "critical")
        st.sidebar.caption(f"{len(notifications)} notifications | {critical_notifications} critical")
    except Exception:
        st.sidebar.error("Backend offline")

    if "selected_page" not in st.session_state or st.session_state.selected_page not in allowed_pages:
        st.session_state.selected_page = next(iter(allowed_pages))
    page = st.sidebar.selectbox("Main Section", list(allowed_pages.keys()), key="selected_page", on_change=close_utility_page)
    render_top_utility_bar(notifications, health)
    render_project_identity_bar(page)

    allowed_pages[page]()

    # Footer
    st.markdown("""
    <div class="footer">
        <p>Global AI Trade Intelligence Platform | Academic Project | Streamlit + FastAPI + Explainable AI</p>
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
