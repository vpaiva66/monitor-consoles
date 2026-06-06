from __future__ import annotations

import re
import unicodedata
from typing import Optional

from .models import Listing


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.lower()).strip()


_ACCESSORY_HINTS = (
    "controle", "joystick", "manete", "capa", "case", "cabo", "carregador",
    "fonte", "suporte", "headset", "fone", "cartao", "memory card", "pelicula",
    "adaptador", "base", "dock ", "skin", "jogo ", "jogos", "midia", "game ",
    "caixa vazia", "so a caixa", "manual",
)


def classify_model(title: str) -> Optional[str]:
    t = _norm(title)

    if "3ds" in t or "3 ds" in t:
        return "Nintendo 3DS"
    if "switch" in t:
        return "Nintendo Switch"
    if re.search(r"\bds\b", t) or "nintendo ds" in t or "ds lite" in t or "dsi" in t:
        return "Nintendo DS"

    if "360" in t:
        return "Xbox 360"
    if "series s" in t or "series x" in t or "xbox series" in t:
        return "Xbox Series"
    if "xbox one" in t or "one x" in t:
        return "Xbox One"

    if "ps5" in t or "playstation 5" in t or "play 5" in t:
        return "PS5"
    if "ps4" in t or "playstation 4" in t or "play 4" in t:
        return "PS4"
    if "ps3" in t or "playstation 3" in t or "play 3" in t:
        return "PS3"
    if "vita" in t:
        return "PS Vita"
    if "psp" in t or "playstation portable" in t:
        return "PSP"

    return None


def looks_like_accessory(title: str) -> bool:
    t = _norm(title)
    return any(hint in t for hint in _ACCESSORY_HINTS)


def normalize(listing: Listing) -> Optional[Listing]:
    if looks_like_accessory(listing.title):
        return None
    model = classify_model(listing.title)
    if model is None:
        return None
    listing.model = model
    return listing
