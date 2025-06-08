from flask import Flask, render_template, request, flash, redirect, url_for
from models import db, InvestmentCriteria, to_nullable_int, to_nullable_float
import requests
import json
import cryptography
from config import *

access_token = ""
refresh_token = ""


def get_prosper_token():
    url = "https://api.prosper.com/v1/security/oauth/token"
    payload = f"grant_type=password&client_id={PROSPER_CLIENT_ID}&client_secret={PROSPER_CLIENT_SECRET}&username={PROSPER_USERNAME}&password={PROSPER_PASSWORD}"
    headers = { 'accept': "application/json", 'content-type': "application/x-www-form-urlencoded" }
    response = requests.request("POST", url, data=payload, headers=headers)
    response_data = json.loads(response.text)
    global access_token, refresh_token
    access_token = response_data["access_token"]
    refresh_token = response_data["refresh_token"]
    return response_data

def create_app():
    app = Flask(__name__)
    with app.app_context():
        get_prosper_token()
    return app

app = create_app()


app.config['SECRET_KEY'] = SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = SQLALCHEMY_TRACK_MODIFICATIONS

db.init_app(app)

def refresh_prosper_token():
    url = "https://api.prosper.com/v1/security/oauth/token"
    payload = f"grant_type=refresh_token&client_id={PROSPER_CLIENT_ID}&client_secret={PROSPER_CLIENT_SECRET}&refresh_token={refresh_token}"
    headers = { 'accept': "application/json", 'content-type': "application/x-www-form-urlencoded" }
    response = requests.request("POST", url, data=payload, headers=headers)
    response_data = json.loads(response.text)
    return response_data


def get_notes():
    url = "https://api.prosper.com/v1/notes/"
    headers = { 'authorization': f"bearer {access_token}", 'accept': "application/json", 'timezone' : "America/Denver" }
    response = requests.request("GET", url, headers=headers)
    response_data = json.loads(response.text)
    return response_data

def get_listings():
    url = "https://api.prosper.com/listingsvc/v2/listings/?biddable=true&invested=false"
    headers = { 'authorization': f"bearer {access_token}", 'accept': "application/json", 'timezone' : "America/Denver" }
    response = requests.request("GET", url, headers=headers)
    response_data = json.loads(response.text)
    return response_data


@app.route("/")
def index():
    return render_template("index.html")

@app.route("/notes")
def notes():
    current_notes = get_notes()
    return render_template("notes.html", data = current_notes)

@app.route("/listings")
def listings():
    current_listings = get_listings()
    return render_template("listings.html", data = current_listings)

# In app.py

# ... (all your imports like Flask, render_template, request, db, InvestmentCriteria, etc.)

# --- Routes for Managing Investment Strategies ---

@app.route('/strategies')
def list_strategies():
    """
    READ: Displays a list of all saved investment strategies.
    Renders the 'strategy_list.html' template.
    """
    all_strategies = InvestmentCriteria.query.order_by(InvestmentCriteria.name).all()
    return render_template('strategy_list.html', strategies=all_strategies, active_page='list_strategies')

@app.route('/strategy', defaults={'strategy_id': None}, methods=['GET', 'POST'])
@app.route('/strategy/<int:strategy_id>', methods=['GET', 'POST'])
def strategy_manager(strategy_id):
    """
    Manages creating and editing an investment strategy.
    """
    criteria_obj = None
    if strategy_id:
        # Fetch the existing strategy for editing or return a 404 error if it doesn't exist.
        criteria_obj = InvestmentCriteria.query.get_or_404(strategy_id)

    if request.method == 'POST':
        # This block now correctly handles both creating and updating.
        
        is_new = criteria_obj is None
        if is_new:
            # We are creating a brand new strategy object
            object_to_update = InvestmentCriteria()
            db.session.add(object_to_update)
            flash_message_verb = 'created'
        else:
            # We are updating the strategy object we fetched from the DB
            object_to_update = criteria_obj
            flash_message_verb = 'updated'

        # --- THIS IS THE KEY PART: Populate/Update ALL fields from the form ---
        # This logic runs for BOTH new and existing objects.
        
        # 1. Update top-level fields
        object_to_update.name = request.form.get('name')
        object_to_update.investment_amount = int(request.form.get('investment_amount', 25))
        object_to_update.active = 'active' in request.form
        
        # 2. Build the JSON object for the 'filters' column
        filters_dict = {
            'prosper_rating': request.form.getlist('prosper_rating'),
            'months_employed': {
                'min': to_nullable_int(request.form.get('min_months_employed')),
                'max': to_nullable_int(request.form.get('max_months_employed'))
            },
            'at09s': { # Trades opened in past 24 months
                'min': to_nullable_int(request.form.get('min_at09s')),
                'max': to_nullable_int(request.form.get('max_at09s'))
            },
            'g237s': { # Credit inquiries in past 6 months
                'min': to_nullable_int(request.form.get('min_g237s')),
                'max': to_nullable_int(request.form.get('max_g237s'))
            },
            'employment_status_description': request.form.getlist('employment_status'),
            'listing_category_id': [int(val) for val in request.form.getlist('listing_category')],
            'borrower_state': request.form.getlist('borrower_state'),
            'amount_requested': {
                'min': to_nullable_int(request.form.get('min_loan_amount')),
                'max': to_nullable_int(request.form.get('max_loan_amount'))
            },
            'fico_score': {
                'min': to_nullable_int(request.form.get('min_fico')),
                'max': to_nullable_int(request.form.get('max_fico'))
            },
            'borrower_rate': {
                'min': to_nullable_float(request.form.get('min_borrower_rate')) / 100.0 if request.form.get('min_borrower_rate') else None,
                'max': to_nullable_float(request.form.get('max_borrower_rate')) / 100.0 if request.form.get('max_borrower_rate') else None
            },
            'occupation': request.form.getlist('occupation')
        }
        object_to_update.filters = filters_dict
        
        # 3. Commit the changes to the database. This is the "save" button.
        db.session.commit()
        
        flash(f"Strategy '{object_to_update.name}' {flash_message_verb} successfully!", 'success')
        
        # Redirect back to the list page to see the changes.
        return redirect(url_for('list_strategies'))

    # --- GET request logic remains the same ---
    listings_data = get_listings() # Your logic to load available listings for the preview
    
    return render_template(
        'strategy.html', 
        listings_data=listings_data,
        criteria=criteria_obj,
        criteria_dict=criteria_obj.filters if criteria_obj else {},
        active_page='strategies'
    )

@app.route('/strategy/<int:strategy_id>/delete', methods=['POST'])
def delete_strategy(strategy_id):
    """
    DELETE: Removes a strategy from the database.
    """
    criteria_obj = InvestmentCriteria.query.get_or_404(strategy_id)
    db.session.delete(criteria_obj)
    db.session.commit()
    flash(f"Strategy '{criteria_obj.name}' has been deleted.", 'info')
    return redirect(url_for('list_strategies'))