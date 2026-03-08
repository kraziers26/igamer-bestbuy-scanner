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

        # For similar: always run if mode is similar, or if mode is both (regardless of exact results)
        if mode in ("similar", "both"):
            similar = await self._similar_search(session, product)
            if similar:
                # Avoid duplicate SKUs already found in exact
                existing_skus = {r.get("sku") for r in results}
                for r in similar:
                    if r.get("sku") not in existing_skus:
                        results.append(r)

        return results

    async def _exact_search(self, session, product):
        """
        Try multiple exact search strategies in order of precision.
        Best Buy search works best with product name keywords, not internal model numbers.
        """
        brand = product.get("brand", "")
        description = product.get("description", "")
        model_number = product.get("model_number", "")

        # Strategy 1: Brand + partial model number (first segment before dash)
        # e.g. "Asus FA608UP" instead of full "FA608UP-A16.R95070"
        short_model = model_number.split("-")[0] if "-" in model_number else model_number
        if brand and short_model and len(short_model) >= 4:
            results = await self._call_api(session, f"{brand} {short_model}", product, "exact")
            if results:
                return results

        # Strategy 2: Brand + product line from description
        # Extract first 3-4 meaningful words after brand name
        product_line = self._extract_product_line(brand, description)
        if product_line:
            results = await self._call_api(session, product_line, product, "exact")
            if results:
                return results

        return []

    async def _similar_search(self, session, product):
        """
        Spec-based search — find comparable products by brand + category + key specs.
        """
        brand = product.get("brand", "")
        category = product.get("category", "").lower()
        cpu = product.get("cpu", "")
        ram = product.get("ram", "")
        storage = product.get("storage", "")

        # Build a natural-language spec query
        parts = [brand] if brand else []

        # Add CPU generation hint
        if cpu:
            if "ultra" in cpu.lower():
                parts.append("Core Ultra")
            elif "i9" in cpu.lower() or "i7" in cpu.lower():
                gen = re.search(r'i[79]-(\d{2})', cpu)
                parts.append(f"Core {gen.group(0) if gen else 'i7'}")
            elif "ryzen 9" in cpu.lower():
                parts.append("Ryzen 9")
            elif "ryzen 7" in cpu.lower():
                parts.append("Ryzen 7")
            elif "ryzen 5" in cpu.lower():
                parts.append("Ryzen 5")
            elif "m4" in cpu.lower() or "m3" in cpu.lower() or "m2" in cpu.lower():
                chip = re.search(r'M\d', cpu, re.IGNORECASE)
                if chip:
                    parts.append(chip.group(0))

        # Add RAM
        if ram:
            parts.append(ram)

        # Add category
        if "gaming" in category:
            parts.append("gaming laptop")
        elif "desktop" in category:
            parts.append("desktop")
        elif "laptop" in category or "2-in-1" in category:
            parts.append("laptop")
        elif "all in one" in category:
            parts.append("all-in-one")

        query = " ".join(parts).strip()
        if not query or len(query) < 5:
            return []

        return await self._call_api(session, query, product, "similar")

    def _extract_product_line(self, brand: str, description: str) -> str:
        """
        Extract a clean product line search string from the description.
        e.g. 'Asus TUF FA608UP-A16... GAMING LAPTOP' -> 'Asus TUF gaming laptop'
        """
        SKIP = {
            "GAMING","LAPTOP","DESKTOP","COMPUTER","ALL","IN","ONE","MINI",
            "NOTEBOOK","WINDOWS","SCREEN","TOUCH","DISPLAY","2025","2024","2023"
        }
        tokens = description.split()
        parts = []
        for token in tokens[1:6]:  # skip brand (token 0), take next 5 tokens
            clean = token.rstrip(".,;:")
            if clean.upper() in SKIP:
                break
            if len(clean) >= 2:
                parts.append(clean)
            if len(parts) >= 3:
                break

        if not parts:
            return ""

        # Add category hint
        desc_lower = description.lower()
        if "gaming" in desc_lower and "desktop" in desc_lower:
            parts.append("gaming desktop")
        elif "gaming" in desc_lower:
            parts.append("gaming laptop")
        elif "all in one" in desc_lower:
            parts.append("all-in-one")
        elif "desktop" in desc_lower:
            parts.append("desktop")
        elif "laptop" in desc_lower or "notebook" in desc_lower:
            parts.append("laptop")

        return f"{brand} {' '.join(parts)}".strip()

    async def _call_api(self, session, query: str, product: dict, match_type: str) -> list[dict]:
        # Best Buy API uses (search=keyword) format in the URL path
        import urllib.parse
        encoded_query = urllib.parse.quote(query)
        url = f"{BESTBUY_API_BASE}(search={encoded_query})"

        params = {
            "apiKey": self.api_key,
            "format": "json",
            "show": "sku,name,salePrice,url,onlineAvailability",
            "pageSize": 5,
        }

        logger.info(f"BB search [{match_type}]: {query}")

        try:
            async with session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"BB API status {resp.status} for: {query}")
                    return []
                data = await resp.json()
                products = data.get("products", [])
                logger.info(f"BB returned {len(products)} results for: {query}")
                return self._format_results(products, product, match_type)
        except Exception as e:
            logger.error(f"API error for '{query}': {e}")
            return []

    def _format_results(self, bb_products: list, source_product: dict, match_type: str) -> list[dict]:
        results = []
        your_cost = source_product.get("price", 0)

        for bp in bb_products:
            bb_price = bp.get("salePrice")
            if not bb_price or float(bb_price) <= 0:
                continue
            if bp.get("onlineAvailability") is False:
                continue

            bb_price = float(bb_price)

            # Only flag if BB is cheaper than your cost
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
