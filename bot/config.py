import os
import logging
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

class Config:
    # API Configuration
    BASE_URL = os.getenv("API_BASE_URL", "https://cdn.clawroyale.ai/api")
    WS_JOIN_URL = os.getenv("WS_JOIN_URL", "wss://cdn.clawroyale.ai/ws/join")
    WS_AGENT_URL = os.getenv("WS_AGENT_URL", "wss://cdn.clawroyale.ai/ws/agent")
    
    BASE_URLS = [
        "https://cdn.clawroyale.ai/api",
        "https://cdn.moltyroyale.com/api",
        "https://api.clawroyale.ai/api"
    ]
    
    # Authentication
    API_KEY = os.getenv("API_KEY")
    
    @classmethod
    def validate(cls):
        if not cls.API_KEY:
            logging.error("❌ API_KEY is not set!")
            return False
        return True
    
    # Bot Settings
    AGENT_NAME = os.getenv("AGENT_NAME", "ClawBot")
    # ROOM_MODE: free | paid | auto (auto = paid fallback to free)
    ROOM_MODE = os.getenv("ROOM_MODE", "auto")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    
    # Railway
    RAILWAY_API_TOKEN = os.getenv("RAILWAY_API_TOKEN")
    RAILWAY_ENVIRONMENT = os.getenv("RAILWAY_ENVIRONMENT", "production")
    
    # Storage
    BASE_PATH = os.getenv("DATA_PATH", "/app/data")
    
    @classmethod
    def ensure_directories(cls):
        dirs = [cls.BASE_PATH, f"{cls.BASE_PATH}/cache", f"{cls.BASE_PATH}/logs"]
        for d in dirs:
            Path(d).mkdir(parents=True, exist_ok=True)
    
    VERSION_CACHE_FILE = f"{BASE_PATH}/cache/version_cache.json"
    
    # Web Dashboard
    WEB_PORT = int(os.getenv("WEB_PORT", 8080))
    WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
    
    @classmethod
    def get_all(cls):
        return {
            "API_KEY": cls.API_KEY[:8] + "..." if cls.API_KEY else None,
            "AGENT_NAME": cls.AGENT_NAME,
            "ROOM_MODE": cls.ROOM_MODE,
            "LOG_LEVEL": cls.LOG_LEVEL,
            "BASE_URL": cls.BASE_URL,
            "WEB_PORT": cls.WEB_PORT,
        }
