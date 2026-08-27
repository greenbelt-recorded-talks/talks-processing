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
    app.cli.add_command(commands.migrate_db)
    app.cli.add_command(commands.migration_status)
    app.cli.add_command(commands.load_sample_data)


# Both are shown in the navbar on every page. The colours only need to be
# unmistakably different from each other - neither state is an error.
DEPLOYMENT_LABELS = {
    "cloud": ("Cloud", "uk-label-primary", "Running on PythonAnywhere"),
    "onsite": ("On-site", "uk-label-warning", "Running on the festival server"),
}


def setup_deployment_banner(app):
    """Expose the deployment environment to every template."""

    @app.context_processor
    def inject_deployment():
        env = app.config["DEPLOYMENT_ENV"]
        # An unrecognised value means DEPLOYMENT_ENV was set to something
        # unexpected. Say so in the navbar rather than guessing or hiding it.
        label, css, hint = DEPLOYMENT_LABELS.get(
            env, (env, "uk-label-danger", "Unrecognised DEPLOYMENT_ENV")
        )
        return {
            "deployment_env": env,
            "deployment_label": label,
            "deployment_css": css,
            "deployment_hint": hint,
        }


def setup_login(app):
    from flask_login import login_required, logout_user

    from .models import login_manager

    login_manager.init_app(app)


def create_app():
    """Construct the core application."""
    app = Flask(__name__, instance_relative_config=False)

    # Application Configuration
    app.config.from_object("config.Config")

    # Initialize Plugins
    db.init_app(app)

    # Import blueprints
    register_blueprints(app)

    # Register Commands
    register_commands(app)

    # Setup login
    setup_login(app)

    # Show which deployment this is
    setup_deployment_banner(app)

    # Use Markdown

    from .markdown.markdown import Markdown

    Markdown(app)

    with app.app_context():
        # Imports
        from . import routes

        # Create tables for our models
        db.create_all()

        # Initialize default rota settings
        from .models import RotaSettings
        RotaSettings.initialize_defaults()

        return app
