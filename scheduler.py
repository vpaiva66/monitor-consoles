"""Roda a varredura periodicamente (para uso 24/7 no VPS).

Uso:
    python scheduler.py     # roda agora e depois a cada `interval_minutes`
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from main import load_config, run_once

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scheduler")


def _resolve_timezone():
    """TZ do ambiente, com fallback seguro para UTC se o tzdata não existir.

    Evita o crash do APScheduler/tzlocal quando TZ=America/Sao_Paulo está setado
    mas o pacote tzdata não está instalado no container.
    """
    tz_name = os.getenv("TZ")
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, Exception):  # noqa: BLE001
            log.warning("TZ=%s indisponível (tzdata ausente?); usando UTC.", tz_name)
    return timezone.utc


async def _job(cfg: dict) -> None:
    try:
        await run_once(cfg)
    except Exception:  # noqa: BLE001
        log.exception("Erro na varredura (continuando).")


async def main() -> None:
    cfg = load_config()
    interval = cfg["scheduler"]["interval_minutes"]
    scheduler = AsyncIOScheduler(timezone=_resolve_timezone())
    # coalesce + max_instances=1: se uma varredura demorar mais que o intervalo,
    # não acumula execuções sobrepostas (importante com intervalos curtos no teste).
    scheduler.add_job(_job, "interval", minutes=interval, args=[cfg],
                      coalesce=True, max_instances=1)
    scheduler.start()
    log.info("Agendador iniciado (a cada %d min). Rodando 1ª varredura...", interval)
    await _job(cfg)  # roda imediatamente na largada
    # mantém o loop vivo
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
