from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

# 1. Create the SQLAlchemy extension instance.
#    We don't pass the `app` object here.
db = SQLAlchemy()

class InvestmentCriteria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    investment_amount = db.Column(db.Integer, nullable=False, default=25)
    active = db.Column(db.Boolean, default=False)
    
    # All other criteria are stored in this single JSON column
    filters = db.Column(db.JSON, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"InvestmentCriteria('{self.name}', Active: {self.active})"

# --- Helper Functions ---
def to_nullable_int(value):
    return int(value) if value and value.strip() else None

def to_nullable_float(value):
    return float(value) if value and value.strip() else None