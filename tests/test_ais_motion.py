import datetime

from backend.aisstream_client import _project_api_display_position


def test_ais_display_projection_keeps_true_api_position(monkeypatch):
    monkeypatch.setenv("AISSTREAM_MAP_MOTION_MULTIPLIER", "90")
    monkeypatch.setenv("AISSTREAM_MAX_PROJECTED_NM", "35")
    now = datetime.datetime.fromtimestamp(1000, tz=datetime.timezone.utc)
    row = {
        "position_lat": 1.0,
        "position_lon": 103.0,
        "previous_position_lat": 0.98,
        "previous_position_lon": 102.95,
        "speed_knots": 20,
        "heading": 90,
        "_last_signal_epoch": 970,
        "api_track": [[102.95, 0.98], [103.0, 1.0]],
    }

    projected = _project_api_display_position(row, now)

    assert projected["api_position_lat"] == 1.0
    assert projected["api_position_lon"] == 103.0
    assert projected["display_position_lon"] != projected["api_position_lon"]
    assert 0 < projected["motion_projected_nm"] <= 35
    assert len(projected["motion_trail"]) >= 3
    assert projected["motion_source"].startswith("AISStream API")
