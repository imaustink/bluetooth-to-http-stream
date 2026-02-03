use axum::{
    extract::State,
    http::{header, StatusCode},
    response::{IntoResponse, Response, Html},
    routing::get,
    Router,
};
use bytes::Bytes;
use std::sync::Arc;
use tokio::sync::{RwLock, Semaphore};
use std::collections::VecDeque;
use std::time::{Duration, Instant};
use tracing::{info, warn, error};

const BUFFER_SIZE_MB: usize = 5;
const BUFFER_SIZE_BYTES: usize = BUFFER_SIZE_MB * 1024 * 1024;
const MAX_CHUNKS: usize = (BUFFER_SIZE_BYTES / CHUNK_SIZE) + 256; // ~1280 + extra headroom
const PREBUFFER_PERCENT: f32 = 0.60; // 60% - ~3MB, ~17 seconds
const PREBUFFER_CHUNKS: usize = (MAX_CHUNKS as f32 * PREBUFFER_PERCENT) as usize; // ~768 chunks
const MIN_BUFFER_PERCENT: f32 = 0.40; // Unused - kept for reference (hysteresis removed)
const CHUNK_SIZE: usize = 4096; // Match Python working version
const SERVER_PORT: u16 = 80;

/// Get Bluetooth device MAC from environment or use any available A2DP source
fn get_target_device() -> Option<String> {
    std::env::var("BLUETOOTH_MAC").ok()
}

/// High-performance ring buffer for audio data
#[derive(Clone)]
struct AudioBuffer {
    buffer: Arc<RwLock<VecDeque<Bytes>>>,
    stats: Arc<RwLock<BufferStats>>,
    prebuffer_semaphore: Arc<Semaphore>,
}

#[derive(Debug, Clone, Default)]
struct BufferStats {
    current_size: usize,
    bytes_written: u64,
    bytes_read: u64,
    chunks_written: u64,
    chunks_read: u64,
    is_prebuffered: bool,
}

impl AudioBuffer {
    fn new() -> Self {
        Self {
            buffer: Arc::new(RwLock::new(VecDeque::with_capacity(MAX_CHUNKS))),
            stats: Arc::new(RwLock::new(BufferStats::default())),
            prebuffer_semaphore: Arc::new(Semaphore::new(0)),
        }
    }

    async fn put(&self, data: Bytes) {
        let data_len = data.len();
        
        let mut buffer = self.buffer.write().await;
        let mut stats = self.stats.write().await;
        
        // Enforce hard limit on number of chunks
        while buffer.len() >= MAX_CHUNKS {
            if let Some(old_data) = buffer.pop_front() {
                stats.current_size -= old_data.len();
            }
        }
        
        buffer.push_back(data);
        stats.current_size += data_len;
        stats.bytes_written += data_len as u64;
        stats.chunks_written += 1;

        // Signal prebuffer complete when we reach chunk threshold
        if buffer.len() >= PREBUFFER_CHUNKS {
            if !stats.is_prebuffered {
                stats.is_prebuffered = true;
                self.prebuffer_semaphore.add_permits(1000); // Allow many waiters
            }
        } else {
            // Reset flag when buffer drops below threshold
            if stats.is_prebuffered {
                stats.is_prebuffered = false;
            }
        }
    }

    async fn get(&self) -> Option<Bytes> {
        let mut buffer = self.buffer.write().await;
        let mut stats = self.stats.write().await;
        
        if let Some(data) = buffer.pop_front() {
            stats.current_size -= data.len();
            stats.bytes_read += data.len() as u64;
            stats.chunks_read += 1;
            
            // Reset prebuffer flag when empty
            if buffer.is_empty() {
                stats.is_prebuffered = false;
            }
            
            Some(data)
        } else {
            // Reset prebuffer when empty
            stats.is_prebuffered = false;
            None
        }
    }

    async fn wait_for_prebuffer(&self, timeout: Duration) -> bool {
        tokio::time::timeout(timeout, self.prebuffer_semaphore.acquire())
            .await
            .is_ok()
    }

    async fn get_stats(&self) -> BufferStats {
        self.stats.read().await.clone()
    }

    async fn get_fill_percentage(&self) -> f32 {
        let stats = self.stats.read().await;
        if BUFFER_SIZE_BYTES == 0 {
            0.0
        } else {
            (stats.current_size as f32 / BUFFER_SIZE_BYTES as f32) * 100.0
        }
    }
}

/// Generate WAV header for 44.1kHz 16-bit stereo
fn wav_header() -> [u8; 44] {
    [
        0x52, 0x49, 0x46, 0x46,  // "RIFF"
        0xFF, 0xFF, 0xFF, 0xFF,  // File size (unknown)
        0x57, 0x41, 0x56, 0x45,  // "WAVE"
        0x66, 0x6D, 0x74, 0x20,  // "fmt "
        0x10, 0x00, 0x00, 0x00,  // fmt chunk size (16)
        0x01, 0x00,              // Audio format (1 = PCM)
        0x02, 0x00,              // Channels (2 = stereo)
        0x44, 0xAC, 0x00, 0x00,  // Sample rate (44100)
        0x10, 0xB1, 0x02, 0x00,  // Byte rate (176400)
        0x04, 0x00,              // Block align (4)
        0x10, 0x00,              // Bits per sample (16)
        0x64, 0x61, 0x74, 0x61,  // "data"
        0xFF, 0xFF, 0xFF, 0xFF   // Data size (unknown)
    ]
}

/// Stream audio endpoint
async fn stream_audio(State(buffer): State<AudioBuffer>) -> Response {
    info!("New client connected for streaming");

    // Wait for prebuffer
    info!("Waiting for audio buffer to fill...");
    if !buffer.wait_for_prebuffer(Duration::from_secs(10)).await {
        warn!("Timeout waiting for buffer, starting anyway");
    }

    let audio_stream = async_stream::stream! {
        // Send WAV header first
        yield Ok::<_, std::io::Error>(Bytes::from(wav_header().to_vec()));

        let mut chunk_count = 0u64;
        let mut empty_count = 0u32;
        let mut last_log = Instant::now();

        loop {
            if let Some(data) = buffer.get().await {
                yield Ok(data);
                chunk_count += 1;
                empty_count = 0;

                // Log every 100 chunks or every 5 seconds
                if chunk_count % 100 == 0 || last_log.elapsed() > Duration::from_secs(5) {
                    let stats = buffer.get_stats().await;
                    let fill = buffer.get_fill_percentage().await;
                    let actual_chunks = {
                        let b = buffer.buffer.read().await;
                        b.len()
                    };
                    info!(
                        "🔊 Streaming | Buffer: {:.1}% ({:.1}MB) | Sent: {} | In buffer: {}/{}",
                        fill,
                        stats.current_size as f32 / (1024.0 * 1024.0),
                        chunk_count,
                        actual_chunks,
                        MAX_CHUNKS
                    );
                    last_log = Instant::now();
                }
            } else {
                // Buffer empty - wait for refill
                empty_count += 1;
                if empty_count == 1 {
                    warn!("⚠️  Buffer empty, waiting to refill...");
                }
                
                if !buffer.wait_for_prebuffer(Duration::from_secs(10)).await {
                    warn!("⚠️  Buffer refill timeout");
                }
                
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
        }
    };

    let body = axum::body::Body::from_stream(audio_stream);

    Response::builder()
        .status(StatusCode::OK)
        .header(header::CONTENT_TYPE, "audio/wav")
        .header(header::CACHE_CONTROL, "no-cache")
        .header(header::CONNECTION, "close")
        .body(body)
        .unwrap()
}

/// Status endpoint
async fn status(State(buffer): State<AudioBuffer>) -> impl IntoResponse {
    let stats = buffer.get_stats().await;
    let fill_pct = buffer.get_fill_percentage().await;
    
    // Get actual buffer length
    let actual_chunks = {
        let buffer = buffer.buffer.read().await;
        buffer.len()
    };
    
    let status = serde_json::json!({
        "buffer_fill_percentage": fill_pct,
        "buffer_size_mb": stats.current_size as f32 / (1024.0 * 1024.0),
        "max_buffer_mb": BUFFER_SIZE_MB,
        "chunks_in_buffer": actual_chunks,
        "max_chunks": MAX_CHUNKS,
        "total_bytes_written": stats.bytes_written,
        "total_bytes_read": stats.bytes_read,
        "total_chunks_written": stats.chunks_written,
        "total_chunks_read": stats.chunks_read,
        "prebuffered": stats.is_prebuffered,
        "server": "running"
    });
    let actual_chunks = {
        let buf = buffer.buffer.read().await;
        buf.len()
    };    (StatusCode::OK, axum::Json(status))
}

/// Info endpoint
async fn info(State(buffer): State<AudioBuffer>) -> Html<String> {
    let stats = buffer.get_stats().await;
    let fill_pct = buffer.get_fill_percentage().await;
    let actual_chunks = {
        let buf = buffer.buffer.read().await;
        buf.len()
    };
    
    let html = format!(
        r#"
        <html><body>
        <h2>🎵 BlueALSA Bluetooth Turntable Audio Server (Rust)</h2>
        <p><strong>Stream URL:</strong> http://[server-ip]:{}/stream</p>
        <p><strong>Status:</strong> <a href="/status">/status</a></p>
        <p><strong>Buffer Fill:</strong> {:.1}% ({:.2}MB / {}MB)</p>
        <p><strong>Chunks in Buffer:</strong> {} / {}</p>
        <p><strong>Total Data:</strong> Written: {:.1}MB, Read: {:.1}MB</p>
        <p><strong>Features:</strong></p>
        <ul>
            <li>✅ {}MB Audio Buffer</li>
            <li>✅ BlueALSA Bluetooth Audio</li>
            <li>✅ Zero-Copy Streaming</li>
            <li>✅ Async I/O (Tokio)</li>
            <li>✅ Multiple Client Support</li>
        </ul>
        <p><strong>Configuration:</strong></p>
        <ul>
            <li>Set BLUETOOTH_MAC env var to target specific device</li>
            <li>Otherwise auto-discovers first A2DP Bluetooth source</li>
        </ul>
        </body></html>
        "#,
        SERVER_PORT,
        fill_pct,
        stats.current_size as f32 / (1024.0 * 1024.0),
        BUFFER_SIZE_MB,
        actual_chunks,
        MAX_CHUNKS,
        stats.bytes_written as f32 / (1024.0 * 1024.0),
        stats.bytes_read as f32 / (1024.0 * 1024.0),
        BUFFER_SIZE_MB
    );

    Html(html)
}

/// Audio capture task using arecord via subprocess
async fn audio_capture_task(buffer: AudioBuffer) {
    info!("🎤 Starting BlueALSA audio capture...");

    loop {
        match start_bluealsa_capture(&buffer).await {
            Ok(_) => {
                warn!("Audio capture ended normally, restarting...");
            }
            Err(e) => {
                error!("❌ Audio capture error: {}, restarting in 5s...", e);
                tokio::time::sleep(Duration::from_secs(5)).await;
            }
        }
    }
}

async fn start_bluealsa_capture(buffer: &AudioBuffer) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    use tokio::process::Command;
    use tokio::io::AsyncReadExt;

    // Find Bluetooth source device (use target MAC if set, otherwise auto-discover)
    let target_mac = get_target_device().unwrap_or_else(|| "F4:04:4C:1A:E5:B9".to_string());
    info!("✅ Targeting Bluetooth device: {}", target_mac);

    // Build BlueALSA PCM path: /org/bluealsa/hci0/dev_XX_XX_XX_XX_XX_XX/a2dpsnk/source
    let bluealsa_path = format!(
        "/org/bluealsa/hci0/dev_{}/a2dpsnk/source",
        target_mac.replace(':', "_")
    );
    
    info!("📡 Opening BlueALSA PCM: {}", bluealsa_path);

    // Use bluealsa-cli to capture audio directly from BlueALSA
    let mut child = Command::new("bluealsa-cli")
        .args(&["open", &bluealsa_path])
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::null())
        .spawn()?;

    let mut stdout = child.stdout.take()
        .ok_or("Failed to get stdout")?;

    info!("📡 Audio capture started, filling buffer...");
    
    let mut chunk_buf = vec![0u8; CHUNK_SIZE];
    let mut chunk_count = 0u64;
    let mut last_log = Instant::now();

    loop {
        match stdout.read(&mut chunk_buf).await {
            Ok(n) if n > 0 => {
                buffer.put(Bytes::copy_from_slice(&chunk_buf[..n])).await;
                chunk_count += 1;

                if chunk_count % 100 == 0 || last_log.elapsed() > Duration::from_secs(10) {
                    let stats = buffer.get_stats().await;
                    let fill = buffer.get_fill_percentage().await;
                    let actual_chunks = {
                        let buf = buffer.buffer.read().await;
                        buf.len()
                    };
                    info!(
                        "🔊 Capture | Buffer: {:.1}% ({:.1}MB) | Chunks: {} | In buffer: {}/{}",
                        fill,
                        stats.current_size as f32 / (1024.0 * 1024.0),
                        chunk_count,
                        actual_chunks,
                        MAX_CHUNKS
                    );
                    last_log = Instant::now();
                }
            }
            Ok(_) => {
                warn!("Audio stream ended");
                break;
            }
            Err(e) => {
                error!("Read error: {}", e);
                break;
            }
        }
    }

    let _ = child.kill().await;
    Ok(())
}

async fn find_bluealsa_device() -> Result<String, Box<dyn std::error::Error + Send + Sync>> {
    use tokio::process::Command;

    // Use bluealsa-aplay to get proper device list with full format
    let output = Command::new("bluealsa-aplay")
        .args(&["--list-pcms"])
        .output()
        .await?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    
    // Check if specific MAC address is requested
    let target_device = get_target_device();
    
    // Look for bluealsa PCM device line (format: bluealsa:DEV=XX:XX:XX:XX:XX:XX,PROFILE=a2dp,SRV=...)
    for line in stdout.lines() {
        let line_trimmed = line.trim();
        if line_trimmed.starts_with("bluealsa:DEV=") {
            let device = line_trimmed.to_string();
            
            // If target MAC specified, check if this device matches
            if let Some(ref mac) = target_device {
                if device.contains(mac) {
                    let device_info = format!("{} (MAC: {})", device, mac);
                    info!("Found Bluetooth audio device {}", device_info);
                    return Ok(device);
                }
            } else {
                // Auto-discover: return first bluealsa device with a2dp profile
                if device.contains("PROFILE=a2dp") {
                    info!("Found Bluetooth audio device {} (auto-discovered)", device);
                    return Ok(device);
                }
            }
        }
    }

    let error_msg = if target_device.is_some() {
        format!("Bluetooth device with MAC {} not found in BlueALSA", target_device.unwrap())
    } else {
        "No Bluetooth A2DP audio source found in BlueALSA. Is your Bluetooth device connected and music playing?".to_string()
    };
    
    Err(error_msg.into())
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Initialize tracing
    tracing_subscriber::fmt()
        .with_target(false)
        .with_thread_ids(false)
        .with_level(true)
        .init();

    info!("🎵 BlueALSA AT-TT Turntable Audio Server (Rust)");
    info!("============================================================");

    // Create shared audio buffer
    let audio_buffer = AudioBuffer::new();

    // Start audio capture task
    let capture_buffer = audio_buffer.clone();
    tokio::spawn(async move {
        audio_capture_task(capture_buffer).await;
    });

    // Build HTTP router
    let app = Router::new()
        .route("/", get(info))
        .route("/stream", get(stream_audio))
        .route("/stream.wav", get(stream_audio))
        .route("/status", get(status))
        .with_state(audio_buffer.clone());

    // Start HTTP server
    let addr = format!("0.0.0.0:{}", SERVER_PORT);
    let listener = tokio::net::TcpListener::bind(&addr).await?;
    
    info!("🌐 HTTP server starting on port {}...", SERVER_PORT);
    info!("📱 Stream URL: http://[server-ip]:{}/stream", SERVER_PORT);
    info!("📊 Status URL: http://[server-ip]:{}/status", SERVER_PORT);
    
    if let Some(mac) = get_target_device() {
        info!("🎯 Targeting Bluetooth device: {}", mac);
    } else {
        info!("🔍 Auto-discovering first available Bluetooth A2DP source");
    }
    
    info!("");
    info!("🎧 Server is ready!");
    info!("   Press Ctrl+C to stop");

    // Setup signal handling
    let (tx, rx) = tokio::sync::oneshot::channel();
    let mut tx_opt = Some(tx);
    
    ctrlc::set_handler(move || {
        if let Some(tx) = tx_opt.take() {
            let _ = tx.send(());
        }
    })?;

    // Run server with graceful shutdown
    axum::serve(listener, app)
        .with_graceful_shutdown(async move {
            rx.await.ok();
            info!("🛑 Shutting down gracefully...");
        })
        .await?;

    info!("✅ Shutdown complete");
    Ok(())
}
