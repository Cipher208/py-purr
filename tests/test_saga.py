"""Tests for PURR Saga."""

import pytest
from purr import Saga, SagaStatus


@pytest.mark.asyncio
async def test_saga_success():
    async def step1(data):
        return {"step1": True}

    async def step2(data):
        return {"step2": True}

    saga = Saga("test")
    saga.add_step("step1", step1)
    saga.add_step("step2", step2)

    result = await saga.execute({"start": True})
    assert result == {"start": True, "step1": True, "step2": True}
    assert saga.status == SagaStatus.COMPLETED


@pytest.mark.asyncio
async def test_saga_compensation():
    call_log = []

    async def step1(data):
        call_log.append("step1")
        return {"step1": True}

    async def step2(data):
        call_log.append("step2")
        raise ValueError("step2 failed")

    async def compensate1(data):
        call_log.append("compensate1")

    saga = Saga("test")
    saga.add_step("step1", step1, compensation=compensate1)
    saga.add_step("step2", step2)

    with pytest.raises(ValueError):
        await saga.execute()

    assert call_log == ["step1", "step2", "compensate1"]
    assert saga.status == SagaStatus.COMPENSATED


@pytest.mark.asyncio
async def test_saga_step_failure():
    async def step1(data):
        return {"step1": True}

    async def step2(data):
        raise RuntimeError("boom")

    saga = Saga("test")
    saga.add_step("step1", step1)
    saga.add_step("step2", step2)

    with pytest.raises(RuntimeError):
        await saga.execute()

    assert saga.status == SagaStatus.FAILED


def test_saga_get_state():
    saga = Saga("test")
    state = saga.get_state()
    assert state["name"] == "test"
    assert state["status"] == "pending"
    assert state["current_step"] == 0
