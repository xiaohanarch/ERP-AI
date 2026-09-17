"""场景配置：工具白名单 + 降级开关（运行期可切换，重启复位——演示口径）。"""
from __future__ import annotations

import threading

import yaml

from app.config import settings

_lock = threading.Lock()
_scenes: dict[str, dict] = {}


def load() -> None:
    global _scenes
    with open(settings.scenes_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    with _lock:
        _scenes = data.get("scenes", {})
    print(f"[scenes] 已加载 {len(_scenes)} 个场景：{list(_scenes)}", flush=True)


def is_enabled(scene: str) -> bool:
    with _lock:
        cfg = _scenes.get(scene)
    return bool(cfg and cfg.get("enabled", True))


def scene_tools(scene: str) -> list[str]:
    with _lock:
        cfg = _scenes.get(scene)
    return list(cfg.get("tools", [])) if cfg else []


def set_enabled(scene: str, enabled: bool) -> bool:
    with _lock:
        if scene not in _scenes:
            return False
        _scenes[scene]["enabled"] = enabled
        return True


def all_scenes() -> list[dict]:
    with _lock:
        return [{"code": code, **cfg} for code, cfg in _scenes.items()]
