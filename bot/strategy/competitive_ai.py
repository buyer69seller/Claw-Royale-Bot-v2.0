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

import random
import math
import time
from typing import Dict, List, Optional, Tuple
from ..game.websocket import GameWebSocket
from ..utils.logger import logger


class CompetitiveAI:
    """
    DEBUG VERSION - Dengan full logging untuk diagnosis bot diam
    """
    
    def __init__(self, websocket: GameWebSocket):
        self.websocket = websocket
        
        # ── State ──
        self.state = {}
        self.turn = 0
        self.is_dead = False
        self.action_in_progress = False
        self.loop_iteration = 0
        
        # ── Stats ──
        self.kills = 0
        self.items_collected = 0
        self.survival_time = 0
        self.heals_used = 0
        self.actions_sent = 0  # 🔥 TRACKING: jumlah action terkirim
        
        # ── Self ──
        self.my_position = (0, 0)
        self.my_hp = 100
        self.my_max_hp = 100
        self.my_ep = 50
        self.my_max_ep = 50
        self.my_atk = 5
        self.my_def = 2
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
        self.max_consecutive_no_action = 3  # 🔥 Jika 3 turn no action, force action
        
        # ── First turn flag ──
        self.first_turn = True

    # ═══════════════════════════════════════════════════════════════════════════
    # 1. MAIN HANDLER - DENGAN FULL LOGGING
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def handle_message(self, data: Dict):
        """Main handler dengan full logging"""
        msg_type = data.get("type")
        
        # ── 🔥 LOG SEMUA MESSAGE ──
        logger.info(f"📨 [MSG] Type: {msg_type}")
        
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
        
        # ── ACTION RESULT ──
        if msg_type == "action_result":
            result = data.get("result", {})
            if result.get("success"):
                logger.info(f"✅ [ACTION] Successful!")
                self.action_in_progress = False
                self.consecutive_no_action = 0
            else:
                error = result.get("error", {})
                error_code = error.get("code", "")
                logger.warning(f"❌ [ACTION] Failed: {error_code}")
                
                if error_code == "AGENT_DEAD":
                    self.is_dead = True
                    self.websocket.is_alive = False
                    if self.websocket.on_game_ended:
                        self.websocket.on_game_ended()
                    return
                
                elif error_code in ["TARGET_DEAD", "ACTION_FAILED"]:
                    self.action_in_progress = False
                    self.visible_agents = []
                    return
                
                elif error_code == "NOT_ENOUGH_EP":
                    logger.warning("⚡ Not enough EP!")
                    self.action_in_progress = False
                    return
            
            return
        
        # ── 🔥 AGENT VIEW ──
        if msg_type == "agent_view":
            logger.info(f"📊 [AGENT_VIEW] Turn: {self.turn + 1}")
            
            self.state = data.get("view", {})
            self.turn += 1
            self.survival_time = self.turn
            
            # Update world
            self._update_world_state()
            
            # ── 🔥 LOG STATUS ──
            logger.info(f"   HP: {self.my_hp}/{self.my_max_hp}")
            logger.info(f"   EP: {self.my_ep}/{self.my_max_ep}")
            logger.info(f"   Position: ({self.my_position[0]}, {self.my_position[1]})")
            logger.info(f"   Enemies: {len(self.visible_agents)}")
            logger.info(f"   Items: {len(self.visible_items)}")
            logger.info(f"   Ruins: {len(self.visible_ruins)}")
            logger.info(f"   In Cave: {self.in_cave}")
            logger.info(f"   Alert: {self.alert_gauge}")
            
            # ── 🔥 CEK CAN ACT ──
            can_act = data.get("canAct", True)
            logger.info(f"   Can Act: {can_act}")
            
            if not can_act:
                logger.warning("⏳ Cannot act this turn (waiting)")
                return
            
            # ── 🔥 DECIDE ACTION ──
            if not self.is_dead:
                logger.info("🎯 [DECISION] Starting decision...")
                await self._decide_action()
            else:
                logger.warning("💀 Bot is dead!")
            
            self.loop_iteration += 1
            self.first_turn = False
        
        # ── TURN ADVANCED ──
        elif msg_type == "turn_advanced":
            logger.info(f"🔄 [TURN] Advanced to: {self.turn + 1}")
            self.turn += 1
            self.survival_time = self.turn
            
            if self.state.get("canAct", True) and not self.is_dead:
                await self._decide_action()
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 2. WORLD UPDATE - DENGAN LOGGING
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _update_world_state(self):
        """Update world state dengan logging"""
        view = self.state
        self_section = view.get("self", {})
        
        # Self
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
        
        # Enemies
        self.visible_agents = view.get("visibleAgents", [])
        self.visible_monsters = view.get("visibleMonsters", [])
        
        # Items
        self.visible_items = view.get("visibleItems", [])
        
        # Ruins
        self.visible_ruins = view.get("visibleRuins", [])
        
        # Enemy positions
        self.enemy_positions = []
        for agent in self.visible_agents:
            pos = agent.get("position", {})
            self.enemy_positions.append((pos.get("x", 0), pos.get("y", 0)))
        for monster in self.visible_monsters:
            pos = monster.get("position", {})
            self.enemy_positions.append((pos.get("x", 0), pos.get("y", 0)))
        
        # Death zone
        dz = view.get("deathZone", {})
        self.death_zone_center = (
            dz.get("center", {}).get("x", 10),
            dz.get("center", {}).get("y", 10)
        )
        self.death_zone_radius = dz.get("radius", 10)
        
        # ── 🔥 LOG WORLD ──
        logger.info(f"   Enemy positions: {self.enemy_positions}")
        logger.info(f"   Death zone center: {self.death_zone_center}")
        logger.info(f"   Death zone radius: {self.death_zone_radius}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 3. DECISION ENGINE - DENGAN FORCE ACTION
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def _decide_action(self):
        """
        DECISION ENGINE - Dengan force action jika tidak ada
        """
        try:
            if self.is_dead:
                logger.warning("💀 Bot is dead, skipping decision")
                return
            
            if self.action_in_progress:
                logger.warning("⏳ Action already in progress")
                return
            
            hp_percent = self.my_hp / self.my_max_hp
            ep_percent = self.my_ep / self.my_max_ep
            
            # ── 🔥 FORCE ACTION jika terlalu lama diam ──
            if self.consecutive_no_action >= self.max_consecutive_no_action:
                logger.warning(f"⚠️ No action for {self.consecutive_no_action} turns - FORCE ACTION!")
                self.action_in_progress = True
                await self._force_action()
                self.consecutive_no_action = 0
                return
            
            # ── 🔥 LOG DECISION ──
            logger.info(f"🎯 [DECISION] HP%: {hp_percent:.2f}, EP%: {ep_percent:.2f}")
            
            # ═══════════════════════════════════════════════════════════════════
            # PRIORITY 1: SURVIVAL
            # ═══════════════════════════════════════════════════════════════════
            
            # 1a. Escape cave
            if self.in_cave and self.cave_id:
                logger.info("🚪 [ACTION] Escaping cave...")
                self.action_in_progress = True
                self.consecutive_no_action = 0
                self.actions_sent += 1
                await self.websocket.send_action({
                    "type": "interact",
                    "interactableId": self.cave_id
                })
                logger.info(f"   ✅ Action sent! (Total: {self.actions_sent})")
                return
            
            # 1b. Heal if critical
            if hp_percent < self.HP_CRITICAL:
                heal_item = self._get_healing_item()
                if heal_item:
                    logger.info(f"💊 [ACTION] Healing with {heal_item.get('name', 'item')}")
                    self.action_in_progress = True
                    self.consecutive_no_action = 0
                    self.actions_sent += 1
                    await self.websocket.send_action({
                        "type": "use_item",
                        "itemId": heal_item.get("id")
                    })
                    logger.info(f"   ✅ Action sent! (Total: {self.actions_sent})")
                    return
                else:
                    logger.warning("🏃 [ACTION] Critical HP, retreating!")
                    self.action_in_progress = True
                    self.consecutive_no_action = 0
                    self.actions_sent += 1
                    await self._retreat()
                    logger.info(f"   ✅ Action sent! (Total: {self.actions_sent})")
                    return
            
            # 1c. Retreat if low HP
            if hp_percent < self.HP_VERY_LOW:
                logger.warning("🏃 [ACTION] Low HP, retreating!")
                self.action_in_progress = True
                self.consecutive_no_action = 0
                self.actions_sent += 1
                await self._retreat()
                logger.info(f"   ✅ Action sent! (Total: {self.actions_sent})")
                return
            
            # 1d. Move to safe zone
            if self._is_in_death_zone():
                direction = self._get_safe_direction()
                logger.info(f"🏃 [ACTION] Moving to safe zone: {direction}")
                self.action_in_progress = True
                self.consecutive_no_action = 0
                self.actions_sent += 1
                await self.websocket.send_action({
                    "type": "move",
                    "direction": direction
                })
                logger.info(f"   ✅ Action sent! (Total: {self.actions_sent})")
                return
            
            # 1e. Hide if alert high
            if self.alert_gauge > self.ALERT_HIGH:
                logger.info(f"⚠️ [ACTION] Alert high ({self.alert_gauge}), hiding!")
                self.action_in_progress = True
                self.consecutive_no_action = 0
                self.actions_sent += 1
                await self._retreat()
                logger.info(f"   ✅ Action sent! (Total: {self.actions_sent})")
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
                        logger.info(f"📦 [ACTION] Looting {nearest.get('name', 'item')}")
                        self.action_in_progress = True
                        self.consecutive_no_action = 0
                        self.actions_sent += 1
                        await self.websocket.send_action({
                            "type": "collect",
                            "itemId": nearest.get("id")
                        })
                        self.items_collected += 1
                        logger.info(f"   ✅ Action sent! (Total: {self.actions_sent})")
                        return
                    elif distance < 5:
                        logger.info(f"🚶 [ACTION] Moving to item at distance {distance:.1f}")
                        self.action_in_progress = True
                        self.consecutive_no_action = 0
                        self.actions_sent += 1
                        await self._move_towards((pos.get("x", 0), pos.get("y", 0)))
                        logger.info(f"   ✅ Action sent! (Total: {self.actions_sent})")
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
                        logger.info(f"⚔️ [ACTION] Attacking {target.get('name', 'enemy')}")
                        self.action_in_progress = True
                        self.consecutive_no_action = 0
                        self.actions_sent += 1
                        await self.websocket.send_action({
                            "type": "attack",
                            "targetId": target.get("id")
                        })
                        logger.info(f"   ✅ Action sent! (Total: {self.actions_sent})")
                        return
                    elif distance < 5:
                        logger.info(f"🚶 [ACTION] Moving to target at distance {distance:.1f}")
                        self.action_in_progress = True
                        self.consecutive_no_action = 0
                        self.actions_sent += 1
                        await self._move_towards((pos.get("x", 0), pos.get("y", 0)))
                        logger.info(f"   ✅ Action sent! (Total: {self.actions_sent})")
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
                        logger.info(f"🏛️ [ACTION] Exploring ruin ({explored}/3)")
                        self.action_in_progress = True
                        self.consecutive_no_action = 0
                        self.actions_sent += 1
                        await self.websocket.send_action({
                            "type": "explore",
                            "ruinId": nearest.get("id")
                        })
                        logger.info(f"   ✅ Action sent! (Total: {self.actions_sent})")
                        return
                    elif distance < 5:
                        logger.info(f"🚶 [ACTION] Moving to ruin at distance {distance:.1f}")
                        self.action_in_progress = True
                        self.consecutive_no_action = 0
                        self.actions_sent += 1
                        await self._move_towards((pos.get("x", 0), pos.get("y", 0)))
                        logger.info(f"   ✅ Action sent! (Total: {self.actions_sent})")
                        return
            
            # ═══════════════════════════════════════════════════════════════════
            # FALLBACK: FORCE MOVE
            # ═══════════════════════════════════════════════════════════════════
            
            self.consecutive_no_action += 1
            logger.warning(f"⚠️ [ACTION] No specific action - force move (count: {self.consecutive_no_action})")
            self.action_in_progress = True
            self.actions_sent += 1
            await self._force_action()
            logger.info(f"   ✅ Action sent! (Total: {self.actions_sent})")
            
        except Exception as e:
            logger.error(f"❌ [ERROR] Decision error: {e}")
            self.action_in_progress = False
            await self._force_action()
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 4. FORCE ACTION - UNTUK BOT DIAM
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def _force_action(self):
        """Force action - untuk mengatasi bot diam"""
        # Coba ke arah yang berbeda
        directions = ["up", "down", "left", "right"]
        
        if self._is_in_death_zone():
            direction = self._get_safe_direction()
        else:
            direction = random.choice(directions)
        
        logger.info(f"🚀 [FORCE] Moving {direction}")
        await self.websocket.send_action({
            "type": "move",
            "direction": direction
        })
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 5. HELPERS
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
