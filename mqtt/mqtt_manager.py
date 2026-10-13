"""
Reusable MQTT manager for FastAPI apps, built on aiomqtt (async-native).
 
Usage:
    from mqtt_manager import MqttManager
 
    mqtt = MqttManager(host="localhost", port=1883)
 
    @mqtt.on_topic("sensors/+/temperature")
    async def handle_temp(topic: str, payload: str):
        print(f"{topic} -> {payload}")
 
    # In FastAPI lifespan:
    async with mqtt.lifespan():
        yield
"""
 
import asyncio
import contextlib
import logging
from typing import Awaitable, Callable, Optional
 
import aiomqtt

from app.config import settings
 
logger = logging.getLogger("mqtt_manager")
 
Handler = Callable[[str, str], Awaitable[None]]
 
 
def _topic_matches(pattern: str, topic: str) -> bool:
    """Match MQTT wildcards (+ and #) against a concrete topic."""
    p_parts = pattern.split("/")
    t_parts = topic.split("/")
 
    for i, p in enumerate(p_parts):
        if p == "#":
            return True
        if i >= len(t_parts):
            return False
        if p == "+":
            continue
        if p != t_parts[i]:
            return False
    return len(p_parts) == len(t_parts)
 
 
class MqttManager:
    """
    Wraps an aiomqtt client with:
      - automatic reconnect
      - topic-pattern -> handler routing (supports + and # wildcards)
      - a persistent client for low-latency publishing
      - clean startup/shutdown via an async context manager (for FastAPI lifespan)
    """
 
    def __init__(
        self,
        host: str = 'localhost',
        port: int = 1883,
        username: Optional[str] = None,
        password: Optional[str] = None,
        client_id: Optional[str] = None,
        reconnect_interval: float = 5.0,
        tls_context=None,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.client_id = client_id
        self.reconnect_interval = reconnect_interval
        self.tls_context = tls_context
 
        self._handlers: dict[str, Handler] = {}
        self._listen_task: Optional[asyncio.Task] = None
        self._publish_client: Optional[aiomqtt.Client] = None
        self._stopping = False
 
    # ---------- Handler registration ----------
 
    def on_topic(self, pattern: str):
        """Decorator: register an async handler for a topic pattern (supports + and #)."""
 
        def decorator(func: Handler) -> Handler:
            self._handlers[pattern] = func
            return func
 
        return decorator
 
    def add_handler(self, pattern: str, handler: Handler) -> None:
        self._handlers[pattern] = handler
 
    def remove_handler(self, pattern: str) -> None:
        self._handlers.pop(pattern, None)
 
    # ---------- Internal connection helpers ----------
 
    def _make_client(self) -> aiomqtt.Client:
        return aiomqtt.Client(
            hostname=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            identifier=self.client_id,
            tls_context=self.tls_context,
        )
 
    async def _dispatch(self, topic: str, payload: str) -> None:
        for pattern, handler in self._handlers.items():
            if _topic_matches(pattern, topic):
                try:
                    await handler(topic, payload)
                except Exception:
                    logger.exception("Error in MQTT handler for pattern %r", pattern)
 
    async def _listen_loop(self) -> None:
        while not self._stopping:
            try:
                async with self._make_client() as client:
                    logger.info("Connected to MQTT broker %s:%s", self.host, self.port)
 
                    # Subscribe to every registered pattern
                    for pattern in self._handlers:
                        await client.subscribe(pattern)
 
                    async for message in client.messages:
                        payload = (
                            message.payload.decode()
                            if isinstance(message.payload, (bytes, bytearray))
                            else str(message.payload)
                        )
                        asyncio.create_task(self._dispatch(str(message.topic), payload))
 
            except aiomqtt.MqttError as e:
                if self._stopping:
                    break
                logger.warning(
                    "MQTT connection error (%s), retrying in %.1fs",
                    e,
                    self.reconnect_interval,
                )
                await asyncio.sleep(self.reconnect_interval)
 
    # ---------- Public lifecycle ----------
 
    async def start(self) -> None:
        """Start the background listener and a persistent publish client."""
        self._stopping = False
        self._publish_client = self._make_client()
        await self._publish_client.__aenter__()
        self._listen_task = asyncio.create_task(self._listen_loop())
 
    async def stop(self) -> None:
        """Cancel the listener and close the publish client cleanly."""
        self._stopping = True
 
        if self._listen_task:
            self._listen_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listen_task
            self._listen_task = None
 
        if self._publish_client:
            with contextlib.suppress(Exception):
                await self._publish_client.__aexit__(None, None, None)
            self._publish_client = None
 
    @contextlib.asynccontextmanager
    async def lifespan(self):
        """Convenience context manager for FastAPI's lifespan."""
        await self.start()
        try:
            yield self
        finally:
            await self.stop()
 
    # ---------- Publishing ----------
 
    async def publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False) -> None:
        if not self._publish_client:
            raise RuntimeError("MqttManager is not started — call start() or use lifespan()")
        await self._publish_client.publish(topic, payload=payload, qos=qos, retain=retain)

mqtt = MqttManager(host=settings.HOST, port=settings.PORT)