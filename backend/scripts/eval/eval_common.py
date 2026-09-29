# -*- coding: utf-8 -*-
"""评测公共工具：置信区间与通过率统计（3.1 修复）

提供：
  - wilson_ci : 二项比例的 Wilson score 95% 置信区间
  - mean_ci   : 连续 0~1 指标的均值 ± 正态近似 95% CI
  - pass_rate : 阈值通过率 + Wilson CI
"""
import math


def wilson_ci(n: int, k: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval：二项比例 k/n 的 95% 置信区间（n=0 时返回 [0,1]）"""
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) / n) + z * z / (4 * n * n)) / denom
    return (round(max(0.0, center - margin), 3), round(min(1.0, center + margin), 3))


def mean_ci(vals: list[float], z: float = 1.96) -> tuple[float, float, float]:
    """连续 0~1 指标：返回 (均值, CI下界, CI上界)，正态近似并 clamp 到 [0,1]"""
    n = len(vals)
    if n == 0:
        return (0.0, 0.0, 0.0)
    mean = sum(vals) / n
    if n == 1:
        return (round(mean, 3), mean, mean)
    sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1))
    half = z * sd / math.sqrt(n)
    return (
        round(mean, 3),
        round(max(0.0, mean - half), 3),
        round(min(1.0, mean + half), 3),
    )


def pass_rate(vals: list[float], threshold: float = 0.8) -> dict:
    """阈值通过率（如 accuracy>=0.8 的比例）+ Wilson 95% CI"""
    n = len(vals)
    k = sum(1 for v in vals if v >= threshold)
    lo, hi = wilson_ci(n, k)
    return {
        "n": n,
        "pass": k,
        "rate": round(k / n, 3) if n else 0.0,
        "ci_lo": lo,
        "ci_hi": hi,
    }


def fmt_ci(mean: float, lo: float, hi: float) -> str:
    """'0.962 (95%CI 0.860~0.992)' 风格输出"""
    return f"{mean} (95%CI {lo}~{hi})"
