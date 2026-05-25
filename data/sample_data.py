ports = [
    {"name": "Shanghai", "lat": 31.2304, "lon": 121.4737},
    {"name": "Singapore", "lat": 1.3521, "lon": 103.8198},
    {"name": "Rotterdam", "lat": 51.9244, "lon": 4.4777},
    {"name": "Los Angeles", "lat": 33.7182, "lon": -118.1957},
    {"name": "Dubai", "lat": 25.2048, "lon": 55.2708}
]

vessels = [
    {"name": "Vessel A", "position_lat": 31.2304, "position_lon": 121.4737, "status": "active"},
    {"name": "Vessel B", "position_lat": 1.3521, "position_lon": 103.8198, "status": "active"},
    {"name": "Vessel C", "position_lat": 51.9244, "position_lon": 4.4777, "status": "docked"},
    {"name": "Vessel D", "position_lat": 33.7182, "position_lon": -118.1957, "status": "active"},
    {"name": "Vessel E", "position_lat": 25.2048, "position_lon": 55.2708, "status": "maintenance"}
]

trade_routes = [
    {"origin_port": "Shanghai", "destination_port": "Singapore", "risk_level": 3.5, "distance": 3000},
    {"origin_port": "Singapore", "destination_port": "Rotterdam", "risk_level": 5.2, "distance": 10000},
    {"origin_port": "Rotterdam", "destination_port": "Los Angeles", "risk_level": 4.8, "distance": 9000},
    {"origin_port": "Los Angeles", "destination_port": "Dubai", "risk_level": 6.1, "distance": 13000},
    {"origin_port": "Dubai", "destination_port": "Shanghai", "risk_level": 7.3, "distance": 6000}
]

threat_alerts = [
    {"title": "Piracy Alert", "description": "Increased piracy in Gulf of Aden", "severity": "high", "location": "Gulf of Aden"},
    {"title": "Weather Warning", "description": "Storm approaching Singapore", "severity": "medium", "location": "Singapore"},
    {"title": "Port Congestion", "description": "Heavy traffic at Rotterdam", "severity": "low", "location": "Rotterdam"},
    {"title": "Geopolitical Tension", "description": "Trade sanctions in region", "severity": "high", "location": "South China Sea"},
    {"title": "Cargo Theft", "description": "Recent thefts reported", "severity": "medium", "location": "Los Angeles"},
    {"title": "Delay Notice", "description": "Shipping delay due to strike", "severity": "low", "location": "Dubai"},
    {"title": "Cyber Threat", "description": "Potential hacking attempt", "severity": "high", "location": "Global"},
    {"title": "Fuel Shortage", "description": "Fuel prices rising", "severity": "medium", "location": "Middle East"},
    {"title": "Vessel Breakdown", "description": "Engine failure reported", "severity": "low", "location": "Pacific Ocean"},
    {"title": "Regulatory Change", "description": "New emission standards", "severity": "medium", "location": "EU Ports"}
]

# Risk logs can be generated dynamically