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

async def main():
    setup_logger()
    
    print("\n" + "=" * 60)
    print("🦞 CLAW ROYALE AI BOT v2.0")
    print("=" * 60)
    
    # Cek environment
    if os.getenv("RAILWAY_ENVIRONMENT"):
        print("🏗️  Running on Railway Platform")
        print(f"📦 Service: {os.getenv('RAILWAY_SERVICE_NAME', 'unknown')}")
        print("=" * 60)
    
    # Validasi API_KEY
    if not Config.validate():
        print("\n⚠️  BOT CANNOT START - Invalid configuration")
        print("\nPlease add these variables in Railway:")
        print("  - API_KEY: your_api_key_here")
        print("  - AGENT_NAME: MyBotName (optional)")
        print("=" * 60 + "\n")
        sys.exit(1)
    
    # Buat direktori data
    Config.ensure_directories()
    
    # Tampilkan konfigurasi
    if os.getenv("LOG_LEVEL", "INFO") == "DEBUG":
        Config.print_config()
    
    print("\n" + "=" * 60)
    print("🤖 Bot is starting...")
    print("📌 Auto-join: ENABLED")
    print("📌 Auto-rejoin: ENABLED")
    print("📌 Room Mode: " + Config.ROOM_MODE)
    print("=" * 60 + "\n")
    
    # Start heartbeat
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