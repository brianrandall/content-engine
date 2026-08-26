from dataclasses import dataclass, field
import threading


@dataclass
class ProductionRunState:
    mode: str
    cancel_event: threading.Event = field(
        default_factory=threading.Event
    )
    status: str = "running"
    selected: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    skipped: int = 0
    current_topic: str | None = None
    _lock: threading.Lock = field(
        default_factory=threading.Lock,
        repr=False,
    )

    def request_stop(self):
        with self._lock:
            if self.status == "running":
                self.status = "stopping"
                self.cancel_event.set()
                return True
            return False

    def update(self, **changes):
        with self._lock:
            for name, value in changes.items():
                setattr(self, name, value)

    def snapshot(self):
        with self._lock:
            return {
                "mode": self.mode,
                "status": self.status,
                "selected": self.selected,
                "completed": self.completed,
                "failed": self.failed,
                "cancelled": self.cancelled,
                "skipped": self.skipped,
                "current_topic": self.current_topic,
            }
