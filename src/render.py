"""Per-event-type email renderers for vesselapi notifications.

Each renderer returns a (subject, html_body, text_body) tuple. HTML uses
table-based layout with inline styles so it renders consistently across
Gmail, Outlook, and Apple Mail.
"""

from datetime import datetime
from typing import Tuple

Rendered = Tuple[str, str, str]


_NAVY = "#0b2545"
_TEXT = "#0f1c2e"
_MUTED = "#5e6c84"
_DIVIDER = "#e6eaf0"
_PAGE_BG = "#eef2f6"
_FOOTER_BG = "#f7f9fc"
_LINK = "#2563eb"
_ACCENT = "#0ea5e9"
_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
_MONO = "'SF Mono',Menlo,Consolas,'Liberation Mono',monospace"

_BADGES = {
    "port.arrival":            ("#dcfce7", "#15803d", "Port arrival"),
    "port.departure":          ("#ffedd5", "#c2410c", "Port departure"),
    "eta.eta_changed":         ("#fef3c7", "#b45309", "ETA updated"),
    "eta.destination_changed": ("#ede9fe", "#6d28d9", "Destination changed"),
    "eta.draught_changed":     ("#cffafe", "#0e7490", "Draught changed"),
    "position.geofence_enter": ("#dbeafe", "#1d4ed8", "Geofence enter"),
    "position.geofence_exit":  ("#fee2e2", "#b91c1c", "Geofence exit"),
}
_DEFAULT_BADGE = ("#e2e8f0", "#475569", "Notification")


def render_email(evt: dict) -> Rendered:
    handler = _RENDERERS.get(evt.get("type", ""), _render_generic)
    return handler(evt)


def _vessel_label(v: dict) -> str:
    name = v.get("vesselName") or "Unknown vessel"
    imo = v.get("imo")
    return f"{name} (IMO {imo})" if imo else name


def _fmt_time(iso: str) -> str:
    """Render an ISO-8601 timestamp as e.g. 'Wed 29 Apr 2026 · 06:00 UTC'."""
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%a %d %b %Y · %H:%M UTC")
    except (ValueError, AttributeError, TypeError):
        return iso


def _fmt_duration(minutes) -> str:
    """Render a minute count as e.g. '45m', '1h 30m', '2d 3h'."""
    try:
        m = abs(int(minutes))
    except (TypeError, ValueError):
        return str(minutes)
    if m < 60:
        return f"{m}m"
    if m < 1440:
        h, rem = divmod(m, 60)
        return f"{h}h {rem}m" if rem else f"{h}h"
    d, rem = divmod(m, 1440)
    h = rem // 60
    return f"{d}d {h}h" if h else f"{d}d"


def _shift_label(minutes) -> str:
    try:
        m = int(minutes)
    except (TypeError, ValueError):
        return str(minutes)
    if m == 0:
        return "no change"
    duration = _fmt_duration(m)
    arrow = "▲" if m > 0 else "▼"
    direction = "later" if m > 0 else "earlier"
    return f"{arrow} {duration} {direction}"


def _draught_delta(prev, cur) -> str:
    try:
        p = float(prev)
        c = float(cur)
    except (TypeError, ValueError):
        return "—"
    delta = c - p
    if abs(delta) < 0.05:
        return "no change"
    arrow = "▲" if delta > 0 else "▼"
    direction = "deeper" if delta > 0 else "lighter"
    return f"{arrow} {abs(delta):.2f} m {direction}"


def _row(label: str, value: str, mono: bool = False) -> str:
    val_font = _MONO if mono else _FONT
    return (
        '<tr>'
        f'<td style="padding:13px 0;color:{_MUTED};font-size:11px;text-transform:uppercase;'
        f'letter-spacing:.08em;font-weight:600;width:130px;border-top:1px solid {_DIVIDER};'
        'vertical-align:top;">' + label + '</td>'
        f'<td style="padding:13px 0;color:{_TEXT};font-size:15px;font-weight:600;'
        f'font-family:{val_font};border-top:1px solid {_DIVIDER};">' + value + '</td>'
        '</tr>'
    )


def _envelope(event_type: str, headline: str, lede: str, rows_html: str) -> str:
    badge_bg, badge_fg, badge_text = _BADGES.get(event_type, _DEFAULT_BADGE)
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{headline}</title>'
        '</head>\n'
        f'<body style="margin:0;padding:0;background:{_PAGE_BG};font-family:{_FONT};'
        f'color:{_TEXT};-webkit-font-smoothing:antialiased;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:{_PAGE_BG};">'
        '<tr><td align="center" style="padding:32px 12px;">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" '
        'style="max-width:600px;width:100%;background:#ffffff;border-radius:14px;overflow:hidden;'
        'box-shadow:0 4px 20px rgba(11,37,69,0.08);">'

        # Header
        f'<tr><td style="background:{_NAVY};padding:18px 28px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
        '<td style="vertical-align:middle;">'
        f'<span style="display:inline-block;width:9px;height:9px;border-radius:50%;'
        f'background:{_ACCENT};vertical-align:middle;margin-right:10px;"></span>'
        '<span style="color:#ffffff;font-size:13px;letter-spacing:.14em;text-transform:uppercase;'
        'font-weight:700;vertical-align:middle;">vesselapi <span style="color:#7896c2;">·</span> alerts</span>'
        '</td>'
        '<td align="right" style="color:#7896c2;font-size:11px;font-family:' + _MONO + ';'
        'letter-spacing:.04em;text-transform:lowercase;">live event</td>'
        '</tr></table></td></tr>'

        # Badge
        '<tr><td style="padding:30px 32px 8px 32px;">'
        f'<span style="display:inline-block;padding:5px 13px;border-radius:999px;'
        f'background:{badge_bg};color:{badge_fg};font-size:11px;font-weight:700;'
        f'letter-spacing:.08em;text-transform:uppercase;">{badge_text}</span>'
        '</td></tr>'

        # Headline
        '<tr><td style="padding:10px 32px 0 32px;">'
        f'<h1 style="margin:0;font-size:26px;line-height:1.2;color:{_NAVY};font-weight:700;'
        f'letter-spacing:-0.01em;">{headline}</h1></td></tr>'

        # Lede
        '<tr><td style="padding:6px 32px 22px 32px;">'
        f'<p style="margin:0;color:{_MUTED};font-size:15px;line-height:1.5;">{lede}</p>'
        '</td></tr>'

        # Detail table
        '<tr><td style="padding:0 32px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'{rows_html}'
        '</table></td></tr>'

        # CTA
        '<tr><td style="padding:28px 32px 32px 32px;">'
        f'<a href="https://vesselapi.com" style="display:inline-block;padding:12px 22px;'
        f'background:{_NAVY};color:#ffffff;text-decoration:none;border-radius:8px;'
        'font-size:14px;font-weight:600;letter-spacing:.01em;">View vessel details &rarr;</a>'
        '</td></tr>'

        # Footer
        f'<tr><td style="background:{_FOOTER_BG};padding:18px 32px;border-top:1px solid {_DIVIDER};">'
        '<p style="margin:0;color:#8492a6;font-size:11px;line-height:1.5;">'
        'You\'re receiving this from a vesselapi notification subscription.<br>'
        f'Powered by <a href="https://vesselapi.com" style="color:{_LINK};text-decoration:none;'
        'font-weight:600;">vesselapi</a></p>'
        '</td></tr>'

        '</table></td></tr></table></body></html>'
    )


def _render_port_arrival(evt: dict) -> Rendered:
    v = evt.get("vessel", {})
    name = v.get("vesselName") or "Unknown vessel"
    imo = v.get("imo")
    port = evt["data"]["portEvent"]["port"]
    when = _fmt_time(evt.get("timestamp", ""))
    country = port.get("country", "—")
    port_name = port.get("name", "—")
    unlocode = port.get("unlocode", "—")

    subject = f"⚓ {name} arrived at {port_name}"
    text = f"{_vessel_label(v)} arrived at {port_name}, {country} on {when}."
    headline = f"{name} arrived at {port_name}"
    lede = f"A port-call arrival was recorded {when}."
    rows = (
        _row("Vessel", name)
        + _row("IMO", str(imo) if imo else "—", mono=True)
        + _row("Port", port_name)
        + _row("Country", country)
        + _row("UN/LOCODE", unlocode, mono=True)
        + _row("Reported", when, mono=True)
    )
    return subject, _envelope(evt.get("type", ""), headline, lede, rows), text


def _render_port_departure(evt: dict) -> Rendered:
    v = evt.get("vessel", {})
    name = v.get("vesselName") or "Unknown vessel"
    imo = v.get("imo")
    port = evt["data"]["portEvent"]["port"]
    when = _fmt_time(evt.get("timestamp", ""))
    country = port.get("country", "—")
    port_name = port.get("name", "—")
    unlocode = port.get("unlocode", "—")

    subject = f"🚢 {name} departed {port_name}"
    text = f"{_vessel_label(v)} departed {port_name}, {country} on {when}."
    headline = f"{name} departed {port_name}"
    lede = f"A port-call departure was recorded {when}."
    rows = (
        _row("Vessel", name)
        + _row("IMO", str(imo) if imo else "—", mono=True)
        + _row("Port", port_name)
        + _row("Country", country)
        + _row("UN/LOCODE", unlocode, mono=True)
        + _row("Reported", when, mono=True)
    )
    return subject, _envelope(evt.get("type", ""), headline, lede, rows), text


def _render_eta_changed(evt: dict) -> Rendered:
    v = evt.get("vessel", {})
    name = v.get("vesselName") or "Unknown vessel"
    imo = v.get("imo")
    change = evt["data"]["etaChange"]
    prev = _fmt_time(change.get("previousEta", ""))
    cur = _fmt_time(change.get("currentEta", ""))
    shift = change.get("shiftMinutes", 0)
    duration = _fmt_duration(shift)
    direction = "later" if shift and shift > 0 else "earlier"

    subject = f"⏱ {name} ETA shifted {duration} {direction}"
    text = f"{_vessel_label(v)} ETA changed: {prev} -> {cur} ({duration} {direction})."
    headline = f"{name} ETA shifted {duration} {direction}"
    lede = f"The estimated arrival is now <strong>{duration} {direction}</strong> than previously reported."
    rows = (
        _row("Vessel", name)
        + _row("IMO", str(imo) if imo else "—", mono=True)
        + _row("Previous ETA", prev)
        + _row("Current ETA", cur)
        + _row("Shift", _shift_label(shift))
    )
    return subject, _envelope(evt.get("type", ""), headline, lede, rows), text


def _render_draught_changed(evt: dict) -> Rendered:
    v = evt.get("vessel", {})
    name = v.get("vesselName") or "Unknown vessel"
    imo = v.get("imo")
    change = evt["data"]["draughtChange"]
    prev = change.get("previous")
    cur = change.get("current")
    delta_label = _draught_delta(prev, cur)
    prev_str = f"{float(prev):.2f} m" if prev is not None else "—"
    cur_str = f"{float(cur):.2f} m" if cur is not None else "—"

    subject = f"⚓ {name} draught {delta_label}"
    text = f"{_vessel_label(v)} draught changed: {prev_str} -> {cur_str} ({delta_label})."
    headline = f"{name} draught {delta_label}"
    descriptor = "loading" if delta_label.startswith("▲") else (
        "unloading" if delta_label.startswith("▼") else "stable"
    )
    lede = f"Reported AIS draught changed — vessel appears to be <strong>{descriptor}</strong>."
    rows = (
        _row("Vessel", name)
        + _row("IMO", str(imo) if imo else "—", mono=True)
        + _row("Previous draught", prev_str, mono=True)
        + _row("Current draught", cur_str, mono=True)
        + _row("Change", delta_label)
    )
    return subject, _envelope(evt.get("type", ""), headline, lede, rows), text


def _render_destination_changed(evt: dict) -> Rendered:
    v = evt.get("vessel", {})
    name = v.get("vesselName") or "Unknown vessel"
    imo = v.get("imo")
    change = evt["data"]["destinationChange"]
    prev = change.get("previous", "—")
    cur = change.get("current", "—")

    subject = f"🧭 {name} destination changed"
    text = f"{_vessel_label(v)} destination changed: {prev} -> {cur}."
    headline = f"{name} destination changed"
    lede = "The reported AIS destination has been updated."
    rows = (
        _row("Vessel", name)
        + _row("IMO", str(imo) if imo else "—", mono=True)
        + _row("Previous", prev, mono=True)
        + _row("Current", cur, mono=True)
    )
    return subject, _envelope(evt.get("type", ""), headline, lede, rows), text


def _render_geofence(evt: dict) -> Rendered:
    v = evt.get("vessel", {})
    name = v.get("vesselName") or "Unknown vessel"
    imo = v.get("imo")
    direction = "entered" if evt.get("type", "").endswith("enter") else "exited"
    when = _fmt_time(evt.get("timestamp", ""))

    subject = f"🛰 {name} {direction} geofence"
    text = f"{_vessel_label(v)} {direction} the configured geofence at {when}."
    headline = f"{name} {direction} geofence"
    lede = f"The vessel crossed a configured geofence boundary {when}."
    rows = (
        _row("Vessel", name)
        + _row("IMO", str(imo) if imo else "—", mono=True)
        + _row("Direction", direction.capitalize())
        + _row("Reported", when, mono=True)
    )
    return subject, _envelope(evt.get("type", ""), headline, lede, rows), text


def _render_generic(evt: dict) -> Rendered:
    v = evt.get("vessel", {})
    name = v.get("vesselName") or "Unknown vessel"
    imo = v.get("imo")
    event_type = evt.get("type", "unknown")
    when = _fmt_time(evt.get("timestamp", ""))
    message = (evt.get("data") or {}).get("message")

    subject = f"📡 {name}: {event_type}"
    text_lines = [f"{event_type} event for {_vessel_label(v)} at {when}."]
    if message:
        text_lines.append(message)
    text = " ".join(text_lines)

    headline = f"{name}: {event_type}"
    lede = message or f"A {event_type} event was recorded {when}."
    rows = (
        _row("Vessel", name)
        + _row("IMO", str(imo) if imo else "—", mono=True)
        + _row("Event type", event_type, mono=True)
        + _row("Reported", when, mono=True)
    )
    return subject, _envelope(event_type, headline, lede, rows), text


_RENDERERS = {
    "port.arrival": _render_port_arrival,
    "port.departure": _render_port_departure,
    "eta.eta_changed": _render_eta_changed,
    "eta.destination_changed": _render_destination_changed,
    "eta.draught_changed": _render_draught_changed,
    "position.geofence_enter": _render_geofence,
    "position.geofence_exit": _render_geofence,
}
