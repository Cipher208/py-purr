"""Tests for PURR EventBus."""

import pytest

from purr import Event, EventBus, EventType


@pytest.mark.asyncio
async def test_publish_subscribe():
    bus = EventBus()
    received = []

    async def handler(event: Event):
        received.append(event)

    bus.subscribe("test.topic", handler)
    await bus.publish(Event(type=EventType.SYSTEM, topic="test.topic", payload={"key": "value"}))

    assert len(received) == 1
    assert received[0].payload == {"key": "value"}


@pytest.mark.asyncio
async def test_wildcard_subscribe():
    bus = EventBus()
    received = []

    async def handler(event: Event):
        received.append(event.topic)

    bus.subscribe("*", handler)
    await bus.publish(Event(type=EventType.SYSTEM, topic="a.b.c"))
    await bus.publish(Event(type=EventType.STORE, topic="x.y.z"))

    assert received == ["a.b.c", "x.y.z"]


@pytest.mark.asyncio
async def test_unsubscribe():
    bus = EventBus()
    received = []

    async def handler(event: Event):
        received.append(event)

    bus.subscribe("test", handler)
    bus.unsubscribe("test", handler)
    await bus.publish(Event(type=EventType.SYSTEM, topic="test"))

    assert len(received) == 0


def test_history():
    bus = EventBus()
    bus.publish_sync(Event(type=EventType.SYSTEM, topic="a"))
    bus.publish_sync(Event(type=EventType.SYSTEM, topic="b"))
    bus.publish_sync(Event(type=EventType.STORE, topic="c"))

    assert len(bus.get_history()) == 3
    assert len(bus.get_history(topic="a")) == 1
    assert len(bus.get_history(topic="c")) == 1


class TestHandlerErrorReporting:
    def test_handler_error_reported_via_callback(self):
        import asyncio

        bus = EventBus(on_handler_error=lambda ev, exc: reported.append((ev.id, exc)))
        reported: list = []
        # rebuild bus after list exists (closure binding)
        bus = EventBus(on_handler_error=lambda ev, exc: reported.append((ev.id, exc)))

        async def bad_handler(event):
            raise ValueError("boom")

        async def run():
            ev = Event(type=EventType.SYSTEM, topic="t", payload={})
            bus.subscribe("t", bad_handler)
            await bus.publish(ev)
            return ev

        ev = asyncio.run(run())
        assert len(reported) == 1
        assert reported[0][0] == ev.id
        assert isinstance(reported[0][1], ValueError)

    def test_handler_error_callback_sync(self):
        reported: list = []
        bus = EventBus(on_handler_error=lambda ev, exc: reported.append((ev.id, exc)))
        ev = Event(type=EventType.SYSTEM, topic="t", payload={})
        bus.subscribe("t", lambda e: 1 / 0)
        bus.publish_sync(ev)
        assert len(reported) == 1
        assert isinstance(reported[0][1], ZeroDivisionError)

    def test_on_handler_error_exceptions_swallowed(self):
        def bad_cb(ev, exc):
            raise RuntimeError("callback broke")

        bus = EventBus(on_handler_error=bad_cb)
        bus.subscribe("t", lambda e: 1 / 0)
        bus.publish_sync(Event(type=EventType.SYSTEM, topic="t", payload={}))

    def test_default_stays_silent(self):
        from purr import EventBus

        bus = EventBus()
        bus.subscribe("t", lambda e: 1 / 0)
        bus.publish(Event(type=EventType.SYSTEM, topic="t", payload={}))
        bus.publish_sync(Event(type=EventType.SYSTEM, topic="t", payload={}))
