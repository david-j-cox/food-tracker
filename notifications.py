"""Ntfy push notification scheduling for post-meal symptom check-ins.

Nudges are stored in the database and sent by a background thread
that checks every 30 seconds. This survives Fly.io machine restarts
(pending nudges persist in the DB and resume on next boot).
"""

import threading
import time
from datetime import datetime, timedelta

import requests

from config import Config
from models import PendingNudge, get_session

NTFY_URL = "https://ntfy.sh"
_bg_thread_started = False


def schedule_nudges(meal_slot: str, consumed_at: datetime, app_url: str = "https://food-tracker.fly.dev"):
    """Insert pending nudge rows for 10min and 90min after a meal."""
    if not Config.NTFY_TOPIC:
        return

    meal_label = meal_slot.replace("-", " ")
    db = get_session()
    try:
        # 10-minute nudge
        db.add(PendingNudge(
            fire_at=consumed_at + timedelta(minutes=10),
            title=f"Quick check after {meal_label}",
            message="How are you feeling? Tap to log any symptoms.",
        ))

        # 90-minute nudge (skip if it would land after 10pm)
        fire_90 = consumed_at + timedelta(minutes=90)
        if fire_90.hour < 22:
            db.add(PendingNudge(
                fire_at=fire_90,
                title=f"How's digestion after {meal_label}?",
                message="It's been 90 minutes. Tap to log how you're feeling.",
            ))

        db.commit()
    finally:
        db.close()


def send_due_nudges():
    """Check for and send any nudges that are past due. Called on each request."""
    if not Config.NTFY_TOPIC:
        return

    db = get_session()
    try:
        now = datetime.now()
        due = (
            db.query(PendingNudge)
            .filter(PendingNudge.sent == 0, PendingNudge.fire_at <= now)
            .all()
        )

        for nudge in due:
            try:
                requests.post(
                    f"{NTFY_URL}/{Config.NTFY_TOPIC}",
                    headers={
                        "Title": nudge.title,
                        "Click": "https://food-tracker.fly.dev/symptom",
                        "Tags": "fork_and_knife",
                    },
                    data=nudge.message,
                    timeout=10,
                )
            except Exception:
                pass  # Non-critical; will retry next request
            else:
                nudge.sent = 1

        if due:
            db.commit()

        # Clean up old sent nudges (older than 24h)
        cutoff = now - timedelta(hours=24)
        db.query(PendingNudge).filter(
            PendingNudge.sent == 1,
            PendingNudge.fire_at < cutoff,
        ).delete()
        db.commit()
    except Exception:
        pass  # Don't let nudge processing break the request
    finally:
        db.close()


def _nudge_loop():
    """Background loop that checks for and sends due nudges every 30 seconds."""
    while True:
        try:
            send_due_nudges()
        except Exception:
            pass
        time.sleep(30)


def start_background_nudger():
    """Start the background nudge-checking thread (once per process)."""
    global _bg_thread_started
    if _bg_thread_started:
        return
    _bg_thread_started = True
    t = threading.Thread(target=_nudge_loop, daemon=True)
    t.start()
