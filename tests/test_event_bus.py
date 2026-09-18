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
