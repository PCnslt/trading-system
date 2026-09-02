"""ModelRegistry — governed lifecycle for research models.

A model climbs a strict ladder:

    CANDIDATE -> TESTING -> CHALLENGER -> CHAMPION

and can be retired to GRAVEYARD at any stage. The critical rule is that a
model can NEVER be auto-promoted to CHAMPION: the CHALLENGER -> CHAMPION step
requires an explicit ``oos_evidence`` payload (out-of-sample results) passed by
the caller. No evidence, no promotion.
"""
from __future__ import annotations
import json, os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

CANDIDATE = "CANDIDATE"
TESTING = "TESTING"
CHALLENGER = "CHALLENGER"
CHAMPION = "CHAMPION"
GRAVEYARD = "GRAVEYARD"

VALID_STATUSES = (CANDIDATE, TESTING, CHALLENGER, CHAMPION, GRAVEYARD)

# Single-step transitions only — no skipping the ladder.
ALLOWED_TRANSITIONS: Dict[str, tuple] = {
    CANDIDATE:   (TESTING, GRAVEYARD),
    TESTING:     (CHALLENGER, GRAVEYARD),
    CHALLENGER:  (CHAMPION, GRAVEYARD),
    CHAMPION:    (GRAVEYARD,),
    GRAVEYARD:   (),
}


@dataclass
class Model:
    model_id: str
    status: str = CANDIDATE
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    oos_evidence: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ModelRegistry:
    """In-memory registry with optional JSONL persistence."""

    def __init__(self, path: Optional[str] = None):
        self.path = path
        self._models: Dict[str, Model] = {}
        self._load()

    # -- persistence -------------------------------------------------------
    def _load(self) -> None:
        if not self.path or not os.path.exists(self.path):
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
                mid = row.get("model_id")
                if mid is None or mid in self._models:
                    continue
                self._models[mid] = Model(
                    model_id=mid,
                    status=row.get("status", CANDIDATE),
                    created_at=row.get("created_at", ""),
                    updated_at=row.get("updated_at", ""),
                    oos_evidence=dict(row.get("oos_evidence") or {}),
                    notes=row.get("notes", ""),
                )

    def _save(self) -> None:
        if not self.path:
            return
        with open(self.path, "w") as f:
            for m in self._models.values():
                f.write(json.dumps(m.to_dict()) + "\n")

    # -- registration ------------------------------------------------------
    def register(self, model_id: str, status: str = CANDIDATE,
                 oos_evidence: Optional[Dict[str, Any]] = None,
                 notes: str = "") -> str:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status {status}")
        if model_id in self._models:
            raise ValueError(f"model {model_id} already registered (immutable)")
        self._models[model_id] = Model(
            model_id=model_id, status=status,
            oos_evidence=dict(oos_evidence or {}), notes=notes,
        )
        self._save()
        return model_id

    # -- reads -------------------------------------------------------------
    def get(self, model_id: str) -> Model:
        if model_id not in self._models:
            raise KeyError(f"model {model_id} not found")
        return self._models[model_id]

    def status(self, model_id: str) -> str:
        return self.get(model_id).status

    def count(self) -> int:
        return len(self._models)

    def models_by_status(self, status: str) -> List[Model]:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status {status}")
        return [m for m in self._models.values() if m.status == status]

    # -- lifecycle ---------------------------------------------------------
    def promote(self, model_id: str, new_status: str,
                oos_evidence: Optional[Dict[str, Any]] = None,
                notes: str = "") -> str:
        """Advance a model along the ladder.

        CHALLENGER -> CHAMPION is the hard gate: it requires a truthy
        ``oos_evidence`` dict. There is no code path that auto-promotes."""
        if new_status not in VALID_STATUSES:
            raise ValueError(f"invalid status {new_status}")
        model = self.get(model_id)
        if model.status == new_status:
            return new_status

        if new_status not in ALLOWED_TRANSITIONS.get(model.status, ()):
            raise ValueError(f"illegal transition {model.status} -> {new_status}")

        if new_status == CHAMPION:
            if model.status != CHALLENGER:
                raise ValueError("only CHALLENGER may be promoted to CHAMPION")
            if not oos_evidence:
                raise ValueError(
                    "CHALLENGER -> CHAMPION requires explicit OOS evidence "
                    "(never auto-promote)"
                )
            model.oos_evidence = dict(oos_evidence)

        model.status = new_status
        model.updated_at = datetime.utcnow().isoformat()
        if notes:
            model.notes = notes
        self._save()
        return new_status

    def retire(self, model_id: str, notes: str = "") -> str:
        return self.promote(model_id, GRAVEYARD, notes=notes)
