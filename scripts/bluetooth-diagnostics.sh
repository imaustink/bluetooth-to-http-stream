#!/bin/bash

# Bluetooth Audio Diagnostics for Pi 4
echo "🔍 Bluetooth Audio Diagnostics"
echo "=============================="

echo ""
echo "1. PulseAudio Module Status:"
sudo -u pi pactl list modules | grep -A 3 -B 1 bluetooth

echo ""
echo "2. Bluetooth Service Status:"
systemctl status bluetooth --no-pager

echo ""
echo "3. Available Bluetooth Devices:"
bluetoothctl devices

echo ""
echo "4. Bluetooth Adapter Info:"
hciconfig hci0

echo ""
echo "5. PulseAudio Cards:"
sudo -u pi pactl list cards short

echo ""
echo "6. Bluetooth-related Kernel Modules:"
lsmod | grep bluetooth

echo ""
echo "7. BlueZ Configuration:"
cat /etc/bluetooth/main.conf | grep -v "^#" | grep -v "^$"

echo ""
echo "8. PulseAudio Process Info:"
ps aux | grep pulseaudio

echo ""
echo "9. Audio Groups for pi user:"
groups pi

echo ""
echo "10. Detailed Bluetooth Device Info (if connected):"
bluetoothctl info F4:04:4C:1A:E5:B9 2>/dev/null || echo "AT-TT not currently connected"