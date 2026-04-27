"""Per-renderer tests using the JSON fixtures under tests/fixtures/."""

import pytest

from conftest import load_fixture
from render import render_email


def _evt(name: str) -> dict:
    return load_fixture(name)["event"]


def _assert_envelope(html: str) -> None:
    assert html.startswith("<!DOCTYPE html>")
    assert "vesselapi" in html
    assert "View vessel details" in html


def test_port_arrival_renders():
    subject, html, text = render_email(_evt("port_arrival"))
    assert "EVER GIVEN" in subject
    assert "Suez" in subject
    assert "Egypt" in text
    assert "EVER GIVEN" in html
    assert "9811000" in html
    assert "Wed 22 Apr 2026" in html  # humanized format
    assert "08:14 UTC" in html
    assert "Port arrival" in html  # badge label
    _assert_envelope(html)


def test_port_departure_renders():
    subject, html, text = render_email(_evt("port_departure"))
    assert "MSC GULSUN" in subject
    assert "departed" in subject.lower()
    assert "Singapore" in text
    assert "Singapore" in html
    assert "Port departure" in html
    _assert_envelope(html)


def test_eta_changed_renders():
    subject, html, text = render_email(_evt("eta_changed"))
    assert "OOCL HONG KONG" in subject
    assert "6h 30m" in subject
    assert "later" in subject
    assert "Wed 29 Apr 2026" in html  # humanized format
    assert "06:00 UTC" in html
    assert "12:30 UTC" in html
    assert "ETA updated" in html  # badge
    assert "->" in text
    _assert_envelope(html)


def test_draught_changed_renders():
    subject, html, text = render_email(_evt("draught_changed"))
    assert "YANTIAN EXPRESS" in subject
    assert "draught" in subject.lower()
    assert "9.36 m" in html  # |10.4 - 1.04|
    assert "1.04 m" in html
    assert "10.40 m" in html
    assert "Draught changed" in html  # badge
    assert "deeper" in html  # 1.04 -> 10.4 = loading
    _assert_envelope(html)


def test_destination_changed_renders():
    subject, html, text = render_email(_evt("destination_changed"))
    assert "MAERSK SENTOSA" in subject
    assert "destination changed" in subject.lower()
    assert "USHOU" in html
    assert "USCRP" in html
    assert "Destination changed" in html
    _assert_envelope(html)


def test_geofence_enter_renders():
    subject, html, text = render_email(_evt("geofence_enter"))
    assert "entered geofence" in subject
    assert "MAERSK SEMARANG" in subject
    assert "entered the configured geofence" in text
    assert "Geofence enter" in html
    _assert_envelope(html)


def test_geofence_exit_renders():
    subject, html, text = render_email(_evt("geofence_exit"))
    assert "exited geofence" in subject
    assert "exited the configured geofence" in text
    assert "Geofence exit" in html
    _assert_envelope(html)


def test_unknown_event_falls_back_to_generic():
    subject, html, text = render_email(_evt("unknown_event"))
    assert "vessel.flag_changed" in subject
    assert "BAHAMAS SPIRIT" in subject
    assert "BAHAMAS SPIRIT" in html
    assert "Notification" in html  # default badge label
    _assert_envelope(html)


def test_unknown_vessel_label():
    # No vesselName, no IMO -- should still render without exploding.
    subject, html, _text = render_email({
        "type": "port.arrival",
        "timestamp": "2026-01-01T00:00:00Z",
        "vessel": {},
        "data": {"portEvent": {"port": {"name": "Nowhere"}}},
    })
    assert "Unknown vessel" in subject
    _assert_envelope(html)


def test_bad_timestamp_passes_through():
    from render import _fmt_time  # noqa: WPS437 -- internal helper test

    assert _fmt_time("not-a-date") == "not-a-date"
    # Empty/None inputs should produce a placeholder, not crash.
    assert _fmt_time(None) == "—"
    assert _fmt_time("") == "—"


@pytest.mark.parametrize("fixture", [
    "port_arrival",
    "port_departure",
    "eta_changed",
    "destination_changed",
    "draught_changed",
    "geofence_enter",
    "geofence_exit",
    "unknown_event",
])
def test_all_fixtures_render_three_strings(fixture):
    out = render_email(_evt(fixture))
    assert len(out) == 3
    assert all(isinstance(part, str) and part for part in out)
