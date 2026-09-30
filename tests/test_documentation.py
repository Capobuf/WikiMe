from html.parser import HTMLParser
import json
import sqlite3

import pytest

from app import create_app
from app.documentation import (
    DEFAULT_MODES, build_document_context, get_effective_mode, get_global_settings,
    is_documented_item, item_fingerprint, significant_interface,
)
from app.extensions import db
from app.importers import parse_configuration
from app.models import Client, Device, DocumentationSetting, IntegrationSetting, Site
from .conftest import create_client
from .test_app import ROUTEROS_SAMPLE, SWITCHOS_SAMPLE


CONFIG = ROUTEROS_SAMPLE.decode() + '''
/interface ethernet
set [ find default-name=ether3 ] name=ether3
/ip firewall nat
add chain=srcnat action=masquerade comment="NAT A"
add chain=dstnat action=dst-nat dst-port=443 to-addresses=192.168.1.10 comment="NAT B"
'''


class Inputs(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.inputs = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "input":
            self.inputs.append(dict(attrs))


def analyze(client, configuration=CONFIG, **kwargs):
    response = client.post("/imports/analyze", data={"configuration": configuration, **kwargs})
    assert response.status_code == 200
    inputs = Inputs(response.text).inputs
    token = next(item["value"] for item in inputs if item.get("name") == "preview_token")
    checkboxes = [item for item in inputs if item.get("name") == "items_0"]
    return response, token, checkboxes


def commit(client, token, checkboxes):
    response = client.post("/imports/commit", data={"preview_token": token, "candidates": "0",
                                                  "items_0": [item["value"] for item in checkboxes if "checked" in item]})
    assert response.status_code == 302


@pytest.fixture()
def selected(app, client):
    create_client(client)
    with app.app_context():
        client_id = Client.query.one().id
    client.post(f"/clients/{client_id}/select")
    return client_id


def test_full_snapshot_and_exclusion_reimport(app, client, selected):
    with app.app_context():
        db.session.get(IntegrationSetting, "mikrotik").configuration = {"enabled_items": []}
        db.session.commit()
    _, token, boxes = analyze(client)
    nat_b = next(box for box in boxes if box["aria-label"] == "Documenta elemento 2 di NAT")
    nat_b.pop("checked")
    commit(client, token, boxes)
    with app.app_context():
        device = Device.query.one()
        assert device.sections == parse_configuration(CONFIG).sections
        assert not is_documented_item(device, "NAT", device.sections["NAT"][1])
        device.notes = "Manual note"
        db.session.commit()
    for route in ("/documentation", "/document"):
        text = client.get(route).text
        assert "NAT A" in text and "NAT B" not in text
        assert "Allow established" not in text
    response, token, boxes = analyze(client)
    assert "Escluso precedentemente" in response.text
    assert "checked" not in next(box for box in boxes if box["value"] == nat_b["value"])
    commit(client, token, boxes)
    with app.app_context():
        assert Device.query.count() == 1
        assert Device.query.one().notes == "Manual note"
        assert len(Device.query.one().sections["NAT"]) == 2
    changed = CONFIG.replace("192.168.1.10", "192.168.1.20")
    response, token, boxes = analyze(client, changed)
    assert "checked" in next(box for box in boxes if box["value"] == nat_b["value"])
    commit(client, token, boxes)
    assert "192.168.1.20" in client.get("/document").text
    _, token, boxes = analyze(client)
    box = next(box for box in boxes if box["value"] == nat_b["value"])
    assert "checked" not in box
    box["checked"] = None
    commit(client, token, boxes)
    assert "NAT B" in client.get("/document").text


def test_replaces_snapshot_and_keeps_absent_exclusions(app, client, selected):
    _, token, boxes = analyze(client)
    for box in boxes:
        if "di NAT" in box["aria-label"]:
            box.pop("checked", None)
    commit(client, token, boxes)
    minimal = "/system identity\nset name=TEST-CCR"
    _, token, boxes = analyze(client, minimal)
    commit(client, token, boxes)
    with app.app_context():
        device = Device.query.one()
        assert device.sections == {}
        assert len(device.data["documentation"]["excluded_items"]["NAT"]) == 2
    for route in ("/document", "/documentation"):
        assert 'data-document-section="VLAN"' not in client.get(route).text
    _, _, boxes = analyze(client)
    assert all("checked" not in box for box in boxes if "di NAT" in box["aria-label"])


def test_preferences_persist_validate_and_apply_without_reimport(app, client, selected):
    _, token, boxes = analyze(client)
    commit(client, token, boxes)
    preferences = {**DEFAULT_MODES, "Firewall": "detail", "Interfaces": "hidden"}
    assert client.post("/settings/documentation", data=preferences).status_code == 302
    with app.app_context():
        assert get_global_settings() == preferences
        assert db.session.get(DocumentationSetting, 1).configuration == preferences
    for route in ("/documentation", "/document"):
        text = client.get(route).text
        assert "Allow established" in text
        assert 'data-document-section="Interfaces"' not in text
    assert client.post("/settings/documentation", data={"Firewall": "invalid"}).status_code == 400
    with app.app_context():
        assert get_global_settings() == preferences


def test_site_override_inheritance_and_multi_site(app, client, selected):
    client.post("/sites/new", data={"name": "HQ", "documentation_preferences": "1", "Interfaces": "detail"})
    client.post("/sites/new", data={"name": "Branch"})
    client.post("/sites/new", data={"name": "Empty"})
    with app.app_context():
        hq_id = Site.query.filter_by(name="HQ").one().id
        branch_id = Site.query.filter_by(name="Branch").one().id
        assert db.session.get(Site, hq_id).documentation_overrides == {"Interfaces": "detail"}
    for site_id, name in ((hq_id, "HQ-Router"), (branch_id, "Branch-Router")):
        config = CONFIG.replace("TEST-CCR", name).replace("TEST-SERIAL", name)
        _, token, boxes = analyze(client, config, site_id=site_id)
        commit(client, token, boxes)
    with app.app_context():
        context = build_document_context(db.session.get(Client, selected), get_global_settings())
        assert len(context["groups"]) == 2
        for group in context["groups"]:
            block = next(block for block in group["blocks"] if block["section"] == "Interfaces")
            assert len(block["rows"]) == (3 if group["site"].id == hq_id else 2)
    assert "Eredita — Summary" in client.get(f"/sites/{hq_id}/edit").text
    client.post(f"/sites/{hq_id}/edit", data={"name": "HQ", "documentation_preferences": "1", "Interfaces": ""})
    with app.app_context():
        assert db.session.get(Site, hq_id).documentation_overrides == {}
        preferences = {**DEFAULT_MODES, "Interfaces": "detail"}
        assert get_effective_mode("Interfaces", db.session.get(Site, branch_id), preferences) == "detail"


def test_exclusion_wins_over_site_detail(app, client, selected):
    client.post("/sites/new", data={"name": "HQ", "documentation_preferences": "1", "NAT": "detail"})
    with app.app_context():
        site_id = Site.query.one().id
    _, token, boxes = analyze(client, site_id=site_id)
    for box in boxes:
        if "di NAT" in box["aria-label"]:
            box.pop("checked", None)
    commit(client, token, boxes)
    assert 'data-document-section="NAT"' not in client.get("/document").text


def test_device_hidden_only_hides_inventory_block(app, client, selected):
    _, token, boxes = analyze(client)
    commit(client, token, boxes)
    client.post("/settings/documentation", data={**DEFAULT_MODES, "Device": "hidden"})
    text = client.get("/document").text
    assert 'data-document-section="Device"' not in text
    assert 'data-document-section="NAT"' in text


@pytest.mark.parametrize("item", [
    {"default-name": "ether1", "name": "WAN"}, {"name": "ether1", "comment": "uplink"},
    {"name": "ether1", "access_vlan": "1"}, {"name": "ether1", "tagged_vlans": ["100"]},
    {"name": "ether1", "bridge": "bridge1"}, {"name": "bond1", "slaves": "ether1,ether2"},
    {"name": "ether1", "disabled": True}, {"name": "sfp1", "default-name": "sfp1"},
    {"name": "Port1", "type": "SFP"}, {"name": "ether1", "poe-out": "off"},
])
def test_significant_interfaces(item):
    assert significant_interface(item)


def test_fingerprint_exact_content_and_normal_ports():
    assert item_fingerprint("NAT", {"a": "è", "b": [1, 2]}) == item_fingerprint("NAT", {"b": [1, 2], "a": "è"})
    assert item_fingerprint("NAT", {"a": 1}) != item_fingerprint("NAT", {"a": "1"})
    assert item_fingerprint("NAT", {"a": 1}) != item_fingerprint("Firewall", {"a": 1})
    assert not significant_interface({"name": "ether1", "default-name": "ether1"})
    assert not significant_interface({"name": "Port1", "port": 1, "type": "Ethernet"})


def test_client_isolation_and_unselected_device(app, client, selected):
    _, token, boxes = analyze(client)
    client.post("/imports/commit", data={"preview_token": token, "items_0": [box["value"] for box in boxes]})
    with app.app_context():
        assert Device.query.count() == 0
    commit(client, token, boxes)
    create_client(client, "Other")
    with app.app_context():
        other_id = Client.query.filter_by(company_name="Other").one().id
    client.post(f"/clients/{other_id}/select")
    for route in ("/documentation", "/document", "/devices"):
        assert "TEST-CCR" not in client.get(route).text
    response = client.post("/imports/commit", data={"preview_token": token, "candidates": "0"}, follow_redirects=True)
    assert "non appartiene" in response.text
    _, token, boxes = analyze(client)
    assert all("checked" in box for box in boxes)
    commit(client, token, boxes)
    with app.app_context():
        assert Device.query.count() == 2


def test_security_and_switchos_snapshot(app, client, selected):
    config = CONFIG + '''
/interface wireguard
add name=wg0 private-key=PRIVATE_KEY preshared-key=PRESHARED_KEY
/snmp community
add name=COMMUNITY_SECRET authentication-password=AUTH_PASSWORD
'''
    response, token, boxes = analyze(client, config)
    commit(client, token, boxes)
    with app.app_context():
        serialized = json.dumps(Device.query.one().data)
    for secret in ("do-not-store", "PRIVATE_KEY", "PRESHARED_KEY", "COMMUNITY_SECRET", "AUTH_PASSWORD"):
        assert secret not in serialized and secret not in response.text
    _, token, boxes = analyze(client, SWITCHOS_SAMPLE)
    for box in boxes:
        box.pop("checked", None)
    commit(client, token, boxes)
    with app.app_context():
        device = Device.query.filter_by(platform="SwitchOS").one()
        assert device.sections == parse_configuration(SWITCHOS_SAMPLE).sections
        assert "736563726574" not in json.dumps(device.data)


def test_legacy_sqlite_upgrade_is_additive_and_repeatable(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE site (id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL, name VARCHAR(200) NOT NULL, address VARCHAR(300), description TEXT, notes TEXT)")
        connection.execute("INSERT INTO site (id, client_id, name, notes) VALUES (1, 1, 'Legacy', 'Keep me')")
    config = {"TESTING": True, "SQLALCHEMY_DATABASE_URI": f"sqlite:///{path.as_posix()}"}
    for _ in range(2):
        application = create_app(config)
        with application.app_context():
            site = db.session.get(Site, 1)
            assert site.documentation_overrides == {}
            assert site.notes == "Keep me"


def test_mikrotik_settings_explain_new_behavior(client):
    response = client.get("/settings/integrations/mikrotik")
    assert response.status_code == 200
    assert "/settings/documentation" in response.text
    assert 'name="enabled_items"' not in response.text


def test_all_categories_render_without_mutating_snapshot(app, client, selected):
    config = CONFIG + '''
/interface bridge
add name=bridge1 protocol-mode=rstp
/ip route
add dst-address=0.0.0.0/0 gateway=10.0.0.254
/ip pool
add name=pool1 ranges=10.0.0.10-10.0.0.20
/ip dhcp-server
add name=dhcp1 interface=bridge1 address-pool=pool1
/ip dhcp-server network
add address=10.0.0.0/24 gateway=10.0.0.1
/ip dhcp-server lease
add address=10.0.0.11 mac-address=00:11:22:33:44:55
/interface wireguard
add name=wg0 listen-port=13231 private-key=DO_NOT_STORE
'''
    _, token, boxes = analyze(client, config)
    commit(client, token, boxes)
    client.post("/settings/documentation", data={section: "detail" for section in DEFAULT_MODES})
    with app.app_context():
        snapshot = json.dumps(Device.query.one().data, sort_keys=True)
        context = build_document_context(db.session.get(Client, selected), get_global_settings())
        assert {block["section"] for block in context["groups"][0]["blocks"]} == set(DEFAULT_MODES)
        assert json.dumps(Device.query.one().data, sort_keys=True) == snapshot
    for route in ("/documentation", "/document"):
        response = client.get(route)
        assert response.status_code == 200
        assert "10.0.0.10-10.0.0.20" in response.text
        assert "DO_NOT_STORE" not in response.text
        for section in DEFAULT_MODES:
            assert f'data-document-section="{section}"' in response.text


def test_identical_duplicate_items_share_exclusion(app, client, selected):
    config = CONFIG + '\n/ip firewall nat\nadd chain=srcnat action=masquerade comment="NAT A"'
    _, token, boxes = analyze(client, config)
    next(box for box in boxes if box["aria-label"] == "Documenta elemento 1 di NAT").pop("checked")
    commit(client, token, boxes)
    with app.app_context():
        assert len(Device.query.one().sections["NAT"]) == 3
    assert "NAT A" not in client.get("/document").text
    _, _, boxes = analyze(client, config)
    assert "checked" not in next(box for box in boxes if box["aria-label"] == "Documenta elemento 3 di NAT")
