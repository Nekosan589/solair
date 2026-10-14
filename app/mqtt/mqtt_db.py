"""
Wires MqttManager up to a SQLModel database so incoming MQTT messages are
persisted continuously instead of just kept in memory.

Stores:
  - every raw reading, as an append-only history table (SensorReading)
  - the latest value per topic, upserted in place (LatestReading)

DB writes use SQLModel's synchronous Session, run inside asyncio.to_thread()
so they don't block the event loop that's also running the MQTT listener.

Usage:
    from app.mqtt_manager import MqttManager
    from app.db import init_db
    from app.mqtt_db_listener import register_db_listener

    mqtt = MqttManager(host="localhost", port=1883)

    register_db_listener(mqtt, topic_pattern="sensors/#")

    # In FastAPI lifespan:
    init_db()
    async with mqtt.lifespan():
        yield
"""

import asyncio
import logging
from datetime import datetime, timezone

from sqlmodel import select

from app.models.mqtt_models import LatestReading, SensorReading
from app.mqtt.mqtt_manager import MqttManager
from app.database import get_session_enginge

logger = logging.getLogger("mqtt_db_listener")


def _persist_sync(topic: str, payload: str, keep_history: bool) -> None:
    """Blocking DB write — always call this via asyncio.to_thread()."""
    with get_session_enginge() as session:
        try:
            if keep_history:
                session.add(SensorReading(topic=topic, payload=payload))

            existing = session.exec(
                select(LatestReading).where(LatestReading.topic == topic)
            ).first()

            if existing:
                existing.payload = payload
                existing.updated_at = datetime.now(timezone.utc)
                session.add(existing)
            else:
                session.add(
                    LatestReading(
                        topic=topic,
                        payload=payload,
                        updated_at=datetime.now(timezone.utc),
                    )
                )

            session.commit()
            logger.debug("Persisted %s -> %s", topic, payload)

        except Exception:
            session.rollback()
            logger.exception("Failed to persist MQTT message for topic %r", topic)


def register_db_listener(
    mqtt: MqttManager,
    topic_pattern: str = "#",
    keep_history: bool = True,
) -> None:
    """
    Registers a handler on `mqtt` that continuously persists every message
    matching `topic_pattern` to the database.

    - `keep_history=True` also inserts a row into SensorReading for every
      message (a full time-series/audit trail). Set False if you only want
      the latest value per topic.

    Call this once, before mqtt.start() / mqtt.lifespan() runs, so the
    handler is registered before the listener subscribes to the broker.
    """

    @mqtt.on_topic(topic_pattern)
    async def _persist_to_db(topic: str, payload: str) -> None:
        # Offload the blocking SQLModel session work to a thread so the
        # MQTT event loop (and other handlers/dispatch) stays responsive.
        await asyncio.to_thread(_persist_sync, topic, payload, keep_history)
