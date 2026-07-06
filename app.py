"""
app.py — Weather & Emergency Alert frontend (Gradio).

"""
import gradio as gr
from backend import check_weather_and_send_alert
import os

port = int(os.environ.get("PORT", 7860))

# JS that runs in the user's browser and triggers the real, native
# "Allow this site to know your location?" permission prompt.
GET_LOCATION_JS = """
() => {
  return new Promise((resolve) => {
    if (!navigator.geolocation) {
      resolve([null, null, "Geolocation is not supported by this browser."]);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve([pos.coords.latitude, pos.coords.longitude, ""]),
      (err) => resolve([null, null, "Location permission denied or unavailable: " + err.message])
    );
  });
}
"""

SEVERITY_EMOJI = {
    "LOW": "🟢",
    "MODERATE": "🟡",
    "HIGH": "🟠",
    "CRITICAL": "🔴",
}


def on_location_detected(lat, lon, err):
    if err:
        return err
    return f"📍 Location detected ({lat:.4f}, {lon:.4f})"


def run_check(lat, lon, geo_error, manual_city, recipient_email, emergency_email):
    if not recipient_email or "@" not in recipient_email:
        return "❌ Please enter a valid email address to receive alerts."

    used_lat, used_lon = lat, lon
    prefix = ""
    if geo_error:
        prefix = f"⚠️ Browser location unavailable ({geo_error}). Using manual city instead.\n\n"
        used_lat, used_lon = None, None

    if used_lat is None and not manual_city:
        return prefix + "❌ No location available. Please allow location access or type a city."

    result = check_weather_and_send_alert(
        lat=used_lat,
        lon=used_lon,
        city=manual_city or None,
        recipient_email=recipient_email,
        emergency_contact_email=emergency_email,
    )

    if result["error"]:
        return prefix + f"❌ {result['error']}"

    severity = result["severity"]
    emoji = SEVERITY_EMOJI.get(severity, "")

    lines = [
        prefix,
        f"📍 **Location:** {result['location']}",
        f"{emoji} **Severity:** {severity}",
        "",
        result["analysis"],
    ]

    if result["alert_sent"]:
        lines.append("")
        lines.append(f"✅ **Alert email sent to:** {', '.join(result['recipients_notified'])}")
    elif severity == "LOW":
        lines.append("")
        lines.append("✅ No hazard detected — no email was sent.")

    return "\n".join(lines)


with gr.Blocks(title="Weather & Emergency Alert") as demo:
    gr.Markdown("# 🌦️ Weather & Emergency Alert")
    gr.Markdown(
        "Checks live weather at your location and emails you an alert **only if "
        "a real hazard is detected** (flood, storm, heatwave, cold wave). "
        "No hazard, no email."
    )

    lat_state = gr.Number(visible=False)
    lon_state = gr.Number(visible=False)
    geo_error_state = gr.Textbox(visible=False)

    with gr.Row():
        detect_btn = gr.Button("📍 Detect my location", scale=1)
        geo_status = gr.Textbox(label="Location status", interactive=False, scale=2)

    manual_city = gr.Textbox(
        label="Or type your city manually",
        placeholder="e.g. Bangalore,IN",
    )

    with gr.Row():
        recipient_email = gr.Textbox(label="Your email (required)", placeholder="you@example.com")
        emergency_email = gr.Textbox(label="Emergency contact email (optional)", placeholder="contact@example.com")

    check_btn = gr.Button("Check weather & send alert if needed", variant="primary")
    output = gr.Markdown(label="Result")

    detect_btn.click(
        fn=None,
        inputs=[],
        outputs=[lat_state, lon_state, geo_error_state],
        js=GET_LOCATION_JS,
    ).then(
        fn=on_location_detected,
        inputs=[lat_state, lon_state, geo_error_state],
        outputs=geo_status,
    )

    check_btn.click(
        fn=run_check,
        inputs=[lat_state, lon_state, geo_error_state, manual_city, recipient_email, emergency_email],
        outputs=output,
    )

if __name__ == "__main__":
    demo.launch(
    server_port=port,
    server_name="127.0.0.1",
    show_error=True,
    quiet=False,
    share=True
    )
