#!/usr/bin/env python
"""Food Tracker — mobile-first food & symptom logging app."""

import functools
import html
import json
import os
import tempfile
import traceback
import uuid
from datetime import datetime, timezone

from flask import Flask, redirect, request, session, url_for, jsonify
from sqlalchemy import func

from config import Config
from models import (
    FoodItem, FoodEntry, FoodTag, SymptomEntry, SymptomTag,
    init_db, get_session,
)
from claude_client import (
    identify_food, extract_label, describe_serving_size,
    generate_clarifying_questions, refine_estimate,
    generate_initial_questions, identify_from_answers,
    search_web_nutrition, estimate_with_context,
    suggest_snack, parse_description_to_ingredients,
)
from usda_client import search_foods, get_food_nutrients, get_food_per_gram
from notifications import schedule_nudges, start_background_nudger

# ---------------------------------------------------------------------------
# Daily nutrient targets
# ---------------------------------------------------------------------------
DAILY_TARGETS = {
    "calories": 2450,
    "fat": 82,
    "saturated_fat": 27,
    "protein": 135,
    "carbs": 340,
    "fiber": 38,
    "sugar": 50,
    "sodium": 2300,
    "iron": 8,
    "calcium": 1000,
    "magnesium": 420,
    "potassium": 3400,
    "vitamin_b12": 2.4,
    "vitamin_d": 15,
}

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = Config.SECRET_KEY
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 30  # 30 days

# Create tables on startup
with app.app_context():
    init_db()

# Start background thread to send nudge notifications
start_background_nudger()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MEAL_SLOTS = ["breakfast", "lunch", "dinner", "snack", "pre-run", "post-run"]

NUTRIENT_FIELDS = [
    ("calories", "Calories", "kcal"),
    ("total_fat_g", "Total Fat", "g"),
    ("saturated_fat_g", "Saturated Fat", "g"),
    ("protein_g", "Protein", "g"),
    ("carbohydrates_g", "Carbs", "g"),
    ("fiber_g", "Fiber", "g"),
    ("sugar_g", "Sugar", "g"),
    ("sodium_mg", "Sodium", "mg"),
    ("iron_mg", "Iron", "mg"),
    ("calcium_mg", "Calcium", "mg"),
    ("magnesium_mg", "Magnesium", "mg"),
    ("potassium_mg", "Potassium", "mg"),
    ("vitamin_b12_mcg", "Vitamin B12", "mcg"),
    ("vitamin_d_mcg", "Vitamin D", "mcg"),
]

SEED_SYMPTOM_TAGS = {
    "Digestive": [
        "bloating", "nausea", "diarrhea", "urgency",
        "cramping", "acid_reflux", "gas", "fatty_stool",
    ],
    "General": ["fatigue", "brain_fog", "headache"],
    "Positive": ["felt_great", "high_energy", "good_digestion"],
}

# ---------------------------------------------------------------------------
# Inline HTML helpers
# ---------------------------------------------------------------------------
STYLE = """
<style>
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    max-width: 600px; margin: 0 auto; padding: 16px;
    background: #f5f5f5; color: #1a1a1a;
  }
  h2 { margin-top: 0; font-size: 1.4em; }
  h3 { margin-top: 0; font-size: 1.1em; color: #555; }

  .card {
    background: #fff; border-radius: 12px; padding: 20px;
    box-shadow: 0 1px 3px rgba(0,0,0,.1); margin-bottom: 16px;
  }

  .btn {
    display: block; width: 100%; padding: 14px 20px;
    border: none; border-radius: 8px; cursor: pointer;
    font-size: 1em; font-weight: 600; text-align: center;
    text-decoration: none; margin-bottom: 10px;
    min-height: 48px;
  }
  .btn-primary { background: #2563eb; color: #fff; }
  .btn-secondary { background: #e5e7eb; color: #333; }
  .btn-success { background: #16a34a; color: #fff; }
  .btn-danger { background: #dc2626; color: #fff; }
  .btn:hover { opacity: 0.9; }

  .btn-grid {
    display: grid; grid-template-columns: 1fr 1fr;
    gap: 10px; margin-bottom: 16px;
  }
  .btn-grid .btn { margin-bottom: 0; }

  input, select, textarea {
    width: 100%; padding: 12px; border: 1px solid #d1d5db;
    border-radius: 8px; font-size: 1em; margin-bottom: 12px;
    min-height: 44px;
  }
  input:focus, select:focus, textarea:focus {
    outline: none; border-color: #2563eb; box-shadow: 0 0 0 2px rgba(37,99,235,.2);
  }
  textarea { resize: vertical; min-height: 80px; }

  label {
    display: block; font-weight: 600; margin-bottom: 4px;
    font-size: 0.9em; color: #555;
  }
  .field { margin-bottom: 12px; }

  .nutrient-grid {
    display: grid; grid-template-columns: 1fr 1fr; gap: 8px;
  }
  .nutrient-grid .field { margin-bottom: 4px; }
  .nutrient-grid label { font-size: 0.8em; }
  .nutrient-grid input { padding: 8px; margin-bottom: 0; font-size: 0.9em; }

  .tag-group { margin-bottom: 16px; }
  .tag-group h3 { margin-bottom: 8px; }
  .tag-chips { display: flex; flex-wrap: wrap; gap: 8px; }
  .tag-chip {
    display: inline-block; padding: 8px 14px;
    border: 2px solid #d1d5db; border-radius: 20px;
    cursor: pointer; font-size: 0.9em; user-select: none;
    min-height: 44px; line-height: 28px;
  }
  .tag-chip.selected { border-color: #2563eb; background: #eff6ff; color: #2563eb; }

  .severity-row {
    display: none; align-items: center; gap: 8px;
    margin-top: 6px; padding: 8px 12px;
    background: #f9fafb; border-radius: 8px;
  }
  .severity-row.visible { display: flex; }
  .severity-btn {
    width: 36px; height: 36px; border: 2px solid #d1d5db;
    border-radius: 50%; background: #fff; cursor: pointer;
    font-weight: 600; font-size: 0.9em;
  }
  .severity-btn.active { border-color: #2563eb; background: #2563eb; color: #fff; }

  .meal-grid {
    display: grid; grid-template-columns: 1fr 1fr 1fr;
    gap: 8px; margin-bottom: 12px;
  }
  .meal-option {
    padding: 10px; border: 2px solid #d1d5db; border-radius: 8px;
    text-align: center; cursor: pointer; font-size: 0.9em;
    min-height: 44px; line-height: 24px;
  }
  .meal-option.selected { border-color: #2563eb; background: #eff6ff; }

  .entry-item {
    padding: 10px 0; border-bottom: 1px solid #f0f0f0;
    font-size: 0.9em;
  }
  .entry-item:last-child { border-bottom: none; }
  .entry-meta { color: #888; font-size: 0.8em; }

  .totals {
    display: grid; grid-template-columns: 1fr 1fr;
    gap: 8px; text-align: center;
  }
  .total-box {
    background: #f9fafb; border-radius: 8px; padding: 10px 8px;
  }
  .total-val { font-size: 1.1em; font-weight: 700; color: #2563eb; }
  .total-label { font-size: 0.7em; color: #888; margin-bottom: 6px; }
  .progress-wrap {
    background: #e5e7eb; border-radius: 4px; height: 6px;
    margin-top: 4px; overflow: hidden;
  }
  .progress-bar {
    height: 100%; border-radius: 4px; background: #2563eb;
    transition: width 0.3s ease;
  }
  .progress-bar.near-target { background: #16a34a; }
  .progress-bar.over-target { background: #f59e0b; }

  .micro-toggle {
    display: flex; align-items: center; justify-content: space-between;
    cursor: pointer; user-select: none; padding: 4px 0;
  }
  .micro-toggle h3 { margin: 0; }
  .micro-chevron {
    font-size: 0.8em; color: #888;
    transition: transform 0.2s ease;
  }
  .micro-chevron.open { transform: rotate(180deg); }
  .micro-section {
    display: none; margin-top: 10px;
  }
  .micro-section.open { display: block; }

  .flash { background: #d1fae5; border: 1px solid #6ee7b7;
    border-radius: 8px; padding: 12px; margin-bottom: 16px;
    color: #065f46; text-align: center; }

  .back-link {
    display: inline-block; margin-bottom: 12px;
    color: #2563eb; text-decoration: none; font-size: 0.9em;
  }

  .snack-nutrient {
    background: #e5e7eb; border-radius: 4px; padding: 2px 8px;
    font-size: 0.8em; color: #333; white-space: nowrap;
  }

  .trend-grid {
    display: grid; grid-template-columns: 1fr 1fr;
    gap: 10px;
  }
  .trend-box {
    background: #f9fafb; border-radius: 8px; padding: 10px 8px;
  }
</style>
"""


def page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Food Tracker</title>
{STYLE}
</head><body>{body}</body></html>"""


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("authed"):
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return wrapper


def api_key_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        key = request.headers.get("X-API-Key", "")
        if key != Config.FOOD_TRACKER_API_KEY:
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _parse_float(val, default=None):
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _save_food_entry(db, food_item, meal_slot, quantity, consumed_at, notes, tags):
    """Save a food item + entry + tags. Returns the FoodEntry."""
    db.add(food_item)
    db.flush()

    entry = FoodEntry(
        food_item_id=food_item.id,
        meal_slot=meal_slot,
        quantity=quantity,
        consumed_at=consumed_at,
        notes=notes or None,
    )
    db.add(entry)

    for tag_name in tags:
        tag_name = tag_name.strip().lower()
        if tag_name:
            db.add(FoodTag(food_item_id=food_item.id, tag=tag_name))

    db.commit()

    # Schedule post-meal symptom check-in notifications
    try:
        schedule_nudges(meal_slot, consumed_at)
    except Exception:
        pass  # Notification scheduling failure is non-critical

    return entry


def _estimate_from_description(description: str) -> dict:
    """Estimate nutrients for a free-text food description.

    Parses the description into ingredients via Claude, then uses USDA as
    ground truth per ingredient where available, falling back to Claude's
    per-portion estimate. Returns a dict with:
        estimated_nutrients: dict of col -> value (or None)
        ingredients: list of per-ingredient rows with source provenance
        data_source: human summary like "USDA (3/4 ingredients)"
    """
    ingredients = parse_description_to_ingredients(description)

    cols = [f[0] for f in NUTRIENT_FIELDS]
    totals = {col: 0.0 for col in cols}
    has_data = {col: False for col in cols}
    per_ingredient = []
    usda_hits = 0

    for ing in ingredients:
        grams = _parse_float(ing.get("grams"), 0.0) or 0.0
        fallback = ing.get("fallback_nutrients") or {}
        usda_query = (ing.get("usda_query") or "").strip()

        source = "ai-estimate"
        usda_match = None
        ing_nutrients = {col: _parse_float(fallback.get(col)) for col in cols}

        if usda_query and grams > 0:
            try:
                hits = search_foods(usda_query, limit=3)
                per_gram = None
                for hit in hits:
                    per_gram = get_food_per_gram(hit["fdc_id"])
                    if per_gram:
                        usda_match = hit["description"]
                        break
                if per_gram:
                    source = "usda"
                    usda_hits += 1
                    ing_nutrients = {
                        col: (per_gram[col] * grams if per_gram.get(col) is not None else None)
                        for col in cols
                    }
            except Exception:
                traceback.print_exc()

        for col in cols:
            v = ing_nutrients.get(col)
            if v is not None:
                totals[col] += v
                has_data[col] = True

        per_ingredient.append({
            "name": ing.get("name", ""),
            "amount": ing.get("amount", ""),
            "grams": grams,
            "source": source,
            "usda_match": usda_match,
        })

    rounded = {col: (round(totals[col], 2) if has_data[col] else None) for col in cols}
    n = len(ingredients)
    if n == 0:
        data_source = "none"
    else:
        data_source = f"USDA ({usda_hits}/{n} ingredients)"

    return {
        "estimated_nutrients": rounded,
        "ingredients": per_ingredient,
        "data_source": data_source,
    }


def _today_entries(db):
    """Return today's food entries and symptom entries."""
    from datetime import date
    today = date.today()

    food = (
        db.query(FoodEntry, FoodItem)
        .join(FoodItem)
        .filter(func.date(FoodEntry.consumed_at) == today)
        .order_by(FoodEntry.consumed_at.desc())
        .all()
    )

    symptoms = (
        db.query(SymptomEntry)
        .filter(func.date(SymptomEntry.logged_at) == today)
        .order_by(SymptomEntry.logged_at.desc())
        .all()
    )

    return food, symptoms


def _daily_totals(food_entries):
    """Sum up today's macro and micro nutrients from food entries."""
    totals = {
        "calories": 0, "fat": 0, "saturated_fat": 0, "protein": 0,
        "carbs": 0, "fiber": 0, "sugar": 0, "sodium": 0,
        "iron": 0, "calcium": 0, "magnesium": 0, "potassium": 0,
        "vitamin_b12": 0, "vitamin_d": 0,
    }
    for entry, item in food_entries:
        q = float(entry.quantity or 1)
        totals["calories"] += float(item.calories or 0) * q
        totals["fat"] += float(item.total_fat_g or 0) * q
        totals["saturated_fat"] += float(item.saturated_fat_g or 0) * q
        totals["protein"] += float(item.protein_g or 0) * q
        totals["carbs"] += float(item.carbohydrates_g or 0) * q
        totals["fiber"] += float(item.fiber_g or 0) * q
        totals["sugar"] += float(item.sugar_g or 0) * q
        totals["sodium"] += float(item.sodium_mg or 0) * q
        totals["iron"] += float(item.iron_mg or 0) * q
        totals["calcium"] += float(item.calcium_mg or 0) * q
        totals["magnesium"] += float(item.magnesium_mg or 0) * q
        totals["potassium"] += float(item.potassium_mg or 0) * q
        totals["vitamin_b12"] += float(item.vitamin_b12_mcg or 0) * q
        totals["vitamin_d"] += float(item.vitamin_d_mcg or 0) * q
    return totals


def _progress_box(label, current, target, unit=""):
    """Render a single nutrient box with progress bar."""
    pct = min((current / target) * 100, 100) if target else 0
    bar_class = "progress-bar"
    if pct >= 100:
        bar_class += " over-target"
    elif pct >= 80:
        bar_class += " near-target"
    cur_display = f"{current:.1f}" if current < 10 and current != int(current) else str(int(current))
    return f"""<div class="total-box">
        <div class="total-label">{label}</div>
        <div class="total-val">{cur_display}{unit} <span style="font-size:0.6em;font-weight:400;color:#888">/ {int(target) if target == int(target) else target}{unit}</span></div>
        <div class="progress-wrap"><div class="{bar_class}" style="width:{pct:.0f}%"></div></div>
    </div>"""


def _render_food_list(food_entries):
    """Render today's food entries as HTML."""
    if not food_entries:
        return '<p style="color:#888; text-align:center;">No food logged yet today.</p>'
    rows = ""
    for entry, item in food_entries:
        qty = f" x{entry.quantity}" if float(entry.quantity or 1) != 1.0 else ""
        time_str = entry.consumed_at.strftime("%-I:%M %p") if entry.consumed_at else ""
        cal = int(float(item.calories or 0) * float(entry.quantity or 1))
        rows += f"""<a href="/edit/{entry.id}" class="entry-item" style="display:block; text-decoration:none; color:inherit;">
            <strong>{item.name}</strong>{qty}
            <span style="float:right">{cal} kcal</span><br>
            <span class="entry-meta">{entry.meal_slot} &middot; {time_str} &middot; <span style="color:#2563eb;">tap to edit</span></span>
        </a>"""
    return rows


def _render_symptom_list(symptom_entries):
    """Render today's symptom entries as HTML."""
    if not symptom_entries:
        return '<p style="color:#888; text-align:center;">No symptoms logged today.</p>'
    rows = ""
    for se in symptom_entries:
        time_str = se.logged_at.strftime("%-I:%M %p") if se.logged_at else ""
        tag_strs = [f"{t.tag} ({t.severity}/5)" for t in se.tags]
        rows += f"""<div class="entry-item">
            <strong>{", ".join(tag_strs)}</strong>
            <span style="float:right">{time_str}</span>
            {"<br><span class='entry-meta'>" + se.notes + "</span>" if se.notes else ""}
        </div>"""
    return rows


# ---------------------------------------------------------------------------
# Routes: Auth
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    if session.get("authed"):
        return redirect(url_for("home"))

    body = f"""
    <div class="card" style="margin-top: 40px;">
        <h2>Food Tracker</h2>
        <form method="post" action="/login">
            <div class="field">
                <label for="pin">Enter PIN</label>
                <input type="password" id="pin" name="pin"
                       inputmode="numeric" autocomplete="off" autofocus>
            </div>
            <button class="btn btn-primary" type="submit">Log In</button>
        </form>
    </div>"""
    return page("Login", body)


@app.route("/login", methods=["POST"])
def login():
    pin = request.form.get("pin", "")
    if pin == Config.FOOD_TRACKER_PIN:
        session.permanent = True
        session["authed"] = True
        return redirect(url_for("home"))
    body = """
    <div class="card" style="margin-top: 40px;">
        <h2>Food Tracker</h2>
        <p style="color: #dc2626; text-align: center;">Incorrect PIN. Try again.</p>
        <form method="post" action="/login">
            <div class="field">
                <label for="pin">Enter PIN</label>
                <input type="password" id="pin" name="pin"
                       inputmode="numeric" autocomplete="off" autofocus>
            </div>
            <button class="btn btn-primary" type="submit">Log In</button>
        </form>
    </div>"""
    return page("Login", body)


# ---------------------------------------------------------------------------
# Routes: Home
# ---------------------------------------------------------------------------
@app.route("/home")
@login_required
def home():
    db = get_session()
    try:
        food, symptoms = _today_entries(db)
        totals = _daily_totals(food)

        flash_msg = ""
        if request.args.get("saved"):
            flash_msg = '<div class="flash">Entry saved!</div>'

        body = f"""
        {flash_msg}
        <div class="card">
            <h2>Food Tracker</h2>
            <div class="btn-grid">
                <a class="btn btn-primary" href="/scan/food">Scan Food</a>
                <a class="btn btn-primary" href="/scan/label">Scan Label</a>
                <a class="btn btn-secondary" href="/quick">Quick Add</a>
                <a class="btn btn-success" href="/symptom">Log Symptom</a>
                <a class="btn btn-secondary" href="/describe">Describe Food</a>
                <a class="btn btn-success" href="/suggest-snack">Suggest a Snack</a>
            </div>
            <a class="btn btn-primary" href="/trends">Trends</a>
        </div>

        <div class="card">
            <h3>Today's Totals</h3>
            <div class="totals">
                {_progress_box("Calories", totals['calories'], DAILY_TARGETS['calories'], "kcal")}
                {_progress_box("Protein", totals['protein'], DAILY_TARGETS['protein'], "g")}
                {_progress_box("Carbs", totals['carbs'], DAILY_TARGETS['carbs'], "g")}
                {_progress_box("Fat", totals['fat'], DAILY_TARGETS['fat'], "g")}
                {_progress_box("Sat Fat", totals['saturated_fat'], DAILY_TARGETS['saturated_fat'], "g")}
                {_progress_box("Fiber", totals['fiber'], DAILY_TARGETS['fiber'], "g")}
                {_progress_box("Sugar", totals['sugar'], DAILY_TARGETS['sugar'], "g")}
                {_progress_box("Sodium", totals['sodium'], DAILY_TARGETS['sodium'], "mg")}
            </div>
            <div style="margin-top: 12px;">
                <div class="micro-toggle" onclick="document.getElementById('micro-section').classList.toggle('open'); document.getElementById('micro-chevron').classList.toggle('open');">
                    <h3>Micronutrients</h3>
                    <span id="micro-chevron" class="micro-chevron">&#9660;</span>
                </div>
                <div id="micro-section" class="micro-section">
                    <div class="totals">
                        {_progress_box("Iron", totals['iron'], DAILY_TARGETS['iron'], "mg")}
                        {_progress_box("Calcium", totals['calcium'], DAILY_TARGETS['calcium'], "mg")}
                        {_progress_box("Magnesium", totals['magnesium'], DAILY_TARGETS['magnesium'], "mg")}
                        {_progress_box("Potassium", totals['potassium'], DAILY_TARGETS['potassium'], "mg")}
                        {_progress_box("Vitamin B12", totals['vitamin_b12'], DAILY_TARGETS['vitamin_b12'], "mcg")}
                        {_progress_box("Vitamin D", totals['vitamin_d'], DAILY_TARGETS['vitamin_d'], "mcg")}
                    </div>
                </div>
            </div>
        </div>

        <div class="card">
            <h3>Food Log</h3>
            {_render_food_list(food)}
        </div>

        <div class="card">
            <h3>Symptoms</h3>
            {_render_symptom_list(symptoms)}
        </div>"""
        return page("Home", body)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Routes: Suggest a snack
# ---------------------------------------------------------------------------
@app.route("/suggest-snack")
@login_required
def suggest_snack_page():
    db = get_session()
    try:
        food, _ = _today_entries(db)
        totals = _daily_totals(food)
        suggestions = suggest_snack(totals, DAILY_TARGETS)

        cards_html = ""
        for s in suggestions:
            nutrients = s.get("estimated_nutrients", {})
            nutrient_tags = []
            for key, val in nutrients.items():
                if val:
                    label = key.replace("_", " ").title()
                    unit = "kcal" if key == "calories" else ("mg" if key in ("iron", "calcium", "magnesium", "potassium") else ("mcg" if key.startswith("vitamin") else "g"))
                    nutrient_tags.append(f'<span class="snack-nutrient">{label}: {val}{unit}</span>')

            safe_name = html.escape(s.get("name", ""))
            safe_reason = html.escape(s.get("reason", ""))
            cards_html += f"""
            <div class="card">
                <h3 style="margin-bottom: 4px;">{safe_name}</h3>
                <p style="color: #555; font-size: 0.9em; margin-top: 4px;">{safe_reason}</p>
                <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px;">
                    {''.join(nutrient_tags)}
                </div>
                <form method="post" action="/suggest-snack/refine" style="margin-top: 12px;">
                    <input type="hidden" name="description" value="{safe_name}">
                    <button class="btn btn-primary" type="submit" style="width: 100%;">Use this</button>
                </form>
            </div>"""

        body = f"""
        <a class="back-link" href="/home">&larr; Home</a>
        <div class="card">
            <h2>Snack Suggestions</h2>
            <p style="color: #555; font-size: 0.9em;">Based on your nutrient gaps for today</p>
        </div>
        {cards_html}
        <a class="btn btn-secondary" href="/suggest-snack">Refresh Suggestions</a>
        """
        return page("Suggest a Snack", body)
    finally:
        db.close()


@app.route("/suggest-snack/refine", methods=["POST"])
@login_required
def refine_snack_page():
    """Render an editable form for a snack suggestion.

    The user can edit the description, re-estimate nutrients via USDA, and
    tweak any field before saving.
    """
    description = request.form.get("description", "").strip()
    if not description:
        return redirect(url_for("suggest_snack_page"))

    safe_desc = html.escape(description)

    nutrient_rows = ""
    for field_name, display, unit in NUTRIENT_FIELDS:
        nutrient_rows += f"""
        <div class="field" style="display: flex; align-items: center; gap: 8px;">
            <label for="{field_name}" style="flex: 1; margin: 0;">{display} ({unit})</label>
            <input type="number" step="any" id="{field_name}" name="{field_name}"
                   style="width: 110px;" inputmode="decimal">
        </div>"""

    meal_options = ""
    for slot in MEAL_SLOTS:
        label = slot.replace("-", " ").title()
        sel = "selected" if slot == "snack" else ""
        meal_options += f"""<div class="meal-option {sel}" onclick="selectMeal(this, '{slot}')">{label}</div>"""

    body = f"""
    <a class="back-link" href="/suggest-snack">&larr; Suggestions</a>
    <div class="card">
        <h2>Refine Snack</h2>
        <p style="color:#555; font-size: 0.9em;">Edit the description, then re-estimate nutrients using USDA data.</p>

        <form method="post" action="/suggest-snack/refine/save" id="refine-form">
            <div class="field">
                <label for="description">Description</label>
                <textarea id="description" name="description" rows="3"
                    placeholder="e.g. 1 cup Greek yogurt with 1 tbsp pumpkin seeds">{safe_desc}</textarea>
            </div>

            <button type="button" class="btn btn-secondary" onclick="reestimate()" id="reest-btn"
                    style="width: 100%; margin-bottom: 12px;">Re-estimate nutrients</button>

            <div id="ingredients-box" style="display:none; background:#eff6ff; border:1px solid #bfdbfe;
                 border-radius:8px; padding:10px 14px; margin-bottom:12px; font-size:0.85em;"></div>

            <div class="field">
                <label>Meal</label>
                <div class="meal-grid">{meal_options}</div>
                <input type="hidden" name="meal_slot" id="meal_slot" value="snack">
            </div>
            <div class="field">
                <label for="quantity">Quantity (servings)</label>
                <input type="number" step="any" id="quantity" name="quantity"
                       value="1" min="0.1" inputmode="decimal">
            </div>
            <div class="field">
                <label for="consumed_at">When?</label>
                <input type="datetime-local" id="consumed_at" name="consumed_at">
            </div>

            <h3>Nutrients (per serving)</h3>
            <p style="color:#888; font-size:0.8em; margin-top: -4px;">
                Click Re-estimate to fill these in, or edit manually.
            </p>
            {nutrient_rows}

            <input type="hidden" name="data_source" id="data_source" value="ai-estimate">

            <button class="btn btn-primary" type="submit" style="margin-top: 12px;">Save</button>
        </form>
    </div>

    <script>
    (function() {{
        var now = new Date();
        now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
        document.getElementById('consumed_at').value = now.toISOString().slice(0, 16);
    }})();

    function selectMeal(el, slot) {{
        document.querySelectorAll('.meal-option').forEach(e => e.classList.remove('selected'));
        el.classList.add('selected');
        document.getElementById('meal_slot').value = slot;
    }}

    var NUTRIENT_COLS = {json.dumps([f[0] for f in NUTRIENT_FIELDS])};

    function escapeHtml(s) {{
        if (s == null) return '';
        return String(s).replace(/[&<>"']/g, function(c) {{
            return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c];
        }});
    }}

    function reestimate() {{
        var desc = document.getElementById('description').value.trim();
        if (!desc) return;
        var btn = document.getElementById('reest-btn');
        btn.disabled = true;
        btn.textContent = 'Estimating...';
        fetch('/api/estimate-from-text', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{description: desc}})
        }})
        .then(r => r.json())
        .then(function(data) {{
            if (data.error) {{
                alert('Error: ' + data.error);
                return;
            }}
            var nutrients = data.estimated_nutrients || {{}};
            NUTRIENT_COLS.forEach(function(col) {{
                var val = nutrients[col];
                document.getElementById(col).value = (val != null) ? val : '';
            }});
            document.getElementById('data_source').value = data.data_source || 'ai-estimate';
            var box = document.getElementById('ingredients-box');
            var rows = (data.ingredients || []).map(function(ing) {{
                var tag = ing.source === 'usda'
                    ? '<span style="color:#065f46; background:#d1fae5; padding:1px 6px; border-radius:4px; font-size:0.8em;">USDA</span>'
                    : '<span style="color:#92400e; background:#fef3c7; padding:1px 6px; border-radius:4px; font-size:0.8em;">AI estimate</span>';
                var match = ing.usda_match ? ' <span style="color:#888;">(' + escapeHtml(ing.usda_match) + ')</span>' : '';
                return '<div style="margin: 4px 0;">' + tag + ' <strong>' + escapeHtml(ing.name) + '</strong> — ' + escapeHtml(ing.amount) + match + '</div>';
            }}).join('');
            box.innerHTML = '<div style="font-weight:600; color:#1e40af; margin-bottom:4px;">' + escapeHtml(data.data_source || '') + '</div>' + rows;
            box.style.display = 'block';
        }})
        .catch(function(e) {{ alert('Estimate failed: ' + e); }})
        .finally(function() {{
            btn.disabled = false;
            btn.textContent = 'Re-estimate nutrients';
        }});
    }}
    </script>"""
    return page("Refine Snack", body)


@app.route("/api/estimate-from-text", methods=["POST"])
@login_required
def estimate_from_text_api():
    """Return aggregated nutrient estimate for a free-text food description."""
    data = request.get_json(silent=True) or {}
    description = (data.get("description") or "").strip()
    if not description:
        return jsonify({"error": "description is required"}), 400
    try:
        return jsonify(_estimate_from_description(description))
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/suggest-snack/refine/save", methods=["POST"])
@login_required
def refine_snack_save():
    db = get_session()
    try:
        description = request.form.get("description", "").strip()
        if not description:
            return redirect(url_for("suggest_snack_page"))

        consumed_at_str = request.form.get("consumed_at", "")
        consumed_at = (
            datetime.fromisoformat(consumed_at_str)
            if consumed_at_str
            else datetime.now()
        )

        data_source = request.form.get("data_source", "ai-estimate")
        source_tag = "usda" if data_source.startswith("USDA") else "ai-estimate"

        food_item = FoodItem(
            name=description,
            source=source_tag,
        )
        for field_name, _, _ in NUTRIENT_FIELDS:
            setattr(food_item, field_name, _parse_float(request.form.get(field_name)))

        _save_food_entry(
            db=db,
            food_item=food_item,
            meal_slot=request.form.get("meal_slot", "snack"),
            quantity=_parse_float(request.form.get("quantity"), 1.0),
            consumed_at=consumed_at,
            notes=None,
            tags=[],
        )
        return redirect(url_for("home", saved=1))
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Routes: Nutrient trends
# ---------------------------------------------------------------------------
@app.route("/api/trends")
@login_required
def trends_api():
    """Return 7 days of daily nutrient totals as JSON."""
    from datetime import date, timedelta
    db = get_session()
    try:
        today = date.today()
        start = today - timedelta(days=6)
        entries = (
            db.query(FoodEntry, FoodItem)
            .join(FoodItem)
            .filter(func.date(FoodEntry.consumed_at) >= start)
            .all()
        )
        # Group by date
        by_date = {}
        for entry, item in entries:
            d = entry.consumed_at.date().isoformat()
            by_date.setdefault(d, []).append((entry, item))

        dates = [(start + timedelta(days=i)).isoformat() for i in range(7)]
        nutrients = {key: [] for key in DAILY_TARGETS}
        for d in dates:
            totals = _daily_totals(by_date.get(d, []))
            for key in DAILY_TARGETS:
                nutrients[key].append(round(totals[key], 1))

        return jsonify({"dates": dates, "nutrients": nutrients, "targets": DAILY_TARGETS})
    finally:
        db.close()


TREND_MACROS = [
    ("calories", "Calories", "kcal"),
    ("protein", "Protein", "g"),
    ("carbs", "Carbs", "g"),
    ("fat", "Fat", "g"),
    ("saturated_fat", "Sat Fat", "g"),
    ("fiber", "Fiber", "g"),
    ("sugar", "Sugar", "g"),
    ("sodium", "Sodium", "mg"),
]

TREND_MICROS = [
    ("iron", "Iron", "mg"),
    ("calcium", "Calcium", "mg"),
    ("magnesium", "Magnesium", "mg"),
    ("potassium", "Potassium", "mg"),
    ("vitamin_b12", "Vitamin B12", "mcg"),
    ("vitamin_d", "Vitamin D", "mcg"),
]


@app.route("/trends")
@login_required
def trends_page():
    def _chart_canvas(nutrient_key, label, unit):
        return f'<div class="trend-box"><canvas id="chart-{nutrient_key}" data-key="{nutrient_key}" data-label="{label}" data-unit="{unit}"></canvas></div>'

    macro_charts = "\n".join(_chart_canvas(k, l, u) for k, l, u in TREND_MACROS)
    micro_charts = "\n".join(_chart_canvas(k, l, u) for k, l, u in TREND_MICROS)

    body = f"""
    <a class="back-link" href="/home">&larr; Home</a>
    <div class="card">
        <h2>7-Day Trends</h2>
        <div class="trend-grid">
            {macro_charts}
        </div>
        <h3 style="margin-top: 16px;">Micronutrients</h3>
        <div class="trend-grid">
            {micro_charts}
        </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
    <script>
    fetch('/api/trends')
      .then(r => r.json())
      .then(data => {{
        const shortDates = data.dates.map(d => {{
          const parts = d.split('-');
          return parts[1] + '/' + parts[2];
        }});
        document.querySelectorAll('.trend-box canvas').forEach(canvas => {{
          const key = canvas.dataset.key;
          const label = canvas.dataset.label;
          const unit = canvas.dataset.unit;
          const target = data.targets[key];
          const values = data.nutrients[key];
          new Chart(canvas, {{
            type: 'line',
            data: {{
              labels: shortDates,
              datasets: [
                {{
                  label: label + ' (' + unit + ')',
                  data: values,
                  borderColor: '#2563eb',
                  backgroundColor: 'rgba(37,99,235,0.1)',
                  fill: true,
                  tension: 0.3,
                  pointRadius: 4,
                  pointBackgroundColor: '#2563eb',
                }},
                {{
                  label: 'Target',
                  data: Array(7).fill(target),
                  borderColor: '#f59e0b',
                  borderDash: [6, 4],
                  borderWidth: 2,
                  pointRadius: 0,
                  fill: false,
                }}
              ]
            }},
            options: {{
              responsive: true,
              plugins: {{
                legend: {{ display: false }},
                title: {{
                  display: true,
                  text: label + ' (' + unit + ')',
                  font: {{ size: 13, weight: '600' }},
                  color: '#555',
                  padding: {{ bottom: 8 }}
                }}
              }},
              scales: {{
                y: {{
                  beginAtZero: true,
                  grid: {{ color: '#f0f0f0' }},
                  ticks: {{ font: {{ size: 10 }} }}
                }},
                x: {{
                  grid: {{ display: false }},
                  ticks: {{ font: {{ size: 10 }} }}
                }}
              }}
            }}
          }});
        }});
      }});
    </script>
    """
    return page("Trends", body)


# ---------------------------------------------------------------------------
# Routes: Describe food (text → estimated nutrients)
# ---------------------------------------------------------------------------
@app.route("/describe", methods=["GET"])
@login_required
def describe_food_form():
    nutrient_rows = ""
    for field_name, display, unit in NUTRIENT_FIELDS:
        nutrient_rows += f"""
        <div class="field" style="display: flex; align-items: center; gap: 8px;">
            <label for="{field_name}" style="flex: 1; margin: 0;">{display} ({unit})</label>
            <input type="number" step="any" id="{field_name}" name="{field_name}"
                   style="width: 110px;" inputmode="decimal">
        </div>"""

    meal_options = ""
    for slot in MEAL_SLOTS:
        label = slot.replace("-", " ").title()
        sel = "selected" if slot == "snack" else ""
        meal_options += f"""<div class="meal-option {sel}" onclick="selectMeal(this, '{slot}')">{label}</div>"""

    body = f"""
    <a class="back-link" href="/home">&larr; Home</a>
    <div class="card">
        <h2>Describe Food</h2>
        <p style="color:#555; font-size: 0.9em;">Type what you ate and we'll look up the nutrition.</p>

        <form method="post" action="/describe/save" id="describe-form">
            <div class="field">
                <label for="description">Description</label>
                <textarea id="description" name="description" rows="3" required
                    placeholder="e.g. 2 scrambled eggs with 1 slice whole-wheat toast and butter"></textarea>
            </div>

            <button type="button" class="btn btn-primary" onclick="estimate()" id="est-btn"
                    style="width: 100%; margin-bottom: 12px;">Estimate nutrients</button>

            <div id="ingredients-box" style="display:none; background:#eff6ff; border:1px solid #bfdbfe;
                 border-radius:8px; padding:10px 14px; margin-bottom:12px; font-size:0.85em;"></div>

            <div id="details" style="display:none;">
                <div class="field">
                    <label>Meal</label>
                    <div class="meal-grid">{meal_options}</div>
                    <input type="hidden" name="meal_slot" id="meal_slot" value="snack">
                </div>
                <div class="field">
                    <label for="quantity">Quantity (servings)</label>
                    <input type="number" step="any" id="quantity" name="quantity"
                           value="1" min="0.1" inputmode="decimal">
                </div>
                <div class="field">
                    <label for="consumed_at">When?</label>
                    <input type="datetime-local" id="consumed_at" name="consumed_at">
                </div>

                <h3>Nutrients (per serving)</h3>
                <p style="color:#888; font-size:0.8em; margin-top: -4px;">
                    Edit any value you want to correct.
                </p>
                {nutrient_rows}

                <div class="field" style="margin-top: 12px;">
                    <label for="tags">Tags (comma-separated, optional)</label>
                    <input type="text" id="tags" name="tags"
                           placeholder="e.g. high-fat, dairy, fried">
                </div>
                <div class="field">
                    <label for="notes">Notes (optional)</label>
                    <textarea id="notes" name="notes" placeholder="Any notes..."></textarea>
                </div>

                <input type="hidden" name="data_source" id="data_source" value="ai-estimate">

                <button class="btn btn-primary" type="submit" style="margin-top: 12px;">Save</button>
            </div>
        </form>
    </div>

    <script>
    (function() {{
        var now = new Date();
        now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
        document.getElementById('consumed_at').value = now.toISOString().slice(0, 16);
    }})();

    function selectMeal(el, slot) {{
        document.querySelectorAll('.meal-option').forEach(e => e.classList.remove('selected'));
        el.classList.add('selected');
        document.getElementById('meal_slot').value = slot;
    }}

    var NUTRIENT_COLS = {json.dumps([f[0] for f in NUTRIENT_FIELDS])};

    function escapeHtml(s) {{
        if (s == null) return '';
        return String(s).replace(/[&<>"']/g, function(c) {{
            return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c];
        }});
    }}

    function estimate() {{
        var desc = document.getElementById('description').value.trim();
        if (!desc) return;
        var btn = document.getElementById('est-btn');
        btn.disabled = true;
        btn.textContent = 'Looking up...';
        fetch('/api/estimate-from-text', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{description: desc}})
        }})
        .then(r => r.json())
        .then(function(data) {{
            if (data.error) {{
                alert('Error: ' + data.error);
                return;
            }}
            var nutrients = data.estimated_nutrients || {{}};
            NUTRIENT_COLS.forEach(function(col) {{
                var val = nutrients[col];
                document.getElementById(col).value = (val != null) ? val : '';
            }});
            document.getElementById('data_source').value = data.data_source || 'ai-estimate';
            var box = document.getElementById('ingredients-box');
            var rows = (data.ingredients || []).map(function(ing) {{
                var tag = ing.source === 'usda'
                    ? '<span style="color:#065f46; background:#d1fae5; padding:1px 6px; border-radius:4px; font-size:0.8em;">USDA</span>'
                    : '<span style="color:#92400e; background:#fef3c7; padding:1px 6px; border-radius:4px; font-size:0.8em;">AI estimate</span>';
                var match = ing.usda_match ? ' <span style="color:#888;">(' + escapeHtml(ing.usda_match) + ')</span>' : '';
                return '<div style="margin: 4px 0;">' + tag + ' <strong>' + escapeHtml(ing.name) + '</strong> — ' + escapeHtml(ing.amount) + match + '</div>';
            }}).join('');
            box.innerHTML = '<div style="font-weight:600; color:#1e40af; margin-bottom:4px;">' + escapeHtml(data.data_source || '') + '</div>' + rows;
            box.style.display = 'block';
            document.getElementById('details').style.display = 'block';
            btn.textContent = 'Re-estimate';
        }})
        .catch(function(e) {{ alert('Estimate failed: ' + e); }})
        .finally(function() {{
            btn.disabled = false;
            if (btn.textContent === 'Looking up...') btn.textContent = 'Estimate nutrients';
        }});
    }}
    </script>"""
    return page("Describe Food", body)


@app.route("/describe/save", methods=["POST"])
@login_required
def describe_food_save():
    db = get_session()
    try:
        description = request.form.get("description", "").strip()
        if not description:
            return redirect(url_for("describe_food_form"))

        consumed_at_str = request.form.get("consumed_at", "")
        consumed_at = (
            datetime.fromisoformat(consumed_at_str)
            if consumed_at_str
            else datetime.now()
        )

        data_source = request.form.get("data_source", "ai-estimate")
        source_tag = "usda" if data_source.startswith("USDA") else "ai-estimate"

        food_item = FoodItem(
            name=description,
            source=source_tag,
        )
        for field_name, _, _ in NUTRIENT_FIELDS:
            setattr(food_item, field_name, _parse_float(request.form.get(field_name)))

        tags = [t.strip() for t in request.form.get("tags", "").split(",") if t.strip()]

        _save_food_entry(
            db=db,
            food_item=food_item,
            meal_slot=request.form.get("meal_slot", "snack"),
            quantity=_parse_float(request.form.get("quantity"), 1.0),
            consumed_at=consumed_at,
            notes=request.form.get("notes", "").strip() or None,
            tags=tags,
        )
        return redirect(url_for("home", saved=1))
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Routes: Symptom logging
# ---------------------------------------------------------------------------
@app.route("/symptom", methods=["GET"])
@login_required
def symptom_form():
    db = get_session()
    try:
        # Get all known symptom tags from existing entries
        existing_tags = set()
        rows = db.query(SymptomTag.tag).distinct().all()
        for (tag,) in rows:
            existing_tags.add(tag)

        # Merge with seed tags
        all_tags = {}
        for group, tags in SEED_SYMPTOM_TAGS.items():
            all_tags[group] = []
            for t in tags:
                all_tags[group].append(t)
                existing_tags.discard(t)

        # Add any user-created tags that aren't in the seed set
        if existing_tags:
            all_tags["Custom"] = sorted(existing_tags)

        tag_groups_html = ""
        for group, tags in all_tags.items():
            chips = ""
            for t in tags:
                display = t.replace("_", " ").title()
                chips += f"""<div class="tag-chip" onclick="toggleTag(this, '{t}')"
                    data-tag="{t}">{display}</div>"""
            tag_groups_html += f"""<div class="tag-group">
                <h3>{group}</h3>
                <div class="tag-chips">{chips}</div>
            </div>"""

        body = f"""
        <a class="back-link" href="/home">&larr; Home</a>
        <div class="card">
            <h2>Log Symptoms</h2>
            <form method="post" action="/symptom" id="symptom-form">
                {tag_groups_html}

                <div id="severity-container"></div>

                <div class="field" style="margin-top: 16px;">
                    <label for="new_tag">Add New Symptom Tag</label>
                    <div style="display: flex; gap: 8px;">
                        <input type="text" id="new_tag" placeholder="e.g. dizziness"
                               style="margin-bottom: 0;">
                        <button type="button" class="btn btn-secondary"
                                style="width: auto; white-space: nowrap;"
                                onclick="addNewTag()">Add</button>
                    </div>
                </div>

                <div class="field">
                    <label for="logged_at">When did this start?</label>
                    <input type="datetime-local" id="logged_at" name="logged_at">
                </div>
                <div class="field">
                    <label for="notes">Notes (optional)</label>
                    <textarea id="notes" name="notes"
                              placeholder="Any context..."></textarea>
                </div>

                <input type="hidden" name="symptoms_json" id="symptoms_json" value="{{}}">
                <button class="btn btn-success" type="submit">Save Symptoms</button>
            </form>
        </div>

        <script>
        var selectedSymptoms = {{}};

        (function() {{
            var now = new Date();
            now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
            document.getElementById('logged_at').value = now.toISOString().slice(0, 16);
        }})();

        function toggleTag(el, tag) {{
            if (selectedSymptoms[tag] !== undefined) {{
                delete selectedSymptoms[tag];
                el.classList.remove('selected');
                removeSeverityRow(tag);
            }} else {{
                selectedSymptoms[tag] = 3;
                el.classList.add('selected');
                addSeverityRow(tag);
            }}
            updateJson();
        }}

        function addSeverityRow(tag) {{
            var container = document.getElementById('severity-container');
            var display = tag.replace(/_/g, ' ');
            display = display.charAt(0).toUpperCase() + display.slice(1);
            var row = document.createElement('div');
            row.className = 'severity-row visible';
            row.id = 'sev-' + tag;
            var btns = '';
            for (var i = 1; i <= 5; i++) {{
                var active = i === 3 ? 'active' : '';
                btns += '<button type="button" class="severity-btn ' + active + '" ' +
                        'onclick="setSeverity(\\'' + tag + '\\', ' + i + ', this)">' + i + '</button>';
            }}
            row.innerHTML = '<span style="font-size:0.85em; min-width:90px;">' + display + ':</span>' + btns;
            container.appendChild(row);
        }}

        function removeSeverityRow(tag) {{
            var row = document.getElementById('sev-' + tag);
            if (row) row.remove();
        }}

        function setSeverity(tag, val, btn) {{
            selectedSymptoms[tag] = val;
            var row = document.getElementById('sev-' + tag);
            row.querySelectorAll('.severity-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            updateJson();
        }}

        function addNewTag() {{
            var input = document.getElementById('new_tag');
            var tag = input.value.trim().toLowerCase().replace(/\\s+/g, '_');
            if (!tag) return;
            input.value = '';

            // Check if already exists
            if (document.querySelector('[data-tag="' + tag + '"]')) return;

            // Add chip to a "Custom" group or create one
            var customGroup = document.querySelector('.tag-group:last-of-type');
            var display = tag.replace(/_/g, ' ');
            display = display.charAt(0).toUpperCase() + display.slice(1);
            var chip = document.createElement('div');
            chip.className = 'tag-chip selected';
            chip.setAttribute('data-tag', tag);
            chip.setAttribute('onclick', "toggleTag(this, '" + tag + "')");
            chip.textContent = display;
            customGroup.querySelector('.tag-chips').appendChild(chip);

            selectedSymptoms[tag] = 3;
            addSeverityRow(tag);
            updateJson();
        }}

        function updateJson() {{
            document.getElementById('symptoms_json').value = JSON.stringify(selectedSymptoms);
        }}
        </script>"""
        return page("Log Symptoms", body)
    finally:
        db.close()


@app.route("/symptom", methods=["POST"])
@login_required
def symptom_submit():
    db = get_session()
    try:
        symptoms = json.loads(request.form.get("symptoms_json", "{}"))
        if not symptoms:
            return redirect(url_for("home"))

        logged_at_str = request.form.get("logged_at", "")
        if logged_at_str:
            logged_at = datetime.fromisoformat(logged_at_str)
        else:
            logged_at = datetime.now()

        entry = SymptomEntry(
            logged_at=logged_at,
            notes=request.form.get("notes", "").strip() or None,
        )
        db.add(entry)
        db.flush()

        for tag, severity in symptoms.items():
            db.add(SymptomTag(
                symptom_entry_id=entry.id,
                tag=tag,
                severity=max(1, min(5, int(severity))),
            ))

        db.commit()
        return redirect(url_for("home", saved=1))
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Routes: History
# ---------------------------------------------------------------------------
@app.route("/history")
@login_required
def history():
    db = get_session()
    try:
        food, symptoms = _today_entries(db)
        body = f"""
        <a class="back-link" href="/home">&larr; Home</a>
        <div class="card">
            <h2>Today's Food</h2>
            {_render_food_list(food)}
        </div>
        <div class="card">
            <h2>Today's Symptoms</h2>
            {_render_symptom_list(symptoms)}
        </div>"""
        return page("History", body)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Routes: Edit / Delete food entry
# ---------------------------------------------------------------------------
@app.route("/edit/<int:entry_id>", methods=["GET"])
@login_required
def edit_food(entry_id):
    db = get_session()
    try:
        entry = db.query(FoodEntry).get(entry_id)
        if not entry:
            return redirect(url_for("home"))
        item = db.query(FoodItem).get(entry.food_item_id)
        tags = db.query(FoodTag).filter(FoodTag.food_item_id == item.id).all()
        tags_str = ", ".join(t.tag for t in tags)

        nutrient_inputs = ""
        for field_name, display, unit in NUTRIENT_FIELDS:
            val = getattr(item, field_name, "") or ""
            nutrient_inputs += f"""<div class="field">
                <label for="{field_name}">{display} ({unit})</label>
                <input type="number" step="any" id="{field_name}" name="{field_name}"
                       value="{val}" inputmode="decimal">
            </div>"""

        meal_options = ""
        for slot in MEAL_SLOTS:
            selected = "selected" if slot == entry.meal_slot else ""
            meal_options += f"""<div class="meal-option {selected}" onclick="selectMeal(this, '{slot}')">
                {slot.replace('-', ' ').title()}
            </div>"""

        consumed_str = entry.consumed_at.strftime("%Y-%m-%dT%H:%M") if entry.consumed_at else ""

        body = f"""
        <a class="back-link" href="/home">&larr; Home</a>
        <div class="card">
            <h2>Edit Entry</h2>
            <form method="post" action="/edit/{entry.id}">
                <div class="field">
                    <label for="name">Food Name</label>
                    <input type="text" id="name" name="name" value="{item.name}" required>
                </div>
                <div class="field">
                    <label for="brand">Brand</label>
                    <input type="text" id="brand" name="brand" value="{item.brand or ''}">
                </div>
                <div class="field">
                    <label>Meal</label>
                    <div class="meal-grid">{meal_options}</div>
                    <input type="hidden" name="meal_slot" id="meal_slot" value="{entry.meal_slot}">
                </div>
                <div class="field">
                    <label for="quantity">Quantity (servings)</label>
                    <input type="number" step="any" id="quantity" name="quantity"
                           value="{entry.quantity}" min="0.1" inputmode="decimal">
                </div>
                <div class="field">
                    <label for="consumed_at">When did you eat this?</label>
                    <input type="datetime-local" id="consumed_at" name="consumed_at"
                           value="{consumed_str}">
                </div>

                <h3>Nutrients (per serving)</h3>
                <div class="nutrient-grid">{nutrient_inputs}</div>

                <div class="field" style="margin-top: 12px;">
                    <label for="tags">Tags (comma-separated)</label>
                    <input type="text" id="tags" name="tags" value="{tags_str}">
                </div>
                <div class="field">
                    <label for="notes">Notes (optional)</label>
                    <textarea id="notes" name="notes">{entry.notes or ''}</textarea>
                </div>

                <button class="btn btn-primary" type="submit">Save Changes</button>
            </form>
            <form method="post" action="/delete/{entry.id}" style="margin-top: 8px;"
                  onsubmit="return confirm('Delete this entry?');">
                <button class="btn btn-danger" type="submit">Delete Entry</button>
            </form>
        </div>

        <script>
        function selectMeal(el, slot) {{
            document.querySelectorAll('.meal-option').forEach(e => e.classList.remove('selected'));
            el.classList.add('selected');
            document.getElementById('meal_slot').value = slot;
        }}
        </script>"""
        return page("Edit Entry", body)
    finally:
        db.close()


@app.route("/edit/<int:entry_id>", methods=["POST"])
@login_required
def edit_food_submit(entry_id):
    db = get_session()
    try:
        entry = db.query(FoodEntry).get(entry_id)
        if not entry:
            return redirect(url_for("home"))
        item = db.query(FoodItem).get(entry.food_item_id)

        # Update food item
        item.name = request.form.get("name", "").strip()
        item.brand = request.form.get("brand", "").strip() or None
        for field_name, _, _ in NUTRIENT_FIELDS:
            setattr(item, field_name, _parse_float(request.form.get(field_name)))

        # Update entry
        entry.meal_slot = request.form.get("meal_slot", entry.meal_slot)
        entry.quantity = _parse_float(request.form.get("quantity"), 1.0)
        entry.notes = request.form.get("notes", "").strip() or None

        consumed_at_str = request.form.get("consumed_at", "")
        if consumed_at_str:
            entry.consumed_at = datetime.fromisoformat(consumed_at_str)

        # Update tags: delete old, insert new
        db.query(FoodTag).filter(FoodTag.food_item_id == item.id).delete()
        for tag_name in request.form.get("tags", "").split(","):
            tag_name = tag_name.strip().lower()
            if tag_name:
                db.add(FoodTag(food_item_id=item.id, tag=tag_name))

        db.commit()
        return redirect(url_for("home", saved=1))
    finally:
        db.close()


@app.route("/delete/<int:entry_id>", methods=["POST"])
@login_required
def delete_food(entry_id):
    db = get_session()
    try:
        entry = db.query(FoodEntry).get(entry_id)
        if entry:
            # Delete tags and food item if no other entries reference it
            item_id = entry.food_item_id
            db.delete(entry)
            db.flush()

            other_entries = db.query(FoodEntry).filter(
                FoodEntry.food_item_id == item_id
            ).count()
            if other_entries == 0:
                db.query(FoodTag).filter(FoodTag.food_item_id == item_id).delete()
                item = db.query(FoodItem).get(item_id)
                if item:
                    db.delete(item)

            db.commit()
        return redirect(url_for("home"))
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Routes: Scan Food (Phase 2)
# ---------------------------------------------------------------------------
CAMERA_STYLE = """
<style>
  .upload-area {
    border: 2px dashed #d1d5db; border-radius: 12px; padding: 40px 20px;
    text-align: center; margin-bottom: 16px; cursor: pointer;
    transition: border-color 0.2s;
  }
  .upload-area:hover, .upload-area.dragover { border-color: #2563eb; }
  .upload-area input[type="file"] { display: none; }
  .upload-icon { font-size: 2em; margin-bottom: 8px; }
  .preview-img { max-width: 100%; border-radius: 8px; margin-bottom: 12px; }
  .loading { text-align: center; padding: 40px; }
  .spinner {
    display: inline-block; width: 32px; height: 32px;
    border: 3px solid #e5e7eb; border-top: 3px solid #2563eb;
    border-radius: 50%; animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .match-card {
    border: 2px solid #e5e7eb; border-radius: 8px; padding: 12px;
    margin-bottom: 8px; cursor: pointer; transition: border-color 0.2s;
  }
  .match-card:hover, .match-card.selected { border-color: #2563eb; background: #eff6ff; }
  .match-brand { font-size: 0.8em; color: #888; }
  .match-type { font-size: 0.7em; color: #aaa; text-transform: uppercase; }
  .error-msg { background: #fef2f2; border: 1px solid #fca5a5;
    border-radius: 8px; padding: 12px; color: #991b1b; margin-bottom: 12px; }
</style>
"""


@app.route("/scan/food", methods=["GET"])
@login_required
def scan_food():
    body = f"""
    {CAMERA_STYLE}
    <a class="back-link" href="/home">&larr; Home</a>
    <div class="card">
        <h2>Scan Food</h2>
        <p style="color:#888; font-size:0.9em;">Take a photo of your food and we'll identify it.</p>
        <form method="post" action="/scan/food" enctype="multipart/form-data" id="scan-form">
            <div class="upload-area" onclick="document.getElementById('photo').click()">
                <div class="upload-icon">📷</div>
                <div>Tap to take a photo or choose from gallery</div>
                <input type="file" id="photo" name="photo"
                       accept="image/*"
                       onchange="previewAndSubmit(this)">
            </div>
            <img id="preview" class="preview-img" style="display:none;">
            <div id="loading" class="loading" style="display:none;">
                <div class="spinner"></div>
                <p>Identifying food...</p>
            </div>
            <button class="btn btn-primary" type="submit" id="submit-btn"
                    style="display:none;">Analyze Photo</button>
        </form>
    </div>

    <script>
    function previewAndSubmit(input) {{
        if (input.files && input.files[0]) {{
            var reader = new FileReader();
            reader.onload = function(e) {{
                document.getElementById('preview').src = e.target.result;
                document.getElementById('preview').style.display = 'block';
                document.querySelector('.upload-area').style.display = 'none';
                document.getElementById('loading').style.display = 'block';
                document.getElementById('scan-form').submit();
            }};
            reader.readAsDataURL(input.files[0]);
        }}
    }}
    </script>"""
    return page("Scan Food", body)


@app.route("/scan/food", methods=["POST"])
@login_required
def scan_food_process():
    photo = request.files.get("photo")
    if not photo:
        return redirect(url_for("scan_food"))

    try:
        image_bytes = photo.read()
        media_type = photo.content_type or "image/jpeg"

        # Step 1: Claude generates questions to understand the food
        questions = generate_initial_questions(image_bytes, media_type)

        # Save image to temp file for later steps
        tmp_dir = tempfile.gettempdir()
        img_filename = f"foodscan_{uuid.uuid4().hex}.jpg"
        img_path = os.path.join(tmp_dir, img_filename)
        with open(img_path, "wb") as f:
            f.write(image_bytes)

        session["scan_data"] = {
            "image_path": img_path,
            "media_type": media_type,
        }
        session["clarify_questions"] = questions

        # Render questions page
        questions_html = ""
        for i, q in enumerate(questions):
            question_text = q["question"]
            options = q.get("options")
            if options:
                options_html = "".join(
                    f'<label class="option-chip">'
                    f'<input type="radio" name="answer_{i}" value="{opt}">'
                    f'{opt}</label>'
                    for opt in options
                )
                questions_html += f"""
                <div class="clarify-question">
                    <p><strong>{i + 1}. {question_text}</strong></p>
                    <div class="option-chips">{options_html}</div>
                    <input type="text" name="answer_{i}_other" placeholder="Or type your own..."
                           class="form-input" style="margin-top:6px; font-size:0.85em;">
                </div>"""
            else:
                questions_html += f"""
                <div class="clarify-question">
                    <p><strong>{i + 1}. {question_text}</strong></p>
                    <input type="text" name="answer_{i}" class="form-input"
                           placeholder="Your answer...">
                </div>"""

        body = f"""
        {CAMERA_STYLE}
        <style>
          .clarify-question {{ margin-bottom: 16px; }}
          .clarify-question p {{ margin-bottom: 6px; }}
          .option-chips {{ display: flex; flex-wrap: wrap; gap: 6px; }}
          .option-chip {{
            display: inline-block; padding: 6px 12px;
            border: 2px solid #e5e7eb; border-radius: 20px;
            cursor: pointer; font-size: 0.9em; transition: all 0.2s;
          }}
          .option-chip:has(input:checked) {{
            border-color: #2563eb; background: #eff6ff; color: #2563eb;
          }}
          .option-chip input {{ display: none; }}
        </style>
        <a class="back-link" href="/scan/food">&larr; Retake Photo</a>
        <div class="card">
            <h2>Tell me about this food</h2>
            <p style="font-size:0.85em; color:#888;">
                Answer a few quick questions so I can find the best nutritional data.</p>
        </div>
        <form method="post" action="/scan/food/clarify">
            <div class="card">
                {questions_html}
            </div>
            <button class="btn btn-primary" type="submit">Find Nutrition Info</button>
            <button class="btn btn-secondary" type="submit" name="skip_clarify" value="1"
                    style="margin-top:4px;">Skip &mdash; Just Estimate from Photo</button>
        </form>"""
        return page("Describe Food", body)

    except Exception as e:
        body = f"""
        {CAMERA_STYLE}
        <a class="back-link" href="/scan/food">&larr; Try Again</a>
        <div class="card">
            <div class="error-msg">
                <strong>Error analyzing photo:</strong> {str(e)}
            </div>
            <a class="btn btn-secondary" href="/describe">Describe Instead</a>
        </div>"""
        return page("Scan Error", body)


@app.route("/scan/food/select", methods=["POST"])
@login_required
def scan_food_select():
    """Legacy route — the USDA match step is now handled automatically."""
    return redirect(url_for("scan_food"))


@app.route("/scan/food/clarify", methods=["GET"])
@login_required
def scan_food_clarify():
    """Legacy route — questions are now shown directly after upload."""
    return redirect(url_for("scan_food"))


@app.route("/scan/food/clarify", methods=["POST"])
@login_required
def scan_food_clarify_process():
    scan_data = session.get("scan_data", {})
    if not scan_data:
        return redirect(url_for("scan_food"))

    image_path = scan_data.get("image_path")
    media_type = scan_data.get("media_type", "image/jpeg")

    try:
        with open(image_path, "rb") as f:
            image_bytes = f.read()
    except Exception:
        return redirect(url_for("scan_food"))

    # If user skips questions, fall back to photo-only identification
    if request.form.get("skip_clarify"):
        try:
            result = identify_food(image_bytes, media_type)
            food_name = result.get("food_name", "Unknown food")
            search_term = result.get("search_term", food_name)

            usda_nutrients = _try_usda_lookup(search_term)
            web_data = _try_web_search(food_name, restaurant=None) if not usda_nutrients else None

            final = estimate_with_context(
                image_bytes, media_type,
                qa_pairs=[],
                food_name=food_name,
                usda_nutrients=usda_nutrients,
                web_nutrition=web_data,
            )
        except Exception:
            final = {"food_name": "Unknown food", "estimated_nutrients": {}, "suggested_tags": []}

        _cleanup_temp_image(image_path)
        return _render_review_form(
            food_name=final.get("food_name", "Unknown food"),
            brand=None,
            nutrients=final.get("estimated_nutrients", {}),
            suggested_tags=final.get("suggested_tags", []),
            source=final.get("data_source", "claude_vision"),
            action="/scan/food/save",
            back_url="/scan/food",
            serving_size=final.get("estimated_serving_size"),
        )

    # Collect answers from the questions form
    questions = session.get("clarify_questions", [])
    qa_pairs = []
    for i, q in enumerate(questions):
        options = q.get("options")
        if options:
            answer = request.form.get(f"answer_{i}_other", "").strip()
            if not answer:
                answer = request.form.get(f"answer_{i}", "")
        else:
            answer = request.form.get(f"answer_{i}", "")
        qa_pairs.append({"question": q["question"], "answer": answer or "not sure"})

    try:
        # Step 1: Identify food from photo + answers
        identification = identify_from_answers(image_bytes, qa_pairs, media_type)
        food_name = identification.get("food_name", "Unknown food")
        search_term = identification.get("search_term", food_name)
        restaurant = identification.get("restaurant")

        # Step 2: Search USDA silently
        usda_nutrients = _try_usda_lookup(search_term)

        # Step 3: If no USDA match, search the web
        web_data = None
        if not usda_nutrients:
            web_data = _try_web_search(food_name, restaurant)

        # Step 4: Final estimate with all context
        final = estimate_with_context(
            image_bytes, media_type, qa_pairs,
            food_name=food_name,
            usda_nutrients=usda_nutrients,
            web_nutrition=web_data,
            restaurant=restaurant,
        )

        _cleanup_temp_image(image_path)

        return _render_review_form(
            food_name=final.get("food_name", food_name),
            brand=None,
            nutrients=final.get("estimated_nutrients", {}),
            suggested_tags=final.get("suggested_tags", []),
            source=final.get("data_source", "claude_vision"),
            action="/scan/food/save",
            back_url="/scan/food",
            serving_size=final.get("estimated_serving_size"),
        )
    except Exception:
        _cleanup_temp_image(image_path)
        # Fall back to simple photo-only identification
        try:
            result = identify_food(image_bytes, media_type)
            return _render_review_form(
                food_name=result.get("food_name", "Unknown food"),
                brand=None,
                nutrients=result.get("estimated_nutrients", {}),
                suggested_tags=result.get("suggested_tags", []),
                source="claude_vision",
                action="/scan/food/save",
                back_url="/scan/food",
                serving_size=result.get("estimated_serving_size"),
            )
        except Exception:
            return redirect(url_for("scan_food"))


def _try_usda_lookup(search_term: str) -> dict | None:
    """Search USDA and return nutrients for the best match, or None."""
    try:
        matches = search_foods(search_term, limit=3)
        if matches:
            nutrients = get_food_nutrients(matches[0]["fdc_id"])
            serving_size = nutrients.pop("serving_size", None)
            if nutrients.get("calories") is not None:
                return nutrients
    except Exception:
        pass
    return None


def _try_web_search(food_name: str, restaurant: str | None) -> dict | None:
    """Search the web for nutrition info, or return None on failure."""
    try:
        return search_web_nutrition(food_name, restaurant)
    except Exception:
        return None


def _cleanup_temp_image(image_path: str | None):
    """Remove a temp image file if it exists."""
    if image_path:
        try:
            os.remove(image_path)
        except OSError:
            pass


@app.route("/scan/food/save", methods=["POST"])
@login_required
def scan_food_save():
    return _handle_review_save()


# ---------------------------------------------------------------------------
# Routes: Scan Label (Phase 2)
# ---------------------------------------------------------------------------
@app.route("/scan/label", methods=["GET"])
@login_required
def scan_label():
    body = f"""
    {CAMERA_STYLE}
    <a class="back-link" href="/home">&larr; Home</a>
    <div class="card">
        <h2>Scan Nutrition Label</h2>
        <p style="color:#888; font-size:0.9em;">Take a photo of a nutrition label to extract values.</p>
        <form method="post" action="/scan/label" enctype="multipart/form-data" id="scan-form">
            <div class="upload-area" onclick="document.getElementById('photo').click()">
                <div class="upload-icon">🏷️</div>
                <div>Tap to photograph the nutrition label</div>
                <input type="file" id="photo" name="photo"
                       accept="image/*"
                       onchange="previewAndSubmit(this)">
            </div>
            <img id="preview" class="preview-img" style="display:none;">
            <div id="loading" class="loading" style="display:none;">
                <div class="spinner"></div>
                <p>Reading label...</p>
            </div>
            <button class="btn btn-primary" type="submit" id="submit-btn"
                    style="display:none;">Analyze Label</button>
        </form>
    </div>

    <script>
    function previewAndSubmit(input) {{
        if (input.files && input.files[0]) {{
            var reader = new FileReader();
            reader.onload = function(e) {{
                document.getElementById('preview').src = e.target.result;
                document.getElementById('preview').style.display = 'block';
                document.querySelector('.upload-area').style.display = 'none';
                document.getElementById('loading').style.display = 'block';
                document.getElementById('scan-form').submit();
            }};
            reader.readAsDataURL(input.files[0]);
        }}
    }}
    </script>"""
    return page("Scan Label", body)


@app.route("/scan/label", methods=["POST"])
@login_required
def scan_label_process():
    photo = request.files.get("photo")
    if not photo:
        return redirect(url_for("scan_label"))

    try:
        image_bytes = photo.read()
        media_type = photo.content_type or "image/jpeg"

        result = extract_label(image_bytes, media_type)
        food_name = result.get("food_name", "Unknown Product")
        brand = result.get("brand")
        nutrients = result.get("nutrients", {})
        suggested_tags = result.get("suggested_tags", [])
        serving_size = result.get("serving_size")

        return _render_review_form(
            food_name=food_name,
            brand=brand,
            nutrients=nutrients,
            suggested_tags=suggested_tags,
            source="nutrition_label",
            action="/scan/label/save",
            back_url="/scan/label",
            serving_size=serving_size,
        )

    except Exception as e:
        body = f"""
        {CAMERA_STYLE}
        <a class="back-link" href="/scan/label">&larr; Try Again</a>
        <div class="card">
            <div class="error-msg">
                <strong>Error reading label:</strong> {str(e)}
            </div>
            <a class="btn btn-secondary" href="/describe">Describe Instead</a>
        </div>"""
        return page("Scan Error", body)


@app.route("/scan/label/save", methods=["POST"])
@login_required
def scan_label_save():
    return _handle_review_save()


# ---------------------------------------------------------------------------
# Shared review form + save handler for scan flows
# ---------------------------------------------------------------------------
def _render_review_form(food_name, brand, nutrients, suggested_tags, source, action, back_url, serving_size=None):
    """Render the review/edit form after scanning."""
    nutrient_inputs = ""
    for field_name, display, unit in NUTRIENT_FIELDS:
        val = nutrients.get(field_name, "") if nutrients else ""
        if val is None:
            val = ""
        nutrient_inputs += f"""<div class="field">
            <label for="{field_name}">{display} ({unit})</label>
            <input type="number" step="any" id="{field_name}" name="{field_name}"
                   value="{val}" inputmode="decimal">
        </div>"""

    meal_options = ""
    for slot in MEAL_SLOTS:
        meal_options += f"""<div class="meal-option" onclick="selectMeal(this, '{slot}')">
            {slot.replace('-', ' ').title()}
        </div>"""

    tags_str = ", ".join(suggested_tags) if suggested_tags else ""

    body = f"""
    <a class="back-link" href="{back_url}">&larr; Rescan</a>
    <div class="card">
        <h2>Review & Save</h2>
        <form method="post" action="{action}">
            <div class="field">
                <label for="name">Food Name</label>
                <input type="text" id="name" name="name" value="{food_name}" required>
            </div>
            <div class="field">
                <label for="brand">Brand</label>
                <input type="text" id="brand" name="brand" value="{brand or ''}">
            </div>
            <div class="field">
                <label>Meal</label>
                <div class="meal-grid">{meal_options}</div>
                <input type="hidden" name="meal_slot" id="meal_slot" value="snack">
            </div>
            <div class="field">
                <label for="quantity">Quantity (servings)</label>
                {"<div style='background:#eff6ff; border:1px solid #bfdbfe; border-radius:8px; padding:10px 14px; margin-bottom:8px; font-size:0.85em; color:#1e40af;'><strong>1 serving = " + str(serving_size) + "</strong> — adjust quantity if you ate more or less</div>" if serving_size else ""}
                <input type="number" step="any" id="quantity" name="quantity"
                       value="1" min="0.1" inputmode="decimal">
            </div>
            <div class="field">
                <label for="consumed_at">When did you eat this?</label>
                <input type="datetime-local" id="consumed_at" name="consumed_at">
            </div>

            <h3>Nutrients (per serving)</h3>
            <div class="nutrient-grid">{nutrient_inputs}</div>

            <div class="field" style="margin-top: 12px;">
                <label for="tags">Tags (comma-separated)</label>
                <input type="text" id="tags" name="tags" value="{tags_str}">
            </div>
            <div class="field">
                <label for="notes">Notes (optional)</label>
                <textarea id="notes" name="notes"></textarea>
            </div>

            <input type="hidden" name="source" value="{source}">
            <input type="hidden" name="serving_size" value="{serving_size or ''}">
            <button class="btn btn-primary" type="submit">Save Entry</button>
        </form>
    </div>

    <script>
    (function() {{
        var now = new Date();
        now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
        document.getElementById('consumed_at').value = now.toISOString().slice(0, 16);
    }})();

    function selectMeal(el, slot) {{
        document.querySelectorAll('.meal-option').forEach(e => e.classList.remove('selected'));
        el.classList.add('selected');
        document.getElementById('meal_slot').value = slot;
    }}
    document.querySelector('.meal-option:nth-child(4)').classList.add('selected');
    </script>"""
    return page("Review", body)


def _handle_review_save():
    """Handle form submission from any scan review page."""
    db = get_session()
    try:
        consumed_at_str = request.form.get("consumed_at", "")
        if consumed_at_str:
            consumed_at = datetime.fromisoformat(consumed_at_str)
        else:
            consumed_at = datetime.now()

        food_item = FoodItem(
            name=request.form.get("name", "").strip(),
            brand=request.form.get("brand", "").strip() or None,
            serving_size=request.form.get("serving_size", "").strip() or None,
            source=request.form.get("source", "manual"),
        )

        for field_name, _, _ in NUTRIENT_FIELDS:
            setattr(food_item, field_name, _parse_float(request.form.get(field_name)))

        tags = [t.strip() for t in request.form.get("tags", "").split(",") if t.strip()]

        _save_food_entry(
            db=db,
            food_item=food_item,
            meal_slot=request.form.get("meal_slot", "snack"),
            quantity=_parse_float(request.form.get("quantity"), 1.0),
            consumed_at=consumed_at,
            notes=request.form.get("notes", "").strip(),
            tags=tags,
        )
        return redirect(url_for("home", saved=1))
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Routes: Quick Add (Phase 3)
# ---------------------------------------------------------------------------
@app.route("/quick")
@login_required
def quick_add():
    body = """
    <a class="back-link" href="/home">&larr; Home</a>
    <div class="card">
        <h2>Quick Add</h2>
        <p style="color:#888; font-size:0.9em;">Search foods you've logged before.</p>
        <div class="field">
            <input type="text" id="search" placeholder="Start typing a food name..."
                   autocomplete="off" autofocus oninput="doSearch(this.value)">
        </div>
        <div id="results"></div>
    </div>

    <div id="add-form" style="display:none;">
        <div class="card">
            <h3 id="selected-name"></h3>
            <p id="selected-info" style="font-size:0.85em; color:#888;"></p>
            <form method="post" action="/quick/add">
                <input type="hidden" name="food_item_id" id="food_item_id">
                <div class="field">
                    <label>Meal</label>
                    <div class="meal-grid" id="meal-grid"></div>
                    <input type="hidden" name="meal_slot" id="meal_slot" value="snack">
                </div>
                <div class="field">
                    <label for="quantity">Quantity (servings)</label>
                    <div id="serving-info" style="display:none; background:#eff6ff; border:1px solid #bfdbfe; border-radius:8px; padding:10px 14px; margin-bottom:8px; font-size:0.85em; color:#1e40af;"></div>
                    <input type="number" step="any" id="quantity" name="quantity"
                           value="1" min="0.1" inputmode="decimal">
                </div>
                <div class="field">
                    <label for="consumed_at">When?</label>
                    <input type="datetime-local" id="consumed_at" name="consumed_at">
                </div>
                <button class="btn btn-primary" type="submit">Save</button>
            </form>
        </div>
    </div>

    <script>
    var searchTimeout = null;
    var meals = """ + json.dumps(MEAL_SLOTS) + """;

    // Build meal grid
    var mealHtml = '';
    meals.forEach(function(slot) {
        var label = slot.replace('-', ' ');
        label = label.charAt(0).toUpperCase() + label.slice(1);
        var sel = slot === 'snack' ? 'selected' : '';
        mealHtml += '<div class="meal-option ' + sel + '" onclick="selectMeal(this, \\'' + slot + '\\')">' + label + '</div>';
    });
    document.getElementById('meal-grid').innerHTML = mealHtml;

    // Set default time
    (function() {
        var now = new Date();
        now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
        document.getElementById('consumed_at').value = now.toISOString().slice(0, 16);
    })();

    function selectMeal(el, slot) {
        document.querySelectorAll('.meal-option').forEach(e => e.classList.remove('selected'));
        el.classList.add('selected');
        document.getElementById('meal_slot').value = slot;
    }

    function doSearch(q) {
        clearTimeout(searchTimeout);
        if (q.length < 2) {
            document.getElementById('results').innerHTML = '';
            return;
        }
        searchTimeout = setTimeout(function() {
            fetch('/quick/search?q=' + encodeURIComponent(q))
                .then(r => r.json())
                .then(renderResults);
        }, 250);
    }

    var lastResults = [];

    function escapeHtml(s) {
        if (s == null) return '';
        return String(s).replace(/[&<>"']/g, function(c) {
            return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
        });
    }

    function renderResults(items) {
        lastResults = items;
        var resultsEl = document.getElementById('results');
        if (items.length === 0) {
            resultsEl.innerHTML = '<p style="color:#888; text-align:center; padding:12px;">No matches found.</p>';
            return;
        }
        var html = '';
        items.forEach(function(item, idx) {
            var brand = item.brand ? ' <span style="color:#888; font-size:0.85em;">(' + escapeHtml(item.brand) + ')</span>' : '';
            var cal = item.calories ? item.calories + ' kcal' : '';
            var count = item.use_count > 1 ? '<span style="color:#2563eb; font-size:0.8em;">' + item.use_count + 'x logged</span>' : '';
            html += '<div class="entry-item" data-idx="' + idx + '" style="cursor:pointer; padding:12px 0;">'
                + '<strong>' + escapeHtml(item.name) + '</strong>' + brand
                + '<span style="float:right; font-size:0.9em;">' + cal + '</span>'
                + (count ? '<br>' + count : '')
                + '</div>';
        });
        resultsEl.innerHTML = html;
        resultsEl.querySelectorAll('.entry-item').forEach(function(el) {
            el.addEventListener('click', function() {
                var idx = parseInt(el.getAttribute('data-idx'), 10);
                selectItem(lastResults[idx]);
            });
        });
    }

    function selectItem(item) {
        document.getElementById('food_item_id').value = item.id;
        document.getElementById('selected-name').textContent = item.name;
        var info = [];
        if (item.calories) info.push(item.calories + ' kcal');
        if (item.protein_g) info.push(item.protein_g + 'g protein');
        if (item.total_fat_g) info.push(item.total_fat_g + 'g fat');
        if (item.carbohydrates_g) info.push(item.carbohydrates_g + 'g carbs');
        document.getElementById('selected-info').textContent = info.join(' · ');

        // Show serving size info
        var servingDiv = document.getElementById('serving-info');
        if (item.serving_size) {
            servingDiv.innerHTML = '<strong>1 serving = ' + item.serving_size + '</strong> — adjust quantity if you ate more or less';
            servingDiv.style.display = 'block';
        } else {
            servingDiv.style.display = 'none';
        }

        document.getElementById('add-form').style.display = 'block';
        document.getElementById('add-form').scrollIntoView({behavior: 'smooth'});
    }
    </script>"""
    return page("Quick Add", body)


@app.route("/quick/search")
@login_required
def quick_search():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])

    db = get_session()
    try:
        # Search food items by name, ranked by usage frequency then recency
        results = (
            db.query(
                FoodItem,
                func.count(FoodEntry.id).label("use_count"),
                func.max(FoodEntry.consumed_at).label("last_used"),
            )
            .outerjoin(FoodEntry)
            .filter(FoodItem.name.ilike(f"%{q}%"))
            .group_by(FoodItem.id)
            .order_by(func.count(FoodEntry.id).desc(), func.max(FoodEntry.consumed_at).desc())
            .limit(10)
            .all()
        )

        items = []
        for item, use_count, last_used in results:
            items.append({
                "id": item.id,
                "name": item.name,
                "brand": item.brand,
                "serving_size": item.serving_size,
                "calories": float(item.calories) if item.calories else None,
                "protein_g": float(item.protein_g) if item.protein_g else None,
                "total_fat_g": float(item.total_fat_g) if item.total_fat_g else None,
                "carbohydrates_g": float(item.carbohydrates_g) if item.carbohydrates_g else None,
                "use_count": use_count,
            })
        return jsonify(items)
    finally:
        db.close()


@app.route("/quick/add", methods=["POST"])
@login_required
def quick_add_submit():
    db = get_session()
    try:
        food_item_id = int(request.form.get("food_item_id", 0))
        item = db.query(FoodItem).get(food_item_id)
        if not item:
            return redirect(url_for("quick_add"))

        consumed_at_str = request.form.get("consumed_at", "")
        consumed_at = datetime.fromisoformat(consumed_at_str) if consumed_at_str else datetime.now()

        entry = FoodEntry(
            food_item_id=item.id,
            meal_slot=request.form.get("meal_slot", "snack"),
            quantity=_parse_float(request.form.get("quantity"), 1.0),
            consumed_at=consumed_at,
        )
        db.add(entry)
        db.commit()

        # Schedule nudges
        try:
            schedule_nudges(entry.meal_slot, consumed_at)
        except Exception:
            pass

        return redirect(url_for("home", saved=1))
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Routes: Sync API
# ---------------------------------------------------------------------------
@app.route("/api/entries")
@api_key_required
def api_entries():
    from datetime import date as date_type
    since_str = request.args.get("since", "")
    if since_str:
        since = datetime.fromisoformat(since_str)
    else:
        since = datetime(2020, 1, 1)

    db = get_session()
    try:
        food_items = db.query(FoodItem).filter(FoodItem.created_at >= since).all()
        food_entries = db.query(FoodEntry).filter(FoodEntry.logged_at >= since).all()
        food_tags = (
            db.query(FoodTag)
            .join(FoodItem)
            .filter(FoodItem.created_at >= since)
            .all()
        )
        symptom_entries = db.query(SymptomEntry).filter(SymptomEntry.logged_at >= since).all()
        symptom_tags = (
            db.query(SymptomTag)
            .join(SymptomEntry)
            .filter(SymptomEntry.logged_at >= since)
            .all()
        )

        def serialize_dt(dt):
            return dt.isoformat() if dt else None

        return jsonify({
            "food_items": [
                {
                    "id": fi.id, "name": fi.name, "brand": fi.brand,
                    "calories": float(fi.calories) if fi.calories else None,
                    "total_fat_g": float(fi.total_fat_g) if fi.total_fat_g else None,
                    "saturated_fat_g": float(fi.saturated_fat_g) if fi.saturated_fat_g else None,
                    "protein_g": float(fi.protein_g) if fi.protein_g else None,
                    "carbohydrates_g": float(fi.carbohydrates_g) if fi.carbohydrates_g else None,
                    "fiber_g": float(fi.fiber_g) if fi.fiber_g else None,
                    "sugar_g": float(fi.sugar_g) if fi.sugar_g else None,
                    "sodium_mg": float(fi.sodium_mg) if fi.sodium_mg else None,
                    "iron_mg": float(fi.iron_mg) if fi.iron_mg else None,
                    "calcium_mg": float(fi.calcium_mg) if fi.calcium_mg else None,
                    "magnesium_mg": float(fi.magnesium_mg) if fi.magnesium_mg else None,
                    "potassium_mg": float(fi.potassium_mg) if fi.potassium_mg else None,
                    "vitamin_b12_mcg": float(fi.vitamin_b12_mcg) if fi.vitamin_b12_mcg else None,
                    "vitamin_d_mcg": float(fi.vitamin_d_mcg) if fi.vitamin_d_mcg else None,
                    "serving_size": fi.serving_size,
                    "source": fi.source,
                    "created_at": serialize_dt(fi.created_at),
                } for fi in food_items
            ],
            "food_entries": [
                {
                    "id": fe.id, "food_item_id": fe.food_item_id,
                    "meal_slot": fe.meal_slot,
                    "quantity": float(fe.quantity) if fe.quantity else 1.0,
                    "logged_at": serialize_dt(fe.logged_at),
                    "consumed_at": serialize_dt(fe.consumed_at),
                    "notes": fe.notes,
                } for fe in food_entries
            ],
            "food_tags": [
                {"id": ft.id, "food_item_id": ft.food_item_id, "tag": ft.tag}
                for ft in food_tags
            ],
            "symptom_entries": [
                {
                    "id": se.id,
                    "logged_at": serialize_dt(se.logged_at),
                    "notes": se.notes,
                } for se in symptom_entries
            ],
            "symptom_tags": [
                {
                    "id": st.id, "symptom_entry_id": st.symptom_entry_id,
                    "tag": st.tag, "severity": st.severity,
                } for st in symptom_tags
            ],
        })
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
