import asyncio
import time
from .state.router import StateRouter, AgentState
from .api.client import APIClient
from .game.websocket import GameWebSocket
from .strategy.loadout import LoadoutManager
from .strategy.competitive_ai import CompetitiveAI
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
        self.game_ended = False
        self.join_attempts = 0
        self.max_join_attempts = 5
        self.idle_refresh_count = 0
        self.max_idle_refresh = 3
        self.force_join_attempted = False
        self.waiting_for_next_game = False
        self.consecutive_join_failures = 0
        self.max_join_failures = 3
        
    async def run(self):
        logger.info(f"Starting Claw Royale Bot: {Config.AGENT_NAME}")
        logger.info("=" * 50)
        logger.info("🦞 CLAW ROYALE BOT - COMPETITIVE AI ENABLED")
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
    
    async def _main_loop(self):
        while self.running:
            try:
                if not self.client.is_logged_in:
                    logger.warning("Not logged in, attempting login...")
                    await self._login()
                    await asyncio.sleep(5)
                    continue
                
                if self.consecutive_join_failures >= self.max_join_failures:
                    logger.warning(f"⚠️ {self.consecutive_join_failures} consecutive join failures! Resetting...")
                    self.consecutive_join_failures = 0
                    self.force_join_attempted = False
                    await asyncio.sleep(10)
                    continue
                
                if not self.force_join_attempted or self.game_ended:
                    if self.game_ended:
                        logger.info("🔄 Game ended - immediately joining new game...")
                        self.game_ended = False
                        self.join_attempts = 0
                        self.idle_refresh_count = 0
                        
                        join_success = await self._force_join_free_with_timeout()
                        if not join_success:
                            self.consecutive_join_failures += 1
                            logger.warning(f"⚠️ Join failed ({self.consecutive_join_failures}/{self.max_join_failures})")
                            await asyncio.sleep(5)
                        else:
                            self.consecutive_join_failures = 0
                        continue
                    
                    free_ready = self.client.account_data.get("readiness", {}).get("freeReady") if self.client.account_data else None
                    if free_ready is None or free_ready == False:
                        logger.info("🔧 freeReady not available - starting competitive AI...")
                        join_success = await self._force_join_free_with_timeout()
                        if not join_success:
                            self.consecutive_join_failures += 1
                            await asyncio.sleep(5)
                        else:
                            self.consecutive_join_failures = 0
                        self.force_join_attempted = True
                        continue
                
                if self.idle_refresh_count >= self.max_idle_refresh:
                    logger.info("🔧 Idle too long - forcing competitive AI...")
                    await self._force_refresh_state()
                    join_success = await self._force_join_free_with_timeout()
                    if join_success:
                        self.idle_refresh_count = 0
                        self.force_join_attempted = True
                        self.consecutive_join_failures = 0
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
                    logger.info("😴 Idle - forcing competitive AI...")
                    self.idle_refresh_count += 1
                    
                    if self.reconnect_attempts > 2:
                        logger.info("🔧 Too many idle attempts - force joining...")
                        join_success = await self._force_join_free_with_timeout()
                        if join_success:
                            self.reconnect_attempts = 0
                            self.idle_refresh_count = 0
                            self.consecutive_join_failures = 0
                        else:
                            self.consecutive_join_failures += 1
                    else:
                        join_success = await self._force_join_free_with_timeout()
                        if join_success:
                            self.idle_refresh_count = 0
                            self.consecutive_join_failures = 0
                    
                elif state == AgentState.ERROR:
                    logger.error("⚠️ Bot in error state")
                    await asyncio.sleep(5)
                    
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"Main loop error: {e}", exc_info=True)
                wait_time = min(self.base_backoff * (2 ** self.reconnect_attempts), self.max_backoff)
                logger.info(f"   Backoff: waiting {wait_time}s")
                await asyncio.sleep(wait_time)
                self.reconnect_attempts = min(self.reconnect_attempts + 1, 5)
    
    async def _force_join_free_with_timeout(self) -> bool:
        try:
            join_task = asyncio.create_task(self._force_join_free())
            try:
                await asyncio.wait_for(join_task, timeout=30.0)
                return True
            except asyncio.TimeoutError:
                logger.error("❌ Force join timeout! Cancelling...")
                join_task.cancel()
                if self.websocket:
                    await self.websocket.close()
                    self.websocket = None
                return False
        except Exception as e:
            logger.error(f"❌ Force join error: {e}")
            return False
    
    async def _force_join_free(self):
        logger.info("🚀 Competitive AI: Force joining game...")
        
        self.force_join_attempted = True
        self.waiting_for_next_game = False
        
        max_force_attempts = 3
        for attempt in range(max_force_attempts):
            try:
                self.websocket = GameWebSocket()
                self.websocket.on_game_ended = self._on_game_ended
                
                connected = await self.websocket.connect("free")
                
                if not connected:
                    logger.warning(f"⚠️ Force join attempt {attempt + 1}/{max_force_attempts} failed")
                    await asyncio.sleep(2)
                    continue
                
                logger.info("✅ Joined game!")
                self.last_game_id = self.websocket.game_id
                self.game_ended = False
                self.join_attempts = 0
                self.idle_refresh_count = 0
                self.reconnect_attempts = 0
                self.consecutive_join_failures = 0
                
                logger.info("🤖 Competitive AI: Starting...")
                self.strategy = CompetitiveAI(self.websocket)
                
                try:
                    await asyncio.wait_for(
                        self.websocket.receive_loop(self.strategy.handle_message),
                        timeout=300.0
                    )
                except asyncio.TimeoutError:
                    logger.warning("⚠️ Receive loop timeout! Game may be dead.")
                    self.game_ended = True
                    await self._cleanup()
                    return
                
                await self._cleanup()
                self.game_ended = True
                logger.info("✅ Game ended - will join next game")
                return
                
            except Exception as e:
                logger.error(f"❌ Force join error (attempt {attempt + 1}): {e}")
                await self._cleanup()
                await asyncio.sleep(2)
                await self._force_refresh_state()
        
        logger.error("❌ All force join attempts failed")
        self.game_ended = False
        self.join_attempts = 0
        await asyncio.sleep(5)
    
    def _on_game_ended(self):
        logger.info("🏁 Game ended - triggering competitive AI")
        self.game_ended = True
        self.force_join_attempted = False
    
    async def _force_refresh_state(self):
        logger.debug("🔄 Forcing state refresh...")
        try:
            self.client.account_data = None
            self.client.is_logged_in = False
            
            account = await self.client.get_account()
            if account and account.get("data"):
                self.client.is_logged_in = True
                self.client.account_data = account.get("data")
                logger.debug("   ✅ State refreshed")
                
                games = self.client.account_data.get("currentGames", [])
                if games:
                    for g in games:
                        if g.get('isAlive'):
                            self.last_game_id = g.get('gameId')
                            logger.info(f"   🎮 Found active game: {self.last_game_id}")
                else:
                    logger.debug("   ℹ️ No active games found")
        except Exception as e:
            logger.error(f"❌ Force refresh error: {e}")
    
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
                    logger.warning(f"   ⚠️ freeReady: None - competitive AI will force join")
                else:
                    logger.info(f"   Readiness: freeReady={free_ready}, paidReady={paid_ready}")
                
                games = data.get("currentGames", [])
                if games:
                    for g in games:
                        if g.get('isAlive'):
                            self.last_game_id = g.get('gameId')
                            logger.info(f"   🎮 Active game: {self.last_game_id}")
                else:
                    logger.info("   ℹ️ No active games")
                
                self.client.is_logged_in = True
                self.login_attempted = True
                
                if free_ready is None and not self.force_join_attempted:
                    logger.info("🔧 freeReady is None - competitive AI will force join...")
            else:
                logger.error("❌ Login failed - check API_KEY")
                self.login_attempted = True
                
        except Exception as e:
            logger.error(f"❌ Login error: {e}")
            self.login_attempted = True
    
    async def _auto_setup(self):
        logger.info("🔧 Auto-setup: Checking account readiness...")
        self.setup_attempted = True
        
        try:
            await self._force_refresh_state()
            
            account = await self.client.get_account()
            if not account or not account.get("data"):
                logger.warning("⚠️ Cannot get account data")
                return
            
            data = account.get("data", {})
            readiness = data.get("readiness", {})
            
            free_ready = readiness.get("freeReady")
            paid_ready = readiness.get("paidReady", False)
            
            logger.info(f"   Readiness: freeReady={free_ready}, paidReady={paid_ready}")
            
            if free_ready is None or free_ready == False:
                logger.info("   🔧 freeReady not available - starting competitive AI...")
                await self._force_join_free()
                self.force_join_attempted = True
                
        except Exception as e:
            logger.error(f"❌ Auto-setup error: {e}")
    
    async def _handle_game(self, entry_type: str):
        logger.info(f"📌 Resuming {entry_type} game...")
        self.reconnect_attempts = 0
        self.game_ended = False
        self.join_attempts = 0
        self.idle_refresh_count = 0
        
        try:
            self.websocket = GameWebSocket()
            connected = await self.websocket.resume_game(entry_type)
            if not connected:
                logger.error(f"❌ Failed to resume {entry_type} game")
                self.game_ended = True
                return
            
            self.last_game_id = self.websocket.game_id
            logger.info(f"✅ Resumed game: {self.last_game_id}")
            
            self.strategy = CompetitiveAI(self.websocket)
            self.websocket.on_game_ended = self._on_game_ended
            await self.websocket.receive_loop(self.strategy.handle_message)
            
        except Exception as e:
            logger.error(f"❌ Game error: {e}", exc_info=True)
        finally:
            await self._cleanup()
            self.game_ended = True
    
    async def _handle_start_game(self, entry_type: str):
        logger.info(f"🎯 Starting new {entry_type} game...")
        self.reconnect_attempts = 0
        self.game_ended = False
        self.join_attempts = 0
        self.idle_refresh_count = 0
        
        try:
            if Config.ROOM_MODE == "auto":
                logger.info("   🔄 Auto mode: trying paid first...")
                if await self._try_join("paid"):
                    return
                logger.info("   🔄 Paid not available, trying free...")
                if await self._try_join("free"):
                    return
                logger.error("❌ No rooms available!")
                self.game_ended = True
                return
            else:
                success = await self._try_join(entry_type)
                if not success:
                    self.game_ended = True
                    return
            
        except Exception as e:
            logger.error(f"❌ Game error: {e}", exc_info=True)
            self.game_ended = True
        finally:
            await self._cleanup()
            self.game_ended = True
    
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
        
        logger.info("🤖 Competitive AI: Starting...")
        self.strategy = CompetitiveAI(self.websocket)
        self.websocket.on_game_ended = self._on_game_ended
        await self.websocket.receive_loop(self.strategy.handle_message)
        
        return True
    
    async def _cleanup(self):
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
        self.strategy = None
