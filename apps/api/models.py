from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


class Sport(str, Enum):
    NBA = "NBA"
    SOCCER = "SOCCER"


class Competition(str, Enum):
    NBA = "NBA"
    EPL = "EPL"
    UCL = "UCL"
    UEL = "UEL"
    LALIGA = "LALIGA"


class Venue(str, Enum):
    POLY = "POLY"
    KALSHI = "KALSHI"


class MarketType(str, Enum):
    WINNER_BINARY = "WINNER_BINARY"
    WINNER_3WAY = "WINNER_3WAY"
    OTHER = "OTHER"


class BindingStatus(str, Enum):
    AUTO = "AUTO"
    REVIEW = "REVIEW"
    OVERRIDE = "OVERRIDE"
    REJECTED = "REJECTED"


class CanonicalEvent(SQLModel, table=True):
    __tablename__ = "canonical_events"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    sport: Sport = Field(sa_column=Column(String, nullable=False, index=True))
    competition: Optional[str] = Field(default=None, sa_column=Column(String, index=True))
    start_time_utc: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False, index=True))
    home_team: str = Field(sa_column=Column(String, nullable=False, index=True))
    away_team: str = Field(sa_column=Column(String, nullable=False, index=True))
    title_canonical: str = Field(sa_column=Column(String, nullable=False))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class MarketBinding(SQLModel, table=True):
    __tablename__ = "market_bindings"
    __table_args__ = (
        UniqueConstraint("venue", "venue_market_id", name="uq_binding_venue_market"),
        UniqueConstraint("canonical_event_id", "venue", name="uq_binding_event_venue"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    canonical_event_id: str = Field(foreign_key="canonical_events.id", index=True)
    venue: Venue = Field(sa_column=Column(String, nullable=False, index=True))
    venue_market_id: str = Field(sa_column=Column(String, nullable=False, index=True))
    outcome_schema: str = Field(default="YES_NO", sa_column=Column(String, nullable=False))
    market_type: MarketType = Field(default=MarketType.OTHER, sa_column=Column(String, nullable=False, index=True))
    status: BindingStatus = Field(default=BindingStatus.REVIEW, sa_column=Column(String, nullable=False, index=True))
    confidence: float = Field(default=0.0, sa_column=Column(Float, nullable=False))
    evidence_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )


class OrderBookTop(SQLModel, table=True):
    __tablename__ = "orderbook_tops"
    __table_args__ = (UniqueConstraint("venue", "venue_market_id", "outcome", name="uq_orderbook_side"),)

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    venue: Venue = Field(sa_column=Column(String, nullable=False, index=True))
    venue_market_id: str = Field(sa_column=Column(String, nullable=False, index=True))
    outcome: str = Field(sa_column=Column(String, nullable=False, index=True))
    best_bid: float = Field(sa_column=Column(Float, nullable=False))
    best_ask: float = Field(sa_column=Column(Float, nullable=False))
    bid_size: float = Field(sa_column=Column(Float, nullable=False, default=0.0))
    ask_size: float = Field(sa_column=Column(Float, nullable=False, default=0.0))
    ts: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )


class MispricingSignal(SQLModel, table=True):
    __tablename__ = "mispricing_signals"
    __table_args__ = (
        UniqueConstraint(
            "canonical_event_id",
            "outcome",
            "buy_venue",
            "sell_venue",
            name="uq_signal_event_outcome_direction",
        ),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    canonical_event_id: str = Field(foreign_key="canonical_events.id", index=True)
    outcome: str = Field(sa_column=Column(String, nullable=False, index=True))
    buy_venue: Venue = Field(sa_column=Column(String, nullable=False, index=True))
    sell_venue: Venue = Field(sa_column=Column(String, nullable=False, index=True))
    buy_market_id: str = Field(sa_column=Column(String, nullable=False))
    sell_market_id: str = Field(sa_column=Column(String, nullable=False))
    buy_price: float = Field(sa_column=Column(Float, nullable=False))
    sell_price: float = Field(sa_column=Column(Float, nullable=False))
    size_suggested: float = Field(sa_column=Column(Float, nullable=False))
    edge_raw: float = Field(sa_column=Column(Float, nullable=False))
    edge_after_costs: float = Field(sa_column=Column(Float, nullable=False, index=True))
    confidence: float = Field(sa_column=Column(Float, nullable=False))
    status: str = Field(default="OPEN", sa_column=Column(String, nullable=False, index=True))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )


class PaperPositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class PaperPosition(SQLModel, table=True):
    __tablename__ = "paper_positions"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    canonical_event_id: str = Field(foreign_key="canonical_events.id", index=True)
    signal_id: str = Field(foreign_key="mispricing_signals.id", index=True)
    outcome: str = Field(sa_column=Column(String, nullable=False, index=True))
    buy_venue: Venue = Field(sa_column=Column(String, nullable=False))
    sell_venue: Venue = Field(sa_column=Column(String, nullable=False))
    buy_market_id: str = Field(sa_column=Column(String, nullable=False))
    sell_market_id: str = Field(sa_column=Column(String, nullable=False))
    size: float = Field(sa_column=Column(Float, nullable=False))
    entry_buy_price: float = Field(sa_column=Column(Float, nullable=False))
    entry_sell_price: float = Field(sa_column=Column(Float, nullable=False))
    fill_ratio: float = Field(default=1.0, sa_column=Column(Float, nullable=False))
    status: PaperPositionStatus = Field(default=PaperPositionStatus.OPEN, sa_column=Column(String, nullable=False, index=True))
    opened_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    closed_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    realized_pnl: float = Field(default=0.0, sa_column=Column(Float, nullable=False))
    unrealized_pnl: float = Field(default=0.0, sa_column=Column(Float, nullable=False))


class PaperFill(SQLModel, table=True):
    __tablename__ = "paper_fills"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    position_id: str = Field(foreign_key="paper_positions.id", index=True)
    leg: str = Field(sa_column=Column(String, nullable=False))
    side: str = Field(sa_column=Column(String, nullable=False))
    limit_price: float = Field(sa_column=Column(Float, nullable=False))
    fill_price: float = Field(sa_column=Column(Float, nullable=False))
    size: float = Field(sa_column=Column(Float, nullable=False))
    filled_size: float = Field(sa_column=Column(Float, nullable=False))
    probability: float = Field(sa_column=Column(Float, nullable=False))
    ts: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class PortfolioSnapshot(SQLModel, table=True):
    __tablename__ = "portfolio_snapshots"

    id: int | None = Field(default=None, sa_column=Column(Integer, primary_key=True, autoincrement=True))
    ts: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
    equity: float = Field(default=0.0, sa_column=Column(Float, nullable=False))
    realized_pnl: float = Field(default=0.0, sa_column=Column(Float, nullable=False))
    unrealized_pnl: float = Field(default=0.0, sa_column=Column(Float, nullable=False))
