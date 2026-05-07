"""Strava integration: refresh tokens, fetch today's activities, compute workout-based target adjustments."""

import json
import time
from datetime import datetime, time as dtime, timezone

import requests
from sqlalchemy import desc

from config import Config
from models import StravaActivityCache, StravaToken, get_session

CACHE_TTL_SECONDS = 30 * 60  # 30 minutes

# kcal per minute per kg of bodyweight (METs / 60).
# MET values from the Compendium of Physical Activities (Ainsworth et al.).
SPORT_TYPE_MET = {
    "Run": 9.8,
    "TrailRun": 10.0,
    "VirtualRun": 9.0,
    "Ride": 7.5,
    "VirtualRide": 7.0,
    "MountainBikeRide": 8.5,
    "GravelRide": 8.0,
    "EBikeRide": 4.0,
    "Walk": 3.5,
    "Hike": 6.0,
    "WeightTraining": 5.0,
    "Workout": 5.5,
    "Crossfit": 8.0,
    "Yoga": 2.5,
    "Pilates": 3.0,
    "Swim": 7.0,
    "Rowing": 7.0,
    "Elliptical": 5.0,
    "StairStepper": 8.0,
    "HighIntensityIntervalTraining": 9.0,
    "Soccer": 7.0,
    "Basketball": 6.5,
}
DEFAULT_MET = 5.0


def _seed_token_from_env(db):
    """First-run setup: copy initial refresh token from env into DB."""
    if not Config.STRAVA_INITIAL_REFRESH_TOKEN:
        return None
    token = StravaToken(
        access_token="",
        refresh_token=Config.STRAVA_INITIAL_REFRESH_TOKEN,
        expires_at=0,
    )
    db.add(token)
    db.commit()
    return token


def _get_current_token(db):
    """Return the most recent StravaToken row, seeding from env if none exists."""
    token = db.query(StravaToken).order_by(desc(StravaToken.id)).first()
    if token is None:
        token = _seed_token_from_env(db)
    return token


def _refresh_access_token(db, token):
    """Exchange refresh_token for a new access token. Persists rotated tokens."""
    if not Config.STRAVA_CLIENT_ID or not Config.STRAVA_CLIENT_SECRET:
        raise RuntimeError("STRAVA_ID and STRAVA_SECRET must be set in env")

    response = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": Config.STRAVA_CLIENT_ID,
            "client_secret": Config.STRAVA_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": token.refresh_token,
        },
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()

    token.access_token = payload["access_token"]
    token.refresh_token = payload["refresh_token"]
    token.expires_at = int(payload["expires_at"])
    token.updated_at = datetime.now(timezone.utc)
    db.commit()
    return token


def _ensure_valid_token(db):
    """Return a token guaranteed to be unexpired (with 60s buffer)."""
    token = _get_current_token(db)
    if token is None:
        return None
    if token.expires_at - 60 < int(time.time()):
        token = _refresh_access_token(db, token)
    return token


def _fetch_activities_after(access_token, after_unix):
    activities = []
    page = 1
    while True:
        response = requests.get(
            "https://www.strava.com/api/v3/athlete/activities",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"per_page": 100, "page": page, "after": after_unix},
            timeout=15,
        )
        response.raise_for_status()
        batch = response.json()
        if not batch:
            break
        activities.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return activities


def _start_of_today_unix():
    """Unix timestamp for the start of the current local day."""
    now_local = datetime.now().astimezone()
    midnight = datetime.combine(now_local.date(), dtime.min, tzinfo=now_local.tzinfo)
    return int(midnight.timestamp())


def get_todays_activities(force_refresh=False):
    """Return today's Strava activities (cached for 30 min unless force_refresh).

    Returns a list of dicts: [{sport_type, elapsed_time, distance, start_date_local, name}, ...]
    Returns [] if Strava is not configured or the API call fails.
    """
    db = get_session()
    try:
        if not force_refresh:
            cache = (
                db.query(StravaActivityCache)
                .order_by(desc(StravaActivityCache.id))
                .first()
            )
            if cache is not None:
                age = (datetime.now(timezone.utc) - cache.fetched_at.replace(tzinfo=timezone.utc)).total_seconds()
                cached_date = cache.fetched_at.date()
                today = datetime.now().astimezone().date()
                if age < CACHE_TTL_SECONDS and cached_date == today:
                    return json.loads(cache.activities_json)

        token = _ensure_valid_token(db)
        if token is None:
            return []

        try:
            raw = _fetch_activities_after(token.access_token, _start_of_today_unix())
        except Exception as exc:
            print(f"Strava fetch failed: {exc}")
            return []

        activities = [
            {
                "sport_type": a.get("sport_type") or a.get("type"),
                "elapsed_time": a.get("elapsed_time", 0),
                "moving_time": a.get("moving_time", 0),
                "distance": a.get("distance", 0),  # meters
                "start_date_local": a.get("start_date_local"),
                "name": a.get("name", ""),
            }
            for a in raw
        ]

        db.add(StravaActivityCache(
            fetched_at=datetime.now(timezone.utc),
            activities_json=json.dumps(activities),
        ))
        db.commit()
        return activities
    finally:
        db.close()


def workout_adjustment(activities, weight_kg=None):
    """Compute extra calories/protein/carbs for today's workouts.

    Uses moving_time (actual exertion) when available, falling back to elapsed_time.
    Returns dict: {calories, protein, carbs, summary}
    """
    if weight_kg is None:
        weight_kg = Config.USER_WEIGHT_KG

    extra_kcal = 0.0
    summary_parts = []
    for a in activities:
        seconds = a.get("moving_time") or a.get("elapsed_time") or 0
        if seconds <= 0:
            continue
        minutes = seconds / 60.0
        sport = a.get("sport_type") or "Workout"
        met = SPORT_TYPE_MET.get(sport, DEFAULT_MET)
        kcal = met * weight_kg * (minutes / 60.0)
        extra_kcal += kcal

        # Build a compact human summary
        if sport in ("Run", "TrailRun", "VirtualRun") and a.get("distance"):
            miles = a["distance"] / 1609.34
            summary_parts.append(f"{miles:.1f}mi {sport.replace('Virtual','').replace('Trail','trail ')} ({int(minutes)} min)")
        else:
            summary_parts.append(f"{sport} ({int(minutes)} min)")

    extra_protein = round(extra_kcal * 0.15 / 4)  # 15% protein, 4 kcal/g
    extra_carbs = round(extra_kcal * 0.55 / 4)    # 55% carbs, 4 kcal/g

    return {
        "calories": round(extra_kcal),
        "protein": int(extra_protein),
        "carbs": int(extra_carbs),
        "summary": ", ".join(summary_parts) if summary_parts else "",
    }
