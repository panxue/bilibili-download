import os
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into a copy of base, returning the new dict."""
    out: dict = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _set_nested(cfg: dict, section: str, key: str, value) -> None:
    cfg.setdefault(section, {})[key] = value


class Settings:
    """Backend global settings: config.toml + environment variable overrides."""

    def __init__(self, config_file: str | Path | None = None):
        defaults: dict = {
            "server": {"host": "127.0.0.1", "port": 8000, "auth_token": ""},
            "download": {
                "dir": str(PROJECT_ROOT / "downloads"),
                "staging_dir": str(PROJECT_ROOT / "data" / ".parts"),
                "ffmpeg_path": "ffmpeg",
                "max_concurrent": 2,
                "subdir_by_uploader": True,
                "file_template": "[%(id)s] %(title)s.%(ext)s",
                "overwrite": False,
                "audio_format": "mp3",
            },
            "network": {"proxy": ""},
            "storage": {"db_path": str(PROJECT_ROOT / "data" / "jobs.db"),
                         "cookie_file": str(PROJECT_ROOT / "data" / "cookies.txt")},
        }

        path = Path(config_file) if config_file else PROJECT_ROOT / "backend" / "config.toml"
        if path.is_file():
            with open(path, "rb") as f:
                defaults = _deep_merge(defaults, tomllib.load(f))

        int_keys = {
            ("server", "port"),
            ("download", "max_concurrent"),
        }
        env_map = {
            "BLDLP_HOST": ("server", "host"),
            "BLDLP_PORT": ("server", "port"),
            "BLDLP_TOKEN": ("server", "auth_token"),
            "BLDLP_DOWNLOAD_DIR": ("download", "dir"),
            "BLDLP_CONCURRENT": ("download", "max_concurrent"),
            "BLDLP_PROXY": ("network", "proxy"),
        }
        for env, (sec, key) in env_map.items():
            if env in os.environ:
                val: str | int = os.environ[env]
                if (sec, key) in int_keys:
                    val = int(val)
                _set_nested(defaults, sec, key, val)

        self.raw: dict = defaults
        self._resolve_paths()

    def _resolve_paths(self) -> None:
        for root_key in ("dir", "staging_dir"):
            v = self.raw["download"][root_key]
            self.raw["download"][root_key] = self._abs(v)
        self.raw["storage"]["db_path"] = self._abs(self.raw["storage"]["db_path"])

    @staticmethod
    def _abs(v: str) -> str:
        if v.startswith(("/", "~")):
            return str(Path(v).expanduser().resolve())
        return str((PROJECT_ROOT / v).resolve())

    # ---- Convenience access ----
    @property
    def server(self) -> dict:
        return self.raw["server"]

    @property
    def download(self) -> dict:
        return self.raw["download"]

    @property
    def network(self) -> dict:
        return self.raw["network"]

    @property
    def storage(self) -> dict:
        return self.raw["storage"]

    @property
    def download_dir(self) -> str:
        return self.download["dir"]

    @property
    def staging_dir(self) -> str:
        return self.download["staging_dir"]

    @property
    def db_path(self) -> str:
        return self.storage["db_path"]

    @property
    def cookie_file(self) -> str:
        return self.storage["cookie_file"]

    def ensure_dirs(self) -> None:
        Path(self.download_dir).mkdir(parents=True, exist_ok=True)
        Path(self.staging_dir).mkdir(parents=True, exist_ok=True)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.cookie_file).parent.mkdir(parents=True, exist_ok=True)