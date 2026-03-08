import asyncio
import aiohttp
import logging
import re

logger = logging.getLogger(__name__)
BESTBUY_API_BASE = "https://api.bestbuy.com/v1/products"

class BestBuyScanner:
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def scan(self, inventory: list[dict], mode: str = "both") -> list[dict]:
        results = []
        async with aiohttp.ClientSession() as session:
            tasks = [self._search_product(session, product, mode) for product in inventory]
            for i in range(0, len(tasks), 5):
                batch = tasks[i:i+5]
                batch_results = await asyncio.gather(*batch, return_exceptions=True)
                for r in batch_results:
                    if isinstance(r, Exception):
                        logger.error(f"Search error: {r}")
                    elif r:
                        results.extend(r)
                await asyncio.sleep(0.5)
        return results

    async def _search_product(self, session, product, mode):
        results = []
        if mode in ("exact", "both"):
            exact = await self._exact_search(session, product)
            if exact:
                results.extend(exact)
        if mode == "similar" or (mode == "both" and not results):
            similar = await self._similar_search(session, product)
            if similar:
                results.extend(similar)
        return results

    async def _exact_search(self, session, product):
        query = product.get("search_query", "")
        if not query:
            return []
        return await self._call_api(session, query, product, "exact")

    async def _similar_search(self, session, product):
        query = product.get("spec_query", "")
        if not query or len(query) < 5:
            return []
        return await self._call_api(session, query, product, "similar")

    async def _call_api(self, session, query, product, match_type):
        params = {
            "apiKey": self.api_key,
            "format": "json",
            "show": "sku,name,salePrice,url,onlineAvailability",
            "pageSize": 3,
            "q": query,
        }
        try:
            async with session.get(
                BESTBUY_API_BASE, params=params,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return self._format_results(data.get("products", []), product, match_type)
        except Exception as e:
            logger.error(f"API error for '{query}': {e}")
            return []

    def _format_results(self, bb_products, source_product, match_type):
        results = []
        your_cost = source_product.get("price", 0)

        for bp in bb_products:
            bb_price = bp.get("salePrice")
            if not bb_price or bb_price <= 0:
                continue
            if bp.get("onlineAvailability") is False:
                continue

            bb_price = float(bb_price)

            # Only include if Best Buy is CHEAPER than your cost
            if bb_price >= your_cost:
                continue

            savings_dollar = round(your_cost - bb_price, 2)
            savings_pct = round((savings_dollar / your_cost) * 100, 2)

            results.append({
                "name": bp.get("name", "Unknown"),
                "bb_price": bb_price,
                "url": bp.get("url", ""),
                "your_cost": float(your_cost),
                "savings_dollar": savings_dollar,
                "savings_pct": savings_pct,
                "match_type": match_type,
                "source_description": source_product.get("description", ""),
                "source_brand": source_product.get("brand", ""),
                "sku": bp.get("sku", ""),
            })

        return results
