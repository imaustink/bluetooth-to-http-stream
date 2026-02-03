#!/bin/bash

# Safe Bluetooth Speaker Emulator Startup Script
# This script includes safety checks to prevent kernel panics

echo "🔧 Safe Bluetooth Speaker Emulator Startup"
echo "=========================================="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "❌ Please run as root: sudo ./safe-bluetooth-start.sh"
    exit 1
fi

# Function to check system resources
check_system_resources() {
    echo "📊 Checking system resources..."
    
    # Check memory usage
    local mem_usage=$(free | grep Mem | awk '{printf "%.0f", ($3/$2) * 100}')
    echo "   Memory usage: ${mem_usage}%"
    
    if [ "$mem_usage" -gt 80 ]; then
        echo "⚠️  WARNING: High memory usage (${mem_usage}%). Consider rebooting."
        read -p "Continue anyway? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
    
    # Check if Bluetooth service is responsive
    echo "🔧 Checking Bluetooth service..."
    if systemctl is-active --quiet bluetooth; then
        echo "   ✅ Bluetooth service is running"
    else
        echo "   🔄 Starting Bluetooth service..."
        systemctl start bluetooth
        sleep 2
    fi
    
    # Check for previous kernel panics
    if dmesg | grep -q "Internal error: Oops"; then
        echo "⚠️  WARNING: Previous kernel errors detected in dmesg"
        echo "   Consider rebooting before running the script"
        read -p "Continue anyway? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
}

# Function to setup monitoring
setup_monitoring() {
    echo "📡 Setting up system monitoring..."
    
    # Create a monitoring script that runs in background
    cat > /tmp/bt_monitor.sh << 'EOF'
#!/bin/bash
while true; do
    # Check memory usage
    mem_usage=$(free | grep Mem | awk '{printf "%.0f", ($3/$2) * 100}')
    if [ "$mem_usage" -gt 90 ]; then
        echo "$(date): CRITICAL - Memory usage: ${mem_usage}%" >> /tmp/bt_monitor.log
        # Could implement auto-restart here
    fi
    
    # Check for kernel errors
    if dmesg -T | tail -10 | grep -q "Internal error\|Oops\|Call trace"; then
        echo "$(date): CRITICAL - Kernel error detected!" >> /tmp/bt_monitor.log
        echo "$(date): STOPPING BLUETOOTH SCRIPT" >> /tmp/bt_monitor.log
        pkill -f "rpi-bluetooth-speaker-poc.py"
    fi
    
    sleep 10
done
EOF
    
    chmod +x /tmp/bt_monitor.sh
    /tmp/bt_monitor.sh &
    BT_MONITOR_PID=$!
    echo "   ✅ System monitor started (PID: $BT_MONITOR_PID)"
}

# Function to cleanup on exit
cleanup() {
    echo "🧹 Cleaning up..."
    if [ ! -z "$BT_MONITOR_PID" ]; then
        kill $BT_MONITOR_PID 2>/dev/null
        echo "   ✅ Monitor stopped"
    fi
    
    # Reset Bluetooth adapter
    echo "   🔄 Resetting Bluetooth adapter..."
    hciconfig hci0 down
    sleep 1
    hciconfig hci0 up
    
    echo "   ✅ Cleanup complete"
}

# Trap cleanup on exit
trap cleanup EXIT

# Main execution
main() {
    check_system_resources
    setup_monitoring
    
    echo "🚀 Starting Gentle Bluetooth Speaker Emulator..."
    echo "   Monitor log: tail -f /tmp/bt_monitor.log"
    echo "   Press Ctrl+C to stop safely"
    echo ""
    
    # Start the Python script with resource limits
    ulimit -v 512000  # Limit virtual memory to 500MB
    nice -n 10 python3 rpi-bluetooth-speaker-poc.py
}

# Run main function
main "$@"