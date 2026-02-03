#!/bin/bash
echo "🔧 Fixing 'Device or resource busy' issue"
echo "========================================"

echo "🛑 Stopping PulseAudio (often grabs BlueALSA devices)..."
pulseaudio --kill
sudo pkill -f pulseaudio

echo "🔌 Disconnecting turntable to reset the connection..."
bluetoothctl disconnect F4:04:4C:1A:E5:B9
sleep 3

echo "🛑 Stopping BlueALSA to clear any busy state..."
sudo systemctl stop bluealsa
sudo pkill -f bluealsa
sleep 2

echo "▶️  Starting BlueALSA fresh..."
sudo systemctl start bluealsa
sleep 3

echo "📡 Reconnecting turntable..."
bluetoothctl connect F4:04:4C:1A:E5:B9
sleep 5

echo "🔍 Checking if device is still busy..."
timeout 3s arecord -D "bluealsa:SRV=org.bluealsa,DEV=F4:04:4C:1A:E5:B9,PROFILE=a2dp" -f cd -t wav /tmp/test.wav 2>&1 | head -5

echo "✅ Fix complete! Try your script now."
echo "💡 If still busy, make sure the turntable is actively playing music!"