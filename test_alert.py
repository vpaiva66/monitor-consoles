from __future__ import annotations

import os

import yaml

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from core.detector import Opportunity
from core.models import Listing
from notify.telegram import TelegramNotifier


def main() -> None:
    with open("config.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    notifier = TelegramNotifier(
        bot_token=cfg["telegram"]["bot_token"] or os.getenv("TELEGRAM_BOT_TOKEN", ""),
        chat_id=cfg["telegram"]["chat_id"] or os.getenv("TELEGRAM_CHAT_ID", ""),
        enabled=cfg["telegram"]["enabled"],
    )

    listing = Listing(
        id="mock-0001",
        source="olx",
        title="[TESTE] PS5 Slim 1TB com 2 controles e 3 jogos",
        price=1800,
        url="https://www.olx.com.br/",
        model="PS5",
        variant="Slim",
        region="Belo Horizonte - Pampulha",
    )
    opp = Opportunity(
        listing=listing,
        median_price=2800.0,
        threshold=2200.0,
        discount_pct=(2800 - 1800) / 2800 * 100,
        basis="PS5 Slim",
        sample_size=14,
    )

    print("Enviando alerta de teste...")
    ok = notifier.send(opp)
    if ok:
        print("✅ Alerta enviado! Confira seu Telegram.")
    elif not notifier.enabled:
        print("⚠️ Telegram desativado ou sem token/chat_id — a mensagem foi só logada acima.")
        print("   Verifique telegram.enabled no config.yaml e TELEGRAM_* no .env.")
    else:
        print("❌ Falha no envio — veja o aviso de erro acima.")


if __name__ == "__main__":
    main()
