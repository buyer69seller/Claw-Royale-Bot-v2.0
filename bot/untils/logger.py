import logging
import sys
import os
from datetime import datetime
from pathlib import Path

def setup_logger():
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, log_level, logging.INFO)
    
    handlers = [logging.StreamHandler(sys.stdout)]
    
    try:
        log_dir = os.getenv("DATA_PATH", "/app/data")
        log_path = Path(log_dir) / "logs"
        log_path.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path / f'bot_{datetime.now().strftime("%Y%m%d")}.log'))
    except:
        pass
    
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers,
        force=True
    )
    
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    
    return logging.getLogger("claw-royale-bot")

logger = logging.getLogger("claw-royale-bot")