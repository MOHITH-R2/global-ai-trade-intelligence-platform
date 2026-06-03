# Design Diagrams

Project Title: Global AI Trade Intelligence Platform

This page contains submission-ready ER and DFD diagrams for the project. If drawing by hand, use the simplified versions and explain the points below each diagram.

## ER Diagram

```mermaid
erDiagram
    USER_ACCOUNT {
        int id PK
        string email
        string display_name
        string role
        string provider
        string status
        datetime created_at
        datetime last_login_at
    }

    VESSEL {
        int id PK
        string name
        float position_lat
        float position_lon
        string status
    }

    TRADE_ROUTE {
        int id PK
        string origin_port
        string destination_port
        float risk_level
        float distance
    }

    RISK_LOG {
        int id PK
        int route_id FK
        float risk_score
        datetime timestamp
    }

    THREAT_ALERT {
        int id PK
        string title
        text description
        string severity
        string location
    }

    AIS_POSITION_HISTORY {
        int id PK
        string vessel_identifier
        string vessel_name
        float position_lat
        float position_lon
        float speed_knots
        float heading
        string nearest_port
        string source
        string status
        datetime timestamp
    }

    CARGO_MANIFEST {
        int id PK
        string vessel_identifier
        string vessel_name
        string cargo
        string cargo_class
        float cargo_tons
        string cargo_value
        string origin_port
        string destination_port
        string priority
        string status
        datetime updated_at
    }

    AI_ACTION {
        int id PK
        string priority
        string subject
        string action_type
        text recommendation
        text evidence
        string status
        string owner
        string source
        datetime created_at
        datetime updated_at
    }

    INCIDENT_EVENT {
        int id PK
        string title
        string category
        string severity
        string location
        string vessel_name
        string route
        text description
        string source
        string status
        datetime timestamp
    }

    GENERATED_REPORT {
        int id PK
        text content
        datetime timestamp
    }

    AUDIT_LOG {
        int id PK
        string actor_role
        string actor_identity
        string action
        string resource
        string severity
        text detail
        datetime timestamp
    }

    TRADE_ROUTE ||--o{ RISK_LOG : has
    VESSEL ||--o{ AIS_POSITION_HISTORY : records
    VESSEL ||--o{ CARGO_MANIFEST : carries
    TRADE_ROUTE ||--o{ CARGO_MANIFEST : assigned_to
    THREAT_ALERT ||--o{ AI_ACTION : triggers
    INCIDENT_EVENT ||--o{ AI_ACTION : requires
    USER_ACCOUNT ||--o{ AUDIT_LOG : performs
    AI_ACTION ||--o{ AUDIT_LOG : audited_by
```

### ER Diagram Explanation

- `UserAccount` stores login details, role, provider, and account status.
- `Vessel` stores the main ship information and latest position.
- `TradeRoute` stores origin, destination, distance, and route risk.
- `RiskLog` stores historical risk scores for a route.
- `ThreatAlert` stores warnings such as piracy, storm, war, port delay, and cyber risk.
- `AISPositionHistory` stores vessel movement history from AIS or fallback data.
- `CargoManifest` stores cargo details linked to vessels and routes.
- `AIAction` stores AI-generated recommendations, approvals, and action status.
- `IncidentEvent` stores operational events or crisis records.
- `GeneratedReport` stores report content and timestamp.
- `AuditLog` stores important user/admin/operator actions for accountability.

## DFD Level 0 - Context Diagram

```mermaid
flowchart LR
    U[User / Admin / Operator / Public]
    S[Global AI Trade Intelligence Platform]
    DB[(Database)]
    AIS[AISStream / Live Vessel API]
    EXT[External Data Providers]
    REP[PDF / Report Output]

    U -->|Login, view dashboard, ask copilot, manage alerts| S
    S -->|Maps, risk scores, reports, recommendations| U
    S -->|Read and write records| DB
    AIS -->|Live vessel positions| S
    EXT -->|Weather, port, security, route signals| S
    S -->|Generated reports| REP
```

### Level 0 Explanation

The user interacts with the platform through the Streamlit frontend. The system collects data from the database, live AIS provider, and external risk sources. FastAPI processes the request, AI/risk logic generates output, and the result is shown as maps, dashboards, alerts, recommendations, and reports.

## DFD Level 1 - Main Process Flow

```mermaid
flowchart TD
    U[User]
    P1[1. Authentication and Role Check]
    P2[2. Vessel and AIS Data Handling]
    P3[3. Route and Cargo Management]
    P4[4. AI Risk Analysis]
    P5[5. Alerts and Incident Workflow]
    P6[6. Reports and Dashboard Output]
    P7[7. Audit and Settings Control]

    D1[(User Accounts)]
    D2[(Vessels and AIS History)]
    D3[(Routes and Cargo Manifests)]
    D4[(Risk Logs)]
    D5[(Threat Alerts and Incidents)]
    D6[(Reports)]
    D7[(Audit Logs)]

    AIS[AISStream API]
    EXT[Weather / Port / Security Data]

    U --> P1
    P1 <--> D1
    P1 --> P2

    AIS --> P2
    P2 <--> D2
    P2 --> P4

    U --> P3
    P3 <--> D3
    P3 --> P4

    EXT --> P4
    P4 <--> D4
    P4 --> P5
    P4 --> P6

    P5 <--> D5
    P5 --> P7

    P6 <--> D6
    P6 --> U

    P7 <--> D7
    P7 --> U
```

### Level 1 Explanation

1. User logs in as Admin, Operator, or Public.
2. The system verifies role permissions.
3. Vessel data is loaded from AISStream or local fallback records.
4. Route and cargo data are loaded from the database.
5. AI risk engine combines vessel, route, cargo, alert, and external signals.
6. The platform creates risk scores, route suggestions, alerts, and action plans.
7. Results are displayed in dashboards, maps, reports, and the AI Copilot.
8. Sensitive actions are stored in audit logs.

## DFD Level 2 - AI Risk Analysis Process

```mermaid
flowchart TD
    A[Input Route Details]
    B[Input Vessel Position and Speed]
    C[Input Cargo Priority]
    D[Input Alerts and Incidents]
    E[Input External Conditions]
    F[Calculate Risk Score]
    G[Classify Risk Category]
    H[Generate Recommendation]
    I[Save Risk Log / AI Action]
    J[Display Result to User]

    A --> F
    B --> F
    C --> F
    D --> F
    E --> F
    F --> G
    G --> H
    H --> I
    H --> J
```

### Level 2 Explanation

The AI risk process takes route, vessel, cargo, alert, incident, and external condition data. It calculates a risk score, identifies the risk category, generates a suggested action, saves important records, and displays the decision to the user.

## Simple Hand-Drawn Version

If you have to draw quickly in the exam, draw these:

### Simple ER

```text
UserAccount -> AuditLog
TradeRoute -> RiskLog
TradeRoute -> CargoManifest
Vessel -> AISPositionHistory
Vessel -> CargoManifest
ThreatAlert -> AIAction
IncidentEvent -> AIAction
AIAction -> AuditLog
GeneratedReport is stored separately for report history.
```

### Simple DFD

```text
User
  -> Streamlit Frontend
  -> FastAPI Backend
  -> Database + AIS API + AI Risk Engine
  -> Dashboard / Maps / Alerts / Reports / Copilot Answer
```

## Short Explanation For Invigilator

The ER diagram shows how the database is structured. The main entities are users, vessels, trade routes, risk logs, threat alerts, cargo manifests, AI actions, incidents, reports, and audit logs. Routes have many risk logs, vessels have AIS history and cargo manifests, and user actions are stored in audit logs.

The DFD shows how data moves through the system. The user uses the Streamlit frontend, the frontend calls FastAPI, the backend reads database and AIS/API data, the AI risk engine processes it, and the final output is displayed as dashboards, maps, alerts, route suggestions, reports, and AI Copilot answers.
