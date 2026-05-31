"""Pipeline principal: coleta -> classifica (LLM) -> persiste -> detecta -> notifica.

Uso:
    python main.py            # executa uma varredura completa
    python main.py --debug    # idem, com inspeção da estrutura do JSON da OLX
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

import yaml

try:
    from dotenv import load_dotenv
    load_dotenv()  # carrega .env -> variáveis de ambiente (ANTHROPIC_API_KEY)
except ImportError:
    pass  # sem python-dotenv: usa as variáveis de ambiente já definidas

from collectors import olx
from core.detector import Detector
from core.llm_classify import LLMClassifier, regex_fallback
from core.storage import Storage
from notify.telegram import TelegramNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


async def run_once(cfg: dict, debug: bool = False) -> None:
    storage = Storage(cfg["storage"]["db_path"])
    detector = Detector(
        iqr_k=cfg["detector"]["iqr_k"],
        min_samples=cfg["detector"]["min_samples"],
        floor_ratio=cfg["detector"]["floor_ratio"],
    )
    notifier = TelegramNotifier(
        # config.yaml tem prioridade; senão usa o .env (TELEGRAM_BOT_TOKEN/CHAT_ID)
        bot_token=cfg["telegram"]["bot_token"] or os.getenv("TELEGRAM_BOT_TOKEN", ""),
        chat_id=cfg["telegram"]["chat_id"] or os.getenv("TELEGRAM_CHAT_ID", ""),
        enabled=cfg["telegram"]["enabled"],
    )
    window_days = cfg["detector"]["window_days"]
    valid_models = [s["model"] for s in cfg["searches"]]

    # 1. COLETA — varre todas as buscas e junta os anúncios (dedup por id)
    raw_by_id = {}
    for search in cfg["searches"]:
        listings = await olx.collect(search, cfg["region"], cfg["collector"], debug=debug)
        for l in listings:
            raw_by_id.setdefault(l.id, l)
    raw = list(raw_by_id.values())
    log.info("Total coletado (únicos): %d anúncios", len(raw))

    # 2. CLASSIFICAÇÃO — só os anúncios INÉDITOS vão à LLM (economia de token).
    #    Os já vistos reaproveitam modelo/variante do banco.
    known = storage.get_known([l.id for l in raw])   # {id: (model, variant)}
    to_classify = [l for l in raw if l.id not in known]
    log.info("Inéditos para classificar: %d | reaproveitados do banco: %d",
             len(to_classify), len(raw) - len(to_classify))

    llm_cfg = cfg.get("llm", {})
    if to_classify and llm_cfg.get("enabled"):
        classifier = LLMClassifier(
            model=llm_cfg["model"],
            valid_models=valid_models,
            batch_size=llm_cfg.get("batch_size", 40),
            api_key=llm_cfg.get("api_key") or None,
        )
        new_map = classifier.classify(to_classify) if classifier.available else regex_fallback(to_classify)
    elif to_classify:
        new_map = regex_fallback(to_classify)
    else:
        new_map = {}

    # Atribui modelo/variante a cada anúncio coletado.
    for l in raw:
        if l.id in known:
            l.model, l.variant = known[l.id]
        else:
            model, variant = new_map.get(l.id, (None, None))
            l.model = model if model in valid_models else None
            l.variant = variant if l.model else None

    # 3. PERSISTÊNCIA — grava/atualiza TODOS (inclusive não-consoles, com model
    #    nulo, para não reclassificá-los toda vez). new_ones = inéditos que são
    #    console monitorado.
    new_ones = []
    for l in raw:
        is_new = storage.upsert(l)
        if is_new and l.model in valid_models:
            new_ones.append(l)
    log.info("Consoles novos (não vistos antes): %d", len(new_ones))

    # 4. DETECÇÃO + 5. NOTIFICAÇÃO (só nos novos)
    min_samples = cfg["detector"]["min_samples"]
    total_opps = 0
    for l in new_ones:
        # Compara variante-com-variante; se a variante é desconhecida ou tem
        # poucos exemplos, cai para a mediana do modelo inteiro.
        if l.variant:
            samples = storage.prices_for_model_variant(l.model, l.variant, window_days)
            if len(samples) >= min_samples:
                basis = f"{l.model} {l.variant}"
            else:
                samples = storage.prices_for_model(l.model, window_days)
                basis = f"{l.model} (geral)"
        else:
            samples = storage.prices_for_model(l.model, window_days)
            basis = f"{l.model} (geral)"

        opp = detector.evaluate(l, samples, basis=basis)
        if opp and not storage.was_alerted(l.id):
            notifier.send(opp)
            storage.mark_alerted(l.id)
            total_opps += 1
            log.info("  🔔 OPORTUNIDADE: %s R$ %s (-%.0f%%) [base: %s, n=%d]",
                     l.model, l.price, opp.discount_pct, basis, opp.sample_size)

    # 6. LIMPEZA — remove anúncios fora da janela, mantendo o banco enxuto.
    retention = cfg["storage"].get("retention_days", window_days)
    removed = storage.prune(retention)
    if removed:
        log.info("Banco: %d anúncios antigos removidos (retenção %dd).", removed, retention)

    storage.close()
    log.info("Varredura concluída: %d novos, %d oportunidades.", len(new_ones), total_opps)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", help="inspeciona a estrutura do JSON da OLX")
    args = parser.parse_args()
    asyncio.run(run_once(load_config(), debug=args.debug))


if __name__ == "__main__":
    main()
