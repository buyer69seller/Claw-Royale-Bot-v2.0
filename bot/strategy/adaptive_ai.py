import random
import math
from typing import Dict, List, Optional, Tuple
from ..game.websocket import GameWebSocket
from ..utils.logger import logger

class CompetitiveAI:
    """
    BOT KOMPETITIF - Claw Royale
    Continuous Loop: World Scanner → Threat Assessment → Decision Engine → Action Executor → Kembali ke World Scanner
    """
    
    def __init__(self, websocket: GameWebSocket):
        self.websocket = websocket
        
        # ── State ──
        self.state = {}
        self.turn = 0
        self.is_dead = False
        self.action_in_progress = False
        
        # ── Stats ──
        self.kills = 0
        self.items_collected = 0
        self.survival_time = 0
        self.damage_dealt = 0
        
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
        self.HP_LOW = 0.40
        self.HP_SAFE = 0.60
        
        self.LOOT_RANGE = 3
        self.ATTACK_RANGE = 3
        self.SAFE_ZONE_BUFFER = 2
        self.ALERT_THRESHOLD = 7
        
        # ── Item Values ──
        self.ITEM_VALUES = {
            "relic": 100,
            "pack": 80,
            "potion": 50,
            "herb": 30,
            "smoltz": 10,
            "default": 20
        }
        
        # ── Continuous Loop Control ──
        self.loop_iteration = 0
        self.last_action_time = 0
        
    async def handle_message(self, data: Dict):
        """
        ┌─────────────────────────────────────────────────────────────────────────────────┐
        │                         CONTINUOUS LOOP                                        │
        │                                                                                 │
        │  ┌───────────────────────────────────────────────────────────────────────────┐  │
        │  │  1. WORLD SCANNER ←─────────────────────────────────────────────────┐     │  │
        │  │     ↓                                                               │     │  │
        │  │  2. THREAT ASSESSMENT                                               │     │  │
        │  │     ↓                                                               │     │  │
        │  │  3. DECISION ENGINE (PRIORITY BASED)                                │     │  │
        │  │     ↓                                                               │     │  │
        │  │  4. ACTION EXECUTOR                                                 │     │  │
        │  │     ↓                                                               │     │  │
        │  │  5. WAIT FOR ACTION RESULT                                          │     │  │
        │  │     ↓                                                               │     │  │
        │  │  6. UPDATE STATE ───────────────────────────────────────────────────┘     │  │
        │  └───────────────────────────────────────────────────────────────────────────┘  │
        │                                                                                 │
        └─────────────────────────────────────────────────────────────────────────────────┘
        """
        msg_type = data.get("type")
        
        # ──────────────────────────────────────────────
        # 1. WORLD SCANNER - Update semua informasi
        # ──────────────────────────────────────────────
        if msg_type == "agent_view":
            self.state = data.get("view", {})
            self.turn += 1
            self.survival_time = self.turn
            self._update_world_state()
            
            # ── 2. THREAT ASSESSMENT ──
            threats = self._assess_threats()
            
            # ── 3. DECISION ENGINE ──
            if data.get("canAct", True) and not self.is_dead:
                await self._decide_action(threats)
            
            # ── 4. CONTINUOUS LOOP ──
            # Setelah action, loop kembali ke World Scanner (via agent_view berikutnya)
            self.loop_iteration += 1
            if self.loop_iteration % 10 == 0:
                logger.debug(f"🔄 Continuous Loop: {self.loop_iteration} iterations completed")
        
        elif msg_type == "turn_advanced":
            self.turn += 1
            self.survival_time = self.turn
            if self.state.get("canAct", True) and not self.is_dead:
                threats = self._assess_threats()
                await self._decide_action(threats)
        
        # ──────────────────────────────────────────────
        # 5. ACTION RESULT - Update state setelah action
        # ──────────────────────────────────────────────
        elif msg_type == "action_result":
            result = data.get("result", {})
            if result.get("success"):
                logger.debug("✅ Action successful")
                self.action_in_progress = False
            else:
                error = result.get("error", {})
                error_code = error.get("code", "")
                
                if error_code == "AGENT_DEAD":
                    logger.info(f"💀 YOU DIED! (via action_result)")
                    self.is_dead = True
                    self.websocket.is_alive = False
                    if self.websocket.on_game_ended:
                        self.websocket.on_game_ended()
                    return
                
                elif error_code == "TARGET_DEAD":
                    logger.debug("🎯 Target dead, refreshing...")
                    self.visible_agents = []
                    self.action_in_progress = False
                    # 🔄 Kembali ke World Scanner
                    if self.state.get("canAct", True):
                        threats = self._assess_threats()
                        await self._decide_action(threats)
                    return
                
                elif error_code == "ACTION_FAILED":
                    logger.debug(f"❌ Action failed: {error.get('message')}")
                    self.action_in_progress = False
                    # 🔄 Kembali ke World Scanner
                    if self.state.get("canAct", True):
                        threats = self._assess_threats()
                        await self._decide_action(threats)
                    return
                
                elif error_code == "NOT_ENOUGH_EP":
                    logger.debug("⚡ Not enough EP, waiting...")
                    self.action_in_progress = False
                    return
        
        # ──────────────────────────────────────────────
        # 6. DEATH DETECTION
        # ──────────────────────────────────────────────
        elif msg_type == "agent_died":
            meta = data.get("meta", {})
            if meta.get("youDied") == True:
                logger.info(f"💀 YOU DIED! Survival: {self.survival_time}, Kills: {self.kills}, Loot: {self.items_collected}")
                self.is_dead = True
                self.websocket.is_alive = False
                if self.websocket.on_game_ended:
                    self.websocket.on_game_ended()
                return
            else:
                logger.debug(f"💀 Agent died: {data.get('agentId')}")
                self.visible_agents = []
                # 🔄 Kembali ke World Scanner
                if self.state.get("canAct", True) and not self.is_dead:
                    threats = self._assess_threats()
                    await self._decide_action(threats)
    
    def _update_world_state(self):
        """1. WORLD SCANNER - Update semua informasi dunia"""
        view = self.state
        self_section = view.get("self", {})
        
        # ── Self Scan ──
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
        
        # ── Enemy Scan ──
        self.visible_agents = view.get("visibleAgents", [])
        self.visible_monsters = view.get("visibleMonsters", [])
        
        # ── Item Scan ──
        self.visible_items = view.get("visibleItems", [])
        
        # ── Map Scan ──
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
        
        # ── Log ──
        if self.turn % 5 == 0:
            hp_percent = int((self.my_hp / self.my_max_hp) * 100)
            logger.info(f"📊 T{self.turn}: HP={hp_percent}%, EP={self.my_ep}/{self.my_max_ep}, "
                       f"Pos=({self.my_position[0]},{self.my_position[1]}), "
                       f"Enemies={len(self.visible_agents)}, Items={len(self.visible_items)}, "
                       f"Kills={self.kills}")
    
    def _assess_threats(self) -> Dict:
        """2. THREAT ASSESSMENT - Analisis ancaman dan peluang"""
        threats = {
            "overall_threat": 0,
            "kill_chance": 0,
            "damage_received": 0,
            "escape_chance": 1.0,
            "best_target": None,
            "zone_threat": 0,
            "enemy_density": len(self.visible_agents) + len(self.visible_monsters)
        }
        
        # ── Zone Threat ──
        distance_to_center = self._get_distance(self.my_position, self.death_zone_center)
        threats["zone_threat"] = distance_to_center / max(1, self.death_zone_radius)
        
        # ── Enemy Threat ──
        all_enemies = self.visible_agents + self.visible_monsters
        if all_enemies:
            total_threat = 0
            best_target = None
            best_score = -1
            
            for enemy in all_enemies:
                pos = enemy.get("position", {})
                distance = self._get_distance(
                    self.my_position,
                    (pos.get("x", 0), pos.get("y", 0))
                )
                
                enemy_hp = enemy.get("hp", 100)
                enemy_atk = enemy.get("atk", 5)
                enemy_def = enemy.get("def", 2)
                
                # Kill probability
                damage_per_turn = max(1, self.my_atk - enemy_def // 2)
                turns_to_kill = max(1, enemy_hp // damage_per_turn)
                enemy_damage = max(1, enemy_atk - self.my_def // 2)
                damage_received = enemy_damage * turns_to_kill
                
                # Threat level
                threat_level = (enemy_atk / max(1, self.my_atk)) * (1 / max(1, distance))
                total_threat += threat_level
                
                # Best target score
                kill_score = (100 - enemy_hp) / 100
                distance_score = 1 / (1 + distance)
                risk_score = 1 - (damage_received / max(1, self.my_hp))
                score = kill_score * 0.5 + distance_score * 0.3 + risk_score * 0.2
                
                if score > best_score:
                    best_score = score
                    best_target = enemy
            
            threats["overall_threat"] = total_threat
            threats["best_target"] = best_target
            threats["kill_chance"] = best_score if best_score > 0 else 0
        
        # ── Escape Chance ──
        threats["escape_chance"] = max(0, 1 - threats["overall_threat"] / 10)
        
        return threats
    
    def _get_distance(self, pos1: Tuple[int, int], pos2: Tuple[int, int]) -> float:
        return math.sqrt((pos1[0] - pos2[0])**2 + (pos1[1] - pos2[1])**2)
    
    def _get_nearest_entity(self, entities: List, position_key: str = "position") -> Optional[Dict]:
        if not entities:
            return None
        
        def get_distance(entity):
            pos = entity.get(position_key, {})
            return self._get_distance(
                self.my_position,
                (pos.get("x", 0), pos.get("y", 0))
            )
        
        return min(entities, key=get_distance)
    
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
    
    def _get_item_value(self, item: Dict) -> int:
        item_type = item.get("type", "default").lower()
        return self.ITEM_VALUES.get(item_type, self.ITEM_VALUES["default"])
    
    async def _decide_action(self, threats: Dict):
        """
        3. DECISION ENGINE - Priority Based
        4. ACTION EXECUTOR - Execute selected action
        """
        try:
            if self.is_dead or self.action_in_progress:
                return
            
            hp_percent = self.my_hp / self.my_max_hp
            
            # ──────────────────────────────────────────────
            # PRIORITY 1: SURVIVAL
            # ──────────────────────────────────────────────
            
            # 1a. Escape cave
            if self.in_cave and self.cave_id:
                logger.info("🚪 Escaping cave...")
                self.action_in_progress = True
                await self.websocket.send_action({
                    "type": "interact",
                    "interactableId": self.cave_id
                })
                return
            
            # 1b. Heal if HP critical
            if hp_percent < self.HP_CRITICAL:
                logger.warning(f"⚠️ CRITICAL HP: {self.my_hp}/{self.my_max_hp}")
                
                self_section = self.state.get("self", {})
                items = self_section.get("items", [])
                
                healing_items = []
                for item in items:
                    item_type = item.get("type", "").lower()
                    if "heal" in item_type or "potion" in item_type or "herb" in item_type:
                        healing_items.append(item)
                
                if healing_items:
                    healing_items.sort(key=lambda x: x.get("value", 0), reverse=True)
                    best_item = healing_items[0]
                    logger.info(f"💊 Using: {best_item.get('name', 'heal')}")
                    self.action_in_progress = True
                    await self.websocket.send_action({
                        "type": "use_item",
                        "itemId": best_item.get("id")
                    })
                    return
                
                logger.warning("🏃 No healing - retreating!")
                self.action_in_progress = True
                await self._move_away_from_enemies()
                return
            
            # 1c. Retreat if HP low and enemies nearby
            if hp_percent < self.HP_LOW and self.visible_agents:
                logger.warning(f"⚠️ LOW HP: {self.my_hp}/{self.my_max_hp} - retreating!")
                self.action_in_progress = True
                await self._move_away_from_enemies()
                return
            
            # 1d. Move to safe zone if in death zone
            if self._is_in_death_zone():
                direction = self._get_safe_direction()
                logger.info(f"🏃 Moving to safe zone: {direction}")
                self.action_in_progress = True
                await self.websocket.send_action({
                    "type": "move",
                    "direction": direction
                })
                return
            
            # 1e. Hide if alert too high
            if self.alert_gauge > self.ALERT_THRESHOLD:
                logger.info(f"⚠️ Alert too high ({self.alert_gauge}) - hiding!")
                self.action_in_progress = True
                await self._move_away_from_enemies()
                return
            
            # ──────────────────────────────────────────────
            # PRIORITY 2: LOOT
            # ──────────────────────────────────────────────
            
            if self.visible_items:
                sorted_items = sorted(
                    self.visible_items,
                    key=lambda x: self._get_item_value(x),
                    reverse=True
                )
                
                for item in sorted_items:
                    pos = item.get("position", {})
                    distance = self._get_distance(
                        self.my_position,
                        (pos.get("x", 0), pos.get("y", 0))
                    )
                    
                    if distance <= self.LOOT_RANGE:
                        logger.info(f"📦 Looting: {item.get('name', 'item')} (value: {self._get_item_value(item)})")
                        self.action_in_progress = True
                        await self.websocket.send_action({
                            "type": "collect",
                            "itemId": item.get("id")
                        })
                        self.items_collected += 1
                        return
                    
                    elif distance < 5:
                        logger.info(f"🚶 Moving to item at distance {distance:.1f}")
                        self.action_in_progress = True
                        await self._move_towards((pos.get("x", 0), pos.get("y", 0)))
                        return
            
            # ──────────────────────────────────────────────
            # PRIORITY 3: KILL
            # ──────────────────────────────────────────────
            
            if hp_percent > self.HP_SAFE and threats.get("best_target"):
                target = threats.get("best_target")
                if target:
                    target_hp = target.get("hp", 100)
                    target_name = target.get("name", "enemy")
                    distance = self._get_distance(
                        self.my_position,
                        (target.get("position", {}).get("x", 0), target.get("position", {}).get("y", 0))
                    )
                    
                    if distance <= self.ATTACK_RANGE:
                        logger.info(f"⚔️ Attacking {target_name} (HP: {target_hp})")
                        self.action_in_progress = True
                        await self.websocket.send_action({
                            "type": "attack",
                            "targetId": target.get("id")
                        })
                        return
                    else:
                        # Move closer to target
                        logger.info(f"🚶 Moving to target at distance {distance:.1f}")
                        self.action_in_progress = True
                        await self._move_towards(
                            (target.get("position", {}).get("x", 0), 
                             target.get("position", {}).get("y", 0))
                        )
                        return
            
            # ──────────────────────────────────────────────
            # PRIORITY 4: EXPLORE
            # ──────────────────────────────────────────────
            
            if self.visible_ruins:
                nearest_ruin = self._get_nearest_entity(self.visible_ruins)
                if nearest_ruin:
                    pos = nearest_ruin.get("position", {})
                    distance = self._get_distance(
                        self.my_position,
                        (pos.get("x", 0), pos.get("y", 0))
                    )
                    explored = nearest_ruin.get("explored", 0)
                    
                    if distance <= 2 and explored < 3:
                        logger.info(f"🏛️ Exploring ruin ({explored}/3)")
                        self.action_in_progress = True
                        await self.websocket.send_action({
                            "type": "explore",
                            "ruinId": nearest_ruin.get("id")
                        })
                        return
                    
                    elif distance < 5:
                        logger.info(f"🚶 Moving to ruin at distance {distance:.1f}")
                        self.action_in_progress = True
                        await self._move_towards((pos.get("x", 0), pos.get("y", 0)))
                        return
            
            # ──────────────────────────────────────────────
            # PRIORITY 5: MOVE
            # ──────────────────────────────────────────────
            
            self.action_in_progress = True
            if self._is_in_death_zone():
                direction = self._get_safe_direction()
                await self.websocket.send_action({
                    "type": "move",
                    "direction": direction
                })
            else:
                await self._move_random()
            
        except Exception as e:
            logger.error(f"❌ Decision error: {e}")
            self.action_in_progress = False
            await self._move_random()
    
    # ──────────────────────────────────────────────
    # MOVEMENT HELPERS
    # ──────────────────────────────────────────────
    
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
    
    async def _move_away_from_enemies(self):
        if not self.enemy_positions:
            await self._move_random()
            return
        
        nearest = None
        nearest_dist = 999
        for pos in self.enemy_positions:
            dist = self._get_distance(self.my_position, pos)
            if dist < nearest_dist:
                nearest_dist = dist
                nearest = pos
        
        if nearest:
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
        else:
            await self._move_random()
    
    async def _move_random(self):
        directions = ["up", "down", "left", "right"]
        direction = random.choice(directions)
        logger.debug(f"🚶 Moving {direction} (random)")
        await self.websocket.send_action({
            "type": "move",
            "direction": direction
        })
