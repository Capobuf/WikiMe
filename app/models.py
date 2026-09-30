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
    devices = db.relationship("Device", backref="client", cascade="all, delete-orphan", lazy=True)

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
    documentation_overrides = db.Column(db.JSON, nullable=False, default=dict)
    sources = db.relationship("Source", backref="site", lazy=True)
    devices = db.relationship("Device", backref="site", lazy=True)


class Source(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False, index=True)
    site_id = db.Column(db.Integer, db.ForeignKey("site.id"), nullable=True)
    integration_type = db.Column(db.String(30), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    configuration = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    devices = db.relationship("Device", backref="source", lazy=True)

    @property
    def uses_global_settings(self):
        return self.configuration.get("mode", "global") == "global"


class IntegrationSetting(db.Model):
    integration_type = db.Column(db.String(30), primary_key=True)
    configuration = db.Column(db.JSON, nullable=False, default=dict)


class DocumentationSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    configuration = db.Column(db.JSON, nullable=False, default=dict)


class Device(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False, index=True)
    site_id = db.Column(db.Integer, db.ForeignKey("site.id"), nullable=True, index=True)
    source_id = db.Column(db.Integer, db.ForeignKey("source.id"), nullable=True, index=True)
    name = db.Column(db.String(200), nullable=False)
    vendor = db.Column(db.String(120))
    platform = db.Column(db.String(120))
    role = db.Column(db.String(80))
    model = db.Column(db.String(200))
    serial_number = db.Column(db.String(200), index=True)
    os_version = db.Column(db.String(120))
    management_ip = db.Column(db.String(80))
    notes = db.Column(db.Text)
    fingerprint = db.Column(db.String(64), nullable=False, index=True)
    data = db.Column(db.JSON, nullable=False, default=dict)
    imported_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    @property
    def sections(self):
        return self.data.get("sections", {})
