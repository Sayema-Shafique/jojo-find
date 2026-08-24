import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

DEFAULT_STATE_FILE = os.path.join(os.path.dirname(__file__), "data", "seen_jobs.json")


class StateManager:
    def __init__(self, state_file: str = DEFAULT_STATE_FILE):
        self.state_file = state_file
        self.seen: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self.state_file) as f:
                data = json.load(f)
            self.seen = data.get("seen", {})
        except (FileNotFoundError, json.JSONDecodeError):
            self.seen = {}

    def is_new(self, job_id: str) -> bool:
        return job_id not in self.seen

    def mark_seen(self, job_ids: list[str]) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for job_id in job_ids:
            if job_id not in self.seen:
                self.seen[job_id] = today

    def prune(self, max_age_days: int = 30) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).strftime(
            "%Y-%m-%d"
        )
        before = len(self.seen)
        self.seen = {k: v for k, v in self.seen.items() if v >= cutoff}
        pruned = before - len(self.seen)
        if pruned:
            logger.info("Pruned %d expired entries from state", pruned)

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.state_file), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"seen": self.seen}, f, indent=2)
            os.replace(tmp, self.state_file)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        logger.info("State saved: %d entries", len(self.seen))
