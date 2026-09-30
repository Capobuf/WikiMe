from .extensions import db
from .models import Client, Site, Source
from .documentation import initialize_client_document


def seed_demo_data():
    if Client.query.first():
        return
    acme = Client(company_name="ACME S.r.l.", display_name="ACME", city="Milano", email="it@acme.example")
    northwind = Client(company_name="Northwind Italia S.p.A.", display_name="Northwind", city="Torino")
    db.session.add_all([acme, northwind])
    db.session.flush()
    initialize_client_document(acme)
    initialize_client_document(northwind)
    hq = Site(client_id=acme.id, name="Sede principale", address="Via Roma 10, Milano", description="Uffici e CED")
    production = Site(client_id=acme.id, name="Produzione", address="Via Industria 4, Monza")
    nw_hq = Site(client_id=northwind.id, name="Sede Torino", address="Corso Francia 20, Torino")
    db.session.add_all([hq, production, nw_hq])
    db.session.flush()
    db.session.add_all([
        Source(client_id=acme.id, site_id=hq.id, integration_type="mikrotik", name="CCR2004 - Sede principale", configuration={"mode": "global"}),
        Source(client_id=acme.id, site_id=production.id, integration_type="unifi", name="UniFi Site - Produzione", configuration={"mode": "global"}),
        Source(client_id=northwind.id, site_id=nw_hq.id, integration_type="snipeit", name="Azienda Northwind", configuration={"mode": "global"}),
    ])
    db.session.commit()
