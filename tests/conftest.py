import pytest

from app import create_app
from app.extensions import db


@pytest.fixture()
def app(tmp_path):
    database = tmp_path / "test.db"
    app = create_app({
        "TESTING": True,
        "DEBUG": False,
        "SECRET_KEY": "test-key",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database.as_posix()}",
    })
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def create_client(client, name="ACME"):
    return client.post("/clients/new", data={"company_name": name}, follow_redirects=True)

