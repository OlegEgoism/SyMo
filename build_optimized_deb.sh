#!/bin/bash

# Optimized build script for SyMo with bundled dependencies
# Creates a self-contained package with minimal external dependencies

PACKAGE_NAME="SyMo"
VERSION="1.0.1"
MAINTAINER="Your Name <olegpustovalov220@gmail.com>"
DESCRIPTION="SyMo system monitor with tray icon (optimized build)"

# Minimal system dependencies (only what can't be bundled)
DEPENDS="python3 (>= 3.8), python3-gi, gir1.2-gtk-3.0, gir1.2-appindicator3-0.1, gir1.2-glib-2.0"

# Create build directory
BUILD_DIR="deb_build_optimized"
rm -rf ${BUILD_DIR}
mkdir -p ${BUILD_DIR}/DEBIAN
mkdir -p ${BUILD_DIR}/usr/share/${PACKAGE_NAME}
mkdir -p ${BUILD_DIR}/usr/share/${PACKAGE_NAME}/lib
mkdir -p ${BUILD_DIR}/usr/share/applications
mkdir -p ${BUILD_DIR}/usr/share/icons/hicolor/48x48/apps
mkdir -p ${BUILD_DIR}/usr/bin

# Copy application files
cp app.py language.py logo.png ${BUILD_DIR}/usr/share/${PACKAGE_NAME}/

# Create virtual environment for bundling Python dependencies
echo "Creating virtual environment and installing dependencies..."
python3 -m venv temp_venv
source temp_venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt --target ${BUILD_DIR}/usr/share/${PACKAGE_NAME}/lib

# Clean up unnecessary files to reduce size
echo "Optimizing package size..."
find ${BUILD_DIR}/usr/share/${PACKAGE_NAME}/lib -name "*.pyc" -delete
find ${BUILD_DIR}/usr/share/${PACKAGE_NAME}/lib -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find ${BUILD_DIR}/usr/share/${PACKAGE_NAME}/lib -name "*.pyo" -delete
find ${BUILD_DIR}/usr/share/${PACKAGE_NAME}/lib -name "tests" -type d -exec rm -rf {} + 2>/dev/null || true
find ${BUILD_DIR}/usr/share/${PACKAGE_NAME}/lib -name "test_*" -delete 2>/dev/null || true
find ${BUILD_DIR}/usr/share/${PACKAGE_NAME}/lib -name "*test.py" -delete 2>/dev/null || true

# Remove documentation and examples to reduce size
find ${BUILD_DIR}/usr/share/${PACKAGE_NAME}/lib -name "docs" -type d -exec rm -rf {} + 2>/dev/null || true
find ${BUILD_DIR}/usr/share/${PACKAGE_NAME}/lib -name "examples" -type d -exec rm -rf {} + 2>/dev/null || true
find ${BUILD_DIR}/usr/share/${PACKAGE_NAME}/lib -name "*.md" -delete 2>/dev/null || true
find ${BUILD_DIR}/usr/share/${PACKAGE_NAME}/lib -name "*.rst" -delete 2>/dev/null || true
find ${BUILD_DIR}/usr/share/${PACKAGE_NAME}/lib -name "*.txt" -delete 2>/dev/null || true

# Keep only essential files for pycairo (remove dev/source files)
if [ -d "${BUILD_DIR}/usr/share/${PACKAGE_NAME}/lib/cairo" ]; then
    find ${BUILD_DIR}/usr/share/${PACKAGE_NAME}/lib/cairo -name "*.h" -delete 2>/dev/null || true
    find ${BUILD_DIR}/usr/share/${PACKAGE_NAME}/lib/cairo -name "*.c" -delete 2>/dev/null || true
fi

deactivate
rm -rf temp_venv

# Create optimized launcher script
cat > ${BUILD_DIR}/usr/bin/${PACKAGE_NAME} <<EOF
#!/bin/bash
export PYTHONPATH="/usr/share/${PACKAGE_NAME}/lib:\$PYTHONPATH"
cd /usr/share/${PACKAGE_NAME}
exec python3 app.py "\$@"
EOF
chmod +x ${BUILD_DIR}/usr/bin/${PACKAGE_NAME}

# Copy icon
cp logo.png ${BUILD_DIR}/usr/share/icons/hicolor/48x48/apps/${PACKAGE_NAME}.png

# Create desktop file
cat > ${BUILD_DIR}/usr/share/applications/${PACKAGE_NAME}.desktop <<EOF
[Desktop Entry]
Name=SyMo
Comment=${DESCRIPTION}
Exec=${PACKAGE_NAME}
Icon=${PACKAGE_NAME}
Terminal=false
Type=Application
Categories=Utility;System;Monitor;
StartupNotify=true
Keywords=monitor;system;tray;cpu;memory;disk;network;
X-GNOME-UsesNotifications=true
EOF

# Create control file with minimal dependencies
cat > ${BUILD_DIR}/DEBIAN/control <<EOF
Package: ${PACKAGE_NAME}
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: all
Depends: ${DEPENDS}
Maintainer: ${MAINTAINER}
Description: ${DESCRIPTION}
 Self-contained system monitor with bundled Python dependencies.
 Features:
  - Real-time CPU, RAM, disk, and network monitoring
  - System tray integration with customizable display
  - Power management (shutdown, reboot, lock)
  - Multi-language support (RU, EN, CN, DE)
  - Telegram and Discord notifications
  - Keyboard and mouse activity tracking
 .
 This optimized build includes all Python dependencies bundled
 to minimize system requirements and ensure compatibility.
EOF

# Create postinst script
cat > ${BUILD_DIR}/DEBIAN/postinst <<EOF
#!/bin/bash
# Update icon cache and desktop database
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor/ 2>/dev/null || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications/ 2>/dev/null || true
fi

# Set proper permissions
chmod 755 /usr/bin/${PACKAGE_NAME}
chmod -R 755 /usr/share/${PACKAGE_NAME}

echo "SyMo installed successfully. Run 'SyMo' or find it in Applications menu."
EOF
chmod +x ${BUILD_DIR}/DEBIAN/postinst

# Create prerm script
cat > ${BUILD_DIR}/DEBIAN/prerm <<EOF
#!/bin/bash
# Stop application before removal
pkill -f "/usr/share/${PACKAGE_NAME}/app.py" 2>/dev/null || true
sleep 1
EOF
chmod +x ${BUILD_DIR}/DEBIAN/prerm

# Create postrm script for cleanup
cat > ${BUILD_DIR}/DEBIAN/postrm <<EOF
#!/bin/bash
# Clean up configuration files on purge
if [ "\$1" = "purge" ]; then
    rm -f "\$HOME/.system_monitor_settings.json" 2>/dev/null || true
    rm -f "\$HOME/.system_monitor_telegram.json" 2>/dev/null || true
    rm -f "\$HOME/.system_monitor_discord.json" 2>/dev/null || true
    rm -f "\$HOME/system_monitor_log.txt" 2>/dev/null || true
fi

# Update caches
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor/ 2>/dev/null || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications/ 2>/dev/null || true
fi
EOF
chmod +x ${BUILD_DIR}/DEBIAN/postrm

# Build the package
echo "Building optimized package..."
fakeroot dpkg-deb --build ${BUILD_DIR} ${PACKAGE_NAME}_${VERSION}_optimized.deb

# Check package integrity
if command -v lintian >/dev/null 2>&1; then
    echo "Running package validation..."
    lintian ${PACKAGE_NAME}_${VERSION}_optimized.deb 2>/dev/null || true
fi

# Show package information
PACKAGE_SIZE=$(du -h ${PACKAGE_NAME}_${VERSION}_optimized.deb | cut -f1)
echo "✅ Optimized package built: ${PACKAGE_NAME}_${VERSION}_optimized.deb"
echo "📦 Package size: ${PACKAGE_SIZE}"
echo ""
echo "Installation commands:"
echo "  sudo dpkg -i ${PACKAGE_NAME}_${VERSION}_optimized.deb"
echo "  sudo apt-get install -f  # Fix any dependency issues"
echo ""
echo "Uninstall commands:"
echo "  sudo apt remove symo        # Remove package"
echo "  sudo apt purge symo         # Remove package + config files"