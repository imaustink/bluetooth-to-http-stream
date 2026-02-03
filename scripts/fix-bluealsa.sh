#!/bin/bash
"""
Quick BlueALSA Fix Script
Run this if the diagnostic shows issues
"""

echo "🔧 BlueALSA Quick Fix Script"
echo "================================"

echo "🛑 Stopping audio services..."
sudo systemctl stop bluealsa
sudo pkill -f bluealsa
sudo pkill -f pulseaudio

echo "🔄 Restarting Bluetooth..."
sudo systemctl restart bluetooth
sleep 2

echo "▶️  Starting BlueALSA..."
sudo systemctl start bluealsa
sleep 2

echo "📡 Checking BlueALSA status..."
systemctl is-active bluealsa

echo "🎧 Reconnecting turntable..."
bluetoothctl disconnect F4:04:4C:1A:E5:B9
sleep 3
bluetoothctl connect F4:04:4C:1A:E5:B9
sleep 5

echo "🔍 Checking connection..."
bluetoothctl info F4:04:4C:1A:E5:B9 | grep Connected

echo "📱 Checking BlueALSA devices..."
bluealsa-aplay -L

echo "✅ Fix attempt complete!"
echo "Now try running your Python script again"