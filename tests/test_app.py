from io import BytesIO
import re

from sqlalchemy import inspect

from app.extensions import db
from app.importers import parse_configuration
from app.models import Client, Device, IntegrationSetting, Site, Source
from app.routes.imports import _preview_serializer
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


ROUTEROS_SAMPLE = b'''# 2026-09-27 by RouterOS 7.23.3
# model = CCR2004-1G-12S+2XS
# serial number = TEST-SERIAL
/interface ethernet
set [ find default-name=ether1 ] name=ether1 comment="WAN" mac-address=00:11:22:33:44:55
set [ find default-name=ether2 ] name=ether2 disabled=yes
/interface vlan
add interface=ether1 name=vlan100 vlan-id=100
/interface bridge port
add bridge=bridge1 interface=ether1 pvid=1 disabled=no
/interface bridge vlan
add bridge=bridge1 tagged=ether1 vlan-ids=100 disabled=no
/ip address
add address=10.0.0.1/24 interface=ether1 comment=Management
/ip dns
set servers=1.1.1.1,9.9.9.9 cache-size=2048KiB
/ip firewall filter
add chain=input action=accept comment="Allow established"
/ppp secret
add name=test password=do-not-store profile=default
/system identity
set name=TEST-CCR
'''


SWITCHOS_SAMPLE = "vlan.b:[{nm:'4d616e6167656d656e74',mbr:0x03,vid:0x64}],lacp.b:{},link.b:{en:0x03,an:0x03,nm:['506f727431','53465031'],sfpr:[0x00,0x01]},sys.b:{id:'544553542d5357',ip:0x016410ac},.pwd.b:{pwd:'736563726574'}"


def test_parsers_extract_devices_without_secrets():
    router = parse_configuration(ROUTEROS_SAMPLE.decode(), "router.rsc").as_dict()
    assert router["device"]["name"] == "TEST-CCR"
    assert router["device"]["model"] == "CCR2004-1G-12S+2XS"
    assert router["device"]["management_ip"] == "10.0.0.1"
    assert router["sections"]["VLAN"][0]["vlan-id"] == "100"
    assert "interface" not in router["sections"]["VLAN"][0]
    assert "Bridge ports" not in router["sections"]
    assert router["sections"]["Interfaces"][0]["vlan_mode"] == "trunk"
    assert router["sections"]["Interfaces"][0]["tagged_vlans"] == ["100"]
    assert "disabled" not in router["sections"]["Interfaces"][0]
    assert router["sections"]["Interfaces"][1]["disabled"] is True
    assert [item["server"] for item in router["sections"]["DNS"]] == ["1.1.1.1", "9.9.9.9"]
    assert "cache-size" not in str(router)
    assert "do-not-store" not in str(router)

    switch = parse_configuration(SWITCHOS_SAMPLE, "switch.swb").as_dict()
    assert switch["device"]["name"] == "TEST-SW"
    assert switch["device"]["management_ip"] == "172.16.100.1"
    assert switch["sections"]["Interfaces"][1]["type"] == "SFP"
    assert "secret" not in str(switch)


def test_multiple_configuration_import_creates_and_updates_devices(app, client):
    create_client(client)
    with app.app_context():
        client_id = Client.query.one().id
    client.post(f"/clients/{client_id}/select")

    response = client.post(
        "/imports/analyze",
        data={"files": [(BytesIO(ROUTEROS_SAMPLE), "router.rsc"), (BytesIO(SWITCHOS_SAMPLE.encode()), "switch.swb")]},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "TEST-CCR" in response.text
    assert "TEST-SW" in response.text
    token = re.search(r'name="preview_token" value="([^"]+)"', response.text).group(1)
    with app.app_context():
        preview = _preview_serializer().loads(token)
        assert Device.query.count() == 0
        assert not inspect(db.engine).has_table("import_batch")
        selected_items = {}
        for candidate_index, candidate in enumerate(preview["candidates"]):
            selected_items[f"items_{candidate_index}"] = [
                f"{section_index}:{item_index}"
                for section_index, (section, items) in enumerate(candidate["sections"].items())
                for item_index in range(len(items))
                if section != "DNS" or item_index == 0
            ]

    response = client.post(
        "/imports/commit",
        data={"preview_token": token, "candidates": ["0", "1"], **selected_items},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "2 dispositivi creati" in response.text
    with app.app_context():
        assert Device.query.filter_by(client_id=client_id).count() == 2
        router = Device.query.filter_by(serial_number="TEST-SERIAL").one()
        assert router.management_ip == "10.0.0.1"
        assert len(router.sections["DNS"]) == 1
        assert "password" not in str(router.data)
        assert Source.query.filter_by(name="Import configurazioni MikroTik").count() == 1

    response = client.post(
        "/imports/analyze",
        data={"files": (BytesIO(ROUTEROS_SAMPLE), "router-again.rsc")},
        content_type="multipart/form-data",
    )
    token = re.search(r'name="preview_token" value="([^"]+)"', response.text).group(1)
    with app.app_context():
        preview = _preview_serializer().loads(token)
        selected_items = [
            f"{section_index}:{item_index}"
            for section_index, items in enumerate(preview["candidates"][0]["sections"].values())
            for item_index in range(len(items))
        ]
    client.post("/imports/commit", data={"preview_token": token, "candidates": "0", "items_0": selected_items})
    with app.app_context():
        assert Device.query.filter_by(client_id=client_id).count() == 2
