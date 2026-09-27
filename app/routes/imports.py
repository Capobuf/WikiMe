from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..extensions import db
from ..importers import MAX_FILE_BYTES, MAX_FILES, ImportParseError, decode_configuration, parse_configuration, safe_filename, split_pasted_configurations
from ..models import Device, IntegrationSetting, Site, Source, utc_now
from .helpers import current_client_or_404


bp = Blueprint("imports", __name__, url_prefix="/imports")
PREVIEW_MAX_AGE_SECONDS = 60 * 60

SECTION_SETTING = {
    "Interfaces": "Interfaces",
    "Bridge ports": "Bridges",
    "Bridges": "Bridges",
    "VLAN": "VLAN",
    "IP Addresses": "IP Addresses",
    "Routes / Gateway": "Routes / Gateway",
    "DNS": "DNS",
    "DHCP": "DHCP",
    "DHCP leases": "DHCP",
    "NAT": "NAT",
    "Firewall": "Firewall",
    "VPN": "VPN",
    "VPN users": "VPN",
}


def _preview_serializer():
    return URLSafeTimedSerializer(current_app.secret_key, salt="wikime-import-preview")


def _owned_site_and_source(client):
    site_id = request.form.get("site_id", type=int)
    source_id = request.form.get("source_id", type=int)
    site = Site.query.filter_by(id=site_id, client_id=client.id).first() if site_id else None
    source = Source.query.filter_by(id=source_id, client_id=client.id).first() if source_id else None
    if site_id and not site:
        raise ImportParseError("La sede selezionata non appartiene al cliente corrente.")
    if source_id and (not source or source.integration_type != "mikrotik"):
        raise ImportParseError("La fonte selezionata non è una fonte MikroTik valida.")
    return site, source


def _apply_global_settings(candidate):
    setting = db.session.get(IntegrationSetting, "mikrotik")
    enabled = set((setting.configuration if setting else {}).get("enabled_items", []))
    sections = candidate["sections"]
    excluded = [name for name in sections if SECTION_SETTING.get(name, name) not in enabled]
    candidate["sections"] = {name: items for name, items in sections.items() if name not in excluded}
    candidate["excluded_sections"] = excluded
    return candidate


@bp.get("")
def index():
    client = current_client_or_404()
    return render_template(
        "imports/index.html",
        sites=Site.query.filter_by(client_id=client.id).order_by(Site.name).all(),
        sources=Source.query.filter_by(client_id=client.id, integration_type="mikrotik").order_by(Source.name).all(),
    )


@bp.post("/analyze")
def analyze():
    client = current_client_or_404()
    try:
        site, source = _owned_site_and_source(client)
    except ImportParseError as error:
        flash(str(error), "danger")
        return redirect(url_for("imports.index"))

    inputs = []
    uploads = [item for item in request.files.getlist("files") if item and item.filename]
    pasted = request.form.get("configuration", "").strip()
    if len(uploads) > MAX_FILES:
        flash(f"Puoi analizzare al massimo {MAX_FILES} file alla volta.", "danger")
        return redirect(url_for("imports.index"))
    for uploaded in uploads:
        content = uploaded.stream.read(MAX_FILE_BYTES + 1)
        try:
            inputs.append((safe_filename(uploaded.filename), decode_configuration(content)))
        except ImportParseError as error:
            flash(f"{safe_filename(uploaded.filename)}: {error}", "danger")
    if pasted:
        for index, part in enumerate(split_pasted_configurations(pasted), start=1):
            inputs.append((f"testo-incollato-{index}", part))
    if not inputs:
        flash("Seleziona almeno un file oppure incolla una configurazione.", "warning")
        return redirect(url_for("imports.index"))
    if len(inputs) > MAX_FILES:
        flash(f"Puoi analizzare al massimo {MAX_FILES} configurazioni alla volta.", "danger")
        return redirect(url_for("imports.index"))

    candidates = []
    for filename, text in inputs:
        try:
            candidates.append(_apply_global_settings(parse_configuration(text, filename).as_dict()))
        except ImportParseError as error:
            flash(f"{filename}: {error}", "danger")
    if not candidates:
        return redirect(url_for("imports.index"))

    preview_token = _preview_serializer().dumps({
        "client_id": client.id,
        "site_id": site.id if site else None,
        "source_id": source.id if source else None,
        "candidates": candidates,
    })
    return render_template("imports/preview.html", candidates=candidates, preview_token=preview_token, site=site, source=source)


def _automatic_source(client, site):
    source = Source.query.filter_by(client_id=client.id, integration_type="mikrotik", name="Import configurazioni MikroTik").first()
    if source is None:
        source = Source(
            client_id=client.id,
            site_id=site.id if site else None,
            integration_type="mikrotik",
            name="Import configurazioni MikroTik",
            configuration={"mode": "global", "kind": "file_import"},
        )
        db.session.add(source)
        db.session.flush()
    return source


def _existing_device(client_id, device_data):
    serial = device_data.get("serial_number")
    if serial:
        existing = Device.query.filter_by(client_id=client_id, serial_number=serial).first()
        if existing:
            return existing
    return Device.query.filter_by(
        client_id=client_id,
        platform=device_data.get("platform"),
        name=device_data["name"],
    ).first()


@bp.post("/commit")
def commit():
    client = current_client_or_404()
    try:
        preview = _preview_serializer().loads(request.form.get("preview_token", ""), max_age=PREVIEW_MAX_AGE_SECONDS)
    except SignatureExpired:
        flash("L’anteprima è scaduta. Analizza nuovamente le configurazioni.", "warning")
        return redirect(url_for("imports.index"))
    except BadSignature:
        flash("Anteprima non valida. Analizza nuovamente le configurazioni.", "danger")
        return redirect(url_for("imports.index"))
    if preview.get("client_id") != client.id:
        flash("L’anteprima non appartiene al cliente corrente.", "danger")
        return redirect(url_for("imports.index"))

    selected = {int(value) for value in request.form.getlist("candidates") if value.isdigit()}
    if not selected:
        flash("Seleziona almeno un dispositivo da importare.", "warning")
        return redirect(url_for("imports.index"))

    site_id = preview.get("site_id")
    source_id = preview.get("source_id")
    site = Site.query.filter_by(id=site_id, client_id=client.id).first() if site_id else None
    source = Source.query.filter_by(id=source_id, client_id=client.id).first() if source_id else None
    source = source or _automatic_source(client, site)
    created = updated = 0

    for index, candidate in enumerate(preview.get("candidates", [])):
        if index not in selected:
            continue
        details = candidate["device"]
        device = _existing_device(client.id, details)
        if device is None:
            device = Device(client_id=client.id, name=details["name"], fingerprint=candidate["fingerprint"])
            db.session.add(device)
            created += 1
        else:
            updated += 1
        selected_items = set(request.form.getlist(f"items_{index}"))
        sections = {}
        for section_index, (name, items) in enumerate(candidate["sections"].items()):
            included = [item for item_index, item in enumerate(items) if f"{section_index}:{item_index}" in selected_items]
            if included:
                sections[name] = included
        device.name = details["name"]
        for field in ("vendor", "platform", "role", "model", "serial_number", "os_version", "management_ip"):
            setattr(device, field, details.get(field))
        device.site_id = site.id if site else device.site_id
        device.source_id = source.id
        device.fingerprint = candidate["fingerprint"]
        device.data = {
            "sections": sections,
            "import": {
                "filename": candidate["filename"],
                "format": candidate["format"],
                "warnings": candidate.get("warnings", []),
            },
        }
        device.imported_at = utc_now()
        db.session.flush()

    db.session.commit()
    flash(f"Importazione completata: {created} dispositivi creati, {updated} aggiornati.", "success")
    return redirect(url_for("devices.index"))
