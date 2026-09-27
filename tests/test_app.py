from app.extensions import db
from app.models import Client, IntegrationSetting, Site, Source
from .conftest import create_client


def test_application_starts(client):
    assert client.get("/").status_code == 200
    assert client.get("/clients").status_code == 200


def test_create_and_select_client(app, client):
    response = create_client(client)
    assert "ACME" in response.text
    with app.app_context():
        created = Client.query.filter_by(company_name="ACME").one()
        client_id = created.id
    response = client.post(f"/clients/{client_id}/select", follow_redirects=True)
    assert response.request.path == "/client"
    assert "Cliente corrente: ACME" in response.text


def test_client_query_isolation(app, client):
    with app.app_context():
        first = Client(company_name="First")
        second = Client(company_name="Second")
        db.session.add_all([first, second])
        db.session.flush()
        db.session.add_all([Site(client_id=first.id, name="First Site"), Site(client_id=second.id, name="Secret Site")])
        db.session.commit()
        first_id = first.id
    client.post(f"/clients/{first_id}/select")
    response = client.get("/sites")
    assert "First Site" in response.text
    assert "Secret Site" not in response.text


def test_create_site_for_current_client(app, client):
    create_client(client)
    with app.app_context():
        client_id = Client.query.one().id
    client.post(f"/clients/{client_id}/select")
    client.post("/sites/new", data={"name": "Headquarters", "address": "Via Roma"})
    with app.app_context():
        site = Site.query.one()
        assert site.client_id == client_id


def test_create_source_for_current_client(app, client):
    create_client(client)
    with app.app_context():
        client_id = Client.query.one().id
    client.post(f"/clients/{client_id}/select")
    response = client.post("/sources/new", data={"name": "Router", "integration_type": "mikrotik", "settings_mode": "global"}, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        source = Source.query.one()
        assert source.client_id == client_id
        assert source.configuration == {"mode": "global"}


def test_integration_settings_are_loaded_and_saved(app, client):
    response = client.get("/settings/integrations/mikrotik")
    assert response.status_code == 200
    assert "Interfaces" in response.text
    client.post("/settings/integrations/mikrotik", data={"enabled_items": ["Device", "VLAN"], "excluded_items_policy": "propose"})
    with app.app_context():
        setting = db.session.get(IntegrationSetting, "mikrotik")
        assert setting.configuration["enabled_items"] == ["Device", "VLAN"]


def test_edit_and_delete_crud_entities(app, client):
    create_client(client, "Temporary")
    with app.app_context():
        client_id = Client.query.filter_by(company_name="Temporary").one().id
    client.post(f"/clients/{client_id}/select")
    client.post("/sites/new", data={"name": "Old Site"})
    with app.app_context():
        site_id = Site.query.filter_by(client_id=client_id).one().id
    client.post(f"/sites/{site_id}/edit", data={"name": "New Site"})
    client.post("/sources/new", data={"name": "Old Source", "integration_type": "unifi", "site_id": site_id, "settings_mode": "custom"})
    with app.app_context():
        source_id = Source.query.filter_by(client_id=client_id).one().id
        assert db.session.get(Site, site_id).name == "New Site"
    client.post(f"/sources/{source_id}/edit", data={"name": "New Source", "integration_type": "unifi", "site_id": site_id, "settings_mode": "global"})
    client.post(f"/sources/{source_id}/delete")
    client.post(f"/sites/{site_id}/delete")
    client.post(f"/clients/{client_id}/edit", data={"company_name": "Renamed"})
    with app.app_context():
        assert db.session.get(Client, client_id).company_name == "Renamed"
        assert db.session.get(Source, source_id) is None
        assert db.session.get(Site, site_id) is None
    client.post(f"/clients/{client_id}/delete")
    with app.app_context():
        assert db.session.get(Client, client_id) is None
