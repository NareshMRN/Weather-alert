"""
backend.py — Weather & Emergency Alert backend.

"""
import os
import requests
from dotenv import load_dotenv
from crewai import Agent, LLM, Task, Crew, Process
from crewai.tools import tool
import brevo_python
from brevo_python.rest import ApiException

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
ALERT_SENDER_EMAIL = os.getenv("ALERT_SENDER_EMAIL", "noreply@example.com")
ALERT_SENDER_NAME = os.getenv("ALERT_SENDER_NAME", "Weather Alert System")

llm = LLM(model="gemini/gemini-2.5-flash", api_key=GEMINI_API_KEY)

brevo_config = brevo_python.Configuration()
brevo_config.api_key["api-key"] = BREVO_API_KEY
brevo_client = brevo_python.TransactionalEmailsApi(brevo_python.ApiClient(brevo_config))


# --------------------------------------------------------------------------
# Location helpers
# --------------------------------------------------------------------------

def _reverse_geocode(lat, lon):
    """Converts lat/lon (from the browser) into a 'City,CountryCode' string
    that OpenWeatherMap's city-name lookup can use."""
    try:
        resp = requests.get(
            "https://api.openweathermap.org/geo/1.0/reverse",
            params={"lat": lat, "lon": lon, "limit": 1, "appid": OPENWEATHER_API_KEY},
            timeout=10,
        )
        data = resp.json()
        if data:
            return f"{data[0]['name']},{data[0]['country']}"
    except requests.RequestException:
        pass
    return None


def _get_ip_location():
    """Fallback only: approximates location by server/request IP. Used only if
    the frontend didn't provide lat/lon or a city (e.g. user declined browser
    location permission but still wants a rough check)."""
    try:
        resp = requests.get("http://ip-api.com/json/", timeout=10)
        data = resp.json()
        if data.get("status") == "success":
            return f"{data.get('city')},{data.get('countryCode')}"
    except requests.RequestException:
        pass
    return None


def _resolve_city(lat, lon, city):
    if city:
        return city
    if lat is not None and lon is not None:
        resolved = _reverse_geocode(lat, lon)
        if resolved:
            return resolved
    return _get_ip_location()


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------

@tool("Get weather data")
def fetch_weather_data(city: str) -> str:
    """Fetches real-time weather data (temperature, wind, rain, humidity) for a given city."""
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {"q": city, "appid": OPENWEATHER_API_KEY, "units": "metric"}
    response = requests.get(url, params=params, timeout=15)
    data = response.json()

    if response.status_code != 200:
        return f"Error fetching weather: {data.get('message', 'unknown error')}"

    return (
        f"Weather in {data['name']}: "
        f"{data['weather'][0]['description']}, "
        f"Temperature: {data['main']['temp']}°C, "
        f"Wind speed: {data['wind']['speed']} m/s, "
        f"Rain (last 1h): {data.get('rain', {}).get('1h', 0)} mm, "
        f"Humidity: {data['main']['humidity']}%"
    )


@tool("Send alert email")
def send_alert_email(recipient_email: str, subject: str, message: str) -> str:
    """Sends an alert email via Brevo to recipient_email with the given subject and message body."""
    send_smtp_email = brevo_python.SendSmtpEmail(
        sender={"name": ALERT_SENDER_NAME, "email": ALERT_SENDER_EMAIL},
        to=[{"email": recipient_email}],
        subject=subject,
        html_content=f"<html><body>{message}</body></html>",
    )
    try:
        api_response = brevo_client.send_transac_email(send_smtp_email)
        return f"Email sent successfully to {recipient_email}. Message ID: {api_response.message_id}"
    except ApiException as e:
        return f"Failed to send email: {e}"


# --------------------------------------------------------------------------
# Agents (stateless — safe to build once at import time)
# --------------------------------------------------------------------------

weather_monitor = Agent(
    role="Weather Monitor",
    goal="Get real time weather data for the given location",
    backstory="You're an expert in weather monitoring and data collection",
    tools=[fetch_weather_data],
    verbose=True,
    llm=llm,
)

risk_analyst = Agent(
    role="Risk Analyst",
    goal="Analyze the collected weather data and identify potential risks like floods, storms, or heatwaves",
    backstory="You're an expert in risk analysis and have experience analyzing weather data for hazards",
    verbose=True,
    llm=llm,
)

emergency_coordinator = Agent(
    role="Emergency Coordinator",
    goal="Coordinate an emergency response plan based on the analyzed weather risks",
    backstory="You're an expert in emergency response planning based on hazard severity",
    verbose=True,
    llm=llm,
)

alert_dispatcher = Agent(
    role="Alert Dispatcher",
    goal="Write a clear alert message and send it to the user (and emergency contact, if severe) by email",
    backstory="You're a crisis communications specialist who writes calm, direct alerts and makes sure they get delivered",
    tools=[send_alert_email],
    verbose=True,
    llm=llm,
)


# --------------------------------------------------------------------------
# Main backend entry point — this is what the Gradio frontend calls
# --------------------------------------------------------------------------

def check_weather_and_send_alert(
    lat: float = None,
    lon: float = None,
    city: str = None,
    recipient_email: str = "",
    emergency_contact_email: str = "",
) -> dict:
    """
    Checks weather at a location and sends an alert email ONLY if a real hazard
    is detected. Nothing is emailed for a clear/normal weather result.

    Args:
        lat, lon: Browser-provided GPS coordinates (preferred — pass these if
            the frontend got them from navigator.geolocation).
        city: Optional direct city string (e.g. "Bangalore,IN"), used instead
            of lat/lon if provided, or as a manual fallback if the user
            declined location permission.
        recipient_email: Where to send the alert if a hazard is found.
            Required for an alert to actually be sent.
        emergency_contact_email: Optional second recipient, only emailed if
            severity is HIGH or CRITICAL.

    Returns a dict:
        success, location, weather_summary, analysis, severity,
        alert_sent, recipients_notified, dispatch_result, error
    """
    result = {
        "success": False,
        "location": None,
        "weather_summary": None,
        "analysis": None,
        "severity": None,
        "alert_sent": False,
        "recipients_notified": [],
        "dispatch_result": None,
        "error": None,
    }

    city_query = _resolve_city(lat, lon, city)
    if not city_query:
        result["error"] = "Could not determine a location from the provided coordinates/city."
        return result

    result["location"] = city_query

    # --- Step 1: fetch weather + analyze risk ---
    monitor_task = Task(
        description=f"Use the Fetch Weather Data tool to get the current weather for: {city_query}.",
        expected_output="Real time weather data for the given location.",
        agent=weather_monitor,
    )

    analyse_task = Task(
        description=(
            "Analyze the weather data from the previous task to identify potential risks "
            "(floods, storms, heatwaves, cold waves). Be thorough. Your final answer MUST "
            "start with exactly one line in this format: 'SEVERITY: LOW' or 'SEVERITY: MODERATE' "
            "or 'SEVERITY: HIGH' or 'SEVERITY: CRITICAL' — followed by your explanation of any "
            "hazards found."
        ),
        expected_output="A line starting with 'SEVERITY: <LEVEL>' followed by a short hazard explanation.",
        agent=risk_analyst,
        context=[monitor_task],
    )

    check_crew = Crew(
        agents=[weather_monitor, risk_analyst],
        tasks=[monitor_task, analyse_task],
        process=Process.sequential,
        verbose=True,
    )

    try:
        analysis_result = check_crew.kickoff()
    except Exception as e:
        result["error"] = f"Weather check failed: {e}"
        return result

    analysis_text = str(analysis_result)
    result["analysis"] = analysis_text
    result["success"] = True

    # Determine severity in plain Python — don't rely on the LLM alone to
    # decide whether an email gets sent.
    severity = "LOW"
    for level in ("CRITICAL", "HIGH", "MODERATE", "LOW"):
        if f"SEVERITY: {level}" in analysis_text.upper():
            severity = level
            break
    result["severity"] = severity

    # --- Step 2: only build/run the dispatch crew if there's a real hazard ---
    if severity == "LOW":
        return result

    if not recipient_email:
        result["error"] = "Hazard detected but no recipient_email was provided — no alert sent."
        return result

    emergency_task = Task(
        description=(
            f"Based on this risk analysis:\n\n{analysis_text}\n\n"
            "Write a short emergency response plan with recommended actions for this severity level."
        ),
        expected_output="A short, clear emergency response plan.",
        agent=emergency_coordinator,
    )

    to_list = [recipient_email]
    if emergency_contact_email and severity in ("HIGH", "CRITICAL"):
        to_list.append(emergency_contact_email)

    dispatcher_task = Task(
        description=(
            f"Using the risk analysis and emergency plan, write a clear alert email (state the "
            f"hazards, severity, and recommended actions) and send it using the Send Alert Email "
            f"tool, once per address, to each of these recipients: {to_list}. "
            "Confirm whether each email was sent successfully."
        ),
        expected_output="Confirmation that the alert email(s) were sent, or an explanation of any failures.",
        agent=alert_dispatcher,
        context=[analyse_task, emergency_task],
    )

    dispatch_crew = Crew(
        agents=[emergency_coordinator, alert_dispatcher],
        tasks=[emergency_task, dispatcher_task],
        process=Process.sequential,
        verbose=True,
    )

    try:
        dispatch_result = dispatch_crew.kickoff()
    except Exception as e:
        result["error"] = f"Alert dispatch failed: {e}"
        return result

    result["alert_sent"] = True
    result["recipients_notified"] = to_list
    result["dispatch_result"] = str(dispatch_result)
    return result
