from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import Device, Site
from .helpers import current_client_or_404


bp = Blueprint("devices", __name__, url_prefix="/devices")


@bp.get("")
def index():
    client = current_client_or_404()
    devices = Device.query.filter_by(client_id=client.id).order_by(Device.name).all()
    return render_template("devices/index.html", devices=devices)


@bp.get("/<int:device_id>")
def detail(device_id):
    client = current_client_or_404()
    device = Device.query.filter_by(id=device_id, client_id=client.id).first_or_404()
    return render_template("devices/detail.html", device=device)


@bp.route("/<int:device_id>/edit", methods=["GET", "POST"])
def edit(device_id):
    client = current_client_or_404()
    device = Device.query.filter_by(id=device_id, client_id=client.id).first_or_404()
    sites = Site.query.filter_by(client_id=client.id).order_by(Site.name).all()
    if request.method == "POST":
        site_id = request.form.get("site_id", type=int)
        if site_id and not Site.query.filter_by(id=site_id, client_id=client.id).first():
            flash("Sede non valida.", "danger")
            return render_template("devices/form.html", device=device, sites=sites)
        device.name = request.form.get("name", "").strip()
        if not device.name:
            flash("Il nome è obbligatorio.", "danger")
            return render_template("devices/form.html", device=device, sites=sites)
        for field in ("vendor", "platform", "role", "model", "serial_number", "os_version", "management_ip", "notes"):
            setattr(device, field, request.form.get(field, "").strip() or None)
        device.site_id = site_id
        db.session.commit()
        flash("Dispositivo aggiornato.", "success")
        return redirect(url_for("devices.detail", device_id=device.id))
    return render_template("devices/form.html", device=device, sites=sites)


@bp.post("/<int:device_id>/delete")
def delete(device_id):
    client = current_client_or_404()
    device = Device.query.filter_by(id=device_id, client_id=client.id).first_or_404()
    db.session.delete(device)
    db.session.commit()
    flash("Dispositivo eliminato.", "success")
    return redirect(url_for("devices.index"))
