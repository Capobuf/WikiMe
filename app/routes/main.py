from flask import Blueprint, render_template, request

from ..defaults import INTEGRATIONS
from ..models import Site, Source
from .helpers import current_client_or_404


bp = Blueprint("main", __name__)


DEMO_IMPORTS = {
    "Interfaces": ["ether1 - WAN", "bridge-lan", "sfp-sfpplus1"],
    "IP Addresses": ["192.168.10.1/24", "10.0.0.2/30"],
    "Routes": ["0.0.0.0/0 via 10.0.0.1", "192.168.20.0/24 via bridge-lan"],
    "DNS": ["1.1.1.1, 9.9.9.9"],
    "DHCP Servers": ["dhcp-lan", "dhcp-guest"],
    "NAT": ["masquerade WAN", "dst-nat HTTPS"],
    "Firewall": ["Accept established", "Drop invalid", "Drop WAN input"],
}
DEMO_COUNTS = {"Interfaces": 12, "IP Addresses": 6, "Routes": 4, "DNS": 1, "DHCP Servers": 2, "NAT": 10, "Firewall": 35}
DOC_SECTIONS = ["Generale", "Rete", "Wi-Fi", "VoIP", "Server e virtualizzazione", "NAS e backup", "Rack", "Dispositivi", "Software e servizi"]


@bp.get("/")
def home():
    return render_template("home.html")


@bp.get("/client")
def dashboard():
    client = current_client_or_404()
    integration_count = Source.query.filter_by(client_id=client.id).with_entities(Source.integration_type).distinct().count()
    return render_template("dashboard.html", site_count=Site.query.filter_by(client_id=client.id).count(), source_count=Source.query.filter_by(client_id=client.id).count(), integration_count=integration_count)


@bp.get("/documentation")
def documentation():
    return render_template("documentation.html", sections=DOC_SECTIONS)


@bp.get("/document")
def document():
    client = current_client_or_404()
    return render_template("document.html", client=client, sites=Site.query.filter_by(client_id=client.id).order_by(Site.name).all())


@bp.get("/imports")
def imports():
    client = current_client_or_404()
    sources = Source.query.filter_by(client_id=client.id).order_by(Source.name).all()
    source = None
    source_id = request.args.get("source_id", type=int)
    if source_id:
        source = Source.query.filter_by(id=source_id, client_id=client.id).first_or_404()
    return render_template("imports/index.html", sources=sources, selected_source=source, demo_imports=DEMO_IMPORTS, demo_counts=DEMO_COUNTS)

