import asyncio
import time
from .state.router import StateRouter, AgentState
from .api.client import APIClient
from .game.websocket import GameWebSocket
from .strategy.loadout import LoadoutManager
from .strategy.gameplay import GameStrategy
from .utils.logger import logger
from .config import Config

class Heartbeat:
    def __init__(self):
        self.router = StateRouter()
        self.client = APIClient()
        self.loadout_manager = LoadoutManager()
        self.websocket = None
        self.strategy = None
        self.running = True
        self.login_attempted = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.base_backoff = 1
        self.max_backoff = 30
        self.last_game_id = None
        self.supervisor_retry_count = 0
        self.max_supervisor_retries = 10
        self.setup_attempted = False
        
    async def run(self):
        logger.info(f"Starting Claw Royale Bot: {Config.AGENT_NAME}")
        logger.info("=" * 50)
        logger.info("🦞 CLAW ROYALE BOT - SUPERVISOR ENABLED")
        logger.info("=" * 50)
        
        if self.client._has_api_key():
            await self._login()
        else:
            logger.error("❌ API_KEY is not configured!")
            return
        
        if not self.setup_attempted:
            await self._auto_setup()
        
        while self.running:
            try:
                await self._main_loop()
            except Exception as e:
                self.supervisor_retry_count += 1
                logger.error(f"❌ Supervisor caught error: {e}")
                logger.info(f"   Retry #{self.supervisor_retry_count}/{self.max_supervisor_retries}")
                
                if self.supervisor_retry_count >= self.max_supervisor_retries:
                    logger.error("❌ Max supervisor retries reached. Stopping...")
                    break
                
                wait_time = min(self.base_backoff * (2 ** self.supervisor_retry_count), self.max_backoff)
                logger.info(f"   Waiting {wait_time}s before restart...")
                await asyncio.sleep(wait_time)
                
                if self.websocket:
                    await self.websocket.close()
                    self.websocket = None
                self.strategy = None
                self.supervisor_retry_count = 0
    
    async def _auto_setup(self):
        logger.info("🔧 Auto-setup: Checking account readiness...")
        self.setup_attempted = True
        
        try:
            account = await self.client.get_account()
            if not account or not account.get("data"):
                logger.warning("⚠️ Cannot get account data")
                return
            
            data = account.get("data", {})
            readiness = data.get("readiness", {})
            
            free_ready = readiness.get("freeReady")
            paid_ready = readiness.get("paidReady", False)
            
            logger.info(f"   Readiness: freeReady={free_ready}, paidReady={paid_ready}")
            
            if free_ready is None:
                logger.info("   🔧 freeReady is None - attempting setup...")
                
                # Coba redeem WELCOME bundle
                try:
                    result = await self.client.redeem_code("WELCOME")
                    if result.get("success"):
                        logger.info("   ✅ WELCOME bundle redeemed!")
                        await asyncio.sleep(2)
                        await self.client.get_account()
                    else:
                        logger.warning(f"   ⚠️ Redeem failed: {result}")
                except Exception as e:
                    logger.warning(f"   ⚠️ Redeem error: {e}")
                
                await asyncio.sleep(3)
                account = await self.client.get_account()
                if account and account.get("data"):
                    readiness = account.get("data", {}).get("readiness", {})
                    free_ready = readiness.get("freeReady")
                    logger.info(f"   📊 After setup: freeReady={free_ready}")
            
            if free_ready is None or free_ready == False:
                logger.warning("⚠️ freeReady not available - attempting force join...")
                await self._force_join_free()
                
        except Exception as e:
            logger.error(f"❌ Auto-setup error: {e}")
    
    async def _force_join_free(self):
        """Force join free room tanpa menunggu readiness"""
        logger.info("🔧 Force joining free room...")
        
        try:
            # Buat WebSocket baru
            self.websocket = GameWebSocket()
            connected = await self.websocket.connect("free")
            
            if connected:
                logger.info("✅ Force joined free room!")
                self.last_game_id = self.websocket.game_id
                
                # Start strategy
                self.strategy = GameStrategy(self.websocket)
                await self.websocket.receive_loop(self.strategy.handle_message)
                
                await self._cleanup()
            else:
                logger.error("❌ Force join failed - will retry later")
                
        except Exception as e:
            logger.error(f"❌ Force join error: {e}")
            # Cleanup
            await self._cleanup()
    
    async def _main_loop(self):
        while self.running:
            try:
                if not self.client.is_logged_in:
                    logger.warning("Not logged in, attempting login...")
                    await self._login()
                    await asyncio.sleep(5)
                    continue
                
                state = await self.router.check_state()
                
                if state == AgentState.IN_GAME_FREE:
                    logger.info("🎮 Resuming free game")
                    await self._handle_game("free")
                elif state == AgentState.IN_GAME_PAID:
                    logger.info("🎮 Resuming paid game")
                    await self._handle_game("paid")
                elif state == AgentState.READY_FREE:
                    logger.info("🎮 Starting new free game...")
                    await self._handle_start_game("free")
                elif state == AgentState.READY_PAID:
                    logger.info("🎮 Starting new paid game...")
                    await self._handle_start_game("paid")
                elif state == AgentState.IDLE:
                    logger.info("😴 Idle - waiting for games")
                    
                    if not self.setup_attempted:
                        await self._auto_setup()
                    
                    if self.last_game_id:
                        await self._handle_reconnect()
                    elif self.reconnect_attempts > 3:
                        logger.info("🔧 Idle too long - attempting force join...")
                        await self._force_join_free()
                        self.reconnect_attempts = 0
                    
                    await asyncio.sleep(30)
                elif state == AgentState.ERROR:
                    logger.error("⚠️ Bot in error state")
                    await asyncio.sleep(10)
                    
                await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"Main loop error: {e}", exc_info=True)
                wait_time = min(self.base_backoff * (2 ** self.reconnect_attempts), self.max_backoff)
                logger.info(f"   Backoff: waiting {wait_time}s")
                await asyncio.sleep(wait_time)
                self.reconnect_attempts = min(self.reconnect_attempts + 1, 5)
    
    async def _login(self):
        if self.login_attempted:
            return
        
        logger.info("🔐 Logging in...")
        
        try:
            account = await self.client.get_account()
            
            if account and account.get("data"):
                data = account.get("data", {})
                logger.info(f"✅ Login successful!")
                logger.info(f"   Account: {data.get('name', 'Unknown')} (ID: {data.get('id')})")
                logger.info(f"   Balance: {data.get('balance', 0)} sMoltz")
                
                readiness = data.get("readiness", {})
                free_ready = readiness.get("freeReady")
                paid_ready = readiness.get("paidReady", False)
                
                if free_ready is None:
                    logger.warning(f"   ⚠️ freeReady: None (may need setup)")
                else:
                    logger.info(f"   Readiness: freeReady={free_ready}, paidReady={paid_ready}")
                
                games = data.get("currentGames", [])
                if games:
                    for g in games:
                        if g.get('isAlive'):
                            self.last_game_id = g.get('gameId')
                            logger.info(f"   🎮 Active game: {self.last_game_id}")
                
                self.client.is_logged_in = True
                self.login_attempted = True
                
                if free_ready is None and not self.setup_attempted:
                    await self._auto_setup()
            else:
                logger.error("❌ Login failed")
                self.login_attempted = True
                
        except Exception as e:
            logger.error(f"❌ Login error: {e}")
            self.login_attempted = True
    
    async def _handle_reconnect(self):
        if self.reconnect_attempts > self.max_reconnect_attempts:
            logger.warning(f"⚠️ Max reconnect attempts reached")
            self.reconnect_attempts = 0
            self.last_game_id = None
            return
        
        wait_time = min(self.base_backoff * (2 ** self.reconnect_attempts), self.max_backoff)
        logger.info(f"🔄 Reconnect attempt {self.reconnect_attempts + 1}/{self.max_reconnect_attempts}")
        logger.info(f"   Backoff: waiting {wait_time}s")
        
        await asyncio.sleep(wait_time)
        self.reconnect_attempts += 1
        
        try:
            account = await self.client.get_account()
            if not account or not account.get("data"):
                return
            
            games = account.get("data", {}).get("currentGames", [])
            for game in games:
                if game.get("gameId") == self.last_game_id and game.get("isAlive"):
                    logger.info(f"   ✅ Game {self.last_game_id} still active!")
                    entry_type = game.get("entryType", "free")
                    
                    self.websocket = GameWebSocket()
                    connected = await self.websocket.resume_game(entry_type)
                    
                    if connected:
                        logger.info(f"   ✅ Reconnected to game {self.last_game_id}")
                        self.reconnect_attempts = 0
                        
                        self.strategy = GameStrategy(self.websocket)
                        await self.websocket.receive_loop(self.strategy.handle_message)
                        
                        await self._cleanup()
                        return
                    break
            
            logger.info(f"   ℹ️ Game {self.last_game_id} ended")
            self.last_game_id = None
            self.reconnect_attempts = 0
            
        except Exception as e:
            logger.error(f"❌ Reconnect error: {e}")
    
    async def _handle_game(self, entry_type: str):
        logger.info(f"📌 Resuming {entry_type} game...")
        self.reconnect_attempts = 0
        
        try:
            self.websocket = GameWebSocket()
            connected = await self.websocket.resume_game(entry_type)
            if not connected:
                logger.error(f"❌ Failed to resume {entry_type} game")
                return
            
            self.last_game_id = self.websocket.game_id
            logger.info(f"✅ Resumed game: {self.last_game_id}")
            
            self.strategy = GameStrategy(self.websocket)
            await self.websocket.receive_loop(self.strategy.handle_message)
            
        except Exception as e:
            logger.error(f"❌ Game error: {e}", exc_info=True)
        finally:
            await self._cleanup()
            logger.info(f"✅ {entry_type} game ended - looking for next game")
    
    async def _handle_start_game(self, entry_type: str):
        logger.info(f"🎯 Starting new {entry_type} game...")
        self.reconnect_attempts = 0
        
        try:
            if Config.ROOM_MODE == "auto":
                logger.info("   🔄 Auto mode: trying paid first...")
                if await self._try_join("paid"):
                    return
                logger.info("   🔄 Paid not available, trying free...")
                if await self._try_join("free"):
                    return
                logger.error("❌ No rooms available!")
                return
            else:
                await self._try_join(entry_type)
            
        except Exception as e:
            logger.error(f"❌ Game error: {e}", exc_info=True)
        finally:
            await self._cleanup()
            logger.info(f"✅ Game ended - looking for next game")
    
    async def _try_join(self, entry_type: str) -> bool:
        logger.info(f"📦 Checking loadout...")
        await self.loadout_manager.configure_full_loadout()
        
        logger.info(f"🔌 Connecting to {entry_type} room...")
        self.websocket = GameWebSocket()
        connected = await self.websocket.connect(entry_type)
        
        if not connected:
            logger.warning(f"❌ Failed to connect to {entry_type} room!")
            return False
        
        self.last_game_id = self.websocket.game_id
        logger.info(f"✅ Joined {entry_type} game: {self.last_game_id}")
        
        logger.info("🎮 Starting gameplay...")
        self.strategy = GameStrategy(self.websocket)
        await self.websocket.receive_loop(self.strategy.handle_message)
        
        return True
    
    async def _cleanup(self):
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
        self.strategy = None
