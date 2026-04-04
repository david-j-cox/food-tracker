import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    DATABASE_URL = os.getenv("DATABASE_URL")
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    FOOD_TRACKER_PIN = os.getenv("FOOD_TRACKER_PIN")
    FOOD_TRACKER_API_KEY = os.getenv("FOOD_TRACKER_API_KEY")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    USDA_API_KEY = os.getenv("USDA_API_KEY")
    NTFY_TOPIC = os.getenv("NTFY_TOPIC")
