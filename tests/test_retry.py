"""RetryHandler contract: success-after-failures, exhaustion (Task 2)."""

import asyncio

import pytest

from purr.retry import RetryConfig, RetryHandler


def _fast_config(**over):
    kw = {"max_retries": 3, "base_delay": 0.001, "max_delay": 0.01, "jitter": False}
    kw.update(over)
    return RetryConfig(**kw)


def test_succeeds_on_third_attempt():
    async def go():
        attempts = []

        async def flaky():
            attempts.append(1)
            if len(attempts) < 3:
                raise RuntimeError("not yet")
            return "ok"

        result = await RetryHandler(_fast_config()).execute(flaky)
        return result, len(attempts)

    result, attempts = asyncio.run(go())
    assert result == "ok"
    assert attempts == 3


def test_exhaustion_reraises_last_error():
    async def go():
        async def always():
            raise ValueError("dead")

        await RetryHandler(_fast_config(max_retries=2)).execute(always)

    with pytest.raises(ValueError, match="dead"):
        asyncio.run(go())


def test_delay_grows_exponentially_capped():
    h = RetryHandler(_fast_config(base_delay=1.0, max_delay=2.5, exponential_base=2.0))
    assert h._calculate_delay(1) == pytest.approx(1.0)
    assert h._calculate_delay(2) == pytest.approx(2.0)
    assert h._calculate_delay(3) == pytest.approx(2.5)
