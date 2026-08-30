import asyncio
import json
import websockets
from typing import Callable, Dict
from ..config import Config
from ..utils.logger import logger
from ..api.client import APIClient

class GameWebSocket:
    def __init__(self):
        self.client = APIClient()
        self.websocket = None
        self.game_id = None
        self.agent_id = None
        self.self_token = None
        self.is_alive = True
        self.entry_type = None
        self.connected = False
        
    async def connect(self, entry_type: str = "free") -> bool:
        try:
            version = await self.client.get_version()
            headers = {
                "X-API-Key": Config.API_KEY,
                "X-Version": version or "1.15.0"
            }
            
            logger.info(f"🔌 Connecting to {Config.WS_JOIN_URL}")
            self.websocket = await websockets.connect(
                Config.WS_JOIN_URL,
                extra_headers=headers,
                max_size=10_000_000,
                ping_interval=20,
                ping_timeout=60
            )
            self.entry_type = entry_type
            
            # Welcome
            welcome = json.loads(await asyncio.wait_for(self.websocket.recv(), timeout=10.0))
            logger.info(f"📨 Welcome: {welcome.get('decision')}")
            
            if welcome.get("decision") == "BLOCKED":
                logger.error(f"❌ Blocked: {welcome}")
                return False
            
            # Hello
            await self.websocket.send(json.dumps({"type": "hello", "entryType": entry_type}))
            
            # Assigned
            assigned = json.loads(await asyncio.wait_for(self.websocket.recv(), timeout=10.0))
            self.game_id = assigned.get("gameId")
            self.agent_id = assigned.get("agentId")
            self.self_token = self.agent_id
            
            logger.info(f"✅ Joined game: {self.game_id}")
            logger.info(f"🎯 Self-token: {self.self_token}")
            
            self.connected = True
            self.is_alive = True
            return True
            
        except Exception as e:
            logger.error(f"❌ Connection error: {e}")
            return False
    
    async def resume_game(self, entry_type: str) -> bool:
        try:
            version = await self.client.get_version()
            headers = {
                "X-API-Key": Config.API_KEY,
                "X-Version": version or "1.15.0"
            }
            
            self.websocket = await websockets.connect(
                Config.WS_AGENT_URL,
                extra_headers=headers,
                max_size=10_000_000,
                ping_interval=20,
                ping_timeout=60
            )
            self.entry_type = entry_type
            self.connected = True
            self.is_alive = True
            
            # Try to get game_id
            try:
                msg = json.loads(await asyncio.wait_for(self.websocket.recv(), timeout=5.0))
                self.game_id = msg.get("gameId") or msg.get("game_id")
            except:
                pass
            
            logger.info(f"✅ Resumed game: {self.game_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Resume error: {e}")
            return False
    
    async def receive_loop(self, message_handler: Callable):
        logger.info("🔄 Receive loop started")
        
        try:
            while self.websocket and self.is_alive and self.connected:
                try:
                    msg = json.loads(await asyncio.wait_for(self.websocket.recv(), timeout=30.0))
                    msg_type = msg.get("type")
                    
                    # Death detection
                    if msg_type == "agent_died" and msg.get("meta", {}).get("youDied") == True:
                        logger.info("💀 YOU DIED!")
                        self.is_alive = False
                        await message_handler(msg)
                        break
                    
                    if msg_type == "game_ended":
                        logger.info("🏁 GAME ENDED")
                        self.is_alive = False
                        await message_handler(msg)
                        break
                    
                    await message_handler(msg)
                    
                except asyncio.TimeoutError:
                    try:
                        await self.websocket.send(json.dumps({"type": "ping"}))
                        logger.debug("💓 Ping")
                    except:
                        logger.warning("⚠️ Ping failed")
                        break
                    
        except Exception as e:
            logger.error(f"❌ Receive error: {e}")
        finally:
            self.is_alive = False
            self.connected = False
            logger.info("🔄 Receive loop ended")
    
    async def send_action(self, action: Dict) -> bool:
        try:
            if not self.websocket or not self.is_alive or not self.connected:
                return False
            await self.websocket.send(json.dumps(action))
            logger.debug(f"📤 {action.get('type')}")
            return True
        except Exception as e:
            logger.error(f"❌ Send error: {e}")
            return False
    
    async def close(self):
        self.connected = False
        self.is_alive = False
        if self.websocket:
            try:
                await self.websocket.close()
            except:
                pass
            self.websocket = None