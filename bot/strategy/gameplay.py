import random
import math
from typing import Dict, List, Optional
from ..game.websocket import GameWebSocket
from ..utils.logger import logger

class GameStrategy:
    def __init__(self, websocket: GameWebSocket):
        self.websocket = websocket
        self.state = {}
        self.targets = []
        self.monsters = []
        self.items = []
        self.ruins = []
        self.cave_id = None
        self.turn = 0
        self.safe_positions = []
        self.death_zone_radius = 10  # Default, akan diupdate dari game
        
    async def handle_message(self, data: Dict):
        """Handle incoming game messages"""
        msg_type = data.get("type")
        
        if msg_type == "agent_view":
            self.state = data.get("view", {})
            self._update_state()
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
                elif error.get("code") == "AGENT_DEAD":
                    logger.info("💀 You are dead!")
                    self.websocket.is_alive = False
    
    def _update_state(self):
        """Update internal state dari agent_view"""
        view = self.state
        self.self_token = view.get("self", {}).get("id")
        
        # Update visible entities
        self.targets = view.get("visibleAgents", [])
        self.monsters = view.get("visibleMonsters", [])
        self.items = view.get("visibleItems", [])
        self.ruins = view.get("visibleRuins", [])
        
        # Check if in cave
        in_cave = view.get("self", {}).get("inCave", False)
        if in_cave:
            logger.debug("📍 Inside cave - need to escape")
        
        # Update death zone info jika ada
        if "deathZone" in view:
            self.death_zone_radius = view.get("deathZone", {}).get("radius", 10)
    
    async def _decide_action(self):
        """
        Decision tree untuk gameplay:
        1. Survival check (HP, danger, cave)
        2. Collect loot
        3. Explore ruins
        4. Fight
        5. Reposition / Move
        """
        try:
            self_state = self.state.get("self", {})
            hp = self_state.get("hp", 100)
            max_hp = self_state.get("maxHp", 100)
            in_cave = self_state.get("inCave", False)
            position = self_state.get("position", {})
            
            # ========================================
            # 1. SURVIVAL CHECK
            # ========================================
            
            # 1a. Auto keluar cave
            if in_cave:
                logger.info("🚪 Exiting cave...")
                await self._exit_cave()
                return
            
            # 1b. Low HP - cari healing
            if hp < max_hp * 0.3:
                logger.warning(f"⚠️ Low HP: {hp}/{max_hp}")
                # Cek inventory untuk healing
                items = self_state.get("items", [])
                for item in items:
                    if item.get("type") == "heal" or "potion" in item.get("name", "").lower():
                        logger.info(f"💊 Using healing item: {item.get('name')}")
                        await self.websocket.send_action({
                            "type": "use_item",
                            "itemId": item.get("id")
                        })
                        return
            
            # 1c. Reposition untuk survival (jauh dari death zone)
            if await self._should_reposition():
                logger.info("📍 Repositioning for survival...")
                await self._move_away_from_danger()
                return
            
            # ========================================
            # 2. COLLECT LOOT (Auto Loot)
            # ========================================
            
            if self.items:
                nearest_item = min(self.items, key=lambda x: x.get("distance", 999))
                if nearest_item.get("distance", 999) < 2:
                    logger.info(f"📦 Collecting {nearest_item.get('name', 'item')}")
                    await self.websocket.send_action({
                        "type": "collect",
                        "itemId": nearest_item.get("id")
                    })
                    return
            
            # ========================================
            # 3. EXPLORE RUINS (Auto Explore)
            # ========================================
            
            if self.ruins:
                nearest_ruin = min(self.ruins, key=lambda x: x.get("distance", 999))
                if nearest_ruin.get("distance", 999) < 2:
                    # Cek apakah ruin belum fully explored
                    if nearest_ruin.get("explored", 0) < 3:
                        logger.info(f"🏛️ Exploring ruin at distance {nearest_ruin.get('distance')}")
                        await self.websocket.send_action({
                            "type": "explore",
                            "ruinId": nearest_ruin.get("id")
                        })
                        return
                else:
                    # Move closer to ruin
                    await self._move_towards(nearest_ruin.get("position"))
                    return
            
            # ========================================
            # 4. FIGHT (Auto Attack)
            # ========================================
            
            # 4a. Fight monsters
            if self.monsters and self._should_fight():
                nearest_monster = min(self.monsters, key=lambda x: x.get("distance", 999))
                if nearest_monster.get("distance", 999) < 3:
                    logger.info(f"⚔️ Attacking monster: {nearest_monster.get('name', 'unknown')}")
                    await self.websocket.send_action({
                        "type": "attack",
                        "targetId": nearest_monster.get("id")
                    })
                    return
            
            # 4b. Fight other agents (if strong enough)
            if self.targets and self._should_fight_agent():
                best_target = self._get_best_target()
                if best_target and best_target.get("distance", 999) < 4:
                    logger.info(f"⚔️ Attacking agent: {best_target.get('name', 'unknown')}")
                    await self.websocket.send_action({
                        "type": "attack",
                        "targetId": best_target.get("id")
                    })
                    return
            
            # ========================================
            # 5. REPOSITION / MOVE
            # ========================================
            
            await self._move_strategic()
            
        except Exception as e:
            logger.error(f"Decision error: {e}")
            # Fallback: move random
            await self._move_random()
    
    # ========================================
    # SURVIVAL METHODS
    # ========================================
    
    async def _exit_cave(self):
        """Auto keluar dari cave"""
        if self.cave_id:
            await self.websocket.send_action({
                "type": "interact",
                "interactableId": self.cave_id
            })
            self.cave_id = None
        else:
            # Cari cave terdekat untuk exit
            for interactable in self.state.get("visibleInteractables", []):
                if interactable.get("type") == "cave":
                    await self.websocket.send_action({
                        "type": "interact",
                        "interactableId": interactable.get("id")
                    })
                    break
    
    async def _should_reposition(self) -> bool:
        """Cek apakah perlu reposition untuk survival"""
        self_state = self.state.get("self", {})
        position = self_state.get("position", {})
        
        # Cek death zone
        if "deathZone" in self.state:
            dz = self.state.get("deathZone", {})
            center = dz.get("center", {})
            radius = dz.get("radius", 10)
            
            # Hitung jarak ke center death zone
            dx = position.get("x", 0) - center.get("x", 0)
            dy = position.get("y", 0) - center.get("y", 0)
            distance = math.sqrt(dx*dx + dy*dy)
            
            # Jika di luar radius, harus pindah ke dalam
            if distance > radius - 2:
                logger.debug(f"⚠️ Outside death zone: {distance:.1f} > {radius}")
                return True
        
        # Cek nearby threats
        for target in self.targets:
            if target.get("distance", 999) < 2:
                return True
        
        return False
    
    async def _move_away_from_danger(self):
        """Bergerak menjauh dari danger zone"""
        self_state = self.state.get("self", {})
        position = self_state.get("position", {})
        
        # Cari arah ke center death zone
        if "deathZone" in self.state:
            dz = self.state.get("deathZone", {})
            center = dz.get("center", {})
            
            dx = center.get("x", 0) - position.get("x", 0)
            dy = center.get("y", 0) - position.get("y", 0)
            
            # Pilih arah ke center
            if abs(dx) > abs(dy):
                direction = "right" if dx > 0 else "left"
            else:
                direction = "down" if dy > 0 else "up"
            
            await self.websocket.send_action({
                "type": "move",
                "direction": direction
            })
        else:
            await self._move_random()
    
    # ========================================
    # COMBAT METHODS
    # ========================================
    
    def _should_fight(self) -> bool:
        """Cek apakah sebaiknya fight monster"""
        self_state = self.state.get("self", {})
        hp = self_state.get("hp", 100)
        max_hp = self_state.get("maxHp", 100)
        
        if hp < max_hp * 0.4:
            return False
        
        for monster in self.monsters[:3]:
            if monster.get("hp", 100) < 30 and monster.get("distance", 999) < 3:
                return True
        return False
    
    def _should_fight_agent(self) -> bool:
        """Cek apakah sebaiknya fight agent"""
        self_state = self.state.get("self", {})
        hp = self_state.get("hp", 100)
        max_hp = self_state.get("maxHp", 100)
        
        if hp < max_hp * 0.6:
            return False
        
        for target in self.targets[:3]:
            if target.get("hp", 100) < 40 and target.get("distance", 999) < 3:
                return True
        return False
    
    def _get_best_target(self) -> Optional[Dict]:
        """Dapatkan target terbaik untuk diserang"""
        best = None
        best_score = -1
        
        all_targets = self.monsters + self.targets
        for target in all_targets:
            distance = target.get("distance", 999)
            if distance > 4:
                continue
            hp = target.get("hp", 100)
            score = (100 - hp) / (1 + distance)
            if score > best_score:
                best_score = score
                best = target
        
        return best
    
    # ========================================
    # MOVEMENT METHODS
    # ========================================
    
    async def _move_strategic(self):
        """Bergerak secara strategis"""
        self_state = self.state.get("self", {})
        position = self_state.get("position", {})
        
        # Priority: loot > ruin > random
        if self.items:
            nearest = min(self.items, key=lambda x: x.get("distance", 999))
            if nearest.get("distance", 999) < 5:
                await self._move_towards(nearest.get("position"))
                return
        
        if self.ruins:
            nearest = min(self.ruins, key=lambda x: x.get("distance", 999))
            if nearest.get("distance", 999) < 5:
                await self._move_towards(nearest.get("position"))
                return
        
        # Random movement
        await self._move_random()
    
    async def _move_towards(self, target_pos: Dict):
        """Bergerak menuju posisi target"""
        self_state = self.state.get("self", {})
        position = self_state.get("position", {})
        
        dx = target_pos.get("x", 0) - position.get("x", 0)
        dy = target_pos.get("y", 0) - position.get("y", 0)
        
        if abs(dx) > abs(dy):
            direction = "right" if dx > 0 else "left"
        else:
            direction = "down" if dy > 0 else "up"
        
        await self.websocket.send_action({
            "type": "move",
            "direction": direction
        })
    
    async def _move_random(self):
        """Bergerak random"""
        directions = ["up", "down", "left", "right"]
        direction = random.choice(directions)
        await self.websocket.send_action({
            "type": "move",
            "direction": direction
        })
