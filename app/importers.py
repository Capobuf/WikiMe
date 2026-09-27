"""Parser sicuri per export di configurazioni di apparati di rete.

I parser sono intenzionalmente basati su whitelist: estraggono soltanto i campi
utili alla documentazione e non conservano mai il testo originale, password,
secret, community SNMP o chiavi.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path


MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_FILES = 20


class ImportParseError(ValueError):
    pass


@dataclass
class ParsedConfiguration:
    filename: str
    format: str
    device: dict
    sections: dict[str, list[dict]]
    warnings: list[str] = field(default_factory=list)

    def as_dict(self):
        payload = {
            "filename": self.filename,
            "format": self.format,
            "device": self.device,
            "sections": self.sections,
            "warnings": self.warnings,
        }
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        payload["fingerprint"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return payload


def safe_filename(value: str | None, fallback="configurazione"):
    name = Path(value or fallback).name
    return re.sub(r"[^\w.() +\-]", "_", name, flags=re.UNICODE)[:180] or fallback


def decode_configuration(content: bytes):
    if len(content) > MAX_FILE_BYTES:
        raise ImportParseError("Il file supera il limite di 5 MB.")
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ImportParseError("Codifica del file non riconosciuta.")


def parse_configuration(text: str, filename: str = "configurazione"):
    if not text or not text.strip():
        raise ImportParseError("La configurazione è vuota.")
    if len(text.encode("utf-8")) > MAX_FILE_BYTES:
        raise ImportParseError("La configurazione supera il limite di 5 MB.")
    if re.search(r"(?m)^# .* by RouterOS ", text) or re.search(r"(?m)^/system identity\s*$", text):
        return parse_routeros(text, safe_filename(filename))
    if "sys.b:" in text and "link.b:" in text:
        return parse_switchos(text, safe_filename(filename))
    raise ImportParseError("Formato non riconosciuto: sono supportati export RouterOS .rsc e SwitchOS .swb.")


def split_pasted_configurations(text: str):
    """Divide più export RouterOS incollati; gli altri formati restano singoli."""
    starts = list(re.finditer(r"(?m)^# .* by RouterOS [^\r\n]+", text))
    if len(starts) <= 1:
        return [text]
    return [text[item.start() : starts[index + 1].start() if index + 1 < len(starts) else None] for index, item in enumerate(starts)]


def _logical_routeros_lines(text: str):
    current = ""
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = raw_line.strip()
        if current:
            current += stripped
        else:
            current = stripped
        if current.endswith("\\"):
            current = current[:-1]
            continue
        if current:
            yield current
        current = ""
    if current:
        yield current


def _command_properties(command: str):
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    result = {}
    for token in tokens[1:]:
        if token.startswith("!"):
            continue
        if "=" in token:
            key, value = token.split("=", 1)
            result[key] = value
    return result


def _pick(properties: dict, fields: tuple[str, ...]):
    result = {field: properties[field] for field in fields if properties.get(field) not in (None, "")}
    disabled = result.pop("disabled", None)
    if disabled == "yes":
        result["disabled"] = True
    return result


ROUTEROS_SECTIONS = {
    "/interface ethernet": ("Interfaces", ("name", "default-name", "mac-address", "comment", "disabled", "mtu", "speed", "poe-out")),
    "/interface bridge": ("Bridges", ("name", "mac-address", "comment", "disabled", "protocol-mode", "vlan-filtering")),
    "/interface bridge port": ("Bridge ports", ("interface", "bridge", "pvid", "frame-types", "comment", "disabled")),
    "/interface bridge vlan": ("VLAN", ("bridge", "vlan-ids", "tagged", "untagged", "comment", "disabled")),
    "/interface vlan": ("VLAN", ("name", "vlan-id", "interface", "comment", "disabled")),
    "/interface bonding": ("Interfaces", ("name", "slaves", "mode", "comment", "disabled")),
    "/ip address": ("IP Addresses", ("address", "network", "interface", "comment", "disabled")),
    "/ip route": ("Routes / Gateway", ("dst-address", "gateway", "distance", "routing-table", "comment", "disabled")),
    "/ip pool": ("DHCP", ("name", "ranges", "comment")),
    "/ip dhcp-server": ("DHCP", ("name", "interface", "address-pool", "lease-time", "comment", "disabled")),
    "/ip dhcp-server network": ("DHCP", ("address", "gateway", "dns-server", "domain", "comment")),
    "/ip dhcp-server lease": ("DHCP leases", ("address", "mac-address", "server", "host-name", "comment", "disabled")),
    "/ip firewall nat": ("NAT", ("chain", "action", "protocol", "src-address", "dst-address", "src-address-list", "dst-address-list", "in-interface", "out-interface", "dst-port", "to-addresses", "to-ports", "comment", "disabled")),
    "/ip firewall filter": ("Firewall", ("chain", "action", "protocol", "src-address", "dst-address", "src-address-list", "dst-address-list", "in-interface", "out-interface", "src-port", "dst-port", "connection-state", "comment", "disabled")),
    "/interface wireguard": ("VPN", ("name", "listen-port", "mtu", "comment", "disabled")),
    "/interface eoip": ("VPN", ("name", "remote-address", "tunnel-id", "comment", "disabled")),
    "/interface gre": ("VPN", ("name", "remote-address", "local-address", "comment", "disabled")),
    "/ppp secret": ("VPN users", ("name", "service", "profile", "remote-address", "comment", "disabled")),
}


def parse_routeros(text: str, filename: str):
    version_match = re.search(r"(?m)^# .* by RouterOS ([^\s]+)", text)
    model_match = re.search(r"(?mi)^# model\s*=\s*(.+)$", text)
    serial_match = re.search(r"(?mi)^# serial number\s*=\s*(.+)$", text)
    identity = None
    current_section = None
    sections: dict[str, list[dict]] = {}
    dns_servers = []

    for line in _logical_routeros_lines(text):
        if line.startswith("/"):
            current_section = line
            continue
        if not current_section or line.startswith("#") or not (line.startswith("add ") or line.startswith("set ")):
            continue
        props = _command_properties(line)
        if current_section == "/system identity" and line.startswith("set "):
            identity = props.get("name")
            continue
        if current_section == "/ip dns" and line.startswith("set "):
            for source_key, source_label in (("servers", "Statico"), ("dynamic-servers", "Dinamico")):
                for server in props.get(source_key, "").split(","):
                    if server and not any(item["server"] == server for item in dns_servers):
                        dns_servers.append({"server": server, "source": source_label})
            continue
        definition = ROUTEROS_SECTIONS.get(current_section)
        if not definition:
            continue
        section_name, fields = definition
        item = _pick(props, fields)
        if item:
            sections.setdefault(section_name, []).append(item)

    if dns_servers:
        sections["DNS"] = dns_servers

    _enrich_routeros_network_data(sections)

    model = model_match.group(1).strip() if model_match else None
    serial = serial_match.group(1).strip() if serial_match else None
    name = identity or (model and f"MikroTik {model}") or Path(filename).stem
    role = "Switch" if model and model.upper().startswith(("CRS", "CSS")) else "Router"
    management_ip = _routeros_management_ip(sections)
    device = {
        "name": name,
        "vendor": "MikroTik",
        "platform": "RouterOS",
        "role": role,
        "model": model,
        "serial_number": serial,
        "os_version": version_match.group(1) if version_match else None,
        "management_ip": management_ip,
    }
    device = {key: value for key, value in device.items() if value not in (None, "")}
    warnings = []
    if not identity:
        warnings.append("Identità RouterOS non presente: è stato proposto un nome dal modello o dal file.")
    return ParsedConfiguration(filename, "routeros", device, sections, warnings)


def _split_values(value):
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _vlan_sort_key(value):
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, str(value))


def _apply_port_vlan_properties(interface: dict, pvid, tagged, untagged):
    tagged = sorted(set(tagged), key=_vlan_sort_key)
    untagged = sorted(set(untagged), key=_vlan_sort_key)
    native = str(pvid) if pvid not in (None, "") else (untagged[0] if untagged else None)
    if tagged:
        interface["vlan_mode"] = "trunk"
        interface["tagged_vlans"] = tagged
        if native:
            interface["native_vlan"] = native
    elif native:
        interface["vlan_mode"] = "access"
        interface["access_vlan"] = native


def _enrich_routeros_network_data(sections: dict):
    """Sposta appartenenza e modalità VLAN dalle righe VLAN alle porte."""
    interfaces = {item.get("name") or item.get("default-name"): item for item in sections.get("Interfaces", [])}
    port_state = {}
    for bridge_port in sections.pop("Bridge ports", []):
        name = bridge_port.get("interface")
        if not name:
            continue
        state = port_state.setdefault(name, {"tagged": [], "untagged": []})
        state["pvid"] = bridge_port.get("pvid")
        target = interfaces.get(name)
        if target:
            if bridge_port.get("bridge"):
                target["bridge"] = bridge_port["bridge"]
            if bridge_port.get("disabled"):
                target["disabled"] = True

    vlan_definitions = {}
    for vlan in sections.get("VLAN", []):
        vlan_ids = _split_values(vlan.get("vlan-ids") or vlan.get("vlan-id"))
        for vlan_id in vlan_ids:
            for name in _split_values(vlan.get("tagged")):
                port_state.setdefault(name, {"tagged": [], "untagged": []})["tagged"].append(vlan_id)
            for name in _split_values(vlan.get("untagged")):
                port_state.setdefault(name, {"tagged": [], "untagged": []})["untagged"].append(vlan_id)
            parent = vlan.get("interface")
            if parent in interfaces:
                port_state.setdefault(parent, {"tagged": [], "untagged": []})["tagged"].append(vlan_id)

            definition = vlan_definitions.setdefault(vlan_id, {"vlan-id": vlan_id})
            for source_key, target_key in (("name", "name"), ("comment", "comment"), ("bridge", "bridge")):
                if vlan.get(source_key) and not definition.get(target_key):
                    definition[target_key] = vlan[source_key]
            if vlan.get("disabled"):
                definition["disabled"] = True

    for name, state in port_state.items():
        target = interfaces.get(name)
        if target:
            _apply_port_vlan_properties(target, state.get("pvid"), state["tagged"], state["untagged"])
    if vlan_definitions:
        sections["VLAN"] = sorted(vlan_definitions.values(), key=lambda item: _vlan_sort_key(item["vlan-id"]))


def _routeros_management_ip(sections: dict):
    addresses = sections.get("IP Addresses", [])
    for item in addresses:
        marker = f"{item.get('comment', '')} {item.get('interface', '')}".lower()
        if "management" in marker or "mgmt" in marker:
            return item.get("address", "").split("/", 1)[0] or None
    for item in addresses:
        value = item.get("address", "").split("/", 1)[0]
        try:
            if ipaddress.ip_address(value).is_private:
                return value
        except ValueError:
            pass
    return None


def _decode_hex_string(value: str):
    try:
        return bytes.fromhex(value).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return value


def _extract_switchos_block(text: str, key: str):
    match = re.search(rf"(?:^|,)\s*{re.escape(key)}:\{{", text)
    if not match:
        return None
    start = match.end() - 1
    depth = 0
    quote = None
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if char == quote and text[index - 1] != "\\":
                quote = None
            continue
        if char in "'\"":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : index]
    return None


def _switchos_array(block: str, key: str):
    match = re.search(rf"(?:^|,)\s*{re.escape(key)}:\[([^\]]*)\]", block or "")
    if not match:
        return []
    return [item.strip().strip("'\"") for item in match.group(1).split(",")]


def _switchos_scalar(block: str, key: str):
    match = re.search(rf"(?:^|,)\s*{re.escape(key)}:(?:'([^']*)'|\"([^\"]*)\"|([^,}}]+))", block or "")
    if not match:
        return None
    return next((value.strip() for value in match.groups() if value is not None), None)


def _switchos_number(value: str | None):
    if not value:
        return None
    try:
        return int(value, 0)
    except ValueError:
        return None


def _switchos_ip(value: str | None):
    number = _switchos_number(value)
    if number is None:
        return None
    return ".".join(str((number >> shift) & 0xFF) for shift in (0, 8, 16, 24))


def parse_switchos(text: str, filename: str):
    sys_block = _extract_switchos_block(text, "sys.b")
    link_block = _extract_switchos_block(text, "link.b")
    fwd_block = _extract_switchos_block(text, "fwd.b")
    if not sys_block or not link_block:
        raise ImportParseError("Backup SwitchOS incompleto o non riconosciuto.")

    identity_hex = _switchos_scalar(sys_block, "id")
    identity = _decode_hex_string(identity_hex) if identity_hex else Path(filename).stem
    management_ip = _switchos_ip(_switchos_scalar(sys_block, "ip"))
    filename_info = re.match(r"(?i)^(CSS[\w-]+?)[_.-](\d+(?:\.\d+)+)$", Path(filename).stem)
    port_names = [_decode_hex_string(value) for value in _switchos_array(link_block, "nm") if value]
    enabled_mask = _switchos_number(_switchos_scalar(link_block, "en"))
    auto_mask = _switchos_number(_switchos_scalar(link_block, "an"))
    sfp_flags = [_switchos_number(value) or 0 for value in _switchos_array(link_block, "sfpr")]
    default_vlans = [_switchos_number(value) for value in _switchos_array(fwd_block, "dvid")]
    interfaces = []
    for index, name in enumerate(port_names):
        interface = {
            "name": name or f"Port{index + 1}",
            "port": index + 1,
            "type": "SFP" if index < len(sfp_flags) and sfp_flags[index] else "Ethernet",
        }
        if enabled_mask is not None and not enabled_mask & (1 << index):
            interface["disabled"] = True
        if auto_mask is not None and not auto_mask & (1 << index):
            interface["auto_negotiation"] = False
        interfaces.append(interface)

    vlans = []
    vlan_match = re.search(r"vlan\.b:\[(.*?)\],lacp\.b:", text, re.DOTALL)
    if vlan_match:
        for record in re.finditer(r"\{([^{}]+)\}", vlan_match.group(1)):
            body = record.group(1)
            name_hex = _switchos_scalar(body, "nm")
            vid = _switchos_number(_switchos_scalar(body, "vid"))
            members = _switchos_number(_switchos_scalar(body, "mbr"))
            item = {"name": _decode_hex_string(name_hex) if name_hex else f"VLAN {vid}", "vlan-id": vid}
            if members is not None:
                item["_member_ports"] = [index + 1 for index in range(len(port_names)) if members & (1 << index)]
            vlans.append(item)

    memberships = {index + 1: [] for index in range(len(port_names))}
    for vlan in vlans:
        for port in vlan.pop("_member_ports", []):
            memberships[port].append(str(vlan["vlan-id"]))
    for index, interface in enumerate(interfaces):
        pvid = default_vlans[index] if index < len(default_vlans) else None
        pvid = pvid if pvid is not None else 1
        tagged = [vlan for vlan in memberships[index + 1] if vlan != str(pvid)]
        _apply_port_vlan_properties(interface, pvid, tagged, [str(pvid)])

    sections = {"Interfaces": interfaces}
    if vlans:
        sections["VLAN"] = vlans
    device = {
        "name": identity,
        "vendor": "MikroTik",
        "platform": "SwitchOS",
        "role": "Switch",
        "model": filename_info.group(1).upper() if filename_info else None,
        "os_version": filename_info.group(2) if filename_info else None,
        "management_ip": management_ip,
        "port_count": len(port_names),
    }
    device = {key: value for key, value in device.items() if value not in (None, "")}
    warnings = ["Il formato SwitchOS non include sempre modello, seriale e versione: i campi non disponibili restano vuoti."]
    if filename_info:
        warnings = ["Modello e versione SwitchOS sono stati dedotti dal nome del file; verificane la correttezza."]
    return ParsedConfiguration(filename, "switchos", device, sections, warnings)
