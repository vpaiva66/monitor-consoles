"""Roda a varredura periodicamente (para uso 24/7 no VPS).

Uso:
    python scheduler.py     # roda agora e depois a cada `interval_minutes`
"""
from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from main import load_config, run_once

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scheduler")


async def _job(cfg: dict) -> None:
    try:
        await run_once(cfg)
    except Exception:  # noqa: BLE001
        log.exception("Erro na varredura (continuando).")


async def main() -> None:
    cfg = load_config()
    interval = cfg["scheduler"]["interval_minutes"]
    scheduler = AsyncIOScheduler()
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
