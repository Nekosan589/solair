"""Reusable MQTT manager with a synchronous core and an asyncio wrapper.

This module provides one class:

* :class:`MqttManager` -- a synchronous, thread-based MQTT manager built on
  ``paho-mqtt``. Use it in scripts, workers, or any non-async code.

Synchronous usage::
    from mqtt_manager import MqttManager

    mqtt = MqttManager(host="localhost", port=1883)

    @mqtt.on_topic("sensors/+/temperature")
    def handle_temp(topic: str, payload: str) -> None:
        print(f"{topic} -> {payload}")

    with mqtt.lifespan():
        mqtt.publish("sensors/1/temperature", "21.5")

.. note::
   Requires ``paho-mqtt >= 2.0`` (``pip install "paho-mqtt>=2.0"``).
"""

import contextlib
import logging
import ssl
import threading
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
    Tuple,
    Union,
)

import paho.mqtt.client as paho
from paho.mqtt.enums import CallbackAPIVersion
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode

logger: logging.Logger = logging.getLogger("mqtt_manager")

SyncHandler = Callable[[str, str], None]
"""A plain function ``handler(topic, payload) -> None``."""

AsyncHandler = Callable[[str, str], Awaitable[None]]
"""A coroutine function ``async handler(topic, payload) -> None``."""

Handler = Union[SyncHandler, AsyncHandler]
"""Any handler type. Async handlers are only supported by :class:`AsyncMqttManager`."""


def _topic_matches(pattern: str, topic: str) -> bool:
    """Check whether a concrete topic matches an MQTT subscription pattern.

    Supports the two MQTT wildcards:

    * ``+`` -- matches exactly one topic level.
    * ``#`` -- matches all remaining levels (must be the last level).

    :param pattern: Subscription pattern, e.g. ``"sensors/+/temperature"``.
    :type pattern: str
    :param topic: Concrete topic of a received message, e.g.
        ``"sensors/kitchen/temperature"``.
    :type topic: str
    :return: ``True`` if ``topic`` matches ``pattern``, otherwise ``False``.
    :rtype: bool
    """
    p_parts: List[str] = pattern.split("/")
    t_parts: List[str] = topic.split("/")

    for i, p in enumerate(p_parts):
        if p == "#":
            # Multi-level wildcard swallows everything that remains.
            return True
        if i >= len(t_parts):
            # Pattern is longer than the topic.
            return False
        if p == "+":
            # Single-level wildcard matches any one level.
            continue
        if p != t_parts[i]:
            return False
    # Without '#', both must have exactly the same number of levels.
    return len(p_parts) == len(t_parts)


class MqttManager:
    """Synchronous MQTT manager built on :mod:`paho.mqtt.client`.

    Features:

    * Automatic reconnection, handled by paho's background network thread.
    * Routing of incoming messages to handlers by topic pattern, with ``+``
      and ``#`` wildcard support.
    * Automatic re-subscription to every registered pattern on each
      (re)connect.
    * Clean startup/shutdown through :meth:`start`/:meth:`stop`, or the
      :meth:`lifespan` / ``with`` context managers.

    .. warning::
       Handlers run on paho's network thread. Keep them short, or hand heavy
       work off to another thread or queue, otherwise message processing
       (and keep-alive pings) will be delayed.

    :param host: Broker hostname or IP address.
    :type host: str
    :param port: Broker TCP port.
    :type port: int
    :param username: Optional broker username.
    :type username: Optional[str]
    :param password: Optional broker password.
    :type password: Optional[str]
    :param client_id: Optional MQTT client identifier. If ``None`` or empty,
        the broker assigns one.
    :type client_id: Optional[str]
    :param reconnect_interval: Maximum delay in seconds between reconnect
        attempts (paho backs off from 1 second up to this value).
    :type reconnect_interval: float
    :param tls_context: Optional pre-configured SSL context for TLS
        connections.
    :type tls_context: Optional[ssl.SSLContext]
    :param keepalive: Keep-alive interval in seconds sent to the broker.
    :type keepalive: int
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 1883,
        username: Optional[str] = None,
        password: Optional[str] = None,
        client_id: Optional[str] = None,
        reconnect_interval: float = 5.0,
        tls_context: Optional[ssl.SSLContext] = None,
        keepalive: int = 60,
    ) -> None:
        self.host: str = host
        self.port: int = port
        self.username: Optional[str] = username
        self.password: Optional[str] = password
        self.client_id: Optional[str] = client_id
        self.reconnect_interval: float = reconnect_interval
        self.tls_context: Optional[ssl.SSLContext] = tls_context
        self.keepalive: int = keepalive

        # Maps topic pattern -> handler function.
        self._handlers: Dict[str, Handler] = {}
        # Protects ``_handlers``, which is read from paho's thread and
        # modified from the caller's thread.
        self._lock: threading.RLock = threading.RLock()
        # The paho client; ``None`` while the manager is stopped.
        self._client: Optional[paho.Client] = None

    # ------------------------------------------------------------------
    # Handler registration
    # ------------------------------------------------------------------

    def on_topic(self, pattern: str) -> Callable[[Handler], Handler]:
        """Register a handler for a topic pattern, used as a decorator.

        Example::

            @mqtt.on_topic("sensors/+/temperature")
            def handle(topic: str, payload: str) -> None:
                ...

        :param pattern: Topic pattern to subscribe to (``+`` and ``#``
            wildcards are supported).
        :type pattern: str
        :return: A decorator that registers the function and returns it
            unchanged.
        :rtype: Callable[[Handler], Handler]
        """

        def decorator(func: Handler) -> Handler:
            self.add_handler(pattern, func)
            return func

        return decorator

    def add_handler(self, pattern: str, handler: Handler) -> None:
        """Register (or replace) the handler for a topic pattern.

        If the client is already connected and the pattern is new, the
        subscription is made immediately; otherwise it happens on connect.

        :param pattern: Topic pattern to subscribe to.
        :type pattern: str
        :param handler: Callable invoked as ``handler(topic, payload)``.
        :type handler: Handler
        :return: ``None``
        :rtype: None
        """
        with self._lock:
            is_new: bool = pattern not in self._handlers
            self._handlers[pattern] = handler
        client: Optional[paho.Client] = self._client
        if is_new and client is not None and client.is_connected():
            client.subscribe(pattern)

    def remove_handler(self, pattern: str) -> None:
        """Remove the handler for a pattern and unsubscribe from it.

        Does nothing if no handler is registered for ``pattern``.

        :param pattern: Topic pattern previously passed to
            :meth:`add_handler` or :meth:`on_topic`.
        :type pattern: str
        :return: ``None``
        :rtype: None
        """
        with self._lock:
            removed: Optional[Handler] = self._handlers.pop(pattern, None)
        client: Optional[paho.Client] = self._client
        if removed is not None and client is not None and client.is_connected():
            client.unsubscribe(pattern)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_client(self) -> paho.Client:
        """Create and configure a new paho client.

        Applies credentials, TLS, the reconnect back-off, and wires up the
        connection/message callbacks.

        :return: A configured, not-yet-connected paho client.
        :rtype: paho.Client
        """
        client: paho.Client = paho.Client(
            CallbackAPIVersion.VERSION2,
            client_id=self.client_id or "",
        )
        if self.username is not None:
            client.username_pw_set(self.username, self.password)
        if self.tls_context is not None:
            client.tls_set_context(self.tls_context)

        # Back off from 1s up to ``reconnect_interval`` between retries.
        client.reconnect_delay_set(
            min_delay=1, max_delay=max(1, int(self.reconnect_interval))
        )
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        return client

    def _on_connect(
        self,
        client: paho.Client,
        userdata: Any,
        flags: paho.ConnectFlags,
        reason_code: ReasonCode,
        properties: Optional[Properties] = None,
    ) -> None:
        """Handle a (re)connection to the broker (paho callback).

        Re-subscribes to every registered pattern, because subscriptions are
        not guaranteed to survive a reconnect.

        :param client: The paho client that connected.
        :type client: paho.Client
        :param userdata: User data set on the client (unused).
        :type userdata: Any
        :param flags: Connection flags returned by the broker.
        :type flags: paho.ConnectFlags
        :param reason_code: Result of the connection attempt.
        :type reason_code: ReasonCode
        :param properties: MQTT v5 properties (unused).
        :type properties: Optional[Properties]
        :return: ``None``
        :rtype: None
        """
        if reason_code.is_failure:
            logger.warning("MQTT connect refused: %s", reason_code)
            return
        logger.info("Connected to MQTT broker %s:%s", self.host, self.port)
        with self._lock:
            patterns: List[str] = list(self._handlers)
        for pattern in patterns:
            client.subscribe(pattern)

    def _on_disconnect(
        self,
        client: paho.Client,
        userdata: Any,
        flags: paho.DisconnectFlags,
        reason_code: ReasonCode,
        properties: Optional[Properties] = None,
    ) -> None:
        """Log a disconnection from the broker (paho callback).

        Reconnection itself is performed automatically by paho's network
        loop; this callback is for logging only.

        :param client: The paho client that disconnected.
        :type client: paho.Client
        :param userdata: User data set on the client (unused).
        :type userdata: Any
        :param flags: Disconnect flags.
        :type flags: paho.DisconnectFlags
        :param reason_code: Why the connection was closed.
        :type reason_code: ReasonCode
        :param properties: MQTT v5 properties (unused).
        :type properties: Optional[Properties]
        :return: ``None``
        :rtype: None
        """
        if reason_code.is_failure:
            logger.warning(
                "MQTT disconnected (%s), paho will retry automatically", reason_code
            )

    def _on_message(
        self,
        client: paho.Client,
        userdata: Any,
        msg: paho.MQTTMessage,
    ) -> None:
        """Decode an incoming message and dispatch it (paho callback).

        :param client: The paho client that received the message.
        :type client: paho.Client
        :param userdata: User data set on the client (unused).
        :type userdata: Any
        :param msg: The received message.
        :type msg: paho.MQTTMessage
        :return: ``None``
        :rtype: None
        """
        payload: str = (
            msg.payload.decode(errors="replace")
            if isinstance(msg.payload, (bytes, bytearray))
            else str(msg.payload)
        )
        self._dispatch(msg.topic, payload)

    def _dispatch(self, topic: str, payload: str) -> None:
        """Call every handler whose pattern matches ``topic``.

        Exceptions raised by a handler are logged and swallowed so that one
        faulty handler cannot break the others or kill the network thread.

        :param topic: Concrete topic of the received message.
        :type topic: str
        :param payload: Decoded message payload.
        :type payload: str
        :return: ``None``
        :rtype: None
        """
        with self._lock:
            # Snapshot under the lock so handlers can be added/removed while
            # we iterate and call them outside the lock.
            matches: List[Tuple[str, Handler]] = [
                (p, h) for p, h in self._handlers.items() if _topic_matches(p, topic)
            ]
        for pattern, handler in matches:
            try:
                self._invoke(handler, topic, payload)
            except Exception:
                logger.exception("Error in MQTT handler for pattern %r", pattern)

    def _invoke(self, handler: Handler, topic: str, payload: str) -> None:
        """Run a single handler.

        This is the extension point that :class:`AsyncMqttManager` overrides
        to run handlers on the asyncio event loop. Here the handler is called
        directly on paho's thread.

        :param handler: The handler to execute.
        :type handler: Handler
        :param topic: Topic of the received message.
        :type topic: str
        :param payload: Decoded message payload.
        :type payload: str
        :return: ``None``
        :rtype: None
        """
        handler(topic, payload)

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Connect to the broker and start the background network thread.

        The connection is made without blocking (``connect_async``); if the
        broker is unreachable, paho keeps retrying in the background.
        Calling this on an already-started manager does nothing.

        :return: ``None``
        :rtype: None
        """
        if self._client is not None:
            return
        self._client = self._make_client()
        self._client.connect_async(self.host, self.port, keepalive=self.keepalive)
        self._client.loop_start()

    def stop(self) -> None:
        """Disconnect from the broker and stop the network thread.

        Safe to call when the manager is not started.

        :return: ``None``
        :rtype: None
        """
        client: Optional[paho.Client] = self._client
        self._client = None
        if client is None:
            return
        with contextlib.suppress(Exception):
            client.disconnect()
        client.loop_stop()

    @contextlib.contextmanager
    def lifespan(self) -> Iterator["MqttManager"]:
        """Context manager that starts the manager and stops it on exit.

        Example::

            with mqtt.lifespan():
                mqtt.publish("a/b", "hello")

        :return: An iterator yielding this manager (for ``with ... as m``).
        :rtype: Iterator[MqttManager]
        """
        self.start()
        try:
            yield self
        finally:
            self.stop()

    def __enter__(self) -> "MqttManager":
        """Start the manager when entering a ``with`` block.

        :return: This manager.
        :rtype: MqttManager
        """
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        """Stop the manager when leaving a ``with`` block.

        :param exc: Exception info (ignored; exceptions are not suppressed).
        :type exc: Any
        :return: ``None``
        :rtype: None
        """
        self.stop()

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def publish(
        self,
        topic: str,
        payload: str,
        qos: int = 0,
        retain: bool = False,
        wait: bool = False,
        timeout: Optional[float] = None,
    ) -> None:
        """Publish a message to the broker. Safe to call from any thread.

        :param topic: Topic to publish to.
        :type topic: str
        :param payload: Message payload.
        :type payload: str
        :param qos: Quality of Service level (``0``, ``1`` or ``2``).
        :type qos: int
        :param retain: Whether the broker should retain the message.
        :type retain: bool
        :param wait: If ``True``, block until the message has been delivered
            (meaningful for ``qos`` 1 and 2).
        :type wait: bool
        :param timeout: Maximum seconds to wait when ``wait`` is ``True``;
            ``None`` waits indefinitely.
        :type timeout: Optional[float]
        :raises RuntimeError: If the manager has not been started.
        :raises ConnectionError: If a ``qos`` 0 message cannot be sent
            because there is no broker connection.
        :return: ``None``
        :rtype: None
        """
        client: Optional[paho.Client] = self._client
        if client is None:
            raise RuntimeError(
                "MqttManager is not started — call start() or use lifespan()"
            )
        info: paho.MQTTMessageInfo = client.publish(
            topic, payload=payload, qos=qos, retain=retain
        )
        if info.rc == paho.MQTT_ERR_NO_CONN and qos == 0:
            # QoS 0 messages are not queued while offline, so report it.
            raise ConnectionError("Not connected to MQTT broker")
        if wait:
            info.wait_for_publish(timeout=timeout)

