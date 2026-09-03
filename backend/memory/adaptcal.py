"""Post-hoc ladder threshold tuning from labelled demo outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from backend.scoring.ladder import DEFAULT_BANDS

DEFAULT_ENABLED = False
DEFAULT_STEP = 0.02
DEFAULT_TARGET = "false_challenge_rate"

_BAND_MAX_CEILING = 1.01
_BAND_MAX_FLOOR = 1e-9
_EARLY_TIERS = (0, 1)
_HIGH_TIERS = (2, 3)


@dataclass(frozen=True)
class AdaptCalSnapshot:
    enabled: bool
    step: float
    target: str
    false_challenge_rate: float
    catch_rate: float
    denominators: dict
    ladder_bands: list[dict]
    adjusted: bool
    detail: str


class AdaptCal:
    """In-memory calibrator. Scorers must not call observe() at score-time."""

    def __init__(self, *, config: Mapping[str, Any] | None = None) -> None:
        self._enabled = DEFAULT_ENABLED
        self._step = DEFAULT_STEP
        self._target = DEFAULT_TARGET
        self._bands = _bands_from_default()
        self._legit_tx = 0
        self._challenged_legit = 0
        self._fraud_tx = 0
        self._caught_fraud = 0
        self._load_config(config)

    def observe(
        self, *, tier: int, is_legitimate: bool, ground_truth_fraud: bool
    ) -> None:
        """Record one settled outcome. Stores counters only, not handles or text."""
        if is_legitimate:
            self._legit_tx += 1
            if int(tier) >= 1:
                self._challenged_legit += 1
        if ground_truth_fraud:
            self._fraud_tx += 1
            if int(tier) >= 2:
                self._caught_fraud += 1

    def rates(self) -> dict[str, Any]:
        return {
            "false_challenge_rate": _ratio(self._challenged_legit, self._legit_tx),
            "catch_rate": _ratio(self._caught_fraud, self._fraud_tx),
            "denominators": {
                "legit_tx": self._legit_tx,
                "challenged_legit": self._challenged_legit,
                "fraud_tx": self._fraud_tx,
                "caught_fraud": self._caught_fraud,
            },
        }

    def propose(self) -> AdaptCalSnapshot:
        measured = self.rates()
        bands = _copy_bands(self._bands)
        adjusted = False
        if self._enabled:
            bands, adjusted = self._tune(bands, measured)
        return AdaptCalSnapshot(
            enabled=self._enabled,
            step=self._step,
            target=self._target,
            false_challenge_rate=measured["false_challenge_rate"],
            catch_rate=measured["catch_rate"],
            denominators=dict(measured["denominators"]),
            ladder_bands=bands,
            adjusted=adjusted,
            detail=_detail(self._enabled, adjusted, measured, self._step),
        )

    def apply(self) -> AdaptCalSnapshot:
        snapshot = self.propose()
        self._bands = _copy_bands(snapshot.ladder_bands)
        return snapshot

    def current_bands(self) -> list[dict[str, Any]]:
        return _copy_bands(self._bands)

    def _load_config(self, config: Mapping[str, Any] | None) -> None:
        if not isinstance(config, Mapping):
            return
        section = config.get("adaptcal")
        if isinstance(section, Mapping):
            if "enabled" in section:
                self._enabled = bool(section["enabled"])
            if "step" in section:
                self._step = float(section["step"])
            if "target" in section:
                self._target = str(section["target"])
        raw_ladder = config.get("ladder")
        parsed = _parse_ladder(raw_ladder)
        if parsed:
            self._bands = _normalize(parsed)

    def _tune(
        self, bands: list[dict[str, Any]], measured: Mapping[str, Any]
    ) -> tuple[list[dict[str, Any]], bool]:
        den = measured["denominators"]
        changed = False
        by_tier = {int(row["tier"]): dict(row) for row in bands}
        if den["legit_tx"] > 0 and measured["false_challenge_rate"] > 0.0:
            for tier in _EARLY_TIERS:
                if tier in by_tier:
                    by_tier[tier]["max"] = float(by_tier[tier]["max"]) + self._step
                    changed = True
        if den["fraud_tx"] > 0 and measured["catch_rate"] < 1.0:
            for tier in _HIGH_TIERS:
                if tier in by_tier:
                    by_tier[tier]["max"] = float(by_tier[tier]["max"]) - self._step
                    changed = True
        tuned = _normalize(list(by_tier.values()))
        if tuned != _normalize(bands):
            changed = True
        return tuned, changed


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return min(max(numerator / denominator, 0.0), 1.0)


def _bands_from_default() -> list[dict[str, Any]]:
    return [
        {"tier": int(tier), "max": float(max_score), "action": str(action)}
        for tier, max_score, action in DEFAULT_BANDS
    ]


def _parse_ladder(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    parsed: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, Mapping):
            continue
        parsed.append(
            {
                "tier": int(row["tier"]),
                "max": float(row["max"]),
                "action": str(row["action"]),
            }
        )
    return parsed


def _copy_bands(bands: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"tier": int(row["tier"]), "max": float(row["max"]), "action": str(row["action"])}
        for row in bands
    ]


def _normalize(bands: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = _copy_bands(bands)
    rows.sort(key=lambda row: row["tier"])
    if not rows:
        return _bands_from_default()
    last_index = len(rows) - 1
    previous = _BAND_MAX_FLOOR
    out: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        maximum = min(max(float(row["max"]), _BAND_MAX_FLOOR), _BAND_MAX_CEILING)
        if index == last_index:
            maximum = _BAND_MAX_CEILING
        if maximum < previous:
            maximum = previous
        previous = maximum
        out.append({"tier": int(row["tier"]), "max": maximum, "action": str(row["action"])})
    return out


def _detail(enabled: bool, adjusted: bool, measured: Mapping[str, Any], step: float) -> str:
    den = measured["denominators"]
    fcr = (
        f"false_challenge_rate={measured['false_challenge_rate']:.4f} "
        f"({den['challenged_legit']}/{den['legit_tx']})"
    )
    catch = (
        f"catch_rate={measured['catch_rate']:.4f} "
        f"({den['caught_fraud']}/{den['fraud_tx']})"
    )
    if not enabled:
        return f"AdaptCal disabled; bands unchanged. {fcr}; {catch}."
    if not adjusted:
        return f"No band change. {fcr}; {catch}."
    return f"Bands updated by step={step:.2f}. {fcr}; {catch}."
