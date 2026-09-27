from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..defaults import INTEGRATIONS
from ..extensions import db
from ..models import Site, Source
from .helpers import current_client_or_404


bp = Blueprint("sources", __name__, url_prefix="/sources")


def apply_form(source, client):
    integration_type = request.form["integration_type"]
    if integration_type not in INTEGRATIONS:
        raise ValueError("Unsupported integration type")
    site_id = request.form.get("site_id", type=int)
    if site_id and not Site.query.filter_by(id=site_id, client_id=client.id).first():
        raise ValueError("Invalid site")
    source.integration_type = integration_type
    source.name = request.form["name"].strip()
    source.site_id = site_id
    mode = "custom" if request.form.get("settings_mode") == "custom" else "global"
    source.configuration = {"mode": mode}


@bp.get("")
def index():
    client = current_client_or_404()
    sources = Source.query.filter_by(client_id=client.id).order_by(Source.name).all()
    return render_template("sources/index.html", sources=sources)


@bp.route("/new", methods=["GET", "POST"])
def create():
    client = current_client_or_404()
    if request.method == "POST":
        source = Source(client_id=client.id)
        apply_form(source, client)
        db.session.add(source)
        db.session.commit()
        flash("Fonte creata.", "success")
        return redirect(url_for("sources.index"))
    return render_template("sources/form.html", source=None, sites=Site.query.filter_by(client_id=client.id).order_by(Site.name).all())


@bp.route("/<int:source_id>/edit", methods=["GET", "POST"])
def edit(source_id):
    client = current_client_or_404()
    source = Source.query.filter_by(id=source_id, client_id=client.id).first_or_404()
    if request.method == "POST":
        apply_form(source, client)
        db.session.commit()
        flash("Fonte aggiornata.", "success")
        return redirect(url_for("sources.index"))
    return render_template("sources/form.html", source=source, sites=Site.query.filter_by(client_id=client.id).order_by(Site.name).all())


@bp.post("/<int:source_id>/delete")
def delete(source_id):
    client = current_client_or_404()
    source = Source.query.filter_by(id=source_id, client_id=client.id).first_or_404()
    db.session.delete(source)
    db.session.commit()
    flash("Fonte eliminata.", "success")
    return redirect(url_for("sources.index"))

