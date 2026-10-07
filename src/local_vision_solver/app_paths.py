"""Product paths never depend on the process working directory."""
from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    data: Path

    @classmethod
    def for_user(cls, data_dir: Path | None = None):
        if data_dir is None:
            data_dir = cls.default_root()
            pointer=data_dir/'location.json'
            if pointer.is_file():
                import json
                selected=json.loads(pointer.read_text(encoding='utf-8'))['data_directory']
                if not isinstance(selected,str) or not Path(selected).is_absolute():
                    raise ValueError('Invalid saved data directory')
                data_dir=Path(selected)
        return cls(data_dir.expanduser().resolve())

    @staticmethod
    def default_root():
        return Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local'/'share')))/'VisionSolver'

    @property
    def config(self): return self.data / "config.toml"
    @property
    def database(self): return self.data / "state.sqlite3"
    @property
    def sessions(self): return self.data / "sessions"
    @property
    def models(self): return self.data / "models"
    @property
    def runtime(self): return self.data / "runtime" / "llama"
    @property
    def downloads(self): return self.data / "downloads"
    @property
    def logs(self): return self.data / "logs"
    @property
    def recovery(self): return self.data / "recovery"

    def ensure(self):
        for path in (self.data, self.sessions, self.models, self.runtime.parent,
                     self.downloads, self.logs, self.recovery):
            path.mkdir(parents=True, exist_ok=True)
        return self
