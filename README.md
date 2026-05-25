# Global AI Trade Intelligence Platform

A demo-grade trade intelligence platform with a Streamlit frontend, FastAPI backend, SQLite/PostgreSQL database support, an ML-backed risk engine, and PDF export.

## What changed
- Streamlit app startup is now guarded behind `if __name__ == "__main__"`.
- ML model training is lazy-loaded and persisted to `ml/risk_model.joblib`.
- AI risk scoring now uses a deterministic explainable engine with top drivers, confidence, and action guidance.
- The backend exposes `/ai/risk-assessments` for route-level intelligence consumed by the Streamlit UI.
- PDF reports now include priority routes, high-severity alerts, and operational recommendations.
- Database setup is explicit via `python -m database.init_db`.
- PDF report generation ensures the target directory exists.
- Added `requests` to requirements and basic `pytest` support.
- Background report updates now use a fresh DB session.

## Features
- Global mission dashboard with route and fleet visualization
- Fleet tracking with live-style vessel and threat simulation
- AI risk scoring using hybrid rule-based and ML approaches
- Explainable route assessments with ML/rule cross-checks, confidence, top drivers, and recommended response
- Threat center with alert creation, filtering, severity/type charts, and CSV export
- Backend-powered risk forecast with history, route forecasts, and network average trend
- System health screen with service status, uptime, database counts, and data coverage charts
- Report workflow with configurable sections, saved report history, PDF export, and route CSV export
- Operations readiness scoring with bottlenecks, action owners, control checklist, and live mission brief
- Fleet management workflow with vessel creation, incident simulation, live threat overlay, and registry view
- Data log workflow with on-demand risk-log creation and trend/distribution analytics
- Optional real AIS vessel streaming through AISStream.io with cached backend fallback
- Operational Intelligence v2 with AIS history, cargo manifests, AI action approvals, and incident timeline
- Strict three-role access model for Admin, Operator, and Public workflows
- Admin fingerprint gate, operational MFA checks, and read-only Google/Facebook-style public access in the local security preview
- Persistent local user accounts, app-style Login/Create Account/Guest flows, and provider readiness checks for Google, Facebook, Instagram, Apple, Discord, Game Center, Xbox, SSO, and WebAuthn
- Notifications, runtime settings, cargo manifest editing, and route alternative optimization
- Actionable notification digest with one-click investigate, escalate, resolve, and watch workflows
- AI Mission Overlay that fuses War Room route pressure, risky vessels, and alert clusters into a single map layer
- Strategic Autopilot capstone that projects no-action risk, recommends the smallest safe intervention plan, shows route shields/blast radius/trust, and queues audited actions for verified roles
- AIS Reliability Center, Data Stability panel, real vessel detail drawer, and final Mission Pack export for a more self-maintaining demo
- Production Mode Control that blocks demo logins, enforces AIS SSL verification, and keeps unverified live AIS cargo clearly labeled as inferred
- Admin Data Maintenance that compacts duplicate manifests, demotes inferred live cargo, and archives noisy generated workflow rows after strict confirmation
- Smart Operations Inbox that ranks notifications, AI actions, incidents, vessel delay, cargo exposure, data quality, production readiness, and cleanup pressure in one command queue
- System Reliability dashboard with API, AIS, data quality, deployment, production mode, and inbox-health checks
- Mobile Command Mode and Live Command Refresh for smoother phone-friendly operations
- Scenario Lab digital twin that simulates storms, piracy, port shutdowns, cyber disruption, fuel shock, and cargo theft against live routes, vessels, cargo, and readiness
- Command Center with Executive Command + Strategic Autopilot modes, plus Command Copilot with global safest-route planning, incident replay, predictive ETA/delay scoring, alert escalation workflows, access control preview, data quality monitor, and deployment readiness checks
- Voyage Control Tower that acts as an Autonomous Maritime Command OS, fusing AIS anomalies, safest/fastest/lowest-cost route modes, notification pressure, reliability, approval queue, and a no-action timeline into one intervention screen
- AI Risk Brain that classifies natural hazards, hijack/piracy, war/geopolitical disruption, port infrastructure, cyber/AIS integrity, cargo crime, and fuel shocks into risk levels with caution windows, predictions, and defensive playbooks
- Product hardening suite with Admin user management, setup checklist, notification delivery outbox, security audit summary, database backup readiness, external weather/port/security provider hooks, and report-change intelligence
- Deployment hardening dashboard plus Alembic migration scaffold for safer production evolution
- SQLite fallback with optional PostgreSQL support

## AI Intelligence Endpoints
- `GET /ai/live` returns the backend live feed. When AISStream is configured it uses real AIS positions; otherwise it falls back to the local simulation.
- `GET /ai/risk-assessments` returns sorted route assessments with score, band, confidence, top drivers, and recommended action.
- `GET /ai/actions` returns persisted AI recommendations that operators can approve, reject, or complete.
- `POST /ai/actions/{action_id}/status` updates an AI action lifecycle state.
- `POST /ai/command` refreshes the live AI command packet on demand.
- `POST /copilot/ask` answers natural-language command questions from live platform data and global maritime route intelligence.
- `GET /copilot/global-route?origin=Mumbai&destination=Rotterdam` compares global maritime route alternatives and recommends the safest explainable path.
- `GET /routes/alternatives?route_id=1` returns current and alternate route options with risk deltas.
- `POST /scenario/simulate` runs a digital-twin crisis simulation and returns projected readiness, impacted routes, exposed vessels/cargo, a response plan, timeline, and map layers.
- `GET /executive/brief` returns the high-level commander summary, top route risks, top exposed vessels, and priority AI actions.
- `GET /ai/mission-map-overlay` returns fused War Room route, vessel, and alert layers for the Dashboard command map.
- `GET /ai/strategic-autopilot` returns the capstone risk trajectory, intervention plan, route shield, blast radius, trust signals, and map overlay.
- `POST /ai/strategic-autopilot/execute` turns a selected intervention into an audited incident or AI action for verified roles.
- `GET /ai/voyage-control-tower` returns the Autonomous Maritime Command OS packet with vessel anomalies, route mode recommendations, command timeline, alert digest, approval queue, and reliability signals.
- `POST /ai/voyage-control-tower/action` queues, approves, completes, reroutes, or escalates control-tower decisions with role checks and audit records.
- `GET /ai/risk-intelligence` returns the AI Risk Brain with incident-category risk levels, no-action vs controlled predictions, caution windows, global threat-zone layers, and decision memory.
- `GET /ai/incident-playbook?incident_type=War%20/%20Geopolitical` returns defensive solutions for natural, hijack/piracy, war/geopolitical, port, cyber/AIS, cargo, and fuel-shock problems.
- `POST /ai/risk-intelligence/action` queues a verified defensive playbook action or incident record from the AI Risk Brain.

## Operational Intelligence Endpoints
- `GET /operations/intelligence` returns readiness, cargo exposure, queued AI actions, and timeline summary.
- `GET /operations/timeline` returns incident and AI-action timeline rows.
- `GET /vessels/history` returns persisted AIS position history for trail maps.
- `GET /vessels/live` returns AISStream vessels or the local registry fallback.
- `GET /ais/reliability` returns AIS key/provider/SSL/connectivity checks, vessel freshness, stopped-vessel counts, and recent live ships.
- `GET /vessels/predictions` returns ETA and delay-risk predictions for live or local vessels.
- `GET /cargo/manifests` returns live cargo manifest records linked to vessels.
- `POST /cargo/manifests` creates or updates an operator-managed manifest.
- `GET /notifications` returns active action, incident, cargo, and stale-signal notifications.
- `GET /notifications/digest` returns the AI noise-reduced notification digest.
- `POST /notifications/action` queues, escalates, resolves, or acknowledges notification triage actions.
- `GET /operations/inbox` returns the ranked Smart Operations Inbox across alerts, incidents, AI actions, vessels, cargo, data quality, and production readiness.
- `POST /operations/inbox/action` executes audited inbox quick actions such as assign, approve, escalate, complete, or resolve.
- `GET /system/reliability` returns one overall reliability score for backend health, AIS, data quality, deployment, security hardening, production mode, and inbox health.
- `GET /settings/runtime` returns AIS/runtime configuration status and region presets.
- `POST /settings/runtime` applies safe runtime AIS cache and region tuning.
- `GET /settings/production-mode` returns production hardening controls, demo-account policy, SSL status, HTTPS status, and provider readiness.
- `POST /settings/production-mode` toggles runtime production controls after Admin confirmation.
- `GET /replay/timeline` returns replayable AIS, incident, and AI-action events.
- `GET /alerts/workflows` returns alert workflow ownership/status.
- `POST /alerts/{alert_id}/workflow` advances an alert through new, investigating, escalated, or resolved.
- `GET /auth/roles` returns strict role, permission, provider, MFA, fingerprint, session, and public OAuth policy metadata.
- `GET /auth/accounts` returns demo/persistent account metadata without password hashes.
- `POST /auth/login`, `POST /auth/register`, and `POST /auth/social-login` power the app-style role login system.
- `GET /auth/provider-status` shows which real OAuth/OIDC/WebAuthn environment variables are connected or still demo-only.
- `GET /admin/users` and `POST /admin/users` provide Admin-only user management for creating, disabling, promoting, and demoting accounts.
- `GET /security/audit-summary` summarizes risky audit events, top actions, actor roles, and security recommendations.
- `GET /setup/checklist` returns the first-time setup wizard state across backend, database, AIS, auth, notifications, external data, and production mode.
- `GET /notifications/delivery-status` and `POST /notifications/deliver` prepare critical alert delivery through a local outbox or configured external channels.
- `GET /database/operations` and `POST /database/backup` expose database health, production database guidance, and Admin-confirmed SQLite backups.
- `GET /external-data/status` and `GET /weather/maritime` expose environment-driven provider readiness plus transparent fallback weather signals.
- `GET /reports/intelligence` compares recent reports and highlights what changed or was resolved.
- `GET /data-quality` returns data freshness, duplicate, cargo, and AIS configuration checks.
- `GET /data-cleanup/summary` summarizes noisy generated rows, duplicate manifests, and cleanup recommendations.
- `POST /data-cleanup/run` runs Admin-confirmed maintenance for duplicate manifests, inferred live cargo, and generated workflow noise.
- `GET /deployment/readiness` returns packaging, CI, config, health, and database deployment checks.
- `GET /deployment/hardening` returns security, secrets, HTTPS, provider, and deployment hardening checks.
- `POST /demo/reset` clears generated command workflow rows after Admin confirmation.
- `GET /reports/smart?brief_type=CEO%20brief` generates a smart executive/security/fleet/risk brief.

## Real AIS Setup
To use real vessel positions, put your AISStream key in `.env`:
```powershell
AIS_PROVIDER=aisstream
AISSTREAM_API_KEY=your_aisstream_key
AISSTREAM_MAX_VESSELS=12
```

The backend connects to `wss://stream.aisstream.io/v0/stream`, caches recent vessel positions, and serves them through `/ai/live` and `/vessels/live`. Dashboard, Fleet Map, Mission Brief, System Health, Reports, Threat Center, and operations analytics prefer AISStream data when available, then fall back to the local fleet registry without exposing the API key to the browser. Live AIS cargo is labeled as `Inferred Demo Cargo` unless an operator-managed cargo manifest matches the vessel, in which case it becomes `Verified Manifest`.

If AISStream's websocket certificate verification fails in a local demo, set `AISSTREAM_ALLOW_INSECURE_SSL=true` in `.env`. Keep that disabled for production.

Set `APP_MODE=production` in deployment secrets to persist production controls after restart. The Settings page can also toggle production mode for the running backend process during demos.

## Analytics and Operations Endpoints
- `GET /analytics/overview` returns dashboard metrics, fleet status, port readiness, regional risk, latest alerts, and priority routes.
- `GET /analytics/operations` returns readiness score, bottlenecks, next actions, and an operational control checklist.
- `GET /analytics/forecast?days=14` returns historical risk logs plus route-level forecast rows.
- `GET /reports` returns recent generated report metadata.
- `GET /health` returns service status, uptime, AI loop state, and database record counts.

## Setup
1. Clone the repository.
2. Create a virtual environment:
   ```powershell
   python -m venv venv
   ```
3. Activate the environment:
   ```powershell
   venv\Scripts\activate
   ```
4. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
5. Copy `.env.example` to `.env` and adjust values if needed.
6. Initialize the database:
   ```powershell
   python -m database.init_db
   ```

## Run the Backend
From the project root:
```powershell
uvicorn backend.main:app --reload
```
Open http://127.0.0.1:8000.

## Run the Streamlit App
From the project root:
```powershell
streamlit run frontend/app.py
```
Open the URL shown in the Streamlit console.

## Demo Runner
You can also use the bundled helper:
```powershell
.\run_demo.ps1
```
This starts the backend on `http://127.0.0.1:8001` and the frontend on `http://127.0.0.1:8502`.

## Docker
You can run the backend and frontend with Docker Compose:
```powershell
docker compose up --build
```

Backend: http://127.0.0.1:8001  
Frontend: http://127.0.0.1:8502

## Testing
Run the test suite with:
```powershell
python -m pytest
```

## Notes
- The seeded demo DB lives at `database/trade_intelligence.db`; the app copies it to `.runtime/trade_intelligence.db` for writable local runs.
- `requests` is required by the frontend app to call backend APIs.
- Use `.env` to override `API_BASE` or a PostgreSQL connection string.
- Local role sign-in is a hardened demo preview. Before internet deployment, connect real OIDC/OAuth and WebAuthn fingerprint providers behind HTTPS.
- Settings > Deployment contains the production-mode switch; Settings > Data contains Admin data maintenance. Both require strict Admin confirmation phrases.

## Future improvements
- Add production identity-provider callbacks and server-side token verification
- Add real port congestion, weather, and maritime security data feeds
- Increase ML model fidelity with real historical data
