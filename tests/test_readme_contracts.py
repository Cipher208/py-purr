"""README-contract tests: every README tour must run verbatim (D1)."""

from purr import DedupMiddleware, Event, EventBus, EventStream, EventType, Saga, StateMachine, Store


def test_store_tour():
    s = Store(":memory:")
    s.set("user:1001", {"name": "Alice", "role": "admin"})
    assert s.get("user:1001") == {"name": "Alice", "role": "admin"}
    s.set("session_token", "xyz-123", ttl=3600)
    s.mset({"counter": 0, "status": "active"})
    assert s.incr("counter", 1) == 1


def test_state_machine_tour():
    sm = StateMachine("order_pipeline", db_path=":memory:")
    sm.add_transition("idle", "processing", "start_job")
    sm.add_transition("processing", "completed", "finish_job")
    sm.set_state("idle")
    assert sm.send("start_job") is True
    assert sm.current_state == "processing"


def test_saga_tour():
    import asyncio

    import pytest

    async def go():
        saga = Saga("deploy_workflow")
        state = {}

        async def alloc(ctx):
            ctx["allocated"] = True
            return ctx

        async def release(ctx):
            state["compensated"] = True

        async def boom(ctx):
            raise RuntimeError("Migration failed!")

        saga.add_step("reserve", alloc, compensation=release)
        saga.add_step("migrate", boom)
        with pytest.raises(RuntimeError, match="Migration failed!"):
            await saga.execute()
        return state

    assert asyncio.run(go()) == {"compensated": True}


def test_event_stream_tour():
    es = EventStream(":memory:")
    es.append(Event(type=EventType.SYSTEM, topic="user_signups", payload={"user_id": 42}))
    es.set_cursor("c1", es.read(topic="user_signups")[1])
    events, _ = es.read(topic="user_signups", limit=50)
    assert events[0].payload == {"user_id": 42}


def test_event_bus_tour():
    import asyncio

    async def go():
        bus = EventBus()
        seen = []

        async def handle_alert(event):
            seen.append(event.payload)

        bus.subscribe("system.alerts.cpu", handle_alert)
        event = Event(type=EventType.SYSTEM, topic="system.alerts.cpu", payload={"usage": "98%"})
        await bus.publish(event)
        return seen

    assert asyncio.run(go()) == [{"usage": "98%"}]


def test_dedup_middleware_options():
    """DedupMiddleware takes max_size/ttl_seconds (not window_seconds)."""
    import inspect

    params = inspect.signature(DedupMiddleware.__init__).parameters
    assert "ttl_seconds" in params
    assert "window_seconds" not in params
