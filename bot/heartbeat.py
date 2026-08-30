import asyncio
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
        self.rejoin_attempts = 0
        self.max_rejoin_attempts = 5
        self.last_game_id = None
        
    async def run(self):
        logger.info(f"Starting Claw Royale Bot: {Config.AGENT_NAME}")
        logger.info("=" * 50)
        logger.info("🦞 CLAW ROYALE BOT - AUTO JOIN ENABLED")
        logger.info("=" * 50)
        
        # Login
        if self.client._has_api_key():
            await self._login()
        else:
            logger.error("❌ API_KEY is not configured!")
            return
        
        # Main loop
        while self.running:
            try:
                if not self.client.is_logged_in:
                    logger.warning("Not logged in, attempting login...")
                    await self._login()
                    await asyncio.sleep(5)
                    continue
                
                # Check state
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
                    
                    # Coba rejoin jika ada game yang terputus
                    if self.last_game_id and self.rejoin_attempts < self.max_rejoin_attempts:
                        self.rejoin_attempts += 1
                        logger.info(f"🔄 Rejoin attempt {self.rejoin_attempts}/{self.max_rejoin_attempts}")
                        await self._handle_rejoin()
                    else:
                        self.rejoin_attempts = 0
                        self.last_game_id = None
                    
                    await asyncio.sleep(30)
                elif state == AgentState.ERROR:
                    logger.error("⚠️ Bot in error state")
                    await asyncio.sleep(10)
                    
                await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"Heartbeat error: {e}", exc_info=True)
                await asyncio.sleep(10)
    
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
                logger.info(f"   Readiness: freeReady={readiness.get('freeReady')}, paidReady={readiness.get('paidReady')}")
                
                # Cek active games
                games = data.get("currentGames", [])
                if games:
                    logger.info(f"   🎮 Active games: {len(games)}")
                    for g in games:
                        logger.info(f"      - {g.get('entryType')}: {g.get('gameId')} (alive: {g.get('isAlive')})")
                        if g.get('isAlive'):
                            self.last_game_id = g.get('gameId')
                
                self.client.is_logged_in = True
                self.login_attempted = True
            else:
                logger.error("❌ Login failed")
                self.login_attempted = True
                
        except Exception as e:
            logger.error(f"❌ Login error: {e}")
            self.login_attempted = True
    
    async def _handle_game(self, entry_type: str):
        """Resume existing game"""
        logger.info(f"📌 Resuming {entry_type} game...")
        
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
    
    async def _handle_start_game(self, entry_type: str):
        """Start new game"""
        logger.info(f"🎯 Starting new {entry_type} game...")
        self.rejoin_attempts = 0
        
        try:
            # Loadout
            logger.info("📦 Checking loadout...")
            await self.loadout_manager.configure_full_loadout()
            
            # Connect
            logger.info("🔌 Connecting to game...")
            self.websocket = GameWebSocket()
            connected = await self.websocket.connect(entry_type)
            
            if not connected:
                logger.error(f"❌ Failed to connect to {entry_type} room!")
                return
            
            self.last_game_id = self.websocket.game_id
            logger.info(f"✅ Joined game: {self.last_game_id}")
            
            # Play
            logger.info("🎮 Starting gameplay...")
            self.strategy = GameStrategy(self.websocket)
            await self.websocket.receive_loop(self.strategy.handle_message)
            
        except Exception as e:
            logger.error(f"❌ Game error: {e}", exc_info=True)
        finally:
            await self._cleanup()
    
    async def _handle_rejoin(self):
        """Rejoin game yang terputus"""
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
                        logger.info(f"   ✅ Rejoined game {self.last_game_id}")
                        self.rejoin_attempts = 0
                        
                        self.strategy = GameStrategy(self.websocket)
                        await self.websocket.receive_loop(self.strategy.handle_message)
                        
                        await self._cleanup()
                        return
                    break
            
            # Game not found or ended
            logger.info(f"   ℹ️ Game {self.last_game_id} ended")
            self.last_game_id = None
            self.rejoin_attempts = 0
            
        except Exception as e:
            logger.error(f"❌ Rejoin error: {e}")
    
    async def _cleanup(self):
        """Cleanup WebSocket"""
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
        self.strategy = None