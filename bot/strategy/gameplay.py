import random
import math
from typing import Dict, List, Optional, Any
from ..game.websocket import GameWebSocket
from ..utils.logger import logger

class GameStrategy:
    """
    Decision Engine untuk Claw Royale Bot
    """
    
    def __init__(self, websocket: GameWebSocket):
        self.websocket = websocket
        self.state = {}
        self.self_token = None
        self.targets = []
        self.monsters = []
        self.items = []
        self.ruins = []
        self.cave_id = None
        self.turn = 0
        self.is_dead = False
        self.last_action = None
        self.action_cooldown = 0
        self.no_action_count = 0  # Track jika tidak ada action
        
        # Konfigurasi threshold
        self.HP_DANGER_THRESHOLD = 0.30
        self.HP_SAFE_THRESHOLD = 0.60
        self.ENEMY_ATTACK_RANGE = 3
        self.ENEMY_DANGER_RANGE = 2
        self.COLLECT_RANGE = 2
        self.EXPLORE_RANGE = 2
        
    async def handle_message(self, data: Dict):
        """Handle incoming game messages"""
        msg_type = data.get("type")
        
        # ──────────────────────────────────────────────
        # 1. CEK MATI?
        # ──────────────────────────────────────────────
        if msg_type == "agent_died":
            meta = data.get("meta", {})
            agent_id = data.get("agentId")
            
            # 🔥 Cek apakah ini kematian sendiri
            if meta.get("youDied") == True:
                logger.info("💀 🔥 YOU DIED! Stopping run...")
                self.is_dead = True
                self.websocket.is_alive = False
                if self.websocket.on_game_ended:
                    self.websocket.on_game_ended()
                return
            else:
                # Kematian agent lain - log tapi lanjut
                logger.info(f"💀 Agent died: {agent_id}")
                # Refresh targets
                self.targets = []
                return
        
        if msg_type == "action_result":
            result = data.get("result", {})
            if not result.get("success"):
                error = result.get("error", {})
                error_code = error.get("code", "unknown")
                
                if error_code == "AGENT_DEAD":
                    logger.info("💀 🔥 YOU DIED! (via action_result)")
                    self.is_dead = True
                    self.websocket.is_alive = False
                    if self.websocket.on_game_ended:
                        self.websocket.on_game_ended()
                    return
                elif error_code == "TARGET_DEAD":
                    logger.debug("🎯 Target dead, refreshing...")
                    self.targets = []
                    await self._decide_action()
                    return
                elif error_code == "ACTION_FAILED":
                    logger.debug(f"❌ Action failed: {error.get('message')}")
                    await self._decide_action()
                    return
                elif error_code == "NOT_ENOUGH_EP":
                    logger.debug("⚡ Not enough EP, waiting...")
                    return
            else:
                # Action success
                self.no_action_count = 0
                logger.debug(f"✅ Action successful")
        
        # ──────────────────────────────────────────────
        # UPDATE STATE
        # ──────────────────────────────────────────────
        if msg_type == "agent_view":
            self.state = data.get("view", {})
            self._update_state()
            self.turn += 1
            
            # Log setiap 5 turn
            if self.turn % 5 == 0:
                self_section = self.state.get("self", {})
                hp = self_section.get("hp", 0)
                max_hp = self_section.get("maxHp", 100)
                ep = self_section.get("ep", 0)
                max_ep = self_section.get("maxEp", 50)
                pos = self_section.get("position", {})
                logger.info(f"📊 Turn {self.turn}: HP={hp}/{max_hp}, EP={ep}/{max_ep}, "
                           f"Pos=({pos.get('x',0)},{pos.get('y',0)}), "
                           f"Targets={len(self.targets)}, Items={len(self.items)}")
            
            # ── Can act? ──
            if not data.get("canAct", True):
                logger.debug("⏳ Cannot act this turn")
                return
            
            # ── DECISION ENGINE ──
            await self._decide_action()
        
        elif msg_type == "turn_advanced":
            self.turn += 1
            if self.action_cooldown > 0:
                self.action_cooldown -= 1
            
            # Log setiap 10 turn
            if self.turn % 10 == 0:
                logger.info(f"🔄 Turn {self.turn} advanced")
            
            if self.state.get("canAct", True):
                await self._decide_action()
    
    def _update_state(self):
        """Update internal state"""
        view = self.state
        self_section = view.get("self", {})
        
        self.self_token = self_section.get("id")
        self.cave_id = self_section.get("caveId")
        
        self.targets = view.get("visibleAgents", [])
        self.monsters = view.get("visibleMonsters", [])
        self.items = view.get("visibleItems", [])
        self.ruins = view.get("visibleRuins", [])
    
    async def _decide_action(self):
        """
        DECISION ENGINE:
        1. Saya mati? → STOP
        2. Bahaya tinggi? → bertahan/kabur
        3. Item aman? → collect
        4. Enemy menguntungkan? → attack
        5. Ruin aman? → explore
        6. Tidak ada tujuan? → move
        """
        try:
            if self.is_dead:
                return
            
            # ── 2. BAHAYA TINGGI ──
            if await self._handle_danger():
                return
            
            # ── 3. ITEM AMAN ──
            if await self._handle_collect():
                return
            
            # ── 4. ENEMY MENGUNTUNGKAN ──
            if await self._handle_attack():
                return
            
            # ── 5. RUIN AMAN ──
            if await self._handle_explore():
                return
            
            # ── 6. TIDAK ADA TUJUAN ──
            await self._handle_move()
            
        except Exception as e:
            logger.error(f"❌ Decision error: {e}")
            await self._move_random()
    
    # ──────────────────────────────────────────────────────────
    # 2. BAHAYA TINGGI
    # ──────────────────────────────────────────────────────────
    async def _handle_danger(self) -> bool:
        self_section = self.state.get("self", {})
        hp = self_section.get("hp", 100)
        max_hp = self_section.get("maxHp", 100)
        in_cave = self_section.get("inCave", False)
        
        # Escape cave
        if in_cave:
            logger.info("🚪 Escaping cave...")
            if self.cave_id:
                await self.websocket.send_action({
                    "type": "interact",
                    "interactableId": self.cave_id
                })
                return True
        
        # Low HP
        if hp < max_hp * self.HP_DANGER_THRESHOLD:
            logger.warning(f"⚠️ Low HP: {hp}/{max_hp}")
            
            # Try healing
            items = self_section.get("items", [])
            for item in items:
                item_type = item.get("type", "")
                if "heal" in item_type.lower() or "potion" in item_type.lower():
                    logger.info(f"💊 Using {item.get('name', 'item')}")
                    await self.websocket.send_action({
                        "type": "use_item",
                        "itemId": item.get("id")
                    })
                    return True
            
            # Run away
            logger.info("🏃 Running from danger")
            await self._move_away_from_danger()
            return True
        
        # Nearby enemy
        for target in self.targets:
            if target.get("distance", 999) < self.ENEMY_DANGER_RANGE:
                logger.info(f"⚠️ Enemy nearby - running")
                await self._move_away_from_danger()
                return True
        
        return False
    
    # ──────────────────────────────────────────────────────────
    # 3. COLLECT ITEMS
    # ──────────────────────────────────────────────────────────
    async def _handle_collect(self) -> bool:
        if not self.items:
            return False
        
        safe_items = [i for i in self.items if i.get("distance", 999) <= self.COLLECT_RANGE]
        
        if safe_items:
            nearest = min(safe_items, key=lambda x: x.get("distance", 999))
            logger.info(f"📦 Collecting {nearest.get('name', 'item')}")
            await self.websocket.send_action({
                "type": "collect",
                "itemId": nearest.get("id")
            })
            return True
        
        # Move towards nearest item
        nearest = min(self.items, key=lambda x: x.get("distance", 999))
        if nearest.get("distance", 999) < 5:
            logger.debug(f"🚶 Moving towards item")
            await self._move_towards(nearest.get("position"))
            return True
        
        return False
    
    # ──────────────────────────────────────────────────────────
    # 4. ATTACK
    # ──────────────────────────────────────────────────────────
    async def _handle_attack(self) -> bool:
        self_section = self.state.get("self", {})
        hp = self_section.get("hp", 100)
        max_hp = self_section.get("maxHp", 100)
        
        if hp < max_hp * self.HP_SAFE_THRESHOLD:
            return False
        
        all_targets = self.monsters + self.targets
        if not all_targets:
            return False
        
        viable = []
        for target in all_targets:
            dist = target.get("distance", 999)
            target_hp = target.get("hp", 100)
            if dist <= self.ENEMY_ATTACK_RANGE and target_hp < 50:
                viable.append(target)
        
        if not viable:
            return False
        
        viable.sort(key=lambda x: (x.get("hp", 100), x.get("distance", 999)))
        best = viable[0]
        
        logger.info(f"⚔️ Attacking {best.get('name', 'enemy')} (HP: {best.get('hp')})")
        await self.websocket.send_action({
            "type": "attack",
            "targetId": best.get("id")
        })
        return True
    
    # ──────────────────────────────────────────────────────────
    # 5. EXPLORE RUIN
    # ──────────────────────────────────────────────────────────
    async def _handle_explore(self) -> bool:
        if not self.ruins:
            return False
        
        self_section = self.state.get("self", {})
        hp = self_section.get("hp", 100)
        max_hp = self_section.get("maxHp", 100)
        
        if hp < max_hp * 0.5:
            return False
        
        for ruin in self.ruins:
            dist = ruin.get("distance", 999)
            explored = ruin.get("explored", 0)
            
            if dist <= self.EXPLORE_RANGE and explored < 3:
                logger.info(f"🏛️ Exploring ruin ({explored}/3)")
                await self.websocket.send_action({
                    "type": "explore",
                    "ruinId": ruin.get("id")
                })
                return True
        
        nearest = min(self.ruins, key=lambda x: x.get("distance", 999))
        if nearest.get("distance", 999) < 5:
            logger.debug(f"🚶 Moving towards ruin")
            await self._move_towards(nearest.get("position"))
            return True
        
        return False
    
    # ──────────────────────────────────────────────────────────
    # 6. MOVE
    # ──────────────────────────────────────────────────────────
    async def _handle_move(self):
        logger.debug("🚶 Moving - no specific goal")
        
        # Move towards nearest item or ruin
        if self.items:
            nearest = min(self.items, key=lambda x: x.get("distance", 999))
            if nearest.get("distance", 999) < 8:
                await self._move_towards(nearest.get("position"))
                return
        
        if self.ruins:
            nearest = min(self.ruins, key=lambda x: x.get("distance", 999))
            if nearest.get("distance", 999) < 8:
                await self._move_towards(nearest.get("position"))
                return
        
        await self._move_random()
    
    # ──────────────────────────────────────────────────────────
    # MOVEMENT HELPERS
    # ──────────────────────────────────────────────────────────
    async def _move_away_from_danger(self):
        self_section = self.state.get("self", {})
        position = self_section.get("position", {})
        
        all_targets = self.monsters + self.targets
        nearest = min(all_targets, key=lambda x: x.get("distance", 999)) if all_targets else None
        
        if nearest and nearest.get("position"):
            enemy_pos = nearest.get("position")
            dx = position.get("x", 0) - enemy_pos.get("x", 0)
            dy = position.get("y", 0) - enemy_pos.get("y", 0)
            
            if abs(dx) > abs(dy):
                direction = "right" if dx > 0 else "left"
            else:
                direction = "down" if dy > 0 else "up"
        else:
            directions = ["up", "down", "left", "right"]
            direction = random.choice(directions)
        
        await self.websocket.send_action({"type": "move", "direction": direction})
    
    async def _move_towards(self, target_pos: Dict):
        self_section = self.state.get("self", {})
        position = self_section.get("position", {})
        
        dx = target_pos.get("x", 0) - position.get("x", 0)
        dy = target_pos.get("y", 0) - position.get("y", 0)
        
        if abs(dx) > abs(dy):
            direction = "right" if dx > 0 else "left"
        else:
            direction = "down" if dy > 0 else "up"
        
        await self.websocket.send_action({"type": "move", "direction": direction})
    
    async def _move_random(self):
        directions = ["up", "down", "left", "right"]
        direction = random.choice(directions)
        logger.debug(f"🚶 Moving {direction} (random)")
        await self.websocket.send_action({"type": "move", "direction": direction})
