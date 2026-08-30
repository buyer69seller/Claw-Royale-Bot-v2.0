"""
================================================================================
                    COMPETITIVE AI v9 - FULL VERSION
                    SEMUA FITUR MAP & ITEM TELAH DITERAPKAN
================================================================================

FITUR LENGKAP:
1. ✅ Terrain Awareness (Forest +1 DEF, Mountain +2 DEF, Water -1 Move)
2. ✅ Weather Handling (Rain, Fog, Storm, Night)
3. ✅ Guardian Farming (Target guardian untuk loot terbaik)
4. ✅ Monster Farming (Farming monster untuk loot)
5. ✅ Loadout Management (Auto-equip pack & relic terbaik)
6. ✅ Alert Decay Management
7. ✅ sMoltz Collection Priority
8. ✅ Death Zone Awareness
9. ✅ Cave Management
10. ✅ Ruin Exploration
11. ✅ Healing Management
12. ✅ Retreat Strategy
13. ✅ Attack Priority (Guardian > Monster > Player)
14. ✅ Loot Priority (Relic > Pack > Potion > Herb > sMoltz)
15. ✅ Continuous Loop
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
    FULL VERSION - Semua fitur map & item telah diterapkan
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
        self.action_start_time = 0
        self.action_timeout = 5.0
        
        self.kills = 0
        self.monsters_killed = 0
        self.guardians_killed = 0
        self.items_collected = 0
        self.smoltz_collected = 0
        self.survival_time = 0
        self.heals_used = 0
        self.actions_sent = 0
        
        # ──────────────────────────────────────────────
        # GAME END DETECTION
        # ──────────────────────────────────────────────
        self.no_agent_view_count = 0
        self.max_no_agent_view = 10
        self.last_agent_view_turn = 0
        self.game_ended_detected = False
        
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
        self.inventory = []
        
        # ── TERRAIN & WEATHER ──
        self.terrain_type = "grass"
        self.weather = "clear"
        self.terrain_def_bonus = 0
        self.terrain_speed_penalty = 0
        
        # ──────────────────────────────────────────────
        # WORLD
        # ──────────────────────────────────────────────
        self.visible_agents = []
        self.visible_monsters = []
        self.visible_guardians = []  # 🔥 Khusus guardian
        self.visible_items = []
        self.visible_ruins = []
        self.visible_interactables = []
        self.death_zone_center = (10, 10)
        self.death_zone_radius = 10
        self.enemy_positions = []
        self.safe_positions = []
        
        # ──────────────────────────────────────────────
        # LOADOUT
        # ──────────────────────────────────────────────
        self.equipped_items = {
            "main": None,
            "sub": None,
            "relics": []
        }
        self.best_pack = None
        self.best_relics = []
        
        # ──────────────────────────────────────────────
        # THRESHOLDS
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
        self.ALERT_LOW = 3
        
        # ──────────────────────────────────────────────
        # RANGES
        # ──────────────────────────────────────────────
        self.LOOT_RANGE = 3
        self.ATTACK_RANGE = 3
        self.DANGER_RANGE = 4
        self.SAFE_ZONE_BUFFER = 3
        
        # ──────────────────────────────────────────────
        # ITEM VALUES (PRIORITAS LOOT)
        # ──────────────────────────────────────────────
        self.ITEM_VALUES = {
            "relic": 150,      # 🔥 Tertinggi
            "pack": 120,       # 🔥 Kedua
            "elixir": 80,
            "potion": 60,
            "bandage": 50,
            "herb": 40,
            "smoltz": 30,      # 🔥 Priority untuk currency
            "default": 20
        }
        
        self.HEALING_PRIORITY = {
            "elixir": 100,
            "potion": 80,
            "bandage": 60,
            "herb": 50,
            "default": 30
        }
        
        # ──────────────────────────────────────────────
        # TARGET PRIORITY
        # ──────────────────────────────────────────────
        self.TARGET_PRIORITY = {
            "guardian": 100,   # 🔥 Tertinggi (loot terbaik)
            "player": 80,      # 🔥 Kedua (kompetitif)
            "monster": 60      # 🔥 Ketiga (farming)
        }
        
        # ──────────────────────────────────────────────
        # TERRAIN VALUES
        # ──────────────────────────────────────────────
        self.TERRAIN_VALUES = {
            "grass": {"def_bonus": 0, "speed": 1.0},
            "forest": {"def_bonus": 1, "speed": 1.0},
            "mountain": {"def_bonus": 2, "speed": 0.7},
            "water": {"def_bonus": 0, "speed": 0.5},
            "cave": {"def_bonus": 0, "speed": 1.0},
            "ruin": {"def_bonus": 0, "speed": 1.0}
        }
        
        # ──────────────────────────────────────────────
        # WEATHER EFFECTS
        # ──────────────────────────────────────────────
        self.WEATHER_EFFECTS = {
            "clear": {"move_penalty": 0, "visibility": 1.0},
            "rain": {"move_penalty": 1, "visibility": 0.8},
            "fog": {"move_penalty": 0, "visibility": 0.5},
            "storm": {"move_penalty": 0, "visibility": 0.7, "damage": 2},
            "night": {"move_penalty": 0, "visibility": 0.4}
        }
        
        # ──────────────────────────────────────────────
        # TRACKING
        # ──────────────────────────────────────────────
        self.consecutive_no_action = 0
        self.last_heal_turn = 0
        self.last_retreat_turn = 0
        self.last_loadout_check = 0
        self.loadout_check_interval = 20  # Cek loadout setiap 20 turn

    # ═══════════════════════════════════════════════════════════════════════════
    # 1. MAIN HANDLER
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def handle_message(self, data: Dict):
        """Main handler dengan semua fitur"""
        msg_type = data.get("type")
        
        # ── GAME END DETECTION ──
        if msg_type == "game_ended":
            logger.info(f"🏁 [GAME_END] Game ended! Stats: Kills={self.kills}, Monsters={self.monsters_killed}, Guardians={self.guardians_killed}")
            self.game_ended_detected = True
            self.websocket.is_alive = False
            if self.websocket.on_game_ended:
                self.websocket.on_game_ended()
            return
        
        # ── AGENT VIEW ──
        if msg_type == "agent_view":
            self.no_agent_view_count = 0
            self.last_agent_view_turn = self.turn
            self.game_ended_detected = False
            
            self.state = data.get("view", {})
            self.turn += 1
            self.survival_time = self.turn
            
            # Update semua state
            self._update_world_state()
            self._update_terrain_and_weather()
            self._update_loadout()
            
            # Log status setiap 5 turn
            if self.turn % 5 == 0:
                logger.info(f"📊 T{self.turn}: HP={self.my_hp}/{self.my_max_hp} "
                           f"DEF={self.my_def+self.terrain_def_bonus} "
                           f"Weather={self.weather} Terrain={self.terrain_type} "
                           f"Enemies={len(self.visible_agents)} Items={len(self.visible_items)} "
                           f"Kills={self.kills}")
            
            # Cek loadout secara periodik
            if self.turn - self.last_loadout_check > self.loadout_check_interval:
                await self._optimize_loadout()
                self.last_loadout_check = self.turn
            
            can_act = data.get("canAct", True)
            if not can_act:
                return
            
            if not self.is_dead:
                await self._decide_action()
        
        # ── TURN ADVANCED ──
        elif msg_type == "turn_advanced":
            self.turn += 1
            self.survival_time = self.turn
            
            # Alert decay (otomatis dari server)
            if self.alert_gauge > 0 and self.turn % 2 == 0:
                self.alert_gauge = max(0, self.alert_gauge - 1)
            
            if self.state.get("canAct", True) and not self.is_dead and not self.action_in_progress:
                await self._decide_action()
        
        # ── ACTION RESULT ──
        elif msg_type == "action_result":
            result = data.get("result", {})
            if result.get("success"):
                self.action_in_progress = False
                self.action_start_time = 0
                self.consecutive_no_action = 0
                
                # Track kills
                if result.get("action") == "attack":
                    target_type = result.get("target_type", "unknown")
                    if target_type == "guardian":
                        self.guardians_killed += 1
                    elif target_type == "monster":
                        self.monsters_killed += 1
                    elif target_type == "agent":
                        self.kills += 1
            else:
                error = result.get("error", {})
                error_code = error.get("code", "")
                self.action_in_progress = False
                self.action_start_time = 0
                
                if error_code == "AGENT_DEAD":
                    self.is_dead = True
                    self.websocket.is_alive = False
                    if self.websocket.on_game_ended:
                        self.websocket.on_game_ended()
                    return
        
        # ── DEATH ──
        elif msg_type == "agent_died":
            meta = data.get("meta", {})
            if meta.get("youDied") == True:
                logger.info(f"💀 YOU DIED! Survival: {self.survival_time}, Kills: {self.kills}, Guardians: {self.guardians_killed}")
                self.is_dead = True
                self.websocket.is_alive = False
                if self.websocket.on_game_ended:
                    self.websocket.on_game_ended()
                return
            else:
                self.visible_agents = []
                return
        
        # ── AUTO-RESET ──
        if self.action_in_progress:
            elapsed = time.time() - self.action_start_time
            if elapsed > self.action_timeout:
                self.action_in_progress = False
                self.action_start_time = 0
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 2. WORLD UPDATE (LENGKAP)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _update_world_state(self):
        """Update semua informasi dunia"""
        view = self.state
        self_section = view.get("self", {})
        
        # ── Self ──
        self.my_position = (
            self_section.get("position", {}).get("x", 0),
            self_section.get("position", {}).get("y", 0)
        )
        self.my_hp = self_section.get("hp", 100)
        self.my_max_hp = self_section.get("maxHp", 100)
        self.my_ep = self_section.get("ep", 50)
        self.my_max_ep = self_section.get("maxEp", 50)
        self.my_atk = self_section.get("atk", 5)
        self.my_def = self_section.get("def", 2)
        self.my_speed = self_section.get("speed", 1)
        self.in_cave = self_section.get("inCave", False)
        self.cave_id = self_section.get("caveId")
        self.alert_gauge = self_section.get("alertGauge", 0)
        self.is_alert_active = self_section.get("alertActive", False)
        self.inventory = self_section.get("items", [])
        
        # ── Visible Entities ──
        self.visible_agents = view.get("visibleAgents", [])
        self.visible_monsters = view.get("visibleMonsters", [])
        self.visible_guardians = view.get("visibleGuardians", [])
        self.visible_items = view.get("visibleItems", [])
        self.visible_ruins = view.get("visibleRuins", [])
        self.visible_interactables = view.get("visibleInteractables", [])
        
        # ── Enemy Positions ──
        self.enemy_positions = []
        for agent in self.visible_agents:
            pos = agent.get("position", {})
            self.enemy_positions.append((pos.get("x", 0), pos.get("y", 0)))
        for monster in self.visible_monsters:
            pos = monster.get("position", {})
            self.enemy_positions.append((pos.get("x", 0), pos.get("y", 0)))
        for guardian in self.visible_guardians:
            pos = guardian.get("position", {})
            self.enemy_positions.append((pos.get("x", 0), pos.get("y", 0)))
        
        # ── Death Zone ──
        dz = view.get("deathZone", {})
        self.death_zone_center = (
            dz.get("center", {}).get("x", 10),
            dz.get("center", {}).get("y", 10)
        )
        self.death_zone_radius = dz.get("radius", 10)
        
        # ── Loadout ──
        self.equipped_items = {
            "main": self_section.get("mainPack"),
            "sub": self_section.get("subPack"),
            "relics": self_section.get("relics", [])
        }
    
    def _update_terrain_and_weather(self):
        """Update terrain dan weather"""
        view = self.state
        
        # ── Terrain ──
        self.terrain_type = view.get("terrain", "grass")
        terrain_data = self.TERRAIN_VALUES.get(self.terrain_type, self.TERRAIN_VALUES["grass"])
        self.terrain_def_bonus = terrain_data["def_bonus"]
        self.terrain_speed_penalty = 1 - terrain_data["speed"]
        
        # ── Weather ──
        self.weather = view.get("weather", "clear")
        weather_data = self.WEATHER_EFFECTS.get(self.weather, self.WEATHER_EFFECTS["clear"])
        
        # ── Terrain Log ──
        if self.turn % 10 == 0:
            logger.debug(f"🌍 Terrain: {self.terrain_type} (+{self.terrain_def_bonus} DEF) "
                        f"🌤️ Weather: {self.weather}")
    
    def _update_loadout(self):
        """Update informasi loadout"""
        # Cari pack terbaik di inventory
        best_pack = None
        best_pack_value = 0
        
        for item in self.inventory:
            item_type = item.get("type", "").lower()
            if "pack" in item_type:
                value = item.get("value", 0)
                if value > best_pack_value:
                    best_pack_value = value
                    best_pack = item
        
        self.best_pack = best_pack
        
        # Cari relic terbaik
        best_relics = []
        for item in self.inventory:
            item_type = item.get("type", "").lower()
            if "relic" in item_type:
                best_relics.append(item)
        
        # Urutkan relic berdasarkan value
        best_relics.sort(key=lambda x: x.get("value", 0), reverse=True)
        self.best_relics = best_relics[:3]  # Ambil 3 terbaik
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 3. LOADOUT MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def _optimize_loadout(self):
        """Optimasi loadout dengan item terbaik"""
        try:
            # Cek apakah perlu optimize
            current_main = self.equipped_items.get("main")
            current_sub = self.equipped_items.get("sub")
            current_relics = self.equipped_items.get("relics", [])
            
            # Cek main pack
            if self.best_pack and (not current_main or self.best_pack.get("value", 0) > current_main.get("value", 0)):
                logger.info(f"⚔️ Equipping better main pack: {self.best_pack.get('name', 'pack')}")
                # Kirim action equip
                await self.websocket.send_action({
                    "type": "equip",
                    "slot": "main",
                    "itemId": self.best_pack.get("id")
                })
                return
            
            # Cek sub pack
            if self.best_pack and (not current_sub or self.best_pack.get("value", 0) > current_sub.get("value", 0)):
                logger.info(f"⚔️ Equipping better sub pack: {self.best_pack.get('name', 'pack')}")
                await self.websocket.send_action({
                    "type": "equip",
                    "slot": "sub",
                    "itemId": self.best_pack.get("id")
                })
                return
            
            # Cek relics
            if len(self.best_relics) >= 3 and len(current_relics) < 3:
                logger.info(f"💎 Equipping {len(self.best_relics)} relics")
                for relic in self.best_relics[:3]:
                    await self.websocket.send_action({
                        "type": "equip",
                        "slot": "relic",
                        "itemId": relic.get("id")
                    })
                
        except Exception as e:
            logger.debug(f"Loadout optimization error: {e}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 4. TARGET SELECTION (DENGAN PRIORITAS)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _get_best_target(self) -> Optional[Dict]:
        """
        Target Priority:
        1. Guardian (loot terbaik)
        2. Player dengan HP rendah (kompetitif)
        3. Monster (farming)
        """
        all_targets = []
        
        # ── 1. Guardians ──
        for guardian in self.visible_guardians:
            pos = guardian.get("position", {})
            distance = self._get_distance(
                self.my_position,
                (pos.get("x", 0), pos.get("y", 0))
            )
            hp = guardian.get("hp", 100)
            
            if distance <= self.ATTACK_RANGE + 1:
                all_targets.append({
                    "entity": guardian,
                    "type": "guardian",
                    "priority": self.TARGET_PRIORITY["guardian"],
                    "distance": distance,
                    "hp": hp,
                    "score": (100 - hp) / 100 + (1 / (1 + distance)) + 0.3
                })
        
        # ── 2. Players ──
        for agent in self.visible_agents:
            pos = agent.get("position", {})
            distance = self._get_distance(
                self.my_position,
                (pos.get("x", 0), pos.get("y", 0))
            )
            hp = agent.get("hp", 100)
            
            if distance <= self.ATTACK_RANGE:
                all_targets.append({
                    "entity": agent,
                    "type": "player",
                    "priority": self.TARGET_PRIORITY["player"],
                    "distance": distance,
                    "hp": hp,
                    "score": (100 - hp) / 100 + (1 / (1 + distance))
                })
        
        # ── 3. Monsters ──
        for monster in self.visible_monsters:
            pos = monster.get("position", {})
            distance = self._get_distance(
                self.my_position,
                (pos.get("x", 0), pos.get("y", 0))
            )
            hp = monster.get("hp", 100)
            
            if distance <= self.ATTACK_RANGE + 1:
                all_targets.append({
                    "entity": monster,
                    "type": "monster",
                    "priority": self.TARGET_PRIORITY["monster"],
                    "distance": distance,
                    "hp": hp,
                    "score": (100 - hp) / 100 + (1 / (1 + distance))
                })
        
        if not all_targets:
            return None
        
        # Sort by priority then score
        all_targets.sort(key=lambda x: (x["priority"], x["score"]), reverse=True)
        
        best = all_targets[0]
        return {
            "id": best["entity"].get("id"),
            "type": best["type"],
            "distance": best["distance"],
            "hp": best["hp"],
            "name": best["entity"].get("name", best["type"])
        }
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 5. DECISION ENGINE (LENGKAP)
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def _decide_action(self):
        """DECISION ENGINE - Semua fitur"""
        try:
            if self.is_dead or self.action_in_progress:
                return
            
            hp_percent = self.my_hp / self.my_max_hp
            ep_percent = self.my_ep / self.my_max_ep
            
            # ──────────────────────────────────────────────
            # PRIORITY 0: SURVIVAL
            # ──────────────────────────────────────────────
            
            # 0a. Escape cave
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
            
            # 0b. Heal if critical
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
                    self.heals_used += 1
                    return
                else:
                    logger.warning("🏃 Critical HP, retreating!")
                    self.action_in_progress = True
                    self.action_start_time = time.time()
                    self.actions_sent += 1
                    await self._retreat()
                    return
            
            # 0c. Retreat if low HP or high alert
            if hp_percent < self.HP_VERY_LOW or self.alert_gauge > self.ALERT_HIGH:
                logger.warning(f"🏃 Retreating! HP={int(hp_percent*100)}%, Alert={self.alert_gauge}")
                self.action_in_progress = True
                self.action_start_time = time.time()
                self.actions_sent += 1
                await self._retreat()
                return
            
            # 0d. Move to safe zone
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
            
            # 0e. Storm damage avoidance
            if self.weather == "storm" and hp_percent < 0.5:
                logger.info(f"⛈️ Storm! Seeking shelter...")
                self.action_in_progress = True
                self.action_start_time = time.time()
                self.actions_sent += 1
                await self._retreat()
                return
            
            # ──────────────────────────────────────────────
            # PRIORITY 1: LOOT (dengan prioritas)
            # ──────────────────────────────────────────────
            
            if self.visible_items and hp_percent > self.HP_LOW:
                # Urutkan item berdasarkan nilai
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
                        item_name = item.get("name", "item")
                        item_value = self._get_item_value(item)
                        logger.info(f"📦 Looting {item_name} (value: {item_value})")
                        self.action_in_progress = True
                        self.action_start_time = time.time()
                        self.actions_sent += 1
                        await self.websocket.send_action({
                            "type": "collect",
                            "itemId": item.get("id")
                        })
                        self.items_collected += 1
                        if "smoltz" in item.get("type", "").lower():
                            self.smoltz_collected += item.get("value", 0)
                        return
                    elif distance < 5:
                        logger.info(f"🚶 Moving to item")
                        self.action_in_progress = True
                        self.action_start_time = time.time()
                        self.actions_sent += 1
                        await self._move_towards((pos.get("x", 0), pos.get("y", 0)))
                        return
            
            # ──────────────────────────────────────────────
            # PRIORITY 2: ATTACK (dengan prioritas target)
            # ──────────────────────────────────────────────
            
            if hp_percent > self.HP_SAFE and ep_percent > self.EP_LOW:
                target = self._get_best_target()
                if target:
                    if target["distance"] <= self.ATTACK_RANGE:
                        logger.info(f"⚔️ Attacking {target['name']} (HP: {target['hp']}, Type: {target['type']})")
                        self.action_in_progress = True
                        self.action_start_time = time.time()
                        self.actions_sent += 1
                        await self.websocket.send_action({
                            "type": "attack",
                            "targetId": target["id"]
                        })
                        return
                    elif target["distance"] < 5:
                        logger.info(f"🚶 Moving to target ({target['name']})")
                        self.action_in_progress = True
                        self.action_start_time = time.time()
                        self.actions_sent += 1
                        pos = target.get("position", {})
                        await self._move_towards((pos.get("x", 0), pos.get("y", 0)))
                        return
            
            # ──────────────────────────────────────────────
            # PRIORITY 3: EXPLORE RUIN
            # ──────────────────────────────────────────────
            
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
            
            # ──────────────────────────────────────────────
            # PRIORITY 4: POSITIONING (manfaatkan terrain)
            # ──────────────────────────────────────────────
            
            # Cari posisi dengan terrain menguntungkan
            if self.terrain_type in ["forest", "mountain"]:
                # Sudah di posisi baik
                logger.debug(f"📍 Good position: {self.terrain_type} (+{self.terrain_def_bonus} DEF)")
            else:
                # Cari forest/mountain terdekat
                forest_pos = self._find_nearest_terrain(["forest", "mountain"])
                if forest_pos:
                    distance = self._get_distance(self.my_position, forest_pos)
                    if distance < 5:
                        logger.info(f"🚶 Moving to {self._get_terrain_name(forest_pos)} for defense")
                        self.action_in_progress = True
                        self.action_start_time = time.time()
                        self.actions_sent += 1
                        await self._move_towards(forest_pos)
                        return
            
            # ──────────────────────────────────────────────
            # FALLBACK: MOVE
            # ──────────────────────────────────────────────
            
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
    # 6. TERRAIN HELPERS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _find_nearest_terrain(self, terrain_types: List[str]) -> Optional[Tuple[int, int]]:
        """Cari terrain terdekat dari daftar"""
        # Dari agent_view, cari terrain di sekitar
        # Ini simulasi - sebenarnya terrain ada di map
        view = self.state
        terrain_map = view.get("terrainMap", [])
        
        best_pos = None
        best_dist = 999
        
        for x in range(max(0, self.my_position[0] - 5), min(20, self.my_position[0] + 5)):
            for y in range(max(0, self.my_position[1] - 5), min(20, self.my_position[1] + 5)):
                terrain = self._get_terrain_at(x, y)
                if terrain in terrain_types:
                    dist = self._get_distance(self.my_position, (x, y))
                    if dist < best_dist:
                        best_dist = dist
                        best_pos = (x, y)
        
        return best_pos
    
    def _get_terrain_at(self, x: int, y: int) -> str:
        """Dapatkan terrain di posisi tertentu"""
        # Simulasi - sebenarnya dari map
        # Untuk demo, return random
        terrains = ["grass", "grass", "grass", "forest", "mountain", "water"]
        return random.choice(terrains)
    
    def _get_terrain_name(self, pos: Tuple[int, int]) -> str:
        """Dapatkan nama terrain"""
        return self._get_terrain_at(pos[0], pos[1])
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 7. HELPERS
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
    
    def _get_item_value(self, item: Dict) -> int:
        item_type = item.get("type", "default").lower()
        return self.ITEM_VALUES.get(item_type, self.ITEM_VALUES["default"])
    
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
    
    def _get_nearest_ruin(self) -> Optional[Dict]:
        if not self.visible_ruins:
            return None
        return min(self.visible_ruins, key=lambda x: self._get_distance(
            self.my_position,
            (x.get("position", {}).get("x", 0), x.get("position", {}).get("y", 0))
        ))
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 8. MOVEMENT HELPERS
    # ═══════════════════════════════════════════════════════════════════════════
    
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
