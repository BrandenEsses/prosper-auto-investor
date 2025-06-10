import json
import requests
from datetime import datetime
from flask import Flask, render_template, request, flash, redirect, url_for
from flask_apscheduler import APScheduler

from models import db, InvestmentCriteria, AvailableListing, OwnedNote, to_nullable_int, to_nullable_float
from config import PROSPER_CLIENT_ID, PROSPER_CLIENT_SECRET, PROSPER_USERNAME, PROSPER_PASSWORD

# --- Global Token Variables ---
access_token = None
refresh_token = None

# Initialize extensions
scheduler = APScheduler()


# --- API Communication Functions ---

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
    except requests.exceptions.RequestException as e:
        print(f"FATAL: Could not get initial token. Error: {e}")

def refresh_prosper_token():
    """Refreshes the access token using the stored refresh token."""
    global access_token, refresh_token
    print("--- Background Job: Refreshing Prosper token... ---")
    if not refresh_token:
        print("--- CRITICAL: No refresh token. Attempting to get a new one. ---")
        get_prosper_token()
        return bool(access_token)
        
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
        print(f"--- CRITICAL: Token refresh failed: {e}. ---")
        return False

def get_notes():
    """Fetches ALL currently owned notes from the API using pagination."""
    print("--- API Call: Fetching all owned notes... ---")
    if not access_token: return []
    all_notes, offset, limit, total_to_fetch = [], 0, 100, float('inf')
    while offset < total_to_fetch:
        url = f"https://api.prosper.com/v1/notes/?offset={offset}&limit={limit}"
        headers = {'authorization': f"bearer {access_token}", 'accept': "application/json"}
        try:
            response = requests.get(url, headers=headers); response.raise_for_status(); response_data = response.json()
            if offset == 0: total_to_fetch = response_data.get('total_count', 0)
            current_page_notes = response_data.get('result', [])
            if not current_page_notes: break
            all_notes.extend(current_page_notes)
            offset += limit
        except Exception as e: print(f"--- ERROR fetching notes page (offset {offset}): {e} ---"); break
    print(f"--- Found {len(all_notes)} total owned notes. ---")
    return all_notes

def get_listings():
    """Fetches ALL available listings from the API using pagination."""
    print("--- API Call: Fetching all available listings... ---")
    if not access_token: return []
    all_listings, offset, limit, total_to_fetch = [], 0, 500, float('inf')
    while offset < total_to_fetch:
        url = f"https://api.prosper.com/listingsvc/v2/listings/?offset={offset}&limit={limit}&biddable=true&invested=false"
        headers = {'authorization': f"bearer {access_token}", 'accept': "application/json"}
        try:
            response = requests.get(url, headers=headers); response.raise_for_status(); response_data = response.json()
            if offset == 0: total_to_fetch = response_data.get('total_count', 0)
            current_page_listings = response_data.get('result', [])
            if not current_page_listings: break
            all_listings.extend(current_page_listings)
            offset += limit
        except Exception as e: print(f"--- ERROR fetching listings page (offset {offset}): {e} ---"); break
    print(f"--- Found {len(all_listings)} total available listings. ---")
    return all_listings

# --- Background Job Definition ---

def perform_data_update(app):
    """The function executed by the scheduler to refresh all data and cache it."""
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

def create_app():
    app = Flask(__name__)
    app.config.from_pyfile('config.py')
    
    db.init_app(app)
    scheduler.init_app(app)

    # --- ALL APP-DEPENDENT LOGIC MOVED INSIDE THE FACTORY ---
    
    # Define custom Jinja filters here
    @app.template_filter('currency')
    def currency_filter(value):
        """Formats a number as USD currency with commas."""
        if value is None:
            return ''
        return f"${value:,.2f}"

    # Define context processors here
    @app.context_processor
    def inject_global_data():
        """Makes variables available to all templates."""
        last_refresh_timestamp = None
        latest_listing = AvailableListing.query.order_by(AvailableListing.cached_at.desc()).first()
        if latest_listing:
            last_refresh_timestamp = latest_listing.cached_at.isoformat() + "Z"
        return dict(now=datetime.utcnow, last_refresh_timestamp=last_refresh_timestamp)

    # Define all routes inside the factory
    @app.route("/")
    def index():
        return render_template("index.html", active_page='home')

    @app.route("/notes")
    def notes():
        notes_from_db = OwnedNote.query.all()
        current_notes = {"result": [note.note_data for note in notes_from_db]}
        return render_template("notes.html", data=current_notes, total_count=len(notes_from_db), active_page='notes')

    @app.route("/listings")
    def listings():
        listings_from_db = AvailableListing.query.all()
        current_listings = {"result": [listing.listing_data for listing in listings_from_db]}
        return render_template("available_listings.html", data=current_listings, total_count=len(listings_from_db), active_page='listings')

    @app.route('/strategies')
    def list_strategies():
        all_strategies = InvestmentCriteria.query.order_by(InvestmentCriteria.name).all()
        return render_template('strategy_list.html', strategies=all_strategies, active_page='strategies')

    @app.route('/strategy', defaults={'strategy_id': None}, methods=['GET', 'POST'])
    @app.route('/strategy/<int:strategy_id>', methods=['GET', 'POST'])
    def strategy_manager(strategy_id):
        criteria_obj = InvestmentCriteria.query.get_or_404(strategy_id) if strategy_id else None
        if request.method == 'POST':
            is_new = criteria_obj is None
            object_to_update = InvestmentCriteria() if is_new else criteria_obj
            if is_new: db.session.add(object_to_update)
            flash_message_verb = 'created' if is_new else 'updated'
            
            # Populate all fields from form...
            object_to_update.name = request.form.get('name')
            object_to_update.investment_amount = int(request.form.get('investment_amount', 25))
            object_to_update.active = 'active' in request.form
            object_to_update.filters = {
                'prosper_rating': request.form.getlist('prosper_rating'),
                'months_employed': {'min': to_nullable_int(request.form.get('min_months_employed')),'max': to_nullable_int(request.form.get('max_months_employed'))},
                'at09s': {'min': to_nullable_int(request.form.get('min_at09s')),'max': to_nullable_int(request.form.get('max_at09s'))},
                'g237s': {'min': to_nullable_int(request.form.get('min_g237s')),'max': to_nullable_int(request.form.get('max_g237s'))},
                'employment_status_description': request.form.getlist('employment_status'),
                'listing_category_id': [int(val) for val in request.form.getlist('listing_category')],
                'borrower_state': request.form.getlist('borrower_state'),
                'amount_requested': {'min': to_nullable_int(request.form.get('min_loan_amount')),'max': to_nullable_int(request.form.get('max_loan_amount'))},
                'fico_score': {'min': to_nullable_int(request.form.get('min_fico')),'max': to_nullable_int(request.form.get('max_fico'))},
                'borrower_rate': {'min': to_nullable_float(request.form.get('min_borrower_rate')) / 100.0 if request.form.get('min_borrower_rate') else None,'max': to_nullable_float(request.form.get('max_borrower_rate')) / 100.0 if request.form.get('max_borrower_rate') else None},
                'occupation': request.form.getlist('occupation')
            }
            db.session.commit()
            flash(f"Strategy '{object_to_update.name}' {flash_message_verb} successfully!", 'success')
            return redirect(url_for('list_strategies'))

        listings_from_db = AvailableListing.query.all()
        listings_data_for_template = {"result": [listing.listing_data for listing in listings_from_db]}
        return render_template('strategy.html', listings_data=listings_data_for_template, criteria=criteria_obj, criteria_dict=criteria_obj.filters if criteria_obj else {}, active_page='strategies')

    @app.route('/strategy/<int:strategy_id>/delete', methods=['POST'])
    def delete_strategy(strategy_id):
        criteria_obj = InvestmentCriteria.query.get_or_404(strategy_id)
        db.session.delete(criteria_obj)
        db.session.commit()
        flash(f"Strategy '{criteria_obj.name}' has been deleted.", 'info')
        return redirect(url_for('list_strategies'))

    # --- Startup and Scheduler Logic ---
    with app.app_context():
        db.create_all()
        get_prosper_token()
        print("Running data fetch on application startup...")
        perform_data_update(app)
        if not scheduler.get_job('hourly-update'):
            scheduler.add_job(id='hourly-update', func=lambda: perform_data_update(app), trigger='interval', seconds=3540)
            print("Scheduled hourly data refresh job.")

    scheduler.start(paused=app.config.get('TESTING', False))
    return app


# --- Create and Run App ---
app = create_app()

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
