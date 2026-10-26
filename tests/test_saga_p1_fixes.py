"""P1-6 Saga fixes: stale per-step state on re-execute, data rollback on compensation."""

import pytest

from purr import Saga, SagaStatus


@pytest.mark.asyncio
async def test_saga_reexecute_no_stale_compensations():
    """Audit P1-6a: execute() reset _status/_current_step but not per-step
    status, so a re-executed saga carried stale COMPLETED steps from the
    previous run (saga.py:107-109 compensates everything COMPLETED).

    Scenario (audit): run 1 completes s1 (compensation COMP1). Run 2
    re-executes with a failing first step: no compensation may fire (the
    failure is at step 0, nothing completed in run 2), and no step may
    report a stale status from run 1.
    """
    log = []

    async def act1(data):
        if data.get("fail_step0"):
            log.append("act1-fail")
            raise RuntimeError("act1 failed")
        log.append("act1")
        return {"a": 1}

    async def comp1(data):
        log.append("COMP1")

    async def ok2(data):
        log.append("ok2")
        return {"b": 2}

    saga = Saga("test")
    saga.add_step("s1", act1, compensation=comp1)
    saga.add_step("s2", ok2)

    # Run 1: completes fully.
    await saga.execute()
    assert log == ["act1", "ok2"]
    assert saga.status == SagaStatus.COMPLETED

    # Run 2: fails at step 0. COMP1 must NOT fire (s1 did not complete
    # in run 2), and no step may keep a stale run-1 status.
    log.clear()
    with pytest.raises(RuntimeError):
        await saga.execute({"fail_step0": True})

    assert log == ["act1-fail"]  # no COMP1 from run 1
    assert saga.status == SagaStatus.COMPENSATED  # failure path always compensates
    state = {s["name"]: s["status"] for s in saga.get_state()["steps"]}
    assert state["s1"] == "failed"
    assert state["s2"] == "pending"  # not stale "completed" from run 1

    # Run 3: clean re-execution succeeds again.
    log.clear()
    await saga.execute()
    assert log == ["act1", "ok2"]
    assert saga.status == SagaStatus.COMPLETED


@pytest.mark.asyncio
async def test_saga_data_rolled_back_on_compensation():
    """Audit P1-6b: after compensation, saga.data must not contain keys
    written by compensated steps."""

    async def act1(data):
        return {"a": 1}

    async def act2(data):
        return {"b": 2}

    async def fail(data):
        raise RuntimeError("boom")

    async def comp(data):
        pass

    saga = Saga("test")
    saga.add_step("s1", act1, compensation=comp)
    saga.add_step("s2", act2, compensation=comp)
    saga.add_step("s3", fail)

    with pytest.raises(RuntimeError):
        await saga.execute()

    assert saga.status == SagaStatus.COMPENSATED
    assert "a" not in saga.data
    assert "b" not in saga.data


@pytest.mark.asyncio
async def test_saga_data_rolled_back_without_compensation():
    """A step without a compensation callback must still have its written
    keys rolled back when a later step fails."""

    async def act1(data):
        return {"a": 1}

    async def fail(data):
        raise RuntimeError("boom")

    saga = Saga("test")
    saga.add_step("s1", act1)  # no compensation callback
    saga.add_step("s2", fail)

    with pytest.raises(RuntimeError):
        await saga.execute()

    assert saga.status == SagaStatus.COMPENSATED
    assert "a" not in saga.data


@pytest.mark.asyncio
async def test_saga_reexecute_fresh_compensations_documented():
    """Documents the contract: execute() re-runs ALL steps, so a step
    completed in an earlier run re-completes and its compensation fires
    for failures later in the *current* run (same as a first run).
    Compensations are per-run: exactly one firing per completed step."""

    async def act1(data):
        return {"a": 1}

    async def boom(data):
        raise RuntimeError("boom")

    count = {"n": 0}

    async def comp1(data):
        count["n"] += 1

    saga = Saga("test")
    saga.add_step("s1", act1, compensation=comp1)
    saga.add_step("s2", boom)

    with pytest.raises(RuntimeError):
        await saga.execute()
    assert count["n"] == 1

    with pytest.raises(RuntimeError):
        await saga.execute()
    assert count["n"] == 2  # one per run, for this run's completion
