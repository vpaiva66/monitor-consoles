"""Modelos de dados compartilhados pelo sistema."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Listing:
    """Um anúncio normalizado, independente da plataforma de origem."""

    id: str                      # id único da plataforma (chave de dedupe)
    source: str                  # "olx" (futuramente "facebook")
    title: str
    price: Optional[int]         # em reais inteiros; None se "a combinar"/sem preço
    url: str
    model: Optional[str] = None    # rótulo canônico, ex: "PS5" (preenchido na classificação)
    variant: Optional[str] = None  # variante, ex: "Slim"/"Pro"/"OLED"; None se desconhecida
    region: Optional[str] = None
    image: Optional[str] = None
    posted_at: Optional[str] = None  # data de publicação informada pela OLX (ISO/texto)

    def is_priced(self) -> bool:
        return self.price is not None and self.price > 0
