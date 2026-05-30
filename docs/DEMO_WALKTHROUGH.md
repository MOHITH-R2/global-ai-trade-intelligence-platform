# Demo Walkthrough

Use this flow for a 5 to 7 minute project presentation.

## 1. Start The Project

```powershell
.\run_demo.ps1 -Restart
```

Open:

```text
http://127.0.0.1:8502
```

## 2. Login

Use the Admin demo login when presenting full features:

- Email: `admin@demo.app`
- Password: `admin-demo`
- Fingerprint confirmation: checked
- Phrase: `ADMIN ACCESS`

Use Operator demo if you want to show operational workflow without admin settings.

## 3. Dashboard

Start with **Dashboard**.

Explain:

- It shows mission posture, readiness, risk, alerts, vessels, and routes.
- The map uses live AIS data when available and fallback demo data when not.
- Public users only get sanitized dashboard access.

## 4. Command Center > AI Captain

Open **Command Center > AI Captain**.

Explain:

- AI Captain combines Mission Control, Strategic Autopilot, AI Risk Brain, route optimizer, AIS health, notifications, and vessel predictions.
- It gives one final decision: Safe, Delay, Reroute, Escalate, or Stop Voyage.
- Show the global route optimizer from Mumbai to Rotterdam.
- Show the incident prediction tab and emergency war-room steps.

## 5. Fleet & Operations

Open **Fleet & Operations**.

Explain:

- Ships are shown with cargo, speed, route, destination, and operational status.
- Real AIS vessels are used if the API is connected.
- Ship intelligence gives ETA risk and AI recommendations.

## 6. Risk & Alerts

Open **Risk & Alerts > AI Risk Brain**.

Explain:

- The system classifies natural hazard, hijack/piracy, war/geopolitical, port, cyber/AIS, cargo crime, and fuel-shock risks.
- It gives caution windows, no-action predictions, controlled predictions, and playbooks.

## 7. Reports

Open **Reports**.

Explain:

- The platform generates executive, fleet, risk, and security reports.
- Use Mission Pack for a final command summary.

## 8. Settings

Open the Settings icon.

Explain:

- Shows production readiness, AIS provider status, security checks, database operations, and external data hooks.
- Real production needs HTTPS, real OAuth/WebAuthn, production secrets, PostgreSQL, and verified external APIs.

## Closing Line

This project is not only a ship map. It is an AI-oriented maritime command platform that predicts trade risk, recommends safer routes, protects cargo, and supports role-based operational decisions.
