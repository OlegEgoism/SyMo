#!/bin/bash

# PyInstaller Single Executable Build Script for SyMo
# Creates a single-file executable with all dependencies bundled

PACKAGE_NAME="SyMo"
VERSION="1.0.1"

echo "📦 Building SyMo with PyInstaller (Single Executable)..."
echo "This creates a single-file executable with all dependencies included"

# Check if PyInstaller is installed
if ! command -v pyinstaller &> /dev/null; then
    echo "Installing PyInstaller..."
    pip install pyinstaller
fi

# Clean previous builds
rm -rf build/ dist/ *.spec

echo "🔧 Creating optimized single executable..."

# Create PyInstaller spec file for advanced configuration
cat > symo.spec <<EOF
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('logo.png', '.'),
        ('language.py', '.'),
    ],
    hiddenimports=[
        'gi.repository.AppIndicator3',
        'gi.repository.Gtk',
        'gi.repository.GLib',
        'gi.repository.GObject',
        'gi.repository.Gio',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'scipy',
        'pandas',
        'PIL',
        'unittest',
        'pydoc',
        'xml',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Remove unnecessary modules to reduce size
a.binaries = [x for x in a.binaries if not x[0].startswith('libQt')]
a.binaries = [x for x in a.binaries if not x[0].startswith('libicu')]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='${PACKAGE_NAME}-portable',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='logo.png',
)
EOF

# Build with PyInstaller using the spec file
echo "🚀 Building executable..."
pyinstaller symo.spec

if [ -f "dist/${PACKAGE_NAME}-portable" ]; then
    # Get file size
    PORTABLE_SIZE=$(du -h "dist/${PACKAGE_NAME}-portable" | cut -f1)
    
    # Move to root directory
    cp "dist/${PACKAGE_NAME}-portable" ./
    
    echo "✅ Build successful!"
    echo "📦 Portable executable: ${PACKAGE_NAME}-portable"
    echo "💾 File size: ${PORTABLE_SIZE}"
    echo ""
    echo "🎯 Features:"
    echo "  - Single executable file (no installation needed)"
    echo "  - All dependencies bundled"
    echo "  - Runs on any Linux system with GTK3"
    echo "  - No Python interpreter required"
    echo ""
    echo "🚀 Run portable version:"
    echo "  ./${PACKAGE_NAME}-portable"
    echo ""
    echo "📋 Distribution:"
    echo "  # Just distribute the single file!"
    echo "  scp ${PACKAGE_NAME}-portable user@remote-host:/usr/local/bin/symo"
    
    # Clean up build files
    rm -rf build/ dist/ symo.spec
else
    echo "❌ Build failed!"
    exit 1
fi