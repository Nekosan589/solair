from typing import Optional

from sqlmodel import Field, SQLModel
from datetime import datetime, timezone

class LatestReading(SQLModel, table=True):
    """One row per topic, always overwritten with the most recent value.

    Useful for fast "current state" lookups without scanning history.
    """

    topic: str = Field(primary_key=True)
    payload: str
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class SensorReading(SQLModel, table=True):
    """Append-only history: one row per MQTT message received."""

    id: Optional[int] = Field(default=None, primary_key=True)
    topic: str = Field(index=True)
    payload: str
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)