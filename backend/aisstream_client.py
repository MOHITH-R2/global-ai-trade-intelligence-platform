import asyncio
import datetime
import json
import logging
import math
import os
import ssl
import threading
from typing import Any
from dotenv import load_dotenv

load_dotenv()

try:
    import websockets
except ImportError:  # pragma: no cover - handled by status output in app
    websockets = None


LOGGER = logging.getLogger(__name__)
AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"
DEFAULT_BOUNDING_BOXES = [
    [[0.7, 100.8], [1.8, 104.4]],       # Singapore / Malacca Strait
    [[22.0, 113.0], [31.8, 123.8]],     # South China Sea / Shanghai
    [[24.0, 51.0], [26.8, 57.5]],       # Gulf corridor / Dubai
    [[32.8, -119.2], [34.3, -117.6]],   # Los Angeles
    [[50.8, 2.5], [52.4, 5.3]],         # Rotterdam approaches
]
PORT_COORDS = {
    "Shanghai": (31.2304, 121.4737),
    "Singapore": (1.3521, 103.8198),
    "Rotterdam": (51.9244, 4.4777),
    "Los Angeles": (33.7182, -118.1957),
    "Dubai": (25.2048, 55.2708),
}
FALLBACK_MANIFESTS = [
    {"cargo": "Petrol", "tons": 82000, "value": "$74M", "class": "Energy"},
    {"cargo": "Gold", "tons": 42, "value": "$2.7B", "class": "High value"},
    {"cargo": "Electronics", "tons": 12800, "value": "$430M", "class": "Priority"},
    {"cargo": "LNG", "tons": 91000, "value": "$118M", "class": "Energy"},
    {"cargo": "Grain", "tons": 64000, "value": "$31M", "class": "Food"},
    {"cargo": "Medical Supplies", "tons": 7200, "value": "$210M", "class": "Critical"},
]

AISSTREAM_LOCK = threading.Lock()
AISSTREAM_STATE: dict[str, Any] = {
    "running": False,
    "connected": False,
    "last_error": None,
    "last_message_at": None,
    "vessels": {},
}


def aisstream_enabled() -> bool:
    return os.getenv("AIS_PROVIDER", "demo").strip().lower() == "aisstream" and bool(
        os.getenv("AISSTREAM_API_KEY", "").strip()
    )


def insecure_ssl_allowed() -> bool:
    app_mode = os.getenv("APP_MODE", "demo").strip().lower()
    production_flag = os.getenv("PRODUCTION_MODE", "").strip().lower()
    if app_mode in {"prod", "production"} or production_flag in {"1", "true", "yes", "on"}:
        return False
    return os.getenv("AISSTREAM_ALLOW_INSECURE_SSL", "").strip().lower() in {"1", "true", "yes", "on"}


def _number(value, default=None):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _text(*values):
    for value in values:
        if value is None:
            continue
        value = str(value).strip()
        if value:
            return value
    return ""


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def _nearest_port(lat: float, lon: float) -> str:
    return min(PORT_COORDS, key=lambda port: abs(lat - PORT_COORDS[port][0]) + abs(lon - PORT_COORDS[port][1]))


def _project_position(lat: float, lon: float, heading: float, nautical_miles: float = 120.0):
    radians = math.radians(heading or 0)
    lat_delta = math.cos(radians) * nautical_miles / 60
    cos_lat = max(0.2, abs(math.cos(math.radians(lat))))
    lon_delta = math.sin(radians) * nautical_miles / (60 * cos_lat)
    return lat + lat_delta, lon + lon_delta


def _geo_distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_nm = 3440.065
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return radius_nm * (2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1 - a))))


def _bearing_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_lambda = math.radians(lon2 - lon1)
    y = math.sin(delta_lambda) * math.cos(phi2)
    x = (math.cos(phi1) * math.sin(phi2)) - (
        math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)
    )
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _exaggerated_motion_allowed() -> bool:
    return os.getenv("AISSTREAM_DEMO_EXAGGERATED_MOTION", "").strip().lower() in {"1", "true", "yes", "on"}


def _map_motion_multiplier() -> float:
    default_multiplier = 90.0
    raw_value = _number(os.getenv("AISSTREAM_MAP_MOTION_MULTIPLIER"), default_multiplier) or default_multiplier
    max_multiplier = 5000.0 if _exaggerated_motion_allowed() else 220.0
    return max(1.0, min(max_multiplier, raw_value))


def _motion_window_seconds() -> float:
    value = _number(os.getenv("AISSTREAM_MOTION_WINDOW_SECONDS"), 90.0) or 90.0
    return max(10.0, min(240.0, value))


def _max_projected_nm() -> float:
    value = _number(os.getenv("AISSTREAM_MAX_PROJECTED_NM"), 35.0) or 35.0
    return max(1.0, min(140.0, value))


def _clean_track(track: Any, lon: float, lat: float, display_lon: float, display_lat: float) -> list[list[float]]:
    rows: list[list[float]] = []
    if isinstance(track, list):
        for point in track[-7:]:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            point_lon = _number(point[0])
            point_lat = _number(point[1])
            if point_lat is None or point_lon is None:
                continue
            rows.append([round(point_lon, 5), round(point_lat, 5)])

    current = [round(lon, 5), round(lat, 5)]
    if not rows or rows[-1] != current:
        rows.append(current)

    display = [round(display_lon, 5), round(display_lat, 5)]
    if rows[-1] != display:
        rows.append(display)
    return rows[-8:]


def _project_api_display_position(row: dict[str, Any], now: datetime.datetime) -> dict[str, Any]:
    lat = _number(row.get("position_lat"))
    lon = _number(row.get("position_lon"))
    speed = max(0.0, _number(row.get("speed_knots"), 0.0) or 0.0)
    heading = _number(row.get("heading"), _number(row.get("cog"), 0.0)) or 0.0
    last_epoch = _number(row.get("_last_signal_epoch"), now.timestamp())
    prev_lat = _number(row.get("previous_position_lat"))
    prev_lon = _number(row.get("previous_position_lon"))
    if lat is None or lon is None:
        return row

    age_seconds = max(0.0, now.timestamp() - float(last_epoch or now.timestamp()))
    source_heading = heading
    api_step_nm = 0.0
    if prev_lat is not None and prev_lon is not None:
        api_step_nm = _geo_distance_nm(prev_lat, prev_lon, lat, lon)
        if api_step_nm >= 0.03:
            source_heading = _bearing_between(prev_lat, prev_lon, lat, lon)

    projected_seconds = min(age_seconds, _motion_window_seconds())
    real_nm = speed * (projected_seconds / 3600.0)
    projected_nm = min(_max_projected_nm(), real_nm * _map_motion_multiplier())
    if speed <= 0.5 or projected_nm <= 0.02:
        display_lat, display_lon = lat, lon
    else:
        display_lat, display_lon = _project_position(lat, lon, source_heading, projected_nm)
        display_lat = max(-89.9, min(89.9, display_lat))
        display_lon = ((display_lon + 180) % 360) - 180

    track = _clean_track(row.get("api_track"), lon, lat, display_lon, display_lat)
    row.update({
        "api_position_lat": round(lat, 5),
        "api_position_lon": round(lon, 5),
        "display_position_lat": round(display_lat, 5),
        "display_position_lon": round(display_lon, 5),
        "motion_age_seconds": round(age_seconds, 1),
        "motion_projected_nm": round(projected_nm, 2),
        "motion_real_nm": round(real_nm, 3),
        "motion_multiplier": round(_map_motion_multiplier(), 1),
        "motion_quality": "api-track" if api_step_nm >= 0.03 else "api-heading",
        "motion_source": "AISStream API speed, heading, signal age, and previous API track",
        "motion_trail": track,
        "api_track": track[:-1] if track[-1] != [round(lon, 5), round(lat, 5)] else track,
        "course_heading": round(source_heading, 1),
    })
    return row


def _manifest_for_mmsi(mmsi: str):
    try:
        index = int(mmsi) % len(FALLBACK_MANIFESTS)
    except ValueError:
        index = 0
    return FALLBACK_MANIFESTS[index]


def _bounding_boxes():
    raw_boxes = os.getenv("AISSTREAM_BOUNDING_BOXES", "").strip()
    if not raw_boxes:
        return DEFAULT_BOUNDING_BOXES
    try:
        parsed = json.loads(raw_boxes)
        if isinstance(parsed, list) and parsed:
            return parsed
    except json.JSONDecodeError as exc:
        with AISSTREAM_LOCK:
            AISSTREAM_STATE["last_error"] = f"Invalid AISSTREAM_BOUNDING_BOXES JSON: {exc}"
    return DEFAULT_BOUNDING_BOXES


def _max_vessels() -> int:
    return int(_number(os.getenv("AISSTREAM_MAX_VESSELS"), 12) or 12)


def _stale_seconds() -> int:
    return int(_number(os.getenv("AISSTREAM_STALE_SECONDS"), 900) or 900)


def _subscription_message():
    message = {
        "APIKey": os.getenv("AISSTREAM_API_KEY", "").strip(),
        "BoundingBoxes": _bounding_boxes(),
        "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
    }
    raw_mmsi = os.getenv("AISSTREAM_MMSI", "").strip()
    if raw_mmsi:
        message["FiltersShipMMSI"] = [item.strip() for item in raw_mmsi.split(",") if item.strip()]
    return message


def _trim_cache_locked():
    vessels = AISSTREAM_STATE["vessels"]
    cutoff = _utc_now().timestamp() - _stale_seconds()
    stale_keys = [
        mmsi
        for mmsi, row in vessels.items()
        if float(row.get("_last_signal_epoch", 0) or 0) < cutoff
    ]
    for mmsi in stale_keys:
        vessels.pop(mmsi, None)
    max_vessels = max(1, _max_vessels() * 4)
    if len(vessels) > max_vessels:
        newest = sorted(vessels.items(), key=lambda item: item[1].get("_last_signal_epoch", 0), reverse=True)
        AISSTREAM_STATE["vessels"] = dict(newest[:max_vessels])


def _handle_position_report(message: dict[str, Any]):
    body = message.get("Message", {}).get("PositionReport", {})
    metadata = message.get("Metadata") or message.get("MetaData") or {}
    lat = _number(body.get("Latitude"), _number(metadata.get("Latitude")))
    lon = _number(body.get("Longitude"), _number(metadata.get("Longitude")))
    if lat is None or lon is None or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return

    mmsi = _text(body.get("UserID"), metadata.get("MMSI"), metadata.get("UserID"))
    if not mmsi:
        return

    now = _utc_now()
    with AISSTREAM_LOCK:
        existing = AISSTREAM_STATE["vessels"].get(mmsi, {})
        previous_lat = _number(existing.get("position_lat"))
        previous_lon = _number(existing.get("position_lon"))
        existing_track = existing.get("api_track", [])
        api_track = []
        if isinstance(existing_track, list):
            api_track = [
                [round(_number(point[0], 0) or 0, 5), round(_number(point[1], 0) or 0, 5)]
                for point in existing_track
                if isinstance(point, (list, tuple)) and len(point) >= 2
            ][-7:]
        current_track_point = [round(lon, 5), round(lat, 5)]
        if not api_track or api_track[-1] != current_track_point:
            api_track.append(current_track_point)
        api_track = api_track[-8:]
        name = _text(metadata.get("ShipName"), metadata.get("Name"), existing.get("name"), f"MMSI {mmsi}")
        destination = _text(metadata.get("Destination"), metadata.get("DEST"), existing.get("ais_destination"))
        speed = _number(body.get("Sog"), _number(metadata.get("Sog"), existing.get("speed_knots", 0))) or 0
        cog = _number(body.get("Cog"), _number(metadata.get("Cog"), 0)) or 0
        heading = _number(body.get("TrueHeading"), _number(metadata.get("Heading"), cog)) or cog
        if heading in {360, 511}:
            heading = cog
        origin_port = _nearest_port(lat, lon)
        destination_lat, destination_lon = _project_position(lat, lon, heading, max(30.0, min(220.0, (speed or 8) * 7)))
        manifest = _manifest_for_mmsi(mmsi)

        AISSTREAM_STATE["vessels"][mmsi] = {
            **existing,
            "id": mmsi,
            "mmsi": mmsi,
            "name": name,
            "position_lat": round(lat, 5),
            "position_lon": round(lon, 5),
            "previous_position_lat": round(previous_lat, 5) if previous_lat is not None else round(lat, 5),
            "previous_position_lon": round(previous_lon, 5) if previous_lon is not None else round(lon, 5),
            "status": "active",
            "route": f"{origin_port} AIS corridor",
            "origin_port": origin_port,
            "destination_port": destination or "Live AIS destination",
            "origin_lat": PORT_COORDS[origin_port][0],
            "origin_lon": PORT_COORDS[origin_port][1],
            "destination_lat": round(destination_lat, 5),
            "destination_lon": round(destination_lon, 5),
            "ais_destination": destination,
            "cargo": existing.get("cargo") or manifest["cargo"],
            "cargo_class": existing.get("cargo_class") or manifest["class"],
            "cargo_tons": existing.get("cargo_tons") or manifest["tons"],
            "cargo_value": existing.get("cargo_value") or manifest["value"],
            "cargo_source": existing.get("cargo_source") or "Inferred Demo Cargo",
            "cargo_verified": bool(existing.get("cargo_verified", False)),
            "progress": 0,
            "speed_knots": round(speed, 1),
            "eta_hours": None,
            "heading": round(heading, 1),
            "last_signal_at": now.isoformat(),
            "previous_signal_at": existing.get("last_signal_at"),
            "source": "AISStream",
            "api_track": api_track,
            "_last_signal_epoch": now.timestamp(),
            "_previous_signal_epoch": existing.get("_last_signal_epoch"),
        }
        AISSTREAM_STATE["last_message_at"] = now.isoformat()
        _trim_cache_locked()


def _handle_static_data(message: dict[str, Any]):
    body = message.get("Message", {}).get("ShipStaticData", {})
    metadata = message.get("Metadata") or message.get("MetaData") or {}
    mmsi = _text(body.get("UserID"), metadata.get("MMSI"), metadata.get("UserID"))
    if not mmsi:
        return
    with AISSTREAM_LOCK:
        existing = AISSTREAM_STATE["vessels"].get(mmsi, {"id": mmsi, "mmsi": mmsi})
        name = _text(body.get("Name"), metadata.get("ShipName"), metadata.get("Name"), existing.get("name"))
        destination = _text(body.get("Destination"), metadata.get("Destination"), existing.get("ais_destination"))
        existing.update({
            "name": name or existing.get("name", f"MMSI {mmsi}"),
            "ais_destination": destination,
        })
        AISSTREAM_STATE["vessels"][mmsi] = existing


def _handle_ais_message(raw_message: str):
    try:
        message = json.loads(raw_message)
    except json.JSONDecodeError:
        return

    message_type = message.get("MessageType")
    if message_type == "PositionReport":
        _handle_position_report(message)
    elif message_type == "ShipStaticData":
        _handle_static_data(message)
    elif message_type == "Error":
        with AISSTREAM_LOCK:
            AISSTREAM_STATE["last_error"] = str(message)


async def _aisstream_loop():
    if websockets is None:
        with AISSTREAM_LOCK:
            AISSTREAM_STATE["last_error"] = "Python package 'websockets' is not installed."
        return

    while aisstream_enabled():
        try:
            ssl_context = ssl._create_unverified_context() if insecure_ssl_allowed() else None
            connect_kwargs = {"ping_interval": 20, "ping_timeout": 20}
            if ssl_context is not None:
                connect_kwargs["ssl"] = ssl_context
            async with websockets.connect(AISSTREAM_URL, **connect_kwargs) as websocket:
                await websocket.send(json.dumps(_subscription_message()))
                with AISSTREAM_LOCK:
                    AISSTREAM_STATE["connected"] = True
                    AISSTREAM_STATE["last_error"] = None
                async for raw_message in websocket:
                    _handle_ais_message(raw_message)
        except Exception as exc:  # pragma: no cover - depends on external service/network
            LOGGER.warning("AISStream connection failed: %s", exc)
            with AISSTREAM_LOCK:
                AISSTREAM_STATE["connected"] = False
                AISSTREAM_STATE["last_error"] = str(exc)
            await asyncio.sleep(10)


def _thread_entry():
    try:
        asyncio.run(_aisstream_loop())
    except Exception as exc:  # pragma: no cover - defensive guard for background thread
        LOGGER.exception("AISStream listener stopped: %s", exc)
        with AISSTREAM_LOCK:
            AISSTREAM_STATE["connected"] = False
            AISSTREAM_STATE["last_error"] = str(exc)


def start_aisstream_listener():
    if not aisstream_enabled():
        return
    with AISSTREAM_LOCK:
        if AISSTREAM_STATE["running"]:
            return
        AISSTREAM_STATE["running"] = True
    thread = threading.Thread(target=_thread_entry, daemon=True)
    thread.start()


def get_aisstream_vessels(limit: int | None = None):
    now = _utc_now()
    with AISSTREAM_LOCK:
        _trim_cache_locked()
        rows = [dict(row) for row in AISSTREAM_STATE["vessels"].values()]
    projected_rows = [_project_api_display_position(row, now) for row in rows]
    clean_rows = [{key: value for key, value in row.items() if not key.startswith("_")} for row in projected_rows]
    clean_rows.sort(key=lambda row: row.get("last_signal_at", ""), reverse=True)
    return clean_rows[: limit or _max_vessels()]


def get_aisstream_status():
    boxes = _bounding_boxes()
    with AISSTREAM_LOCK:
        return {
            "enabled": aisstream_enabled(),
            "running": AISSTREAM_STATE["running"],
            "connected": AISSTREAM_STATE["connected"],
            "vessel_count": len(AISSTREAM_STATE["vessels"]),
            "last_message_at": AISSTREAM_STATE["last_message_at"],
            "last_error": AISSTREAM_STATE["last_error"],
            "bounding_boxes": boxes,
            "ssl_verification": "disabled-local-demo" if insecure_ssl_allowed() else "enabled",
            "map_motion_multiplier": _map_motion_multiplier(),
            "motion_window_seconds": _motion_window_seconds(),
            "max_projected_nm": _max_projected_nm(),
            "motion_mode": "demo-exaggerated" if _exaggerated_motion_allowed() else "realistic-api-projection",
        }
