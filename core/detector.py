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
    discount_pct: float
    basis: str = ""
    sample_size: int = 0


def _quantile(sorted_vals: List[float], q: float) -> float:
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
    def __init__(self, min_discount_pct: float, min_samples: int, floor_ratio: float):
        self.min_discount = min_discount_pct / 100.0
        self.min_samples = min_samples
        self.floor_ratio = floor_ratio

    def evaluate(self, listing: Listing, sample_prices: List[int],
                 basis: str = "") -> Optional[Opportunity]:
        if not listing.is_priced():
            return None
        if len(sample_prices) < self.min_samples:
            return None

        vals = sorted(float(p) for p in sample_prices)
        med = median(vals)
        p25 = _quantile(vals, 0.25)
        threshold = min(med * (1 - self.min_discount), p25)
        floor = med * self.floor_ratio

        price = float(listing.price)
        if price < floor:
            return None
        if price >= threshold:
            return None

        discount = (med - price) / med * 100.0
        return Opportunity(
            listing=listing,
            median_price=med,
            threshold=threshold,
            discount_pct=discount,
            basis=basis,
            sample_size=len(sample_prices),
        )
