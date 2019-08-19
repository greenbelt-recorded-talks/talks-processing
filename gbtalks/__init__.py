from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

db = SQLAlchemy()
login_manager = LoginManager()


def register_blueprints(app):
    # Since the application instance is now created, register each Blueprint
    # with the Flask application instance (app)
    from gbtalks.rota import rota_blueprint

    app.register_blueprint(rota_blueprint)

def register_commands(app):
    """Register Click commands."""
    from gbtalks import commands
    app.cli.add_command(commands.convert_talks)

def create_app():
    """Construct the core application."""
    app = Flask(__name__, instance_relative_config=False)

    # Application Configuration
    app.config.from_object('config.Config')

    # Initialize Plugins
    db.init_app(app)
    login_manager.init_app(app)

    # Import blueprints
    register_blueprints(app)

    # Register Commands
    register_commands(app)

    with app.app_context():
        # Imports
        from . import routes
        
        # Create tables for our models
        db.create_all()

        return app

