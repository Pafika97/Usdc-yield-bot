import aiohttp
from typing import List, Dict, Any

class DefiLlamaProvider:
    """
    Берём пулы из публичного эндпоинта DefiLlama и фильтруем по USDC.
    Документация: https://api-docs.defillama.com/  (см. раздел Yield)
    Пулы: https://yields.llama.fi/pools
    """
    name = "DefiLlama"

    BASE = "https://yields.llama.fi/pools"

    async def fetch(self, session: aiohttp.ClientSession) -> List[Dict[str, Any]]:
        params = {}
        # без фильтров, фильтруем на клиенте по символу
        async with session.get(self.BASE, params=params, timeout=30) as r:
            r.raise_for_status()
            data = await r.json()

        pools = data.get("data") or data.get("pools") or []  # совместимость
        out = []
        for p in pools:
            symbol = (p.get("symbol") or "").upper()
            if "USDC" not in symbol:
                continue
            apy = p.get("apy")
            tvl = p.get("tvlUsd") or p.get("tvl") or 0
            project = p.get("project")
            chain = p.get("chain")
            url = f'https://defillama.com/yields/pool/{p.get("pool")}' if p.get("pool") else "https://defillama.com/yields"

            if apy is None:
                continue

            out.append({
                "platform": project or "unknown",
                "chain": chain or "",
                "symbol": symbol,
                "apy": float(apy),
                "tvl_usd": float(tvl) if isinstance(tvl, (int, float)) else 0.0,
                "source_url": url,
                "source": self.name,
                "notes": "",
            })
        # сортируем по APY убыв.
        out.sort(key=lambda x: x["apy"], reverse=True)
        return out
