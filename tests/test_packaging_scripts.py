from pathlib import Path


def test_deb_packaging_script_exists_and_uses_dpkg_deb():
    code = Path('scripts/create-deb-package.sh').read_text(encoding='utf-8')
    assert 'dpkg-deb --build' in code
    assert 'Package: ${PKG_NAME}' in code
    assert '/usr/share/applications/${PKG_NAME}.desktop' in code


def test_rpm_packaging_script_exists_and_uses_rpmbuild():
    code = Path('scripts/create-rpm-package.sh').read_text(encoding='utf-8')
    assert 'rpmbuild --define "_topdir ${TOPDIR}" -ba' in code
    assert 'Name:           ${PKG_NAME}' in code
    assert 'install -D -m 0755 ${PKG_NAME} %{buildroot}/usr/bin/${PKG_NAME}' in code


def test_readme_has_package_build_section():
    readme = Path('README.md').read_text(encoding='utf-8')
    assert 'Package Build (DEB/RPM, without `build.sh`)' in readme
    assert './scripts/create-deb-package.sh 1.0.0' in readme
    assert './scripts/create-rpm-package.sh 1.0.0 1' in readme
