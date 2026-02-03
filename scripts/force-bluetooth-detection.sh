#!/bin/bash

# Force PulseAudio to detect Bluetooth audio device
echo "🔍 Forcing PulseAudio Bluetooth detection..."

ATT_MAC="F4:04:4C:1A:E5:B9"

echo "1. Current Bluetooth device info:"
bluetoothctl info $ATT_MAC

echo ""
echo "2. Current PulseAudio cards:"
sudo -u pi pactl list cards short

echo ""
echo "3. Reloading Bluetooth modules..."
sudo -u pi pactl unload-module module-bluetooth-discover
sudo -u pi pactl unload-module module-bluetooth-policy
sleep 2
sudo -u pi pactl load-module module-bluetooth-policy
sudo -u pi pactl load-module module-bluetooth-discover

echo ""
echo "4. PulseAudio cards after reload:"
sudo -u pi pactl list cards short

echo ""
echo "5. Checking for A2DP services on AT-TT:"
sdptool browse $ATT_MAC | grep -A 5 "Audio"

echo ""
echo "6. Manually creating loopback from Bluetooth source:"
# Try to create a manual audio path
BLUETOOTH_SOURCE=$(sudo -u pi pactl list sources short | grep bluez | head -1 | cut -f1)
if [ ! -z "$BLUETOOTH_SOURCE" ]; then
    echo "Found Bluetooth source: $BLUETOOTH_SOURCE"
    sudo -u pi pactl load-module module-loopback source=$BLUETOOTH_SOURCE
else
    echo "No Bluetooth source found"
fi

echo ""
echo "✅ Diagnostic complete"