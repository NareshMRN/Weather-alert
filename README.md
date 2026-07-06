# Weather & Emergency Alert — Backend

Backend for a web app that checks live weather at the user's location and
sends an emergency alert email — **only when a real hazard is detected**.
Built with CrewAI (4 agents), Gemini as the LLM, OpenWeatherMap for weather
data, and Brevo for email delivery.

This repo contains **backend only**. The frontend (Gradio) is a separate
piece — `backend.py` exposes one plain Python function for it to call.

## Files

```
backend.py               <- the actual backend logic (import this)
example_gradio_app.py    <- reference example showing how to wire up Gradio + browser geolocation
requirements.txt
.env.example
```

## How the frontend should use this

```python
from backend import check_weather_and_send_alert

result = check_weather_and_send_alert(
    lat=12.9716,                          # from browser navigator.geolocation
    lon=77.5946,
    city=None,                            # or pass a city string instead of lat/lon
    recipient_email="user@example.com",   # required for an alert to be sent
    emergency_contact_email="",           # optional, only emailed on HIGH/CRITICAL
)
```

Returns a dict with keys: success, location, analysis, severity, alert_sent,
recipients_notified, dispatch_result, error.

**No email is sent when severity is LOW** — this is enforced in plain
Python (the dispatch agent/task isn't even created), not left to the LLM to
decide on its own.

## Real browser location permission

Since this now has a real web frontend, actual GPS permission is possible
via the browser's navigator.geolocation API — this is what triggers the
native "Allow this site to see your location?" prompt. See
example_gradio_app.py for a working example of:
- calling navigator.geolocation.getCurrentPosition() from JS inside Gradio
- passing the resulting lat/lon into check_weather_and_send_alert
- falling back to manual city entry if the user denies permission

If lat/lon aren't available (permission denied, JS failed) and no manual
city is given either, the backend falls back to approximate IP-based
geolocation as a last resort.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# fill in GEMINI_API_KEY, OPENWEATHER_API_KEY, BREVO_API_KEY, ALERT_SENDER_EMAIL
```

## Try the reference frontend

```bash
pip install gradio
python example_gradio_app.py
```

## Notes for whoever builds the real frontend

- check_weather_and_send_alert can take a few seconds to run (multiple LLM
  calls + API calls) — show a loading state in the UI.
- Handle result["error"] — e.g. location couldn't be resolved, or a hazard
  was found but no recipient_email was given.
- Consider validating recipient_email format client-side before calling.
- severity will be one of LOW, MODERATE, HIGH, CRITICAL — useful for
  color-coding the UI (green/yellow/orange/red).

## Known limitations

- Tsunami detection is not real — OpenWeatherMap has no tsunami data (that's
  a seismic/NOAA/USGS thing, not weather). The risk analysis is text-based
  from the LLM reasoning over weather conditions only; there's no dedicated
  tsunami feed wired in yet.
- IP-based location fallback is approximate (city-level), not exact.
- Brevo free tier email limits apply (typically 300/day).
