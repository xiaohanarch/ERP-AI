"""场景图注册表：scene -> compiled graph。"""
from __future__ import annotations

from hub.graphs import batch, diag, eventdiag, proc, taxcode, xdom

GRAPHS = {
    "ap.diag": diag.build,
    "ap.batch": batch.build,
    "ap.taxcode": taxcode.build,
    "ap.event": eventdiag.build,   # 仅内部（事件订阅线程）
    "proc.diag": proc.build,       # 采购域查询（独立可用 / 被委派执行）
    "xdom.diag": xdom.build,       # 跨域根因诊断（AP -> 委派采购域）
}

USER_SCENES = ("ap.diag", "ap.batch", "ap.taxcode", "proc.diag", "xdom.diag")
