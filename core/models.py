from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Listing:
    id: str
    source: str
    title: str
    price: Optional[int]
    url: str
    model: Optional[str] = None
    variant: Optional[str] = None
    region: Optional[str] = None
    image: Optional[str] = None
    posted_at: Optional[str] = None

    def is_priced(self) -> bool:
        return self.price is not None and self.price > 0
