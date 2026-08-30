import random
from typing import Dict
from ..game.websocket import GameWebSocket
from ..utils.logger import logger

class GameStrategy:
    def __init__(self, websocket: GameWebSocket):
        self.websocket = websocket
        self.state = {}
        self.targets = []
        self.turn = 0
        
    async def handle_message(self, data: Dict):
        msg_type = data.get("type")
        
        if msg_type == "agent_view":
            self.state = data.get("view", {})
            self.targets = self.state.get("visibleAgents", [])
            await self._decide_action()
            
        elif msg_type == "turn_advanced":
            self.turn += 1
            await self._decide_action()
            
        elif msg_type == "action_result":
            result = data.get("result", {})
            if not result.get("success"):
                error = result.get("error", {})
                if error.get("code") == "TARGET_DEAD":
                    logger.debug("Target dead, retrying...")
                    self.targets = []
                    await self._decide_action()
    
    async def _decide_action(self):
        try:
            # 1. Survival - if low HP, heal or run
            if self._in_danger():
                await self._move_random()
                return
            
            # 2. Fight - if target nearby
            if self.targets and self._should_fight():
                await self._handle_fight()
                return
            
            # 3. Explore - move random
            await self._move_random()
            
        except Exception as e:
            logger.error(f"Action error: {e}")
    
    def _in_danger(self) -> bool:
        hp = self.state.get("self", {}).get("hp", 100)
        max_hp = self.state.get("self", {}).get("maxHp", 100)
        return hp < max_hp * 0.3
    
    def _should_fight(self) -> bool:
        hp = self.state.get("self", {}).get("hp", 100)
        max_hp = self.state.get("self", {}).get("maxHp", 100)
        if hp < max_hp * 0.5:
            return False
        for target in self.targets[:3]:
            if target.get("hp", 100) < 50 and target.get("distance", 999) < 5:
                return True
        return False
    
    async def _handle_fight(self):
        best = None
        best_score = -1
        for target in self.targets:
            dist = target.get("distance", 999)
            if dist > 5:
                continue
            score = (100 - target.get("hp", 100)) / (1 + dist)
            if score > best_score:
                best_score = score
                best = target
        
        if best:
            await self.websocket.send_action({
                "type": "attack",
                "targetId": best.get("id")
            })
    
    async def _move_random(self):
        directions = ["up", "down", "left", "right"]
        await self.websocket.send_action({
            "type": "move",
            "direction": random.choice(directions)
        })