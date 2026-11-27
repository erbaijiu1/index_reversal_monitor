"""Pure CAP/GDP calculation and deterministic step-position mapping."""
from dataclasses import dataclass

@dataclass(frozen=True)
class AllocationConfig:
    floor: float = 0.20
    neutral: float = 0.40
    ceiling: float = 1.00
    buy_thresholds: tuple[float, ...] = (0.60, 0.55, 0.50, 0.45, 0.40)
    sell_thresholds: tuple[float, ...] = (0.70, 0.75, 0.80, 0.85, 0.90)
    buy_ratio: float = 2.0
    sell_weights: tuple[float, ...] = (0.20, 0.15, 0.15, 0.25, 0.25)

    def validate(self) -> None:
        if not 0 <= self.floor <= self.neutral <= self.ceiling <= 1:
            raise ValueError("position bounds must be ordered within [0, 1]")
        if self.buy_ratio <= 0 or not self.buy_thresholds or not self.sell_thresholds:
            raise ValueError("invalid steps")
        if list(self.buy_thresholds) != sorted(self.buy_thresholds, reverse=True):
            raise ValueError("buy thresholds must descend")
        if list(self.sell_thresholds) != sorted(self.sell_thresholds):
            raise ValueError("sell thresholds must ascend")
        if self.buy_thresholds[0] >= self.sell_thresholds[0]:
            raise ValueError("buy and sell ranges must not overlap")
        if len(self.sell_weights) != len(self.sell_thresholds) or any(w < 0 for w in self.sell_weights) or sum(self.sell_weights) <= 0:
            raise ValueError("invalid sell weights")

def cap_gdp_ratio(market_cap: float, reference_gdp: float) -> float:
    if market_cap <= 0 or reference_gdp <= 0:
        raise ValueError("market cap and GDP must be positive")
    return market_cap / reference_gdp

def target_weight(x: float, cfg: AllocationConfig = AllocationConfig()) -> float:
    cfg.validate()
    if x <= 0:
        raise ValueError("CAP/GDP ratio must be positive")
    if x < cfg.buy_thresholds[0]:
        k = sum(x < threshold for threshold in cfg.buy_thresholds)
        weights = [cfg.buy_ratio ** i for i in range(len(cfg.buy_thresholds))]
        fraction = sum(weights[:k]) / sum(weights)
        return cfg.neutral + (cfg.ceiling - cfg.neutral) * fraction
    if x < cfg.sell_thresholds[0]:
        return cfg.neutral
    k = sum(x >= threshold for threshold in cfg.sell_thresholds)
    fraction = sum(cfg.sell_weights[:k]) / sum(cfg.sell_weights)
    return cfg.neutral - (cfg.neutral - cfg.floor) * fraction
