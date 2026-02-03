#!/bin/bash

# Configure Pi 4 as proper A2DP Audio Sink
echo "🎵 Configuring Pi 4 as A2DP Audio Sink..."

# Install bluez-alsa if not present (better A2DP support)
sudo apt update
sudo apt install -y bluez-alsa-utils alsa-utils

# Stop current bluetooth
sudo systemctl stop bluetooth
sleep 2

# Configure bluetooth for A2DP sink mode
sudo bash -c 'cat > /etc/bluetooth/main.conf << EOF
[General]
Name = Pi4-Speaker
Class = 0x20041C
DiscoverableTimeout = 0
PairableTimeout = 0
AutoConnectTimeout = 60
FastConnectable = true
Privacy = off

[Policy]
AutoEnable = true
ReconnectAttempts = 7
ReconnectIntervals = 1,2,4,8,16,32,64

[A2DP]
SBCQuality = XQ
EOF'

# Start bluetooth
sudo systemctl start bluetooth
sleep 3

# Kill all pulseaudio
sudo pkill -f pulseaudio
sleep 2

# Create A2DP sink specific PulseAudio config
mkdir -p ~/.config/pulse
cat > ~/.config/pulse/default.pa << 'EOF'
#!/usr/bin/pulseaudio -nF

# Load core modules
load-module module-device-restore
load-module module-stream-restore
load-module module-card-restore

# CRITICAL: Load bluetooth modules for A2DP SINK
load-module module-bluetooth-policy auto_switch=2
load-module module-bluetooth-discover autodetect_mtu=yes a2dp_config="ldac_eqmid=hq ldac_fmt=f32"

# ALSA support  
load-module module-alsa-card device_id=0 name=platform-soc_sound
load-module module-udev-detect

# Core audio modules
load-module module-native-protocol-unix auth-anonymous=1
load-module module-default-device-restore
load-module module-rescue-streams
load-module module-always-sink
load-module module-intended-roles
load-module module-suspend-on-idle

# Allow network connections
load-module module-native-protocol-tcp auth-ip-acl=127.0.0.1;192.168.0.0/16

set-default-sink alsa_output.platform-soc_sound.analog-stereo
EOF

# Start user pulseaudio
pulseaudio --start --log-target=stderr -v &
sleep 5

# Set up bluetooth discoverable mode
bluetoothctl power on
bluetoothctl agent NoInputNoOutput
bluetoothctl default-agent
bluetoothctl discoverable on
bluetoothctl pairable on

# Set device class for audio sink
sudo hciconfig hci0 class 0x20041C

echo ""
echo "✅ A2DP Sink Configuration Complete!"
echo ""
echo "🎵 Pi is now configured as an Audio Sink"
echo "📱 AT-TT should be able to connect and stream audio"
echo ""
echo "Test commands:"
echo "  pactl list cards"
echo "  pactl list sinks"
echo "  bluetoothctl devices"
echo ""
echo "🚀 Now try connecting your AT-TT turntable!"