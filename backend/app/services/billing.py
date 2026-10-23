"""Sandbox-only billing. Nothing in this module dispatches real workflows."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from sqlalchemy import BigInteger, DateTime, Integer, String, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker
from sqlalchemy.types import JSON
from standardwebhooks.webhooks import EmptyWebhookSecretError, Webhook, WebhookVerificationError

from app.api.runs import Base
from app.core.config import Settings


PACK_SIZE = 5
PACK_CENTS = 500
SIMULATION = {
    "simulated": True,
    "summary": "Simulated fix: reject an empty email before saving a user.",
    "patch": '+ if not email or "@" not in email:\n+     raise ValueError("Invalid email")',
    "checks": ["Analyze issue", "Prepare example patch", "Simulate test result"],
}


class BillingError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.status = code, status


class BillingAccount(Base):
    __tablename__ = "billing_accounts"
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)


class BillingCheckout(Base):
    __tablename__ = "billing_checkouts"
    __table_args__ = (UniqueConstraint("user_id", "request_key"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    order_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    product_id: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    url: Mapped[str | None] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BillingEntry(Base):
    __tablename__ = "billing_entries"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BillingEvent(Base):
    __tablename__ = "billing_events"
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SimulationRun(Base):
    __tablename__ = "simulation_runs"
    __table_args__ = (UniqueConstraint("user_id", "request_key"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


def billing_configured(config: Settings) -> bool:
    return bool(config.billing_enabled and config.database_url and config.public_base_url
                and config.polar_access_token and config.polar_webhook_secret
                and config.polar_product_id and config.polar_organization_id)


class SandboxBilling:
    def __init__(self, config: Settings):
        self.config = config
        self._sessions = None

    def _factory(self):
        self.require_enabled()
        if self._sessions is None:
            from sqlalchemy import create_engine
            engine = create_engine(self.config.database_url, pool_pre_ping=True, pool_recycle=300)
            if engine.dialect.name == "sqlite":
                Base.metadata.create_all(engine)
            self._sessions = sessionmaker(engine, expire_on_commit=False)
        return self._sessions

    def require_enabled(self):
        if not billing_configured(self.config):
            raise BillingError("billing_unavailable", "Sandbox billing is not configured yet.", 503)

    def _lock(self, session, user_id: int):
        # The account row serializes purchases, refunds and spending across API processes.
        if session.bind.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        session.execute(insert(BillingAccount).values(user_id=user_id).on_conflict_do_nothing())
        session.scalar(select(BillingAccount).where(BillingAccount.user_id == user_id).with_for_update())

    @staticmethod
    def _balance(session, user_id):
        return session.scalar(select(func.coalesce(func.sum(BillingEntry.delta), 0))
                              .where(BillingEntry.user_id == user_id))

    def status(self, user_id: int):
        if not billing_configured(self.config):
            return {"enabled": False, "environment": "sandbox", "demo_balance": 0,
                    "pack_attempts": PACK_SIZE, "test_price_cents": PACK_CENTS,
                    "currency": "usd", "purchases": [], "activity": []}
        with self._factory()() as session:
            purchases = session.scalars(select(BillingCheckout).where(BillingCheckout.user_id == user_id)
                                        .order_by(BillingCheckout.created_at.desc()).limit(20)).all()
            activity = session.scalars(select(BillingEntry).where(BillingEntry.user_id == user_id)
                                       .order_by(BillingEntry.created_at.desc()).limit(20)).all()
            return {"enabled": True, "environment": "sandbox", "demo_balance": self._balance(session, user_id),
                    "pack_attempts": PACK_SIZE, "test_price_cents": PACK_CENTS, "currency": "usd",
                    "purchases": [{"id": row.id, "state": row.state, "created_at": _iso_time(row.created_at)}
                                  for row in purchases],
                    "activity": [{"id": row.id, "kind": row.kind, "delta": row.delta,
                                  "created_at": _iso_time(row.created_at)} for row in activity]}

    def balance(self, user_id: int) -> int:
        if not billing_configured(self.config):
            return 0
        with self._factory()() as session:
            return self._balance(session, user_id)

    def checkout(self, user_id: int, request_key: str):
        factory = self._factory()
        with factory.begin() as session:
            self._lock(session, user_id)
            existing = session.scalar(select(BillingCheckout).where(
                BillingCheckout.user_id == user_id, BillingCheckout.request_key == request_key))
            if existing:
                if existing.url and existing.state == "pending":
                    return {"id": existing.id, "url": existing.url}
                raise BillingError("checkout_already_requested", "Refresh billing before starting a new checkout.", 409)
            pending = session.scalar(select(func.count()).select_from(BillingCheckout).where(
                BillingCheckout.user_id == user_id, BillingCheckout.state == "pending",
                BillingCheckout.created_at > datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)))
            if pending >= 5:
                raise BillingError("checkout_limit", "Too many pending test checkouts. Try again tomorrow.", 429)
            intent_id = uuid4().hex
            session.add(BillingCheckout(id=intent_id, user_id=user_id, request_key=request_key,
                        product_id=self.config.polar_product_id, state="pending", created_at=_now()))
        base = self.config.public_base_url.rstrip("/")
        try:
            with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
                response = client.post("https://sandbox-api.polar.sh/v1/checkouts/", headers={
                    "Authorization": f"Bearer {self.config.polar_access_token}",
                    "Polar-Version": "2026-04",
                }, json={
                    "products": [self.config.polar_product_id],
                    "external_customer_id": f"github:{user_id}",
                    "metadata": {"repopilot_intent": intent_id},
                    "allow_discount_codes": False,
                    "success_url": base + "/billing?checkout=returned",
                    "return_url": base + "/billing?checkout=cancelled",
                })
                response.raise_for_status()
                payload = response.json()
            if (not isinstance(payload, dict) or not isinstance(payload.get("url"), str)
                    or len(payload["url"]) > 2048 or not isinstance(payload.get("id"), str)
                    or not 1 <= len(payload["id"]) <= 128):
                raise ValueError("Invalid checkout response")
            url = payload["url"]
            parsed = urlsplit(url)
            if (parsed.scheme != "https" or parsed.hostname != "sandbox.polar.sh" or parsed.port
                    or parsed.username or parsed.password):
                raise ValueError("Unexpected checkout URL")
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            with factory.begin() as session:
                self._lock(session, user_id)
                row = session.get(BillingCheckout, intent_id)
                if row.state == "pending":
                    row.state = "failed"
            raise BillingError("checkout_failed", "Could not open Polar sandbox checkout. Please retry.", 502) from None
        with factory.begin() as session:
            self._lock(session, user_id)
            row = session.get(BillingCheckout, intent_id)
            if row.provider_id is not None and row.provider_id != payload["id"]:
                raise BillingError("checkout_mismatch", "Checkout confirmation did not match.", 502)
            row.provider_id, row.url = payload["id"], url
        return {"id": intent_id, "url": url}

    def webhook(self, body: bytes, headers: dict[str, str]):
        self.require_enabled()
        event = _verify_event(self.config.polar_webhook_secret, body, headers)
        if not isinstance(event, dict):
            raise BillingError("invalid_webhook", "Invalid webhook payload.")
        event_type = event.get("type")
        if event_type not in {"order.paid", "order.refunded"}:
            return {"received": True}
        data = event.get("data")
        if not isinstance(data, dict):
            raise BillingError("invalid_order", "Invalid order payload.")
        customer, metadata = data.get("customer"), data.get("metadata")
        if not isinstance(customer, dict) or not isinstance(metadata, dict):
            raise BillingError("invalid_order", "Invalid order ownership.")
        intent_id = metadata.get("repopilot_intent")
        if not isinstance(intent_id, str):
            return {"received": True}
        with self._factory().begin() as session:
            row = session.get(BillingCheckout, intent_id)
            if row is None:
                return {"received": True}
            self._lock(session, row.user_id)
            session.refresh(row)
            if (data.get("product_id") != row.product_id
                    or customer.get("organization_id") != self.config.polar_organization_id
                    or customer.get("external_id") != f"github:{row.user_id}"
                    or not isinstance(data.get("id"), str) or not data["id"]
                    or not isinstance(data.get("checkout_id"), str) or not data["checkout_id"]
                    or (row.provider_id is not None and row.provider_id != data["checkout_id"])
                    or (row.order_id is not None and row.order_id != data["id"])):
                raise BillingError("order_mismatch", "Order did not match the checkout.")
            event_id = headers["webhook-id"]
            if len(event_id) > 255:
                raise BillingError("invalid_webhook", "Invalid event identifier.")
            if session.get(BillingEvent, event_id):
                return {"received": True}
            session.add(BillingEvent(id=event_id, created_at=_now()))
            row.provider_id, row.order_id = data["checkout_id"], data["id"]
            if event_type == "order.paid":
                if (data.get("paid") is not True or data.get("status") != "paid"
                        or data.get("currency") != "usd" or data.get("net_amount") != PACK_CENTS
                        or data.get("subscription_id") is not None):
                    raise BillingError("invalid_payment", "Expected a paid one-time test pack.")
                if row.state not in {"paid", "refunded"}:
                    self._entry(session, row.user_id, "purchase:" + data["id"], "purchase", PACK_SIZE)
                    row.state = "paid"
            else:
                if not isinstance(data.get("refunded_amount"), int) or data["refunded_amount"] <= 0:
                    raise BillingError("invalid_refund", "Expected a refunded order.")
                if row.state == "paid":
                    self._entry(session, row.user_id, "refund:" + data["id"], "refund", -PACK_SIZE)
                row.state = "refunded"
        return {"received": True}

    @staticmethod
    def _entry(session, user_id, source, kind, delta):
        session.add(BillingEntry(id=uuid4().hex, user_id=user_id, source=source, kind=kind,
                                delta=delta, created_at=_now()))

    def simulate(self, user_id: int, request_key: str):
        with self._factory().begin() as session:
            self._lock(session, user_id)
            run = session.scalar(select(SimulationRun).where(
                SimulationRun.user_id == user_id, SimulationRun.request_key == request_key))
            if run is not None:
                return self._simulation_response(run, self._balance(session, user_id))
            source = f"demo:{user_id}:{request_key}"
            existing = session.scalar(select(BillingEntry).where(BillingEntry.source == source))
            if not existing:
                if self._balance(session, user_id) < 1:
                    raise BillingError("demo_balance_empty", "No simulation credits remaining.", 409)
                self._entry(session, user_id, source, "simulation", -1)
            run = SimulationRun(id=uuid4().hex, user_id=user_id, request_key=request_key,
                                created_at=_now(), result=dict(SIMULATION))
            session.add(run)
            session.flush()
            return self._simulation_response(run, self._balance(session, user_id))

    @staticmethod
    def _simulation_response(run: SimulationRun, balance: int):
        return {**run.result, "simulation_id": run.id, "created_at": _iso_time(run.created_at),
                "demo_balance": balance}

    def simulations(self, user_id: int):
        if not billing_configured(self.config):
            return []
        with self._factory()() as session:
            rows = session.scalars(select(SimulationRun).where(SimulationRun.user_id == user_id)
                                   .order_by(SimulationRun.created_at.desc()).limit(20)).all()
            balance = self._balance(session, user_id)
            return [self._simulation_response(row, balance) for row in rows]


def _now():
    return datetime.now(timezone.utc)


def _iso_time(value: datetime) -> str:
    return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat()


def _verify_event(secret: str, body: bytes, headers: dict[str, str]):
    # Current secrets use Standard Webhooks; older Polar endpoints sign with the
    # full secret's UTF-8 bytes. Match Polar's SDK by checking both keys.
    for key in (secret, base64.b64encode(secret.encode()).decode()):
        try:
            return Webhook(key).verify(body, headers)
        except (WebhookVerificationError, EmptyWebhookSecretError, ValueError, TypeError, UnicodeError):
            continue
    raise BillingError("invalid_webhook", "Webhook verification failed.", 400) from None
