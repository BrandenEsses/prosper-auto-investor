import json
import requests
from datetime import datetime
from flask import Flask, render_template, request, flash, redirect, url_for
from flask_apscheduler import APScheduler

# Import from your models.py file
from models import db, InvestmentCriteria, AvailableListing, OwnedNote, to_nullable_int, to_nullable_float

# Imports configuration variables like SECRET_KEY, PROSPER_CLIENT_ID, etc.
from config import *

# --- Global Token Variables ---
access_token = None
refresh_token = None

# Initialize extensions
scheduler = APScheduler()


# --- API Communication & Background Job Functions ---

def get_prosper_token():
    """Gets the initial access and refresh tokens from Prosper."""
    global access_token, refresh_token
    print("Attempting to get initial Prosper token...")
    url = "https://api.prosper.com/v1/security/oauth/token"
    payload = f"grant_type=password&client_id={PROSPER_CLIENT_ID}&client_secret={PROSPER_CLIENT_SECRET}&username={PROSPER_USERNAME}&password={PROSPER_PASSWORD}"
    headers = {'accept': "application/json", 'content-type': "application/x-www-form-urlencoded"}
    try:
        response = requests.request("POST", url, data=payload, headers=headers)
        response.raise_for_status()
        response_data = response.json()
        access_token = response_data.get("access_token")
        refresh_token = response_data.get("refresh_token")
        print("Initial token received successfully.")
        return response_data
    except requests.exceptions.RequestException as e:
        print(f"FATAL: Could not get initial token. Error: {e}")
        return None

def refresh_prosper_token():
    """Refreshes the access token using the stored refresh token."""
    global access_token, refresh_token
    print("--- Background Job: Refreshing Prosper token... ---")
    if not refresh_token:
        print("--- CRITICAL: No refresh token available. Attempting to get a new one. ---")
        return get_prosper_token() is not None
        
    url = "https://api.prosper.com/v1/security/oauth/token"
    payload = f"grant_type=refresh_token&client_id={PROSPER_CLIENT_ID}&client_secret={PROSPER_CLIENT_SECRET}&refresh_token={refresh_token}"
    headers = {'accept': "application/json", 'content-type': "application/x-www-form-urlencoded"}
    try:
        response = requests.request("POST", url, data=payload, headers=headers)
        response.raise_for_status()
        response_data = response.json()
        access_token = response_data["access_token"]
        refresh_token = response_data["refresh_token"]
        print("--- Token refreshed successfully. ---")
        return True
    except requests.exceptions.RequestException as e:
        print(f"--- CRITICAL: Token refresh failed: {e}. A new token will be attempted on the next cycle. ---")
        return False

def get_notes():
    """Fetches currently owned notes from the API."""
    print("--- API Call: Fetching owned notes... ---")
    if not access_token: return []
    url = "https://api.prosper.com/v1/notes/"
    headers = {'authorization': f"bearer {access_token}", 'accept': "application/json"}
    try:
        response = requests.request("GET", url, headers=headers)
        response.raise_for_status()
        response_data = response.json()
        result_list = response_data.get('result', [])
        print(f"--- Found {len(result_list)} owned notes from API. ---")
        return result_list
    except requests.exceptions.RequestException as e:
        print(f"--- ERROR fetching notes: {e} ---")
        return []

def get_listings():
    """Fetches available listings from the API."""
    print("--- API Call: Fetching available listings... ---")
    if not access_token: return []
    url = "https://api.prosper.com/listingsvc/v2/listings/?biddable=true&invested=false"
    headers = {'authorization': f"bearer {access_token}", 'accept': "application/json"}
    try:
        response = requests.request("GET", url, headers=headers)
        response.raise_for_status()
        response_data = response.json()
        result_list = response_data.get('result', [])
        print(f"--- Found {len(result_list)} listings from API. ---")
        return result_list
    except requests.exceptions.RequestException as e:
        print(f"--- ERROR fetching listings: {e} ---")
        return []

def perform_hourly_update(app):
    """The function executed by the scheduler to refresh data and cache it."""
    with app.app_context():
        print(f"--- Running data update job at {datetime.now()} ---")
        if not refresh_prosper_token(): return
        
        new_listings = get_listings()
        if new_listings:
            try:
                db.session.query(AvailableListing).delete()
                for listing_json in new_listings:
                    db.session.add(AvailableListing(listing_number=listing_json['listing_number'], listing_data=listing_json))
                db.session.commit()
                print(f"Successfully cached {len(new_listings)} new listings.")
            except Exception as e:
                db.session.rollback(); print(f"--- DATABASE ERROR caching listings: {e} ---")

        new_notes = get_notes()
        if new_notes:
            try:
                db.session.query(OwnedNote).delete()
                for note_json in new_notes:
                    db.session.add(OwnedNote(loan_note_id=note_json['loan_note_id'], note_data=note_json))
                db.session.commit()
                print(f"Successfully cached {len(new_notes)} new notes.")
            except Exception as e:
                db.session.rollback(); print(f"--- DATABASE ERROR caching notes: {e} ---")


# --- Application Factory ---

def create_app():
    app = Flask(__name__)
    app.config.from_pyfile('config.py')
    
    db.init_app(app)
    scheduler.init_app(app)

    # All app-dependent logic is now defined inside the factory
    
    with app.app_context():
        db.create_all()
        get_prosper_token()
        print("Running data fetch on application startup...")
        perform_hourly_update(app)
        if not scheduler.get_job('hourly-update'):
            scheduler.add_job(id='hourly-update', func=lambda: perform_hourly_update(app), trigger='interval', seconds=3540)
            print("Scheduled hourly data refresh job.")

    scheduler.start(paused=app.config.get('TESTING', False))
    return app


# --- Create App Instance ---
app = create_app()


# --- Global Context Processor ---

@app.context_processor
def inject_global_data():
    """Makes variables available to all templates."""
    last_refresh_timestamp = None
    # Find the most recently cached listing to get the timestamp
    latest_listing = AvailableListing.query.order_by(AvailableListing.cached_at.desc()).first()
    if latest_listing:
        # --- THIS IS THE FIX ---
        # We append 'Z' to the ISO string to explicitly mark it as UTC for all browsers.
        last_refresh_timestamp = latest_listing.cached_at.isoformat() + "Z"
        
    return dict(
        now=datetime.utcnow, 
        last_refresh_timestamp=last_refresh_timestamp
    )


# --- Define Routes within App Context ---
with app.app_context():
    @app.route("/")
    def index():
        return render_template("index.html", active_page='home') # UPDATED

    @app.route("/notes")
    def notes():
        notes_from_db = OwnedNote.query.all()
        current_notes = {"result": [note.note_data for note in notes_from_db]}
        return render_template("notes.html", data=current_notes, active_page='notes') # UPDATED

    @app.route("/listings")
    def listings():
        listings_from_db = AvailableListing.query.all()
        current_listings = {"result": [listing.listing_data for listing in listings_from_db]}
        return render_template("listings.html", data=current_listings, active_page='listings')

    @app.route('/strategies')
    def list_strategies():
        all_strategies = InvestmentCriteria.query.order_by(InvestmentCriteria.name).all()
        return render_template('strategy_list.html', strategies=all_strategies, active_page='strategies')

@app.route('/strategy', defaults={'strategy_id': None}, methods=['GET', 'POST'])
@app.route('/strategy/<int:strategy_id>', methods=['GET', 'POST'])
def strategy_manager(strategy_id):
    """
    Manages creating and editing an investment strategy, with a live preview.
    """
    criteria_obj = InvestmentCriteria.query.get_or_404(strategy_id) if strategy_id else None

    if request.method == 'POST':
        is_new = criteria_obj is None
        object_to_update = InvestmentCriteria() if is_new else criteria_obj
        if is_new:
            db.session.add(object_to_update)
        flash_message_verb = 'created' if is_new else 'updated'
        
        # --- Populate top-level fields ---
        object_to_update.name = request.form.get('name')
        object_to_update.investment_amount = int(request.form.get('investment_amount', 25))
        object_to_update.active = 'active' in request.form
        
        # --- Build the complete JSON object for the 'filters' column ---
        object_to_update.filters = {
            'prosper_rating': request.form.getlist('prosper_rating'),
            'at09s': { # Trades opened in past 24 months
                'min': to_nullable_int(request.form.get('min_at09s')),
                'max': to_nullable_int(request.form.get('max_at09s'))
            },
            'employment_status_description': request.form.getlist('employment_status'),
            'borrower_state': request.form.getlist('borrower_state'),
            'fico_score': { # TransUnion FICO Score
                'min': to_nullable_int(request.form.get('min_fico')),
                'max': to_nullable_int(request.form.get('max_fico'))
            },
            'occupation': request.form.getlist('occupation'),
            'months_employed': {
                'min': to_nullable_int(request.form.get('min_months_employed')),
                'max': to_nullable_int(request.form.get('max_months_employed'))
            },
            'g237s': { # Credit inquiries in past 6 months
                'min': to_nullable_int(request.form.get('min_g237s')),
                'max': to_nullable_int(request.form.get('max_g237s'))
            },
            'listing_category_id': [int(val) for val in request.form.getlist('listing_category')],
            'amount_requested': {
                'min': to_nullable_int(request.form.get('min_loan_amount')),
                'max': to_nullable_int(request.form.get('max_loan_amount'))
            },
            'borrower_rate': {
                'min': to_nullable_float(request.form.get('min_borrower_rate')) / 100.0 if request.form.get('min_borrower_rate') else None,
                'max': to_nullable_float(request.form.get('max_borrower_rate')) / 100.0 if request.form.get('max_borrower_rate') else None
            }
        }
        
        db.session.commit()
        flash(f"Strategy '{object_to_update.name}' {flash_message_verb} successfully!", 'success')
        return redirect(url_for('list_strategies'))

    # For GET requests, load listings for the live preview from our database cache
    listings_from_db = AvailableListing.query.all()
    listings_data_for_template = {"result": [listing.listing_data for listing in listings_from_db]}
    
    return render_template(
        'strategy.html', 
        listings_data=listings_data_for_template,
        criteria=criteria_obj,
        criteria_dict=criteria_obj.filters if criteria_obj else {},
        active_page='strategies'
    )
    
@app.route('/strategy/<int:strategy_id>/delete', methods=['POST'])
def delete_strategy(strategy_id):
    criteria_obj = InvestmentCriteria.query.get_or_404(strategy_id)
    db.session.delete(criteria_obj)
    db.session.commit()
    flash(f"Strategy '{criteria_obj.name}' has been deleted.", 'info')
    return redirect(url_for('list_strategies'))


# Main entry point for running with `python app.py`
if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)