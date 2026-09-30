from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..documentation import DATASETS, build_composed_document_context
from ..extensions import db
from ..models import ClientDocument, DocumentBlock, DocumentSection, Site
from .helpers import current_client_or_404


bp = Blueprint("documentation", __name__, url_prefix="/documentation")


def _section_or_404(section_id):
    client = current_client_or_404()
    return (DocumentSection.query.join(ClientDocument)
            .filter(DocumentSection.id == section_id, ClientDocument.client_id == client.id)
            .first_or_404())


def _block_or_404(block_id):
    client = current_client_or_404()
    return (DocumentBlock.query.join(DocumentSection).join(ClientDocument)
            .filter(DocumentBlock.id == block_id, ClientDocument.client_id == client.id)
            .first_or_404())


def _ordered_siblings(section):
    return (DocumentSection.query
            .filter_by(document_id=section.document_id, parent_id=section.parent_id)
            .order_by(DocumentSection.position, DocumentSection.id).all())


def _ordered_blocks(block):
    return (DocumentBlock.query.filter_by(section_id=block.section_id)
            .order_by(DocumentBlock.position, DocumentBlock.id).all())


def _move(item, ordered, offset):
    index = next(index for index, candidate in enumerate(ordered) if candidate.id == item.id)
    target_index = index + offset
    if target_index < 0 or target_index >= len(ordered):
        return False
    for position, candidate in enumerate(ordered):
        candidate.position = position
    target = ordered[target_index]
    item.position, target.position = target.position, item.position
    return True


@bp.get("")
def index():
    client = current_client_or_404()
    return render_template("documentation.html", **build_composed_document_context(client, include_empty=True))


@bp.post("/sections/new")
def section_create():
    client = current_client_or_404()
    document = client.document
    parent_id = request.form.get("parent_id", type=int)
    parent = _section_or_404(parent_id) if parent_id else None
    title = request.form.get("title", "").strip()
    if not title:
        flash("Il titolo della sezione è obbligatorio.", "danger")
        return redirect(url_for("documentation.index"))
    siblings = DocumentSection.query.filter_by(document_id=document.id, parent_id=parent.id if parent else None)
    last_sibling = siblings.order_by(DocumentSection.position.desc(), DocumentSection.id.desc()).first()
    section = DocumentSection(document_id=document.id, parent_id=parent.id if parent else None,
                              title=title, position=(last_sibling.position + 1 if last_sibling else 0))
    db.session.add(section)
    db.session.commit()
    flash("Sezione aggiunta.", "success")
    return redirect(url_for("documentation.index"))


@bp.post("/sections/<int:section_id>/edit")
def section_edit(section_id):
    section = _section_or_404(section_id)
    title = request.form.get("title", "").strip()
    if not title:
        flash("Il titolo della sezione è obbligatorio.", "danger")
    else:
        section.title = title
        db.session.commit()
        flash("Sezione rinominata.", "success")
    return redirect(url_for("documentation.index"))


@bp.post("/sections/<int:section_id>/move-up")
def section_move_up(section_id):
    section = _section_or_404(section_id)
    if _move(section, _ordered_siblings(section), -1):
        db.session.commit()
    return redirect(url_for("documentation.index"))


@bp.post("/sections/<int:section_id>/move-down")
def section_move_down(section_id):
    section = _section_or_404(section_id)
    if _move(section, _ordered_siblings(section), 1):
        db.session.commit()
    return redirect(url_for("documentation.index"))


@bp.post("/sections/<int:section_id>/delete")
def section_delete(section_id):
    section = _section_or_404(section_id)
    db.session.delete(section)
    db.session.commit()
    flash("Sezione eliminata.", "success")
    return redirect(url_for("documentation.index"))


def _apply_block_form(block, client):
    kind = request.form.get("kind")
    if kind == "markdown":
        block.kind = kind
        block.markdown = request.form.get("markdown", "")
        block.dataset_key = None
        block.site_id = None
        return None
    dataset_key = request.form.get("dataset_key")
    if kind != "dataset" or dataset_key not in DATASETS:
        return "Seleziona un tipo di blocco e un dataset validi."
    site_value = request.form.get("site_id", "").strip()
    try:
        site_id = int(site_value) if site_value else None
    except ValueError:
        return "La sede selezionata non è valida."
    if site_id and not Site.query.filter_by(id=site_id, client_id=client.id).first():
        return "La sede selezionata non appartiene al cliente corrente."
    block.kind = kind
    block.markdown = None
    block.dataset_key = dataset_key
    block.site_id = site_id
    return None


def _block_form_context(client, section, block=None):
    return {"client": client, "section": section, "block": block, "datasets": DATASETS,
            "sites": Site.query.filter_by(client_id=client.id).order_by(Site.name, Site.id).all()}


@bp.route("/sections/<int:section_id>/blocks/new", methods=["GET", "POST"])
def block_create(section_id):
    client = current_client_or_404()
    section = _section_or_404(section_id)
    last_block = (DocumentBlock.query.filter_by(section_id=section.id)
                  .order_by(DocumentBlock.position.desc(), DocumentBlock.id.desc()).first())
    block = DocumentBlock(section_id=section.id, position=(last_block.position + 1 if last_block else 0))
    if request.method == "POST":
        error = _apply_block_form(block, client)
        if error:
            flash(error, "danger")
        else:
            db.session.add(block)
            db.session.commit()
            flash("Blocco aggiunto.", "success")
            return redirect(url_for("documentation.index"))
    return render_template("documentation_block_form.html", **_block_form_context(client, section, block))


@bp.route("/blocks/<int:block_id>/edit", methods=["GET", "POST"])
def block_edit(block_id):
    client = current_client_or_404()
    block = _block_or_404(block_id)
    if request.method == "POST":
        error = _apply_block_form(block, client)
        if error:
            flash(error, "danger")
        else:
            db.session.commit()
            flash("Blocco aggiornato.", "success")
            return redirect(url_for("documentation.index"))
    return render_template("documentation_block_form.html",
                           **_block_form_context(client, block.section, block))


@bp.post("/blocks/<int:block_id>/move-up")
def block_move_up(block_id):
    block = _block_or_404(block_id)
    if _move(block, _ordered_blocks(block), -1):
        db.session.commit()
    return redirect(url_for("documentation.index"))


@bp.post("/blocks/<int:block_id>/move-down")
def block_move_down(block_id):
    block = _block_or_404(block_id)
    if _move(block, _ordered_blocks(block), 1):
        db.session.commit()
    return redirect(url_for("documentation.index"))


@bp.post("/blocks/<int:block_id>/delete")
def block_delete(block_id):
    block = _block_or_404(block_id)
    db.session.delete(block)
    db.session.commit()
    flash("Blocco eliminato.", "success")
    return redirect(url_for("documentation.index"))
