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

import random
import math
import time
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict
from ..game.websocket import GameWebSocket
from ..utils.logger import logger


class CompetitiveAI:
    """
    AUTO-PILOT ENGINE v8.1 - Dengan Decision Engine Cepat & Tepat
    
    Decision Time Target: < 10ms per turn
    """
    
    def __init__(self, websocket: GameWebSocket):
        self.websocket = websocket
        
        # ──────────────────────────────────────────────
        # STATE & STATS
        # ──────────────────────────────────────────────
        self.state = {}
        self.turn = 0
        self.is_dead = False
        self.action_in_progress = False
        self.loop_iteration = 0
        self.decision_time = 0
        
        self.kills = 0
        self.items_collected = 0
        self.survival_time = 0
        self.damage_dealt = 0
        self.damage_taken = 0
        self.heals_used = 0
        self.monsters_killed = 0
        self.ruins_explored = 0
        
        # ──────────────────────────────────────────────
        # CACHED VALUES (untuk kecepatan)
        # ──────────────────────────────────────────────
        self._cached_danger = 0
        self._cached_nearest_item = None
        self._cached_nearest_enemy = None
        self._cached_nearest_ruin = None
        self._cached_hp_percent = 1.0
        self._cached_ep_percent = 1.0
        self._cache_turn = -1
        
        # ──────────────────────────────────────────────
        # SELF
        # ──────────────────────────────────────────────
        self.my_position = (0, 0)
        self.my_hp = 100
        self.my_max_hp = 100
        self.my_ep = 50
        self.my_max_ep = 50
        self.my_atk = 5
        self.my_def = 2
        self.my_speed = 1
        self.in_cave = False
        self.cave_id = None
        self.alert_gauge = 0
        self.is_alert_active = False
        
        # ──────────────────────────────────────────────
        # INVENTORY
        # ──────────────────────────────────────────────
        self.inventory = []
        self.equipped_items = {"main": None, "sub": None, "relics": []}
        
        # ──────────────────────────────────────────────
        # WORLD
        # ──────────────────────────────────────────────
        self.visible_agents = []
        self.visible_monsters = []
        self.visible_items = []
        self.visible_ruins = []
        self.visible_interactables = []
        self.death_zone_center = (10, 10)
        self.death_zone_radius = 10
        self.enemy_positions = []
        self.safe_positions = []
        
        # ──────────────────────────────────────────────
        # PRIORITY THRESHOLDS (UNTUK KECEPATAN)
        # ──────────────────────────────────────────────
        self.HP_CRITICAL = 0.25
        self.HP_VERY_LOW = 0.35
        self.HP_LOW = 0.45
        self.HP_SAFE = 0.60
        self.HP_HIGH = 0.75
        
        self.EP_CRITICAL = 0.15
        self.EP_LOW = 0.30
        self.EP_SAFE = 0.50
        
        self.ALERT_HIGH = 7
        self.ALERT_MEDIUM = 5
        
        # ──────────────────────────────────────────────
        # RANGES (UNTUK KECEPATAN)
        # ──────────────────────────────────────────────
        self.LOOT_RANGE = 3
        self.ATTACK_RANGE = 3
        self.DANGER_RANGE = 4
        self.SAFE_ZONE_BUFFER = 3
        
        # ──────────────────────────────────────────────
        # SIMPLE HEURISTICS (UNTUK KECEPATAN)
        # ──────────────────────────────────────────────
        self.ITEM_VALUES = {
            "relic": 100, "pack": 80, "elixir": 70, "potion": 50,
            "bandage": 40, "herb": 30, "smoltz": 10, "default": 20
        }
        
        self.HEALING_PRIORITY = {
            "elixir": 100, "potion": 80, "bandage": 60, "herb": 50, "default": 30
        }
        
        # ──────────────────────────────────────────────
        # DECISION WEIGHTS (UNTUK KECEPATAN)
        # ──────────────────────────────────────────────
        self.weights = {
            "survival": 1.0,
            "loot": 0.8,
            "kill": 0.7,
            "explore": 0.5,
            "retreat": 0.9
        }
        
        # ──────────────────────────────────────────────
        # STRATEGY STATE
        # ──────────────────────────────────────────────
        self.strategy_mode = "balanced"
        self.last_heal_turn = 0
        self.last_retreat_turn = 0
        self.escape_attempts = 0
        self.max_escape_attempts = 3
        self.consecutive_no_action = 0

    # ═══════════════════════════════════════════════════════════════════════════
    # 1. FAST WORLD SCANNER (DENGAN CACHING)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _update_world_state(self):
        """WORLD SCANNER - Update cepat dengan caching"""
        view = self.state
        self_section = view.get("self", {})
        
        # ── Self (minimal) ──
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
        self.my_atk = self_section.get("atk", 5)
        self.my_def = self_section.get("def", 2)
        
        # ── Cached Values ──
        self._cached_hp_percent = self.my_hp / self.my_max_hp
        self._cached_ep_percent = self.my_ep / self.my_max_ep
        self._cache_turn = self.turn
        
        # ── Inventory ──
        self.inventory = self_section.get("items", [])
        
        # ── Enemies ──
        self.visible_agents = view.get("visibleAgents", [])
        self.visible_monsters = view.get("visibleMonsters", [])
        
        # ── Items ──
        self.visible_items = view.get("visibleItems", [])
        
        # ── Map ──
        self.visible_ruins = view.get("visibleRuins", [])
        
        # ── Enemy Positions ──
        self.enemy_positions = []
        for agent in self.visible_agents:
            pos = agent.get("position", {})
            self.enemy_positions.append((pos.get("x", 0), pos.get("y", 0)))
        for monster in self.visible_monsters:
            pos = monster.get("position", {})
            self.enemy_positions.append((pos.get("x", 0), pos.get("y", 0)))
        
        # ── Death Zone ──
        dz = view.get("deathZone", {})
        self.death_zone_center = (
            dz.get("center", {}).get("x", 10),
            dz.get("center", {}).get("y", 10)
        )
        self.death_zone_radius = dz.get("radius", 10)
        
        # ── Update Cache ──
        self._cache_nearest_entities()
        
        # ── Log ──
        if self.turn % 5 == 0:
            logger.info(f"📊 T{self.turn}: HP={int(self._cached_hp_percent*100)}% "
                       f"EP={int(self._cached_ep_percent*100)}% "
                       f"Enemies={len(self.visible_agents)} Items={len(self.visible_items)}")
    
    def _cache_nearest_entities(self):
        """Cache nearest entities untuk kecepatan"""
        # Nearest Item
        if self.visible_items:
            self._cached_nearest_item = min(
                self.visible_items,
                key=lambda x: self._fast_distance(self.my_position, 
                    (x.get("position", {}).get("x", 0), x.get("position", {}).get("y", 0)))
            )
        else:
            self._cached_nearest_item = None
        
        # Nearest Enemy
        all_enemies = self.visible_agents + self.visible_monsters
        if all_enemies:
            self._cached_nearest_enemy = min(
                all_enemies,
                key=lambda x: self._fast_distance(self.my_position,
                    (x.get("position", {}).get("x", 0), x.get("position", {}).get("y", 0)))
            )
        else:
            self._cached_nearest_enemy = None
        
        # Nearest Ruin
        if self.visible_ruins:
            self._cached_nearest_ruin = min(
                self.visible_ruins,
                key=lambda x: self._fast_distance(self.my_position,
                    (x.get("position", {}).get("x", 0), x.get("position", {}).get("y", 0)))
            )
        else:
            self._cached_nearest_ruin = None
        
        # Danger Level
        self._cached_danger = self._fast_danger_calculation()
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 2. FAST MATH HELPERS (TANPA sqrt UNTUK KECEPATAN)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _fast_distance(self, pos1: Tuple[int, int], pos2: Tuple[int, int]) -> float:
        """Fast distance - tanpa sqrt untuk kecepatan"""
        dx = pos1[0] - pos2[0]
        dy = pos1[1] - pos2[1]
        return dx*dx + dy*dy  # Squared distance (cukup untuk perbandingan)
    
    def _fast_danger_calculation(self) -> float:
        """Fast danger calculation - tanpa sqrt"""
        danger = 0.0
        
        # HP danger
        hp_percent = self._cached_hp_percent
        if hp_percent < 0.3:
            danger += 0.5
        elif hp_percent < 0.5:
            danger += 0.3
        
        # Enemy danger (pakai squared distance)
        for pos in self.enemy_positions:
            dx = self.my_position[0] - pos[0]
            dy = self.my_position[1] - pos[1]
            dist_sq = dx*dx + dy*dy
            if dist_sq < self.DANGER_RANGE * self.DANGER_RANGE:
                danger += 0.3
        
        # Zone danger
        if self._fast_is_in_death_zone():
            danger += 0.3
        
        # Alert danger
        if self.alert_gauge > self.ALERT_HIGH:
            danger += 0.4
        elif self.alert_gauge > self.ALERT_MEDIUM:
            danger += 0.2
        
        return min(danger, 1.0)
    
    def _fast_is_in_death_zone(self) -> bool:
        """Fast death zone check - tanpa sqrt"""
        dx = self.my_position[0] - self.death_zone_center[0]
        dy = self.my_position[1] - self.death_zone_center[1]
        dist_sq = dx*dx + dy*dy
        radius_sq = (self.death_zone_radius - self.SAFE_ZONE_BUFFER) ** 2
        return dist_sq > radius_sq
    
    def _fast_get_safe_direction(self) -> str:
        """Fast safe direction - tanpa sqrt"""
        x, y = self.my_position
        cx, cy = self.death_zone_center
        
        dx = cx - x
        dy = cy - y
        
        if abs(dx) > abs(dy):
            return "right" if dx > 0 else "left"
        else:
            return "down" if dy > 0 else "up"
    
    def _fast_get_item_value(self, item: Dict) -> int:
        """Fast item value lookup"""
        item_type = item.get("type", "default").lower()
        return self.ITEM_VALUES.get(item_type, self.ITEM_VALUES["default"])
    
    def _fast_get_healing_item(self) -> Optional[Dict]:
        """Fast healing item lookup"""
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
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 3. DECISION ENGINE - CEPAT & TEPAT
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def _decide_action(self, threats: Dict):
        """
        DECISION ENGINE - Optimasi Kecepatan
        
        EARLY EXIT PATTERN:
        - Cek kondisi paling kritis dulu (survival)
        - Exit segera jika kondisi terpenuhi
        - Gunakan cached values
        """
        start_time = time.time()
        
        try:
            if self.is_dead or self.action_in_progress:
                return
            
            hp_percent = self._cached_hp_percent
            ep_percent = self._cached_ep_percent
            danger = self._cached_danger
            
            # ═══════════════════════════════════════════════════════════════════
            # EARLY EXIT 1: SURVIVAL (TERTINGGI)
            # ═══════════════════════════════════════════════════════════════════
            
            # 1a. Escape cave (FAST CHECK)
            if self.in_cave and self.cave_id:
                self.action_in_progress = True
                await self.websocket.send_action({
                    "type": "interact",
                    "interactableId": self.cave_id
                })
                self._log_decision("escape_cave", time.time() - start_time)
                return
            
            # 1b. Critical HP -> Heal (FASTEST)
            if hp_percent < self.HP_CRITICAL:
                heal_item = self._fast_get_healing_item()
                if heal_item:
                    self.action_in_progress = True
                    await self.websocket.send_action({
                        "type": "use_item",
                        "itemId": heal_item.get("id")
                    })
                    self.heals_used += 1
                    self._log_decision("critical_heal", time.time() - start_time)
                    return
                else:
                    # No healing item -> retreat
                    self.action_in_progress = True
                    await self._fast_retreat()
                    self._log_decision("critical_retreat", time.time() - start_time)
                    return
            
            # 1c. Very Low HP -> Retreat (FAST)
            if hp_percent < self.HP_VERY_LOW or danger > 0.6:
                self.action_in_progress = True
                await self._fast_retreat()
                self._log_decision("retreat", time.time() - start_time)
                return
            
            # 1d. In Death Zone -> Move to safe zone (FAST)
            if self._fast_is_in_death_zone():
                direction = self._fast_get_safe_direction()
                self.action_in_progress = True
                await self.websocket.send_action({
                    "type": "move",
                    "direction": direction
                })
                self._log_decision("safe_zone", time.time() - start_time)
                return
            
            # 1e. Alert too high -> Hide (FAST)
            if self.alert_gauge > self.ALERT_HIGH:
                self.action_in_progress = True
                await self._fast_retreat()
                self._log_decision("hide", time.time() - start_time)
                return
            
            # 1f. EP Critical -> Rest (FAST)
            if ep_percent < self.EP_CRITICAL:
                # Tidak action, biarkan EP regenerasi
                self._log_decision("rest", time.time() - start_time)
                return
            
            # ═══════════════════════════════════════════════════════════════════
            # EARLY EXIT 2: LOOT (CUKUP PENTING)
            # ═══════════════════════════════════════════════════════════════════
            
            if self.visible_items and hp_percent > self.HP_LOW:
                nearest = self._cached_nearest_item
                if nearest:
                    pos = nearest.get("position", {})
                    dist_sq = self._fast_distance(
                        self.my_position,
                        (pos.get("x", 0), pos.get("y", 0))
                    )
                    
                    if dist_sq <= self.LOOT_RANGE * self.LOOT_RANGE:
                        # Dalam range -> Collect
                        self.action_in_progress = True
                        await self.websocket.send_action({
                            "type": "collect",
                            "itemId": nearest.get("id")
                        })
                        self.items_collected += 1
                        self._log_decision("loot", time.time() - start_time)
                        return
                    elif dist_sq < 25:  # Jarak 5
                        # Move to item
                        self.action_in_progress = True
                        await self._fast_move_towards((pos.get("x", 0), pos.get("y", 0)))
                        self._log_decision("move_to_item", time.time() - start_time)
                        return
            
            # ═══════════════════════════════════════════════════════════════════
            # EARLY EXIT 3: KILL (JIKA MENGUNTUNGKAN)
            # ═══════════════════════════════════════════════════════════════════
            
            if hp_percent > self.HP_SAFE and ep_percent > self.EP_SAFE:
                target = self._fast_get_best_target()
                if target:
                    pos = target.get("position", {})
                    dist_sq = self._fast_distance(
                        self.my_position,
                        (pos.get("x", 0), pos.get("y", 0))
                    )
                    
                    if dist_sq <= self.ATTACK_RANGE * self.ATTACK_RANGE:
                        # Attack
                        self.action_in_progress = True
                        await self.websocket.send_action({
                            "type": "attack",
                            "targetId": target.get("id")
                        })
                        self._log_decision("attack", time.time() - start_time)
                        return
                    elif dist_sq < 36:  # Jarak 6
                        # Move to target
                        self.action_in_progress = True
                        await self._fast_move_towards((pos.get("x", 0), pos.get("y", 0)))
                        self._log_decision("move_to_target", time.time() - start_time)
                        return
            
            # ═══════════════════════════════════════════════════════════════════
            # EARLY EXIT 4: EXPLORE
            # ═══════════════════════════════════════════════════════════════════
            
            if self.visible_ruins and hp_percent > self.HP_LOW:
                nearest = self._cached_nearest_ruin
                if nearest:
                    pos = nearest.get("position", {})
                    dist_sq = self._fast_distance(
                        self.my_position,
                        (pos.get("x", 0), pos.get("y", 0))
                    )
                    explored = nearest.get("explored", 0)
                    
                    if dist_sq <= 4 and explored < 3:  # Jarak 2
                        self.action_in_progress = True
                        await self.websocket.send_action({
                            "type": "explore",
                            "ruinId": nearest.get("id")
                        })
                        self.ruins_explored += 1
                        self._log_decision("explore", time.time() - start_time)
                        return
                    elif dist_sq < 25:  # Jarak 5
                        self.action_in_progress = True
                        await self._fast_move_towards((pos.get("x", 0), pos.get("y", 0)))
                        self._log_decision("move_to_ruin", time.time() - start_time)
                        return
            
            # ═══════════════════════════════════════════════════════════════════
            # FALLBACK: MOVE (SIMPLE & CEPAT)
            # ═══════════════════════════════════════════════════════════════════
            
            self.action_in_progress = True
            if self._fast_is_in_death_zone():
                direction = self._fast_get_safe_direction()
                await self.websocket.send_action({
                    "type": "move",
                    "direction": direction
                })
            else:
                await self._fast_move_random()
            
            self._log_decision("move", time.time() - start_time)
            
        except Exception as e:
            logger.error(f"❌ Decision error: {e}")
            self.action_in_progress = False
            await self._fast_move_random()
        
        # Track decision time
        self.decision_time = time.time() - start_time
    
    def _log_decision(self, action: str, elapsed: float):
        """Log decision dengan waktu eksekusi"""
        if self.turn % 10 == 0:
            logger.debug(f"⚡ Decision: {action} ({elapsed*1000:.1f}ms)")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 4. FAST ACTION HELPERS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _fast_get_best_target(self) -> Optional[Dict]:
        """Fast target selection - cari HP terendah dalam range"""
        all_enemies = self.visible_agents + self.visible_monsters
        if not all_enemies:
            return None
        
        best_target = None
        best_score = -1
        
        for enemy in all_enemies:
            pos = enemy.get("position", {})
            dist_sq = self._fast_distance(
                self.my_position,
                (pos.get("x", 0), pos.get("y", 0))
            )
            
            if dist_sq > self.ATTACK_RANGE * self.ATTACK_RANGE:
                continue
            
            enemy_hp = enemy.get("hp", 100)
            
            # Simple score: HP rendah + jarak dekat
            score = (100 - enemy_hp) / 100  # 0-1
            if dist_sq > 0:
                score += 1 / (dist_sq + 1)  # Distance bonus
            
            if score > best_score:
                best_score = score
                best_target = enemy
        
        return best_target
    
    async def _fast_retreat(self):
        """Fast retreat - menjauh dari enemy terdekat"""
        if not self.enemy_positions:
            # Random retreat
            directions = ["up", "down", "left", "right"]
            direction = random.choice(directions)
        else:
            # Retreat away from nearest enemy
            nearest = min(
                self.enemy_positions,
                key=lambda p: self._fast_distance(self.my_position, p)
            )
            x, y = self.my_position
            ex, ey = nearest
            
            dx = x - ex
            dy = y - ey
            
            if abs(dx) > abs(dy):
                direction = "right" if dx > 0 else "left"
            else:
                direction = "down" if dy > 0 else "up"
        
        self.escape_attempts += 1
        await self.websocket.send_action({
            "type": "move",
            "direction": direction
        })
    
    async def _fast_move_towards(self, target_pos: Tuple[int, int]):
        """Fast move towards target"""
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
    
    async def _fast_move_random(self):
        """Fast random move"""
        directions = ["up", "down", "left", "right"]
        direction = random.choice(directions)
        await self.websocket.send_action({
            "type": "move",
            "direction": direction
        })
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 5. MAIN HANDLER
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def handle_message(self, data: Dict):
        """Main handler dengan fast decision"""
        msg_type = data.get("type")
        
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
                self.visible_agents = []
                if self.state.get("canAct", True) and not self.is_dead:
                    await self._decide_action({})
                return
        
        # ── ACTION RESULT ──
        if msg_type == "action_result":
            result = data.get("result", {})
            if result.get("success"):
                self.action_in_progress = False
                self.consecutive_no_action = 0
            else:
                error = result.get("error", {})
                error_code = error.get("code", "")
                
                if error_code == "AGENT_DEAD":
                    self.is_dead = True
                    self.websocket.is_alive = False
                    if self.websocket.on_game_ended:
                        self.websocket.on_game_ended()
                    return
                
                elif error_code in ["TARGET_DEAD", "ACTION_FAILED"]:
                    self.action_in_progress = False
                    self.visible_agents = []
                    if self.state.get("canAct", True):
                        await self._decide_action({})
                    return
                
                elif error_code == "NOT_ENOUGH_EP":
                    self.action_in_progress = False
                    return
            
            # Continue loop
            if self.state.get("canAct", True) and not self.is_dead:
                await self._decide_action({})
            return
        
        # ── AGENT VIEW ──
        if msg_type == "agent_view":
            self.state = data.get("view", {})
            self.turn += 1
            self.survival_time = self.turn
            
            # Fast update
            self._update_world_state()
            
            # Fast decision
            if data.get("canAct", True) and not self.is_dead:
                await self._decide_action({})
            
            self.loop_iteration += 1
        
        # ── TURN ADVANCED ──
        elif msg_type == "turn_advanced":
            self.turn += 1
            self.survival_time = self.turn
            if self.state.get("canAct", True) and not self.is_dead:
                await self._decide_action({})
