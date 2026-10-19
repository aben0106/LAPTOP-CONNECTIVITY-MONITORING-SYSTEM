"""
Creates the SQLite database file (monitor.db) from schema.sql.

  python create_database.py            creates monitor.db with the first admin account
  python create_database.py --sample   also adds a few fake students and laptops for testing
  python create_database.py --reset    deletes the old monitor.db first (ERASES ALL DATA)

Needs Flask installed (pip install flask): it is used only to scramble the password.
"""
import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

from werkzeug.security import generate_password_hash

HERE = os.path.dirname(os.path.abspath(__file__))

# The first admin account. Change the password after you log in the first time.
ADMIN_USERNAME = "ictc"
ADMIN_PASSWORD = "ictc12345"


def utc(minutes_ago=0):
    t = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def add_sample(db):
    """Three fake students: one on university wifi, one away, one offline."""
    students = [
        ("202210494", "Bin Jamal", "Abduljalel", "SN-TEST-001", "i5"),
        ("2020-00002", "Ben", "Lee", "SN-TEST-002", "i3"),
        ("2020-00003", "Cara", "Diaz", "SN-TEST-003", "i7"),
    ]
    for number, first, last, serial, cpu in students:
        cur = db.execute(
            "INSERT INTO Student (Admin_ID, Student_Number, First_name, Last_name) VALUES (1, ?, ?, ?)",
            (number, first, last),
        )
        db.execute(
            "INSERT INTO Laptop (Student_ID, Admin_ID, Serial_Number, Processor_Type) VALUES (?, 1, ?, ?)",
            (cur.lastrowid, serial, cpu),
        )
    agent_sql = (
        "INSERT INTO Agent (Laptop_ID, SSID, BSSID, Location, IP_Address, Default_Gateway, "
        "Connection_Status, Timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    )
    # Ana: connected to a university router just now -> Online
    db.execute(agent_sql, (1, "MSU-WiFi", "aa:bb:cc:dd:ee:ff", "Library 2nd floor",
                           "10.0.0.5", "10.0.0.1", "Online", utc(0)))
    # Ben: on another network just now -> Away
    db.execute(agent_sql, (2, "HomeNet", "11:22:33:44:55:66", None,
                           "192.168.1.9", "192.168.1.1", "Away", utc(0)))
    # Cara: last report was 10 minutes ago -> shows Offline
    db.execute(agent_sql, (3, "MSU-WiFi", "aa:bb:cc:dd:ee:ff", "Library 2nd floor",
                           "10.0.0.7", "10.0.0.1", "Online", utc(10)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=os.path.join(HERE, "monitor.db"))
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    if os.path.exists(args.db):
        if args.reset:
            os.remove(args.db)
        else:
            sys.exit(f"{args.db} already exists. Use --reset to delete it and start over.")

    with open(os.path.join(HERE, "schema.sql"), encoding="utf-8") as f:
        schema = f.read()

    db = sqlite3.connect(args.db)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(schema)
    db.execute(
        "INSERT INTO Admin (First_name, Last_name, Username, Password_hash) VALUES (?, ?, ?, ?)",
        ("ICTC", "Admin", ADMIN_USERNAME, generate_password_hash(ADMIN_PASSWORD)),
    )
    if args.sample:
        add_sample(db)
    db.commit()
    db.close()
    print("Created", args.db)
    print(f"Admin login: {ADMIN_USERNAME} / {ADMIN_PASSWORD}")
    if args.sample:
        print("Added 3 sample students and laptops.")


if __name__ == "__main__":
    main()
