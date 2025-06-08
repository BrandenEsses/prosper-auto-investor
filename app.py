import json
import requests
from datetime import datetime
from flask import Flask, render_template, request, flash, redirect, url_for
from flask_apscheduler import APScheduler

# Import from your models.py file
from models import db, InvestmentCriteria, AvailableListing, OwnedNote, to_nullable_int, to_nullable_float

# Your config variables will be loaded via app.config.from_pyfile()
# but we can import them here if they are needed at the global scope.
# For this structure, they are only needed inside functions that have app_context.
from config import PROSPER_CLIENT_ID, PROSPER_CLIENT_SECRET, PROSPER_USERNAME, PROSPER_PASSWORD

# --- Global Token Variables ---
# These are managed by the functions below. Be aware that this approach is not ideal
# for multi-process production servers, but works for single-process setups.
access_token = None
refresh_token = None

# Initialize extensions without an app instance
scheduler = APScheduler()

# --- API Communication Functions ---
# (Your original functions, with added error handling)

def get_prosper_token():
    """Gets the initial access and refresh tokens."""
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
    """Refreshes the access token using the refresh token."""
    global access_token, refresh_token
    print("--- Background Job: Refreshing Prosper token... ---")
    if not refresh_token:
        print("--- CRITICAL: No refresh token available. Cannot refresh. ---")
        return False
        
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
        print(f"--- CRITICAL: Token refresh failed: {e} ---")
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
        print(f"--- Found {len(response_data.get('result', []))} owned notes from API. ---")
        return response_data.get('result', [])
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
        print(f"--- Found {len(response_data.get('result', []))} listings from API. ---")
        return response_data.get('result', [])
    except requests.exceptions.RequestException as e:
        print(f"--- ERROR fetching listings: {e} ---")
        return []

# --- Background Job Definition ---
def perform_hourly_update(app):
    """The function executed by the scheduler to refresh data and cache it."""
    with app.app_context():
        print(f"--- Running hourly update job at {datetime.now()} ---")
        
        if not refresh_prosper_token():
            return # Abort if token refresh fails

        # Update Available Listings in DB
        new_listings = get_listings()
        if new_listings:
            try:
                db.session.query(AvailableListing).delete()
                print(f"Cleared old listings from cache.")
                for listing_json in new_listings:
                    listing_obj = AvailableListing(listing_number=listing_json['listing_number'], listing_data=listing_json)
                    db.session.add(listing_obj)
                db.session.commit()
                print(f"Successfully cached {len(new_listings)} new listings.")
            except Exception as e:
                db.session.rollback()
                print(f"--- DATABASE ERROR caching listings: {e} ---")

        # Update Owned Notes in DB
        new_notes = get_notes()
        if new_notes:
            try:
                db.session.query(OwnedNote).delete()
                print(f"Cleared old notes from cache.")
                for note_json in new_notes:
                    note_obj = OwnedNote(loan_note_id=note_json['loan_note_id'], note_data=note_json)
                    db.session.add(note_obj)
                db.session.commit()
                print(f"Successfully cached {len(new_notes)} new notes.")
            except Exception as e:
                db.session.rollback()
                print(f"--- DATABASE ERROR caching notes: {e} ---")

# --- Application Factory ---
def create_app():
    app = Flask(__name__)
    app.config.from_pyfile('config.py')
    
    db.init_app(app)
    scheduler.init_app(app)

    with app.app_context():
        db.create_all()
        get_prosper_token()
        
        if not AvailableListing.query.first():
            print("Listing cache is empty. Running initial data fetch...")
            perform_hourly_update(app)

        if not scheduler.get_job('hourly-update'):
            scheduler.add_job(
                id='hourly-update',
                func=lambda: perform_hourly_update(app),
                trigger='interval',
                seconds=3540,
                replace_existing=True
            )
            print("Scheduled hourly data refresh job.")

    scheduler.start(paused=app.config.get('TESTING', False)) # Don't start scheduler during testing
    return app

def create_app():
    app = Flask(__name__)
    app.config.from_pyfile('config.py')
    
    # Initialize extensions
    db.init_app(app)
    scheduler.init_app(app)

    with app.app_context():
        # Ensure all tables exist
        db.create_all()
        
        # Always get the initial API token on startup
        print("Getting initial Prosper token...")
        get_prosper_token()
        
        # --- MODIFIED BEHAVIOR ---
        # The 'if' condition has been removed. This will now run on every startup.
        print("Running data fetch on application startup...")
        perform_hourly_update(app)

        # Schedule the recurring job if it doesn't exist
        if not scheduler.get_job('hourly-update'):
            scheduler.add_job(
                id='hourly-update',
                func=lambda: perform_hourly_update(app),
                trigger='interval',
                seconds=3540,
                replace_existing=True
            )
            print("Scheduled hourly data refresh job.")

    # Start the background scheduler
    scheduler.start(paused=app.config.get('TESTING', False))
    return app

# --- Create App Instance and Define Routes ---
app = create_app()

@app.route("/")
def index():
    return render_template("index.html", active_page='home') # Assuming you have home.html

@app.route("/notes")
def notes():
    """UPDATED: Fetches owned notes from the database cache."""
    notes_from_db = OwnedNote.query.all()
    current_notes = {"result": [note.note_data for note in notes_from_db]}
    return render_template("notes.html", data=current_notes, active_page='notes')

@app.route("/listings")
def listings():
    """UPDATED: Fetches available listings from the database cache."""
    listings_from_db = AvailableListing.query.all()
    current_listings = {"result": [listing.listing_data for listing in listings_from_db]}
    return render_template("listings.html", data=current_listings, active_page='listings')

@app.route('/strategies')
def list_strategies():
    """Displays a list of all saved investment strategies."""
    all_strategies = InvestmentCriteria.query.order_by(InvestmentCriteria.name).all()
    return render_template('strategy_list.html', strategies=all_strategies, active_page='strategies')

@app.route('/strategy', defaults={'strategy_id': None}, methods=['GET', 'POST'])
@app.route('/strategy/<int:strategy_id>', methods=['GET', 'POST'])
def strategy_manager(strategy_id):
    """Manages creating and editing an investment strategy, with a live preview."""
    criteria_obj = None
    if strategy_id:
        criteria_obj = InvestmentCriteria.query.get_or_404(strategy_id)

    if request.method == 'POST':
        # ... (Your full POST logic for saving the strategy) ...
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
    """Handles deleting a strategy."""
    criteria_obj = InvestmentCriteria.query.get_or_404(strategy_id)
    db.session.delete(criteria_obj)
    db.session.commit()
    flash(f"Strategy '{criteria_obj.name}' has been deleted.", 'info')
    return redirect(url_for('list_strategies'))

# Main entry point for running the app directly
if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)