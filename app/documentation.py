"""Document preferences and projection of the current technical snapshot."""

import hashlib
import json
import re

from .extensions import db
from .models import DocumentationSetting


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


def build_document_context(client, global_settings):
    sites = sorted(client.sites, key=lambda site: site.name.lower())
    groups = []
    for site in [*sites, None]:
        devices = sorted((device for device in client.devices if device.site_id == (site.id if site else None)), key=lambda device: device.name.lower())
        blocks = []
        for section in ["Device", "Bridges", "VLAN", "IP Addresses", "Routes / Gateway", "DNS", "DHCP", "DHCP leases", "NAT", "Firewall", "VPN", "VPN users", "Interfaces"]:
            mode = get_effective_mode(section, site, global_settings)
            if mode == "hidden":
                continue
            rows = []
            for device in devices:
                items = [{key: getattr(device, key) for key, _ in COLUMNS["Device"]}] if section == "Device" else device.sections.get(section, [])
                rows.extend({"device_name": device.name, "item": item} for item in items
                            if is_documented_item(device, section, item)
                            and not (section == "Interfaces" and mode == "summary" and not significant_interface(item)))
            if rows:
                blocks.append({"section": section, "label": LABELS[section], "mode": mode, "rows": rows,
                               "columns": visible_columns(section, [row["item"] for row in rows], mode)})
        if blocks:
            groups.append({"site": site, "blocks": blocks})
    return {"client": client, "sites": sites, "groups": groups, "format_cell": format_cell}
