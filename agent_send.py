"""
agent_send.py - the laptop agent (simple version)

Every 30 seconds it collects:  IP address, online/offline, date and time
and sends it to the server.

Run (the server must already be running):
    python agent_send.py            # keeps sending every 30 seconds (Ctrl+C to stop)
    python agent_send.py --once     # sends one time only, good for testing
"""

import getpass
import json
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

# ---- SETTINGS ----
SERVER_URL = "http://127.0.0.1:5000"   # later: the address of your cloud website
SEND_EVERY_SECONDS = 30
# ------------------


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
        pass   # no wifi, or netsh not available: just send None
    return ssid, bssid


def is_online():
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=3).close()
        return True
    except OSError:
        return False


def send_to_server(data):
    request = urllib.request.Request(
        SERVER_URL + "/api/checkin",
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status


def build_report():
    ssid, bssid = get_wifi_info()
    return {
        "computer_name": socket.gethostname(),
        "student_name": getpass.getuser(),
        "ip_address": get_ip_address(),
        "wifi_name": ssid,          # None while Location services is off
        "router_bssid": bssid,      # None while Location services is off
        "status": "online" if is_online() else "offline",
    }


if __name__ == "__main__":
    once = "--once" in sys.argv
    while True:
        report = build_report()
        now = datetime.now().strftime("%I:%M:%S %p")
        try:
            send_to_server(report)
            print(f"[{now}] Sent: {report['status']}, IP {report['ip_address']}, "
                  f"wifi {report['wifi_name'] or 'n/a'}, BSSID {report['router_bssid'] or 'n/a'}")
        except Exception as error:
            # Server not reachable (or laptop offline) - just try again next time
            print(f"[{now}] Could not reach the server: {error}")
        if once:
            break
        time.sleep(SEND_EVERY_SECONDS)
