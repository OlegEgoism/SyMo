#!/bin/bash

# Flatpak Build Script for SyMo
# Creates a modern sandboxed application with excellent desktop integration

PACKAGE_NAME="SyMo"
VERSION="1.0.1"
APP_ID="com.symo.SystemMonitor"

echo "📦 Building SyMo as Flatpak..."
echo "This creates a modern sandboxed application with excellent desktop integration"

# Check if Flatpak development tools are installed
if ! command -v flatpak-builder &> /dev/null; then
    echo "Installing Flatpak development tools..."
    sudo apt update
    sudo apt install -y flatpak flatpak-builder
    
    # Add Flathub repository if not already added
    flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
    
    # Install GNOME SDK and Platform
    flatpak install -y flathub org.gnome.Platform//45 org.gnome.Sdk//45
fi

# Clean previous builds
rm -rf .flatpak-builder build-dir ${APP_ID}.flatpak

echo "🔧 Building Flatpak application..."

# Build the Flatpak
flatpak-builder --repo=repo --force-clean build-dir ${APP_ID}.yml

if [ $? -eq 0 ]; then
    echo "📦 Creating Flatpak bundle..."
    
    # Create a single-file bundle for easy distribution
    flatpak build-bundle repo ${APP_ID}.flatpak ${APP_ID}
    
    if [ -f "${APP_ID}.flatpak" ]; then
        # Get file size
        FLATPAK_SIZE=$(du -h "${APP_ID}.flatpak" | cut -f1)
        
        echo "✅ Flatpak build successful!"
        echo "📦 Flatpak bundle: ${APP_ID}.flatpak"
        echo "💾 Bundle size: ${FLATPAK_SIZE}"
        echo ""
        echo "🎯 Flatpak Benefits:"
        echo "  - Modern Linux packaging standard"
        echo "  - Excellent desktop integration with themes"
        echo "  - Automatic updates via repositories"
        echo "  - Sandboxed security model"
        echo "  - Works on ALL Linux distributions"
        echo "  - Shared runtime reduces total disk usage"
        echo ""
        echo "🚀 Test the Flatpak locally:"
        echo "  flatpak install --user ${APP_ID}.flatpak"
        echo "  flatpak run ${APP_ID}"
        echo ""
        echo "📋 Distribution options:"
        echo ""
        echo "1. Single Bundle (Easy Distribution):"
        echo "   # Users install the bundle directly:"
        echo "   flatpak install --user ${APP_ID}.flatpak"
        echo ""
        echo "2. Repository Distribution (Automatic Updates):"
        echo "   # Upload 'repo' directory to web server"
        echo "   # Users add your repository:"
        echo "   flatpak remote-add --user myrepo https://your-server.com/repo"
        echo "   flatpak install --user myrepo ${APP_ID}"
        echo ""
        echo "3. Flathub Submission:"
        echo "   # Submit manifest to https://github.com/flathub/flathub"
        echo "   # Users install from Flathub:"
        echo "   flatpak install flathub ${APP_ID}"
        echo ""
        echo "🧹 Cleanup:"
        echo "  flatpak uninstall --user ${APP_ID}"
    else
        echo "❌ Failed to create Flatpak bundle!"
        exit 1
    fi
else
    echo "❌ Flatpak build failed!"
    echo "Check the build log above for errors."
    exit 1
fi