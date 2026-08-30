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
        self.game_ended = False  # Flag untuk tracking game ended
        self.waiting_for_next_game = False
        
    async def run(self):
        logger.info(f"Starting Claw Royale Bot: {Config.AGENT_NAME}")
        logger.info("=" * 50)
        logger.info("🦞 CLAW ROYALE BOT - AUTO REJOIN ENABLED")
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
                
                # Jika game ended (mati atau selesai), langsung cari game baru
                if self.game_ended:
                    logger.info("🔄 Game ended - searching for next game...")
                    self.game_ended = False
                    self.waiting_for_next_game = True
                    
                    # Cek state untuk game baru
                    state = await self.router.check_state()
                    
                    if state == AgentState.READY_FREE:
                        logger.info("🎮 Found new free game!")
                        await self._handle_start_game("free")
                    elif state == AgentState.READY_PAID:
                        logger.info("🎮 Found new paid game!")
                        await self._handle_start_game("paid")
                    elif state == AgentState.IN_GAME_FREE:
                        logger.info("🎮 Resuming free game")
                        await self._handle_game("free")
                    elif state == AgentState.IN_GAME_PAID:
                        logger.info("🎮 Resuming paid game")
                        await self._handle_game("paid")
                    else:
                        logger.info("😴 No game available yet, waiting...")
                        self.waiting_for_next_game = False
                        await asyncio.sleep(10)
                    continue
                
                # Normal state check
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
                    
                    if self.last_game_id and not self.game_ended:
                        logger.info(f"🔄 Attempting to rejoin game {self.last_game_id}...")
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
    
    async def _handle_game(self, entry_type: str):
        """Resume existing game"""
        logger.info(f"📌 Resuming {entry_type} game...")
        self.reconnect_attempts = 0
        self.game_ended = False
        
        try:
            self.websocket = GameWebSocket()
            connected = await self.websocket.resume_game(entry_type)
            if not connected:
                logger.error(f"❌ Failed to resume {entry_type} game")
                self.game_ended = True  # Game ended, cari baru
                return
            
            self.last_game_id = self.websocket.game_id
            logger.info(f"✅ Resumed game: {self.last_game_id}")
            
            self.strategy = GameStrategy(self.websocket)
            await self.websocket.receive_loop(self.strategy.handle_message)
            
        except Exception as e:
            logger.error(f"❌ Game error: {e}", exc_info=True)
        finally:
            await self._cleanup()
            # Set flag bahwa game ended, akan cari game baru di loop utama
            self.game_ended = True
            logger.info(f"✅ {entry_type} game ended - will search for next game")
    
    async def _handle_start_game(self, entry_type: str):
        """Start new game"""
        logger.info(f"🎯 Starting new {entry_type} game...")
        self.reconnect_attempts = 0
        self.game_ended = False
        
        try:
            # Auto-matchmaking
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
            # Set flag bahwa game ended, akan cari game baru di loop utama
            self.game_ended = True
            logger.info(f"✅ Game ended - will search for next game")
    
    async def _try_join(self, entry_type: str) -> bool:
        """Try to join a game"""
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
    
    async def _force_join_free(self):
        """Force join free room tanpa menunggu readiness"""
        logger.info("🔧 Force joining free room...")
        
        try:
            self.websocket = GameWebSocket()
            connected = await self.websocket.connect("free")
            
            if connected:
                logger.info("✅ Force joined free room!")
                self.last_game_id = self.websocket.game_id
                self.game_ended = False
                
                self.strategy = GameStrategy(self.websocket)
                await self.websocket.receive_loop(self.strategy.handle_message)
                
                await self._cleanup()
                self.game_ended = True
                logger.info("✅ Force join game ended - will search for next")
            else:
                logger.error("❌ Force join failed - will retry later")
                self.game_ended = False
                await asyncio.sleep(10)
                
        except Exception as e:
            logger.error(f"❌ Force join error: {e}")
            await self._cleanup()
            await asyncio.sleep(5)
            self.game_ended = False
