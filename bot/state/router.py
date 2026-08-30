from enum import Enum
from typing import Optional, Dict
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
            
            # Check slots
            free_live = any(
                g.get("entryType") == "free" and g.get("isAlive") == True
                for g in games
            )
            
            paid_live = any(
                g.get("entryType") == "paid" and g.get("isAlive") == True
                for g in games
            )
            
            readiness = data.get("readiness", {})
            free_ready = readiness.get("freeReady", False)
            paid_ready = readiness.get("paidReady", False)
            
            # Log changes
            current = f"free={free_ready}, paid={paid_ready}"
            if current != self.last_readiness:
                logger.info(f"📊 Readiness: freeReady={free_ready}, paidReady={paid_ready}")
                self.last_readiness = current
            
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
            
            return self.state
            
        except Exception as e:
            logger.error(f"State error: {e}")
            self.state = AgentState.ERROR
            return self.state