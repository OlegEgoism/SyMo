import io
import json

from app_core import updates


def test_version_comparison():
    assert updates.parse_version("v1.2.10") == (1, 2, 10)
    assert updates.parse_version("beta") is None
    assert updates.is_newer("v1.3.0", "1.2.0") and updates.is_newer("1.10", "1.9.9")
    assert not updates.is_newer("1.2.0", "1.2.0") and not updates.is_newer("", "1.2.0")


def test_fetch_latest_version(monkeypatch):
    monkeypatch.setattr(updates.urllib.request, "urlopen",
                        lambda request, timeout: io.BytesIO(json.dumps({"tag_name": "v2.0.1"}).encode()))
    assert updates.fetch_latest_version() == "2.0.1"

    def offline(request, timeout):
        raise OSError("no network")

    monkeypatch.setattr(updates.urllib.request, "urlopen", offline)
    assert updates.fetch_latest_version() is None
