from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import urllib.parse
from typing import Any, Dict, List, Optional

from playwright.async_api import async_playwright

from core.models import Listing

log = logging.getLogger("collector.olx")

_PAGE_SIZE = 50

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def build_url(category_path: str, region_path: str, query: str, page: int = 1) -> str:
    base = f"https://www.olx.com.br{category_path}/{region_path}".rstrip("/")
    params = {"q": query, "sf": "1"}
    if page > 1:
        params["o"] = str(page)
    return f"{base}?{urllib.parse.urlencode(params)}"


def parse_price(raw: Any) -> Optional[int]:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    s = str(raw)
    s = re.sub(r",\d{2}\b", "", s)
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else None


def _first(d: Dict, *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _looks_like_ad(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    has_title = any(k in obj for k in ("subject", "title"))
    has_id = any(k in obj for k in ("listId", "adId", "id", "listIdString"))
    return has_title and has_id


def _find_ads(node: Any, acc: List[List[Dict]]) -> None:
    if isinstance(node, list):
        if node and sum(_looks_like_ad(x) for x in node) >= max(1, len(node) // 2):
            acc.append([x for x in node if _looks_like_ad(x)])
        for item in node:
            _find_ads(item, acc)
    elif isinstance(node, dict):
        for v in node.values():
            _find_ads(v, acc)


def _extract_image(ad: Dict) -> Optional[str]:
    imgs = ad.get("images") or ad.get("thumbnails")
    if isinstance(imgs, list) and imgs:
        first = imgs[0]
        if isinstance(first, dict):
            return _first(first, "original", "url", "src")
        if isinstance(first, str):
            return first
    return _first(ad, "thumbnail", "image")


def _ad_to_listing(ad: Dict) -> Optional[Listing]:
    title = _first(ad, "subject", "title")
    ad_id = _first(ad, "listId", "adId", "id", "listIdString")
    url = _first(ad, "url", "friendlyUrl")
    if not (title and ad_id and url):
        return None

    location = None
    loc = ad.get("locationDetails") or ad.get("location")
    if isinstance(loc, dict):
        location = _first(loc, "municipality", "city", "name", "neighbourhood")
    elif isinstance(loc, str):
        location = loc

    return Listing(
        id=str(ad_id),
        source="olx",
        title=str(title),
        price=parse_price(_first(ad, "price", "priceValue", "oldPrice")),
        url=str(url),
        region=location,
        image=_extract_image(ad),
        posted_at=str(_first(ad, "date", "createdAt", "listTime") or ""),
    )


def _parse_next_data(html: str, debug: bool = False) -> List[Listing]:
    m = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL
    )
    if not m:
        log.warning("__NEXT_DATA__ não encontrado na página (layout pode ter mudado).")
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        log.warning("Falha ao decodificar __NEXT_DATA__: %s", e)
        return []

    if debug:
        page_props = data.get("props", {}).get("pageProps", {})
        log.info("DEBUG pageProps keys: %s", list(page_props.keys()))

    buckets: List[List[Dict]] = []
    _find_ads(data, buckets)
    if not buckets:
        log.warning("Nenhuma lista de anúncios reconhecida no JSON.")
        return []

    best = max(buckets, key=len)
    listings = [l for ad in best if (l := _ad_to_listing(ad))]
    return listings


_CHROME_ARGS = [
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--no-sandbox",
    "--disable-extensions",
]


async def _launch_browser(p, headless: bool, channel: Optional[str]):
    launch_kwargs = {"headless": headless, "args": _CHROME_ARGS}
    if channel:
        launch_kwargs["channel"] = channel
    return await p.chromium.launch(**launch_kwargs)


async def _new_context(browser):
    return await browser.new_context(
        user_agent=_UA,
        locale="pt-BR",
        viewport={"width": 1366, "height": 768},
    )


async def _fetch_one(context, url: str, timeout: int) -> str:
    page = await context.new_page()
    try:
        await page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
        return await page.content()
    finally:
        try:
            await page.close()
        except Exception:
            pass


async def collect(search: Dict, region: Dict, cfg: Dict, debug: bool = False) -> List[Listing]:
    all_listings: List[Listing] = []
    pages = int(cfg.get("pages_per_search", 1))
    headless = cfg.get("headless", True)
    channel = cfg.get("browser_channel") or None
    timeout = cfg.get("nav_timeout_seconds", 45)
    max_retries = int(cfg.get("max_retries", 2))

    async with async_playwright() as p:
        browser = await _launch_browser(p, headless, channel)
        context = await _new_context(browser)
        try:
            for page in range(1, pages + 1):
                url = build_url(
                    region["category_path"], region["region_path"], search["query"], page
                )
                log.info("Coletando [%s] pág.%d: %s", search["model"], page, url)

                html = None
                for attempt in range(1, max_retries + 2):
                    try:
                        html = await _fetch_one(context, url, timeout)
                        break
                    except Exception as e:
                        log.warning("Falha em %s (tentativa %d/%d): %s",
                                    url, attempt, max_retries + 1, e)
                        if not browser.is_connected():
                            log.warning("Navegador desconectado; relançando...")
                            try:
                                await browser.close()
                            except Exception:
                                pass
                            browser = await _launch_browser(p, headless, channel)
                            context = await _new_context(browser)
                        await asyncio.sleep(2 * attempt)

                if not html:
                    log.warning("Pulando %s após esgotar tentativas.", url)
                    continue

                listings = _parse_next_data(html, debug=debug)
                log.info("  -> %d anúncios brutos", len(listings))
                all_listings.extend(listings)

                if len(listings) < _PAGE_SIZE:
                    if page < pages:
                        log.info("  Última página real atingida; pulando pág.%d+.", page + 1)
                    break

                delay = random.uniform(cfg.get("min_delay_seconds", 4),
                                       cfg.get("max_delay_seconds", 9))
                await asyncio.sleep(delay)
        finally:
            try:
                await browser.close()
            except Exception:
                pass

    return all_listings
