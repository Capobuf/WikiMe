from datetime import datetime, timezone

from .extensions import db


def utc_now():
    return datetime.now(timezone.utc)


class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(200), nullable=False)
    display_name = db.Column(db.String(200))
    address = db.Column(db.String(300))
    city = db.Column(db.String(120))
    email = db.Column(db.String(200))
    phone = db.Column(db.String(80))
    website = db.Column(db.String(300))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    sites = db.relationship("Site", backref="client", cascade="all, delete-orphan", lazy=True)
    sources = db.relationship("Source", backref="client", cascade="all, delete-orphan", lazy=True)

    @property
    def name(self):
        return self.display_name or self.company_name


class Site(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.String(300))
    description = db.Column(db.Text)
    notes = db.Column(db.Text)
    sources = db.relationship("Source", backref="site", lazy=True)


class Source(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False, index=True)
    site_id = db.Column(db.Integer, db.ForeignKey("site.id"), nullable=True)
    integration_type = db.Column(db.String(30), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    configuration = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    @property
    def uses_global_settings(self):
        return self.configuration.get("mode", "global") == "global"


class IntegrationSetting(db.Model):
    integration_type = db.Column(db.String(30), primary_key=True)
    configuration = db.Column(db.JSON, nullable=False, default=dict)

