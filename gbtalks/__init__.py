from flask import Flask
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def register_blueprints(app):
    # Since the application instance is now created, register each Blueprint
    # with the Flask application instance (app)

    # Rota
    from gbtalks.rota import rota_blueprint
    app.register_blueprint(rota_blueprint)

    # Google Login
    from .oauth import blueprint
    app.register_blueprint(blueprint, url_prefix="/login")

def register_commands(app):
    """Register Click commands."""
    from gbtalks import commands
    app.cli.add_command(commands.convert_talks)
    app.cli.add_command(commands.create_db)

def setup_login(app):
    from flask_login import login_required, logout_user
    from .models import login_manager
    login_manager.init_app(app)


def create_app():
    """Construct the core application."""
    app = Flask(__name__, instance_relative_config=False)

    # Application Configuration
    app.config.from_object('config.Config')

    # Initialize Plugins
    db.init_app(app)

    # Import blueprints
    register_blueprints(app)

    # Register Commands
    register_commands(app)

    # Setup login
    setup_login(app)

    # Use Markdown
    from flaskext.markdown import Markdown
    Markdown(app)

    with app.app_context():
        # Imports
        from . import routes
        
        # Create tables for our models
        db.create_all()

        return app

