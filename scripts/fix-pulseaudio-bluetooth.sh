#!/bin/bash

echo "=== Fixing PulseAudio Bluetooth Module Configuration ==="

# Stop PulseAudio first
echo "Stopping PulseAudio..."
pulseaudio --kill 2>/dev/null || true
sleep 2

# Create a clean PulseAudio configuration for Bluetooth
echo "Creating PulseAudio configuration for Bluetooth..."

# Backup original config if it exists
if [ -f ~/.config/pulse/default.pa ]; then
    cp ~/.config/pulse/default.pa ~/.config/pulse/default.pa.backup.$(date +%s)
fi

# Create the config directory
mkdir -p ~/.config/pulse

# Create a clean default.pa configuration
cat > ~/.config/pulse/default.pa << 'EOF'
#!/usr/bin/pulseaudio -nF
#
# This file is part of PulseAudio.
#
# PulseAudio is free software; you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# PulseAudio is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with PulseAudio; if not, see <http://www.gnu.org/licenses/>.

# This startup script is used only if PulseAudio is started per-user
# (i.e. not in system mode)

.fail

### Automatically restore the volume of streams and devices
load-module module-device-restore
load-module module-stream-restore
load-module module-card-restore

### Automatically augment property information from .desktop files
### stored in /usr/share/application
load-module module-augment-properties

### Should be after module-*-restore but before module-*-detect
load-module module-switch-on-port-available

### Use hot-plugged devices like Bluetooth or USB automatically (only load one of these)
load-module module-udev-detect

### Load several protocols
load-module module-native-protocol-unix auth-anonymous=1

### Automatically restore the default sink/source when changed by the user
### during runtime
### NOTE: This should be loaded as early as possible so that subsequent modules
### that look up the default sink/source get the right value
load-module module-default-device-restore

### Make sure we always have a sink around, even if it is a null sink.
load-module module-always-sink

### Honour intended role device property
load-module module-intended-roles

### Automatically suspend sinks/sources that become idle for too long
load-module module-suspend-on-idle

### Enable positioned event sounds
load-module module-position-event-sounds

### Cork music/video streams when a phone stream is active
load-module module-role-cork

### Modules to allow autoloading of filters (such as echo cancellation)
### on demand. module-filter-heuristics tries to determine what filters
### make sense, and module-filter-apply does the heavy-lifting of
### loading modules and rerouting streams.
load-module module-filter-heuristics
load-module module-filter-apply

### Load DBus protocol
load-module module-dbus-protocol

### Bluetooth support
load-module module-bluetooth-policy auto_switch=2
load-module module-bluez5-discover

### Enable TCP protocol for network access
load-module module-native-protocol-tcp auth-ip-acl=127.0.0.1;192.168.0.0/16

.nofail
.ifexists module-esound-protocol-unix.so
load-module module-esound-protocol-unix
.endif
.fail

### Make some devices default
#set-default-sink output
#set-default-source input
EOF

echo "Checking if bluetoothd is running..."
if ! systemctl is-active --quiet bluetooth; then
    echo "Starting bluetooth service..."
    sudo systemctl start bluetooth
    sleep 2
fi

echo "Starting PulseAudio with new configuration..."
pulseaudio --start --verbose

echo ""
echo "=== Configuration Complete ==="
echo "Testing PulseAudio modules..."

sleep 3

# Check if bluetooth modules loaded successfully
echo ""
echo "Checking loaded modules:"
pactl list modules short | grep -E "(bluetooth|bluez)"

echo ""
echo "Checking PulseAudio cards:"
pactl list cards short

echo ""
echo "=== Next Steps ==="
echo "1. The Bluetooth modules should now be loaded properly"
echo "2. Put your AT-TT turntable in pairing mode"
echo "3. Connect it to 'Pi4-Speaker' from the turntable's Bluetooth menu"
echo "4. Check for new Bluetooth card with: pactl list cards short"
echo ""
echo "If the turntable connects successfully, you should see a new card like:"
echo "bluez_card.F4_04_4C_1A_E5_B9"