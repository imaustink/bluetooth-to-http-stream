#!/bin/bash

# Fix PulseAudio conflicts for Bluetooth Audio
echo "🔧 Fixing PulseAudio conflicts..."

# Stop ALL PulseAudio processes
echo "Stopping all PulseAudio processes..."
sudo pkill -f pulseaudio
sleep 3

# Disable system-wide PulseAudio service permanently
echo "Disabling system-wide PulseAudio..."
sudo systemctl stop pulseaudio 2>/dev/null || true
sudo systemctl disable pulseaudio 2>/dev/null || true
sudo systemctl mask pulseaudio 2>/dev/null || true

# Remove the problematic system service file we created
sudo rm -f /etc/systemd/system/pulseaudio.service
sudo systemctl daemon-reload

# Make sure user PulseAudio config exists
mkdir -p ~/.config/pulse

# Create proper user config if it doesn't exist
if [ ! -f ~/.config/pulse/default.pa ]; then
    echo "Creating user PulseAudio config..."
    cat > ~/.config/pulse/default.pa << 'EOF'
#!/usr/bin/pulseaudio -nF

# Load device drivers
load-module module-device-restore
load-module module-stream-restore
load-module module-card-restore

# Bluetooth support - CRITICAL for A2DP
load-module module-bluetooth-policy auto_switch=2
load-module module-bluetooth-discover autodetect_mtu=yes

# ALSA support
load-module module-alsa-card device_id=0 name=platform-soc_sound
load-module module-udev-detect

# Native protocol
load-module module-native-protocol-unix auth-anonymous=1

# Default modules
load-module module-default-device-restore
load-module module-rescue-streams
load-module module-always-sink
load-module module-intended-roles
load-module module-suspend-on-idle

# Network support
load-module module-native-protocol-tcp auth-ip-acl=127.0.0.1;192.168.0.0/16

set-default-sink alsa_output.platform-soc_sound.analog-stereo
EOF
fi

# Start ONLY user PulseAudio
echo "Starting user PulseAudio..."
pulseaudio --start --log-target=stderr -v &

# Wait for startup
sleep 5

# Verify only one PulseAudio is running
echo ""
echo "PulseAudio processes after cleanup:"
ps aux | grep pulseaudio | grep -v grep

echo ""
echo "Testing PulseAudio:"
pactl info

echo ""
echo "Bluetooth modules loaded:"
pactl list modules | grep bluetooth

echo ""
echo "✅ PulseAudio cleanup complete"
echo "💡 Now try your Bluetooth speaker script again"