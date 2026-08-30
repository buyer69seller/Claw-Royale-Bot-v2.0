import httpx
import json
import os
from typing import Optional, Dict
from ..config import Config
from ..utils.logger import logger

class APIClient:
    def __init__(self):
        self.base_url = Config.BASE_URL
        self.base_urls = Config.BASE_URLS
        self.current_url_index = 0
        self.api_key = Config.API_KEY
        self.version = None
        self.is_logged_in = False
        self.account_data = None
        self._load_cache()
        
    def _load_cache(self):
        try:
            os.makedirs(os.path.dirname(Config.VERSION_CACHE_FILE), exist_ok=True)
            with open(Config.VERSION_CACHE_FILE, 'r') as f:
                self.version_cache = json.load(f)
        except:
            self.version_cache = {}
    
    def _save_cache(self):
        try:
            with open(Config.VERSION_CACHE_FILE, 'w') as f:
                json.dump(self.version_cache, f)
        except Exception as e:
            logger.warning(f"Failed to save cache: {e}")
    
    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "User-Agent": f"ClawRoyaleBot/{Config.AGENT_NAME}",
            "Accept": "application/json"
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        if self.version:
            headers["X-Version"] = self.version
        else:
            headers["X-Version"] = "1.15.0"
        return headers
    
    def _has_api_key(self) -> bool:
        return self.api_key is not None and self.api_key != ""
    
    def _switch_base_url(self):
        self.current_url_index = (self.current_url_index + 1) % len(self.base_urls)
        self.base_url = self.base_urls[self.current_url_index]
        logger.info(f"Switched to API: {self.base_url}")
    
    async def get_version(self) -> Optional[str]:
        if not self._has_api_key():
            return None
        
        if "version" in self.version_cache:
            return self.version_cache["version"]
        
        for _ in range(len(self.base_urls)):
            try:
                url = f"{self.base_url}/version"
                async with httpx.AsyncClient(verify=True, timeout=30.0) as client:
                    response = await client.get(url, headers=self._get_headers())
                    if response.status_code == 200:
                        version = response.json().get("version")
                        self.version_cache["version"] = version
                        self._save_cache()
                        self.version = version
                        logger.info(f"✅ API Version: {version}")
                        return version
            except Exception as e:
                logger.warning(f"Failed to get version: {e}")
            self._switch_base_url()
        
        return "1.15.0"
    
    async def _request(self, method: str, endpoint: str, data: Dict = None, params: Dict = None) -> Dict:
        if not self._has_api_key():
            return {"error": "API_KEY not configured", "success": False}
        
        for _ in range(len(self.base_urls)):
            try:
                url = f"{self.base_url}{endpoint}"
                headers = self._get_headers()
                
                async with httpx.AsyncClient(verify=True, timeout=30.0) as client:
                    if method.upper() == "GET":
                        response = await client.get(url, headers=headers, params=params)
                    elif method.upper() == "POST":
                        response = await client.post(url, headers=headers, json=data)
                    else:
                        return {"error": f"Unsupported method: {method}", "success": False}
                    
                    if response.status_code == 200:
                        result = response.json()
                        if endpoint == "/accounts/me" and result.get("data"):
                            self.account_data = result.get("data")
                            self.is_logged_in = True
                        return result
                    
                    if response.status_code == 401:
                        logger.error("❌ Authentication failed")
                        self.is_logged_in = False
                        return {"error": "Authentication failed", "success": False}
                    
                    if response.status_code == 426:
                        await self.get_version()
                        return await self._request(method, endpoint, data, params)
                    
                    try:
                        error_data = response.json()
                        return {"error": error_data.get("error", {}).get("message", str(response.status_code)), "success": False}
                    except:
                        return {"error": f"HTTP {response.status_code}", "success": False}
                        
            except Exception as e:
                logger.warning(f"Request error: {e}")
                self._switch_base_url()
        
        return {"error": "All endpoints failed", "success": False}
    
    async def get_account(self) -> Dict:
        return await self._request("GET", "/accounts/me")
    
    async def get_balance(self) -> Dict:
        return await self._request("GET", "/accounts/me/balance")
    
    async def get_loadout(self) -> Dict:
        return await self._request("GET", "/accounts/me/loadout")
    
    async def set_loadout(self, loadout: Dict) -> Dict:
        return await self._request("POST", "/accounts/me/loadout", data=loadout)
    
    async def get_dashboard_games(self) -> Dict:
        return await self._request("GET", "/accounts/me/dashboard/games")
    
    async def redeem_code(self, code: str = "WELCOME") -> Dict:
        return await self._request("POST", "/api/redeem", data={"code": code})
