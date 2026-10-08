"""
server.py - backend for the MSU laptop connectivity monitor (piece 1)

What it does:
  1. Receives check-ins from laptop agents   -> POST /api/checkin
  2. Saves them in a database (laptops.db)
  3. Lets the dashboard ask for all laptops  -> GET  /api/laptops
  4. Lets ICTC name the routers (BSSID)      -> POST /api/locations, GET /api/locations

Run it:   python server.py
"""

import sqlite3
from datetime import datetime, timezone
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__)
DB_FILE = "laptops.db"

# If a laptop has not checked in for this many seconds, we call it OFFLINE (red).
# The wifi names (SSIDs) that belong to the university. Laptops on any of these
# are "green". Online on any other wifi = "orange" (Away).
# CHANGE THIS to MSU's real wifi name(s)!
UNIVERSITY_SSIDS = ["MSU-WIFI"]

OFFLINE_AFTER_SECONDS = 90  # agent reports every 30s, so 90s of silence = offline


# ---------- Database helpers ----------

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row   # lets us use row["name"]
    return conn


def init_db():
    """Create the tables the first time the server runs."""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS laptops (
            computer_name      TEXT PRIMARY KEY,
            student_name       TEXT,
            ip_address         TEXT,
            wifi_name          TEXT,
            router_bssid       TEXT,
            reported_status    TEXT,     -- green / orange as sent by the laptop
            last_seen          TEXT,     -- last time the laptop checked in (UTC)
            last_online_bssid  TEXT      -- router it was connected to when last online
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS locations (
            bssid       TEXT PRIMARY KEY,
            place_name  TEXT
        )
    """)
    conn.commit()
    conn.close()


def now_utc():
    return datetime.now(timezone.utc)


def clean_bssid(value):
    """Make BSSIDs look the same every time (lowercase, with colons)."""
    if not value:
        return None
    return value.strip().lower().replace("-", ":")


# ---------- Endpoints ----------

@app.route("/")
def dashboard():
    """Show the dashboard page (static/index.html)."""
    return send_from_directory("static", "index.html")


@app.route("/api/checkin", methods=["POST"])
def checkin():
    """A laptop agent sends its info here."""
    data = request.get_json(silent=True)
    if not data or not data.get("computer_name"):
        return jsonify({"error": "computer_name is required"}), 400

    bssid = clean_bssid(data.get("router_bssid"))
    status = data.get("status", "online")

    conn = get_db()
    old = conn.execute(
        "SELECT last_online_bssid FROM laptops WHERE computer_name = ?",
        (data["computer_name"],)
    ).fetchone()

    # Remember the last router it was connected to (only update when we have one).
    last_online_bssid = bssid if bssid else (old["last_online_bssid"] if old else None)

    conn.execute("""
        INSERT INTO laptops (computer_name, student_name, ip_address, wifi_name,
                             router_bssid, reported_status, last_seen, last_online_bssid)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(computer_name) DO UPDATE SET
            student_name      = excluded.student_name,
            ip_address        = excluded.ip_address,
            wifi_name         = excluded.wifi_name,
            router_bssid      = excluded.router_bssid,
            reported_status   = excluded.reported_status,
            last_seen         = excluded.last_seen,
            last_online_bssid = excluded.last_online_bssid
    """, (
        data["computer_name"], data.get("student_name"), data.get("ip_address"),
        data.get("wifi_name"), bssid, status,
        now_utc().isoformat(timespec="seconds"), last_online_bssid
    ))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/laptops", methods=["GET"])
def list_laptops():
    """The dashboard asks for this to show every laptop."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM laptops ORDER BY student_name").fetchall()
    places = {r["bssid"]: r["place_name"]
              for r in conn.execute("SELECT * FROM locations").fetchall()}
    conn.close()

    result = []
    for r in rows:
        last_seen = datetime.fromisoformat(r["last_seen"])
        silent_for = (now_utc() - last_seen).total_seconds()

        # The laptop can't tell us it's offline, so the SERVER decides:
        if silent_for > OFFLINE_AFTER_SECONDS:
            status = "offline"
        elif r["reported_status"] == "offline":
            status = "offline"
        elif r["wifi_name"]:
            # We know the wifi name, so we can tell campus wifi from other wifi.
            on_campus = r["wifi_name"].lower() in [n.lower() for n in UNIVERSITY_SSIDS]
            status = "green" if on_campus else "orange"
        else:
            # Online, but Windows hid the wifi name (Location services off).
            status = "online"

        result.append({
            "student_name": r["student_name"],
            "computer_name": r["computer_name"],
            "ip_address": r["ip_address"],
            "wifi_name": r["wifi_name"],
            "router_bssid": r["router_bssid"],
            "place_name": places.get(r["router_bssid"]),
            "status": status,
            # Where it is connected now (None if red)
            "connected_to": places.get(r["router_bssid"], r["router_bssid"]) if status != "offline" else None,
            # Where it was last connected
            "last_location": places.get(r["last_online_bssid"], r["last_online_bssid"]),
            "last_seen_utc": r["last_seen"],
        })
    return jsonify(result)


@app.route("/api/locations", methods=["POST"])
def add_location():
    """ICTC names a router, e.g. {"bssid": "a4:2b:b0:11:22:33", "place_name": "Library 2F"}"""
    data = request.get_json(silent=True) or {}
    bssid = clean_bssid(data.get("bssid"))
    if not bssid or not data.get("place_name"):
        return jsonify({"error": "bssid and place_name are required"}), 400

    conn = get_db()
    conn.execute(
        "INSERT INTO locations (bssid, place_name) VALUES (?, ?) "
        "ON CONFLICT(bssid) DO UPDATE SET place_name = excluded.place_name",
        (bssid, data["place_name"])
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/locations", methods=["GET"])
def get_locations():
    conn = get_db()
    rows = conn.execute("SELECT * FROM locations ORDER BY place_name").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
