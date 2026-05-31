"""Coletor da OLX usando Playwright.

A OLX é um app Next.js: os anúncios vêm num JSON embutido em <script id="__NEXT_DATA__">.
HTTP cru retorna 403 (anti-bot), por isso usamos um navegador real.

A estrutura exata do JSON pode variar; o parser abaixo é defensivo: procura
recursivamente a maior lista de objetos que pareçam anúncios. Na 1ª execução,
rode com `--debug` (ver main.py) para inspecionar o JSON bruto e ajustar se preciso.
"""
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

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def build_url(category_path: str, region_path: str, query: str, page: int = 1) -> str:
    base = f"https://www.olx.com.br{category_path}/{region_path}".rstrip("/")
    params = {"q": query, "sf": "1"}  # sf=1 -> ordenar por mais recentes primeiro
    if page > 1:
        params["o"] = str(page)  # OLX usa &o=N para paginação
    return f"{base}?{urllib.parse.urlencode(params)}"


def parse_price(raw: Any) -> Optional[int]:
    """'R$ 2.000' / 2000 / '2.000,00' -> 2000 (reais inteiros). None se não houver."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    s = str(raw)
    # remove parte de centavos (",00") e tudo que não é dígito
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
    """Coleta toda lista cujos itens pareçam anúncios."""
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
        # despeja as chaves de topo para ajudar a mapear a estrutura
        page_props = data.get("props", {}).get("pageProps", {})
        log.info("DEBUG pageProps keys: %s", list(page_props.keys()))

    buckets: List[List[Dict]] = []
    _find_ads(data, buckets)
    if not buckets:
        log.warning("Nenhuma lista de anúncios reconhecida no JSON.")
        return []

    best = max(buckets, key=len)  # a maior lista costuma ser a de resultados
    listings = [l for ad in best if (l := _ad_to_listing(ad))]
    return listings


# Flags de estabilidade do Chrome em container/VPS pequeno. --disable-dev-shm-usage
# evita crash por /dev/shm cheio; --disable-gpu/--no-sandbox reduzem superfície de
# falha em ambiente headless sem GPU.
_CHROME_ARGS = [
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--no-sandbox",
    "--disable-extensions",
]


async def _launch_browser(p, headless: bool, channel: Optional[str]):
    launch_kwargs = {"headless": headless, "args": _CHROME_ARGS}
    if channel:  # "chrome" usa o Google Chrome do sistema
        launch_kwargs["channel"] = channel
    return await p.chromium.launch(**launch_kwargs)


async def _new_context(browser):
    return await browser.new_context(
        user_agent=_UA,
        locale="pt-BR",
        viewport={"width": 1366, "height": 768},
    )


async def _fetch_one(context, url: str, timeout: int) -> str:
    """Carrega uma URL num contexto já aberto e devolve o HTML. Levanta em erro."""
    page = await context.new_page()
    try:
        await page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)  # deixa o Next hidratar
        return await page.content()
    finally:
        try:
            await page.close()
        except Exception:  # noqa: BLE001
            pass


async def collect(search: Dict, region: Dict, cfg: Dict, debug: bool = False) -> List[Listing]:
    """Coleta anúncios de uma busca (todas as páginas configuradas).

    Reusa UM navegador para todas as páginas da busca (menos rotatividade de
    processos) e, se o Chrome cair (SIGSEGV em VPS com pouca memória), relança o
    navegador e tenta de novo, sem derrubar a varredura inteira.
    """
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
                for attempt in range(1, max_retries + 2):  # 1 tentativa + N retries
                    try:
                        html = await _fetch_one(context, url, timeout)
                        break
                    except Exception as e:  # noqa: BLE001
                        log.warning("Falha em %s (tentativa %d/%d): %s",
                                    url, attempt, max_retries + 1, e)
                        # Se o navegador caiu, relança browser + contexto.
                        if not browser.is_connected():
                            log.warning("Navegador desconectado; relançando...")
                            try:
                                await browser.close()
                            except Exception:  # noqa: BLE001
                                pass
                            browser = await _launch_browser(p, headless, channel)
                            context = await _new_context(browser)
                        await asyncio.sleep(2 * attempt)  # backoff antes de retry

                if not html:
                    log.warning("Pulando %s após esgotar tentativas.", url)
                    continue

                listings = _parse_next_data(html, debug=debug)
                log.info("  -> %d anúncios brutos", len(listings))
                all_listings.extend(listings)

                # atraso humano entre páginas
                delay = random.uniform(cfg.get("min_delay_seconds", 4),
                                       cfg.get("max_delay_seconds", 9))
                await asyncio.sleep(delay)
        finally:
            try:
                await browser.close()
            except Exception:  # noqa: BLE001
                pass

    return all_listings
