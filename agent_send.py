"""
agent_send.py - the laptop agent

Every 30 seconds it:
  1. reads the router list from Firebase  (router/ node: bssid -> location)
  2. reads this laptop's wifi BSSID, IP address and gateway
  3. decides the status and the location
  4. writes the result to Firebase at agent/<LAPTOP_ID>

Status:
  online  = the BSSID is in the router list   (location = that router's location)
  away    = has internet, but the BSSID is NOT in the router list
  offline = no internet

No extra installs needed (standard Python only).

Run:
    python agent_send.py            # keeps sending every 30 seconds (Ctrl+C to stop)
    python agent_send.py --once     # sends one time only, good for testing
"""

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

# ---- SETTINGS (change these) ----
API_KEY = "AIzaSyBT-h3T1JpZH7zSV5avMSb2BXutcm9MQZQ"
DATABASE_URL = "https://msu-laptopmonitoringsystem-default-rtdb.asia-southeast1.firebasedatabase.app"

AGENT_EMAIL = "PUT_AGENT_EMAIL_HERE"        # the agent's Firebase login (not the admin's)
AGENT_PASSWORD = "PUT_AGENT_PASSWORD_HERE"
LAPTOP_ID = "L001"                          # must match laptop/<id> in the database

SEND_EVERY_SECONDS = 30
AWAY_LOCATION = "Outside university"
# ---------------------------------

_token = {"value": None, "time": 0}
_routers = {}   # last router list we got (kept if Firebase cannot be reached)


# ---------- Firebase ----------

def sign_in():
    """Log in with the agent account and get a token."""
    url = ("https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key="
           + API_KEY)
    body = json.dumps({
        "email": AGENT_EMAIL,
        "password": AGENT_PASSWORD,
        "returnSecureToken": True,
    }).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))
    _token["value"] = data["idToken"]
    _token["time"] = time.time()


def get_token():
    """Tokens last 1 hour, so log in again after 50 minutes."""
    if _token["value"] is None or time.time() - _token["time"] > 50 * 60:
        sign_in()
    return _token["value"]


def firebase_request(method, path, data=None):
    url = f"{DATABASE_URL}/{path}.json?auth={get_token()}"
    body = json.dumps(data).encode("utf-8") if data is not None else None
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def normalize_bssid(value):
    """Make every BSSID look the same: lowercase with colons."""
    if not value:
        return None
    return value.strip().lower().replace("-", ":")


def load_routers():
    """Read router/ from Firebase and return {bssid: location}.
    Works whether the router key is the BSSID itself (R001 style or bssid style)."""
    global _routers
    data = firebase_request("GET", "router")
    routers = {}
    for key, item in (data or {}).items():
        if not isinstance(item, dict):
            continue
        bssid = normalize_bssid(item.get("bssid") or key)
        if bssid:
            routers[bssid] = item.get("location") or "Unknown"
    _routers = routers
    return routers


# ---------- Laptop info ----------

def get_ip_address():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def get_wifi_info():
    """Ask Windows for the wifi name (SSID) and router address (BSSID).
    If Location services is off, Windows hides them and we send None."""
    ssid = None
    bssid = None
    try:
        output = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True, text=True, timeout=10
        ).stdout
        for line in output.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key, value = key.strip().lower(), value.strip()
            if key == "ssid" and value:
                ssid = value
            elif key in ("bssid", "ap bssid") and value:
                bssid = value
    except Exception:
        pass
    return ssid, normalize_bssid(bssid)


def get_default_gateway():
    try:
        output = subprocess.run(
            ["ipconfig"], capture_output=True, text=True, timeout=10
        ).stdout
        lines = output.splitlines()
        for i, line in enumerate(lines):
            if "default gateway" in line.lower() and ":" in line:
                value = line.split(":", 1)[1].strip()
                # the IPv4 address may be on the same line or the next one
                if not value or ":" in value:
                    value = lines[i + 1].strip() if i + 1 < len(lines) else ""
                if value and ":" not in value:
                    return value
    except Exception:
        pass
    return None


def is_online():
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=3).close()
        return True
    except OSError:
        return False


# ---------- Build the report ----------

def build_report(routers):
    ssid, bssid = get_wifi_info()

    if not is_online():
        status = "offline"
        location = None
    elif bssid and bssid in routers:
        status = "online"
        location = routers[bssid]          # <- location comes from the router table
    else:
        status = "away"
        location = AWAY_LOCATION

    return {
        "laptopId": LAPTOP_ID,
        "ssid": ssid,
        "bssid": bssid,
        "location": location,
        "ip_address": get_ip_address(),
        "default_gateway": get_default_gateway(),
        "connection_status": status,
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def explain_error(error):
    if isinstance(error, urllib.error.HTTPError):
        try:
            return f"{error.code} {error.read().decode('utf-8')[:200]}"
        except Exception:
            return str(error.code)
    return str(error)


if __name__ == "__main__":
    once = "--once" in sys.argv
    while True:
        now = datetime.now().strftime("%I:%M:%S %p")
        try:
            try:
                routers = load_routers()
            except Exception as error:
                routers = _routers      # use the last list we had
                print(f"[{now}] Could not read the router list ({explain_error(error)}), "
                      f"using the last one ({len(routers)} routers).")

            report = build_report(routers)
            firebase_request("PUT", f"agent/{LAPTOP_ID}", report)
            print(f"[{now}] Sent: {report['connection_status']}, "
                  f"location {report['location'] or 'n/a'}, "
                  f"BSSID {report['bssid'] or 'n/a'}, IP {report['ip_address']}")
        except Exception as error:
            print(f"[{now}] Could not send: {explain_error(error)}")
        if once:
            break
        time.sleep(SEND_EVERY_SECONDS)