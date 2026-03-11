"""Shared data models for the fraud detection system."""

import json
from dataclasses import dataclass, field
from typing import Optional


FRAUD_SCORE_BLOCK_THRESHOLD = 0.8


@dataclass
class FraudSignal:
    """A single fraud indicator produced by a check."""

    check_name: str
    flag: str
    score: float = 0.0
    blocking: bool = False


@dataclass
class FraudCheckResult:
    """Aggregated result from one or more fraud checks."""

    signals: list[FraudSignal] = field(default_factory=list)

    @property
    def fraud_score(self) -> float:
        """Combined score clamped to [0, 1]."""
        return max(0.0, min(1.0, sum(s.score for s in self.signals)))

    @property
    def fraud_flags(self) -> list[str]:
        return [s.flag for s in self.signals]

    @property
    def should_block(self) -> bool:
        """True if any signal is explicitly blocking or combined score exceeds threshold."""
        if any(s.blocking for s in self.signals):
            return True
        return self.fraud_score >= FRAUD_SCORE_BLOCK_THRESHOLD

    @property
    def fraud_flags_json(self) -> Optional[str]:
        flags = self.fraud_flags
        return json.dumps(flags) if flags else None

    @property
    def blocking_signal(self) -> Optional[FraudSignal]:
        """Return the first blocking signal, if any."""
        for s in self.signals:
            if s.blocking:
                return s
        return self.signals[0] if self.should_block and self.signals else None
