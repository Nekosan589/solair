"""Reusable MQTT manager with a synchronous core and an asyncio wrapper.

This module provides one classe:

* :class:`AsyncMqttManager` -- a subclass that adds ``async``/``await``
  support so the same functionality can be used inside a FastAPI server.

Asynchronous (FastAPI) usage::

    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from mqtt_manager import AsyncMqttManager

    mqtt = AsyncMqttManager(host="localhost", port=1883)

    @mqtt.on_topic("sensors/+/temperature")
    async def handle_temp(topic: str, payload: str) -> None:
        print(f"{topic} -> {payload}")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with mqtt.lifespan():
            yield

    app = FastAPI(lifespan=lifespan)


"""
from mqtt.paho_mqtt_manager import MqttManager


import asyncio
import contextlib
import inspect
import logging
import ssl
from concurrent.futures import Future
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Optional,
    Union,
)

logger: logging.Logger = logging.getLogger("mqtt_manager")

SyncHandler = Callable[[str, str], None]
"""A plain function ``handler(topic, payload) -> None``."""

AsyncHandler = Callable[[str, str], Awaitable[None]]
"""A coroutine function ``async handler(topic, payload) -> None``."""

Handler = Union[SyncHandler, AsyncHandler]
"""Any handler type. Async handlers are only supported by :class:`AsyncMqttManager`."""



class AsyncMqttManager(MqttManager):
    """Asyncio-friendly version of :class:`MqttManager` for FastAPI.

    It reuses the synchronous engine and adds:

    * ``await start()``, ``await stop()`` and ``async with lifespan()``.
    * Support for ``async def`` handlers. Both async and plain handlers are
      executed on the asyncio event loop (not paho's thread), so they can
      safely use async libraries and touch application state.
    * ``await publish(...)``.

    The constructor takes the same parameters as :class:`MqttManager`.
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
        super().__init__(
            host=host,
            port=port,
            username=username,
            password=password,
            client_id=client_id,
            reconnect_interval=reconnect_interval,
            tls_context=tls_context,
            keepalive=keepalive,
        )
        # Event loop captured in ``start()``; handlers are scheduled onto it.
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ------------------------------------------------------------------
    # Dispatch onto the event loop
    # ------------------------------------------------------------------

    def _invoke(self, handler: Handler, topic: str, payload: str) -> None:
        """Run a handler on the asyncio event loop (overrides the base).

        Called from paho's thread, so everything is scheduled thread-safely:
        coroutine functions via :func:`asyncio.run_coroutine_threadsafe`, plain
        functions via :meth:`asyncio.AbstractEventLoop.call_soon_threadsafe`.
        Messages are dropped if the loop is missing or closed.

        :param handler: Sync or async handler to execute.
        :type handler: Handler
        :param topic: Topic of the received message.
        :type topic: str
        :param payload: Decoded message payload.
        :type payload: str
        :return: ``None``
        :rtype: None
        """
        loop: Optional[asyncio.AbstractEventLoop] = self._loop
        if loop is None or loop.is_closed():
            return

        if inspect.iscoroutinefunction(handler):
            future: "Future[None]" = asyncio.run_coroutine_threadsafe(
                handler(topic, payload), loop
            )
            future.add_done_callback(self._log_future_error)
        else:
            loop.call_soon_threadsafe(self._run_sync_handler, handler, topic, payload)

    @staticmethod
    def _log_future_error(future: "Future[None]") -> None:
        """Log an exception raised inside an async handler.

        :param future: The completed future wrapping the handler coroutine.
        :type future: concurrent.futures.Future
        :return: ``None``
        :rtype: None
        """
        if future.cancelled():
            return
        exc: Optional[BaseException] = future.exception()
        if exc is not None:
            logger.error("Error in async MQTT handler", exc_info=exc)

    @staticmethod
    def _run_sync_handler(handler: Handler, topic: str, payload: str) -> None:
        """Run a plain handler on the event loop, logging any exception.

        :param handler: Plain (non-async) handler.
        :type handler: Handler
        :param topic: Topic of the received message.
        :type topic: str
        :param payload: Decoded message payload.
        :type payload: str
        :return: ``None``
        :rtype: None
        """
        try:
            handler(topic, payload)
        except Exception:
            logger.exception("Error in MQTT handler for topic %r", topic)

    # ------------------------------------------------------------------
    # Async lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:  # type: ignore[override]
        """Capture the running event loop and start the manager.

        Must be awaited from inside the event loop that should run the
        handlers (e.g. FastAPI's lifespan).

        :return: ``None``
        :rtype: None
        """
        self._loop = asyncio.get_running_loop()
        # ``connect_async`` and ``loop_start`` do not block, so no thread hop.
        super().start()

    async def stop(self) -> None:  # type: ignore[override]
        """Stop the manager without blocking the event loop.

        ``loop_stop()`` joins paho's thread, so it is run in a worker thread.

        :return: ``None``
        :rtype: None
        """
        await asyncio.to_thread(super().stop)
        self._loop = None

    @contextlib.asynccontextmanager
    async def lifespan(self) -> AsyncIterator["AsyncMqttManager"]:  # type: ignore[override]
        """Async context manager that starts and stops the manager.

        Example (FastAPI)::

            @asynccontextmanager
            async def lifespan(app: FastAPI):
                async with mqtt.lifespan():
                    yield

        :return: An async iterator yielding this manager.
        :rtype: AsyncIterator[AsyncMqttManager]
        """
        await self.start()
        try:
            yield self
        finally:
            await self.stop()

    async def __aenter__(self) -> "AsyncMqttManager":
        """Start the manager when entering an ``async with`` block.

        :return: This manager.
        :rtype: AsyncMqttManager
        """
        await self.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        """Stop the manager when leaving an ``async with`` block.

        :param exc: Exception info (ignored; exceptions are not suppressed).
        :type exc: Any
        :return: ``None``
        :rtype: None
        """
        await self.stop()

    # ------------------------------------------------------------------
    # Async publish
    # ------------------------------------------------------------------

    async def publish(  # type: ignore[override]
        self,
        topic: str,
        payload: str,
        qos: int = 0,
        retain: bool = False,
        wait: bool = False,
        timeout: Optional[float] = None,
    ) -> None:
        """Publish a message without blocking the event loop.

        Parameters and errors are the same as :meth:`MqttManager.publish`.
        With ``wait=True`` the blocking wait runs in a worker thread.

        :param topic: Topic to publish to.
        :type topic: str
        :param payload: Message payload.
        :type payload: str
        :param qos: Quality of Service level (``0``, ``1`` or ``2``).
        :type qos: int
        :param retain: Whether the broker should retain the message.
        :type retain: bool
        :param wait: If ``True``, wait until the message is delivered.
        :type wait: bool
        :param timeout: Maximum seconds to wait when ``wait`` is ``True``.
        :type timeout: Optional[float]
        :raises RuntimeError: If the manager has not been started.
        :raises ConnectionError: If a ``qos`` 0 message cannot be sent
            because there is no broker connection.
        :return: ``None``
        :rtype: None
        """
        if wait:
            await asyncio.to_thread(
                super().publish, topic, payload, qos, retain, True, timeout
            )
        else:
            super().publish(topic, payload, qos, retain)

