from enum import Enum
from ..api.client import APIClient
from ..utils.logger import logger

class AgentState(Enum):
    NO_ACCOUNT = "no_account"
    READY_FREE = "ready_free"
    READY_PAID = "ready_paid"
    IN_GAME_FREE = "in_game_free"
    IN_GAME_PAID = "in_game_paid"
    IDLE = "idle"
    ERROR = "error"

class StateRouter:
    def __init__(self):
        self.client = APIClient()
        self.state = AgentState.IDLE
        self.last_readiness = None
        
    async def check_state(self) -> AgentState:
        try:
            if not self.client._has_api_key():
                self.state = AgentState.NO_ACCOUNT
                return self.state
            
            if not self.client.is_logged_in:
                self.state = AgentState.NO_ACCOUNT
                return self.state
            
            account = await self.client.get_account()
            
            if not account or account.get("error") or "data" not in account:
                self.state = AgentState.NO_ACCOUNT
                return self.state
            
            data = account.get("data", {})
            games = data.get("currentGames", [])
            
            # Cek game slots
            free_live = any(g.get("entryType") == "free" and g.get("isAlive") == True for g in games)
            paid_live = any(g.get("entryType") == "paid" and g.get("isAlive") == True for g in games)
            
            readiness = data.get("readiness", {})
            free_ready = readiness.get("freeReady")  # Bisa None
            paid_ready = readiness.get("paidReady", False)
            
            # Log perubahan readiness
            current_readiness = f"free={free_ready}, paid={paid_ready}"
            if current_readiness != self.last_readiness:
                if free_ready is None:
                    logger.warning(f"📊 Readiness: freeReady=None (may need setup), paidReady={paid_ready}")
                else:
                    logger.info(f"📊 Readiness: freeReady={free_ready}, paidReady={paid_ready}")
                self.last_readiness = current_readiness
            
            # Jika freeReady None, treat sebagai False tapi catat
            if free_ready is None:
                logger.debug("   ℹ️ freeReady is None - treating as not ready")
                free_ready = False
            
            # Determine state (prioritas: IN_GAME > READY > IDLE)
            if free_live:
                self.state = AgentState.IN_GAME_FREE
                logger.info("📌 IN_GAME_FREE")
            elif paid_live:
                self.state = AgentState.IN_GAME_PAID
                logger.info("📌 IN_GAME_PAID")
            elif free_ready:
                self.state = AgentState.READY_FREE
                logger.info("✅ READY_FREE")
            elif paid_ready:
                self.state = AgentState.READY_PAID
                logger.info("✅ READY_PAID")
            else:
                self.state = AgentState.IDLE
                logger.info("💤 IDLE")
                
                # Debug: kenapa tidak ready
                if not free_live and not free_ready:
                    logger.debug("   - Free not ready: may need setup or whitelist")
                if not paid_live and not paid_ready:
                    logger.debug("   - Paid not ready: check prerequisites")
            
            return self.state
            
        except Exception as e:
            logger.error(f"State error: {e}")
            self.state = AgentState.ERROR
            return self.state
