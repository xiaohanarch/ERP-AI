"""场景图注册表：scene -> compiled graph。"""
from __future__ import annotations

from hub.graphs import batch, diag, eventdiag, taxcode

GRAPHS = {
    "ap.diag": diag.build,
    "ap.batch": batch.build,
    "ap.taxcode": taxcode.build,
    "ap.event": eventdiag.build,   # 仅内部（事件订阅线程）
}

USER_SCENES = ("ap.diag", "ap.batch", "ap.taxcode")
