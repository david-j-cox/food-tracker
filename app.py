#!/usr/bin/env python
"""Food Tracker — mobile-first food & symptom logging app."""

import functools
from datetime import datetime, timezone

from flask import Flask, redirect, request, session, url_for, jsonify
from sqlalchemy import func

from config import Config
from models import (
    FoodItem, FoodEntry, FoodTag, SymptomEntry, SymptomTag,
    init_db, get_session,
)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = Config.SECRET_KEY
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 30  # 30 days

# Create tables on startup
with app.app_context():
    init_db()

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
    display: grid; grid-template-columns: 1fr 1fr 1fr 1fr;
    gap: 8px; text-align: center;
  }
  .total-box {
    background: #f9fafb; border-radius: 8px; padding: 10px 4px;
  }
  .total-val { font-size: 1.3em; font-weight: 700; color: #2563eb; }
  .total-label { font-size: 0.7em; color: #888; }

  .flash { background: #d1fae5; border: 1px solid #6ee7b7;
    border-radius: 8px; padding: 12px; margin-bottom: 16px;
    color: #065f46; text-align: center; }

  .back-link {
    display: inline-block; margin-bottom: 12px;
    color: #2563eb; text-decoration: none; font-size: 0.9em;
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
    return entry


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
    """Sum up today's macros from food entries."""
    totals = {"calories": 0, "fat": 0, "protein": 0, "carbs": 0}
    for entry, item in food_entries:
        q = float(entry.quantity or 1)
        totals["calories"] += float(item.calories or 0) * q
        totals["fat"] += float(item.total_fat_g or 0) * q
        totals["protein"] += float(item.protein_g or 0) * q
        totals["carbs"] += float(item.carbohydrates_g or 0) * q
    return totals


def _render_food_list(food_entries):
    """Render today's food entries as HTML."""
    if not food_entries:
        return '<p style="color:#888; text-align:center;">No food logged yet today.</p>'
    rows = ""
    for entry, item in food_entries:
        qty = f" x{entry.quantity}" if float(entry.quantity or 1) != 1.0 else ""
        time_str = entry.consumed_at.strftime("%-I:%M %p") if entry.consumed_at else ""
        cal = int(float(item.calories or 0) * float(entry.quantity or 1))
        rows += f"""<div class="entry-item">
            <strong>{item.name}</strong>{qty}
            <span style="float:right">{cal} kcal</span><br>
            <span class="entry-meta">{entry.meal_slot} &middot; {time_str}</span>
        </div>"""
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
            </div>
            <a class="btn btn-secondary" href="/add" style="margin-top: 4px;">Manual Entry</a>
        </div>

        <div class="card">
            <h3>Today's Totals</h3>
            <div class="totals">
                <div class="total-box">
                    <div class="total-val">{int(totals['calories'])}</div>
                    <div class="total-label">Calories</div>
                </div>
                <div class="total-box">
                    <div class="total-val">{int(totals['fat'])}g</div>
                    <div class="total-label">Fat</div>
                </div>
                <div class="total-box">
                    <div class="total-val">{int(totals['protein'])}g</div>
                    <div class="total-label">Protein</div>
                </div>
                <div class="total-box">
                    <div class="total-val">{int(totals['carbs'])}g</div>
                    <div class="total-label">Carbs</div>
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
# Routes: Manual food entry
# ---------------------------------------------------------------------------
@app.route("/add", methods=["GET"])
@login_required
def add_food_form():
    nutrient_inputs = ""
    for field_name, display, unit in NUTRIENT_FIELDS:
        nutrient_inputs += f"""<div class="field">
            <label for="{field_name}">{display} ({unit})</label>
            <input type="number" step="any" id="{field_name}" name="{field_name}"
                   placeholder="0" inputmode="decimal">
        </div>"""

    meal_options = ""
    for slot in MEAL_SLOTS:
        meal_options += f"""<div class="meal-option" onclick="selectMeal(this, '{slot}')">
            {slot.replace('-', ' ').title()}
        </div>"""

    body = f"""
    <a class="back-link" href="/home">&larr; Home</a>
    <div class="card">
        <h2>Add Food</h2>
        <form method="post" action="/add" id="food-form">
            <div class="field">
                <label for="name">Food Name</label>
                <input type="text" id="name" name="name" required placeholder="e.g. Grilled chicken breast">
            </div>
            <div class="field">
                <label for="brand">Brand (optional)</label>
                <input type="text" id="brand" name="brand" placeholder="e.g. Tyson">
            </div>
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
                <label for="consumed_at">When did you eat this?</label>
                <input type="datetime-local" id="consumed_at" name="consumed_at">
            </div>

            <h3>Nutrients (per serving)</h3>
            <div class="nutrient-grid">{nutrient_inputs}</div>

            <div class="field" style="margin-top: 12px;">
                <label for="tags">Tags (comma-separated)</label>
                <input type="text" id="tags" name="tags"
                       placeholder="e.g. high-fat, dairy, fried">
            </div>
            <div class="field">
                <label for="notes">Notes (optional)</label>
                <textarea id="notes" name="notes" placeholder="Any notes..."></textarea>
            </div>

            <button class="btn btn-primary" type="submit">Save Entry</button>
        </form>
    </div>

    <script>
    // Set default consumed_at to now
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
    // Default select snack
    document.querySelector('.meal-option:nth-child(4)').classList.add('selected');
    </script>"""
    return page("Add Food", body)


@app.route("/add", methods=["POST"])
@login_required
def add_food_submit():
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
            source="manual",
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
    import json
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
# Routes: Scan placeholders (Phase 2)
# ---------------------------------------------------------------------------
@app.route("/scan/food")
@login_required
def scan_food():
    body = """
    <a class="back-link" href="/home">&larr; Home</a>
    <div class="card">
        <h2>Scan Food</h2>
        <p style="color:#888; text-align:center;">
            Camera scanning coming soon. Use Manual Entry for now.</p>
        <a class="btn btn-secondary" href="/add">Go to Manual Entry</a>
    </div>"""
    return page("Scan Food", body)


@app.route("/scan/label")
@login_required
def scan_label():
    body = """
    <a class="back-link" href="/home">&larr; Home</a>
    <div class="card">
        <h2>Scan Label</h2>
        <p style="color:#888; text-align:center;">
            Label scanning coming soon. Use Manual Entry for now.</p>
        <a class="btn btn-secondary" href="/add">Go to Manual Entry</a>
    </div>"""
    return page("Scan Label", body)


# ---------------------------------------------------------------------------
# Routes: Quick Add placeholder (Phase 3)
# ---------------------------------------------------------------------------
@app.route("/quick")
@login_required
def quick_add():
    body = """
    <a class="back-link" href="/home">&larr; Home</a>
    <div class="card">
        <h2>Quick Add</h2>
        <p style="color:#888; text-align:center;">
            Quick Add coming soon. Use Manual Entry for now.</p>
        <a class="btn btn-secondary" href="/add">Go to Manual Entry</a>
    </div>"""
    return page("Quick Add", body)


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
