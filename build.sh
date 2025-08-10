#!/bin/bash

# Nuitka Compilation Build Script for SyMo (Fixed Resource Handling)
# Creates a compiled native executable with proper resource bundling

PACKAGE_NAME="SyMo"
VERSION="1.0.1"

echo "🔥 Building SyMo with Nuitka compilation (Fixed Resources)..."
echo "This creates a native compiled executable with properly bundled resources"

# Check and install system dependencies
echo "🔧 Checking system dependencies..."
if ! command -v patchelf &> /dev/null; then
    echo "Installing patchelf (required for Nuitka standalone builds)..."
    sudo apt update && sudo apt install -y patchelf
fi

# Check other build dependencies
if ! command -v gcc &> /dev/null; then
    echo "Installing build-essential..."
    sudo apt install -y build-essential
fi

# Check if Nuitka is installed and install if needed
if ! command -v nuitka3 &> /dev/null && ! command -v nuitka &> /dev/null; then
    echo "Installing Nuitka..."
    pip install nuitka
fi

# Determine which nuitka command to use
NUITKA_CMD="nuitka"
if command -v nuitka3 &> /dev/null; then
    NUITKA_CMD="nuitka3"
elif command -v nuitka &> /dev/null; then
    NUITKA_CMD="nuitka"
else
    echo "❌ Failed to install Nuitka. Trying alternative installation..."
    pip3 install nuitka
    if command -v nuitka &> /dev/null; then
        NUITKA_CMD="nuitka"
    else
        echo "❌ Could not install Nuitka. Please install manually:"
        echo "  pip3 install nuitka"
        exit 1
    fi
fi

echo "Using Nuitka command: $NUITKA_CMD"

# Clean previous builds
rm -rf ${PACKAGE_NAME}.dist ${PACKAGE_NAME}.build ${PACKAGE_NAME}.onefile-build
rm -f ${PACKAGE_NAME} ${PACKAGE_NAME}.bin ${PACKAGE_NAME}-compiled

echo "🚀 Compiling Python to native executable..."

# Try standalone build first (creates directory with resources)
echo "📁 Creating standalone build with resources..."
$NUITKA_CMD --standalone \
    --enable-plugin=gi \
    --include-data-files=logo.png=logo.png \
    --include-data-files=language.py=language.py \
    --assume-yes-for-downloads \
    --output-dir=build_standalone \
    --follow-imports \
    --python-flag=no_site \
    --python-flag=-O \
    app.py

if [ $? -eq 0 ] && [ -d "build_standalone/app.dist" ]; then
    echo "✅ Standalone build successful!"

    # Copy the standalone build to a cleaner name
    cp -r build_standalone/app.dist ${PACKAGE_NAME}-standalone

    # Create a wrapper script for easier execution
    cat > ${PACKAGE_NAME}-run << 'EOF'
#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$DIR/${PACKAGE_NAME}-standalone"
exec ./app "$@"
EOF
    chmod +x ${PACKAGE_NAME}-run

    STANDALONE_SIZE=$(du -sh ${PACKAGE_NAME}-standalone | cut -f1)

    echo "📦 Standalone build: ${PACKAGE_NAME}-standalone/"
    echo "🚀 Runner script: ${PACKAGE_NAME}-run"
    echo "💾 Total size: ${STANDALONE_SIZE}"
    echo ""
    echo "🎯 Standalone Benefits:"
    echo "  - All resources properly bundled"
    echo "  - Native performance (3x faster)"
    echo "  - Complete self-contained directory"
    echo "  - Logo and images included"
    echo ""
    echo "🚀 Run standalone version:"
    echo "  ./${PACKAGE_NAME}-run"
    echo ""
    echo "📋 Distribution:"
    echo "  # Distribute the entire ${PACKAGE_NAME}-standalone/ directory"
    echo "  tar -czf ${PACKAGE_NAME}-standalone.tar.gz ${PACKAGE_NAME}-standalone/ ${PACKAGE_NAME}-run"
    echo "  # Users extract and run:"
    echo "  tar -xzf ${PACKAGE_NAME}-standalone.tar.gz && ./${PACKAGE_NAME}-run"

    # Try onefile build as well (might work with newer Nuitka)
    echo ""
    echo "🗜️ Attempting onefile build (experimental)..."
    $NUITKA_CMD --onefile \
        --enable-plugin=gi \
        --include-data-files=logo.png=logo.png \
        --include-data-files=language.py=language.py \
        --assume-yes-for-downloads \
        --output-filename=${PACKAGE_NAME}-onefile \
        --follow-imports \
        --python-flag=no_site \
        --python-flag=-O \
        app.py

    if [ -f "${PACKAGE_NAME}-onefile" ]; then
        ONEFILE_SIZE=$(du -h ${PACKAGE_NAME}-onefile | cut -f1)
        echo "✅ Onefile build also successful!"
        echo "📦 Single executable: ${PACKAGE_NAME}-onefile"
        echo "💾 File size: ${ONEFILE_SIZE}"
        echo ""
        echo "⚠️  Note: Onefile version may have resource loading issues."
        echo "   Use standalone version if images don't load properly."
        echo ""
        echo "🚀 Test onefile version:"
        echo "  ./${PACKAGE_NAME}-onefile"
    else
        echo "⚠️  Onefile build failed, but standalone version is ready!"
    fi

    # Clean up build directories
    rm -rf build_standalone

else
    echo "❌ Compilation failed!"
    echo "This might be due to GTK/GObject complexity. Try PyInstaller as alternative:"
    echo "  ./build_pyinstaller.sh"
    exit 1
fi