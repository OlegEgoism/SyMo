#!/usr/bin/env bash
set -euo pipefail

APP_NAME="SyMo"
PKG_NAME="symo"
VERSION="${1:-1.0.0}"
RELEASE="${2:-1}"
RPMROOT="${PWD}/packaging/rpm"
TOPDIR="${RPMROOT}/rpmbuild"
TARBALL_DIR="${TOPDIR}/SOURCES"
SPEC_DIR="${TOPDIR}/SPECS"

if ! command -v rpmbuild >/dev/null 2>&1; then
  echo "rpmbuild is required (install: rpm-build)"
  exit 1
fi

rm -rf "${TOPDIR}"
mkdir -p "${TOPDIR}"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}

SRC_DIR="${RPMROOT}/${PKG_NAME}-${VERSION}"
rm -rf "${SRC_DIR}"
mkdir -p "${SRC_DIR}"
cp -r app.py app_core notifications requirements.txt logo.png README.md "${SRC_DIR}/"

cat > "${SRC_DIR}/${PKG_NAME}" <<'LAUNCH'
#!/usr/bin/env bash
set -euo pipefail
cd /opt/symo
exec python3 app.py "$@"
LAUNCH
chmod +x "${SRC_DIR}/${PKG_NAME}"

cat > "${SRC_DIR}/${PKG_NAME}.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=${APP_NAME}
Comment=SyMo System Monitor Tray App
Exec=${PKG_NAME}
Icon=${PKG_NAME}
Terminal=false
Categories=Utility;System;
DESKTOP

mkdir -p "${TARBALL_DIR}"
tar -C "${RPMROOT}" -czf "${TARBALL_DIR}/${PKG_NAME}-${VERSION}.tar.gz" "${PKG_NAME}-${VERSION}"

mkdir -p "${SPEC_DIR}"
cat > "${SPEC_DIR}/${PKG_NAME}.spec" <<SPEC
Name:           ${PKG_NAME}
Version:        ${VERSION}
Release:        ${RELEASE}%{?dist}
Summary:        GTK system tray monitor for Linux
License:        MIT
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch
Requires:       python3, python3-gobject, python3-psutil, python3-requests

%description
SyMo displays system metrics in tray, includes power controls,
and can send Telegram/Discord notifications.

%prep
%autosetup

%build

%install
mkdir -p %{buildroot}/opt/symo
cp -r app.py app_core notifications requirements.txt README.md %{buildroot}/opt/symo/
install -D -m 0755 ${PKG_NAME} %{buildroot}/usr/bin/${PKG_NAME}
install -D -m 0644 logo.png %{buildroot}/usr/share/pixmaps/${PKG_NAME}.png
install -D -m 0644 ${PKG_NAME}.desktop %{buildroot}/usr/share/applications/${PKG_NAME}.desktop

%post
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database /usr/share/applications >/dev/null 2>&1 || :
fi

%files
/opt/symo/app.py
/opt/symo/app_core
/opt/symo/notifications
/opt/symo/requirements.txt
/opt/symo/README.md
/usr/bin/${PKG_NAME}
/usr/share/pixmaps/${PKG_NAME}.png
/usr/share/applications/${PKG_NAME}.desktop

%changelog
* Sat Mar 14 2026 SyMo Maintainers <maintainers@example.com> - ${VERSION}-${RELEASE}
- Initial RPM packaging
SPEC

rpmbuild --define "_topdir ${TOPDIR}" -ba "${SPEC_DIR}/${PKG_NAME}.spec"

find "${TOPDIR}/RPMS" -name '*.rpm' -print
