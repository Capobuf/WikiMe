from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import Site
from .helpers import current_client_or_404


bp = Blueprint("sites", __name__, url_prefix="/sites")


def apply_form(site):
    site.name = request.form["name"].strip()
    for field in ("address", "description", "notes"):
        setattr(site, field, request.form.get(field, "").strip() or None)


@bp.get("")
def index():
    client = current_client_or_404()
    sites = Site.query.filter_by(client_id=client.id).order_by(Site.name).all()
    return render_template("sites/index.html", sites=sites)


@bp.route("/new", methods=["GET", "POST"])
def create():
    client = current_client_or_404()
    if request.method == "POST":
        site = Site(client_id=client.id)
        apply_form(site)
        db.session.add(site)
        db.session.commit()
        flash("Sede creata.", "success")
        return redirect(url_for("sites.index"))
    return render_template("sites/form.html", site=None)


@bp.route("/<int:site_id>/edit", methods=["GET", "POST"])
def edit(site_id):
    client = current_client_or_404()
    site = Site.query.filter_by(id=site_id, client_id=client.id).first_or_404()
    if request.method == "POST":
        apply_form(site)
        db.session.commit()
        flash("Sede aggiornata.", "success")
        return redirect(url_for("sites.index"))
    return render_template("sites/form.html", site=site)


@bp.post("/<int:site_id>/delete")
def delete(site_id):
    client = current_client_or_404()
    site = Site.query.filter_by(id=site_id, client_id=client.id).first_or_404()
    for source in site.sources:
        source.site_id = None
    for device in site.devices:
        device.site_id = None
    db.session.delete(site)
    db.session.commit()
    flash("Sede eliminata.", "success")
    return redirect(url_for("sites.index"))
