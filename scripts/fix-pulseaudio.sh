#!/bin/bash

# Fix PulseAudio for Bluetooth Speaker on Pi 4
echo "🔧 Fixing PulseAudio configuration..."

# Stop any existing PulseAudio processes
sudo pkill -f pulseaudio
sleep 2

# Remove system service (it's conflicting)
sudo systemctl stop pulseaudio 2>/dev/null || true
sudo systemctl disable pulseaudio 2>/dev/null || true

# Configure PulseAudio for user session instead of system-wide
mkdir -p ~/.config/pulse

# Create user-specific PulseAudio config
cat > ~/.config/pulse/default.pa << 'EOF'
#!/usr/bin/pulseaudio -nF

# Load device drivers
load-module module-device-restore
load-module module-stream-restore
load-module module-card-restore

# Bluetooth support
load-module module-bluetooth-policy auto_switch=2
load-module module-bluetooth-discover a2dp_config="sbc_freq=48000 sbc_cmode=joint_stereo"

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

# Allow network connections
load-module module-native-protocol-tcp auth-ip-acl=127.0.0.1;192.168.0.0/16

set-default-sink alsa_output.platform-soc_sound.analog-stereo
EOF

# Start user PulseAudio
pulseaudio --start --log-target=stderr -v

echo "✅ PulseAudio configured for user session"
echo "🎵 Test with: pactl info"