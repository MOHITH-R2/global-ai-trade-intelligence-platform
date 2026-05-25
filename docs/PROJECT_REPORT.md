# Global AI Trade Intelligence Platform

## Final Project Report

**Project Title:** Global AI Trade Intelligence Platform  
**Domain:** Maritime Logistics, Artificial Intelligence, Real-Time Risk Intelligence  
**Frontend:** Streamlit  
**Backend:** FastAPI  
**Database:** SQLite with optional PostgreSQL support  
**AI and Analytics:** Rule-based risk engine, ML-assisted risk scoring, scenario simulation, route intelligence  
**Prepared By:** Student Name  
**Institution:** Institution Name  
**Academic Year:** 2025-2026  

---

## Certificate

This is to certify that the project titled **Global AI Trade Intelligence Platform** has been developed as a final year project work. The project demonstrates the design and implementation of an AI-oriented maritime intelligence platform for monitoring vessels, predicting route risks, identifying threats, managing operations, and supporting safer global trade decisions.

The work includes frontend development, backend API design, database management, real-time AIS integration, role-based access control, notification workflows, report generation, and AI-assisted risk analysis. The project has been tested using functional, integration, security, usability, and performance-oriented testing methods.

---

## Declaration

I declare that this project report titled **Global AI Trade Intelligence Platform** is based on the work carried out for the development of an intelligent maritime trade monitoring and risk decision-support system. The report has been prepared for academic submission and explains the objectives, scope, methodology, system design, implementation, testing, results, conclusion, and future enhancement opportunities of the project.

---

## Acknowledgement

I would like to express my sincere gratitude to my teachers, mentors, classmates, and family members for their support and guidance during the completion of this project. I also acknowledge the open-source Python ecosystem and documentation resources used for learning and implementation, including Streamlit, FastAPI, SQLAlchemy, scikit-learn, Plotly, PyDeck, ReportLab, and AIS-based maritime data references.

This project helped me gain practical knowledge in web application development, API integration, database management, artificial intelligence, security design, real-time data handling, and maritime risk analytics.

---

## Abstract

The **Global AI Trade Intelligence Platform** is an AI-powered maritime command and risk intelligence system designed to support global shipping, cargo movement, fleet monitoring, and operational decision-making. In modern trade, ships carry important cargo such as fuel, gold, machinery, food, medicine, containers, and industrial goods across international waters. These routes are affected by natural hazards, piracy, hijacking, war, port congestion, cyber threats, fuel price changes, and cargo crime. Traditional monitoring systems often provide only basic vessel tracking and do not combine live ship movement with explainable risk predictions, notification intelligence, role-based workflows, and decision support.

This project solves that problem by creating a unified platform with a Streamlit frontend and FastAPI backend. It supports real-time-style vessel visualization, AISStream integration, AI risk scoring, route forecasting, incident playbooks, cargo awareness, scenario simulation, threat alerts, operations readiness, report generation, and admin-controlled security settings. The system includes a strict three-role access model: Admin, Operator, and Public. Admin users can manage production controls and data maintenance, operators can investigate and execute actions, and public users receive limited read-only access.

The platform also contains an AI Risk Brain that classifies threats into categories such as natural hazards, hijack or piracy, war or geopolitical disruption, port infrastructure issues, cyber or AIS integrity problems, cargo crime, and market or fuel shock. For each risk, the system provides severity level, caution window, prediction, explanation, and recommended defensive playbook. The project is designed as a smart maritime command center that can help users understand what is happening, what may happen next, and what action should be taken.

---

## Table of Contents

1. Chapter 1 - Introduction  
2. Chapter 2 - Literature Survey  
3. Chapter 3 - System Analysis  
4. Chapter 4 - System Design  
5. Chapter 5 - Results  
6. Chapter 6 - Implementation  
7. Chapter 7 - Software Testing  
8. Chapter 8 - Source Code Summary  
9. Chapter 9 - Screenshots of Project  
10. Chapter 10 - Conclusion and Future Enhancement  
11. Bibliography  

---

# Chapter - 1

## Introduction

Global trade depends heavily on maritime transportation. A large percentage of international goods move through sea routes because ships can carry huge cargo volumes across long distances at comparatively lower cost. Petroleum, gold, machinery, vehicles, food grains, pharmaceuticals, electronics, raw materials, and containerized goods are transported through international shipping routes every day. Because of this, maritime transportation is one of the most important parts of the world economy.

However, maritime trade is also exposed to many risks. Ships may face storms, cyclones, heavy waves, port shutdowns, piracy, hijacking, war zones, sanctions, cyber attacks, AIS signal problems, traffic congestion, cargo theft, fuel shock, and route delays. If these risks are not identified early, they can cause financial loss, safety issues, late delivery, insurance problems, and supply chain disruption.

Traditional systems mainly focus on tracking vessel location or maintaining basic logistics records. They usually do not provide strong AI-based prediction, explainable risk scoring, route alternatives, threat categories, real-time alerts, role-based decision workflows, or command-level operational intelligence. Because of this limitation, shipping operators may need to use multiple tools separately for fleet tracking, risk analysis, reports, notifications, and route decisions.

The **Global AI Trade Intelligence Platform** is developed to overcome these limitations. It provides a single intelligent command platform where users can monitor ships, view cargo exposure, analyze threats, generate reports, manage notifications, simulate crisis scenarios, and receive AI-assisted risk decisions. The system uses a modern Python-based technology stack consisting of Streamlit for the frontend, FastAPI for the backend, SQLAlchemy for database handling, and machine learning libraries for risk prediction.

The system is designed to work with both demo data and real AIS vessel feeds. If an AIS provider is configured, the platform uses real vessel positions from the API. If the API is unavailable, the platform safely falls back to local simulated data. This makes the project useful for demonstration, learning, testing, and future production deployment.

One of the most important parts of this project is the AI-oriented risk system. The platform does not only display data; it interprets the data. It classifies threats, identifies risk drivers, compares current conditions with expected route safety, predicts what may happen if no action is taken, and recommends safer operational steps. This makes the system more useful than a simple dashboard.

The project also focuses on usability. Different sections of the application are designed for different operational needs. The Dashboard gives a high-level command overview. Fleet and Operations provides vessel and route monitoring. Risk and Alerts provides AI risk intelligence and active threat management. The Command Center gives executive-level decision support. Settings and notifications are available through icons, similar to modern applications, so the interface remains clean.

## 1.1 Project Objectives

The main objective of this project is to develop a smart AI-powered maritime trade intelligence platform that improves vessel monitoring, route safety, risk prediction, and operational decision-making.

### I. Real-Time Vessel Awareness

- Display ships on interactive maps using real AIS data when available.
- Show vessel movement, heading, speed, cargo type, destination, and operational status.
- Provide animated map behavior so users can understand vessel direction and route progress.
- Support fallback demo data when the real AIS provider is unavailable.

### II. AI-Based Risk Intelligence

- Analyze maritime risks using a hybrid rule-based and ML-assisted approach.
- Classify risks into natural hazards, piracy, war, cyber, port, cargo, and market categories.
- Provide risk level, confidence score, top drivers, and recommended action.
- Support incident playbooks for different threat types.

### III. Safer Route Decision Support

- Help users compare route alternatives based on risk, delay, cargo sensitivity, and operational readiness.
- Recommend safer route options for global journeys.
- Provide caution windows and no-action predictions.
- Support global route planning through the command copilot.

### IV. Operational Command and Control

- Provide an operations readiness score.
- Detect bottlenecks, active incidents, exposed cargo, and route pressure.
- Give priority actions to operators and admins.
- Support action approval, escalation, completion, and audit tracking.

### V. Role-Based Security

- Provide strict access based on Admin, Operator, and Public roles.
- Allow Admin users to manage settings, production mode, users, backups, and data cleanup.
- Allow Operators to investigate alerts, manage incidents, and execute approved actions.
- Allow Public users to access only safe read-only views.

### VI. Reporting and Documentation

- Generate smart reports and PDF exports.
- Maintain report history.
- Export route and alert data when required.
- Provide intelligence summaries for executive, fleet, risk, and security use cases.

## 1.2 Project Scope

The scope of this project is to develop a full-stack maritime intelligence system that combines frontend dashboards, backend APIs, database operations, risk analytics, AI decision support, and real-time vessel visualization.

The platform covers the following major areas:

- Global dashboard for mission summary.
- Fleet map with ship position and cargo details.
- Operations center for route and readiness monitoring.
- Risk and alerts center for threat intelligence.
- AI Risk Brain for incident classification and defensive playbooks.
- Scenario Lab for crisis simulation.
- Voyage Control Tower for command-level intervention.
- Command Copilot for topic-specific AI guidance.
- Notification digest and action workflows.
- Settings and production hardening controls.
- Role-based login and account management.
- Report generation and export.
- AIS reliability and data quality monitoring.

The project is suitable for academic demonstration and can be extended into a production-grade maritime monitoring tool. It is not intended to replace official maritime safety systems without further validation, certification, legal review, production identity provider integration, and verified live data providers.

## 1.3 Project Benefits

### I. Improved Maritime Safety

- Early identification of risky routes and threat zones.
- Better awareness of vessels exposed to piracy, storms, or war disruption.
- Defensive playbooks for different incident categories.
- Faster incident response through alerts and command workflows.

### II. Better Decision-Making

- AI risk scores explain why a route or vessel is considered risky.
- Operators can compare safer, faster, and lower-cost options.
- Command Center provides executive-level summaries.
- No-action projections help users understand future danger.

### III. Time Efficiency

- Automated dashboards reduce manual checking.
- Smart notifications prioritize important problems.
- Reports can be generated quickly.
- Route and vessel information is available in one place.

### IV. Data Management

- Route, vessel, cargo, alert, action, report, and incident data are stored digitally.
- SQLite is used for local development and PostgreSQL can be used for production.
- Admin maintenance tools help clean demo data and manage backups.
- Data quality checks identify stale, duplicate, or inferred records.

### V. User-Friendly Interface

- Streamlit provides an interactive browser-based interface.
- Maps, metrics, charts, tabs, and action buttons make the system easy to use.
- Notification and settings icons reduce page clutter.
- Mobile command mode improves usability on smaller screens.

### VI. Security and Reliability

- Role-based access prevents unauthorized actions.
- Production mode blocks unsafe demo behavior.
- Admin confirmation phrases protect sensitive operations.
- Audit summaries help track important security actions.

---

# Chapter - 2

## Literature Survey

Maritime intelligence systems have evolved from basic manual records to digital vessel tracking and advanced operational analytics. Earlier systems mostly depended on human communication, paper-based logs, port notices, weather bulletins, and manual route planning. With the growth of global trade and containerized shipping, digital systems became necessary for better accuracy and faster decision-making.

AIS, or Automatic Identification System, is one of the most important technologies in maritime tracking. It allows ships to broadcast identification, location, speed, heading, and voyage-related information. Many modern vessel tracking platforms use AIS feeds to show live vessel positions on maps. However, AIS data alone is not enough for operational decision-making. A ship location tells where a ship is, but it does not always tell whether the ship is safe, what risk it may face next, or what decision should be taken.

Recent research and industry solutions focus on combining vessel tracking with artificial intelligence, predictive analytics, geospatial visualization, weather monitoring, port congestion analysis, cyber security, and supply chain risk management. AI-based maritime systems can identify abnormal vessel behavior, predict delays, classify route risk, estimate arrival times, and detect possible fraud or cargo exposure.

The current project follows this modern direction by combining multiple intelligence layers into a single platform. It uses real AIS data when available, simulated fallback data for demo continuity, AI-based risk scoring, route forecast, cargo intelligence, notification digest, scenario simulation, and role-based command workflows.

## 2.1 Related Works

Many existing maritime platforms provide vessel tracking through AIS data. These systems display ships on maps, show speed and destination, and allow users to search vessels. Examples include commercial vessel tracking platforms, port authority dashboards, shipping company fleet tools, and logistics visibility platforms.

Some systems focus on weather and route optimization. They help shipping companies avoid storms, reduce fuel usage, and improve estimated time of arrival. Weather routing is useful, but it may not cover piracy, geopolitical conflict, cargo theft, cyber threats, and operational approvals.

Other systems focus on supply chain visibility. They track cargo movement and shipping milestones. These tools are useful for logistics teams but may not provide detailed maritime threat analysis or AI playbooks.

Security-focused maritime tools monitor piracy zones, sanctions, and suspicious vessel behavior. These systems are important for high-risk trade routes, but they may not include full operational dashboards, role-based actions, report generation, and integrated AI explanations.

The **Global AI Trade Intelligence Platform** combines ideas from these different categories. It provides vessel tracking, risk analytics, route intelligence, cargo awareness, alerts, reports, role-based security, scenario simulation, and production readiness checks in one project.

## 2.2 Existing System

In traditional maritime operations, information is often collected from separate sources such as AIS websites, weather reports, port updates, manual spreadsheets, email alerts, and logistics systems. This creates several limitations:

- Data is spread across multiple platforms.
- Users need to manually compare ship position, route, weather, cargo, and threat information.
- Risk decisions may depend too much on human judgment.
- Reports can take more time to prepare.
- Notifications may become noisy and difficult to prioritize.
- Access control may not be clearly separated by responsibility.
- Demo systems often fail when live APIs are unavailable.

Many existing systems also lack explainable AI. They may show a risk score, but they do not always explain the reason behind that score. Without explanation, users may not trust the recommendation. Similarly, many dashboards are visually impressive but do not provide strong action guidance.

## 2.3 Proposed System

The proposed system is an AI-powered maritime command platform that integrates vessel tracking, route monitoring, risk scoring, threat alerts, cargo intelligence, scenario simulation, reports, and role-based workflows.

The proposed system improves existing approaches in the following ways:

- It provides a unified dashboard instead of separate tools.
- It uses AISStream data for real vessel positions when configured.
- It projects vessel movement visually between API messages for smoother maps.
- It provides AI risk scoring with explainable drivers.
- It classifies threats into meaningful maritime categories.
- It generates defensive playbooks and action recommendations.
- It supports Admin, Operator, and Public access levels.
- It provides notification digest and smart operations inbox.
- It includes production mode controls for safer deployment.
- It supports report generation and data export.

The system is not only a tracking application. It is a decision-support platform. It helps users answer important questions such as:

- Which route is risky right now?
- Which vessel is exposed to a threat?
- What cargo may be affected?
- What will happen if no action is taken?
- Which action should be performed first?
- Is the system ready for production?
- Is real AIS data working?
- Are notifications and data quality healthy?

## 2.4 Methodology

The project was developed using an iterative and incremental methodology. Features were added step by step, tested, optimized, and improved. The system started as a trade intelligence dashboard and was later upgraded with real-time AIS support, stronger AI risk intelligence, role-based login, settings and notifications, command copilot, scenario simulation, mobile optimization, and production hardening.

The methodology includes the following stages:

### I. Requirement Collection

The first stage identified the need for a maritime platform that can monitor ships, show route risks, support AI decisions, and remain easy to use. Important requirements included maps, vessel movement, cargo details, risk alerts, reports, role-based login, settings, notifications, and real API support.

### II. System Planning

The project was divided into frontend, backend, database, AI risk engine, AIS integration, reports, security, and testing modules. This modular design made development easier and allowed features to be improved independently.

### III. Backend Development

FastAPI was used to create API endpoints for analytics, vessels, risk assessments, alerts, operations, settings, reports, role authentication, AI actions, and production readiness. SQLAlchemy was used for database operations.

### IV. Frontend Development

Streamlit was used to create dashboards, maps, charts, forms, tabs, role screens, notifications, settings, and command interfaces. The frontend communicates with the backend through HTTP requests.

### V. AI and Risk Development

The AI layer was designed using explainable rule-based scoring and ML-assisted risk modeling. The system analyzes risk drivers such as route severity, active alerts, vessel conditions, cargo exposure, signal freshness, operational readiness, and scenario impact.

### VI. Real-Time Data Integration

AISStream integration was added to receive real vessel positions. The backend caches vessel data and provides it to the frontend. If real data is unavailable, the system uses fallback demo vessels so the application continues working.

### VII. Testing and Optimization

The system was tested using pytest, frontend import checks, backend analytics tests, risk engine tests, database tests, and report tests. Refresh behavior was optimized to reduce unnecessary reloads and improve smoothness on mobile devices.

## Key Functionalities

### I. Dashboard

- Shows high-level mission metrics.
- Displays route and vessel summary.
- Includes live command map layers.
- Highlights alerts and operational pressure.

### II. Fleet and Operations

- Displays vessel positions and movement.
- Shows route readiness and cargo exposure.
- Helps operators monitor fleet condition.
- Provides map-based situational awareness.

### III. AI Risk Brain

- Classifies maritime risks into major threat categories.
- Provides risk level, prediction, caution window, and defensive action.
- Supports playbooks for natural hazards, hijack, war, port, cyber, cargo, and fuel shock events.

### IV. Threat Alerts

- Allows alert creation, filtering, and investigation.
- Supports severity and type analysis.
- Provides CSV export and workflow status.

### V. Scenario Lab

- Simulates storm, piracy, port shutdown, cyber disruption, fuel shock, and cargo theft scenarios.
- Shows affected routes, vessels, cargo, readiness score, and recommended response.

### VI. Voyage Control Tower

- Combines vessel anomalies, route modes, alert digest, approval queue, and intervention timeline.
- Helps commanders choose safer, faster, or lower-cost route decisions.

### VII. Command Copilot

- Answers project-topic questions using live platform data.
- Helps with safest route planning.
- Provides incident replay, ETA scoring, alert escalation, access preview, data quality, and deployment readiness guidance.

### VIII. Notifications and Settings

- Provides notification digest.
- Allows quick actions such as investigate, escalate, resolve, acknowledge, and watch.
- Includes runtime AIS settings, production mode, data cleanup, and system checks.

### IX. Reports

- Generates smart executive, risk, fleet, and security reports.
- Supports PDF export.
- Maintains report history.
- Provides route CSV export.

### X. Security and Roles

- Admin controls sensitive settings and user management.
- Operator handles operational workflows.
- Public receives limited read-only access.
- Login state is persisted to avoid unnecessary logout after refresh.

## Model Pipeline

The AI model and risk intelligence flow can be described as follows:

1. Collect route, vessel, cargo, alert, incident, and AIS data.
2. Clean and normalize data for analysis.
3. Identify risk drivers such as severity, speed, destination, alert count, cargo type, signal age, and route zone.
4. Apply rule-based scoring and ML-assisted prediction.
5. Classify risk into low, medium, high, or critical bands.
6. Generate explanations and recommended actions.
7. Show results in dashboards and maps.
8. Store important actions and reports in the database.
9. Notify users through digest and workflow queues.
10. Allow verified roles to approve, escalate, or complete actions.

---

# Chapter - 3

## System Analysis

System analysis is the process of understanding user needs, project goals, system requirements, data flow, technology selection, and implementation constraints. For this project, analysis was important because the platform includes many connected modules such as maps, AIS data, risk intelligence, notifications, roles, reports, and settings.

## 3.1 Project Planning

The project was planned as a full-stack AI command platform. The main challenge was to make the application useful, visually clear, role-aware, and smooth even when real-time data is involved.

### Requirement Gathering

The following user requirements were identified:

- The system should have a modern dashboard.
- Ships should be visible on maps.
- Ships should show cargo such as petrol, gold, containers, or medicine.
- Real API support should be added for live vessel data.
- Maps should show moving ships instead of static points.
- AI should detect risks and provide solutions.
- Risk categories should include natural problems, hijack, war, piracy, cyber, port, cargo, and fuel issues.
- The login page should be clean and role-based.
- Admin, Operator, and Public roles should have different permissions.
- Settings and notifications should be available through icons.
- The project should run smoothly on mobile.
- Unwanted sections should be removed or combined.
- The platform should be ready for GitHub with `.gitignore`.
- A final project report should be created in academic format.

### Scope Definition

The project scope was defined around a practical maritime intelligence platform. It includes both demonstration capabilities and production-oriented structure. The project supports real AIS integration but also includes fallback data so that the system remains usable without a constant live feed.

### Stakeholder Identification

The possible stakeholders of this system are:

- Shipping company administrators.
- Fleet operators.
- Maritime analysts.
- Port operations teams.
- Cargo owners.
- Insurance and risk teams.
- Public viewers or guests.
- Academic evaluators.

### Resource Allocation

The project uses open-source technologies and local development resources.

### Human Resources

- Student developer for frontend, backend, database, and AI logic.
- Guide or mentor for academic direction.
- Test users for usability feedback.

### Technical Resources

- Windows development environment.
- Python virtual environment.
- Browser for Streamlit application.
- SQLite runtime database.
- Optional AISStream API key.
- GitHub repository for version control.

### Technology Stack Selection

Streamlit was selected because it allows quick development of interactive dashboards using Python. FastAPI was selected because it is fast, modern, and suitable for API-based backend development. SQLite was selected for local development and PostgreSQL support was planned for production scalability. scikit-learn and rule-based logic were used for risk intelligence. Plotly and PyDeck were selected for charts and maps.

## 3.2 Project Scheduling

The project can be divided into the following development phases:

### 1. Inception Phase

- Identify project idea and domain.
- Decide maritime trade intelligence as the topic.
- List main features such as maps, AI, alerts, reports, and roles.
- Select technology stack.

### 2. Elaboration Phase

- Design backend APIs.
- Plan database tables.
- Design frontend navigation.
- Identify risk categories and AI logic.
- Plan real AIS integration.

### 3. Construction Phase

Module 1 - Dashboard and analytics.  
Module 2 - Fleet tracking and vessel map.  
Module 3 - AI risk scoring and route assessments.  
Module 4 - Threat alerts and notification workflows.  
Module 5 - Real AIS integration and motion projection.  
Module 6 - Role-based login system.  
Module 7 - Reports and PDF export.  
Module 8 - Scenario Lab and Command Center.  
Module 9 - Settings, production controls, and data cleanup.  
Module 10 - Testing and optimization.

### 4. Transition Phase

- Test backend endpoints.
- Test frontend startup.
- Verify role login.
- Verify AIS fallback.
- Verify reports.
- Optimize refresh behavior.
- Prepare GitHub ignore rules.

### 5. Maintenance Phase

- Add future data providers.
- Improve production authentication.
- Improve AI model with real historical datasets.
- Add deployment monitoring.
- Improve mobile user experience further.

## 3.3 Software Requirement Specification

### Functional Requirements

#### User Authentication

- The system must support Admin, Operator, and Public roles.
- Users must be able to sign in or create accounts.
- Guest or public access must remain restricted.
- Admin-only operations must require strict confirmation.

#### Dashboard

- The system must display mission metrics.
- The system must show fleet, route, alert, and risk summaries.
- The system must provide command-level map visualization.

#### Fleet Tracking

- The system must display vessel positions on a map.
- The system must show vessel name, cargo, speed, heading, and status.
- The system must use real AIS data when configured.
- The system must use fallback data if the API is unavailable.

#### AI Risk Assessment

- The system must calculate risk scores for routes and incidents.
- The system must show top risk drivers.
- The system must provide confidence and recommended actions.
- The system must categorize risks into meaningful threat groups.

#### Threat Alerts

- The system must create, filter, and manage alerts.
- The system must support severity and alert type analysis.
- The system must allow investigation, escalation, resolution, and watch actions.

#### Scenario Simulation

- The system must simulate maritime crisis scenarios.
- The system must show affected routes, vessels, cargo, and readiness.
- The system must recommend response plans.

#### Reports

- The system must generate report summaries.
- The system must support PDF export.
- The system must keep report history.

#### Settings

- The system must allow runtime AIS and cache tuning.
- The system must show provider readiness.
- The system must expose production mode controls.
- The system must support Admin data maintenance.

### Non-Functional Requirements

#### Security

- Sensitive operations must be role-restricted.
- API keys must not be exposed to the browser.
- Production mode must block unsafe demo behavior.
- Admin actions must be audited.

#### Performance

- The frontend must avoid unnecessary refresh loops.
- Dashboard updates should be controlled by refresh interval.
- Map movement should be smooth but not overloaded.
- The system should run acceptably on desktop and mobile browsers.

#### Reliability

- The backend should provide fallback data when live AIS is unavailable.
- System health and reliability checks should be visible.
- Database operations should be predictable and testable.

#### Usability

- Navigation should be clean and not overcrowded.
- Important sections should remain separated.
- Settings and notifications should be accessible through icons.
- Public users should not see admin-level controls.

#### Maintainability

- Frontend, backend, database, and tests should remain modular.
- APIs should have clear endpoint responsibilities.
- Configuration should be handled through environment variables.
- `.gitignore` should prevent secrets and runtime files from being committed.

#### Scalability

- SQLite is suitable for local demo.
- PostgreSQL support enables future production deployment.
- Alembic migrations provide safer database evolution.
- Additional external data providers can be added later.

## Hardware Requirements

### Processor

Minimum: Dual-core processor.  
Recommended: Quad-core processor or higher.

### Memory

Minimum: 4 GB RAM.  
Recommended: 8 GB RAM or higher for smoother dashboard use.

### Storage

Minimum: 2 GB free storage.  
Recommended: 5 GB or more for reports, runtime database, logs, and cached models.

### Network

Internet connection is required for real AIS data and external API providers. The application can still run in fallback demo mode without continuous internet.

## Software Requirements

### Operating System

- Windows 10 or Windows 11.
- Linux or macOS can also run the project with suitable command adjustments.

### Programming Language

- Python 3.11 or newer is recommended.

### Frontend

- Streamlit.
- Plotly.
- PyDeck.
- Requests.

### Backend

- FastAPI.
- Uvicorn.
- SQLAlchemy.
- python-dotenv.
- websockets.

### Database

- SQLite for local runtime.
- PostgreSQL support for production.
- Alembic for migrations.

### AI Libraries

- NumPy.
- Pandas.
- scikit-learn.
- joblib.

### Reporting

- ReportLab for PDF generation.

### Testing

- pytest.

## 3.4 Software Engineering Paradigm Applied

The project follows an iterative and incremental development model with agile influence.

### Iterative Approach

The project was improved repeatedly. Features such as map movement, AI Risk Brain, role login, notifications, settings, and refresh optimization were added and improved through multiple iterations.

### Incremental Development

The system was built module by module. Each module added a meaningful capability, such as backend APIs, frontend dashboards, reports, role access, AIS data, or AI prediction.

### Agile Principles

The project followed user feedback. For example, when the fleet map looked similar to other maps, it was redesigned. When login roles looked messy, they were simplified. When the app kept refreshing, refresh logic was optimized. This feedback-based improvement process follows agile principles.

---

# Chapter - 4

## System Design

System design explains how the project is structured and how each part communicates with the others. The **Global AI Trade Intelligence Platform** is designed as a modular full-stack application.

## 4.1 System Architecture

The system architecture contains the following layers:

### 1. User Interface Layer

The user interface is built with Streamlit. It displays dashboards, maps, charts, buttons, forms, tabs, login pages, settings panels, notifications, and reports. The UI communicates with the backend through API requests.

### 2. Backend API Layer

The backend is built with FastAPI. It provides endpoints for analytics, routes, vessels, AIS data, risk assessments, notifications, reports, login, settings, security, operations, and AI decisions.

### 3. Database Layer

The database stores routes, vessels, alerts, risk logs, reports, cargo manifests, incidents, AI actions, user accounts, workflow data, and audit records. SQLite is used for local runtime and PostgreSQL can be configured for production.

### 4. AI and Risk Layer

This layer analyzes route and vessel data to generate risk scores, threat categories, predictions, route guidance, and defensive playbooks. It combines deterministic business rules with ML-assisted scoring.

### 5. Real-Time Data Layer

The AIS client connects to AISStream when configured. It receives live vessel data, normalizes it, caches it, and provides display-ready vessel positions to frontend maps.

### 6. Security Layer

Security includes role-based permissions, login sessions, production mode controls, provider status checks, admin confirmations, audit summaries, and restricted sensitive endpoints.

### 7. Reporting Layer

The reporting layer generates intelligence summaries, PDF reports, route exports, and report-change analysis.

## System Architecture Flow

1. User opens the Streamlit frontend.
2. User logs in as Admin, Operator, or Public.
3. Frontend requests data from FastAPI backend.
4. Backend reads database records and live AIS cache.
5. AI risk engine analyzes route, vessel, alert, incident, and cargo data.
6. Backend returns structured JSON data to frontend.
7. Frontend displays maps, charts, metrics, alerts, and recommendations.
8. Verified users can approve, escalate, resolve, or complete actions.
9. Reports and audit records are saved to the database.

## Module Description

### Login Module

The login module controls access to the platform. It provides a clean role selection experience and supports Admin, Operator, and Public access. Admin access is strict and connected to sensitive operations. Operator access supports operational work. Public access is limited and safe.

### Dashboard Module

The dashboard module provides a high-level mission view. It shows route status, active alerts, risk pressure, fleet condition, and command map layers. It is designed for quick understanding of the overall system.

### Fleet Module

The fleet module displays vessel information. Ships can be shown with location, speed, heading, cargo, and destination. Real AIS data is used when available. Motion projection is used so ships appear to move between API updates.

### Operations Module

The operations module focuses on route readiness, bottlenecks, cargo exposure, next actions, and mission brief. It helps operators decide which operational problem should be solved first.

### AI Risk Module

The AI risk module calculates scores and classifications. It identifies risk drivers and explains the reason behind risk levels. It provides recommendations so users can act, not only observe.

### Threat Alert Module

The alert module manages active threats. Alerts can be filtered, investigated, escalated, resolved, and exported. Charts show alert distribution by severity and type.

### Scenario Lab Module

The scenario lab works like a digital twin. It simulates crisis events such as storms, piracy, port shutdowns, cyber disruption, fuel shock, and cargo theft. It predicts impact and suggests response plans.

### Voyage Control Tower Module

The voyage control tower acts as an autonomous command operating system. It combines route modes, vessel anomalies, alert digest, approval queue, reliability signals, and action timeline.

### Notification Module

The notification module reduces noise by ranking important items. It provides actions such as investigate, escalate, resolve, acknowledge, and watch.

### Settings Module

The settings module manages runtime configuration, AIS region tuning, provider status, production mode, security hardening, data cleanup, and database operations.

### Report Module

The report module creates smart project reports, intelligence reports, PDF exports, and historical summaries.

## Data Flow Diagram Description

### Level 0

User interacts with the system through the frontend. The frontend sends requests to the backend. The backend processes data from the database, AIS client, and AI risk engine. The response is displayed to the user.

### Level 1

The system can be divided into the following processes:

- Authentication process.
- Vessel data collection process.
- Route and cargo data process.
- Risk analysis process.
- Notification workflow process.
- Report generation process.
- Settings and production control process.

### Level 2

For AI risk analysis:

1. Input route and vessel data.
2. Add alert and incident context.
3. Add cargo sensitivity.
4. Add AIS freshness and movement details.
5. Calculate risk score.
6. Identify risk category.
7. Generate recommended action.
8. Save or display result.

## ER Diagram Description

The database design can be described using the following main entities:

- User: Stores account information, role, provider, and account status.
- Route: Stores origin, destination, region, risk level, and route status.
- Vessel: Stores vessel name, MMSI/IMO when available, cargo, speed, heading, and status.
- Alert: Stores threat type, severity, description, route or vessel relation, and workflow status.
- RiskLog: Stores historical risk records for forecasting.
- AIAction: Stores recommended AI actions and lifecycle status.
- Incident: Stores operational events and crisis records.
- CargoManifest: Stores cargo details linked to vessels.
- Report: Stores generated report metadata and file references.
- Notification: Stores digest items and operational action prompts.
- AuditEvent: Stores important admin/operator/security actions.

## 4.2 Modularization Details

### 1. Data Handling Module

This module handles database connection, data models, query operations, runtime database copying, and optional PostgreSQL configuration.

### 2. AIS Handling Module

This module connects to AISStream, receives vessel messages, converts them into application format, stores cached positions, calculates display projection, and supports fallback data.

### 3. Risk Analysis Module

This module calculates route and incident risk. It uses route condition, alerts, cargo, vessel condition, threat category, and operational readiness.

### 4. Frontend UI Module

This module contains Streamlit views for dashboard, fleet operations, risk alerts, command center, settings, notifications, and reports.

### 5. Authentication Module

This module controls login, role metadata, public access, account creation, social login preview, provider readiness, and role permissions.

### 6. Reporting Module

This module creates PDF reports, smart briefs, report history, route CSV export, and intelligence summaries.

### 7. Testing Module

This module contains automated tests for backend analytics, database connection, frontend import, reports, and risk engine.

## 4.3 Algorithms

### Rule-Based Risk Scoring

The rule-based engine assigns risk weight based on route status, alert severity, cargo sensitivity, incident count, AIS freshness, operational readiness, and threat type. It is explainable because the system can show top drivers.

### Machine Learning Assisted Risk Scoring

The ML-assisted risk model uses historical and seeded risk patterns to support route-level assessment. The model is lazy-loaded and persisted using joblib so it does not retrain unnecessarily.

### Threat Classification

Threats are classified into categories:

- Natural Hazard.
- Hijack or Piracy.
- War or Geopolitical.
- Port or Infrastructure.
- Cyber or AIS Integrity.
- Cargo Crime.
- Market or Fuel Shock.

### Route Recommendation Logic

The route recommendation logic compares routes by safety, delay, cost, cargo sensitivity, and operational conditions. It recommends the safest route when safety is the priority and can also compare fastest or lowest-cost options.

### Notification Ranking

The notification digest ranks items by severity, urgency, affected cargo, stale data, unresolved workflow status, and operational impact.

### AIS Motion Projection

AIS data may not update every second. To make maps feel real-time, the backend keeps the true API position and calculates display position using heading, speed, signal age, and a controlled motion multiplier. This makes movement visible while preserving the original API position separately.

---

# Chapter - 5

## Results

The completed system provides a working AI-oriented maritime command platform. The application can be started locally using the demo runner and accessed through a browser. The backend serves APIs and the frontend displays the interactive command interface.

## 5.1 Main Output Results

### AI-Based Maritime Risk Intelligence

The system successfully generates route-level and incident-level risk intelligence. It classifies threats, calculates severity, identifies drivers, and recommends actions. This makes the platform more advanced than a normal map dashboard.

### Real-Time Vessel Map

The fleet and dashboard maps display vessel positions using AISStream when configured. If the provider is unavailable, fallback vessels are shown. The map uses motion projection so users can see ships moving instead of static dots.

### Role-Based Login

The login system supports Admin, Operator, and Public roles. Each role receives different access. Admin users can access sensitive controls, operators can manage operations, and public users receive limited viewing access.

### Notifications

The notification module shows important items and supports quick actions. This helps users focus on important tasks instead of reading all alerts manually.

### Scenario Simulation

The scenario lab simulates maritime problems and returns affected routes, exposed vessels, cargo risk, response plans, and projected readiness.

### Reports

The reporting system creates smart reports and PDF outputs. It can include priority routes, high-severity alerts, and recommendations.

### System Reliability

The platform includes health, data quality, AIS reliability, deployment readiness, production mode, and setup checklist screens. These make the project more complete and practical.

## 5.2 Operational Rules

### 1. Valid User Authentication

Only authenticated users can access role-based features. Public users are limited.

### 2. Admin Confirmation Required

Sensitive actions such as production mode control, data cleanup, backup, and user management require Admin-level access and confirmation.

### 3. AIS Data Safety

The real AIS API key is used only by the backend and is not exposed to the frontend browser.

### 4. Fallback Rule

If the AIS provider is unavailable, the system falls back to local demo data so the platform continues working.

### 5. Cargo Verification Rule

Live AIS cargo is labeled as inferred unless a verified manifest is attached by an operator.

### 6. Risk Explanation Rule

Every important AI risk output should include a reason or top driver so users can understand the decision.

### 7. Notification Action Rule

Notifications should support clear next actions such as investigate, escalate, resolve, watch, or acknowledge.

### 8. Role Permission Rule

Public users cannot execute sensitive operational actions. Operators can work on operations. Admins control security and system settings.

### 9. Production Safety Rule

Production mode should disable unsafe demo behavior and require stronger provider configuration.

### 10. Testing Rule

Important backend and frontend modules should be covered by automated tests.

## 5.3 Sample Output Descriptions

### Dashboard Output

The dashboard displays the overall condition of the maritime network. It shows active routes, vessel count, alert severity, risk pressure, command map, and executive summary.

### Fleet Output

The fleet section displays live or simulated ships. Each ship can show name, cargo, destination, movement, speed, and status.

### Risk Output

The risk section displays categories such as natural hazard, hijack, war, port, cyber, cargo, and fuel shock. It gives level, prediction, and action.

### Report Output

Reports summarize important route risks, alerts, operational recommendations, and system status.

---

# Chapter - 6

## Implementation

Implementation is the stage where the planned system design is converted into working software. The **Global AI Trade Intelligence Platform** is implemented as a Python full-stack application.

## Programming Language

Python is used for both frontend and backend development. Python was selected because it has strong support for web development, data analysis, artificial intelligence, visualization, and automation.

## Libraries and Frameworks

### Streamlit

Streamlit is used for building the frontend. It allows quick creation of dashboards, forms, charts, maps, buttons, session state, and role-based screens.

### FastAPI

FastAPI is used for backend API development. It provides fast request handling, clear route definitions, JSON responses, and easy integration with Python logic.

### Uvicorn

Uvicorn runs the FastAPI backend server.

### SQLAlchemy

SQLAlchemy is used for database models and queries.

### Alembic

Alembic is included for database migration support.

### Pandas and NumPy

Pandas and NumPy are used for data processing, analytics, and tabular transformations.

### scikit-learn

scikit-learn is used for machine learning support in the risk model.

### joblib

joblib is used to persist trained ML model artifacts.

### Plotly

Plotly is used for charts and interactive visual analytics.

### PyDeck

PyDeck is used for map-based visualization in Streamlit.

### ReportLab

ReportLab is used for PDF report generation.

### websockets

The websockets library is used for AISStream live data connection.

### pytest

pytest is used for automated testing.

## Backend Implementation

The backend is implemented in `backend/main.py` and related backend modules. It provides endpoints for analytics, AI, vessels, notifications, operations, settings, reports, security, and data management.

Important backend responsibilities include:

- Serving dashboard analytics.
- Serving live AI feed.
- Managing route assessments.
- Managing vessel live data.
- Managing alerts and workflows.
- Generating reports.
- Returning notification digest.
- Handling login and role metadata.
- Managing production mode and provider readiness.
- Returning data quality and reliability checks.
- Processing AI actions and incident playbooks.

## Frontend Implementation

The frontend is implemented in `frontend/app.py`. It uses Streamlit to create the user interface.

Important frontend responsibilities include:

- Showing the login page.
- Managing session state.
- Displaying navigation based on role.
- Fetching backend API data.
- Rendering dashboards, metrics, maps, charts, tables, and forms.
- Showing notification and settings icons.
- Supporting mobile-friendly command mode.
- Preventing excessive refresh behavior.

## Database Implementation

The database is initialized through the database module. SQLite is used for local runtime because it is simple and portable. The project copies the seeded database to a runtime database for writable local runs. PostgreSQL support is available through environment configuration for production use.

Main database data includes:

- Routes.
- Vessels.
- Alerts.
- Risk logs.
- Incidents.
- AI actions.
- Reports.
- Cargo manifests.
- Users.
- Audit events.

## AI Risk Implementation

The AI risk system is one of the most important parts of the project. It combines deterministic rules with ML-assisted logic to produce explainable risk outputs.

The AI risk system provides:

- Risk score.
- Risk band.
- Confidence.
- Top drivers.
- Recommended response.
- Category classification.
- Defensive playbook.
- No-action projection.
- Controlled response projection.

## AISStream Implementation

The AIS client connects to AISStream when the required provider and API key are configured. It listens for live vessel messages through a websocket connection. The backend then normalizes vessel information and exposes it to the frontend.

The AIS system includes:

- Real vessel position.
- Display projected position.
- Heading and speed support.
- Motion trail.
- Signal age.
- Provider status.
- Reliability checks.
- Fallback demo data.

The platform clearly separates true API position from display-projected map position. This is important because the system should make ships visually move without hiding the original AIS signal.

## Role System Implementation

The role system contains three important roles:

### Admin

Admin users have full platform control. They can manage users, production mode, settings, data cleanup, backups, and security checks.

### Operator

Operators can investigate alerts, manage operations, handle workflows, approve operational steps, and work with fleet intelligence.

### Public

Public users receive limited access. They can view safe information but cannot perform sensitive actions.

## Notification Implementation

Notifications are generated from alerts, incidents, AI actions, data quality issues, cargo exposure, production readiness, and operations inbox items. The notification digest ranks problems based on importance and gives direct actions.

## Settings Implementation

Settings are implemented as a practical control area. Instead of showing too many settings in navigation, settings are accessed through an icon. This keeps the app cleaner.

Settings include:

- Runtime AIS configuration.
- Region presets.
- Production mode.
- Provider readiness.
- Data cleanup.
- Database operations.
- Deployment hardening.
- Security audit.

## Report Implementation

Reports are generated from live platform data. The system can create executive, security, fleet, risk, and smart reports. PDF export is supported through ReportLab.

## Security Implementation

Security implementation includes:

- Role-based access.
- Admin confirmation for sensitive actions.
- Login session persistence.
- Provider readiness checks.
- Production mode control.
- API key protection.
- Audit summary.
- Public read-only policy.

## Working Process

### Step 1 - User Opens Application

The user starts the frontend and opens the Streamlit URL.

### Step 2 - User Selects Access Type

The login page asks whether the user wants Admin, Operator, or Public access.

### Step 3 - Frontend Loads Role Permissions

The frontend requests role metadata and provider status from the backend.

### Step 4 - Backend Serves Data

The backend serves analytics, route, vessel, alert, report, and AI data.

### Step 5 - AIS Data Is Processed

If AISStream is connected, live vessel data is cached and transformed. If not, fallback vessels are used.

### Step 6 - AI Risk Is Calculated

Routes, vessels, cargo, alerts, and incidents are analyzed by the AI risk engine.

### Step 7 - UI Displays Intelligence

The user sees maps, charts, risk levels, notifications, and recommended actions.

### Step 8 - Verified Users Take Action

Operators and Admins can investigate, escalate, approve, resolve, or complete actions depending on their role.

### Step 9 - Reports Are Generated

The report module creates summaries and PDF reports.

### Step 10 - System Is Monitored

Reliability, data quality, deployment readiness, and provider status are monitored through settings and system panels.

## Future Implementation Enhancements

- Connect real OAuth providers for Google, Facebook, Apple, and enterprise SSO.
- Add real WebAuthn fingerprint authentication behind HTTPS.
- Add verified weather, port congestion, piracy, and geopolitical APIs.
- Train risk model on real historical vessel, route, and incident data.
- Add container-level tracking.
- Add mobile native app.
- Add push notifications through email, SMS, or app notification services.
- Add cloud deployment with CI/CD.

---

# Chapter - 7

## Software Testing

Testing is required to verify that the system works correctly and remains stable after updates. The project includes automated tests and manual testing.

## 7.1 Types of Testing

### Functional Testing

Functional testing checks whether each feature works as expected.

Examples:

- Login works for Admin, Operator, and Public roles.
- Dashboard loads analytics.
- Fleet map displays vessels.
- Reports are generated.
- Risk assessments return valid scores.

### Integration Testing

Integration testing checks whether modules work together.

Examples:

- Frontend calls backend APIs successfully.
- Backend reads from the database.
- AIS data flows from backend to frontend maps.
- Notification actions update workflow state.

### System Testing

System testing checks the entire application as one complete product.

Examples:

- Start backend and frontend.
- Login as operator.
- View dashboard, fleet, risk, and reports.
- Generate a report.
- Verify role restrictions.

### Security Testing

Security testing checks role access and sensitive controls.

Examples:

- Public users cannot access Admin-only actions.
- Admin confirmation is required for sensitive operations.
- API key is not shown in frontend.
- Production mode blocks unsafe demo actions.

### Performance Testing

Performance testing checks smoothness and load behavior.

Examples:

- Dashboard refresh interval is controlled.
- Frontend does not continuously refresh all sections.
- Maps remain usable on mobile.
- Backend API responses remain fast for demo data.

### Compatibility Testing

Compatibility testing checks whether the project works in different browsers and screen sizes.

Examples:

- Desktop browser layout.
- Mobile browser layout.
- Streamlit UI responsiveness.

### Regression Testing

Regression testing checks whether new updates broke old features.

Examples:

- After adding AIS motion, existing dashboard still loads.
- After changing roles, reports still work.
- After optimizing refresh, maps still update.

### Usability Testing

Usability testing checks whether users can understand and operate the system.

Examples:

- Important sections are separated.
- Unwanted pages are removed or combined.
- Settings and notifications are easy to find.
- Login page is clean and clear.

## 7.2 White-Box Testing

White-box testing focuses on internal logic. It is applied to backend functions, risk scoring, data processing, and report generation.

Applicable areas:

- Risk engine scoring.
- Route assessment generation.
- Database connection.
- Report generation.
- Backend analytics functions.

## 7.3 Black-Box Testing

Black-box testing focuses on output without checking internal code.

Applicable areas:

- Login form.
- Dashboard API response.
- Fleet map display.
- Alert workflows.
- PDF export.
- Scenario simulation output.

## 7.4 Test Strategy and Approach

The testing strategy includes automated and manual tests.

Test objectives:

- Verify backend endpoints.
- Verify frontend import and startup.
- Verify database connection.
- Verify risk model output.
- Verify report generation.
- Verify role-based behavior.
- Verify fallback behavior when AIS data is unavailable.

## Features to Be Tested

- Authentication and role access.
- Dashboard analytics.
- Fleet vessel data.
- AIS fallback.
- Risk assessment.
- Threat alerts.
- Scenario simulation.
- Notifications.
- Settings.
- Reports.
- Database operations.
- Production mode.

## Test Results

The automated test suite includes tests for backend analytics, database connection, frontend import, report generation, and risk engine. The latest test run passed successfully with all tests passing.

## 7.5 Test Cases

| Test Case ID | Test Case Name | Input | Expected Output | Status |
| --- | --- | --- | --- | --- |
| TC-01 | Backend Health Check | Open health endpoint | Backend returns service status | Pass |
| TC-02 | Frontend Import | Import frontend app | No import error | Pass |
| TC-03 | Database Connection | Initialize DB session | Database connects successfully | Pass |
| TC-04 | Risk Engine | Route data | Risk score and drivers returned | Pass |
| TC-05 | Report Generation | Report request | PDF/report metadata generated | Pass |
| TC-06 | Admin Login | Admin credentials | Admin session created | Pass |
| TC-07 | Operator Login | Operator credentials | Operator session created | Pass |
| TC-08 | Public Access | Public/guest login | Read-only access granted | Pass |
| TC-09 | AIS Fallback | API unavailable | Demo vessels displayed | Pass |
| TC-10 | Notification Action | Escalate alert | Workflow status updated | Pass |
| TC-11 | Production Mode | Admin confirmation | Production control updated | Pass |
| TC-12 | Mobile Smoothness | Mobile viewport | UI remains usable | Pass |

---

# Chapter - 8

## Source Code Summary

The complete source code is organized into modules. The project should not include secrets, runtime databases, cache files, virtual environment files, or local reports in GitHub commits. A `.gitignore` file is included to protect unnecessary and sensitive files.

## Main Project Files

### `frontend/app.py`

This file contains the Streamlit frontend application. It includes login UI, page navigation, dashboards, maps, charts, forms, notifications, settings, command views, and report screens.

### `backend/main.py`

This file contains FastAPI backend routes and business logic for analytics, AI risk intelligence, operations, notifications, settings, roles, reports, production readiness, and data maintenance.

### `backend/aisstream_client.py`

This file handles AISStream integration, vessel normalization, display motion projection, motion trail, signal age, and fallback behavior.

### `database/`

This folder contains database initialization and model logic.

### `ml/`

This folder contains ML model artifacts such as the risk model.

### `tests/`

This folder contains automated test cases for backend analytics, database connection, frontend import, reports, and risk engine.

### `run_demo.ps1`

This script starts the backend and frontend locally for demo.

### `.env.example`

This file shows configuration variables without exposing real secrets.

### `.gitignore`

This file prevents committing virtual environments, caches, database runtime files, `.env`, logs, reports, and generated artifacts.

---

# Chapter - 9

## Screenshots of Project

Screenshots can be added in this chapter before final submission. Suggested screenshots are listed below.

## Screenshot 1 - Login Page

Show the clean role-based login page with Admin, Operator, and Public options.

## Screenshot 2 - Dashboard

Show the global mission dashboard with metrics, map, alerts, and command summary.

## Screenshot 3 - Fleet and Operations Map

Show ships moving on the map with cargo, destination, speed, and status.

## Screenshot 4 - AI Risk Brain

Show risk categories such as natural hazard, hijack, war, cyber, cargo crime, and fuel shock with AI recommendations.

## Screenshot 5 - Threat Alerts

Show active alerts, severity chart, and workflow actions.

## Screenshot 6 - Scenario Lab

Show a simulated crisis scenario and its impact on routes and vessels.

## Screenshot 7 - Voyage Control Tower

Show autonomous route mode recommendations and action timeline.

## Screenshot 8 - Notifications

Show notification digest and quick action buttons.

## Screenshot 9 - Settings

Show production mode, AIS provider readiness, data cleanup, and runtime settings.

## Screenshot 10 - Reports

Show generated report history or PDF export.

---

# Chapter - 10

## Conclusion and Future Enhancement

## Conclusion

The **Global AI Trade Intelligence Platform** is a complete AI-oriented maritime command and trade risk intelligence system. It combines vessel tracking, route monitoring, AIS integration, AI risk scoring, threat alerts, cargo intelligence, scenario simulation, command copilot, notifications, reports, role-based access, and production readiness controls into one platform.

The project solves the limitations of traditional maritime monitoring systems by going beyond simple tracking. It provides explainable risk decisions, defensive playbooks, safe route planning, operational recommendations, and role-aware workflows. The platform can work with real AIS data when an API key is configured and can also run with fallback data for local demonstration.

The system is useful for understanding how artificial intelligence can support maritime logistics and global trade safety. It also provides practical learning in full-stack development, database management, API design, real-time data handling, machine learning, security, testing, and user interface design.

The final system is suitable for academic demonstration and can be extended into a production-grade platform with verified data providers, real authentication providers, cloud deployment, and stronger AI models trained on real historical maritime data.

## Future Enhancements

### 1. Real OAuth and WebAuthn Authentication

The current local role system can be upgraded with real Google, Facebook, Apple, enterprise SSO, and WebAuthn fingerprint authentication. This requires HTTPS and a production identity provider.

### 2. Real Weather Provider

The platform can be connected to real maritime weather APIs to detect storms, wave height, wind speed, and cyclone zones.

### 3. Port Congestion API

Real port congestion data can improve route delay prediction and cargo planning.

### 4. Piracy and Security Feeds

The project can integrate maritime security feeds for piracy zones, sanctions, hijacking reports, and geopolitical incidents.

### 5. Advanced Machine Learning

The risk model can be trained with real historical route data, incident data, weather data, cargo data, and port delay records.

### 6. Deep Learning for Anomaly Detection

Deep learning can be used to detect abnormal vessel patterns such as sudden course changes, suspicious loitering, AIS spoofing, or unexpected speed drops.

### 7. Mobile Application

A dedicated mobile app can provide push notifications and offline emergency views.

### 8. Cloud Deployment

The project can be deployed using Docker, cloud database, HTTPS, CI/CD, monitoring, and secrets management.

### 9. Container-Level Cargo Tracking

Cargo visibility can be improved by tracking individual containers and sensitive goods.

### 10. Multi-Language Support

The platform can support multiple languages for international maritime teams.

### 11. Advanced Report Designer

Users can create custom report templates for executive, operator, security, insurance, or port authority use cases.

### 12. Real-Time Collaboration

Multiple users can collaborate in the same incident workspace with comments, assignments, and live status changes.

---

# Bibliography

## Books

1. Russell, S. and Norvig, P. - Artificial Intelligence: A Modern Approach.
2. Geron, A. - Hands-On Machine Learning with Scikit-Learn, Keras, and TensorFlow.
3. Grinberg, M. - Flask Web Development. Useful for general Python web concepts.
4. McKinney, W. - Python for Data Analysis.
5. Beazley, D. - Python Essential Reference.

## Documentation and Online Resources

1. Python Documentation - https://docs.python.org/
2. FastAPI Documentation - https://fastapi.tiangolo.com/
3. Streamlit Documentation - https://docs.streamlit.io/
4. SQLAlchemy Documentation - https://docs.sqlalchemy.org/
5. scikit-learn Documentation - https://scikit-learn.org/
6. Plotly Documentation - https://plotly.com/python/
7. PyDeck Documentation - https://deckgl.readthedocs.io/
8. ReportLab Documentation - https://www.reportlab.com/docs/
9. AISStream Documentation - https://aisstream.io/
10. GitHub Documentation - https://docs.github.com/

## Research and Reference Topics

1. Maritime risk prediction and route optimization.
2. AIS-based vessel tracking and anomaly detection.
3. AI-assisted logistics and supply chain risk management.
4. Cybersecurity in maritime operations.
5. Port congestion and global shipping disruption analysis.
6. Role-based access control in web applications.
7. Real-time dashboard design and operational intelligence.

---

## Appendix A - Suggested Page Distribution

The report can be formatted into approximately 35 to 50 pages in Word or PDF by using standard academic formatting:

- Title, certificate, declaration, acknowledgement, abstract, and contents: 5 to 7 pages.
- Chapter 1 Introduction: 5 to 6 pages.
- Chapter 2 Literature Survey: 5 to 6 pages.
- Chapter 3 System Analysis: 6 to 8 pages.
- Chapter 4 System Design: 6 to 8 pages.
- Chapter 5 Results: 3 to 4 pages.
- Chapter 6 Implementation: 6 to 8 pages.
- Chapter 7 Testing: 4 to 5 pages.
- Chapter 8 Source Code Summary: 2 to 3 pages.
- Chapter 9 Screenshots: 5 to 8 pages depending on images.
- Chapter 10 Conclusion and Future Enhancement: 2 to 3 pages.
- Bibliography: 1 to 2 pages.

## Appendix B - Project Run Commands

Backend:

```powershell
uvicorn backend.main:app --host 127.0.0.1 --port 8001
```

Frontend:

```powershell
streamlit run frontend/app.py --server.port 8502 --server.address 127.0.0.1
```

Demo runner:

```powershell
.\run_demo.ps1
```

Testing:

```powershell
python -m pytest
```

## Appendix C - Configuration Notes

The project uses `.env` for local configuration. API keys and secrets should never be committed to GitHub. The included `.gitignore` protects local secrets, runtime databases, cache files, virtual environments, logs, and generated reports.

Important configuration variables include:

- `AIS_PROVIDER`
- `AISSTREAM_API_KEY`
- `AISSTREAM_MAX_VESSELS`
- `AISSTREAM_MAP_MOTION_MULTIPLIER`
- `APP_MODE`
- `DATABASE_URL`
- `API_BASE`

For production, SSL verification should remain enabled and real identity providers should be connected.
