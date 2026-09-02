"""PredictionStore — append-only, immutable JSONL ledger of predictions.

Every prediction is written exactly once under a globally unique
``prediction_id``. Duplicate IDs raise; nothing is ever overwritten. This is
the PIT (point-in-time) backbone for downstream evaluation: predictions are
frozen the moment they are emitted so that any later re-run cannot silently
mutate history.
"""
from __future__ import annotations
import json, os
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Iterator, Optional


@dataclass
class Prediction:
    """A single frozen prediction. ``prediction`` is the model's numeric signal
    (e.g. expected return); ``probability``/``confidence`` are optional
    probabilistic annotations."""
    prediction_id: str
    experiment_id: str
    model_id: str
    timestamp: str
    symbol: str
    target_id: str
    prediction: float
    probability: Optional[float] = None
    confidence: Optional[float] = None
    model_version: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


REQUIRED_FIELDS = (
    "prediction_id", "experiment_id", "model_id", "timestamp",
    "symbol", "target_id", "prediction", "probability", "confidence",
    "model_version",
)


class PredictionStore:
    """Append-only JSONL store keyed by immutable ``prediction_id``."""

    def __init__(self, path: str):
        self.path = path
        self._ids: set = set()
        self._rows: list = []
        self._load()

    # -- load --------------------------------------------------------------
    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                pid = row.get("prediction_id")
                # tolerate pre-existing duplicates on disk, but only count once
                if pid is not None and pid not in self._ids:
                    self._ids.add(pid)
                    self._rows.append(row)

    # -- write -------------------------------------------------------------
    def append(self, prediction: Any) -> str:
        """Append one prediction. Raises ValueError on duplicate ID or missing
        required fields. Returns the prediction_id."""
        row = prediction.to_dict() if isinstance(prediction, Prediction) else dict(prediction)

        pid = row.get("prediction_id")
        if pid is None:
            raise ValueError("prediction_id is required")
        missing = [k for k in REQUIRED_FIELDS if k not in row]
        if missing:
            raise ValueError(f"missing required fields: {missing}")
        if pid in self._ids:
            raise ValueError(f"prediction {pid} already exists (immutable)")

        self._ids.add(pid)
        self._rows.append(row)
        with open(self.path, "a") as f:
            f.write(json.dumps(row) + "\n")
        return pid

    # -- read --------------------------------------------------------------
    def count(self) -> int:
        return len(self._rows)

    def get(self, prediction_id: str) -> Optional[Dict[str, Any]]:
        for row in self._rows:
            if row["prediction_id"] == prediction_id:
                return dict(row)
        return None

    def iter_predictions(self) -> Iterator[Dict[str, Any]]:
        for row in self._rows:
            yield dict(row)

    def query(self, **filters: Any) -> list:
        """Return predictions matching exact equality on the given fields."""
        out = []
        for row in self._rows:
            if all(row.get(k) == v for k, v in filters.items()):
                out.append(dict(row))
        return out

    def ids(self) -> set:
        return set(self._ids)
