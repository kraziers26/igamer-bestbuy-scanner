import asyncio
import aiohttp
import logging
import re
import urllib.parse

logger = logging.getLogger(__name__)
BESTBUY_API_BASE = "https://api.bestbuy.com/v1/products"

# Price sanity: BB result must be within this range of your cost
# e.g. 0.25 = BB price must be between 25% and 100% of your cost
# This eliminates $10 accessories matching a $500 laptop
PRICE_FLOOR_RATIO = 0.35   # BB price must be at least 35% of your cost
PRICE_CEIL_RATIO  = 1.10   # BB price must be no more than 110% of your cost (catches near-matches)

# CPU tier mapping for spec validation — higher number = more powerful
CPU_TIERS = {
    # Intel Core Ultra
    "ultra 9": 9, "ultra 7": 7, "ultra 5": 5,
    # Intel Core i-series
    "i9": 9, "i7": 7, "i5": 5, "i3": 3,
    # AMD Ryzen
    "ryzen 9": 9, "ryzen 7": 7, "ryzen 5": 5, "ryzen 3": 3,
    "ryzen ai 9": 9, "ryzen ai 7": 7,
    # Apple
    "m4": 8, "m3": 7, "m2": 6, "m1": 5,
}

def get_cpu_tier(cpu_string: str) -> int | None:
    """Return numeric tier for a CPU string, or None if unrecognised."""
    s = cpu_string.lower()
    for key, tier in CPU_TIERS.items():
        if key in s:
            return tier
    return None

def extract_ram_gb(text: str) -> int | None:
    m = re.search(r'(\d+)\s*gb', text, re.IGNORECASE)
    return int(m.group(1)) if m else None

def specs_compatible(source: dict, bb_name: str) -> tuple[bool, str]:
    """
    Check whether the BB result name is spec-compatible with our source product.
    Returns (is_compatible, match_type) where match_type is 'exact' or 'similar'.
    """
    bb_lower = bb_name.lower()

    # ── CPU tier check ──────────────────────────────────────────────────────
    source_cpu = source.get("cpu", "")
    source_tier = get_cpu_tier(source_cpu)
    bb_tier = None
    for key, tier in CPU_TIERS.items():
        if key in bb_lower:
            bb_tier = tier
            break

    if source_tier is not None and bb_tier is not None:
        if bb_tier < source_tier:
            # BB item has a lower-tier CPU — definitely similar, not exact
            return True, "similar"
        if bb_tier > source_tier:
            # BB item has a higher-tier CPU — could be a better deal, flag as similar
            return True, "similar"
        # Same tier — compatible for exact

    # ── RAM check ───────────────────────────────────────────────────────────
    source_ram = extract_ram_gb(source.get("ram", ""))
    bb_ram = extract_ram_gb(bb_lower)
    if source_ram and bb_ram:
        if bb_ram < source_ram // 2:
            # BB item has much less RAM — likely a wrong match
            return False, ""
        if bb_ram != source_ram:
            return True, "similar"

    return True, "exact"


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

        if mode in ("similar", "both"):
            similar = await self._similar_search(session, product)
            if similar:
                existing_skus = {r.get("sku") for r in results}
                for r in similar:
                    if r.get("sku") not in existing_skus:
                        results.append(r)

        return results

    async def _exact_search(self, session, product):
        brand = product.get("brand", "")
        description = product.get("description", "")
        model_number = product.get("model_number", "")

        # Strategy 1: brand + shortened model number
        short_model = model_number.split("-")[0] if "-" in model_number else model_number
        if brand and short_model and len(short_model) >= 4:
            results = await self._call_api(session, f"{brand} {short_model}", product, "exact")
            if results:
                return results

        # Strategy 2: brand + product line keywords
        product_line = self._extract_product_line(brand, description)
        if product_line:
            results = await self._call_api(session, product_line, product, "exact")
            if results:
                return results

        return []

    async def _similar_search(self, session, product):
        brand = product.get("brand", "")
        category = product.get("category", "").lower()
        cpu = product.get("cpu", "")
        ram = product.get("ram", "")

        parts = [brand] if brand else []

        if cpu:
            cpu_l = cpu.lower()
            if "ultra 9" in cpu_l:   parts.append("Core Ultra 9")
            elif "ultra 7" in cpu_l: parts.append("Core Ultra 7")
            elif "ultra 5" in cpu_l: parts.append("Core Ultra 5")
            elif "i9" in cpu_l:      parts.append("Core i9")
            elif "i7" in cpu_l:      parts.append("Core i7")
            elif "i5" in cpu_l:      parts.append("Core i5")
            elif "ryzen ai 9" in cpu_l: parts.append("Ryzen AI 9")
            elif "ryzen 9" in cpu_l: parts.append("Ryzen 9")
            elif "ryzen 7" in cpu_l: parts.append("Ryzen 7")
            elif "ryzen 5" in cpu_l: parts.append("Ryzen 5")
            elif "m4" in cpu_l:      parts.append("M4")
            elif "m3" in cpu_l:      parts.append("M3")
            elif "m2" in cpu_l:      parts.append("M2")

        if ram:
            parts.append(ram)

        if "gaming" in category and "desktop" in category:
            parts.append("gaming desktop")
        elif "gaming" in category:
            parts.append("gaming laptop")
        elif "all in one" in category:
            parts.append("all-in-one")
        elif "desktop" in category:
            parts.append("desktop")
        else:
            parts.append("laptop")

        query = " ".join(parts).strip()
        if not query or len(query) < 5:
            return []

        return await self._call_api(session, query, product, "similar")

    def _extract_product_line(self, brand: str, description: str) -> str:
        SKIP = {
            "GAMING","LAPTOP","DESKTOP","COMPUTER","ALL","IN","ONE","MINI",
            "NOTEBOOK","WINDOWS","SCREEN","TOUCH","DISPLAY","2025","2024","2023"
        }
        tokens = description.split()
        parts = []
        for token in tokens[1:6]:
            clean = token.rstrip(".,;:")
            if clean.upper() in SKIP:
                break
            if len(clean) >= 2:
                parts.append(clean)
            if len(parts) >= 3:
                break

        if not parts:
            return ""

        desc_lower = description.lower()
        if "gaming" in desc_lower and "desktop" in desc_lower:
            parts.append("gaming desktop")
        elif "gaming" in desc_lower:
            parts.append("gaming laptop")
        elif "all in one" in desc_lower:
            parts.append("all-in-one")
        elif "desktop" in desc_lower:
            parts.append("desktop")
        else:
            parts.append("laptop")

        return f"{brand} {' '.join(parts)}".strip()

    async def _call_api(self, session, query: str, product: dict, match_type: str) -> list[dict]:
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
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    logger.warning(f"BB API {resp.status} for: {query}")
                    return []
                data = await resp.json()
                products = data.get("products", [])
                logger.info(f"BB returned {len(products)} for: {query}")
                return self._format_results(products, product, match_type)
        except Exception as e:
            logger.error(f"API error '{query}': {e}")
            return []

    def _format_results(self, bb_products: list, source_product: dict, match_type: str) -> list[dict]:
        results = []
        your_cost = source_product.get("price", 0)
        if not your_cost:
            return []

        # Price sanity bounds
        price_floor = your_cost * PRICE_FLOOR_RATIO
        price_ceil  = your_cost * PRICE_CEIL_RATIO

        for bp in bb_products:
            bb_price = bp.get("salePrice")
            if not bb_price:
                continue
            bb_price = float(bb_price)

            if bb_price <= 0:
                continue

            # ── Price sanity check ─────────────────────────────────────────
            # Reject items that are way too cheap or way too expensive
            # e.g. a $10 cable will never match a $500 laptop
            if bb_price < price_floor or bb_price > price_ceil:
                logger.info(f"Price sanity reject: BB ${bb_price:.2f} vs your cost ${your_cost:.2f} (floor ${price_floor:.2f})")
                continue

            if bp.get("onlineAvailability") is False:
                continue

            # Only flag if BB is actually cheaper than your cost
            if bb_price >= your_cost:
                continue

            # ── Spec compatibility check ───────────────────────────────────
            bb_name = bp.get("name", "")
            compatible, verified_match_type = specs_compatible(source_product, bb_name)

            if not compatible:
                logger.info(f"Spec reject: '{bb_name}' incompatible with source")
                continue

            # Override match_type based on spec check
            # If called as "exact" but specs differ → downgrade to "similar"
            final_match_type = verified_match_type if match_type == "exact" else "similar"

            savings_dollar = round(your_cost - bb_price, 2)
            savings_pct    = round((savings_dollar / your_cost) * 100, 2)

            results.append({
                "name": bb_name,
                "bb_price": bb_price,
                "url": bp.get("url", ""),
                "your_cost": float(your_cost),
                "savings_dollar": savings_dollar,
                "savings_pct": savings_pct,
                "match_type": final_match_type,
                "source_description": source_product.get("description", ""),
                "source_brand": source_product.get("brand", ""),
                "sku": bp.get("sku", ""),
            })

        return results
