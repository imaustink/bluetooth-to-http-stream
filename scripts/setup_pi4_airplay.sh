#!/bin/bash
# Raspberry Pi 4 Setup Script for Bluetooth to AirPlay Streaming
# Run with: chmod +x setup_pi4_airplay.sh && ./setup_pi4_airplay.sh

set -e  # Exit on error

echo "🍓 Raspberry Pi 4 - Bluetooth to AirPlay Setup"
echo "=============================================="

# Check if running on Raspberry Pi
if ! grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null; then
    echo "⚠️  Warning: This script is designed for Raspberry Pi 4"
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Update system
echo "📦 Updating system packages..."
sudo apt update
sudo apt upgrade -y

# Install system dependencies
echo "🔧 Installing system dependencies..."
sudo apt install -y \
    python3-pip \
    python3-venv \
    python3-dev \
    bluetooth \
    bluez \
    bluez-tools \
    pulseaudio \
    pulseaudio-module-bluetooth \
    gstreamer1.0-tools \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly \
    gstreamer1.0-alsa \
    alsa-utils \
    libbluetooth-dev \
    libglib2.0-dev \
    libgirepository1.0-dev \
    libcairo2-dev \
    pkg-config \
    avahi-daemon \
    avahi-utils

# Install BlueALSA for better Bluetooth audio support
echo "🎵 Installing BlueALSA..."
if ! command -v bluealsa &> /dev/null; then
    # Build BlueALSA from source if not available in repos
    sudo apt install -y \
        build-essential \
        autotools-dev \
        libtool \
        autoconf \
        automake \
        libdbus-1-dev \
        libglib2.0-dev \
        libsbc1 \
        libsbc-dev \
        libasound2-dev
    
    cd /tmp
    git clone https://github.com/Arkq/bluez-alsa.git
    cd bluez-alsa
    autoreconf --install
    ./configure --enable-systemd --with-alsaplugindir=/usr/lib/aarch64-linux-gnu/alsa-lib
    make -j$(nproc)
    sudo make install
    sudo ldconfig
    
    # Enable BlueALSA service
    sudo systemctl enable bluealsa
    sudo systemctl start bluealsa
else
    echo "✅ BlueALSA already installed"
fi

# Create Python virtual environment
echo "🐍 Setting up Python environment..."
cd "$(dirname "$0")"
python3 -m venv venv
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install Python dependencies
echo "📦 Installing Python dependencies..."
pip install -r requirements.txt

# Setup Bluetooth permissions
echo "🔐 Setting up Bluetooth permissions..."
sudo usermod -a -G bluetooth $USER
sudo usermod -a -G audio $USER

# Configure PulseAudio for Bluetooth
echo "🎧 Configuring PulseAudio..."
mkdir -p ~/.config/pulse
cat > ~/.config/pulse/default.pa << 'EOF'
#!/usr/bin/pulseaudio -nF

# Load system default configuration
.include /etc/pulse/default.pa

# Automatically switch to newly-connected devices
load-module module-switch-on-connect

# Enable Bluetooth discovery
load-module module-bluetooth-discover

# Set default sample rate to match CD quality
default-sample-rate = 44100
alternate-sample-rate = 48000
EOF

# Create systemd service for auto-start
echo "⚙️  Creating systemd service..."
sudo tee /etc/systemd/system/airplay-streamer.service > /dev/null << EOF
[Unit]
Description=Bluetooth to AirPlay Audio Streamer
After=network.target bluetooth.service pulseaudio.service
Wants=bluetooth.service

[Service]
Type=simple
User=$USER
Group=audio
WorkingDirectory=$(pwd)
Environment=HOME=/home/$USER
Environment=XDG_RUNTIME_DIR=/run/user/$(id -u $USER)
ExecStart=$(pwd)/venv/bin/python AIRPLAY_STREAM.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable the service (but don't start it yet)
sudo systemctl daemon-reload
sudo systemctl enable airplay-streamer

# Create convenient start/stop scripts
cat > start_streamer.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
python AIRPLAY_STREAM.py
EOF

cat > stop_streamer.sh << 'EOF'
#!/bin/bash
sudo systemctl stop airplay-streamer
pkill -f AIRPLAY_STREAM.py
EOF

chmod +x start_streamer.sh stop_streamer.sh

# Test Bluetooth setup
echo "🧪 Testing Bluetooth setup..."
if systemctl is-active --quiet bluetooth; then
    echo "✅ Bluetooth service is running"
else
    echo "❌ Bluetooth service not running"
    sudo systemctl start bluetooth
fi

if command -v bluealsa &> /dev/null; then
    echo "✅ BlueALSA is installed"
else
    echo "⚠️  BlueALSA installation may have issues"
fi

echo ""
echo "🎉 Setup Complete!"
echo "=================="
echo ""
echo "Next steps:"
echo "1. Reboot your Raspberry Pi: sudo reboot"
echo "2. Pair your AT-TT turntable via Bluetooth"
echo "3. Run the streamer: ./start_streamer.sh"
echo "   Or install dependencies only: python AIRPLAY_STREAM.py --install-deps"
echo ""
echo "Service management:"
echo "• Start service: sudo systemctl start airplay-streamer"
echo "• Stop service: sudo systemctl stop airplay-streamer"
echo "• View logs: sudo journalctl -u airplay-streamer -f"
echo ""
echo "Troubleshooting:"
echo "• Check Bluetooth: bluetoothctl devices"
echo "• Test audio: aplay /usr/share/sounds/alsa/Front_Left.wav"
echo "• List audio devices: arecord -l"
echo ""
echo "🎵 Remember: Your AT-TT must be connected via Bluetooth before streaming!"