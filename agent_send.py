"""
agent_send.py - the laptop agent

Every 30 seconds it:
  1. reads this laptop's own serial number (once, when it starts)
  2. reads the laptop list from Firebase and finds the laptop with that serial
     number (laptop/<id>/serial_number) -> that tells us which student owns it
  3. reads the router list from Firebase (router/ node: bssid -> location)
  4. reads this laptop's wifi BSSID, IP address and gateway
  5. decides the status and the location
  6. writes the result to Firebase at agent/<laptop id>

The same .exe works on every laptop - nothing to change per laptop.
A laptop only starts reporting once ICTC has registered its serial number
on the dashboard (Add Student).

Status:
  online  = the BSSID is in the router list   (location = that router's location)
  away    = can reach Firebase, but the BSSID is NOT in the router list
  offline = cannot reach Firebase
            (in practice the dashboard marks a laptop Offline when it has
             not reported for 2 minutes, because an offline laptop cannot send)

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

AGENT_EMAIL = "testagent@gmail.com"        # the agent's Firebase login (not the admin's)
AGENT_PASSWORD = "MSUAGENT123!!!"

SEND_EVERY_SECONDS = 30
AWAY_LOCATION = "Outside university"
# ---------------------------------

# Stops a black console window from flashing every time netsh / ipconfig /
# powershell runs (matters once this is built into a background .exe).
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Values some manufacturers put in place of a real serial number
FAKE_SERIALS = {"", "0", "NONE", "DEFAULT STRING", "TO BE FILLED BY O.E.M.",
                "SYSTEM SERIAL NUMBER", "NOT APPLICABLE", "N/A"}

_token = {"value": None, "time": 0}
_routers = {}    # last router list we got (kept if Firebase cannot be reached)
_laptops = {}    # last laptop list we got: {SERIAL: laptop id}


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


def normalize_serial(value):
    """Make every serial number look the same: uppercase, no spaces."""
    if not value:
        return None
    return "".join(str(value).split()).upper()


def load_routers():
    """Read router/ from Firebase and return {bssid: location}.
    Works whether the router key is R001-style or the BSSID itself."""
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


def load_laptops():
    """Read laptop/ from Firebase and return {SERIAL: laptop id}."""
    global _laptops
    data = firebase_request("GET", "laptop")
    laptops = {}
    for laptop_id, item in (data or {}).items():
        if not isinstance(item, dict):
            continue
        serial = normalize_serial(item.get("serial_number"))
        if serial:
            laptops[serial] = laptop_id
    _laptops = laptops
    return laptops


# ---------- Laptop info ----------

def run_hidden(command):
    """Run a Windows command without showing a window and return its text output."""
    return subprocess.run(
        command, capture_output=True, text=True, timeout=15,
        stdin=subprocess.DEVNULL,   # needed when built with --noconsole
        creationflags=NO_WINDOW
    ).stdout


def get_serial_number():
    """Read the laptop's serial number from the BIOS.
    Tries PowerShell first (works on Windows 10 and 11), then the older wmic."""
    serial = None
    try:
        output = run_hidden(["powershell", "-NoProfile", "-Command",
                             "(Get-CimInstance Win32_BIOS).SerialNumber"])
        serial = output.strip()
    except Exception:
        pass

    if not serial:
        try:
            output = run_hidden(["wmic", "bios", "get", "serialnumber"])
            lines = [line.strip() for line in output.splitlines() if line.strip()]
            # first line is the heading "SerialNumber", the second is the value
            if len(lines) >= 2:
                serial = lines[1]
        except Exception:
            pass

    serial = normalize_serial(serial)
    if not serial or serial in FAKE_SERIALS:
        return None
    return serial


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
        output = run_hidden(["netsh", "wlan", "show", "interfaces"])
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
        lines = run_hidden(["ipconfig"]).splitlines()
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
    """Online = this laptop can reach our Firebase database.
    (Checking Firebase itself is more reliable than checking Google's DNS,
     which some university networks block.)"""
    host = DATABASE_URL.replace("https://", "").split("/")[0]
    try:
        socket.create_connection((host, 443), timeout=5).close()
        return True
    except OSError:
        return False


# ---------- Build the report ----------

def build_report(laptop_id, serial, routers):
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
        "laptopId": laptop_id,
        "serial_number": serial,
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

    serial = get_serial_number()       # the serial never changes, so read it once
    if serial:
        print(f"This laptop's serial number: {serial}")
    else:
        print("Could not read this laptop's serial number. The agent cannot report.")
        sys.exit(1)

    while True:
        now = datetime.now().strftime("%I:%M:%S %p")
        try:
            # 1. Which laptop is this? Compare our serial with the laptop list.
            try:
                laptops = load_laptops()
            except Exception as error:
                laptops = _laptops     # use the last list we had
                print(f"[{now}] Could not read the laptop list ({explain_error(error)}), "
                      f"using the last one ({len(laptops)} laptops).")

            laptop_id = laptops.get(serial)
            if not laptop_id:
                print(f"[{now}] Serial {serial} is not registered yet. "
                      f"Add it on the dashboard (Add Student). Will try again.")
            else:
                # 2. Where is it? Compare the BSSID with the router list.
                try:
                    routers = load_routers()
                except Exception as error:
                    routers = _routers  # use the last list we had
                    print(f"[{now}] Could not read the router list ({explain_error(error)}), "
                          f"using the last one ({len(routers)} routers).")

                # 3. Send the report.
                report = build_report(laptop_id, serial, routers)
                firebase_request("PUT", f"agent/{laptop_id}", report)
                print(f"[{now}] Sent as {laptop_id}: {report['connection_status']}, "
                      f"location {report['location'] or 'n/a'}, "
                      f"BSSID {report['bssid'] or 'n/a'}, IP {report['ip_address']}")
        except Exception as error:
            print(f"[{now}] Could not send: {explain_error(error)}")
        if once:
            break
        time.sleep(SEND_EVERY_SECONDS)