#!/usr/bin/env python
"""Initialize the database and seed symptom tags for autocomplete."""

from models import init_db

SEED_SYMPTOM_TAGS = {
    "Digestive": [
        "bloating", "nausea", "diarrhea", "urgency",
        "cramping", "acid_reflux", "gas", "fatty_stool",
    ],
    "General": ["fatigue", "brain_fog", "headache"],
    "Positive": ["felt_great", "high_energy", "good_digestion"],
}


def main():
    print("Creating database tables...")
    init_db()
    print("Tables created successfully.")

    # Symptom tags are stored dynamically in symptom_tags table rows,
    # not in a separate lookup table. The seed list lives in app.py's
    # SEED_SYMPTOM_TAGS constant and is always shown in the UI.
    # No seeding needed — the tags appear in the form automatically.

    print("Database initialized and ready.")


if __name__ == "__main__":
    main()
