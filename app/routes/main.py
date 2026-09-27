from flask import Blueprint, render_template

from ..models import Device, Site, Source
from .helpers import current_client_or_404


bp = Blueprint("main", __name__)


DOC_SECTIONS = ["Generale", "Rete", "Wi-Fi", "VoIP", "Server e virtualizzazione", "NAS e backup", "Rack", "Dispositivi", "Software e servizi"]


@bp.get("/")
def home():
    return render_template("home.html")


@bp.get("/client")
def dashboard():
    client = current_client_or_404()
    integration_count = Source.query.filter_by(client_id=client.id).with_entities(Source.integration_type).distinct().count()
    return render_template("dashboard.html", site_count=Site.query.filter_by(client_id=client.id).count(), source_count=Source.query.filter_by(client_id=client.id).count(), device_count=Device.query.filter_by(client_id=client.id).count(), integration_count=integration_count)


@bp.get("/documentation")
def documentation():
    return render_template("documentation.html", sections=DOC_SECTIONS)


@bp.get("/document")
def document():
    client = current_client_or_404()
    return render_template(
        "document.html",
        client=client,
        sites=Site.query.filter_by(client_id=client.id).order_by(Site.name).all(),
        devices=Device.query.filter_by(client_id=client.id).order_by(Device.name).all(),
    )
