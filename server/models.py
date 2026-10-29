import threading
from typing import Any

from pydantic import BaseModel, Field, StrictFloat, StrictInt, field_validator, model_validator

SESSIONS: dict[str, "SessionState"] = {}
SESSIONS_LOCK = threading.Lock()


class Player(BaseModel):
    id: str = Field(pattern=r"^P[1-4]$")
    name: str = Field(min_length=1, max_length=40)

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, name):
        if not name.strip():
            raise ValueError("player name cannot be blank")
        return name.strip()


class SessionCreate(BaseModel):
    game_id: str
    players: list[Player] = Field(min_length=2, max_length=4)
    teams: dict[str, list[str]] | None = None
    rules: dict[str, Any] = Field(default_factory=dict)

    @field_validator("players")
    @classmethod
    def unique_player_ids(cls, players):
        ids = [p.id for p in players]
        if len(set(ids)) != len(ids):
            raise ValueError("player ids must be unique")
        return players


class SessionState(BaseModel):
    game_id: str
    players: list[Player]
    teams: dict[str, list[str]] | None = None
    rules: dict[str, Any]
    round: int = 1
    total_rounds: int = 1
    turn: str | None = None
    scores: dict[str, int]
    status: str = "playing"
    applied_hashes: list[str] = Field(default_factory=list)
    history: list[dict[str, Any]] = Field(default_factory=list)


class ApplyRequest(BaseModel):
    report: dict[str, Any]
    signature: str


class RulesUpdate(BaseModel):
    rules: dict[str, StrictInt | StrictFloat]

    @field_validator("rules")
    @classmethod
    def valid_rule_values(cls, rules):
        if any(isinstance(value, bool) or not 0 <= value <= 3600 for value in rules.values()):
            raise ValueError("rule values must be numeric and between 0 and 3600")
        return rules


class JudgeConfig(BaseModel):
    session_id: str
    game: str
    round: int = Field(ge=1)
    rois: dict[str, list[float]] = Field(default_factory=dict)
    seeds: dict[str, list[float]] = Field(default_factory=dict)
    teams: dict[str, list[str]] | None = None
    players: list[str] = Field(default_factory=list)
    cues: dict[str, Any] = Field(default_factory=dict)
    rules: dict[str, Any] = Field(default_factory=dict)
    question_id: str | None = None
    throw_count: dict[str, int] = Field(default_factory=dict)

    @field_validator("rois")
    @classmethod
    def validate_rois(cls, rois):
        for name, roi in rois.items():
            if len(roi) != 4 or any(not 0 <= float(value) <= 1 for value in roi):
                raise ValueError(f"{name} must be four normalized coordinates")
            x1, y1, x2, y2 = roi
            if x1 >= x2 or y1 >= y2:
                raise ValueError(f"{name} must have positive area")
        return rois

    @model_validator(mode="after")
    def valid_seeds(self):
        for player, point in self.seeds.items():
            if len(point) != 2 or any(not 0 <= float(value) <= 1 for value in point):
                raise ValueError(f"{player} seed must be a normalized point")
        return self
