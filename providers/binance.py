# OPTIONAL provider: Binance Simple Earn (заготовка)
# Многие эндпоинты Simple Earn требуют авторизации (USER_DATA).
# Документация: https://developers.binance.com/docs/binance-spot-api-docs/rest-api  (Simple Earn)
# В библиотеке python-binance есть хелпер для Simple Earn, но здесь используем aiohttp + API ключи из .env

import os
import hmac
import time
import hashlib
import aiohttp
from typing import List, Dict, Any
from urllib.parse import urlencode

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY") or ""
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET") or ""

class BinanceEarnProvider:
    name = "Binance Simple Earn"

    # Эндпоинт для Simple Earn flexible/locked продуктов (USER_DATA)
    # Пример: GET /sapi/v1/simple-earn/flexible/list  (может отличаться, проверяйте актуальную доку)
    # Некоторые рынки недоступны без KYC/региональных ограничений.

    BASE = "https://api.binance.com"

    def _sign(self, params: Dict[str, Any]) -> str:
        query = urlencode(params, doseq=True)
        return hmac.new(BINANCE_API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()

    async def _auth_get(self, session: aiohttp.ClientSession, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if not BINANCE_API_KEY or not BINANCE_API_SECRET:
            raise RuntimeError("Binance API keys are not set")
        params["timestamp"] = int(time.time() * 1000)
        params["signature"] = self._sign(params)
        headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
        async with session.get(self.BASE + path, params=params, headers=headers, timeout=30) as r:
            r.raise_for_status()
            return await r.json()

    async def fetch(self, session: aiohttp.ClientSession) -> List[Dict[str, Any]]:
        # Это пример — нужно подобрать точные пути и поля под актуальную спецификацию.
        # Ниже — заглушка, чтобы не ломать основной бот.
        return []
