from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from ..extensions import db
from ..models import Client


bp = Blueprint("clients", __name__, url_prefix="/clients")


def apply_form(client):
    client.company_name = request.form["company_name"].strip()
    for field in ("display_name", "address", "city", "email", "phone", "website", "notes"):
        setattr(client, field, request.form.get(field, "").strip() or None)


@bp.get("")
def index():
    return render_template("clients/index.html", clients=Client.query.order_by(Client.company_name).all())


@bp.route("/new", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        client = Client()
        apply_form(client)
        if not client.company_name:
            flash("La ragione sociale è obbligatoria.", "danger")
        else:
            db.session.add(client)
            db.session.commit()
            flash("Cliente creato.", "success")
            return redirect(url_for("clients.index"))
    return render_template("clients/form.html", client=None)


@bp.route("/<int:client_id>/edit", methods=["GET", "POST"])
def edit(client_id):
    client = db.get_or_404(Client, client_id)
    if request.method == "POST":
        apply_form(client)
        db.session.commit()
        flash("Cliente aggiornato.", "success")
        return redirect(url_for("clients.index"))
    return render_template("clients/form.html", client=client)


@bp.post("/<int:client_id>/delete")
def delete(client_id):
    client = db.get_or_404(Client, client_id)
    db.session.delete(client)
    db.session.commit()
    if session.get("current_client_id") == client_id:
        session.pop("current_client_id", None)
    flash("Cliente eliminato.", "success")
    return redirect(url_for("clients.index"))


@bp.post("/<int:client_id>/select")
def select(client_id):
    client = db.get_or_404(Client, client_id)
    session["current_client_id"] = client.id
    flash(f"Cliente corrente: {client.name}.", "success")
    return redirect(request.form.get("next") or url_for("main.dashboard"))

