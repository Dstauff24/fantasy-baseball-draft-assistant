from __future__ import annotations

import traceback as tb_module
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TraceEvent:
    stage: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class DebugTrace:
    enabled: bool = False
    events: list[TraceEvent] = field(default_factory=list)
    failed_stage: str | None = None
    exception_type: str | None = None
    exception_message: str | None = None
    traceback: str | None = None

    def log(self, stage: str, message: str, **data: Any) -> None:
        if self.enabled:
            self.events.append(TraceEvent(stage=stage, message=message, data=data))

    def fail(self, stage: str, exc: Exception, capture_tb: bool = True) -> None:
        self.failed_stage = stage
        self.exception_type = type(exc).__name__
        self.exception_message = str(exc) if str(exc) else repr(exc)
        if capture_tb:
            self.traceback = tb_module.format_exc()

    def to_dict(self) -> dict[str, Any]:
        return {
            "failed_stage": self.failed_stage,
            "exception_type": self.exception_type,
            "exception_message": self.exception_message,
            "traceback": self.traceback if self.enabled else None,
            "events": [
                {"stage": e.stage, "message": e.message, **e.data}
                for e in self.events
            ],
        }

    @staticmethod
    def make(include_debug: bool) -> "DebugTrace":
        return DebugTrace(enabled=include_debug)