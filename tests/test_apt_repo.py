"""Сборка apt-репозитория: индексы, подпись InRelease и Release.gpg ключом из отдельного GNUPGHOME."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(not all(shutil.which(t) for t in ("gpg", "gpgv", "dpkg-scanpackages", "dpkg-deb")),
                                reason="нужны gpg и dpkg-dev")


def _fake_deb(directory: Path) -> None:
    pkg = directory / "pkg"
    (pkg / "DEBIAN").mkdir(parents=True)
    (pkg / "DEBIAN" / "control").write_text(
        "Package: symo\nVersion: 9.9.9\nArchitecture: amd64\nMaintainer: Test <t@example.invalid>\n"
        "Description: test\n")
    subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(pkg), str(directory / "symo_9.9.9_amd64.deb")],
                   check=True, capture_output=True)
    shutil.rmtree(pkg)


def test_repository_is_signed_and_indexed(tmp_path):
    gnupg = tmp_path / "gnupg"
    gnupg.mkdir(mode=0o700)
    env = dict(os.environ, GNUPGHOME=str(gnupg))
    subprocess.run(["gpg", "--batch", "--pinentry-mode", "loopback", "--passphrase", "", "--quick-generate-key",
                    "SyMo APT test <test@example.invalid>", "ed25519", "sign", "never"],
                   env=env, check=True, capture_output=True)
    debs = tmp_path / "dist"
    debs.mkdir()
    _fake_deb(debs)
    site = tmp_path / "site"
    subprocess.run([str(ROOT / "build-apt-repo.sh"), str(debs), str(site)], env=env, check=True, capture_output=True)

    names = {p.name for p in site.iterdir()}
    assert {"InRelease", "Release", "Release.gpg", "Packages", "Packages.gz", "symo.gpg", "symo_9.9.9_amd64.deb",
            "index.html", ".nojekyll"} <= names
    assert "Package: symo\nVersion: 9.9.9" in (site / "Packages").read_text()
    release = (site / "Release").read_text()
    assert "SHA256:" in release and " Packages.gz" in release
    for args in (["InRelease"], ["Release.gpg", "Release"]):
        subprocess.run(["gpgv", "--keyring", str(site / "symo.gpg"), *args], cwd=site, check=True, capture_output=True)
