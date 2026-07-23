import time

from backend.main import (
    AlertWorkflowUpdate,
    AutopilotExecuteRequest,
    AuthLoginRequest,
    AuthRegisterRequest,
    AuthSocialRequest,
    AuthSessionValidateRequest,
    CaptainActionRequest,
    CargoManifestUpsert,
    CommandActionRequest,
    DataMaintenanceRequest,
    DemoResetRequest,
    InboxActionRequest,
    CopilotRequest,
    IncidentStatusUpdate,
    NotificationActionRequest,
    ProblemSolverRequest,
    RiskIntelligenceActionRequest,
    RuntimeSettingsUpdate,
    ScenarioRequest,
    act_on_notification,
    ask_copilot,
    execute_strategic_autopilot,
    execute_ai_captain_action,
    generate_smart_report,
    get_ai_route_assessments,
    get_ai_actions,
    get_ai_incident_playbook,
    get_ai_captain,
    get_ai_risk_intelligence,
    get_live_incident_predictions,
    get_analytics_overview,
    get_alert_workflows,
    get_auth_accounts,
    get_auth_provider_status,
    get_auth_roles,
    get_audit_log,
    get_ai_self_check,
    get_ais_reliability,
    get_production_mode,
    get_strategic_autopilot,
    get_cargo_manifests,
    get_cargo_custody,
    get_confidence_heatmap,
    get_data_quality,
    get_data_cleanup_summary,
    get_decision_timeline,
    get_delivery_plan,
    get_deployment_hardening,
    get_deployment_readiness,
    get_executive_brief,
    get_global_route_plan,
    get_incident_commander,
    get_incidents,
    get_mission_map_overlay,
    get_mission_pack,
    get_mission_control,
    get_notifications_digest,
    get_notification_intelligence,
    get_notifications,
    get_operations_intelligence,
    get_operations_intelligence_v2,
    get_operations_inbox,
    get_operations_timeline,
    get_port_congestion,
    get_production_upgrade_hub,
    get_replay_timeline,
    get_route_alternatives,
    get_route_optimizer,
    get_risk_forecast,
    get_role_command_view,
    get_runtime_settings,
    get_sea_lane_engine,
    get_system_reliability,
    get_vessel_intelligence,
    get_vessel_history,
    get_vessel_predictions,
    get_daily_brief,
    get_war_room,
    login_auth_account,
    plan_global_route,
    register_auth_account,
    reset_demo_state,
    run_command_action,
    run_ai_risk_intelligence_action,
    simulate_scenario,
    solve_domain_problem,
    social_auth_login,
    health,
    update_alert_workflow,
    update_incident_status,
    update_runtime_settings,
    upsert_cargo_manifest,
    validate_auth_session,
)
from database.connection import SessionLocal


def test_health_returns_service_details():
    db = SessionLocal()
    try:
        payload = health(db)
    finally:
        db.close()

    assert payload["status"] in {"healthy", "degraded"}
    assert "database" in payload
    assert "services" in payload


def test_analytics_overview_shape():
    db = SessionLocal()
    try:
        payload = get_analytics_overview(db)
    finally:
        db.close()

    assert "summary" in payload
    assert "top_routes" in payload
    assert "regional_risk" in payload
    assert isinstance(payload["top_routes"], list)


def test_forecast_contains_history_and_forecast_rows():
    db = SessionLocal()
    try:
        payload = get_risk_forecast(days=7, db=db)
    finally:
        db.close()

    assert "history" in payload
    assert "forecast" in payload
    assert "top_forecast" in payload


def test_operations_intelligence_contains_readiness_and_actions():
    db = SessionLocal()
    try:
        payload = get_operations_intelligence(db)
    finally:
        db.close()

    assert "readiness_score" in payload
    assert "next_actions" in payload
    assert "checklist" in payload


def test_operational_intelligence_v2_shapes():
    db = SessionLocal()
    try:
        intelligence = get_operations_intelligence_v2(db)
        actions = get_ai_actions(db=db)
        manifests = get_cargo_manifests(db=db)
        history = get_vessel_history(db=db)
        timeline = get_operations_timeline(db=db)
    finally:
        db.close()

    assert "summary" in intelligence
    assert "readiness_score" in intelligence
    assert isinstance(actions, list)
    assert isinstance(manifests, list)
    assert "rows" in history
    assert isinstance(timeline, list)


def test_productization_endpoints_shape(seeded_ids):
    db = SessionLocal()
    try:
        settings = get_runtime_settings()
        notifications = get_notifications(db=db)
        alternatives = get_route_alternatives(route_id=seeded_ids["route_id"], db=db)
        manifest = upsert_cargo_manifest(
            CargoManifestUpsert(
                vessel_identifier="test-vessel",
                vessel_name="Test Vessel",
                cargo="Test Cargo",
                cargo_class="Priority",
                cargo_tons=100,
                cargo_value="$1M",
                origin_port="Singapore",
                destination_port="Rotterdam",
            ),
            db=db,
        )
    finally:
        db.close()

    assert "available_regions" in settings
    assert isinstance(notifications, list)
    assert "alternatives" in alternatives
    assert alternatives["alternatives"]
    assert manifest["priority"] == "P2"


def test_scenario_simulation_returns_digital_twin_plan():
    db = SessionLocal()
    try:
        payload = simulate_scenario(
            ScenarioRequest(
                scenario_type="Piracy Swarm",
                severity="high",
                location="Gulf of Aden",
                duration_hours=18,
            ),
            db=db,
        )
    finally:
        db.close()

    assert payload["scenario"]["type"] == "Piracy Swarm"
    assert "readiness" in payload
    assert "impact_summary" in payload
    assert isinstance(payload["impacted_routes"], list)
    assert isinstance(payload["response_plan"], list)
    assert payload["response_plan"]


def test_ai_risk_intelligence_covers_incident_categories_and_actions():
    db = SessionLocal()
    try:
        intelligence = get_ai_risk_intelligence(db=db)
        playbook = get_ai_incident_playbook(incident_type="war between country", db=db)
        action = run_ai_risk_intelligence_action(
            RiskIntelligenceActionRequest(
                incident_type="Hijack / Piracy",
                target="Test route",
                owner="Tester",
                note="Test defensive playbook queue.",
                priority="P2",
            ),
            db=db,
        )
    finally:
        db.close()

    categories = {row["category"] for row in intelligence["categories"]}
    assert {"Natural Hazard", "Hijack / Piracy", "War / Geopolitical"} <= categories
    assert intelligence["summary"]["overall_priority"] in {"P1", "P2", "P3"}
    assert intelligence["forecast"]
    assert playbook["incident_type"] == "War / Geopolitical"
    assert playbook["immediate_steps"]
    assert action["status"] == "queued"
    assert action["record"]["source"] == "AI Risk Brain"


def test_ai_captain_final_command_layer_shapes():
    db = SessionLocal()
    try:
        captain = get_ai_captain(origin="Mumbai", destination="Rotterdam", db=db)
        predictions = get_live_incident_predictions(db=db)
        action = execute_ai_captain_action(
            CaptainActionRequest(
                order="queue_captain_order",
                target="Mumbai to Rotterdam",
                owner="Tester",
                note="Test captain order.",
                priority="P2",
                origin="Mumbai",
                destination="Rotterdam",
            ),
            db=db,
        )
    finally:
        db.close()

    assert captain["verdict"] in {"SAFE", "DELAY", "REROUTE", "ESCALATE", "STOP VOYAGE"}
    assert captain["global_route"]["recommended"]
    assert captain["incident_predictions"]
    assert captain["vessel_board"]
    assert captain["emergency_war_room"]["steps"]
    assert {"mission_score", "no_action_risk", "incident_likelihood"} <= set(captain["metrics"])
    assert predictions["predictions"]
    assert action["status"] == "queued"
    assert action["record"]["source"] == "AI Captain"


def test_command_upgrade_endpoints_shape():
    db = SessionLocal()
    try:
        roles = get_auth_roles()
        brief = get_executive_brief(db)
        predictions = get_vessel_predictions(db=db)
        replay = get_replay_timeline(db=db)
        quality = get_data_quality(db)
        deployment = get_deployment_readiness(db)
        copilot = ask_copilot(CopilotRequest(question="what should i do next", role="Admin"), db)
    finally:
        db.close()

    assert "roles" in roles
    assert roles["strict_mode"] is True
    assert "Admin Fingerprint" in roles["providers"]
    assert set(roles["roles"]) == {"Admin", "Operator", "Public"}
    assert any("fingerprint" in method for method in roles["roles"]["Admin"]["auth"]["required_methods"])
    assert "Google OAuth" in roles["roles"]["Public"]["auth"]["allowed_providers"]
    assert "commander_summary" in brief
    assert "predictions" in predictions
    assert "events" in replay
    assert quality["status"] in {"pass", "warn", "fail"}
    assert "checks" in deployment
    assert "answer" in copilot


def test_production_upgrade_hub_and_sea_lane_engine_shapes():
    db = SessionLocal()
    try:
        hub = get_production_upgrade_hub(db=db)
        delivery = get_delivery_plan(severity="critical", db=db)
        route = get_sea_lane_engine(
            origin="Mumbai",
            destination="Rotterdam",
            objective="safest",
            cargo_priority="P1",
            avoid="war,piracy,security,geopolitical",
        )
    finally:
        db.close()

    assert hub["modules"]
    assert hub["status"] in {"production-ready", "staging-ready", "integration-needed", "demo-fallback"}
    assert hub["external_data"]["total"] >= hub["external_data"]["connected"]
    assert delivery["channels"]
    assert "outbox" in delivery["recommended_sequence"]
    assert route["recommended"]
    assert route["controls"]
    assert route["recommended"]["route_controls"]
    assert route["cargo_priority"] == "P1"


def test_persistent_auth_provider_status_and_login_flows():
    db = SessionLocal()
    try:
        accounts = get_auth_accounts(db=db)
        provider_status = get_auth_provider_status()
        admin_login = login_auth_account(
            AuthLoginRequest(
                email="admin@demo.app",
                password="admin-demo",
                role="Admin",
                provider="Admin Fingerprint",
                biometric_ok=True,
                phrase="ADMIN ACCESS",
            ),
            db=db,
        )
        restored = validate_auth_session(AuthSessionValidateRequest(token=admin_login["session_token"]), db=db)
        unique_email = f"public-{int(time.time() * 1000)}@example.com"
        registered = register_auth_account(
            AuthRegisterRequest(
                email=unique_email,
                display_name="Test Public",
                password="public-secret",
                role="Public",
                provider="Email Magic Link",
            ),
            db=db,
        )
        social = social_auth_login(AuthSocialRequest(provider="Google OAuth", identity=f"public-{int(time.time() * 1000)}@example.com"), db=db)
    finally:
        db.close()

    assert accounts["accounts"]
    assert any(row["provider"] == "Google OAuth" for row in provider_status["providers"])
    assert admin_login["account"]["role"] == "Admin"
    assert restored["account"]["role"] == "Admin"
    assert registered["account"]["email"] == unique_email
    assert registered["account"]["role"] == "Public"
    assert social["account"]["role"] == "Public"


def test_notification_actions_mission_overlay_and_hardening_shapes():
    db = SessionLocal()
    try:
        triage = act_on_notification(
            NotificationActionRequest(
                target="Test Notification Target",
                action="investigate",
                owner="Tester",
                note="Test notification triage.",
                priority="P2",
            ),
            db=db,
        )
        overlay = get_mission_map_overlay(db=db)
        hardening = get_deployment_hardening(db=db)
        reliability = get_ais_reliability(db=db)
        cleanup = get_data_cleanup_summary(db=db)
        production = get_production_mode(db=db)
        inbox = get_operations_inbox(db=db)
        system = get_system_reliability(db=db)
    finally:
        db.close()

    assert triage["status"] == "queued"
    assert "summary" in overlay
    assert "routes" in overlay
    assert "vessels" in overlay
    assert "checks" in hardening
    assert "checks" in reliability
    assert "duplicate_manifests" in cleanup
    assert "inferred_live_manifests" in cleanup["summary"]
    assert "enforced_controls" in production
    assert "items" in inbox
    assert "checks" in system
    assert DataMaintenanceRequest(confirm="CLEAN DATA").compact_manifests is True
    assert InboxActionRequest(target="Test").target == "Test"


def test_strategic_autopilot_plan_and_execution_shapes():
    db = SessionLocal()
    try:
        autopilot = get_strategic_autopilot(db=db)
        intervention_id = autopilot["interventions"][0]["id"]
        executed = execute_strategic_autopilot(
            AutopilotExecuteRequest(
                intervention_id=intervention_id,
                owner="Tester",
                note="Test strategic autopilot execution.",
            ),
            db=db,
        )
    finally:
        db.close()

    assert autopilot["mode"]
    assert "risk_projection" in autopilot
    assert autopilot["trajectory"]
    assert autopilot["route_shield"]
    assert executed["status"] in {"queued", "incident_created"}
    assert executed["record"]


def test_audit_notifications_optimizer_and_explainability_shapes(seeded_ids):
    db = SessionLocal()
    try:
        assessments = get_ai_route_assessments(db)
        optimizer = get_route_optimizer(route_id=seeded_ids["route_id"], db=db)
        notification_intel = get_notification_intelligence(db=db)
        audit = get_audit_log(db=db)
    finally:
        db.close()

    assert assessments
    assert "model_trace" in assessments[0]
    assert "human_checklist" in assessments[0]
    assert {"safest", "fastest", "lowest_cost", "balanced"} <= set(optimizer["modes"])
    assert "pressure_score" in notification_intel
    assert "events" in audit


def test_runtime_smart_report_and_alert_workflow_shapes(seeded_ids):
    db = SessionLocal()
    try:
        settings = update_runtime_settings(RuntimeSettingsUpdate(max_vessels=12, stale_seconds=900))
        smart = generate_smart_report(brief_type="CEO brief", db=db)
        workflows = get_alert_workflows(db=db)
        workflow = update_alert_workflow(
            seeded_ids["alert_id"],
            AlertWorkflowUpdate(status="investigating", owner="Tester", note="Test workflow update."),
            db=db,
        )
    finally:
        db.close()

    assert "applied" in settings
    assert smart["report_id"]
    assert workflows
    assert workflow["workflow_status"] == "investigating"


def test_copilot_global_route_planner_handles_world_ports():
    plan = plan_global_route("Mumbai", "Rotterdam")
    endpoint_plan = get_global_route_plan(origin="Singapore", destination="New York")
    db = SessionLocal()
    try:
        copilot = ask_copilot(
            CopilotRequest(question="What is the safest route from Mumbai to Rotterdam?", role="Admin"),
            db,
        )
    finally:
        db.close()

    assert plan["recommended"]["ports"][0] == "Mumbai"
    assert plan["recommended"]["ports"][-1] == "Rotterdam"
    assert plan["alternatives"]
    assert endpoint_plan["recommended"]["ports"][0] == "Singapore"
    assert "Recommended safest global route" in copilot["answer"]
    assert copilot["evidence"]["global_route"]["recommended"]


def test_problem_solver_is_topic_locked_and_actionable():
    db = SessionLocal()
    try:
        route_answer = solve_domain_problem(
            ProblemSolverRequest(
                problem="AIS vessels are stale and route safety needs review before departure",
                topic="Auto",
                role="Operator",
            ),
            db,
        )
        route_plan_answer = solve_domain_problem(
            ProblemSolverRequest(
                problem="Find safest route from Mumbai to Rotterdam for P1 cargo and avoid war piracy zones",
                topic="Auto",
                role="Operator",
            ),
            db,
        )
        off_topic = solve_domain_problem(
            ProblemSolverRequest(problem="Tell me a joke about movies", topic="Auto", role="Public"),
            db,
        )
    finally:
        db.close()

    assert route_answer["status"] == "answered"
    assert route_answer["topic"] in {"Route safety", "AIS / live data"}
    assert route_answer["action_plan"]
    assert route_answer["open_page"]
    assert route_plan_answer["route_intelligence"]["recommended"]
    assert route_plan_answer["route_intelligence"]["watch_zones"]
    assert route_plan_answer["recommended_decision"]
    assert off_topic["status"] == "off_topic"
    assert "maritime trade intelligence" in off_topic["answer"]


def test_mission_control_incidents_digest_and_vessel_intelligence_shapes():
    db = SessionLocal()
    try:
        mission = get_mission_control(db=db)
        war_room = get_war_room(db=db)
        incidents = get_incident_commander(persist=False, db=db)
        digest = get_notifications_digest(db=db)
        predictions = get_vessel_predictions(limit=1, db=db)["predictions"]
        vessel_name = predictions[0]["vessel"] if predictions else get_vessel_history(db=db)["vessels"][0]["vessel_name"]
        vessel_intel = get_vessel_intelligence(vessel_identifier=vessel_name, db=db)
        daily = get_daily_brief(db=db)
    finally:
        db.close()

    assert mission["top_problem"]
    assert mission["priorities"]
    assert "explainability" in mission
    assert war_room["playbook"]
    assert war_room["decision_gates"]
    assert "cards" in incidents
    assert "cards" in digest
    assert "risk_score" in vessel_intel
    assert "Daily Maritime Command Brief" in daily["content"]


def test_action_layer_role_views_and_mission_pack_shapes():
    db = SessionLocal()
    try:
        command_result = run_command_action(
            CommandActionRequest(
                action="create_incident",
                target="Test Command Target",
                owner="Tester",
                note="Test command action incident.",
                priority="P2",
            ),
            db=db,
        )
        incident_id = command_result["record"]["id"]
        updated = update_incident_status(
            incident_id,
            IncidentStatusUpdate(status="resolved", owner="Tester", note="Test resolve workflow."),
            db=db,
        )
        incidents = get_incidents(limit=5, db=db)
        timeline = get_decision_timeline(db=db)
        role_view = get_role_command_view(role="Public", db=db)
        confidence = get_confidence_heatmap(db=db)
        ports = get_port_congestion(db=db)
        custody = get_cargo_custody(db=db)
        self_check = get_ai_self_check(db=db)
        pack = get_mission_pack(db=db)
    finally:
        db.close()

    assert command_result["status"] == "completed"
    assert updated["status"] == "resolved"
    assert "events" in incidents
    assert timeline["events"]
    assert role_view["role"] == "Public"
    assert confidence["rows"]
    assert ports["ports"]
    assert "chain" in custody
    assert self_check["checks"]
    assert "Exportable Mission Pack" in pack["content"]
