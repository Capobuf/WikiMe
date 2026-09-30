"""Document preferences and projection of the current technical snapshot."""

import hashlib
import json
import re

import mistune
from markupsafe import Markup

from .extensions import db
from .models import ClientDocument, DocumentBlock, DocumentSection, DocumentationSetting


DEFAULT_MODES = {
    "Device": "detail", "Interfaces": "summary", "Bridges": "summary",
    "VLAN": "detail", "IP Addresses": "detail", "Routes / Gateway": "summary",
    "DNS": "summary", "DHCP": "detail", "DHCP leases": "hidden",
    "NAT": "detail", "Firewall": "hidden", "VPN": "detail", "VPN users": "summary",
}
MODES = ("hidden", "summary", "detail")
LABELS = {
    "Device": "Apparati", "Interfaces": "Interfacce / porte", "Bridges": "Bridge",
    "VLAN": "VLAN", "IP Addresses": "Indirizzamento", "Routes / Gateway": "Routing",
    "DNS": "DNS", "DHCP": "DHCP", "DHCP leases": "Lease DHCP", "NAT": "NAT",
    "Firewall": "Firewall", "VPN": "VPN", "VPN users": "Utenti VPN",
}
NETWORK_DATASETS = (
    "Device", "Bridges", "VLAN", "IP Addresses", "Routes / Gateway", "DNS",
    "DHCP", "DHCP leases", "NAT", "Firewall", "VPN", "VPN users", "Interfaces",
)
DATASETS = {
    "client_info": "Informazioni generali",
    "sites": "Sedi",
    **{key: LABELS[key] for key in NETWORK_DATASETS},
}

# Explicit columns keep technical fields readable and never expose arbitrary JSON.
COLUMNS = {
    "Device": [("name", "Nome"), ("role", "Ruolo"), ("vendor", "Produttore"), ("platform", "Piattaforma"), ("model", "Modello"), ("serial_number", "Seriale"), ("os_version", "Versione"), ("management_ip", "IP management")],
    "Interfaces": [("port", "Porta"), ("default-name", "Nome originale"), ("name", "Nome"), ("type", "Tipo"), ("vlan_mode", "Modalità VLAN"), ("access_vlan", "VLAN access"), ("native_vlan", "VLAN nativa"), ("tagged_vlans", "VLAN tagged"), ("bridge", "Bridge"), ("slaves", "Slaves"), ("mode", "Bonding"), ("poe-out", "PoE"), ("mac-address", "MAC"), ("mtu", "MTU"), ("speed", "Velocità"), ("auto_negotiation", "Autonegotiation"), ("comment", "Note"), ("disabled", "Stato")],
    "Bridges": [("name", "Nome"), ("protocol-mode", "Protocollo"), ("vlan-filtering", "Filtro VLAN"), ("mac-address", "MAC"), ("comment", "Note"), ("disabled", "Stato")],
    "VLAN": [("vlan-id", "VLAN"), ("name", "Nome"), ("bridge", "Bridge"), ("comment", "Note"), ("disabled", "Stato")],
    "IP Addresses": [("address", "Indirizzo"), ("interface", "Interfaccia"), ("network", "Rete"), ("comment", "Note"), ("disabled", "Stato")],
    "Routes / Gateway": [("dst-address", "Destinazione"), ("gateway", "Gateway"), ("distance", "Distanza"), ("routing-table", "Tabella"), ("comment", "Note"), ("disabled", "Stato")],
    "DNS": [("server", "Server"), ("source", "Origine")],
    "DHCP": [("name", "Nome"), ("interface", "Interfaccia"), ("address", "Rete"), ("ranges", "Intervalli"), ("address-pool", "Pool"), ("lease-time", "Durata lease"), ("gateway", "Gateway"), ("dns-server", "DNS"), ("domain", "Dominio"), ("comment", "Note"), ("disabled", "Stato")],
    "DHCP leases": [("address", "Indirizzo"), ("mac-address", "MAC"), ("server", "Server"), ("host-name", "Host"), ("comment", "Note"), ("disabled", "Stato")],
    "NAT": [("chain", "Chain"), ("action", "Azione"), ("protocol", "Protocollo"), ("src-address", "Origine"), ("src-address-list", "Lista origine"), ("dst-address", "Destinazione"), ("dst-address-list", "Lista destinazione"), ("in-interface", "Ingresso"), ("out-interface", "Uscita"), ("dst-port", "Porta"), ("to-addresses", "Traduzione indirizzo"), ("to-ports", "Traduzione porta"), ("comment", "Note"), ("disabled", "Stato")],
    "Firewall": [("chain", "Chain"), ("action", "Azione"), ("protocol", "Protocollo"), ("src-address", "Origine"), ("src-address-list", "Lista origine"), ("dst-address", "Destinazione"), ("dst-address-list", "Lista destinazione"), ("in-interface", "Ingresso"), ("out-interface", "Uscita"), ("src-port", "Porta origine"), ("dst-port", "Porta destinazione"), ("connection-state", "Stato connessione"), ("comment", "Note"), ("disabled", "Stato")],
    "VPN": [("name", "Nome"), ("listen-port", "Porta ascolto"), ("remote-address", "Indirizzo remoto"), ("local-address", "Indirizzo locale"), ("tunnel-id", "Tunnel"), ("mtu", "MTU"), ("comment", "Note"), ("disabled", "Stato")],
    "VPN users": [("name", "Nome"), ("service", "Servizio"), ("profile", "Profilo"), ("remote-address", "Indirizzo remoto"), ("comment", "Note"), ("disabled", "Stato")],
}
SUMMARY_COLUMNS = {
    "Device": {"name", "role", "model", "management_ip"},
    "Interfaces": {"port", "name", "default-name", "type", "vlan_mode", "access_vlan", "native_vlan", "tagged_vlans", "bridge", "slaves", "poe-out", "comment", "disabled"},
    "Routes / Gateway": {"dst-address", "gateway", "comment", "disabled"},
    "VPN users": {"name", "service", "disabled"},
}


def get_global_settings():
    setting = db.session.get(DocumentationSetting, 1)
    return {**DEFAULT_MODES, **valid_modes(setting.configuration if setting else {})}


def valid_modes(configuration):
    return {section: mode for section, mode in configuration.items() if section in DEFAULT_MODES and mode in MODES}


def get_effective_mode(section, site, global_settings):
    overrides = valid_modes(site.documentation_overrides or {}) if site else {}
    return overrides.get(section, valid_modes(global_settings).get(section, DEFAULT_MODES[section]))


def item_fingerprint(section, item):
    canonical = json.dumps([section, item], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def excluded_items(device):
    return (device.data or {}).get("documentation", {}).get("excluded_items", {}) if device else {}


def is_documented_item(device, section, item):
    return item_fingerprint(section, item) not in excluded_items(device).get(section, [])


def update_exclusions(device, sections, documented_items):
    exclusions = {name: set(values) for name, values in excluded_items(device).items()}
    for section_index, (section, items) in enumerate(sections.items()):
        excluded = exclusions.setdefault(section, set())
        # Identical content has one fingerprint, including duplicate rows.
        current = {item_fingerprint(section, item) for item in items}
        unchecked = {item_fingerprint(section, item) for index, item in enumerate(items)
                     if f"{section_index}:{index}" not in documented_items}
        excluded.difference_update(current)
        excluded.update(unchecked)
    return {name: sorted(values) for name, values in exclusions.items() if values}


def significant_interface(item):
    name = item.get("name", "")
    default = item.get("default-name")
    renamed = name != default if default else bool(name and not re.fullmatch(r"(?:ether|port)\d+", name, re.I))
    return bool(renamed or "sfp" in (name + str(default or "")).lower()
                or item.get("type", "Ethernet").lower() != "ethernet"
                or any(item.get(key) for key in ("comment", "access_vlan", "native_vlan", "tagged_vlans", "bridge", "slaves", "disabled", "poe-out")))


def visible_columns(section, items, mode="detail"):
    allowed = SUMMARY_COLUMNS.get(section) if mode == "summary" else None
    return [(key, label) for key, label in COLUMNS[section]
            if (allowed is None or key in allowed) and any(item.get(key) not in (None, "", []) for item in items)]


def format_cell(item, key):
    value = item.get(key)
    if value is None or value == "":
        return "—"
    if key == "disabled":
        return "Disabilitato" if value else "Abilitato"
    if isinstance(value, bool):
        return "Sì" if value else "No"
    if isinstance(value, list):
        return ", ".join(str(part) for part in value)
    return value


_markdown = mistune.create_markdown(escape=True, plugins=["table"])


def render_markdown(value):
    return Markup(_markdown(value or ""))


def initialize_client_document(client):
    """Create the initial document once; an existing empty document stays empty."""
    document = ClientDocument.query.filter_by(client_id=client.id).first()
    if document is not None:
        return document
    document = ClientDocument(client_id=client.id)
    db.session.add(document)
    db.session.flush()
    definitions = (
        ("Informazioni generali", ["client_info"]),
        ("Sedi", ["sites"]),
        ("Rete", list(NETWORK_DATASETS)),
    )
    for section_position, (title, datasets) in enumerate(definitions):
        section = DocumentSection(document_id=document.id, title=title, position=section_position)
        db.session.add(section)
        db.session.flush()
        db.session.add_all([
            DocumentBlock(section_id=section.id, kind="dataset", position=position, dataset_key=dataset)
            for position, dataset in enumerate(datasets)
        ])
    return document


def initialize_missing_client_documents():
    from .models import Client

    for client in Client.query.order_by(Client.id):
        initialize_client_document(client)


def build_dataset_projection(client, dataset_key, site_id=None, global_settings=None):
    if dataset_key not in DATASETS:
        raise ValueError("Unsupported dataset")
    if site_id is not None:
        site = next((item for item in client.sites if item.id == site_id), None)
        if site is None:
            raise ValueError("Site does not belong to client")
    else:
        site = None

    if dataset_key == "client_info":
        fields = [
            ("Ragione sociale", client.company_name), ("Indirizzo", client.address),
            ("Città", client.city), ("Email", client.email),
            ("Telefono", client.phone), ("Sito web", client.website),
        ]
        return {"key": dataset_key, "label": DATASETS[dataset_key], "kind": "details",
                "rows": [(label, value) for label, value in fields if value]}

    if dataset_key == "sites":
        rows = [{"name": item.name, "address": item.address, "description": item.description}
                for item in sorted(client.sites, key=lambda item: (item.name.lower(), item.id))
                if site_id is None or item.id == site_id]
        if not rows:
            return None
        return {"key": dataset_key, "label": DATASETS[dataset_key], "kind": "sites", "rows": rows}

    settings = global_settings or get_global_settings()
    candidate_sites = [site] if site else [*sorted(client.sites, key=lambda item: (item.name.lower(), item.id)), None]
    groups = []
    for candidate_site in candidate_sites:
        mode = get_effective_mode(dataset_key, candidate_site, settings)
        if mode == "hidden":
            continue
        devices = sorted(
            (device for device in client.devices if device.site_id == (candidate_site.id if candidate_site else None)),
            key=lambda device: (device.name.lower(), device.id),
        )
        rows = []
        for device in devices:
            items = ([{key: getattr(device, key) for key, _ in COLUMNS["Device"]}]
                     if dataset_key == "Device" else device.sections.get(dataset_key, []))
            rows.extend(
                {"device_name": device.name, "item": item}
                for item in items
                if is_documented_item(device, dataset_key, item)
                and not (dataset_key == "Interfaces" and mode == "summary" and not significant_interface(item))
            )
        if rows:
            groups.append({
                "site": candidate_site, "mode": mode, "rows": rows,
                "columns": visible_columns(dataset_key, [row["item"] for row in rows], mode),
            })
    if not groups:
        return None
    return {"key": dataset_key, "label": DATASETS[dataset_key], "kind": "network",
            "scoped": site_id is not None, "groups": groups}


def _section_tree(document, client, global_settings, include_empty=False):
    sections = sorted(document.sections, key=lambda item: (item.position, item.id))
    children = {}
    for section in sections:
        children.setdefault(section.parent_id, []).append(section)

    def build(section):
        blocks = []
        for block in sorted(section.blocks, key=lambda item: (item.position, item.id)):
            if block.kind == "markdown":
                if include_empty or (block.markdown or "").strip():
                    blocks.append({"model": block, "html": render_markdown(block.markdown)})
            else:
                projection = build_dataset_projection(client, block.dataset_key, block.site_id, global_settings)
                if include_empty or projection:
                    blocks.append({"model": block, "projection": projection})
        child_nodes = [build(child) for child in children.get(section.id, [])]
        child_nodes = [child for child in child_nodes if include_empty or child["visible"]]
        return {"model": section, "blocks": blocks, "children": child_nodes,
                "visible": bool(blocks or child_nodes)}

    return [node for section in children.get(None, []) if (node := build(section))["visible"] or include_empty]


def build_composed_document_context(client, include_empty=False):
    document = initialize_client_document(client)
    tree = _section_tree(document, client, get_global_settings(), include_empty)
    visible_tree = tree if not include_empty else _section_tree(document, client, get_global_settings())
    return {"client": client, "document": document, "section_tree": tree,
            "visible_section_tree": visible_tree, "datasets": DATASETS, "format_cell": format_cell}


def build_document_context(client, global_settings):
    """Legacy aggregate retained for import-preview compatibility and focused tests."""
    sites = sorted(client.sites, key=lambda site: site.name.lower())
    groups = []
    for site in [*sites, None]:
        blocks = []
        for section in NETWORK_DATASETS:
            projection = build_dataset_projection(client, section, site.id if site else None, global_settings)
            if projection:
                group = next((item for item in projection["groups"]
                              if item["site"] is site or (site is None and item["site"] is None)), None)
                if group:
                    blocks.append({"section": section, "label": LABELS[section], **group})
        if blocks:
            groups.append({"site": site, "blocks": blocks})
    return {"client": client, "sites": sites, "groups": groups, "format_cell": format_cell}
