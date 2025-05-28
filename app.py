from flask import Flask, render_template
import requests
import json
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

def create_app():
    app = Flask(__name__)
    with app.app_context():
        get_prosper_token()
    return app

app = create_app()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/notes")
def notes():
    current_notes = get_notes()
    return render_template("notes.html", data = current_notes)

# @app.route("/refresh")
# def refresh():
#     return refresh_prosper_token()

# @app.route("/notes")
# def listings():
#     return get_listings()