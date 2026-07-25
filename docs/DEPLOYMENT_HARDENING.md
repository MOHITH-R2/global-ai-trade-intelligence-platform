# Deployment Hardening

This project is still demo-friendly, but it now has a clearer production path.

## Before Public Deployment

- Set `PUBLIC_BASE_URL` to an HTTPS origin.
- Set `CORS_ORIGINS` to the deployed frontend origin.
- Set `APP_MODE=production` or `PRODUCTION_MODE=true`.
- Move `AISSTREAM_API_KEY`, OAuth secrets, OIDC secrets, and WebAuthn settings into deployment secret storage.
- Keep `AISSTREAM_ALLOW_INSECURE_SSL=false`.
- Use a persistent PostgreSQL `DATABASE_URL` for real multi-user deployments.
- Use real OAuth/OIDC callbacks for Google, Facebook, Instagram, Apple, Discord, Microsoft/Xbox, and Company SSO.
- Back Admin fingerprint with WebAuthn or a trusted identity provider.
- Run database migrations with Alembic instead of relying only on `Base.metadata.create_all`.
- Keep `Public Visitor` read-only and sanitized.
- Review `/deployment/hardening` until warnings are resolved.
- Review `/deployment/readiness` after every deploy.

## Container Notes

- The Dockerfile runs the FastAPI backend and honors the platform `PORT` variable.
- Docker Compose runs two services: backend on `8001` and Streamlit on `8502`.
- Compose waits for backend `/health` before starting the frontend.
- Fresh runtime databases are seeded at backend startup, so deployments do not depend on a checked-in SQLite file.
- Local `.env`, SQLite files, report exports, and ML artifacts are excluded from Docker images.

## Useful Commands

```powershell
venv\Scripts\python.exe -m pytest
alembic upgrade head
.\run_demo.ps1
.\scripts\demo_walkthrough.ps1
```

## Current Auth Model

- Admin requires password, simulated fingerprint confirmation, and the exact phrase `ADMIN ACCESS`.
- Fleet Operator and Risk Analyst require password plus a 6-digit MFA/passkey code.
- Viewer uses authenticated read-only access.
- Public Visitor uses guest or social-style login and cannot write data.

## Strategic Autopilot

The Strategic Autopilot is the capstone command layer. It reads Mission Control, War Room, route risk, ETA prediction, notification digest, data quality, hardening, and live AIS status. It can recommend interventions in read-only mode, but execution is still role-gated and audited.

- Admin can execute all autopilot interventions.
- Fleet Operator can execute fleet/action interventions.
- Risk Analyst can execute alert/report workflow interventions.
- Viewer can review the plan but cannot execute it.
- Public Visitor cannot access the page.

## Stabilization Release

This release is intended to keep the demo stable without constant follow-up updates.

- AIS Reliability Center explains API key, websocket, SSL, vessel freshness, and live cache state.
- Data Stability summarizes duplicate/noisy generated rows and when to use Demo Reset.
- Fleet map includes a real vessel detail drawer for MMSI, speed, heading, cargo, and AI recommendation.
- Reports include a final Mission Pack export with Strategic Autopilot, War Room, AIS reliability, and AI self-check context.
- Production hardening warns when local-demo AIS SSL bypass is enabled.
