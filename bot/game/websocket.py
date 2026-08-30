import asyncio
import json
import websockets
from typing import Callable, Dict, Optional
from ..config import Config
from ..utils.logger import logger
from ..api.client import APIClient

class GameWebSocket:
    def __init__(self):
        self.client = APIClient()
        self.websocket = None
        self.game_id = None
        self.agent_id = None
        self.is_alive = True
        self.connected = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.base_backoff = 1
        self.max_backoff = 30
        self.on_game_ended = None
        self.self_token = None
        self.last_agent_view_time = 0
        self.join_attempts = 0
        self.max_join_attempts = 3
        
    async def connect(self, entry_type: str = "free") -> bool:
        """Connect ke Claw Royale via /ws/join"""
        try:
            version = await self.client.get_version()
            if not version:
                version = "1.15.0"
            
            headers = {
                "X-API-Key": Config.API_KEY,
                "X-Version": version,
                "User-Agent": f"ClawRoyaleBot/{Config.AGENT_NAME}"
            }
            
            logger.info(f"🔌 Connecting to {Config.WS_JOIN_URL}")
            
            try:
                self.websocket = await websockets.connect(
                    Config.WS_JOIN_URL,
                    extra_headers=headers,
                    max_size=10_000_000,
                    ping_interval=20,
                    ping_timeout=60,
                    close_timeout=10
                )
            except TypeError:
                try:
                    self.websocket = await websockets.connect(
                        Config.WS_JOIN_URL,
                        headers=headers,
                        max_size=10_000_000,
                        ping_interval=20,
                        ping_timeout=60
                    )
                except TypeError:
                    extra_headers_list = [
                        ("X-API-Key", Config.API_KEY),
                        ("X-Version", version),
                        ("User-Agent", f"ClawRoyaleBot/{Config.AGENT_NAME}")
                    ]
                    self.websocket = await websockets.connect(
                        Config.WS_JOIN_URL,
                        extra_headers=extra_headers_list,
                        max_size=10_000_000,
                        ping_interval=20,
                        ping_timeout=60
                    )
            
            logger.info("   ✅ WebSocket connected")
            
            # Welcome frame
            logger.info("   ⏳ Waiting for welcome frame...")
            welcome_raw = await asyncio.wait_for(self.websocket.recv(), timeout=10.0)
            welcome = json.loads(welcome_raw)
            
            decision = welcome.get("decision")
            logger.info(f"   📨 Welcome decision: {decision}")
            
            if decision == "BLOCKED":
                blocked_reason = welcome.get("reason", "Unknown")
                logger.error(f"   ❌ Blocked: {blocked_reason}")
                return False
            
            # Send hello
            hello_msg = {
                "type": "hello",
                "entryType": entry_type
            }
            logger.info(f"   📤 Sending hello: {hello_msg}")
            await self.websocket.send(json.dumps(hello_msg))
            
            # Wait for assigned
            logger.info("   ⏳ Waiting for assignment...")
            assigned_raw = await asyncio.wait_for(self.websocket.recv(), timeout=10.0)
            assigned = json.loads(assigned_raw)
            
            self.game_id = assigned.get("gameId")
            self.agent_id = assigned.get("agentId")
            self.self_token = self.agent_id
            
            # 🔥 CEK: Jika gameId None, berarti tidak ada game
            if self.game_id is None:
                logger.error("❌ No game assigned! gameId is None")
                logger.info("   ℹ️ This means no game available or server issue")
                await self.close()
                return False
            
            logger.info(f"   ✅ Assigned to game: {self.game_id}")
            if self.self_token:
                logger.info(f"   🎯 Self-token: {self.self_token}")
            
            self.connected = True
            self.is_alive = True
            self.reconnect_attempts = 0
            self.last_agent_view_time = asyncio.get_event_loop().time()
            self.join_attempts = 0
            return True
            
        except asyncio.TimeoutError:
            logger.error("❌ Connection timeout!")
            return False
        except websockets.WebSocketException as e:
            logger.error(f"❌ WebSocket error: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Connection error: {e}")
            return False
    
    async def resume_game(self, entry_type: str) -> bool:
        """Resume game yang sudah ada"""
        try:
            version = await self.client.get_version()
            if not version:
                version = "1.15.0"
            
            headers = {
                "X-API-Key": Config.API_KEY,
                "X-Version": version,
                "User-Agent": f"ClawRoyaleBot/{Config.AGENT_NAME}"
            }
            
            logger.info(f"🔌 Resuming {entry_type} game at {Config.WS_AGENT_URL}")
            
            try:
                self.websocket = await websockets.connect(
                    Config.WS_AGENT_URL,
                    extra_headers=headers,
                    max_size=10_000_000,
                    ping_interval=20,
                    ping_timeout=60,
                    close_timeout=10
                )
            except TypeError:
                try:
                    self.websocket = await websockets.connect(
                        Config.WS_AGENT_URL,
                        headers=headers,
                        max_size=10_000_000,
                        ping_interval=20,
                        ping_timeout=60
                    )
                except TypeError:
                    extra_headers_list = [
                        ("X-API-Key", Config.API_KEY),
                        ("X-Version", version),
                        ("User-Agent", f"ClawRoyaleBot/{Config.AGENT_NAME}")
                    ]
                    self.websocket = await websockets.connect(
                        Config.WS_AGENT_URL,
                        extra_headers=extra_headers_list,
                        max_size=10_000_000,
                        ping_interval=20,
                        ping_timeout=60
                    )
            
            self.connected = True
            self.is_alive = True
            self.reconnect_attempts = 0
            self.last_agent_view_time = asyncio.get_event_loop().time()
            logger.info("   ✅ Resumed successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Resume error: {e}")
            return False
    
    async def receive_loop(self, message_handler: Callable):
        """Main receive loop"""
        logger.info("🔄 Receive loop started")
        
        no_agent_view_count = 0
        max_no_agent_view = 10
        
        try:
            while self.websocket and self.is_alive and self.connected:
                try:
                    current_time = asyncio.get_event_loop().time()
                    
                    # 🔥 CEK: Jika tidak ada agent_view dalam 10 detik
                    if current_time - self.last_agent_view_time > 10:
                        no_agent_view_count += 1
                        
                        if no_agent_view_count >= max_no_agent_view:
                            logger.error("❌ No agent_view received! Game may be dead.")
                            self.is_alive = False
                            self.connected = False
                            if self.on_game_ended:
                                self.on_game_ended()
                            break
                    
                    message = await asyncio.wait_for(self.websocket.recv(), timeout=30.0)
                    data = json.loads(message)
                    msg_type = data.get("type")
                    
                    # 🔥 TRACK agent_view
                    if msg_type == "agent_view":
                        self.last_agent_view_time = current_time
                        no_agent_view_count = 0
                        logger.info(f"📨 [agent_view] Received! Turn: {data.get('turn', 'unknown')}")
                    
                    if msg_type not in ["agent_view", "turn_advanced"]:
                        logger.info(f"📨 [MSG] Type: {msg_type}")
                    
                    # ── DEATH DETECTION ──
                    if msg_type == "agent_died":
                        meta = data.get("meta", {})
                        if meta.get("youDied") == True:
                            logger.info("💀 YOU DIED!")
                            self.is_alive = False
                            self.connected = False
                            await message_handler(data)
                            if self.on_game_ended:
                                self.on_game_ended()
                            break
                        else:
                            logger.debug(f"💀 Agent died: {data.get('agentId')}")
                            continue
                    
                    if msg_type == "game_ended":
                        logger.info("🏁 GAME ENDED")
                        self.is_alive = False
                        self.connected = False
                        await message_handler(data)
                        if self.on_game_ended:
                            self.on_game_ended()
                        break
                    
                    # Handle normal message
                    await message_handler(data)
                    
                except asyncio.TimeoutError:
                    logger.warning("⚠️ Receive timeout, sending ping...")
                    try:
                        await self.websocket.send(json.dumps({"type": "ping"}))
                    except Exception as e:
                        logger.warning(f"⚠️ Ping failed: {e}")
                        if self.reconnect_attempts < self.max_reconnect_attempts:
                            wait = min(self.base_backoff * (2 ** self.reconnect_attempts), self.max_backoff)
                            self.reconnect_attempts += 1
                            logger.info(f"🔄 Reconnect backoff: {wait}s (attempt {self.reconnect_attempts})")
                            await asyncio.sleep(wait)
                            await self._reconnect()
                            if self.connected:
                                self.reconnect_attempts = 0
                        else:
                            logger.error("❌ Max reconnect attempts reached")
                            if self.on_game_ended:
                                self.on_game_ended()
                            break
                    continue
                    
        except websockets.WebSocketException as e:
            logger.error(f"❌ WebSocket error: {e}")
            if self.reconnect_attempts < self.max_reconnect_attempts:
                await self._reconnect()
            else:
                if self.on_game_ended:
                    self.on_game_ended()
        except Exception as e:
            logger.error(f"❌ Receive error: {e}")
            if self.on_game_ended:
                self.on_game_ended()
        finally:
            self.is_alive = False
            self.connected = False
            logger.info("🔄 Receive loop ended")
    
    async def _reconnect(self):
        try:
            if self.websocket:
                await self.websocket.close()
                self.websocket = None
            
            await asyncio.sleep(2)
            
            version = await self.client.get_version()
            if not version:
                version = "1.15.0"
            
            headers = {
                "X-API-Key": Config.API_KEY,
                "X-Version": version,
                "User-Agent": f"ClawRoyaleBot/{Config.AGENT_NAME}"
            }
            
            try:
                self.websocket = await websockets.connect(
                    Config.WS_AGENT_URL,
                    extra_headers=headers,
                    max_size=10_000_000,
                    ping_interval=20,
                    ping_timeout=60,
                    close_timeout=10
                )
            except TypeError:
                try:
                    self.websocket = await websockets.connect(
                        Config.WS_AGENT_URL,
                        headers=headers,
                        max_size=10_000_000,
                        ping_interval=20,
                        ping_timeout=60
                    )
                except TypeError:
                    extra_headers_list = [
                        ("X-API-Key", Config.API_KEY),
                        ("X-Version", version),
                        ("User-Agent", f"ClawRoyaleBot/{Config.AGENT_NAME}")
                    ]
                    self.websocket = await websockets.connect(
                        Config.WS_AGENT_URL,
                        extra_headers=extra_headers_list,
                        max_size=10_000_000,
                        ping_interval=20,
                        ping_timeout=60
                    )
            
            self.connected = True
            self.is_alive = True
            logger.info("✅ Reconnected successfully")
            
        except Exception as e:
            logger.error(f"❌ Reconnect failed: {e}")
    
    async def send_action(self, action: Dict) -> bool:
        try:
            if not self.websocket or not self.is_alive or not self.connected:
                return False
            
            action_type = action.get("type")
            logger.debug(f"📤 Action: {action_type}")
            
            await self.websocket.send(json.dumps(action))
            return True
            
        except Exception as e:
            logger.error(f"❌ Send action error: {e}")
            return False
    
    async def close(self):
        self.connected = False
        self.is_alive = False
        
        if self.websocket:
            try:
                await self.websocket.close()
                logger.info("🔌 WebSocket closed")
            except Exception as e:
                logger.warning(f"Error closing WebSocket: {e}")
            self.websocket = None
