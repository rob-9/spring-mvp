"""
Database models for spans and traces.

SQLAlchemy ORM models that map to PostgreSQL tables.
"""

from sqlalchemy import Column, String, DateTime, Float, Integer, Boolean, JSON, Index
from sqlalchemy.dialects.postgresql import ARRAY
from .database import Base
from datetime import datetime


class SpanModel(Base):
    """
    Database model for spans.

    Maps to 'spans' table in PostgreSQL.
    """
    __tablename__ = "spans"

    # primary identifiers
    span_id = Column(String, primary_key=True, index=True)
    trace_id = Column(String, index=True, nullable=False)
    parent_span_id = Column(String, index=True, nullable=True)

    # span metadata
    name = Column(String, nullable=False, index=True)
    start_time = Column(DateTime, nullable=False, index=True)
    end_time = Column(DateTime, nullable=True)
    duration_ms = Column(Float, nullable=True)

    # agent metadata
    agent_id = Column(String, nullable=True, index=True)
    agent_name = Column(String, nullable=True)
    decision_node = Column(Boolean, default=False)
    triggered_by = Column(String, nullable=True)

    # cost tracking
    cost_usd = Column(Float, nullable=True, index=True)
    tokens_input = Column(Integer, nullable=True)
    tokens_output = Column(Integer, nullable=True)
    tokens_total = Column(Integer, nullable=True)
    model = Column(String, nullable=True)

    # execution tracking
    status = Column(String, nullable=False, default="running", index=True)
    attempt_number = Column(Integer, default=1)
    decision_made = Column(String, nullable=True)

    # span links (stored as json array)
    links = Column(JSON, nullable=True)

    # additional context (flexible json field)
    span_metadata = Column(JSON, nullable=True)

    # timestamps for record keeping
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # indexes for common queries
    __table_args__ = (
        Index('idx_trace_start_time', 'trace_id', 'start_time'),
        Index('idx_parent_span', 'parent_span_id', 'span_id'),
        Index('idx_agent_status', 'agent_id', 'status'),
        Index('idx_cost_status', 'cost_usd', 'status'),
    )


class TraceModel(Base):
    """
    Database model for traces.

    Aggregated view of all spans in a trace.
    """
    __tablename__ = "traces"

    trace_id = Column(String, primary_key=True, index=True)
    start_time = Column(DateTime, nullable=False, index=True)
    end_time = Column(DateTime, nullable=True)
    duration_ms = Column(Float, nullable=True)

    # aggregated metrics
    total_cost_usd = Column(Float, default=0.0)
    total_tokens = Column(Integer, default=0)
    span_count = Column(Integer, default=0)

    # outcome tracking
    status = Column(String, nullable=False, default="running", index=True)
    outcome = Column(String, nullable=True)

    # metadata
    trace_metadata = Column(JSON, nullable=True)

    # timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
