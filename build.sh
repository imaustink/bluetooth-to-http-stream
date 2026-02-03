#!/bin/bash
# Build script for Rust turntable server

set -e

echo "🦀 Building Rust PipeWire Turntable Server..."

# Check if we're on macOS or Linux
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "📦 Building for macOS (for testing/development)..."
    cargo build --release
    echo "✅ Binary: target/release/pipewire-turntable-server"
else
    echo "📦 Building for Linux..."
    cargo build --release
    echo "✅ Binary: target/release/pipewire-turntable-server"
fi

echo ""
echo "🚀 To run:"
echo "   ./target/release/pipewire-turntable-server"
echo ""
echo "📦 To cross-compile for Raspberry Pi from macOS:"
echo "   rustup target add aarch64-unknown-linux-gnu"
echo "   cargo build --release --target aarch64-unknown-linux-gnu"
