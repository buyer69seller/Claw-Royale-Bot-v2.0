"""
================================================================================
                    COMPETITIVE AI - AUTO-PILOT ENGINE v8.1
                    DENGAN DECISION ENGINE CEPAT & TEPAT
================================================================================

OPTIMASI KECEPATAN:
1. Early Exit Pattern - Keluar cepat jika kondisi terpenuhi
2. Cached Calculations - Cache hasil perhitungan
3. Priority-based Decision - Cek prioritas tertinggi dulu
4. Simple Heuristics - Gunakan aturan sederhana untuk keputusan cepat
5. Lazy Evaluation - Evaluasi hanya jika diperlukan
================================================================================
"""
"""
================================================================================
                    COMPETITIVE AI - DEBUG VERSION
                    DENGAN FULL LOGGING UNTUK DIAGNOSIS
================================================================================
"""
"""
================================================================================
                    COMPETITIVE AI - FIXED VERSION
                    DENGAN AUTO-RESET action_in_progress
================================================================================
"""

import random
import math
import time
from typing import Dict, List, Optional, Tuple
from ..game.websocket import GameWebSocket
from ..utils.logger import logger


class CompetitiveAI:
    """
    FIXED VERSION - Dengan auto-reset action_in_progress
    """
    
    def __init__(self, websocket: GameWebSocket):
        self.websocket = websocket
        
        # ── State ──
        self.state = {}
        self.turn = 0
        self.is_dead = False
        self.action_in_progress = False
        self.action_start_time = 0  # 🔥 Untuk timeout
        self.action_timeout = 5.0   # 🔥 5 detik timeout
        
        # ── Stats ──
        self.kills = 0
        self.items_collected = 0
        self.survival_time = 0
        self.heals_used = 0
        self.actions_sent = 0
        
        # ── Self ──
        self.my_position = (0, 0)
        self.my_hp = 100
        self.my_max_hp = 100
        self.my_ep = 50
        self.my_max_ep = 50
        self.in_cave = False
        self.cave_id = None
        self.alert_gauge = 0
        
        # ── World ──
        self.visible_agents = []
        self.visible_monsters = []
        self.visible_items = []
        self.visible_ruins = []
        self.death_zone_center = (10, 10)
        self.death_zone_radius = 10
        self.enemy_positions = []
        
        # ── Thresholds ──
        self.HP_CRITICAL = 0.25
        self.HP_VERY_LOW = 0.35
        self.HP_LOW = 0.45
        self.HP_SAFE = 0.60
        
        self.LOOT_RANGE = 3
        self.ATTACK_RANGE = 3
        self.DANGER_RANGE = 4
        self.SAFE_ZONE_BUFFER = 3
        self.ALERT_HIGH = 7
        
        # ── Item Values ──
        self.ITEM_VALUES = {
            "relic": 100, "pack": 80, "elixir": 70, "potion": 50,
            "bandage": 40, "herb": 30, "smoltz": 10, "default": 20
        }
        
        self.HEALING_PRIORITY = {
            "elixir": 100, "potion": 80, "bandage": 60, "herb": 50, "default": 30
        }
        
        # ── Debug ──
        self.last_action_time = 0
        self.consecutive_no_action = 0
        self.first_turn = True
        
        # ── Inventory ──
        self.inventory = []

    # ═══════════════════════════════════════════════════════════════════════════
    # 1. MAIN HANDLER
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def handle_message(self, data: Dict):
        """Main handler dengan auto-reset"""
        msg_type = data.get("type")
        
        # ── 🔥 AUTO-RESET: Cek timeout action ──
        if self.action_in_progress:
            elapsed = time.time() - self.action_start_time
            if elapsed > self.action_timeout:
                logger.warning(f"⏰ Action timeout! Resetting action_in_progress (elapsed: {elapsed:.1f}s)")
                self.action_in_progress = False
                self.action_start_time = 0
                # 🔥 Coba action baru
                if not self.is_dead and self.state.get("canAct", True):
                    await self._decide_action()
                return
        
        # ── DEATH DETECTION ──
        if msg_type == "agent_died":
            meta = data.get("meta", {})
            if meta.get("youDied") == True:
                logger.info(f"💀 YOU DIED! Survival: {self.survival_time}, Kills: {self.kills}")
                self.is_dead = True
                self.websocket.is_alive = False
                if self.websocket.on_game_ended:
                    self.websocket.on_game_ended()
                return
            else:
                logger.info(f"💀 Agent died: {data.get('agentId')}")
                self.visible_agents = []
                return
        
        # ── 🔥 ACTION RESULT ──
        if msg_type == "action_result":
            result = data.get("result", {})
            if result.get("success"):
                logger.info(f"✅ [ACTION] Successful!")
                self.action_in_progress = False
                self.action_start_time = 0
                self.consecutive_no_action = 0
            else:
                error = result.get("error", {})
                error_code = error.get("code", "")
                logger.warning(f"❌ [ACTION] Failed: {error_code}")
                self.action_in_progress = False
                self.action_start_time = 0
                
                if error_code == "AGENT_DEAD":
                    self.is_dead = True
                    self.websocket.is_alive = False
                    if self.websocket.on_game_ended:
                        self.websocket.on_game_ended()
                    return
                
                elif error_code in ["TARGET_DEAD", "ACTION_FAILED"]:
                    self.visible_agents = []
                    if self.state.get("canAct", True):
                        await self._decide_action()
                    return
                
                elif error_code == "NOT_ENOUGH_EP":
                    logger.warning("⚡ Not enough EP!")
                    return
            
            # 🔥 Setelah action_result, langsung decision lagi
            if not self.is_dead and self.state.get("canAct", True):
                await self._decide_action()
            return
        
        # ── AGENT VIEW ──
        if msg_type == "agent_view":
            self.state = data.get("view", {})
            self.turn += 1
            self.survival_time = self.turn
            
            # Update world
            self._update_world_state()
            
            # 🔥 CEK CAN ACT
            can_act = data.get("canAct", True)
            if not can_act:
                logger.debug(f"⏳ Cannot act this turn")
                return
            
            # 🔥 DECIDE ACTION
            if not self.is_dead:
                await self._decide_action()
        
        # ── TURN ADVANCED ──
        elif msg_type == "turn_advanced":
            self.turn += 1
            self.survival_time = self.turn
            
            # 🔥 Auto-reset jika action_in_progress terlalu lama
            if self.action_in_progress:
                elapsed = time.time() - self.action_start_time
                if elapsed > self.action_timeout:
                    logger.warning(f"⏰ Action timeout on turn_advanced! Resetting...")
                    self.action_in_progress = False
                    self.action_start_time = 0
            
            if self.state.get("canAct", True) and not self.is_dead and not self.action_in_progress:
                await self._decide_action()
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 2. WORLD UPDATE
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _update_world_state(self):
        """Update world state"""
        view = self.state
        self_section = view.get("self", {})
        
        self.my_position = (
            self_section.get("position", {}).get("x", 0),
            self_section.get("position", {}).get("y", 0)
        )
        self.my_hp = self_section.get("hp", 100)
        self.my_max_hp = self_section.get("maxHp", 100)
        self.my_ep = self_section.get("ep", 50)
        self.my_max_ep = self_section.get("maxEp", 50)
        self.in_cave = self_section.get("inCave", False)
        self.cave_id = self_section.get("caveId")
        self.alert_gauge = self_section.get("alertGauge", 0)
        self.inventory = self_section.get("items", [])
        
        self.visible_agents = view.get("visibleAgents", [])
        self.visible_monsters = view.get("visibleMonsters", [])
        self.visible_items = view.get("visibleItems", [])
        self.visible_ruins = view.get("visibleRuins", [])
        
        self.enemy_positions = []
        for agent in self.visible_agents:
            pos = agent.get("position", {})
            self.enemy_positions.append((pos.get("x", 0), pos.get("y", 0)))
        for monster in self.visible_monsters:
            pos = monster.get("position", {})
            self.enemy_positions.append((pos.get("x", 0), pos.get("y", 0)))
        
        dz = view.get("deathZone", {})
        self.death_zone_center = (
            dz.get("center", {}).get("x", 10),
            dz.get("center", {}).get("y", 10)
        )
        self.death_zone_radius = dz.get("radius", 10)
        
        # ── Log setiap 5 turn ──
        if self.turn % 5 == 0 and self.turn > 0:
            logger.info(f"📊 T{self.turn}: HP={self.my_hp}/{self.my_max_hp}, "
                       f"Pos=({self.my_position[0]},{self.my_position[1]}), "
                       f"Enemies={len(self.visible_agents)}, Items={len(self.visible_items)}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 3. DECISION ENGINE
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def _decide_action(self):
        """DECISION ENGINE - Dengan force action jika stuck"""
        try:
            if self.is_dead:
                return
            
            # 🔥 JANGAN decision jika action_in_progress
            if self.action_in_progress:
                elapsed = time.time() - self.action_start_time
                if elapsed < self.action_timeout:
                    logger.debug(f"⏳ Action in progress ({elapsed:.1f}s)")
                    return
                else:
                    logger.warning(f"⏰ Force resetting action_in_progress")
                    self.action_in_progress = False
                    self.action_start_time = 0
            
            hp_percent = self.my_hp / self.my_max_hp
            ep_percent = self.my_ep / self.my_max_ep
            
            # ═══════════════════════════════════════════════════════════════════
            # PRIORITY 1: SURVIVAL
            # ═══════════════════════════════════════════════════════════════════
            
            # 1a. Escape cave
            if self.in_cave and self.cave_id:
                logger.info("🚪 Escaping cave...")
                self.action_in_progress = True
                self.action_start_time = time.time()
                self.actions_sent += 1
                await self.websocket.send_action({
                    "type": "interact",
                    "interactableId": self.cave_id
                })
                return
            
            # 1b. Heal if critical
            if hp_percent < self.HP_CRITICAL:
                heal_item = self._get_healing_item()
                if heal_item:
                    logger.info(f"💊 Healing with {heal_item.get('name', 'item')}")
                    self.action_in_progress = True
                    self.action_start_time = time.time()
                    self.actions_sent += 1
                    await self.websocket.send_action({
                        "type": "use_item",
                        "itemId": heal_item.get("id")
                    })
                    return
                else:
                    logger.warning("🏃 Critical HP, retreating!")
                    self.action_in_progress = True
                    self.action_start_time = time.time()
                    self.actions_sent += 1
                    await self._retreat()
                    return
            
            # 1c. Retreat if low HP
            if hp_percent < self.HP_VERY_LOW:
                logger.warning("🏃 Low HP, retreating!")
                self.action_in_progress = True
                self.action_start_time = time.time()
                self.actions_sent += 1
                await self._retreat()
                return
            
            # 1d. Move to safe zone
            if self._is_in_death_zone():
                direction = self._get_safe_direction()
                logger.info(f"🏃 Moving to safe zone: {direction}")
                self.action_in_progress = True
                self.action_start_time = time.time()
                self.actions_sent += 1
                await self.websocket.send_action({
                    "type": "move",
                    "direction": direction
                })
                return
            
            # 1e. Hide if alert high
            if self.alert_gauge > self.ALERT_HIGH:
                logger.info(f"⚠️ Alert high ({self.alert_gauge}), hiding!")
                self.action_in_progress = True
                self.action_start_time = time.time()
                self.actions_sent += 1
                await self._retreat()
                return
            
            # ═══════════════════════════════════════════════════════════════════
            # PRIORITY 2: LOOT
            # ═══════════════════════════════════════════════════════════════════
            
            if self.visible_items and hp_percent > self.HP_LOW:
                nearest = self._get_nearest_item()
                if nearest:
                    pos = nearest.get("position", {})
                    distance = self._get_distance(
                        self.my_position,
                        (pos.get("x", 0), pos.get("y", 0))
                    )
                    
                    if distance <= self.LOOT_RANGE:
                        logger.info(f"📦 Looting {nearest.get('name', 'item')}")
                        self.action_in_progress = True
                        self.action_start_time = time.time()
                        self.actions_sent += 1
                        await self.websocket.send_action({
                            "type": "collect",
                            "itemId": nearest.get("id")
                        })
                        self.items_collected += 1
                        return
                    elif distance < 5:
                        logger.info(f"🚶 Moving to item")
                        self.action_in_progress = True
                        self.action_start_time = time.time()
                        self.actions_sent += 1
                        await self._move_towards((pos.get("x", 0), pos.get("y", 0)))
                        return
            
            # ═══════════════════════════════════════════════════════════════════
            # PRIORITY 3: KILL
            # ═══════════════════════════════════════════════════════════════════
            
            if hp_percent > self.HP_SAFE and ep_percent > 0.3:
                target = self._get_best_target()
                if target:
                    pos = target.get("position", {})
                    distance = self._get_distance(
                        self.my_position,
                        (pos.get("x", 0), pos.get("y", 0))
                    )
                    
                    if distance <= self.ATTACK_RANGE:
                        logger.info(f"⚔️ Attacking {target.get('name', 'enemy')}")
                        self.action_in_progress = True
                        self.action_start_time = time.time()
                        self.actions_sent += 1
                        await self.websocket.send_action({
                            "type": "attack",
                            "targetId": target.get("id")
                        })
                        return
                    elif distance < 5:
                        logger.info(f"🚶 Moving to target")
                        self.action_in_progress = True
                        self.action_start_time = time.time()
                        self.actions_sent += 1
                        await self._move_towards((pos.get("x", 0), pos.get("y", 0)))
                        return
            
            # ═══════════════════════════════════════════════════════════════════
            # PRIORITY 4: EXPLORE
            # ═══════════════════════════════════════════════════════════════════
            
            if self.visible_ruins and hp_percent > self.HP_LOW:
                nearest = self._get_nearest_ruin()
                if nearest:
                    pos = nearest.get("position", {})
                    distance = self._get_distance(
                        self.my_position,
                        (pos.get("x", 0), pos.get("y", 0))
                    )
                    explored = nearest.get("explored", 0)
                    
                    if distance <= 2 and explored < 3:
                        logger.info(f"🏛️ Exploring ruin ({explored}/3)")
                        self.action_in_progress = True
                        self.action_start_time = time.time()
                        self.actions_sent += 1
                        await self.websocket.send_action({
                            "type": "explore",
                            "ruinId": nearest.get("id")
                        })
                        return
                    elif distance < 5:
                        logger.info(f"🚶 Moving to ruin")
                        self.action_in_progress = True
                        self.action_start_time = time.time()
                        self.actions_sent += 1
                        await self._move_towards((pos.get("x", 0), pos.get("y", 0)))
                        return
            
            # ═══════════════════════════════════════════════════════════════════
            # FALLBACK: MOVE
            # ═══════════════════════════════════════════════════════════════════
            
            self.consecutive_no_action += 1
            logger.info(f"🚶 Moving random (count: {self.consecutive_no_action})")
            self.action_in_progress = True
            self.action_start_time = time.time()
            self.actions_sent += 1
            await self._force_move()
            
        except Exception as e:
            logger.error(f"❌ Decision error: {e}")
            self.action_in_progress = False
            self.action_start_time = 0
            await self._force_move()
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 4. HELPERS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _get_distance(self, pos1: Tuple[int, int], pos2: Tuple[int, int]) -> float:
        return math.sqrt((pos1[0] - pos2[0])**2 + (pos1[1] - pos2[1])**2)
    
    def _is_in_death_zone(self) -> bool:
        distance = self._get_distance(self.my_position, self.death_zone_center)
        return distance > self.death_zone_radius - self.SAFE_ZONE_BUFFER
    
    def _get_safe_direction(self) -> str:
        x, y = self.my_position
        cx, cy = self.death_zone_center
        dx = cx - x
        dy = cy - y
        if abs(dx) > abs(dy):
            return "right" if dx > 0 else "left"
        else:
            return "down" if dy > 0 else "up"
    
    def _get_healing_item(self) -> Optional[Dict]:
        best_item = None
        best_priority = -1
        for item in self.inventory:
            item_type = item.get("type", "").lower()
            if "heal" in item_type or "potion" in item_type or "herb" in item_type or "elixir" in item_type:
                priority = self.HEALING_PRIORITY.get(item_type, self.HEALING_PRIORITY["default"])
                if priority > best_priority:
                    best_priority = priority
                    best_item = item
        return best_item
    
    def _get_nearest_item(self) -> Optional[Dict]:
        if not self.visible_items:
            return None
        return min(self.visible_items, key=lambda x: self._get_distance(
            self.my_position,
            (x.get("position", {}).get("x", 0), x.get("position", {}).get("y", 0))
        ))
    
    def _get_nearest_ruin(self) -> Optional[Dict]:
        if not self.visible_ruins:
            return None
        return min(self.visible_ruins, key=lambda x: self._get_distance(
            self.my_position,
            (x.get("position", {}).get("x", 0), x.get("position", {}).get("y", 0))
        ))
    
    def _get_best_target(self) -> Optional[Dict]:
        all_enemies = self.visible_agents + self.visible_monsters
        if not all_enemies:
            return None
        
        best = None
        best_score = -1
        for enemy in all_enemies:
            pos = enemy.get("position", {})
            distance = self._get_distance(
                self.my_position,
                (pos.get("x", 0), pos.get("y", 0))
            )
            if distance > self.ATTACK_RANGE + 2:
                continue
            hp = enemy.get("hp", 100)
            score = (100 - hp) / 100 + (1 / (1 + distance))
            if score > best_score:
                best_score = score
                best = enemy
        return best
    
    async def _retreat(self):
        if not self.enemy_positions:
            directions = ["up", "down", "left", "right"]
            direction = random.choice(directions)
        else:
            nearest = min(self.enemy_positions, key=lambda p: self._get_distance(self.my_position, p))
            x, y = self.my_position
            ex, ey = nearest
            dx = x - ex
            dy = y - ey
            if abs(dx) > abs(dy):
                direction = "right" if dx > 0 else "left"
            else:
                direction = "down" if dy > 0 else "up"
        
        await self.websocket.send_action({
            "type": "move",
            "direction": direction
        })
    
    async def _move_towards(self, target_pos: Tuple[int, int]):
        x, y = self.my_position
        tx, ty = target_pos
        dx = tx - x
        dy = ty - y
        if abs(dx) > abs(dy):
            direction = "right" if dx > 0 else "left"
        else:
            direction = "down" if dy > 0 else "up"
        await self.websocket.send_action({
            "type": "move",
            "direction": direction
        })
    
    async def _force_move(self):
        directions = ["up", "down", "left", "right"]
        if self._is_in_death_zone():
            direction = self._get_safe_direction()
        else:
            direction = random.choice(directions)
        await self.websocket.send_action({
            "type": "move",
            "direction": direction
        })
