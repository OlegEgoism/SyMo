import time

from app_core.system_usage import MetricsSampler, SystemUsage


def test_metrics_sampler_reuses_cached_values_until_interval_elapsed(monkeypatch):
    counters = {
        "cpu_temp": 0,
        "cpu_usage": 0,
        "ram": 0,
        "swap": 0,
        "disk": 0,
        "net": 0,
        "uptime": 0,
    }

    monkeypatch.setattr(SystemUsage, "get_cpu_temp", staticmethod(lambda: counters.__setitem__("cpu_temp", counters["cpu_temp"] + 1) or 42))
    monkeypatch.setattr(SystemUsage, "get_cpu_usage", staticmethod(lambda: counters.__setitem__("cpu_usage", counters["cpu_usage"] + 1) or 12.5))
    monkeypatch.setattr(SystemUsage, "get_ram_usage", staticmethod(lambda: counters.__setitem__("ram", counters["ram"] + 1) or (1.0, 8.0)))
    monkeypatch.setattr(SystemUsage, "get_swap_usage", staticmethod(lambda: counters.__setitem__("swap", counters["swap"] + 1) or (0.1, 2.0)))
    monkeypatch.setattr(SystemUsage, "get_disk_usage", staticmethod(lambda: counters.__setitem__("disk", counters["disk"] + 1) or (20.0, 100.0)))
    monkeypatch.setattr(SystemUsage, "get_network_speed", staticmethod(lambda _prev: counters.__setitem__("net", counters["net"] + 1) or (0.2, 0.3)))
    monkeypatch.setattr(SystemUsage, "get_uptime", staticmethod(lambda: counters.__setitem__("uptime", counters["uptime"] + 1) or "0:00:30"))

    sampler = MetricsSampler()
    prev_net = {"recv": 0.0, "sent": 0.0, "time": time.time()}
    intervals = {k: 3 for k in counters}

    first = sampler.collect(prev_net, intervals)
    second = sampler.collect(prev_net, intervals)

    assert first == second
    assert counters == {k: 1 for k in counters}


def test_metrics_sampler_refreshes_after_interval(monkeypatch):
    values = {"cpu": 0.0}

    def cpu_usage():
        values["cpu"] += 10.0
        return values["cpu"]

    monkeypatch.setattr(SystemUsage, "get_cpu_usage", staticmethod(cpu_usage))
    monkeypatch.setattr(SystemUsage, "get_cpu_temp", staticmethod(lambda: 40))
    monkeypatch.setattr(SystemUsage, "get_ram_usage", staticmethod(lambda: (1.0, 8.0)))
    monkeypatch.setattr(SystemUsage, "get_swap_usage", staticmethod(lambda: (0.1, 2.0)))
    monkeypatch.setattr(SystemUsage, "get_disk_usage", staticmethod(lambda: (20.0, 100.0)))
    monkeypatch.setattr(SystemUsage, "get_network_speed", staticmethod(lambda _prev: (0.0, 0.0)))
    monkeypatch.setattr(SystemUsage, "get_uptime", staticmethod(lambda: "0:01:00"))

    sampler = MetricsSampler()
    prev_net = {"recv": 0.0, "sent": 0.0, "time": time.time()}

    v1 = sampler.collect(prev_net, {"cpu_usage": 1})["cpu_usage"]
    v2 = sampler.collect(prev_net, {"cpu_usage": 1})["cpu_usage"]
    assert v1 == v2

    time.sleep(1.05)
    v3 = sampler.collect(prev_net, {"cpu_usage": 1})["cpu_usage"]
    assert v3 > v2
