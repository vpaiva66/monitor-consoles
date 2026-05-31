"""Decide se um anúncio é uma 'oportunidade' (preço abaixo do normal).

Usa mediana + IQR (intervalo interquartil) por modelo, robusto a outliers:
um anúncio é oportunidade se  price < mediana - k*IQR,  desde que haja
amostras suficientes e o preço não seja baixo demais (provável cilada).
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import List, Optional

from .models import Listing


@dataclass
class Opportunity:
    listing: Listing
    median_price: float
    threshold: float
    discount_pct: float          # quanto abaixo da mediana, em %
    basis: str = ""              # base de comparação, ex: "PS4 Slim" ou "PS4 (geral)"
    sample_size: int = 0         # nº de anúncios usados na mediana


def _quantile(sorted_vals: List[float], q: float) -> float:
    """Quantil por interpolação linear (q em [0,1])."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


class Detector:
    def __init__(self, iqr_k: float, min_samples: int, floor_ratio: float):
        self.iqr_k = iqr_k
        self.min_samples = min_samples
        self.floor_ratio = floor_ratio

    def evaluate(self, listing: Listing, sample_prices: List[int],
                 basis: str = "") -> Optional[Opportunity]:
        """Retorna Opportunity se o anúncio for uma boa oportunidade, senão None."""
        if not listing.is_priced():
            return None
        if len(sample_prices) < self.min_samples:
            return None  # ainda em aquecimento para esta base de comparação

        vals = sorted(float(p) for p in sample_prices)
        med = median(vals)
        q1 = _quantile(vals, 0.25)
        q3 = _quantile(vals, 0.75)
        iqr = q3 - q1
        threshold = med - self.iqr_k * iqr
        floor = med * self.floor_ratio

        price = float(listing.price)
        if price < floor:
            return None  # barato demais => provável golpe/peça/defeito
        if price >= threshold:
            return None  # dentro do normal

        discount = (med - price) / med * 100.0
        return Opportunity(
            listing=listing,
            median_price=med,
            threshold=threshold,
            discount_pct=discount,
            basis=basis,
            sample_size=len(sample_prices),
        )
