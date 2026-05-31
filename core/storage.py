"""Persistência em SQLite: histórico de anúncios e controle de dedupe/alertas."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from .models import Listing


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS listings (
                id          TEXT PRIMARY KEY,
                source      TEXT NOT NULL,
                model       TEXT,
                variant     TEXT,
                title       TEXT,
                price       INTEGER,
                url         TEXT,
                region      TEXT,
                image       TEXT,
                posted_at   TEXT,
                first_seen  TEXT NOT NULL,
                last_seen   TEXT NOT NULL,
                alerted     INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_listings_model ON listings(model);
            CREATE INDEX IF NOT EXISTS idx_listings_seen  ON listings(last_seen);
            """
        )
        # Migração: adiciona `variant` se o banco veio de uma versão anterior.
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(listings)").fetchall()]
        if "variant" not in cols:
            self.conn.execute("ALTER TABLE listings ADD COLUMN variant TEXT")
        self.conn.commit()

    def upsert(self, listing: Listing) -> bool:
        """Insere ou atualiza um anúncio. Retorna True se for NOVO (não visto antes)."""
        now = _now()
        exists = self.conn.execute(
            "SELECT 1 FROM listings WHERE id = ?", (listing.id,)
        ).fetchone() is not None
        if exists:
            self.conn.execute(
                "UPDATE listings SET price=?, last_seen=?, title=?, model=?, variant=? WHERE id=?",
                (listing.price, now, listing.title, listing.model, listing.variant, listing.id),
            )
        else:
            self.conn.execute(
                """INSERT INTO listings
                   (id, source, model, variant, title, price, url, region, image,
                    posted_at, first_seen, last_seen, alerted)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)""",
                (listing.id, listing.source, listing.model, listing.variant,
                 listing.title, listing.price, listing.url, listing.region,
                 listing.image, listing.posted_at, now, now),
            )
        self.conn.commit()
        return not exists

    def prices_for_model(self, model: str, window_days: int) -> List[int]:
        """Preços de um modelo (todas as variantes) na janela."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
        cur = self.conn.execute(
            """SELECT price FROM listings
               WHERE model = ? AND price IS NOT NULL AND price > 0
                 AND last_seen >= ?""",
            (model, cutoff),
        )
        return [row["price"] for row in cur.fetchall()]

    def prices_for_model_variant(self, model: str, variant: str, window_days: int) -> List[int]:
        """Preços de um modelo + variante específica na janela."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
        cur = self.conn.execute(
            """SELECT price FROM listings
               WHERE model = ? AND variant = ? AND price IS NOT NULL AND price > 0
                 AND last_seen >= ?""",
            (model, variant, cutoff),
        )
        return [row["price"] for row in cur.fetchall()]

    def get_known(self, ids: List[str]) -> dict:
        """{id: (model, variant)} para os ids já presentes no banco.

        Inclui anúncios já vistos que NÃO são console (model=None) — assim eles
        não voltam a ser reclassificados pela LLM.
        """
        out: dict = {}
        ids = list(ids)
        for i in range(0, len(ids), 500):  # respeita o limite de variáveis do SQLite
            chunk = ids[i:i + 500]
            ph = ",".join("?" * len(chunk))
            rows = self.conn.execute(
                f"SELECT id, model, variant FROM listings WHERE id IN ({ph})", chunk
            ).fetchall()
            for r in rows:
                out[r["id"]] = (r["model"], r["variant"])
        return out

    def prune(self, retention_days: int) -> int:
        """Remove anúncios não vistos há mais de `retention_days`. Retorna quantos."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        cur = self.conn.execute("DELETE FROM listings WHERE last_seen < ?", (cutoff,))
        self.conn.commit()
        return cur.rowcount

    def mark_alerted(self, listing_id: str) -> None:
        self.conn.execute("UPDATE listings SET alerted=1 WHERE id=?", (listing_id,))
        self.conn.commit()

    def was_alerted(self, listing_id: str) -> bool:
        row = self.conn.execute(
            "SELECT alerted FROM listings WHERE id=?", (listing_id,)
        ).fetchone()
        return bool(row and row["alerted"])

    def close(self) -> None:
        self.conn.close()
