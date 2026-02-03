#!/bin/bash
echo "🔧 Comprehensive BlueALSA Reset"
echo "=============================="

# Make sure we're playing music
echo "💿 IMPORTANT: Make sure your turntable is playing music!"
echo "   BlueALSA won't detect audio sources that aren't actively sending audio."
echo ""
read -p "🎵 Is your turntable playing music right now? (y/n): " -r
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ Please start playing music on your turntable first, then run this script again."
    exit 1
fi

echo ""
echo "🛑 Stopping all audio services..."
sudo systemctl stop bluealsa
sudo pkill -f bluealsa
sudo pkill -f pulseaudio
pulseaudio --kill

echo "🔌 Completely disconnecting turntable..."
bluetoothctl disconnect F4:04:4C:1A:E5:B9
sleep 2

echo "🔄 Restarting Bluetooth service..."
sudo systemctl restart bluetooth
sleep 3

echo "▶️  Starting BlueALSA with explicit A2DP support..."
sudo systemctl start bluealsa
sleep 2

echo "📡 Reconnecting turntable..."
bluetoothctl connect F4:04:4C:1A:E5:B9
sleep 3

echo "⏳ Waiting for BlueALSA to detect the audio stream..."
echo "   (This can take 10-15 seconds with active audio)"
sleep 10

echo "🔍 Checking BlueALSA devices..."
bluealsa-aplay -L

echo ""
echo "🧪 Testing if we can capture audio..."
timeout 3s arecord -D "bluealsa:SRV=org.bluealsa,DEV=F4:04:4C:1A:E5:B9,PROFILE=a2dp" -f cd -t wav /tmp/test.wav 2>&1 | head -3

echo ""
echo "✅ Reset complete! If BlueALSA still doesn't see the device:"
echo "   1. Make sure turntable is actively playing music"
echo "   2. Try: sudo systemctl restart bluealsa"
echo "   3. The device might need to be removed and re-paired"