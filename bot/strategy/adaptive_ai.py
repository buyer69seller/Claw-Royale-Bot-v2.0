import random
import math
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from ..game.websocket import GameWebSocket
from ..utils.logger import logger

class ActionType(Enum):
    KILL = "kill"
    LOOT = "loot"
    HEAL = "heal"
    EQUIP = "equip"
    MOVE = "move"
    INTERACT = "interact"
    RETREAT = "retreat"
    EXPLORE = "explore"
    WAIT = "wait"

class ActionScore:
    """Scoring system untuk setiap aksi"""
    
    SCORE_KILL = 1000
    SCORE_SURVIVAL = 600
    SCORE_LOOT = 50
    SCORE_POSITION = 100
    SCORE_HEAL = 10
    SCORE_RETREAT = 200
    SCORE_EXPLORE = 150
    SCORE_EQUIP = 300
    
    PENALTY_BAD_FIGHT = -1000
    PENALTY_DEATH = -100000
    PENALTY_WASTE_TURN = -50
    
    @staticmethod
    def calculate_kill_score(target_hp: int, target_atk: int, 
                            my_hp: int, my_atk: int, distance: int) -> float:
        if target_hp <= 0:
            return -1000
        
        damage_per_turn = max(1, my_atk - target_atk // 2)
        turns_to_kill = max(1, target_hp // damage_per_turn)
        enemy_damage = max(1, target_atk - my_atk // 2)
        damage_taken = enemy_damage * turns_to_kill
        survival_chance = max(0, 1 - (damage_taken / max(1, my_hp)))
        distance_factor = max(0, 1 - (distance / 10))
        
        score = (ActionScore.SCORE_KILL * survival_chance * distance_factor) - (damage_taken * 10)
        
        if target_hp < 30:
            score += 200
        
        if target_atk > my_atk * 1.5:
            score += ActionScore.PENALTY_BAD_FIGHT
            
        return score
    
    @staticmethod
    def calculate_loot_score(item_value: int, distance: int, threat_level: float) -> float:
        if item_value <= 0:
            return -100
        
        distance_factor = max(0, 1 - (distance / 5))
        threat_penalty = threat_level * 200
        score = (ActionScore.SCORE_LOOT + item_value) * distance_factor - threat_penalty
        
        if item_value > 100:
            score += 100
            
        return score
    
    @staticmethod
    def calculate_heal_score(hp_recovered: int, current_hp: int, 
                            max_hp: int, threat_level: float) -> float:
        if current_hp >= max_hp:
            return -50
        
        hp_percent = current_hp / max_hp
        urgency = 1 - hp_percent
        score = ActionScore.SCORE_HEAL * hp_recovered * urgency
        
        if threat_level > 0.5 and hp_percent < 0.4:
            score += 300
            
        return score
    
    @staticmethod
    def calculate_position_score(position: Tuple[int, int], 
                               death_zone_center: Tuple[int, int],
                               death_zone_radius: int,
                               enemy_positions: List[Tuple[int, int]]) -> float:
        x, y = position
        cx, cy = death_zone_center
        distance_to_center = math.sqrt((x - cx)**2 + (y - cy)**2)
        safety_score = max(0, 1 - (distance_to_center / max(1, death_zone_radius)))
        
        enemy_density = 0
        for ex, ey in enemy_positions:
            dist = math.sqrt((x - ex)**2 + (y - ey)**2)
            if dist < 5:
                enemy_density += 1 / max(1, dist)
        
        score = ActionScore.SCORE_POSITION * safety_score - (enemy_density * 50)
        return score
    
    @staticmethod
    def calculate_retreat_score(threat_level: float, current_hp: int, 
                               max_hp: int, escape_chance: float) -> float:
        if threat_level < 0.3:
            return -50
        
        hp_percent = current_hp / max_hp
        urgency = 1 - hp_percent
        score = (ActionScore.SCORE_RETREAT * urgency * threat_level * escape_chance)
        
        if hp_percent < 0.2 and threat_level > 0.8:
            score += 1000
            
        return score

class AdaptiveAI:
    """Adaptive Combat AI dengan Scoring System"""
    
    def __init__(self, websocket: GameWebSocket):
        self.websocket = websocket
        self.state = {}
        self.turn = 0
        self.is_dead = False
        self.best_action = None
        self.action_history = []
        self.kills = 0
        self.damage_dealt = 0
        self.items_collected = 0
        self.survival_time = 0
        
        self.HP_CRITICAL = 0.20
        self.HP_LOW = 0.40
        self.HP_SAFE = 0.70
        
        self.weights = {
            "survival": 1.0,
            "aggression": 0.7,
            "greed": 0.5,
            "positioning": 0.8
        }
        
    async def handle_message(self, data: Dict):
        msg_type = data.get("type")
        
        if msg_type == "agent_died":
            meta = data.get("meta", {})
            if meta.get("youDied") == True:
                logger.info(f"💀 YOU DIED! Survival time: {self.survival_time}, Kills: {self.kills}")
                self.is_dead = True
                self.websocket.is_alive = False
                if self.websocket.on_game_ended:
                    self.websocket.on_game_ended()
                return
            else:
                logger.debug(f"💀 Agent died: {data.get('agentId')}")
                return
        
        if msg_type == "action_result":
            result = data.get("result", {})
            if not result.get("success"):
                error = result.get("error", {})
                if error.get("code") == "AGENT_DEAD":
                    logger.info(f"💀 YOU DIED! (via action_result)")
                    self.is_dead = True
                    self.websocket.is_alive = False
                    if self.websocket.on_game_ended:
                        self.websocket.on_game_ended()
                    return
        
        if msg_type == "agent_view":
            self.state = data.get("view", {})
            self.turn += 1
            self.survival_time = self.turn
            
            if data.get("canAct", True):
                await self._analyze_and_decide()
        
        elif msg_type == "turn_advanced":
            self.turn += 1
            self.survival_time = self.turn
            if self.state.get("canAct", True):
                await self._analyze_and_decide()
    
    async def _analyze_and_decide(self):
        try:
            world = self._analyze_world()
            threats = self._assess_threats(world)
            actions = self._score_actions(world, threats)
            
            if actions:
                best = max(actions, key=lambda x: x['score'])
                self.best_action = best
                
                if self.turn % 5 == 0:
                    logger.info(f"🎯 Turn {self.turn}: Best action = {best['action'].value} (score: {best['score']:.1f})")
                
                await self._execute_action(best)
            else:
                logger.warning("⚠️ No actions scored, moving randomly")
                await self._move_random()
                
        except Exception as e:
            logger.error(f"❌ AI error: {e}")
            await self._move_random()
    
    def _analyze_world(self) -> Dict:
        self_section = self.state.get("self", {})
        
        world = {
            "self": {
                "id": self_section.get("id"),
                "hp": self_section.get("hp", 100),
                "max_hp": self_section.get("maxHp", 100),
                "ep": self_section.get("ep", 50),
                "max_ep": self_section.get("maxEp", 50),
                "position": self_section.get("position", {"x": 0, "y": 0}),
                "in_cave": self_section.get("inCave", False),
                "alert": self_section.get("alertGauge", 0),
                "items": self_section.get("items", [])
            },
            "enemies": {
                "agents": self.state.get("visibleAgents", []),
                "monsters": self.state.get("visibleMonsters", [])
            },
            "items": self.state.get("visibleItems", []),
            "ruins": self.state.get("visibleRuins", []),
            "death_zone": self.state.get("deathZone", {"center": {"x": 10, "y": 10}, "radius": 10})
        }
        
        if self.turn % 10 == 0:
            hp = world["self"]["hp"]
            max_hp = world["self"]["max_hp"]
            enemies = len(world["enemies"]["agents"]) + len(world["enemies"]["monsters"])
            items = len(world["items"])
            logger.info(f"📊 Turn {self.turn}: HP={hp}/{max_hp}, Enemies={enemies}, Items={items}")
        
        return world
    
    def _assess_threats(self, world: Dict) -> Dict:
        threats = {
            "overall_threat": 0,
            "kill_chance": 0,
            "damage_received": 0,
            "escape_chance": 1.0,
            "targets": []
        }
        
        self_section = world["self"]
        my_hp = self_section["hp"]
        my_atk = 5
        my_def = 2
        
        all_enemies = world["enemies"]["agents"] + world["enemies"]["monsters"]
        
        for enemy in all_enemies:
            enemy_hp = enemy.get("hp", 100)
            enemy_atk = enemy.get("atk", 5)
            enemy_def = enemy.get("def", 2)
            distance = enemy.get("distance", 10)
            
            damage_per_turn = max(1, my_atk - enemy_def // 2)
            turns_to_kill = max(1, enemy_hp // damage_per_turn)
            enemy_damage = max(1, enemy_atk - my_def // 2)
            damage_received = enemy_damage * turns_to_kill
            threat_level = (enemy_atk / max(1, my_atk)) * (1 / max(1, distance))
            
            threats["targets"].append({
                "id": enemy.get("id"),
                "hp": enemy_hp,
                "atk": enemy_atk,
                "def": enemy_def,
                "distance": distance,
                "threat_level": threat_level,
                "kill_probability": max(0, 1 - (damage_received / max(1, my_hp))),
                "turns_to_kill": turns_to_kill,
                "damage_received": damage_received
            })
            
            threats["damage_received"] += damage_received / max(1, len(all_enemies))
            threats["overall_threat"] += threat_level
        
        hp_percent = my_hp / world["self"]["max_hp"]
        threats["escape_chance"] = max(0, 1 - threats["overall_threat"] / 10)
        
        pos = self_section["position"]
        dz = world["death_zone"]
        cx, cy = dz["center"]["x"], dz["center"]["y"]
        radius = dz["radius"]
        dx = pos["x"] - cx
        dy = pos["y"] - cy
        distance_to_center = math.sqrt(dx*dx + dy*dy)
        
        if distance_to_center > radius * 0.8:
            threats["overall_threat"] += 2
        
        if threats["targets"]:
            threats["kill_chance"] = max(t["kill_probability"] for t in threats["targets"])
        
        return threats
    
    def _score_actions(self, world: Dict, threats: Dict) -> List[Dict]:
        actions = []
        self_section = world["self"]
        
        # 1. KILL
        for target in threats["targets"]:
            if target["distance"] <= 3:
                score = ActionScore.calculate_kill_score(
                    target_hp=target["hp"],
                    target_atk=target["atk"],
                    my_hp=self_section["hp"],
                    my_atk=5,
                    distance=target["distance"]
                )
                score *= self.weights["aggression"]
                actions.append({
                    "action": ActionType.KILL,
                    "target_id": target["id"],
                    "score": score,
                    "details": f"Kill {target['id'][:8]} (HP: {target['hp']})"
                })
        
        # 2. LOOT
        for item in world["items"]:
            distance = item.get("distance", 10)
            item_value = item.get("value", 10)
            score = ActionScore.calculate_loot_score(
                item_value=item_value,
                distance=distance,
                threat_level=threats["overall_threat"]
            )
            score *= self.weights["greed"]
            actions.append({
                "action": ActionType.LOOT,
                "target_id": item.get("id"),
                "score": score,
                "details": f"Loot {item.get('name', 'item')} (value: {item_value})"
            })
        
        # 3. HEAL
        hp_percent = self_section["hp"] / self_section["max_hp"]
        if hp_percent < 0.8:
            for item in self_section["items"]:
                item_type = item.get("type", "")
                if "heal" in item_type.lower() or "potion" in item_type.lower():
                    hp_recovered = item.get("value", 20)
                    score = ActionScore.calculate_heal_score(
                        hp_recovered=hp_recovered,
                        current_hp=self_section["hp"],
                        max_hp=self_section["max_hp"],
                        threat_level=threats["overall_threat"]
                    )
                    actions.append({
                        "action": ActionType.HEAL,
                        "target_id": item.get("id"),
                        "score": score,
                        "details": f"Heal +{hp_recovered} HP"
                    })
        
        # 4. RETREAT
        if hp_percent < self.HP_LOW or threats["overall_threat"] > 5:
            score = ActionScore.calculate_retreat_score(
                threat_level=threats["overall_threat"],
                current_hp=self_section["hp"],
                max_hp=self_section["max_hp"],
                escape_chance=threats["escape_chance"]
            )
            
            pos = self_section["position"]
            dz = world["death_zone"]
            cx, cy = dz["center"]["x"], dz["center"]["y"]
            dx = cx - pos["x"]
            dy = cy - pos["y"]
            
            if abs(dx) > abs(dy):
                direction = "right" if dx > 0 else "left"
            else:
                direction = "down" if dy > 0 else "up"
            
            actions.append({
                "action": ActionType.RETREAT,
                "direction": direction,
                "score": score,
                "details": f"Retreat {direction} (threat: {threats['overall_threat']:.1f})"
            })
        
        # 5. EXPLORE
        for ruin in world["ruins"]:
            distance = ruin.get("distance", 10)
            explored = ruin.get("explored", 0)
            if distance <= 2 and explored < 3:
                score = ActionScore.SCORE_EXPLORE * (3 - explored) / 3
                score -= threats["overall_threat"] * 20
                actions.append({
                    "action": ActionType.EXPLORE,
                    "target_id": ruin.get("id"),
                    "score": score,
                    "details": f"Explore ruin ({explored}/3)"
                })
        
        # 6. POSITION (MOVE)
        pos = self_section["position"]
        dz = world["death_zone"]
        cx, cy = dz["center"]["x"], dz["center"]["y"]
        radius = dz["radius"]
        
        enemy_positions = [
            (e.get("position", {}).get("x", 0), e.get("position", {}).get("y", 0))
            for e in world["enemies"]["agents"] + world["enemies"]["monsters"]
        ]
        
        position_score = ActionScore.calculate_position_score(
            position=(pos["x"], pos["y"]),
            death_zone_center=(cx, cy),
            death_zone_radius=radius,
            enemy_positions=enemy_positions
        )
        
        if position_score < 50:
            dx = cx - pos["x"]
            dy = cy - pos["y"]
            if abs(dx) > abs(dy):
                direction = "right" if dx > 0 else "left"
            else:
                direction = "down" if dy > 0 else "up"
            
            score = position_score * self.weights["positioning"]
            actions.append({
                "action": ActionType.MOVE,
                "direction": direction,
                "score": score,
                "details": f"Move {direction} (position: {position_score:.1f})"
            })
        
        # 7. FALLBACK: Random move
        if not actions:
            directions = ["up", "down", "left", "right"]
            for direction in directions:
                actions.append({
                    "action": ActionType.MOVE,
                    "direction": direction,
                    "score": -10,
                    "details": f"Random move {direction}"
                })
        
        actions.sort(key=lambda x: x["score"], reverse=True)
        return actions
    
    async def _execute_action(self, action: Dict):
        action_type = action["action"]
        
        if action_type == ActionType.KILL:
            await self.websocket.send_action({
                "type": "attack",
                "targetId": action["target_id"]
            })
            self.kills += 1
            logger.info(f"⚔️ Attacking target (kill #{self.kills})")
            
        elif action_type == ActionType.LOOT:
            await self.websocket.send_action({
                "type": "collect",
                "itemId": action["target_id"]
            })
            self.items_collected += 1
            logger.info(f"📦 Collecting item #{self.items_collected}")
            
        elif action_type == ActionType.HEAL:
            await self.websocket.send_action({
                "type": "use_item",
                "itemId": action["target_id"]
            })
            logger.info(f"💊 Healing")
            
        elif action_type == ActionType.INTERACT:
            await self.websocket.send_action({
                "type": "interact",
                "interactableId": action["target_id"]
            })
            logger.info(f"🤝 Interacting")
            
        elif action_type == ActionType.EXPLORE:
            await self.websocket.send_action({
                "type": "explore",
                "ruinId": action["target_id"]
            })
            logger.info(f"🏛️ Exploring ruin")
            
        elif action_type == ActionType.RETREAT or action_type == ActionType.MOVE:
            direction = action.get("direction", "up")
            await self.websocket.send_action({
                "type": "move",
                "direction": direction
            })
            logger.debug(f"🚶 {action['details']}")
            
        else:
            logger.warning(f"⚠️ Unknown action: {action_type}")
    
    async def _move_random(self):
        directions = ["up", "down", "left", "right"]
        direction = random.choice(directions)
        await self.websocket.send_action({
            "type": "move",
            "direction": direction
        })
