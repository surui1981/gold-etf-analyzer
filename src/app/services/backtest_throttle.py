"""回测 5 分钟节流缓存（V0.71.0）。

设计：
- 模块级 ``dict[hash, (timestamp, result)]``，key 为 ``sha256(canonical_json(params))[:16]``；
- 同 params 5 分钟内直接返回缓存（含 ``cached=True`` 标记供前端展示）；
- 单用户本机部署，无需 per-user；hash 碰撞概率 ~2⁻⁶⁴ 可忽略；
- ``clear()`` 显式清空（测试隔离 / 手动刷新用）。

不引入新依赖（仅 stdlib hashlib / json / datetime）。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

# V0.71.0：缓存 TTL 固定 300s（5 分钟），前端节流 500ms + 后端节流 300s
TTL_SECONDS = 300

# 最大缓存条目数：超过则清空（防内存膨胀，罕见 param grid 仍安全）
MAX_CACHE_SIZE = 64

_CACHE: dict[str, tuple[datetime, dict]] = {}


def _canonical_params(params: dict) -> str:
    """按 key 排序 + 紧凑分隔符序列化（确保同 param 不同字段顺序生成同 hash）。"""
    return json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)


def hash_params(params: dict) -> str:
    """params → 16 字符 hex hash（sha256 截断）。"""
    return hashlib.sha256(_canonical_params(params).encode("utf-8")).hexdigest()[:16]


def get_cached(params: dict) -> dict | None:
    """读取缓存；过期或缺失返回 None。命中时附带 ``cached=True`` + ``cached_age_seconds`` 标记。

    Note:
        命中侧 ``cached_age_seconds`` 由调用方计算更精确，本函数只返回原值 + 标志位。
    """
    h = hash_params(params)
    item = _CACHE.get(h)
    if item is None:
        return None
    stored_at, result = item
    if datetime.now() - stored_at > timedelta(seconds=TTL_SECONDS):
        _CACHE.pop(h, None)
        return None
    age = int((datetime.now() - stored_at).total_seconds())
    return {**result, "cached": True, "cached_age_seconds": age}


def store(params: dict, result: dict) -> None:
    """写入缓存。超 MAX_CACHE_SIZE 时整体清空（罕见 param grid 场景）。"""
    if len(_CACHE) >= MAX_CACHE_SIZE:
        _CACHE.clear()
    _CACHE[hash_params(params)] = (
        datetime.now(),
        {k: v for k, v in result.items() if k != "cached"},
    )


def clear() -> None:
    """显式清空缓存（测试隔离 / 手动刷新）。"""
    _CACHE.clear()


def cache_size() -> int:
    """当前缓存条目数（供诊断 / 单元测试）。"""
    return len(_CACHE)
