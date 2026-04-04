from datetime import datetime, timezone

from sqlalchemy import (
    Column, DateTime, Float, ForeignKey, Integer, Numeric, String, Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from config import Config

Base = declarative_base()


class FoodItem(Base):
    __tablename__ = "food_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    brand = Column(Text, nullable=True)

    # Core macros
    calories = Column(Numeric, nullable=True)
    total_fat_g = Column(Numeric, nullable=True)
    saturated_fat_g = Column(Numeric, nullable=True)
    protein_g = Column(Numeric, nullable=True)
    carbohydrates_g = Column(Numeric, nullable=True)
    fiber_g = Column(Numeric, nullable=True)
    sugar_g = Column(Numeric, nullable=True)
    sodium_mg = Column(Numeric, nullable=True)

    # Performance micros
    iron_mg = Column(Numeric, nullable=True)
    calcium_mg = Column(Numeric, nullable=True)
    magnesium_mg = Column(Numeric, nullable=True)
    potassium_mg = Column(Numeric, nullable=True)
    vitamin_b12_mcg = Column(Numeric, nullable=True)
    vitamin_d_mcg = Column(Numeric, nullable=True)

    source = Column(Text, nullable=False, default="manual")  # usda, nutrition_label, claude_vision, manual
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    entries = relationship("FoodEntry", back_populates="food_item")
    tags = relationship("FoodTag", back_populates="food_item", cascade="all, delete-orphan")


class FoodEntry(Base):
    __tablename__ = "food_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    food_item_id = Column(Integer, ForeignKey("food_items.id"), nullable=False)
    meal_slot = Column(Text, nullable=False)  # breakfast, lunch, dinner, snack, pre-run, post-run
    quantity = Column(Numeric, nullable=False, default=1.0)
    logged_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    consumed_at = Column(DateTime, nullable=False)
    notes = Column(Text, nullable=True)

    food_item = relationship("FoodItem", back_populates="entries")


class FoodTag(Base):
    __tablename__ = "food_tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    food_item_id = Column(Integer, ForeignKey("food_items.id"), nullable=False)
    tag = Column(Text, nullable=False)

    food_item = relationship("FoodItem", back_populates="tags")


class SymptomEntry(Base):
    __tablename__ = "symptom_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    logged_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    notes = Column(Text, nullable=True)

    tags = relationship("SymptomTag", back_populates="symptom_entry", cascade="all, delete-orphan")


class SymptomTag(Base):
    __tablename__ = "symptom_tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symptom_entry_id = Column(Integer, ForeignKey("symptom_entries.id"), nullable=False)
    tag = Column(Text, nullable=False)
    severity = Column(Integer, nullable=False)  # 1-5

    symptom_entry = relationship("SymptomEntry", back_populates="tags")


# ---------------------------------------------------------------------------
# Engine & session setup
# ---------------------------------------------------------------------------
engine = create_engine(Config.DATABASE_URL)
Session = sessionmaker(bind=engine)


def init_db():
    """Create all tables if they don't exist."""
    Base.metadata.create_all(engine)


def get_session():
    """Return a new database session."""
    return Session()
