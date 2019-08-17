"""
The rota Blueprint handles the rota management for this application.
"""
from flask import Blueprint
rota_blueprint = Blueprint('rota', __name__, template_folder='templates')
 
from . import routes



