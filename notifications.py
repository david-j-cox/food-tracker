"""Ntfy push notification scheduling for post-meal symptom check-ins."""

import threading
from datetime import datetime, timedelta

import requests

from config import Config

NTFY_URL = "https://ntfy.sh"


def schedule_nudges(meal_slot: str, consumed_at: datetime, app_url: str = "https://food-tracker.fly.dev"):
    """Schedule push notifications at 10min and 90min after a meal.

    The 90-min nudge is skipped if it would fire after 10pm ET.
    """
    if not Config.NTFY_TOPIC:
        return

    now = datetime.now()
    meal_label = meal_slot.replace("-", " ")

    # 10-minute nudge
    delay_10 = max(0, (consumed_at + timedelta(minutes=10) - now).total_seconds())
    threading.Timer(delay_10, _send_nudge, args=[
        f"Quick check after {meal_label}",
        f"How are you feeling? Tap to log any symptoms.",
        f"{app_url}/symptom",
    ]).start()

    # 90-minute nudge (skip if it would land after 10pm)
    fire_time_90 = consumed_at + timedelta(minutes=90)
    if fire_time_90.hour < 22:  # Before 10pm
        delay_90 = max(0, (fire_time_90 - now).total_seconds())
        threading.Timer(delay_90, _send_nudge, args=[
            f"How's digestion after {meal_label}?",
            f"It's been 90 minutes. Tap to log how you're feeling.",
            f"{app_url}/symptom",
        ]).start()


def _send_nudge(title: str, message: str, click_url: str):
    """Send a push notification via ntfy.sh."""
    try:
        requests.post(
            f"{NTFY_URL}/{Config.NTFY_TOPIC}",
            headers={
                "Title": title,
                "Click": click_url,
                "Tags": "fork_and_knife",
            },
            data=message,
            timeout=10,
        )
    except Exception:
        pass  # Notification failure is non-critical
