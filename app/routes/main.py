from flask import Blueprint, render_template

from ..models import Device, Site, Source
from ..documentation import build_composed_document_context
from .helpers import current_client_or_404


bp = Blueprint("main", __name__)


@bp.get("/")
def home():
    return render_template("home.html")


@bp.get("/client")
def dashboard():
    client = current_client_or_404()
    integration_count = Source.query.filter_by(client_id=client.id).with_entities(Source.integration_type).distinct().count()
    return render_template("dashboard.html", site_count=Site.query.filter_by(client_id=client.id).count(), source_count=Source.query.filter_by(client_id=client.id).count(), device_count=Device.query.filter_by(client_id=client.id).count(), integration_count=integration_count)


@bp.get("/document")
def document():
    return render_template("document.html", **build_composed_document_context(current_client_or_404()))
