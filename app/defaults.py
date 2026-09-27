INTEGRATIONS = {
    "mikrotik": {
        "label": "MikroTik",
        "items": ["Device", "Interfaces", "Bridges", "VLAN", "IP Addresses", "Routes / Gateway", "DNS", "DHCP", "NAT", "Firewall", "VPN"],
    },
    "unifi": {
        "label": "UniFi",
        "items": ["Gateway", "Switch", "Access Point", "Networks", "VLAN", "SSID"],
    },
    "snipeit": {
        "label": "Snipe-IT",
        "items": ["Categorie", "Location", "Status"],
    },
}


def default_integration_configuration(integration_type):
    return {
        "enabled_items": INTEGRATIONS[integration_type]["items"],
        "excluded_items_policy": "remember",
    }

