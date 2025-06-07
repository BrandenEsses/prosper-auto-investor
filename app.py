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
@app.route('/strategies')
def list_strategies():
    """This page will list all saved strategies."""
    all_strategies = InvestmentCriteria.query.order_by(InvestmentCriteria.name).all()
    return render_template('strategy_list.html', strategies=all_strategies, active_page='strategies')

@app.route('/strategy', methods=['GET', 'POST'])
def new_strategy():
    """Handles GET for the blank form and POST for creating a new strategy."""
    # This redirects to the unified strategy_manager, keeping code clean
    return redirect(url_for('strategy_manager', strategy_id=None))

@app.route('/strategy/<int:strategy_id>', methods=['GET', 'POST'])
def strategy_manager(strategy_id):
    # This is the main route we built in the last step.
    # It handles displaying the tool and saving the data.
    # We just need to ensure it gets the right active_page variable.
    
    criteria_obj = None
    if strategy_id:
        criteria_obj = InvestmentCriteria.query.get_or_404(strategy_id)

    if request.method == 'POST':
        # ... (Your full POST logic for saving the strategy) ...
        # After saving, we redirect to the list of strategies
        return redirect(url_for('list_strategies'))

    # For GET request
    listings_data = get_listings()
    
    return render_template(
        'strategy.html', 
        listings_data=listings_data,
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