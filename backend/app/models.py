"""ORM models. Money is BIGINT paise; every time is timestamptz in UTC.

The import pipeline tables are described in docs/data-model.md.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# BIGINT ids on Postgres; SQLite only auto-increments INTEGER PRIMARY KEY.
BigId = BigInteger().with_variant(Integer, "sqlite")


class UtcDateTime(TypeDecorator):
    """timestamptz that accepts only aware datetimes and always returns UTC.

    SQLite has no time zone type, so values come back naive there; they were
    stored as UTC, so UTC is attached on the way out.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime: times must be timezone-aware")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _created() -> Mapped[datetime]:
    return mapped_column(UtcDateTime, server_default=func.now())


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


BATCH_STATUSES = ("running", "done", "failed")
SOURCES = ("sms_backup", "manual", "statement", "live_sms", "gmail")
PARSE_STATUSES = ("parsed", "unknown")
TXN_STATUSES = ("active", "superseded")
CANDIDATE_STATUSES = ("open", "confirmed", "dismissed")
# Owner data (Phase 3C). These repeat the engine's vocabulary on purpose: a migration fixes
# them in the database, so a change in app/engine/reconcile.py needs a migration too
# (tests/test_owner_load.py checks that they agree).
ACCOUNT_KINDS = ("bank_account", "credit_card", "wallet", "fd")
IDENTIFIER_KINDS = ("last4", "text")
PARTY_KINDS = ("person", "business", "unsure", "self", "investment")
# unsure: no role answer yet (D-096); self: "It's me" (D-117); investment: D-118
SUGGESTIONS = ("self", "investment")  # what To-do may ask about a party (D-117, D-118)
OWNER_SOURCES = ("file", "terminal", "app")  # who wrote an owner row
# Who gave a party its display name (D-116): an owner source, or the bank statement.
NAME_SOURCES = (*OWNER_SOURCES, "statement")
OWNER_LINK_KINDS = ("duplicate", "self_transfer", "card_bill", "refund", "fd")
VERDICTS = ("same", "different")
OWNER_ROLES = (
    "spend",
    "card_bill_counted",
    "refund",
    "payback",
    "income",
    "self_transfer",
    "card_bill_excluded",
    "fd_move",
    "investment",
    "ignored",
    "uncertain",
)  # every role except duplicate, which is decided as a link
# Derived data (Phase 3C)
RUN_STATUSES = ("running", "done", "failed")
# read: the first read after a deploy found rows made by other engine versions (D-102)
RUN_TRIGGERS = ("import", "reparse", "owner", "manual", "read")
MERCHANT_KINDS = ("business", "person", "unsure", "none")
ROLES = (*OWNER_ROLES, "duplicate")
DECIDERS = ("engine", "owner")
LINK_STATUSES = ("linked", "candidate")
LABEL_MAX = 30  # one limit for a label name: API, app and database (D-097)
DEVICE_NAME_MAX = 60  # a phone's name, "samsung SM-S918B" (D-122)


class Heartbeat(Base):
    """Single row (id=1) written by /health/db so Supabase sees regular activity.

    last_seen is set by the database clock (CURRENT_TIMESTAMP, i.e. now() on
    Postgres) in the upsert, never by the app.
    """

    __tablename__ = "heartbeat"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ImportBatch(Base):
    __tablename__ = "import_batches"
    __table_args__ = (CheckConstraint(_in("status", BATCH_STATUSES), name="ck_batch_status"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(UtcDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    status: Mapped[str] = mapped_column(String(10), index=True)
    input_fingerprint: Mapped[str] = mapped_column(String(64))  # sha256 of input bytes
    app_version: Mapped[str] = mapped_column(String(20))
    parser_versions: Mapped[dict] = mapped_column(JSON)
    counts: Mapped[dict] = mapped_column(JSON)


class RawMessage(Base):
    __tablename__ = "raw_messages"
    __table_args__ = (
        UniqueConstraint("owner_id", "content_hash", name="uq_raw_owner_hash"),
        CheckConstraint(_in("source", SOURCES), name="ck_raw_source"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source: Mapped[str] = mapped_column(String(20))
    sender_raw: Mapped[str] = mapped_column(String(64))
    sender_core: Mapped[str] = mapped_column(String(64), index=True)
    body: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(UtcDateTime)
    content_hash: Mapped[str] = mapped_column(String(64))
    first_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"))
    created_at: Mapped[datetime] = _created()


class ParseResult(Base):
    __tablename__ = "parse_results"
    __table_args__ = (
        UniqueConstraint("raw_message_id", "parser_version", name="uq_parse_raw_version"),
        CheckConstraint(_in("status", PARSE_STATUSES), name="ck_parse_status"),
        # Exactly one current result per raw message (the pipeline always sets one).
        Index(
            "uq_parse_current",
            "raw_message_id",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    raw_message_id: Mapped[int] = mapped_column(ForeignKey("raw_messages.id"))
    parser_version: Mapped[str] = mapped_column(String(20))  # "none": no parser for the bank
    status: Mapped[str] = mapped_column(String(10))
    unknown_reason: Mapped[str | None] = mapped_column(String(32), index=True)
    unknown_detail: Mapped[str | None] = mapped_column(Text)  # may hold values: never logged
    is_current: Mapped[bool] = mapped_column(Boolean, index=True)
    # ParsedMessage fields (null for unknown results)
    bank: Mapped[str | None] = mapped_column(String(20))
    template_id: Mapped[str | None] = mapped_column(String(20))
    type: Mapped[str | None] = mapped_column(String(20), index=True)
    direction: Mapped[str | None] = mapped_column(String(6))
    amount_paise: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3))
    account_last4: Mapped[str | None] = mapped_column(String(4))
    channel: Mapped[str | None] = mapped_column(String(20))
    counterparty_raw: Mapped[str | None] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(Text)
    balance_paise: Mapped[int | None] = mapped_column(BigInteger)
    txn_time_utc: Mapped[datetime | None] = mapped_column(UtcDateTime)
    time_inferred: Mapped[bool | None] = mapped_column(Boolean)
    hints: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = _created()


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("owner_id", "dedupe_key", name="uq_txn_owner_key"),
        CheckConstraint("amount_paise > 0", name="ck_txn_amount_positive"),
        CheckConstraint(_in("status", TXN_STATUSES), name="ck_txn_status"),
        CheckConstraint(_in("direction", ("debit", "credit")), name="ck_txn_direction"),
        # Fuzzy duplicate-candidate lookup
        Index("ix_txn_candidate", "owner_id", "bank", "direction", "amount_paise"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    dedupe_key: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(20))
    direction: Mapped[str] = mapped_column(String(6))
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    account_last4: Mapped[str | None] = mapped_column(String(4))
    channel: Mapped[str | None] = mapped_column(String(20))
    counterparty_raw: Mapped[str | None] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(Text)
    balance_paise: Mapped[int | None] = mapped_column(BigInteger)
    txn_time_utc: Mapped[datetime] = mapped_column(UtcDateTime, index=True)
    time_inferred: Mapped[bool] = mapped_column(Boolean)
    bank: Mapped[str] = mapped_column(String(20))
    hints: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(12), index=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, server_default=func.now(), onupdate=func.now()
    )


class TransactionSource(Base):
    """Which raw message (and which parse of it) a transaction came from."""

    __tablename__ = "transaction_sources"
    __table_args__ = (UniqueConstraint("raw_message_id", name="uq_source_raw"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), index=True)
    raw_message_id: Mapped[int] = mapped_column(ForeignKey("raw_messages.id"))
    parse_result_id: Mapped[int] = mapped_column(ForeignKey("parse_results.id"))


class DuplicateCandidate(Base):
    """Two transactions that may be one event. Recorded only; Reconcile decides."""

    __tablename__ = "duplicate_candidates"
    __table_args__ = (
        UniqueConstraint("txn_a", "txn_b", name="uq_candidate_pair"),
        CheckConstraint("txn_a < txn_b", name="ck_candidate_order"),
        CheckConstraint(_in("status", CANDIDATE_STATUSES), name="ck_candidate_status"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    txn_a: Mapped[int] = mapped_column(ForeignKey("transactions.id"))
    txn_b: Mapped[int] = mapped_column(ForeignKey("transactions.id"))
    rule: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(10), index=True)
    created_at: Mapped[datetime] = _created()


# --- Owner data ---------------------------------------------------------------
# Written only by owner commands (and later the app). Import, reparse and recompute
# read these tables and never write them. They hold the owner's own words and
# transaction ids, never merchant keys (D-065). Private: never printed or logged.


class OwnAccount(Base):
    """One of the owner's bank accounts, credit cards, wallets or FDs."""

    __tablename__ = "own_accounts"
    __table_args__ = (
        UniqueConstraint("owner_id", "label", name="uq_own_account_label"),
        CheckConstraint(_in("kind", ACCOUNT_KINDS), name="ck_own_account_kind"),
        CheckConstraint(_in("source", OWNER_SOURCES), name="ck_own_account_source"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    label: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(20))
    bank: Mapped[str | None] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = _created()


class OwnIdentifier(Base):
    """How an own account shows up: a last 4, or a counterparty text (name or UPI ID)."""

    __tablename__ = "own_identifiers"
    __table_args__ = (
        UniqueConstraint("owner_id", "kind", "value", "own_account_id", name="uq_own_identifier"),
        CheckConstraint(_in("kind", IDENTIFIER_KINDS), name="ck_own_identifier_kind"),
        CheckConstraint(_in("source", OWNER_SOURCES), name="ck_own_identifier_source"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    own_account_id: Mapped[int] = mapped_column(ForeignKey("own_accounts.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    value: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(10))


class Party(Base):
    """A person or business the owner named. income_label set: an income source.

    display_name: the name the owner gave in the app (D-096); shown over the label, which
    stays the entry's key (an owner-file party keeps its file label)."""

    __tablename__ = "parties"
    __table_args__ = (
        UniqueConstraint("owner_id", "label", name="uq_party_label"),
        CheckConstraint(_in("kind", PARTY_KINDS), name="ck_party_kind"),
        CheckConstraint(_in("source", OWNER_SOURCES), name="ck_party_source"),
        CheckConstraint(
            "name_source IS NULL OR " + _in("name_source", NAME_SOURCES),
            name="ck_party_name_source",
        ),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    label: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(10))
    income_label: Mapped[str | None] = mapped_column(String(80))
    # The owner's default category for every payment to this party (a slug; no CHECK,
    # so a new category needs no migration).
    category: Mapped[str | None] = mapped_column(String(40))
    display_name: Mapped[str | None] = mapped_column(String(LABEL_MAX))
    source: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = _created()
    # When the owner last answered Friend or Family for this party (4F-B); null: never, or
    # before 4F-B. payback-audit never calls an answered party silent.
    answered_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    # Who gave display_name (D-116): app, terminal, file or statement; null: no name, or a
    # name from before 4A. statement-names never overwrites a name the owner gave.
    name_source: Mapped[str | None] = mapped_column(String(10))
    # Suggestions the owner answered No to ("self", "investment"): never asked again (4Z).
    dismissed: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")


class OwnerName(Base):
    """ "Your name as banks show it" (D-117): one row per variant. Owner data; private."""

    __tablename__ = "owner_names"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_owner_name"),
        CheckConstraint(_in("source", OWNER_SOURCES), name="ck_owner_name_source"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    name: Mapped[str] = mapped_column(String(LABEL_MAX * 2))
    source: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = _created()


class PartyText(Base):
    """A counterparty text (name or UPI ID) that belongs to a party.

    A row is never deleted by the app: a join that ends gets `ended_at` (D-096). A text has
    at most one active row; recompute, the owner file and the export read active rows."""

    __tablename__ = "party_texts"
    __table_args__ = (
        Index(
            "uq_party_text_active",
            "owner_id",
            "text",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
            sqlite_where=text("ended_at IS NULL"),
        ),
        CheckConstraint(_in("source", OWNER_SOURCES), name="ck_party_text_source"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    party_id: Mapped[int] = mapped_column(ForeignKey("parties.id"), index=True)
    text: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = _created()
    ended_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


class OwnerLinkDecision(Base):
    """The owner says two transactions are, or are not, one event of this kind."""

    __tablename__ = "owner_link_decisions"
    __table_args__ = (
        UniqueConstraint("owner_id", "kind", "txn_a", "txn_b", name="uq_owner_link"),
        CheckConstraint("txn_a < txn_b", name="ck_owner_link_order"),
        CheckConstraint(_in("kind", OWNER_LINK_KINDS), name="ck_owner_link_kind"),
        CheckConstraint(_in("verdict", VERDICTS), name="ck_owner_link_verdict"),
        CheckConstraint(_in("source", OWNER_SOURCES), name="ck_owner_link_source"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(20))
    txn_a: Mapped[int] = mapped_column(ForeignKey("transactions.id"))
    txn_b: Mapped[int] = mapped_column(ForeignKey("transactions.id"))
    verdict: Mapped[str] = mapped_column(String(10))
    decided_at: Mapped[datetime] = mapped_column(UtcDateTime)
    source: Mapped[str] = mapped_column(String(10))


class OwnerRole(Base):
    """The owner fixes one transaction's role."""

    __tablename__ = "owner_roles"
    __table_args__ = (
        CheckConstraint(_in("role", OWNER_ROLES), name="ck_owner_role_role"),
        CheckConstraint(_in("source", OWNER_SOURCES), name="ck_owner_role_source"),
    )

    transaction_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("transactions.id"), primary_key=True, autoincrement=False
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    role: Mapped[str] = mapped_column(String(20))
    decided_at: Mapped[datetime] = mapped_column(UtcDateTime)
    source: Mapped[str] = mapped_column(String(10))


class OwnerCategory(Base):
    """The owner fixes one transaction's category. It beats the party default."""

    __tablename__ = "owner_categories"
    __table_args__ = (
        CheckConstraint(_in("source", OWNER_SOURCES), name="ck_owner_category_source"),
    )

    transaction_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("transactions.id"), primary_key=True, autoincrement=False
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    category: Mapped[str] = mapped_column(String(40))
    decided_at: Mapped[datetime] = mapped_column(UtcDateTime)
    source: Mapped[str] = mapped_column(String(10))


class TxnCheck(Base):
    """The owner said "Looks right" about a transaction the generic parser read (D-101).

    One row per transaction; it only clears the "check" flag and changes no total."""

    __tablename__ = "txn_checks"
    __table_args__ = (CheckConstraint(_in("source", OWNER_SOURCES), name="ck_txn_check_source"),)

    transaction_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("transactions.id"), primary_key=True, autoincrement=False
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    checked_at: Mapped[datetime] = mapped_column(UtcDateTime)
    source: Mapped[str] = mapped_column(String(10))


class Label(Base):
    """A label the owner made, for example a trip (D-056). It never replaces a category."""

    __tablename__ = "labels"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_label_name"),
        CheckConstraint(_in("source", OWNER_SOURCES), name="ck_label_source"),
        CheckConstraint(f"length(name) <= {LABEL_MAX}", name="ck_label_name_length"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(LABEL_MAX))
    source: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = _created()


class TxnLabel(Base):
    """The one label of a transaction: the primary key allows one row per transaction."""

    __tablename__ = "txn_labels"
    __table_args__ = (CheckConstraint(_in("source", OWNER_SOURCES), name="ck_txn_label_source"),)

    transaction_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("transactions.id"), primary_key=True, autoincrement=False
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    label_id: Mapped[int] = mapped_column(ForeignKey("labels.id"), index=True)
    source: Mapped[str] = mapped_column(String(10))


class ClientOp(Base):
    """One owner action sent with an Idempotency-Key (D-091, D-092): its final answer, so a
    repeat of the same key gets the same answer and writes nothing. Never deleted."""

    __tablename__ = "client_ops"

    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    op_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    received_at: Mapped[datetime] = mapped_column(UtcDateTime)
    method: Mapped[str] = mapped_column(String(6))
    path: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))  # method, path and body
    status_code: Mapped[int | None] = mapped_column(SmallInteger)
    response_body: Mapped[dict | None] = mapped_column(JSON)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    # The write skipped its recompute (X-Defer-Recompute, D-094); the next read runs it.
    recompute_pending: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )


class RecomputeMark(Base):
    """The owner data changed since the last recompute (D-106): every owner write sets it in
    its own transaction; the next read recomputes and deletes it. A failed recompute keeps
    it with `failed_at` and the error type, and is tried again after 5 minutes."""

    __tablename__ = "recompute_marks"

    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    marked_at: Mapped[datetime] = mapped_column(UtcDateTime)
    failed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    failure: Mapped[str | None] = mapped_column(String(40))


class Device(Base):
    """A phone that uploads bank SMS (D-122). Its token is shown once and stored only as a
    SHA-256; the token can call the SMS ingest route and nothing else. Revoked, never deleted."""

    __tablename__ = "devices"
    __table_args__ = (
        UniqueConstraint("owner_id", "device_id", name="uq_device_owner_device"),
        UniqueConstraint("token_hash", name="uq_device_token_hash"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(Uuid)  # chosen by the phone, once per install
    name: Mapped[str] = mapped_column(String(DEVICE_NAME_MAX))
    token_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created()
    last_seen_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


# --- Derived data -------------------------------------------------------------
# Written only by recompute (app/pipeline/recompute.py): one pure function of the
# active transactions, the owner tables and the engine versions. Deleting every row
# and running recompute gives the same rows back.


class DeriveRun(Base):
    """One recompute that wrote something. The derived tables match the last done run."""

    __tablename__ = "derive_runs"
    __table_args__ = (
        CheckConstraint(_in("status", RUN_STATUSES), name="ck_run_status"),
        CheckConstraint(_in("trigger", RUN_TRIGGERS), name="ck_run_trigger"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    status: Mapped[str] = mapped_column(String(10))
    trigger: Mapped[str] = mapped_column(String(10))
    versions: Mapped[dict] = mapped_column(JSON)  # {"merchant": ..., "reconcile": ...}
    counts: Mapped[dict] = mapped_column(JSON)  # counts only


class TxnDerived(Base):
    """Merchant and role of one active transaction."""

    __tablename__ = "txn_derived"
    __table_args__ = (
        CheckConstraint(_in("merchant_kind", MERCHANT_KINDS), name="ck_derived_merchant_kind"),
        CheckConstraint(_in("role", ROLES), name="ck_derived_role"),
        CheckConstraint(_in("role_basis", DECIDERS), name="ck_derived_basis"),
        CheckConstraint(
            "(role = 'duplicate') = (duplicate_of IS NOT NULL)", name="ck_derived_duplicate"
        ),
    )

    transaction_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("transactions.id"), primary_key=True, autoincrement=False
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    # Merchant: the engine's result; an owner party wins for kind and display name.
    merchant_key: Mapped[str | None] = mapped_column(Text, index=True)
    merchant_kind: Mapped[str] = mapped_column(String(10))
    merchant_confidence: Mapped[str] = mapped_column(String(4))
    display_name: Mapped[str | None] = mapped_column(Text)
    brand_id: Mapped[str | None] = mapped_column(String(40))
    merchant_reasons: Mapped[list] = mapped_column(JSON)
    # The owner entry whose text the transaction matches (also the key-change check).
    party_id: Mapped[int | None] = mapped_column(ForeignKey("parties.id", ondelete="SET NULL"))
    own_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("own_accounts.id", ondelete="SET NULL")
    )
    role: Mapped[str] = mapped_column(String(20), index=True)
    role_rule: Mapped[str] = mapped_column(String(32))
    role_basis: Mapped[str] = mapped_column(String(6))
    role_reasons: Mapped[list] = mapped_column(JSON)
    duplicate_of: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))
    # Category (3D): a slug of the fixed list, never blank.
    category: Mapped[str] = mapped_column(String(40), server_default="uncategorised", index=True)
    category_rule: Mapped[str] = mapped_column(String(32), server_default="NONE")
    category_basis: Mapped[str] = mapped_column(String(6), server_default="engine")


class TxnLink(Base):
    """Two transactions that are (linked) or may be (candidate) one event."""

    __tablename__ = "txn_links"
    __table_args__ = (
        UniqueConstraint("kind", "txn_a", "txn_b", name="uq_link_pair"),
        CheckConstraint("txn_a < txn_b", name="ck_link_order"),
        CheckConstraint(_in("kind", OWNER_LINK_KINDS), name="ck_link_kind"),
        CheckConstraint(_in("status", LINK_STATUSES), name="ck_link_status"),
        CheckConstraint(_in("decided_by", DECIDERS), name="ck_link_decided_by"),
        Index("ix_link_status_kind", "status", "kind"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(20))
    txn_a: Mapped[int] = mapped_column(ForeignKey("transactions.id"))
    txn_b: Mapped[int] = mapped_column(ForeignKey("transactions.id"))
    status: Mapped[str] = mapped_column(String(10))
    rule: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(32))
    decided_by: Mapped[str] = mapped_column(String(6))
