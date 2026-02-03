#!/usr/bin/env python3
"""
Buffered Turntable Audio Server - Anti-Jitter Edition
Captures audio from AT-TT turntable via BlueALSA and streams with buffering
"""

import subprocess
import time
import signal
import sys
import threading
import queue
from collections import deque
import os
import select
from http.server import HTTPServer, BaseHTTPRequestHandler

class AudioBuffer:
    """Ring buffer for smooth audio streaming"""
    
    def __init__(self, max_size_mb=5):
        self.max_size = max_size_mb * 1024 * 1024  # Convert to bytes
        self.buffer = deque()
        self.current_size = 0
        self.lock = threading.Lock()
        self.prebuffer_target = max_size_mb * 1024 * 1024 * 0.3  # 30% of buffer for prebuffering
        self.is_prebuffered = threading.Event()
        
        # Statistics for better monitoring
        self.bytes_written = 0
        self.bytes_read = 0
        self.chunks_written = 0
        self.chunks_read = 0
        
    def put(self, data):
        """Add data to buffer with overflow protection"""
        with self.lock:
            self.buffer.append(data)
            self.current_size += len(data)
            self.bytes_written += len(data)
            self.chunks_written += 1
            
            # Remove old data if buffer is full
            overflow_bytes = 0
            while self.current_size > self.max_size and self.buffer:
                old_data = self.buffer.popleft()
                self.current_size -= len(old_data)
                overflow_bytes += len(old_data)
            
            # Signal when we have enough data for smooth streaming
            if self.current_size >= self.prebuffer_target:
                self.is_prebuffered.set()
    
    def get(self, size=4096):
        """Get data from buffer"""
        with self.lock:
            if not self.buffer:
                return b''
            
            data = self.buffer.popleft()
            self.current_size -= len(data)
            self.bytes_read += len(data)
            self.chunks_read += 1
            return data
    
    def get_fill_level(self):
        """Get buffer fill percentage"""
        with self.lock:
            if self.max_size == 0:
                return 0.0
            return (self.current_size / self.max_size) * 100
    
    def get_stats(self):
        """Get buffer statistics"""
        with self.lock:
            return {
                'current_size_bytes': self.current_size,
                'current_size_mb': self.current_size / (1024 * 1024),
                'max_size_mb': self.max_size / (1024 * 1024),
                'fill_percentage': (self.current_size / self.max_size) * 100 if self.max_size > 0 else 0,
                'chunks_in_buffer': len(self.buffer),
                'total_bytes_written': self.bytes_written,
                'total_bytes_read': self.bytes_read,
                'total_chunks_written': self.chunks_written,
                'total_chunks_read': self.chunks_read,
                'is_prebuffered': self.is_prebuffered.is_set()
            }
    
    def wait_for_prebuffer(self, timeout=10):
        """Wait for initial buffer to fill"""
        return self.is_prebuffered.wait(timeout)

class BufferedTurntableHandler(BaseHTTPRequestHandler):
    """HTTP handler with buffered audio streaming"""
    
    def log_message(self, format, *args):
        """Suppress default HTTP logging"""
        pass
    
    def do_GET(self):
        """Handle GET requests for audio stream"""
        if self.path == '/stream':
            self.stream_audio()
        elif self.path == '/status':
            self.show_status()
        elif self.path == '/':
            self.show_info()
        else:
            self.send_error(404)
    
    def stream_audio(self):
        """Stream buffered audio to client"""
        print(f"📱 New client connected: {self.client_address[0]}")
        
        # Wait for buffer to fill initially
        print("⏳ Waiting for audio buffer to fill...")
        if not self.server.audio_buffer.wait_for_prebuffer():
            print("⚠️  Timeout waiting for buffer, starting anyway...")
        
        self.send_response(200)
        self.send_header('Content-Type', 'audio/wav')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'close')
        self.end_headers()
        
        try:
            chunk_count = 0
            while True:
                # Get buffered audio data
                data = self.server.audio_buffer.get()
                
                if data:
                    self.wfile.write(data)
                    self.wfile.flush()
                    chunk_count += 1
                    
                    # Show buffer status periodically
                    if chunk_count % 100 == 0:
                        stats = self.server.audio_buffer.get_stats()
                        print(f"🔊 Streaming to {self.client_address[0]} | Buffer: {stats['fill_percentage']:.1f}% ({stats['current_size_mb']:.1f}MB) | Chunks: {chunk_count} | In Buffer: {stats['chunks_in_buffer']}")
                else:
                    # No data available, small delay to prevent busy waiting
                    time.sleep(0.01)
                    
        except (ConnectionResetError, BrokenPipeError):
            print(f"📱 Client {self.client_address[0]} disconnected")
        except Exception as e:
            print(f"❌ Streaming error: {e}")
    
    def show_status(self):
        """Show server status"""
        stats = self.server.audio_buffer.get_stats()
        status = f"""{{
    "buffer_fill_percentage": {stats['fill_percentage']:.1f},
    "buffer_size_mb": {stats['current_size_mb']:.2f},
    "max_buffer_mb": {stats['max_size_mb']:.1f},
    "chunks_in_buffer": {stats['chunks_in_buffer']},
    "total_bytes_written": {stats['total_bytes_written']},
    "total_bytes_read": {stats['total_bytes_read']},
    "total_chunks_written": {stats['total_chunks_written']},
    "total_chunks_read": {stats['total_chunks_read']},
    "prebuffered": {str(stats['is_prebuffered']).lower()},
    "server": "running"
}}"""
        
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(status.encode())
    
    def show_info(self):
        """Show connection info"""
        stats = self.server.audio_buffer.get_stats()
        info = """
        <html><body>
        <h2>🎵 Buffered AT-TT Turntable Audio Server</h2>
        <p><strong>Stream URL:</strong> http://192.168.1.218:8888/stream</p>
        <p><strong>Status:</strong> <a href="/status">/status</a></p>
        <p><strong>Buffer Fill:</strong> {:.1f}% ({:.2f}MB / {:.1f}MB)</p>
        <p><strong>Chunks in Buffer:</strong> {}</p>
        <p><strong>Total Data:</strong> Written: {:.1f}MB, Read: {:.1f}MB</p>
        <p><strong>Features:</strong></p>
        <ul>
            <li>✅ 5MB Audio Buffer</li>
            <li>✅ Anti-Jitter Technology</li>
            <li>✅ Smooth Streaming</li>
            <li>✅ Multiple Client Support</li>
            <li>✅ Real-time Buffer Statistics</li>
        </ul>
        </body></html>
        """.format(
            stats['fill_percentage'], 
            stats['current_size_mb'], 
            stats['max_size_mb'],
            stats['chunks_in_buffer'],
            stats['total_bytes_written'] / (1024*1024),
            stats['total_bytes_read'] / (1024*1024)
        )
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(info.encode())

class BufferedTurntableServer:
    """Main server class with buffered audio capture"""
    
    def __init__(self):
        self.att_mac = "F4:04:4C:1A:E5:B9"
        self.audio_buffer = AudioBuffer(max_size_mb=5)
        self.capture_process = None
        self.server = None
        self.capture_thread = None
        self.running = False
        self._shutting_down = False
        self._signal_received = False
        
    def cleanup_existing_processes(self):
        """Kill any existing audio processes"""
        print("🧹 Cleaning up existing processes...")
        subprocess.run(["pkill", "-f", "arecord"], capture_output=True)
        subprocess.run(["pkill", "-f", "bluealsa-aplay"], capture_output=True)
        time.sleep(1)
    
    def check_bluetooth_connection(self):
        """Check if AT-TT is connected"""
        try:
            result = subprocess.run([
                "bluetoothctl", "info", self.att_mac
            ], capture_output=True, text=True, timeout=5)
            
            return "Connected: yes" in result.stdout
        except Exception:
            return False
    
    def check_bluealsa_device(self):
        """Check if BlueALSA can see the turntable"""
        print("🔍 Checking BlueALSA devices...")
        
        try:
            result = subprocess.run(["bluealsa-aplay", "-L"], capture_output=True, text=True)
            
            if "F4:04:4C:1A:E5:B9" in result.stdout:
                print("✅ AT-TT found in BlueALSA")
                return True
            else:
                print("❌ AT-TT not found in BlueALSA")
                return False
                
        except Exception as e:
            print(f"❌ BlueALSA check error: {e}")
            return False
    
    def test_bluealsa_capture(self):
        """Test if BlueALSA capture is working"""
        print("🧪 Testing BlueALSA capture...")
        
        try:
            proc = subprocess.Popen([
                "timeout", "2",
                "arecord", "-D", "bluealsa:SRV=org.bluealsa,DEV=F4:04:4C:1A:E5:B9,PROFILE=a2dp",
                "-f", "cd", "-t", "wav", "/tmp/bluealsa_test.wav"
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            
            stdout, stderr = proc.communicate()
            
            if "Device or resource busy" in stderr:
                print("⚠️  BlueALSA device is busy (need to kill bluealsa-aplay)")
                return "busy"
            elif proc.returncode == 0 or "Recording WAVE" in stderr:
                print("✅ BlueALSA capture test successful")
                return True
            else:
                print(f"❌ BlueALSA test failed: {stderr}")
                return False
                
        except Exception as e:
            print(f"❌ BlueALSA test error: {e}")
            return False
    
    def kill_blocking_processes(self):
        """Kill processes that block BlueALSA access"""
        print("🔧 Killing blocking bluealsa-aplay processes...")
        try:
            # Find and kill bluealsa-aplay processes
            result = subprocess.run(["pgrep", "-f", "bluealsa-aplay"], capture_output=True, text=True)
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    if pid:
                        print(f"   Killing PID {pid}")
                        subprocess.run(["sudo", "kill", pid])
                time.sleep(1)
                return True
        except Exception as e:
            print(f"❌ Error killing processes: {e}")
        return False
    
    def capture_audio_worker(self):
        """Worker thread for audio capture with buffering"""
        print("🎤 Starting buffered audio capture...")
        
        try:
            # Start arecord process
            self.capture_process = subprocess.Popen([
                "arecord",
                "-D", "bluealsa:SRV=org.bluealsa,DEV=F4:04:4C:1A:E5:B9,PROFILE=a2dp",
                "-f", "cd",
                "-t", "wav",
                "--buffer-size=8192",  # Larger buffer for stability
                "-"  # Output to stdout
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            print("📡 Audio capture started, filling buffer...")
            chunk_size = 4096
            chunk_count = 0
            no_data_count = 0
            max_no_data = 5  # Max consecutive "no data" before stopping
            
            while self.running and self.capture_process and self.capture_process.poll() is None:
                try:
                    # Use a timeout on read to avoid blocking indefinitely
                    import select
                    ready, _, _ = select.select([self.capture_process.stdout], [], [], 0.5)
                    
                    if ready:
                        data = self.capture_process.stdout.read(chunk_size)
                        if data:
                            self.audio_buffer.put(data)
                            chunk_count += 1
                            no_data_count = 0  # Reset no-data counter
                            
                            # Progress indicator
                            if chunk_count % 250 == 0:  # Every ~10 seconds at 4KB chunks
                                stats = self.audio_buffer.get_stats()
                                print(f"🔊 Audio capture running | Buffer: {stats['fill_percentage']:.1f}% ({stats['current_size_mb']:.1f}MB) | Chunks captured: {chunk_count} | Buffer chunks: {stats['chunks_in_buffer']}")
                        else:
                            no_data_count += 1
                            if no_data_count <= max_no_data:
                                print("⚠️  No audio data received")
                            elif no_data_count == max_no_data + 1:
                                print("⚠️  No audio data - suppressing further messages...")
                            
                            if no_data_count > max_no_data and not self.running:
                                break
                            time.sleep(0.1)
                    else:
                        # No data ready, check if we should continue
                        if not self.running:
                            break
                        time.sleep(0.1)
                        
                except Exception as e:
                    if self.running and not self._shutting_down:
                        print(f"❌ Capture error: {e}")
                    break
                    
        except Exception as e:
            if not self._shutting_down:
                print(f"❌ Failed to start audio capture: {e}")
        
        print("🔇 Audio capture stopped")
    
    def start_audio_capture(self):
        """Start the audio capture process"""
        if self.capture_thread and self.capture_thread.is_alive():
            print("⚠️  Audio capture already running")
            return True
        
        self.running = True
        self.capture_thread = threading.Thread(target=self.capture_audio_worker, daemon=True)
        self.capture_thread.start()
        
        # Wait a moment for capture to start
        time.sleep(2)
        return self.capture_thread.is_alive()
    
    def start_http_server(self):
        """Start the HTTP server"""
        try:
            self.server = HTTPServer(('0.0.0.0', 8888), BufferedTurntableHandler)
            self.server.audio_buffer = self.audio_buffer
            
            print(f"🌐 HTTP server starting on port 8888...")
            print(f"📱 Stream URL: http://192.168.1.218:8888/stream")
            print(f"📊 Status URL: http://192.168.1.218:8888/status")
            print(f"🔄 Buffer size: 5MB with anti-jitter technology")
            
            server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            server_thread.start()
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to start HTTP server: {e}")
            return False
    
    def shutdown(self):
        """Graceful shutdown"""
        if hasattr(self, '_shutting_down') and self._shutting_down:
            return  # Prevent reentrant calls
        
        self._shutting_down = True
        sys.stdout.flush()  # Flush before printing
        print("\n🛑 Shutting down...")
        sys.stdout.flush()
        
        # Stop the running flag first
        self.running = False
        
        # Terminate capture process more aggressively
        if self.capture_process:
            try:
                print("⏹️  Stopping audio capture process...")
                self.capture_process.terminate()
                
                # Give it a moment to terminate gracefully
                try:
                    self.capture_process.wait(timeout=2)
                    print("✅ Audio capture terminated gracefully")
                except subprocess.TimeoutExpired:
                    print("🔨 Force killing audio capture process...")
                    self.capture_process.kill()
                    try:
                        self.capture_process.wait(timeout=1)
                        print("✅ Audio capture force killed")
                    except subprocess.TimeoutExpired:
                        print("⚠️  Audio capture process may still be running")
                        
            except (subprocess.TimeoutExpired, AttributeError, OSError) as e:
                print(f"⚠️  Error stopping capture process: {e}")
                try:
                    if self.capture_process:
                        self.capture_process.kill()
                except:
                    pass
        
        # Stop HTTP server
        if self.server:
            try:
                print("⏹️  Stopping HTTP server...")
                
                # Close server socket first to stop accepting new connections
                if hasattr(self.server, 'socket') and self.server.socket:
                    self.server.socket.close()
                
                # Shutdown server in a separate thread with timeout
                def shutdown_server():
                    try:
                        self.server.shutdown()
                        self.server.server_close()
                    except:
                        pass
                
                shutdown_thread = threading.Thread(target=shutdown_server, daemon=True)
                shutdown_thread.start()
                shutdown_thread.join(timeout=2)  # 2 second timeout
                
                if shutdown_thread.is_alive():
                    print("⚠️  HTTP server shutdown timed out, forcing close")
                else:
                    print("✅ HTTP server stopped")
                    
            except Exception as e:
                print(f"⚠️  Error stopping HTTP server: {e}")
        
        # Wait for capture thread to finish
        if self.capture_thread and self.capture_thread.is_alive():
            print("⏳ Waiting for capture thread to finish...")
            self.capture_thread.join(timeout=1)  # Reduced to 1 second
            if self.capture_thread.is_alive():
                print("⚠️  Capture thread didn't finish in time")
            else:
                print("✅ Capture thread finished")
        
        # Final cleanup
        try:
            self.cleanup_existing_processes()
        except:
            pass
            
        print("✅ Shutdown complete")
        sys.stdout.flush()
    
    def run(self):
        """Main execution flow"""
        print("🎵 Buffered AT-TT Turntable Audio Server")
        print("=" * 60)
        
        # Setup signal handlers
        def signal_handler(sig, frame):
            if not hasattr(self, '_signal_received') or not self._signal_received:
                self._signal_received = True
                print(f"\n🛑 Received signal {sig}, initiating shutdown...")
                self.shutdown()
                # Give shutdown a moment, then force exit
                threading.Timer(3.0, lambda: os._exit(0)).start()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        try:
            # Step 1: Check connections
            if not self.check_bluetooth_connection():
                print("❌ AT-TT turntable is not connected")
                print("💡 Connect via: bluetoothctl connect F4:04:4C:1A:E5:B9")
                return False
            
            print("✅ AT-TT turntable is connected")
            
            # Step 2: Test BlueALSA
            bluealsa_test = self.test_bluealsa_capture()
            if bluealsa_test == "busy":
                if self.kill_blocking_processes():
                    print("✅ Cleared blocking processes")
                    bluealsa_test = self.test_bluealsa_capture()
            
            if not bluealsa_test:
                print("❌ BlueALSA cannot access the turntable")
                print("💡 Try reconnecting: bluetoothctl disconnect F4:04:4C:1A:E5:B9 && bluetoothctl connect F4:04:4C:1A:E5:B9")
                return False
            
            print("✅ BlueALSA audio capture ready")
            
            # Step 3: Start audio capture
            if not self.start_audio_capture():
                print("❌ Failed to start audio capture")
                return False
            
            print("✅ Buffered audio capture started")
            
            # Step 4: Start HTTP server
            if not self.start_http_server():
                print("❌ Failed to start HTTP server")
                return False
            
            print("✅ HTTP server started")
            print("\n🎧 Server is ready! Use these URLs:")
            print("   📱 Audio Stream: http://192.168.1.218:8888/stream")
            print("   📊 Server Status: http://192.168.1.218:8888/status")
            print("   ℹ️  Server Info: http://192.168.1.218:8888/")
            print("\n💡 Recommended apps:")
            print("   📱 VLC for iOS - Open Network Stream")
            print("   🎵 Foobar2000 - Network → Add Location")
            print("\n📡 Server running with 5MB buffer for smooth streaming...")
            print("   Press Ctrl+C to stop")
            
            # Keep server running
            try:
                while True:
                    time.sleep(1)
                    # Periodic status
                    if int(time.time()) % 30 == 0:  # Every 30 seconds
                        stats = self.audio_buffer.get_stats()
                        capture_status = '✅' if self.capture_thread.is_alive() else '❌'
                        print(f"📊 Status: Buffer {stats['fill_percentage']:.1f}% ({stats['current_size_mb']:.1f}MB) | Chunks: {stats['chunks_in_buffer']} | Capture: {capture_status}")
                        
            except KeyboardInterrupt:
                pass
            
        except Exception as e:
            print(f"❌ Server error: {e}")
            return False
        finally:
            self.shutdown()
        
        return True

if __name__ == "__main__":
    print("Starting Buffered Turntable Audio Server...")
    server = BufferedTurntableServer()
    success = server.run()
    sys.exit(0 if success else 1)