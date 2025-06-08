from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

# Create the SQLAlchemy extension instance, unbound to an app
db = SQLAlchemy()

# --- Helper functions can remain here ---
def to_nullable_int(value):
    return int(value) if value and value.strip() else None

def to_nullable_float(value):
    return float(value) if value and value.strip() else None

# --- Your existing InvestmentCriteria model (no changes needed) ---
class InvestmentCriteria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    investment_amount = db.Column(db.Integer, nullable=False, default=25)
    active = db.Column(db.Boolean, default=False)
    filters = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # ... (to_criteria_dict method can remain)

# --- NEW Model to Store Available Listings ---
class AvailableListing(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    listing_number = db.Column(db.Integer, unique=True, nullable=False)
    listing_data = db.Column(db.JSON, nullable=False)
    cached_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# --- NEW Model to Store Owned Notes ---
class OwnedNote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    loan_note_id = db.Column(db.String(50), unique=True, nullable=False)
    note_data = db.Column(db.JSON, nullable=False)
    cached_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)