from flask import abort, session

from ..extensions import db
from ..models import Client


def current_client_or_404():
    client = db.session.get(Client, session.get("current_client_id"))
    if client is None:
        abort(404)
    return client

