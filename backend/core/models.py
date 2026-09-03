"""SQLModel tables for PRIMA. Field names match docs/03 section 1.

No ORM relationship() graphs -- foreign keys only, so P2/P3 can import
these classes without pulling a mapped object graph.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import JSON, Column, DateTime, Index, event, inspect as sa_inspect
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class Account(SQLModel, table=True):
    __tablename__ = "accounts"
    __table_args__ = (
        Index("ix_accounts_handle", "handle", unique=True),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    handle: str = Field(nullable=False)
    display_name: str = Field(nullable=False)
    bank_code: str = Field(default="BANKA", nullable=False)
    device_id: str = Field(nullable=False)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    # Ledger balance. Available funds = balance_paise minus SUM of
    # active scoped_holds.held_paise -- computed later, not a column.
    balance_paise: int = Field(default=0, nullable=False)
    is_demo_guest: bool = Field(default=False, nullable=False)
    # SEEDED DATA ONLY. Scorers must never read this column.
    # Used later by /api/metrics/ps3. Do not expose from any endpoint.
    ground_truth_role: Optional[str] = Field(default=None)


class Transaction(SQLModel, table=True):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_tx_sender", "sender_id", "attempted_at"),
        Index("ix_tx_receiver", "receiver_id", "attempted_at"),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    sender_id: str = Field(foreign_key="accounts.id", nullable=False)
    receiver_id: str = Field(foreign_key="accounts.id", nullable=False)
    amount_paise: int = Field(nullable=False)
    # Allowed: 'upi' | 'imps' | 'neft' | 'card' (lowercase).
    channel: str = Field(nullable=False)
    note: Optional[str] = Field(default=None)
    # Allowed: 'quoted' | 'settled' | 'held' | 'cancelled' | 'challenged'.
    # Tier 3/4 commit -> held. Contact approved or cooling timeout -> settled.
    # Payer cancel -> cancelled. Contact extend keeps held.
    status: str = Field(nullable=False)
    attempted_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    settled_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    taint_ratio: float = Field(default=0.0, nullable=False)
    # SEEDED DATA ONLY. Scorers must never read this column.
    is_seeded_attack: bool = Field(default=False, nullable=False)


class Event(SQLModel, table=True):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_acct_ts", "account_id", "ts"),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    account_id: str = Field(foreign_key="accounts.id", nullable=False)
    # Allowed: login_new_device | credential_changed | payee_added |
    # limit_raised | screen_share_active | note_entered | call_context |
    # transfer_attempted.
    event_type: str = Field(nullable=False)
    payload: Optional[dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    ts: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    ingest_source: str = Field(default="manual", nullable=False)


class RiskDecision(SQLModel, table=True):
    """APPEND ONLY.

    The only columns that may be updated after insert are commit_at and
    lead_time_ms. A SQLAlchemy before_update listener enforces this.
    """

    __tablename__ = "risk_decisions"

    id: str = Field(default_factory=new_id, primary_key=True)
    transaction_id: Optional[str] = Field(
        default=None,
        foreign_key="transactions.id",
    )
    sender_id: str = Field(nullable=False)
    beneficiary_id: str = Field(nullable=False)
    amount_paise: int = Field(nullable=False)

    ringwatch_score: float = Field(nullable=False)
    trailscore_score: float = Field(nullable=False)
    contextflag_score: float = Field(nullable=False)
    cross_term_bonus: float = Field(default=0.0, nullable=False)
    fused_score: float = Field(nullable=False)
    tier: int = Field(nullable=False)
    verdict: str = Field(nullable=False)

    rules_fired: list[Any] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    user_reason: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    bank_reason: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    regulator_record: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    payload_sha256: str = Field(nullable=False)

    config_version: str = Field(nullable=False)
    quote_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    commit_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    lead_time_ms: Optional[int] = Field(default=None)


@event.listens_for(RiskDecision, "before_update")
def _risk_decision_append_only(mapper, connection, target) -> None:
    """Refuse updates except commit_at and/or lead_time_ms."""
    insp = sa_inspect(target)
    allowed = {"commit_at", "lead_time_ms"}
    dirty: set[str] = set()
    for attr in mapper.column_attrs:
        history = insp.get_history(attr.key, True)
        if history.has_changes():
            dirty.add(attr.key)
    extra = dirty - allowed
    if extra:
        raise RuntimeError(
            "risk_decisions is append-only; "
            f"only commit_at and lead_time_ms may change, not {sorted(extra)}"
        )


class ContextFlag(SQLModel, table=True):
    __tablename__ = "context_flags"

    id: str = Field(default_factory=new_id, primary_key=True)
    decision_id: Optional[str] = Field(
        default=None,
        foreign_key="risk_decisions.id",
    )
    event_id: Optional[str] = Field(
        default=None,
        foreign_key="events.id",
    )
    category: str = Field(nullable=False)
    weight: float = Field(nullable=False)
    matched_span: Optional[str] = Field(default=None)


class ScopedHold(SQLModel, table=True):
    """Amount-scoped hold on an outbound transfer.

    Inbound money is never held. Only outbound. There is no function that
    locks an entire account; do not add one. A hold reduces available
    funds for one amount, never the whole account.
    """

    __tablename__ = "scoped_holds"

    id: str = Field(default_factory=new_id, primary_key=True)
    transaction_id: str = Field(foreign_key="transactions.id", nullable=False)
    account_id: str = Field(foreign_key="accounts.id", nullable=False)
    held_paise: int = Field(nullable=False)
    reason_ref: str = Field(nullable=False)
    opened_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    releases_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    released_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    # released = remainder settled (approve or timeout).
    # cancelled_by_user = payer cancel, no remainder debit.
    # null while still held, including contact extend.
    # escalated = bank/ops only, not contact "hold it".
    outcome: Optional[str] = Field(default=None)


class TrustedContact(SQLModel, table=True):
    __tablename__ = "trusted_contacts"

    id: str = Field(default_factory=new_id, primary_key=True)
    account_id: str = Field(foreign_key="accounts.id", nullable=False)
    contact_name: str = Field(nullable=False)
    watch_token: str = Field(nullable=False, unique=True, index=True)
    nominated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class CircuitBreakerLog(SQLModel, table=True):
    __tablename__ = "circuit_breaker_log"

    id: str = Field(default_factory=new_id, primary_key=True)
    decision_id: str = Field(foreign_key="risk_decisions.id", nullable=False)
    contact_id: str = Field(foreign_key="trusted_contacts.id", nullable=False)
    fired_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    ack: bool = Field(default=False, nullable=False)
    ack_action: Optional[str] = Field(default=None)
    ack_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class ComprehensionProbe(SQLModel, table=True):
    __tablename__ = "comprehension_probes"

    id: str = Field(default_factory=new_id, primary_key=True)
    decision_id: str = Field(foreign_key="risk_decisions.id", nullable=False)
    question: str = Field(nullable=False)
    options: list[Any] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    correct_index: int = Field(nullable=False)
    chosen_index: Optional[int] = Field(default=None)
    shown_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    answered_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class PatternSignature(SQLModel, table=True):
    __tablename__ = "pattern_signatures"

    id: str = Field(default_factory=new_id, primary_key=True)
    label: Optional[str] = Field(default=None)
    signature: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class BankMeshSignal(SQLModel, table=True):
    __tablename__ = "bank_mesh_signals"

    id: str = Field(default_factory=new_id, primary_key=True)
    hashed_account_ref: str = Field(nullable=False)
    origin_bank: str = Field(nullable=False)
    risk_score: float = Field(nullable=False)
    reason_codes: list[Any] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    shared_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
