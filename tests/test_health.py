"""HealthChecker contract: register, check, aggregate (Task 2)."""

from purr.health import ComponentHealth, HealthChecker, HealthStatus


def test_register_defaults_healthy():
    hc = HealthChecker()
    hc.register("db")
    assert hc.check("db") is HealthStatus.HEALTHY


def test_unknown_component_is_unhealthy():
    hc = HealthChecker()
    assert hc.check("ghost") is HealthStatus.UNHEALTHY


def test_bool_check_fn_maps_to_status():
    hc = HealthChecker()
    hc.register("cache", check_fn=lambda: True)
    assert hc.check("cache") is HealthStatus.HEALTHY
    hc.register("queue", check_fn=lambda: False)
    assert hc.check("queue") is HealthStatus.UNHEALTHY


def test_throwing_check_fn_marks_unhealthy_with_error():
    hc = HealthChecker()

    def boom():
        raise RuntimeError("disk gone")

    hc.register("disk", check_fn=boom)
    assert hc.check("disk") is HealthStatus.UNHEALTHY
    assert "disk gone" in hc._components["disk"].error


def test_update_and_aggregate_status():
    hc = HealthChecker()
    hc.register("a")
    hc.register("b")
    hc.update("b", HealthStatus.DEGRADED)
    status = hc.get_status()
    assert status["overall"] == HealthStatus.DEGRADED.value
    hc.update("b", HealthStatus.UNHEALTHY)
    assert hc.get_status()["overall"] == HealthStatus.UNHEALTHY
    assert isinstance(hc._components["a"], ComponentHealth)
