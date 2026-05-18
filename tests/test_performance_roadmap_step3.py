from pathlib import Path


def test_sampler_exists_and_is_interval_cached():
    code = Path("app_core/system_usage.py").read_text(encoding="utf-8")
    assert "class MetricsSampler:" in code
    assert "def collect(self, prev_net_data: Dict[str, float], intervals: Dict[str, int])" in code
    assert "if now - self._last_update_ts[key] < min_interval:" in code
    assert "self._cache[key] = self._collect_metric(key, prev_net_data)" in code


def test_update_info_uses_sampler_snapshot_and_profiling_toggle():
    code = Path("app_core/app.py").read_text(encoding="utf-8")
    assert "self.metrics_sampler.collect(self.prev_net_data, metric_intervals)" in code
    assert "'profiling_enabled': False" in code
    assert "if self.visibility_settings.get('profiling_enabled', False):" in code
    assert '"Profiling update_info: avg=%.2fms max=%.2fms samples=%d"' in code


def test_graph_draw_paths_use_decimation_cap():
    code = Path("app_core/app.py").read_text(encoding="utf-8")
    assert "def _decimate_samples(samples: list[tuple], max_points: int) -> list[tuple]:" in code
    assert "self._decimate_samples(self._visible_samples('cpu', list(self.cpu_history)), max(200, width * 2))" in code
    assert "self._decimate_samples(self._visible_samples('ram', list(self.ram_history)), max(200, width * 2))" in code
    assert "self._decimate_samples(self._visible_samples('swap', list(self.swap_history)), max(200, width * 2))" in code
    assert "self._decimate_samples(self._visible_samples('disk', list(self.disk_history)), max(200, width * 2))" in code
    assert "self._decimate_samples(self._visible_samples('net', list(self.net_history)), max(200, width * 2))" in code
    assert "self._decimate_samples(self._visible_samples('keyboard', list(self.keyboard_history)), max(200, width * 2))" in code
    assert "self._decimate_samples(self._visible_samples('mouse', list(self.mouse_history)), max(200, width * 2))" in code


def test_roadmap_artifact_kept_for_follow_up_prs():
    report = Path("PROJECT_ANALYSIS_RU.md").read_text(encoding="utf-8")
    assert "P0 (обязательно, высокий эффект)" in report
    assert "P1 (средний приоритет)" in report
    assert "P2 (дальнейшее развитие)" in report
