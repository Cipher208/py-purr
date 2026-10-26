"""P2 Saga fixes: value comparison on write tracking and rollback fidelity.

The write tracker used `snapshot[k] != self._data[k]` on a shallow copy:

* a value with a non-scalar `__ne__` (numpy.ndarray, pandas.Series) raised
  `ValueError: truth value is ambiguous` inside the step's try block, so a
  *successful* step was marked FAILED and its error replaced the real one;
* in-place nested mutations (`data["items"].append(2)`) were invisible
  because the shallow snapshot shared the mutated object;
* rollback used `pop()`, deleting pre-existing keys instead of restoring
  their old values, and never restored keys deleted by the step.
"""

from __future__ import annotations

import pytest

from purr import Saga, SagaStatus


class Ambiguous:
    """Minimal stand-in for numpy.ndarray / pandas.Series.

    Comparison yields a non-bool and `bool()` of it raises, which is what
    `if snapshot[k] != self._data[k]` could not survive.
    """

    def __init__(self, value: int = 0) -> None:
        self.value = value

    def __eq__(self, other: object) -> Ambiguous:
        return self

    def __ne__(self, other: object) -> Ambiguous:
        return self

    def __bool__(self) -> bool:
        msg = "The truth value of an array with more than one element is ambiguous"
        raise ValueError(msg)

    __hash__ = None  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_saga_step_with_arraylike_value_does_not_fail():
    """A step writing an array-like value must complete; the failure that
    surfaces must be the *later* step's, not a comparison ValueError."""

    compensated = []

    async def act1(data):
        data["arr"] = Ambiguous(1)
        return {"arr": Ambiguous(1)}

    async def comp1(data):
        compensated.append("comp1")

    async def act2(data):
        raise RuntimeError("second step failed")

    saga = Saga("test")
    saga.add_step("s1", act1, compensation=comp1)
    saga.add_step("s2", act2)

    with pytest.raises(RuntimeError) as exc_info:
        await saga.execute({"arr": Ambiguous(0)})

    assert "second step failed" in str(exc_info.value)
    assert saga.status == SagaStatus.COMPENSATED
    assert saga.get_state()["steps"][0]["status"] == "completed"
    assert saga.get_state()["steps"][1]["status"] == "failed"
    assert compensated == ["comp1"]


@pytest.mark.asyncio
async def test_saga_nested_mutation_rolled_back():
    """In-place mutation of a nested container must be rolled back."""

    async def act1(data):
        data["items"].append(2)
        return {}

    async def act2(data):
        raise RuntimeError("boom")

    saga = Saga("test")
    saga.add_step("s1", act1)
    saga.add_step("s2", act2)

    with pytest.raises(RuntimeError):
        await saga.execute({"items": [1]})

    assert saga.status == SagaStatus.COMPENSATED
    assert saga.data["items"] == [1]


@pytest.mark.asyncio
async def test_saga_restores_overwritten_value():
    """A pre-existing key overwritten by a compensated step gets its old
    value back instead of being deleted."""

    async def act1(data):
        return {"a": 1}

    async def act2(data):
        raise RuntimeError("boom")

    saga = Saga("test")
    saga.add_step("s1", act1)
    saga.add_step("s2", act2)

    with pytest.raises(RuntimeError):
        await saga.execute({"a": 0})

    assert saga.status == SagaStatus.COMPENSATED
    assert saga.data == {"a": 0}


@pytest.mark.asyncio
async def test_saga_restores_deleted_key():
    """A key deleted by a compensated step is restored with its old value."""

    async def act1(data):
        del data["k"]
        return {}

    async def act2(data):
        raise RuntimeError("boom")

    saga = Saga("test")
    saga.add_step("s1", act1)
    saga.add_step("s2", act2)

    with pytest.raises(RuntimeError):
        await saga.execute({"k": "keep", "keep": 1})

    assert saga.status == SagaStatus.COMPENSATED
    assert saga.data == {"k": "keep", "keep": 1}
