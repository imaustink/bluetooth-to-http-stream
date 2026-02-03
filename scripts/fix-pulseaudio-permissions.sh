#!/bin/bash

# Fix PulseAudio permissions after A2DP setup
echo "🔧 Fixing PulseAudio permissions..."

# Kill any existing pulseaudio processes
sudo pkill -f pulseaudio
sleep 3

# Start PulseAudio as pi user (not root)
echo "Starting PulseAudio as pi user..."
pulseaudio --start --log-target=stderr -v

# Wait for startup
sleep 3

# Test PulseAudio
echo "Testing PulseAudio connection:"
pactl info

echo ""
echo "Current cards:"
pactl list cards short

echo ""
echo "Current sinks:"  
pactl list sinks short

echo ""
echo "✅ PulseAudio fixed - ready for AT-TT connection!"