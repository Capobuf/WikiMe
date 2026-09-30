from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..defaults import INTEGRATIONS
from ..extensions import db
from ..models import IntegrationSetting, DocumentationSetting
from ..documentation import DEFAULT_MODES, MODES, LABELS, get_global_settings, valid_modes


bp = Blueprint("settings", __name__, url_prefix="/settings")


@bp.get("/integrations")
def index():
    return render_template("settings/index.html")


@bp.route("/integrations/<integration_type>", methods=["GET", "POST"])
def detail(integration_type):
    if integration_type not in INTEGRATIONS:
        return render_template("errors/error.html", code=404, message="Integrazione non trovata."), 404
    if integration_type == "mikrotik":
        return render_template("settings/mikrotik.html")
    setting = db.get_or_404(IntegrationSetting, integration_type)
    if request.method == "POST":
        allowed = INTEGRATIONS[integration_type]["items"]
        enabled = [item for item in request.form.getlist("enabled_items") if item in allowed]
        setting.configuration = {
            "enabled_items": enabled,
            "excluded_items_policy": request.form.get("excluded_items_policy", "remember"),
        }
        db.session.commit()
        flash("Configurazione salvata.", "success")
        return redirect(url_for("settings.detail", integration_type=integration_type))
    return render_template("settings/detail.html", integration_type=integration_type, setting=setting, definition=INTEGRATIONS[integration_type])



@bp.route("/documentation", methods=["GET", "POST"])
def documentation():
    if request.method == "POST":
        configuration = valid_modes({section: request.form.get(section) for section in DEFAULT_MODES})
        if len(configuration) != len(DEFAULT_MODES):
            flash("Scegli una modalità valida per ogni categoria.", "danger")
            return render_template("settings/documentation.html", preferences=get_global_settings(), labels=LABELS, modes=MODES), 400
        setting = db.session.get(DocumentationSetting, 1)
        if setting is None:
            setting = DocumentationSetting(id=1)
            db.session.add(setting)
        setting.configuration = configuration
        db.session.commit()
        flash("Preferenze documentazione salvate.", "success")
        return redirect(url_for("settings.documentation"))
    return render_template("settings/documentation.html", preferences=get_global_settings(), labels=LABELS, modes=MODES)
