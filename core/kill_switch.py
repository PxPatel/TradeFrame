from pathlib import Path


class KillSwitch:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @property
    def halted(self) -> bool:
        return self.path.exists()

    def halt(self, reason: str):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(reason + "\n", encoding="utf-8")

    def clear(self):
        self.path.unlink(missing_ok=True)