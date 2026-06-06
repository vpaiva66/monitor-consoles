from __future__ import annotations

import argparse
import logging
import sqlite3

import yaml

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from core.llm_classify import LLMClassifier
from core.models import Listing
from main import CONFIG_PATH

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("reclassify")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="grava as mudanças (sem isso, só mostra o diff)")
    args = parser.parse_args()

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    valid_models = [s["model"] for s in cfg["searches"]]
    llm_cfg = cfg["llm"]
    classifier = LLMClassifier(
        model=llm_cfg["model"],
        valid_models=valid_models,
        batch_size=llm_cfg.get("batch_size", 40),
        api_key=llm_cfg.get("api_key") or None,
    )
    if not classifier.available:
        raise SystemExit("SDK/API key da Anthropic indisponível — abortando.")

    db = sqlite3.connect(cfg["storage"]["db_path"])
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT id, title, model, variant FROM listings").fetchall()
    log.info("Reclassificando %d anúncios...", len(rows))

    listings = [Listing(id=r["id"], source="olx", title=r["title"] or "",
                        price=None, url="") for r in rows]
    new_map = classifier.classify(listings)

    changed = 0
    purged = 0
    for r in rows:
        new_model, new_variant = new_map.get(r["id"], (None, None))
        if (new_model, new_variant) == (r["model"], r["variant"]):
            continue
        changed += 1
        if r["model"] is not None and new_model is None:
            purged += 1
        log.info("  %s: %s/%s -> %s/%s | %.60s",
                 r["id"], r["model"], r["variant"], new_model, new_variant, r["title"])
        if args.apply:
            db.execute("UPDATE listings SET model=?, variant=? WHERE id=?",
                       (new_model, new_variant, r["id"]))

    if args.apply:
        db.commit()
    db.close()

    log.info("Total: %d mudanças (%d viraram não-console). %s",
             changed, purged,
             "APLICADO." if args.apply else "DRY-RUN — rode com --apply para gravar.")


if __name__ == "__main__":
    main()
