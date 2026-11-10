"""Validate product FGS inputs and prepare the user's audited chance-table cache.

The public next_level amounts use the containing scene's chip unit. The caller
passes the configured chip_scale for custom scenes or the archive BB for fixed BB scenes.
This module does not run HRC, read saved strategies, or build the action tree.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import hashlib
import math
import os
from pathlib import Path
import tempfile
import threading


MODEL = "audited-threshold-fgs-v1"
DEFAULTS = {
    "enabled": False, "depth": 1, "depth3way": 1,
    "next_level_at": None, "next_level": None,
    "cache_capacity": 5000, "terminal_cache_capacity": 65536,
    "max_states": 20000, "max_sweeps": 2000000, "max_seconds": 60.0,
}
LIMITATIONS = [
    "未来手使用固定手牌排序的推注、跟注、过跟阈值模型，每手最多三人对抗。",
    "支持本桌 ICM 及可选 KO/PKO；不支持 FGS 与外桌 MTT 权益组合。",
    "平分实际底池时停止该分支的未来递归；三人分支另受 depth3way 限制。",
    "预算限制实际 FGS 计算时间和状态数，超限会报告未完成，不会以较浅结果冒充完成。",
    "有限轮阈值求解及本机机会表是已验证模型的一部分，不等同完整未来行动树均衡。",
]
CACHE_BYTES = 92167200
CACHE_SHA256 = "3bc0f9f3304599ce02ebd315137f644b2ec2f12a7768fa476baa2c4e37c793e0"
_RESOURCE_SPECS = (
    ("net.holdemresources.calculator_4.1.0.202603231401.jar",
     "net/holdemresources/sngnash/data/handranking/necombined.range", 662,
     "871775a8393968ac6be770835c1cce744aae91723c3181e1c7fdf5d53ceb52cc"),
    ("net.holdemresources.preflopdata.holdem_1.4.1.jar",
     "net/holdemresources/handevaluation/preflop/hands/data/2wh.dat", 344760,
     "f329b9633decff877074b6dc5ff924c437e4a632cf168b35d789441fe65fc151"),
    ("net.holdemresources.preflopdata.holdem_1.4.1.jar",
     "net/holdemresources/handevaluation/preflop/hands/data/3wh.dat", 85155720,
     "949cf28d7c78ad63063c33f372b8af121bd316d55e41662ebeaca02ddee2915d"),
)
_cache_lock = threading.Lock()


def _integer(value, field, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{field} 必须是 {minimum} 到 {maximum} 的整数。")
    return value


def _number(value, field, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{field} 必须是 {minimum:g} 到 {maximum:g} 的有限数值。")
    return float(value)


def validated_fgs(raw=None, equity=None, players=None):
    """Return normalized public settings; equity may be a UI or native spec.

    Disabled settings are validated too, so misspelled or stale fields are not
    silently discarded. A missing/None setting means the feature is disabled.
    """
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("fgs 必须是对象。")
    unknown = set(raw) - set(DEFAULTS)
    if unknown:
        raise ValueError("未知 FGS 设置：" + ", ".join(sorted(map(str, unknown))))
    cfg = {**deepcopy(DEFAULTS), **deepcopy(raw)}
    if type(cfg["enabled"]) is not bool:
        raise ValueError("fgs.enabled 必须是布尔值。")
    for name in ("depth", "depth3way"):
        cfg[name] = _integer(cfg[name], "fgs." + name, 0, 10)
    for name, lower, upper in (("cache_capacity", 0, 100000), ("terminal_cache_capacity", 0, 1000000),
                               ("max_states", 1, 1000000), ("max_sweeps", 1, 100000000)):
        cfg[name] = _integer(cfg[name], "fgs." + name, lower, upper)
    cfg["max_seconds"] = _number(cfg["max_seconds"], "fgs.max_seconds", .001, 86400)
    at, level = cfg["next_level_at"], cfg["next_level"]
    if (at is None) != (level is None):
        raise ValueError("fgs.next_level_at 与 next_level 必须一起设置或一起留空。")
    if at is not None:
        cfg["next_level_at"] = _integer(at, "fgs.next_level_at", 1, 10)
        if not isinstance(level, dict) or set(level) != {"big_blind", "small_blind", "ante"}:
            raise ValueError("fgs.next_level 必须包含 big_blind、small_blind、ante。")
        cfg["next_level"] = {name: _number(level[name], "fgs.next_level." + name,
            1e-8 if name == "big_blind" else 0, 1e12) for name in ("big_blind", "small_blind", "ante")}
        if cfg["next_level"]["small_blind"] > cfg["next_level"]["big_blind"]:
            raise ValueError("未来级别小盲不能大于大盲。")
    if cfg["enabled"]:
        if not isinstance(equity, dict) or equity.get("mode", equity.get("utility")) != "icm" or equity.get("other_stacks"):
            raise ValueError("FGS 需要本桌 ICM（可选 KO/PKO），不能与 ChipEV 或外桌 MTT 组合。")
        _integer(players, "FGS 本桌人数", 2, 10)
    return cfg


def _chips(value, scale, field):
    amount = Decimal(str(value)) * Decimal(scale)
    if amount != amount.to_integral_value() or not 0 <= amount <= 2**51:
        raise ValueError(f"{field} 不能精确转换为当前场景的整数筹码，或金额过大。")
    return int(amount)


def fgs_spec(raw, equity, tree, *, chip_scale=None):
    """Build compact['fgs'] (without resource path), or None when disabled.

    Flat enum strings match native/hrc_fgs.hpp via the native serializer.
    tree.settings supplies actual forced bets and initial skip-SB, not UI guesses.
    """
    cfg = validated_fgs(raw, equity, len(tree.rules.initial_stacks))
    if not cfg["enabled"]:
        return None
    scale = tree.rules.big_blind if chip_scale is None else chip_scale
    _integer(scale, "FGS chip_scale", 1, 2**51)
    hand = tree.settings.get("handdata", {})
    blinds = hand.get("blinds")
    if not isinstance(blinds, (list, tuple)) or len(blinds) != 3:
        raise ValueError("行动树缺少 FGS 所需的盲注与前注设置。")
    for value, label in zip(blinds, ("big_blind", "small_blind", "ante")):
        _integer(value, "tree." + label, 1 if label == "big_blind" else 0, 2**51)
    if tuple(blinds[:2]) != (tree.rules.big_blind, tree.rules.small_blind):
        raise ValueError("FGS 盲注与行动树规则不一致。")
    antes = {"REGULAR": "Regular", "BB_ANTE_ANTE_FIRST": "BBAnteFirst", "BB_ANTE_BLINDS_FIRST": "BBBlindFirst"}
    straddles = {"OFF": "Off", "SINGLE": "Single", "DOUBLE": "Double", "BUTTON": "Button"}
    if hand.get("anteType", "REGULAR") not in antes or hand.get("straddleType", "OFF") not in straddles:
        raise ValueError("行动树的前注或 straddle 类型不受 FGS 支持。")
    skip, moving = hand.get("skipSb", False), hand.get("movingBu", False)
    if type(skip) is not bool or type(moving) is not bool:
        raise ValueError("行动树的 skipSb/movingBu 必须为布尔值。")
    next_level = [0, 0, 0] if cfg["next_level"] is None else [
        _chips(cfg["next_level"][name], scale, "fgs.next_level." + name)
        for name in ("big_blind", "small_blind", "ante")]
    if cfg["next_level"] is not None and next_level[0] <= 0:
        raise ValueError("未来大盲必须大于零。")
    return {key: cfg[key] for key in ("depth", "depth3way", "cache_capacity", "terminal_cache_capacity",
                                      "max_states", "max_sweeps", "max_seconds")} | {
        "model": MODEL, "big_blind": blinds[0], "small_blind": blinds[1], "ante": blinds[2],
        "ante_type": antes[hand.get("anteType", "REGULAR")],
        "straddle": straddles[hand.get("straddleType", "OFF")], "moving_button": moving, "skip_sb": skip,
        "next_level_at": -1 if cfg["next_level_at"] is None else cfg["next_level_at"], "next_level": next_level,
        "chip_scale": scale, "limitations": list(LIMITATIONS), "budget_clock": "uncached_fgs_computation_seconds",
    }


def _digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def prepare_chances(plugins, cache_dir):
    """Return resource fields to merge into compact['fgs']; cache is hash pinned.

    Valid cached data can be reused without loading original code or resources.
    A missing cache is built independently from the local user's three audited
    resources. Corrupt caches are rejected explicitly, not silently accepted.
    """
    plugins, directory = Path(plugins).resolve(), Path(cache_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "fgs-chance-v1.bin"
    with _cache_lock:
        if not path.exists():
            from .hrc_fgs import ChanceTables
            tables = ChanceTables.from_installation(plugins)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=directory, prefix="fgs-chance-", suffix=".tmp", delete=False) as handle:
                    temporary = Path(handle.name)
                tables.write(temporary)
                if temporary.stat().st_size != CACHE_BYTES or _digest(temporary) != CACHE_SHA256:
                    raise ValueError("独立生成的 FGS 机会表未通过完整 hash 校验。")
                os.replace(temporary, path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        if not path.is_file() or path.stat().st_size != CACHE_BYTES or _digest(path) != CACHE_SHA256:
            raise ValueError(f"FGS 机会缓存损坏或版本不符：{path}")
    return {"chance_cache": str(path), "chance_sha256": CACHE_SHA256, "chance_bytes": CACHE_BYTES,
            "chance_provenance": {"format": "FGSCHN01", "independent_accumulation": True,
                "original_strategy_read": False, "original_leaf_values_read": False,
                "resources": [{"jar": str(plugins / jar), "member": member, "bytes": size, "sha256": digest}
                              for jar, member, size, digest in _RESOURCE_SPECS]}}
