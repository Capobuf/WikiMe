from html.parser import HTMLParser
import json
import sqlite3

import pytest

from app import create_app
from app.documentation import (
    DEFAULT_MODES, build_document_context, get_effective_mode, get_global_settings,
    initialize_client_document, is_documented_item, item_fingerprint, significant_interface,
)
from app.extensions import db
from app.importers import parse_configuration
from app.models import (
    Client, ClientDocument, Device, DocumentBlock, DocumentSection,
    DocumentationSetting, IntegrationSetting, Site,
)
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


def test_document_initialization_is_unique_idempotent_and_never_repopulates_empty(app, client):
    create_client(client)
    with app.app_context():
        customer = Client.query.one()
        assert ClientDocument.query.filter_by(client_id=customer.id).count() == 1
        document = customer.document
        assert [section.title for section in sorted(document.sections, key=lambda item: item.position)] == [
            "Informazioni generali", "Sedi", "Rete",
        ]
        network = next(section for section in document.sections if section.title == "Rete")
        assert [block.dataset_key for block in sorted(network.blocks, key=lambda item: item.position)] == [
            "Device", "Bridges", "VLAN", "IP Addresses", "Routes / Gateway", "DNS",
            "DHCP", "DHCP leases", "NAT", "Firewall", "VPN", "VPN users", "Interfaces",
        ]
        original_counts = (DocumentSection.query.count(), DocumentBlock.query.count())
        initialize_client_document(customer)
        initialize_client_document(customer)
        db.session.commit()
        assert (DocumentSection.query.count(), DocumentBlock.query.count()) == original_counts
        for section in list(document.sections):
            db.session.delete(section)
        db.session.commit()
        initialize_client_document(customer)
        db.session.commit()
        assert ClientDocument.query.count() == 1
        assert DocumentSection.query.count() == 0
        assert DocumentBlock.query.count() == 0


def test_hierarchy_block_order_and_safe_markdown_rendering(app, client, selected):
    with app.app_context():
        document = db.session.get(Client, selected).document
        for section in list(document.sections):
            db.session.delete(section)
        later = DocumentSection(document_id=document.id, title="Dopo", position=20)
        root = DocumentSection(document_id=document.id, title="Prima", position=10)
        db.session.add_all([later, root])
        db.session.flush()
        child = DocumentSection(document_id=document.id, parent_id=root.id, title="Figlia", position=0)
        db.session.add(child)
        db.session.flush()
        db.session.add_all([
            DocumentBlock(section_id=root.id, kind="markdown", position=2, markdown="SECONDO"),
            DocumentBlock(section_id=root.id, kind="markdown", position=1, markdown=(
                "- voce\n\n```shell\necho ok\n```\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n"
                "<script>alert('x')</script>"
            )),
            DocumentBlock(section_id=child.id, kind="markdown", position=0, markdown="CONTENUTO FIGLIA"),
            DocumentBlock(section_id=later.id, kind="markdown", position=0, markdown="CONTENUTO DOPO"),
        ])
        root_id, child_id = root.id, child.id
        db.session.commit()
    text = client.get("/document").text
    assert text.index("Prima") < text.index("Figlia") < text.index("Dopo")
    assert text.index("echo ok") < text.index("SECONDO") < text.index("CONTENUTO FIGLIA")
    assert f'id="section-{root_id}"' in text and f'id="section-{child_id}"' in text
    assert "<ul>" in text and "<pre><code" in text and "<table>" in text
    assert "<script>alert" not in text and "&lt;script&gt;" in text
    assert "Rinomina" not in text and "Aggiungi blocco" not in text


def test_move_actions_only_reorder_siblings_and_blocks(app, client, selected):
    with app.app_context():
        document = db.session.get(Client, selected).document
        for section in list(document.sections):
            db.session.delete(section)
        first = DocumentSection(document_id=document.id, title="Root A", position=0)
        second = DocumentSection(document_id=document.id, title="Root B", position=1)
        db.session.add_all([first, second])
        db.session.flush()
        child = DocumentSection(document_id=document.id, parent_id=first.id, title="Child", position=0)
        db.session.add(child)
        db.session.flush()
        first_block = DocumentBlock(section_id=first.id, kind="markdown", position=0, markdown="Block A")
        second_block = DocumentBlock(section_id=first.id, kind="markdown", position=1, markdown="Block B")
        db.session.add_all([first_block, second_block])
        db.session.commit()
        ids = first.id, second.id, child.id, first_block.id, second_block.id
    first_id, second_id, child_id, first_block_id, second_block_id = ids
    client.post(f"/documentation/sections/{second_id}/move-up")
    client.post(f"/documentation/sections/{child_id}/move-up")
    client.post(f"/documentation/blocks/{second_block_id}/move-up")
    with app.app_context():
        roots = DocumentSection.query.filter_by(parent_id=None).order_by(DocumentSection.position, DocumentSection.id).all()
        assert [item.id for item in roots] == [second_id, first_id]
        assert db.session.get(DocumentSection, child_id).parent_id == first_id
        blocks = DocumentBlock.query.filter_by(section_id=first_id).order_by(DocumentBlock.position, DocumentBlock.id).all()
        assert [item.id for item in blocks] == [second_block_id, first_block_id]


def test_dataset_scope_is_live_and_site_delete_removes_only_scoped_blocks(app, client, selected):
    client.post("/sites/new", data={"name": "HQ"})
    client.post("/sites/new", data={"name": "Branch"})
    with app.app_context():
        customer = db.session.get(Client, selected)
        hq = Site.query.filter_by(name="HQ").one()
        branch = Site.query.filter_by(name="Branch").one()
        section = DocumentSection(document_id=customer.document.id, title="VLAN dedicate", position=99)
        db.session.add(section)
        db.session.flush()
        scoped = DocumentBlock(section_id=section.id, kind="dataset", dataset_key="VLAN", site_id=hq.id, position=0)
        db.session.add(scoped)
        db.session.add_all([
            Device(client_id=customer.id, site_id=hq.id, name="HQ-Router", fingerprint="hq",
                   data={"sections": {"VLAN": [{"vlan-id": "10", "name": "HQ-VLAN"}]}}),
            Device(client_id=customer.id, site_id=branch.id, name="Branch-Router", fingerprint="branch",
                   data={"sections": {"VLAN": [{"vlan-id": "20", "name": "BRANCH-VLAN"}]}}),
        ])
        db.session.commit()
        scoped_id, section_id, hq_id = scoped.id, section.id, hq.id
    text = client.get("/document").text
    dedicated = text[text.index(f'<section id="section-{section_id}"'):]
    assert "HQ-VLAN" in dedicated and "BRANCH-VLAN" not in dedicated
    with app.app_context():
        global_block = DocumentBlock(section_id=section_id, kind="dataset", dataset_key="VLAN", position=1)
        db.session.add(global_block)
        db.session.commit()
        global_id = global_block.id
    text = client.get("/document").text
    assert "HQ" in text and "Branch" in text and "HQ-VLAN" in text and "BRANCH-VLAN" in text
    with app.app_context():
        hq_device = Device.query.filter_by(name="HQ-Router").one()
        hq_device.data = {"sections": {"VLAN": [{"vlan-id": "11", "name": "HQ-VLAN-UPDATED"}]}}
        db.session.commit()
    assert "HQ-VLAN-UPDATED" in client.get("/document").text
    with app.app_context():
        assert db.session.get(DocumentBlock, scoped_id).dataset_key == "VLAN"
    client.post(f"/sites/{hq_id}/delete")
    with app.app_context():
        assert db.session.get(DocumentBlock, scoped_id) is None
        assert db.session.get(DocumentBlock, global_id).site_id is None


def test_section_delete_cascades_and_document_actions_are_client_isolated(app, client, selected):
    with app.app_context():
        first = db.session.get(Client, selected)
        root = DocumentSection(document_id=first.document.id, title="Delete me", position=50)
        db.session.add(root)
        db.session.flush()
        child = DocumentSection(document_id=first.document.id, parent_id=root.id, title="Child", position=0)
        db.session.add(child)
        db.session.flush()
        block = DocumentBlock(section_id=child.id, kind="markdown", markdown="private", position=0)
        second = Client(company_name="Other")
        db.session.add_all([block, second])
        db.session.flush()
        initialize_client_document(second)
        foreign_site = Site(client_id=second.id, name="Foreign")
        db.session.add(foreign_site)
        db.session.commit()
        root_id, child_id, block_id = root.id, child.id, block.id
        other_section_id = second.document.sections[0].id
        own_section_id = next(section.id for section in first.document.sections if section.parent_id is None and section.id != root.id)
        foreign_site_id = foreign_site.id
    assert client.post(f"/documentation/sections/{other_section_id}/edit", data={"title": "Hacked"}).status_code == 404
    response = client.post(
        f"/documentation/sections/{own_section_id}/blocks/new",
        data={"kind": "dataset", "dataset_key": "VLAN", "site_id": foreign_site_id},
    )
    assert response.status_code == 200 and "non appartiene" in response.text
    client.post(f"/documentation/sections/{root_id}/delete")
    with app.app_context():
        assert db.session.get(DocumentSection, root_id) is None
        assert db.session.get(DocumentSection, child_id) is None
        assert db.session.get(DocumentBlock, block_id) is None
        assert db.session.get(DocumentSection, other_section_id).title != "Hacked"
