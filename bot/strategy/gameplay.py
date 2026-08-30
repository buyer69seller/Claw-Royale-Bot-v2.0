import random
import math
from typing import Dict, List, Optional, Any
from ..game.websocket import GameWebSocket
from ..utils.logger import logger

class GameStrategy:
    """
    Decision Engine untuk Claw Royale Bot
    Berdasarkan diagram loop utama:
    1. Cek mati? → STOP
    2. Can act? → tunggu
    3. Bahaya tinggi? → bertahan/kabur
    4. Item aman? → collect
    5. Enemy menguntungkan? → attack
    6. Ruin aman? → explore
    7. Tidak ada tujuan? → move
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
        
        # Konfigurasi threshold
        self.HP_DANGER_THRESHOLD = 0.30   # 30% HP = danger
        self.HP_SAFE_THRESHOLD = 0.60     # 60% HP = safe to fight
        self.ENEMY_ATTACK_RANGE = 3       # Jarak attack
        self.ENEMY_DANGER_RANGE = 2       # Jarak danger
        self.COLLECT_RANGE = 2            # Jarak collect
        self.EXPLORE_RANGE = 2            # Jarak explore
        self.MAX_ATTACK_TARGETS = 3       # Max target yang dipertimbangkan
        
    async def handle_message(self, data: Dict):
        """Handle incoming game messages"""
        msg_type = data.get("type")
        
        # ──────────────────────────────────────────────
        # 1. CEK MATI? → STOP RUN
        # ──────────────────────────────────────────────
        if msg_type == "agent_died":
            meta = data.get("meta", {})
            if meta.get("youDied") == True:
                logger.info("💀 🔥 YOU DIED! Stopping run...")
                self.is_dead = True
                self.websocket.is_alive = False
                # Notify heartbeat bahwa game ended
                if self.websocket.on_game_ended:
                    self.websocket.on_game_ended()
                return
        
        if msg_type == "action_result":
            result = data.get("result", {})
            if not result.get("success"):
                error = result.get("error", {})
                if error.get("code") == "AGENT_DEAD":
                    logger.info("💀 🔥 YOU DIED! (via action_result)")
                    self.is_dead = True
                    self.websocket.is_alive = False
                    if self.websocket.on_game_ended:
                        self.websocket.on_game_ended()
                    return
                elif error.get("code") == "TARGET_DEAD":
                    logger.debug("Target dead, refreshing targets...")
                    self.targets = []
                    await self._decide_action()
                    return
                elif error.get("code") == "ACTION_FAILED":
                    logger.debug(f"Action failed: {error.get('message')}")
                    # Coba action lain
                    await self._decide_action()
                    return
        
        # ──────────────────────────────────────────────
        # UPDATE STATE
        # ──────────────────────────────────────────────
        if msg_type == "agent_view":
            self.state = data.get("view", {})
            self._update_state()
            self.turn += 1
            
            # ──────────────────────────────────────────────
            # 2. CAN ACT? → tidak → tunggu
            # ──────────────────────────────────────────────
            if not data.get("canAct", True):
                logger.debug("⏳ Cannot act this turn, waiting...")
                return
            
            # ──────────────────────────────────────────────
            # DECISION ENGINE
            # ──────────────────────────────────────────────
            await self._decide_action()
        
        elif msg_type == "turn_advanced":
            self.turn += 1
            if self.action_cooldown > 0:
                self.action_cooldown -= 1
            
            # Cek can act dari state terakhir
            if self.state.get("canAct", True):
                await self._decide_action()
    
    def _update_state(self):
        """Update internal state dari agent_view"""
        view = self.state
        self_section = view.get("self", {})
        
        # Self info
        self.self_token = self_section.get("id")
        self.cave_id = self_section.get("caveId")
        
        # Visible entities
        self.targets = view.get("visibleAgents", [])
        self.monsters = view.get("visibleMonsters", [])
        self.items = view.get("visibleItems", [])
        self.ruins = view.get("visibleRuins", [])
        
        # Debug log setiap 10 turn
        if self.turn % 10 == 0:
            hp = self_section.get("hp", 0)
            max_hp = self_section.get("maxHp", 100)
            ep = self_section.get("ep", 0)
            max_ep = self_section.get("maxEp", 50)
            logger.debug(f"📊 Turn {self.turn}: HP={hp}/{max_hp}, EP={ep}/{max_ep}, "
                        f"Targets={len(self.targets)}, Monsters={len(self.monsters)}, "
                        f"Items={len(self.items)}, Ruins={len(self.ruins)}")
    
    async def _decide_action(self):
        """
        ┌───────────────────────────────────────────────┐
        │ DECISION ENGINE                              │
        │                                               │
        │ 1. Saya mati? → STOP RUN                     │
        │ 2. Can act? → tidak → tunggu                 │
        │ 3. Bahaya tinggi? → bertahan / kabur         │
        │ 4. Item aman di sekitar? → collect           │
        │ 5. Enemy menguntungkan? → attack             │
        │ 6. Ruin aman? → explore                      │
        │ 7. Tidak ada tujuan? → move                  │
        └───────────────────────────────────────────────┘
        """
        try:
            # ──────────────────────────────────────────────
            # 1. CEK MATI (sudah di handle_message)
            # ──────────────────────────────────────────────
            if self.is_dead:
                return
            
            # ──────────────────────────────────────────────
            # 3. BAHAYA TINGGI? → BERTAHAN / KABUR
            # ──────────────────────────────────────────────
            if await self._handle_danger():
                return
            
            # ──────────────────────────────────────────────
            # 4. ITEM AMAN DI SEKITAR? → COLLECT
            # ──────────────────────────────────────────────
            if await self._handle_collect():
                return
            
            # ──────────────────────────────────────────────
            # 5. ENEMY MENGUNTUNGKAN? → ATTACK
            # ──────────────────────────────────────────────
            if await self._handle_attack():
                return
            
            # ──────────────────────────────────────────────
            # 6. RUIN AMAN? → EXPLORE
            # ──────────────────────────────────────────────
            if await self._handle_explore():
                return
            
            # ──────────────────────────────────────────────
            # 7. TIDAK ADA TUJUAN? → MOVE
            # ──────────────────────────────────────────────
            await self._handle_move()
            
        except Exception as e:
            logger.error(f"❌ Decision error: {e}")
            # Fallback: move random
            await self._move_random()
    
    # ──────────────────────────────────────────────────────────
    # 3. BAHAYA TINGGI? → BERTAHAN / KABUR
    # ──────────────────────────────────────────────────────────
    async def _handle_danger(self) -> bool:
        """Handle danger: low HP, nearby threats, cave trap"""
        self_section = self.state.get("self", {})
        hp = self_section.get("hp", 100)
        max_hp = self_section.get("maxHp", 100)
        in_cave = self_section.get("inCave", False)
        position = self_section.get("position", {})
        
        # ── 3a. Escape cave ──
        if in_cave:
            logger.info("🚪 Escaping cave...")
            if self.cave_id:
                await self.websocket.send_action({
                    "type": "interact",
                    "interactableId": self.cave_id
                })
                return True
        
        # ── 3b. Low HP → heal atau kabur ──
        if hp < max_hp * self.HP_DANGER_THRESHOLD:
            logger.warning(f"⚠️ Low HP: {hp}/{max_hp}")
            
            # Coba healing items
            items = self_section.get("items", [])
            for item in items:
                item_type = item.get("type", "")
                if "heal" in item_type.lower() or "potion" in item_type.lower():
                    logger.info(f"💊 Using healing item: {item.get('name', 'item')}")
                    await self.websocket.send_action({
                        "type": "use_item",
                        "itemId": item.get("id")
                    })
                    return True
            
            # Kabur dari danger
            logger.info("🏃 Running from danger...")
            await self._move_away_from_danger()
            return True
        
        # ── 3c. Nearby danger ──
        for target in self.targets:
            if target.get("distance", 999) < self.ENEMY_DANGER_RANGE:
                logger.info(f"⚠️ Enemy nearby at {target.get('distance')} - running...")
                await self._move_away_from_danger()
                return True
        
        return False
    
    # ──────────────────────────────────────────────────────────
    # 4. ITEM AMAN DI SEKITAR? → COLLECT
    # ──────────────────────────────────────────────────────────
    async def _handle_collect(self) -> bool:
        """Collect items if safe"""
        if not self.items:
            return False
        
        # Cari item terdekat yang aman
        safe_items = []
        for item in self.items:
            dist = item.get("distance", 999)
            if dist <= self.COLLECT_RANGE:
                safe_items.append(item)
        
        if safe_items:
            # Urutkan berdasarkan jarak
            safe_items.sort(key=lambda x: x.get("distance", 999))
            nearest = safe_items[0]
            
            logger.info(f"📦 Collecting {nearest.get('name', 'item')} at distance {nearest.get('distance')}")
            await self.websocket.send_action({
                "type": "collect",
                "itemId": nearest.get("id")
            })
            return True
        
        # Jika item tidak dalam range, move towards nearest
        nearest_item = min(self.items, key=lambda x: x.get("distance", 999))
        if nearest_item.get("distance", 999) < 5:
            logger.info(f"🚶 Moving towards item at distance {nearest_item.get('distance')}")
            await self._move_towards(nearest_item.get("position"))
            return True
        
        return False
    
    # ──────────────────────────────────────────────────────────
    # 5. ENEMY MENGUNTUNGKAN? → ATTACK
    # ──────────────────────────────────────────────────────────
    async def _handle_attack(self) -> bool:
        """Attack if enemy is vulnerable"""
        self_section = self.state.get("self", {})
        hp = self_section.get("hp", 100)
        max_hp = self_section.get("maxHp", 100)
        
        # Tidak attack jika HP rendah
        if hp < max_hp * self.HP_SAFE_THRESHOLD:
            return False
        
        # Gabungkan semua target (monsters + agents)
        all_targets = self.monsters + self.targets
        
        if not all_targets:
            return False
        
        # Filter target yang menguntungkan
        viable_targets = []
        for target in all_targets:
            dist = target.get("distance", 999)
            target_hp = target.get("hp", 100)
            
            # Target dalam range dan HP rendah
            if dist <= self.ENEMY_ATTACK_RANGE and target_hp < 50:
                viable_targets.append(target)
        
        if not viable_targets:
            return False
        
        # Pilih target terbaik (HP terendah, jarak terdekat)
        viable_targets.sort(
            key=lambda x: (x.get("hp", 100), x.get("distance", 999))
        )
        best = viable_targets[0]
        
        logger.info(f"⚔️ Attacking {best.get('name', 'enemy')} (HP: {best.get('hp', 0)}) at distance {best.get('distance')}")
        await self.websocket.send_action({
            "type": "attack",
            "targetId": best.get("id")
        })
        return True
    
    # ──────────────────────────────────────────────────────────
    # 6. RUIN AMAN? → EXPLORE
    # ──────────────────────────────────────────────────────────
    async def _handle_explore(self) -> bool:
        """Explore ruins if safe"""
        if not self.ruins:
            return False
        
        self_section = self.state.get("self", {})
        hp = self_section.get("hp", 100)
        max_hp = self_section.get("maxHp", 100)
        
        # Jangan explore jika HP rendah
        if hp < max_hp * 0.5:
            return False
        
        # Cari ruin terdekat yang belum fully explored
        for ruin in self.ruins:
            dist = ruin.get("distance", 999)
            explored = ruin.get("explored", 0)
            
            if dist <= self.EXPLORE_RANGE and explored < 3:
                logger.info(f"🏛️ Exploring ruin at distance {dist} ({explored}/3)")
                await self.websocket.send_action({
                    "type": "explore",
                    "ruinId": ruin.get("id")
                })
                return True
            
            # Jika ruin dalam range tapi sudah fully explored
            if dist <= self.EXPLORE_RANGE and explored >= 3:
                logger.debug(f"Ruin fully explored, skipping")
        
        # Jika ada ruin tidak dalam range, move towards nearest
        nearest_ruin = min(self.ruins, key=lambda x: x.get("distance", 999))
        if nearest_ruin.get("distance", 999) < 5:
            logger.info(f"🚶 Moving towards ruin at distance {nearest_ruin.get('distance')}")
            await self._move_towards(nearest_ruin.get("position"))
            return True
        
        return False
    
    # ──────────────────────────────────────────────────────────
    # 7. TIDAK ADA TUJUAN? → MOVE
    # ──────────────────────────────────────────────────────────
    async def _handle_move(self):
        """Strategic movement when nothing else to do"""
        logger.debug("🚶 No specific goal - moving strategically")
        
        # Prioritaskan bergerak ke arah yang belum dijelajahi
        # atau ke arah yang ada item/ruin terdekat
        
        # Cek item terdekat
        if self.items:
            nearest = min(self.items, key=lambda x: x.get("distance", 999))
            if nearest.get("distance", 999) < 8:
                await self._move_towards(nearest.get("position"))
                return
        
        # Cek ruin terdekat
        if self.ruins:
            nearest = min(self.ruins, key=lambda x: x.get("distance", 999))
            if nearest.get("distance", 999) < 8:
                await self._move_towards(nearest.get("position"))
                return
        
        # Random movement
        await self._move_random()
    
    # ──────────────────────────────────────────────────────────
    # MOVEMENT HELPERS
    # ──────────────────────────────────────────────────────────
    async def _move_away_from_danger(self):
        """Move away from nearest danger"""
        self_section = self.state.get("self", {})
        position = self_section.get("position", {})
        
        # Cari nearest enemy
        nearest_enemy = None
        nearest_dist = 999
        
        all_targets = self.monsters + self.targets
        for target in all_targets:
            dist = target.get("distance", 999)
            if dist < nearest_dist:
                nearest_dist = dist
                nearest_enemy = target
        
        if nearest_enemy and nearest_enemy.get("position"):
            # Move away from enemy
            enemy_pos = nearest_enemy.get("position")
            dx = position.get("x", 0) - enemy_pos.get("x", 0)
            dy = position.get("y", 0) - enemy_pos.get("y", 0)
            
            if abs(dx) > abs(dy):
                direction = "right" if dx > 0 else "left"
            else:
                direction = "down" if dy > 0 else "up"
        else:
            # Random escape
            directions = ["up", "down", "left", "right"]
            direction = random.choice(directions)
        
        await self.websocket.send_action({
            "type": "move",
            "direction": direction
        })
    
    async def _move_towards(self, target_pos: Dict):
        """Move towards target position"""
        self_section = self.state.get("self", {})
        position = self_section.get("position", {})
        
        dx = target_pos.get("x", 0) - position.get("x", 0)
        dy = target_pos.get("y", 0) - position.get("y", 0)
        
        # Pilih arah dengan jarak terbesar
        if abs(dx) > abs(dy):
            direction = "right" if dx > 0 else "left"
        else:
            direction = "down" if dy > 0 else "up"
        
        await self.websocket.send_action({
            "type": "move",
            "direction": direction
        })
    
    async def _move_random(self):
        """Random movement"""
        directions = ["up", "down", "left", "right"]
        direction = random.choice(directions)
        
        logger.debug(f"🚶 Moving {direction} (random)")
        await self.websocket.send_action({
            "type": "move",
            "direction": direction
        })
