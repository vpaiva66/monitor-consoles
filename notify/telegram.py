from __future__ import annotations

import logging
import time

import httpx

from core.detector import Opportunity

log = logging.getLogger("notify.telegram")


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, enabled: bool = True):
        self.enabled = enabled and bool(bot_token and chat_id)
        self.bot_token = bot_token
        self.chat_id = chat_id

    def _format(self, opp: Opportunity) -> str:
        l = opp.listing
        titulo = f"{l.model} {l.variant}" if l.variant else l.model
        base = opp.basis or l.model
        return (
            f"🎮 <b>Oportunidade: {titulo}</b>\n"
            f"💰 <b>R$ {l.price:,}</b> "
            f"({opp.discount_pct:.0f}% abaixo da mediana de R$ {opp.median_price:,.0f})\n"
            f"📊 base: {base} ({opp.sample_size} anúncios)\n"
            f"📍 {l.region or 'n/d'}\n"
            f"📝 {l.title}\n"
            f"🔗 {l.url}"
        ).replace(",", ".")

    def send(self, opp: Opportunity, attempts: int = 3) -> bool:
        text = self._format(opp)
        if not self.enabled:
            log.info("[telegram desativado] %s", text.replace("\n", " | "))
            return False
        for attempt in range(1, attempts + 1):
            try:
                r = httpx.post(
                    f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                    json={
                        "chat_id": self.chat_id,
                        "text": text,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": False,
                    },
                    timeout=15,
                )
                r.raise_for_status()
                return True
            except Exception as e:
                log.warning("Falha ao enviar Telegram (tentativa %d/%d): %s",
                            attempt, attempts, e)
                if attempt < attempts:
                    time.sleep(3 * attempt)
        return False
