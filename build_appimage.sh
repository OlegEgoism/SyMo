#!/bin/bash

# AppImage Build Script for SyMo
# Creates a portable Linux application that runs anywhere without installation

PACKAGE_NAME="SyMo"
VERSION="1.0.1"

echo "🖼️ Building SyMo as AppImage..."
echo "This creates a portable application that runs on any Linux distribution"

# Check if appimage-builder is installed
if ! command -v appimage-builder &> /dev/null; then
    echo "Installing appimage-builder..."
    sudo apt update
    sudo apt install -y python3-pip python3-setuptools patchelf desktop-file-utils libgdk-pixbuf2.0-dev fakeroot strace
    
    # Install appimage-builder
    sudo -H pip3 install appimage-builder
fi

# Clean previous builds
rm -rf AppDir *.AppImage

echo "🔧 Building AppImage..."

# Create desktop file for the AppImage
cat > symo.desktop <<EOF
[Desktop Entry]
Name=SyMo
Comment=System Monitor with Tray Icon  
Exec=symo
Icon=logo
Terminal=false
Type=Application
Categories=System;Monitor;Utility;
StartupNotify=true
Keywords=monitor;system;tray;cpu;memory;disk;network;performance;
X-GNOME-UsesNotifications=true
X-AppImage-Version=${VERSION}
EOF

# Build the AppImage
appimage-builder --recipe AppImageBuilder.yml

if [ -f "SyMo-${VERSION}-x86_64.AppImage" ]; then
    # Make executable
    chmod +x "SyMo-${VERSION}-x86_64.AppImage"
    
    # Get file size
    APPIMAGE_SIZE=$(du -h "SyMo-${VERSION}-x86_64.AppImage" | cut -f1)
    
    echo "✅ AppImage build successful!"
    echo "📦 AppImage file: SyMo-${VERSION}-x86_64.AppImage"
    echo "💾 File size: ${APPIMAGE_SIZE}"
    echo ""
    echo "🎯 AppImage Benefits:"
    echo "  - Runs on ANY Linux distribution (Ubuntu, Fedora, Arch, etc.)"
    echo "  - No installation required - just download and run"
    echo "  - Automatic desktop integration"
    echo "  - Self-contained with all dependencies"
    echo "  - Can be distributed via GitHub releases"
    echo ""
    echo "🚀 Test the AppImage:"
    echo "  ./SyMo-${VERSION}-x86_64.AppImage"
    echo ""
    echo "📋 Distribution options:"
    echo "  # Upload to GitHub releases"
    echo "  # Users download and run directly:"
    echo "  wget https://github.com/user/repo/releases/download/v${VERSION}/SyMo-${VERSION}-x86_64.AppImage"
    echo "  chmod +x SyMo-${VERSION}-x86_64.AppImage"
    echo "  ./SyMo-${VERSION}-x86_64.AppImage"
    echo ""
    echo "🔧 Desktop integration:"
    echo "  # AppImage automatically registers with desktop on first run"
    echo "  # Can be found in applications menu after launch"
    
    # Clean up
    rm -f symo.desktop
else
    echo "❌ AppImage build failed!"
    echo "Check the build log above for errors."
    exit 1
fi