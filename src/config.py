"""config.yml を読み込んで辞書として返す"""

from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).parent.parent / "config.yml"


def load_config(path: Path = _CONFIG_PATH) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"設定ファイルが見つかりません: {path}\n"
            "config.yml.example をコピーして config.yml を作成してください"
        )
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)
