#!/usr/bin/env python3
import asyncio
import sys
import signal
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.heartbeat import Heartbeat
from bot.utils.logger import setup_logger
from bot.config import Config

# Health check server (sederhana)
try:
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import threading
    
    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/health':
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"status": "healthy"}')
            else:
                self.send_response(404)
                self.end_headers()
        
        def log_message(self, format, *args):
            pass  # Silent log
    
    def start_health_server():
        try:
            port = Config.WEB_PORT
            server = HTTPServer(('0.0.0.0', port), HealthHandler)
            server.serve_forever()
        except Exception as e:
            print(f"⚠️ Health server error: {e}")
    
    HEALTH_SERVER_STARTED = False
except ImportError:
    HEALTH_SERVER_STARTED = True

async def main():
    setup_logger()
    
    print("\n" + "=" * 60)
    print("🦞 CLAW ROYALE AI BOT v6 - ADAPTIVE AI")
    print("=" * 60)
    
    if os.getenv("RAILWAY_ENVIRONMENT"):
        print("🏗️  Running on Railway Platform")
        print(f"📦 Service: {os.getenv('RAILWAY_SERVICE_NAME', 'unknown')}")
        print("=" * 60)
    
    if not Config.validate():
        print("\n⚠️  BOT CANNOT START - Invalid configuration")
        print("\nPlease add these variables in Railway:")
        print("  - API_KEY: your_api_key_here")
        print("=" * 60 + "\n")
        sys.exit(1)
    
    Config.ensure_directories()
    
    # Start health check server di background
    try:
        import threading
        if not HEALTH_SERVER_STARTED:
            health_thread = threading.Thread(target=start_health_server, daemon=True)
            health_thread.start()
            print(f"🌐 Health check: http://0.0.0.0:{Config.WEB_PORT}/health")
    except Exception as e:
        print(f"⚠️ Health server: {e}")
    
    print("\n" + "=" * 60)
    print("🤖 Bot is starting...")
    print("📌 Engine: Adaptive AI v6")
    print("📌 Scoring System: ENABLED")
    print("📌 Auto-rejoin: ENABLED")
    print("📌 Room Mode: " + Config.ROOM_MODE)
    print("=" * 60 + "\n")
    
    heartbeat = Heartbeat()
    
    def shutdown_handler():
        heartbeat.running = False
        print("\n👋 Shutting down...")
    
    signal.signal(signal.SIGINT, lambda s, f: shutdown_handler())
    signal.signal(signal.SIGTERM, lambda s, f: shutdown_handler())
    
    try:
        await heartbeat.run()
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")
    except Exception as e:
        print(f"❌ Bot error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
