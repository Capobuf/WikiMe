from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..defaults import INTEGRATIONS
from ..extensions import db
from ..models import IntegrationSetting


bp = Blueprint("settings", __name__, url_prefix="/settings/integrations")


@bp.get("")
def index():
    return render_template("settings/index.html")


@bp.route("/<integration_type>", methods=["GET", "POST"])
def detail(integration_type):
    if integration_type not in INTEGRATIONS:
        return render_template("errors/error.html", code=404, message="Integrazione non trovata."), 404
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

