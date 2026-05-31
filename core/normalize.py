"""Classificação de anúncios em modelos canônicos e filtros anti-cilada.

A busca por "nintendo ds" retorna também 3DS; a por "playstation 4" pode trazer
acessórios. Aqui cada anúncio é reclassificado pelo título para o modelo real,
e itens que claramente não são o console (jogos, controles, cabos) são descartados.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

from .models import Listing


def _norm(text: str) -> str:
    """Minúsculas, sem acento, espaços colapsados — para casar palavras-chave."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.lower()).strip()


# Palavras que indicam que o anúncio NÃO é o console em si.
_ACCESSORY_HINTS = (
    "controle", "joystick", "manete", "capa", "case", "cabo", "carregador",
    "fonte", "suporte", "headset", "fone", "cartao", "memory card", "pelicula",
    "adaptador", "base", "dock " , "skin", "jogo ", "jogos", "midia", "game ",
    "caixa vazia", "so a caixa", "manual",
)

# Regras de classificação, da MAIS específica para a menos específica.
# (a ordem importa: "3ds" antes de "ds", "ps5" antes de "ps4", etc.)
def classify_model(title: str) -> Optional[str]:
    t = _norm(title)

    # Nintendo
    if "3ds" in t or "3 ds" in t:
        return "Nintendo 3DS"
    if "switch" in t:
        return "Nintendo Switch"
    if re.search(r"\bds\b", t) or "nintendo ds" in t or "ds lite" in t or "dsi" in t:
        return "Nintendo DS"

    # Xbox
    if "360" in t:
        return "Xbox 360"
    if "xbox one" in t or "one x" in t:
        return "Xbox One X"  # tratamos "xbox one" como o alvo do usuário

    # PlayStation
    if "ps5" in t or "playstation 5" in t or "play 5" in t:
        return "PS5"
    if "ps4" in t or "playstation 4" in t or "play 4" in t:
        return "PS4"

    return None


def looks_like_accessory(title: str) -> bool:
    t = _norm(title)
    return any(hint in t for hint in _ACCESSORY_HINTS)


def normalize(listing: Listing) -> Optional[Listing]:
    """Preenche `model`; retorna None se for acessório ou modelo não reconhecido."""
    if looks_like_accessory(listing.title):
        return None
    model = classify_model(listing.title)
    if model is None:
        return None
    listing.model = model
    return listing
