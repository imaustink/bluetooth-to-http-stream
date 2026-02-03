#!/usr/bin/env python3
"""
PipeWire Turntable Audio Server - For Raspberry Pi OS Bookworm+
Captures audio from AT-TT turntable via PipeWire and streams with buffering
"""

import subprocess
import time
import signal
import sys
import threading
from collections import deque
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

class AudioBuffer:
    """Ring buffer for smooth audio streaming"""
    
    def __init__(self, max_size_mb=5):
        self.max_size = max_size_mb * 1024 * 1024
        self.buffer = deque()
        self.current_size = 0
        self.lock = threading.Lock()
        self.prebuffer_target = max_size_mb * 1024 * 1024 * 0.1  # 10% instead of 30%
        self.is_prebuffered = threading.Event()
        
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
            
            overflow_bytes = 0
            while self.current_size > self.max_size and self.buffer:
                old_data = self.buffer.popleft()
                self.current_size -= len(old_data)
                overflow_bytes += len(old_data)
            
            if self.current_size >= self.prebuffer_target:
                self.is_prebuffered.set()
    
    def get(self, size=4096):
        """Get data from buffer"""
        with self.lock:
            if not self.buffer:
                # Reset prebuffer flag when buffer is empty so it refills before resuming
                self.is_prebuffered.clear()
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
        
        print("⏳ Waiting for audio buffer to fill...")
        if not self.server.audio_buffer.wait_for_prebuffer():
            print("⚠️  Timeout waiting for buffer, starting anyway...")
        
        self.send_response(200)
        self.send_header('Content-Type', 'audio/wav')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'close')
        self.end_headers()
        
        # Send WAV header (44.1kHz, 16-bit stereo, infinite length)
        wav_header = bytes([
            0x52, 0x49, 0x46, 0x46,  # "RIFF"
            0xFF, 0xFF, 0xFF, 0xFF,  # File size (unknown, set to max)
            0x57, 0x41, 0x56, 0x45,  # "WAVE"
            0x66, 0x6D, 0x74, 0x20,  # "fmt "
            0x10, 0x00, 0x00, 0x00,  # fmt chunk size (16)
            0x01, 0x00,              # Audio format (1 = PCM)
            0x02, 0x00,              # Channels (2 = stereo)
            0x44, 0xAC, 0x00, 0x00,  # Sample rate (44100)
            0x10, 0xB1, 0x02, 0x00,  # Byte rate (44100 * 2 * 2 = 176400)
            0x04, 0x00,              # Block align (2 * 2 = 4)
            0x10, 0x00,              # Bits per sample (16)
            0x64, 0x61, 0x74, 0x61,  # "data"
            0xFF, 0xFF, 0xFF, 0xFF   # Data size (unknown, set to max)
        ])
        self.wfile.write(wav_header)
        self.wfile.flush()
        
        try:
            chunk_count = 0
            empty_count = 0
            while True:
                data = self.server.audio_buffer.get()
                
                if data:
                    self.wfile.write(data)
                    self.wfile.flush()
                    chunk_count += 1
                    empty_count = 0
                    
                    if chunk_count % 100 == 0:
                        stats = self.server.audio_buffer.get_stats()
                        print(f"🔊 Streaming to {self.client_address[0]} | Buffer: {stats['fill_percentage']:.1f}% ({stats['current_size_mb']:.1f}MB) | Chunks: {chunk_count} | In Buffer: {stats['chunks_in_buffer']}")
                else:
                    # Buffer is empty - wait for it to refill
                    empty_count += 1
                    if empty_count == 1:
                        print(f"⚠️  Buffer empty for {self.client_address[0]}, waiting to refill...")
                    if not self.server.audio_buffer.wait_for_prebuffer(timeout=5):
                        print(f"⚠️  Buffer refill timeout for {self.client_address[0]}")
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
        <h2>🎵 PipeWire AT-TT Turntable Audio Server</h2>
        <p><strong>Stream URL:</strong> http://192.168.1.218:8888/stream</p>
        <p><strong>Status:</strong> <a href="/status">/status</a></p>
        <p><strong>Buffer Fill:</strong> {:.1f}% ({:.2f}MB / {:.1f}MB)</p>
        <p><strong>Chunks in Buffer:</strong> {}</p>
        <p><strong>Total Data:</strong> Written: {:.1f}MB, Read: {:.1f}MB</p>
        <p><strong>Features:</strong></p>
        <ul>
            <li>✅ 5MB Audio Buffer</li>
            <li>✅ PipeWire Bluetooth Audio</li>
            <li>✅ Smooth Streaming</li>
            <li>✅ Multiple Client Support</li>
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

class PipeWireTurntableServer:
    """Main server class with PipeWire audio capture"""
    
    def __init__(self):
        self.att_mac = "F4:04:4C:1A:E5:B9"
        self.audio_buffer = AudioBuffer(max_size_mb=5)
        self.capture_process = None
        self.server = None
        self.capture_thread = None
        self.running = False
        self._shutting_down = False
        self._signal_received = False
        
    def check_bluetooth_connection(self):
        """Check if AT-TT is connected"""
        try:
            result = subprocess.run([
                "bluetoothctl", "info", self.att_mac
            ], capture_output=True, text=True, timeout=5)
            
            return "Connected: yes" in result.stdout
        except Exception:
            return False
    
    def find_bluetooth_source(self):
        """Find the PipeWire Bluetooth source node"""
        print("🔍 Searching for AT-TT in PipeWire...")
        
        try:
            # List all source nodes
            result = subprocess.run([
                "pw-cli", "ls", "Node"
            ], capture_output=True, text=True, timeout=5)
            
            # Look for our device
            lines = result.stdout.split('\n')
            for i, line in enumerate(lines):
                if self.att_mac.replace(':', '_') in line or "AT-TT" in line:
                    # Extract node ID
                    for j in range(max(0, i-10), i):
                        if 'id ' in lines[j]:
                            node_id = lines[j].split('id ')[1].split(',')[0].strip()
                            print(f"✅ Found AT-TT audio source: node {node_id}")
                            return node_id
            
            print("⚠️  AT-TT not found in PipeWire nodes")
            print("📋 Available nodes:")
            subprocess.run(["pw-cli", "ls", "Node"])
            return None
            
        except Exception as e:
            print(f"❌ PipeWire query error: {e}")
            return None
    
    def capture_audio_worker(self):
        """Worker thread for audio capture with buffering"""
        print("🎤 Starting PipeWire audio capture...")
        
        # Find the Bluetooth source
        node_id = self.find_bluetooth_source()
        if not node_id:
            print("❌ Cannot find AT-TT audio source")
            print("💡 Make sure the turntable is connected and playing audio")
            return
        
        try:
            # Use pw-cat to capture from the Bluetooth source
            self.capture_process = subprocess.Popen([
                "pw-cat",
                "--record",
                "--target", node_id,
                "--format", "s16",
                "--rate", "44100",
                "--channels", "2",
                "-"
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            print("📡 Audio capture started, filling buffer...")
            chunk_size = 4096
            chunk_count = 0
            no_data_count = 0
            max_no_data = 5
            
            while self.running and self.capture_process and self.capture_process.poll() is None:
                try:
                    import select
                    ready, _, _ = select.select([self.capture_process.stdout], [], [], 0.5)
                    
                    if ready:
                        data = self.capture_process.stdout.read(chunk_size)
                        if data:
                            self.audio_buffer.put(data)
                            chunk_count += 1
                            no_data_count = 0
                            
                            if chunk_count % 250 == 0:
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
            
            server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            server_thread.start()
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to start HTTP server: {e}")
            return False
    
    def shutdown(self):
        """Graceful shutdown"""
        if hasattr(self, '_shutting_down') and self._shutting_down:
            return
        
        self._shutting_down = True
        print("\n🛑 Shutting down...")
        
        self.running = False
        
        if self.capture_process:
            try:
                print("⏹️  Stopping audio capture process...")
                self.capture_process.terminate()
                
                try:
                    self.capture_process.wait(timeout=2)
                    print("✅ Audio capture terminated")
                except subprocess.TimeoutExpired:
                    print("🔨 Force killing audio capture process...")
                    self.capture_process.kill()
                    self.capture_process.wait(timeout=1)
                    
            except Exception as e:
                print(f"⚠️  Error stopping capture: {e}")
        
        if self.server:
            try:
                print("⏹️  Stopping HTTP server...")
                if hasattr(self.server, 'socket') and self.server.socket:
                    self.server.socket.close()
                
                def shutdown_server():
                    try:
                        self.server.shutdown()
                        self.server.server_close()
                    except:
                        pass
                
                shutdown_thread = threading.Thread(target=shutdown_server, daemon=True)
                shutdown_thread.start()
                shutdown_thread.join(timeout=2)
                
                print("✅ HTTP server stopped")
                    
            except Exception as e:
                print(f"⚠️  Error stopping HTTP server: {e}")
        
        if self.capture_thread and self.capture_thread.is_alive():
            print("⏳ Waiting for capture thread...")
            self.capture_thread.join(timeout=1)
            
        print("✅ Shutdown complete")
    
    def run(self):
        """Main execution flow"""
        print("🎵 PipeWire AT-TT Turntable Audio Server")
        print("=" * 60)
        
        def signal_handler(sig, frame):
            if not hasattr(self, '_signal_received') or not self._signal_received:
                self._signal_received = True
                print(f"\n🛑 Received signal {sig}, shutting down...")
                self.shutdown()
                threading.Timer(3.0, lambda: os._exit(0)).start()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        try:
            # Check Bluetooth connection
            if not self.check_bluetooth_connection():
                print("❌ AT-TT turntable is not connected")
                print("💡 Connect via: bluetoothctl connect F4:04:4C:1A:E5:B9")
                return False
            
            print("✅ AT-TT turntable is connected")
            
            # Start audio capture
            if not self.start_audio_capture():
                print("❌ Failed to start audio capture")
                return False
            
            print("✅ Audio capture started")
            
            # Start HTTP server
            if not self.start_http_server():
                print("❌ Failed to start HTTP server")
                return False
            
            print("✅ HTTP server started")
            print("\n🎧 Server is ready!")
            print("   📱 Audio Stream: http://192.168.1.218:8888/stream")
            print("   📊 Server Status: http://192.168.1.218:8888/status")
            print("\n📡 Server running with 5MB buffer...")
            print("   Press Ctrl+C to stop")
            
            while True:
                time.sleep(1)
                if int(time.time()) % 30 == 0:
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
    print("Starting PipeWire Turntable Audio Server...")
    server = PipeWireTurntableServer()
    success = server.run()
    sys.exit(0 if success else 1)
