import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, session, url_for

from .defaults import INTEGRATIONS, default_integration_configuration
from .extensions import db
from .models import Client, IntegrationSetting


def create_app(test_config=None):
    load_dotenv()
    app = Flask(__name__, instance_relative_config=True)
    project_root = Path(app.root_path).parent
    database_path = os.getenv("DATABASE_PATH", "instance/wikimi.db")
    if not Path(database_path).is_absolute():
        database_path = project_root / database_path

    app.config.from_mapping(
        SECRET_KEY=os.getenv("SECRET_KEY", "local-poc-secret-key"),
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{Path(database_path).resolve().as_posix()}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        DEBUG=os.getenv("FLASK_ENV", "development") == "development",
    )
    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    db.init_app(app)

    from .routes.clients import bp as clients_bp
    from .routes.main import bp as main_bp
    from .routes.settings import bp as settings_bp
    from .routes.sites import bp as sites_bp
    from .routes.sources import bp as sources_bp

    for blueprint in (main_bp, clients_bp, sites_bp, sources_bp, settings_bp):
        app.register_blueprint(blueprint)

    @app.context_processor
    def inject_layout_context():
        clients = Client.query.order_by(Client.company_name).all()
        current_client = None
        current_id = session.get("current_client_id")
        if current_id:
            current_client = db.session.get(Client, current_id)
            if current_client is None:
                session.pop("current_client_id", None)
        return {"all_clients": clients, "current_client": current_client, "integrations": INTEGRATIONS}

    @app.before_request
    def require_current_client():
        protected = {"main.dashboard", "main.documentation", "main.document", "main.imports", "sites.index", "sources.index"}
        if request.endpoint in protected and not session.get("current_client_id"):
            flash("Seleziona prima un cliente.", "warning")
            return redirect(url_for("clients.index"))

    @app.errorhandler(404)
    def not_found(error):
        return render_template("errors/error.html", code=404, message="Pagina non trovata."), 404

    @app.errorhandler(500)
    def server_error(error):
        app.logger.exception("Application error", exc_info=error)
        return render_template("errors/error.html", code=500, message="Si è verificato un errore applicativo."), 500

    with app.app_context():
        db.create_all()
        for integration_type in INTEGRATIONS:
            if db.session.get(IntegrationSetting, integration_type) is None:
                db.session.add(IntegrationSetting(integration_type=integration_type, configuration=default_integration_configuration(integration_type)))
        db.session.commit()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app.logger.info("WikiMi POC started using %s", app.config["SQLALCHEMY_DATABASE_URI"])
    return app

