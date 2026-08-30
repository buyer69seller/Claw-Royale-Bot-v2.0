from typing import Dict
from ..api.client import APIClient
from ..utils.logger import logger

class LoadoutManager:
    def __init__(self):
        self.client = APIClient()
    
    async def configure_full_loadout(self) -> bool:
        """Full set = Main + Sub + 3 relics (WAJIB)"""
        try:
            loadout = await self.client.get_loadout()
            if loadout.get("error"):
                return False
            
            data = loadout.get("data", {})
            
            # Cek full set
            main = data.get("main")
            sub = data.get("sub")
            relics = data.get("relics", [])
            
            if main and sub and len(relics) >= 3:
                logger.info("✅ Full loadout ready")
                return True
            
            logger.warning(f"⚠️ Loadout not full: main={bool(main)}, sub={bool(sub)}, relics={len(relics)}/3")
            return False
            
        except Exception as e:
            logger.error(f"Loadout error: {e}")
            return False