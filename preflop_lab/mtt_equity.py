"""Independent numerical MTT ICM, including HRC's large-field approximation.

Inputs are surviving local stacks, the full remaining field's prizes, and fixed
outside stacks. Returns local absolute prize equities; settlement and bounties
belong to the caller. No HRC installation or saved utilities are used here.

The compatibility model deliberately keeps the 100-outside-player threshold,
the unbounded Edgeworth correction, and the finite QNG quadrature. Therefore
this is not an exact ICM oracle or a guaranteed prize-conserving approximation.
See research/HRC-MTT-EQUITY.md for measured numerical limitations.
"""
from __future__ import annotations

import math
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Callable

_EPS = sys.float_info.epsilon
_PHI_SCALE = 0.3989422804014327

# Gauss/Kronrod/Patterson quadrature abscissae and weights (QUADPACK QNG).
_X1 = (0.9739065285171717, 0.8650633666889845, 0.6794095682990244, 0.4333953941292472, 0.14887433898163122)
_W10 = (0.06667134430868814, 0.1494513491505806, 0.21908636251598204, 0.26926671930999635, 0.29552422471475287)
_X2 = (0.9956571630258081, 0.9301574913557082, 0.7808177265864169, 0.5627571346686047, 0.2943928627014602)
_W21A = (0.032558162307964725, 0.07503967481091996, 0.10938715880229764, 0.13470921731147334, 0.14773910490133849)
_W21B = (0.011694638867371874, 0.054755896574351995, 0.0931254545836976, 0.12349197626206584, 0.14277593857706009, 0.1494455540029169)
_X3 = (0.999333360901932, 0.9874334029080889, 0.9548079348142663, 0.9001486957483283, 0.8251983149831141, 0.732148388989305, 0.6228479705377252, 0.4994795740710565, 0.36490166134658075, 0.2222549197766013, 0.07465061746138332)
_W43A = (0.016296734289666565, 0.0375228761208695, 0.05469490205825544, 0.06735541460947808, 0.07387019963239395, 0.005768556059769796, 0.027371890593248842, 0.04656082691042883, 0.06174499520144257, 0.07138726726869339)
_W43B = (0.001844477640212414, 0.010798689585891651, 0.021895363867795427, 0.032597463975345686, 0.04216313793519181, 0.050741939600184575, 0.05837939554261925, 0.06474640495144589, 0.06956619791235648, 0.07282444147183322, 0.07450775101417512, 0.07472214751740301)
_X4 = (0.9999029772627293, 0.9979898959866788, 0.9921754978606873, 0.9813581635727128, 0.9650576238583847, 0.9431676131336706, 0.9158064146855072, 0.8832216577713164, 0.8457107484624157, 0.8035576580352309, 0.7570057306854956, 0.7062732097873218, 0.6515894665011779, 0.5932233740579611, 0.531493605970832, 0.46676362304202285, 0.3994248478592188, 0.3298748771061883, 0.25850355920216156, 0.18569539656834666, 0.11184221317990747, 0.03735212339461987)
_W87A = (0.008148377384149173, 0.018761438201562824, 0.027347451050052287, 0.03367770731163793, 0.036935099820427905, 0.0028848724302115306, 0.013685946022712702, 0.02328041350288831, 0.03087249761171336, 0.03569363363941877, 0.0009152833452022414, 0.005399280219300471, 0.01094767960111893, 0.016298731696787336, 0.021081568889203834, 0.025370969769253827, 0.029189697756475754, 0.03237320246720279, 0.034783098950365146, 0.03641222073135179, 0.037253875503047706)
_W87B = (0.00027414556376207234, 0.0018071241550579428, 0.0040968692827591646, 0.006758290051847379, 0.009549957672201646, 0.012329447652244854, 0.015010447346388952, 0.01754896798624319, 0.019938037786440887, 0.022194935961012286, 0.024339147126000805, 0.026374505414839208, 0.0282869107887712, 0.030052581128092695, 0.03164675137143993, 0.033050413419978504, 0.034255099704226064, 0.03526241266015668, 0.0360769896228887, 0.03669860449845609, 0.037120549269832576, 0.03733422875193504, 0.037361073762679026)


def _rescale_error(delta: float, absolute: float, deviation: float) -> float:
    error = abs(delta)
    if deviation and error:
        factor = (200.0 * error / deviation) ** 1.5
        error = deviation * min(1.0, factor)
    return max(error, 50.0 * _EPS * absolute)


def _qng(function: Callable[[float], float], left: float, right: float) -> float:
    """Nested 21/43/87-point quadrature with the audited stopping convention."""
    if left == right:
        return 0.0
    half = (right - left) * 0.5
    center = (right + left) * 0.5
    middle = function(center)
    samples: list[tuple[float, float]] = []
    pairs: list[float] = []
    low = 0.0
    estimate = _W21B[5] * middle
    absolute = _W21B[5] * abs(middle)
    for group, weights in ((_X1, _W21A), (_X2, _W21B)):
        for i, point in enumerate(group):
            upper, lower = function(center + half * point), function(center - half * point)
            pair = upper + lower
            if len(pairs) < 5:
                low += _W10[i] * pair
            estimate += weights[i] * pair
            absolute += weights[i] * (abs(upper) + abs(lower))
            samples.append((upper, lower))
            pairs.append(pair)
    absolute *= half
    mean = estimate * 0.5
    deviation = _W21B[5] * abs(middle - mean)
    for i in range(5):
        deviation += (_W21A[i] * sum(abs(x - mean) for x in samples[i])
                      + _W21B[i] * sum(abs(x - mean) for x in samples[i + 5]))
    # Compatibility detail: the first stopping check uses unscaled deviation.
    error = _rescale_error((estimate - low) * half, absolute, deviation)
    deviation *= half
    for points, reused, fresh in ((_X3, _W43A, _W43B), (_X4, _W87A, _W87B)):
        result = estimate * half
        if error < 1e-10 or error < 1e-10 * abs(result):
            return result
        previous = estimate
        estimate = fresh[-1] * middle
        for i, weight in enumerate(reused):
            estimate += weight * pairs[i]
        for point, weight in zip(points, fresh):
            pair = function(center + half * point) + function(center - half * point)
            estimate += weight * pair
            pairs.append(pair)
        error = _rescale_error((estimate - previous) * half, absolute, deviation)
    return estimate * half


def _normal_cdf(z: float) -> float:
    probability = 0.5 * (1.0 + math.erf(z * 0.7071067811865476))
    if probability > 1e-8:
        return probability
    # Audited CDF uses a truncated asymptotic tail below this boundary.
    square = z * z
    if not math.isfinite(square):
        return 0.0
    series, product, previous, order = 1.0, 1.0, math.inf, 1
    while True:
        odd = (4.0 * order - 3.0) / square
        multiplier = odd * ((4.0 * order - 1.0) / square)
        correction = product * (odd - multiplier)
        series -= correction
        product *= multiplier
        magnitude = abs(correction)
        if not (previous > magnitude and magnitude >= abs(series * _EPS)):
            break
        previous = magnitude
        order += 1
    density = 0.0 if -0.5 * z * z <= -690.0 else _PHI_SCALE * math.exp(-0.5 * z * z)
    return -density / z * series


def _rank_integrand(prizes: tuple[float, ...], stacks: tuple[float, ...], hero: int, t: float) -> float:
    """Exponential-race ICM: integrate conditional Poisson-binomial rank law."""
    distribution = [0.0] * len(stacks)
    distribution[-1] = 1.0
    log_t = math.log(t) if t else -math.inf
    processed = 0
    for player, stack in enumerate(stacks):
        if player == hero:
            continue
        behind = math.exp(log_t * stack / stacks[hero])
        for rank in range(len(stacks) - 2 - processed, len(stacks) - 1):
            transfer = distribution[rank + 1] * behind
            distribution[rank] += transfer
            distribution[rank + 1] -= transfer
        processed += 1
    return sum(prize * chance for prize, chance in zip(prizes, distribution))


def _edgeworth_integrand(prizes: tuple[float, ...], stacks: tuple[float, ...], hero: int, t: float) -> float:
    log_t = math.log(t) if t else -math.inf
    mean = variance = third = 0.0
    for player, stack in enumerate(stacks):
        if player != hero:
            q = math.exp(log_t * stack / stacks[hero])
            v = q * (1.0 - q)
            mean += q
            variance += v
            third += v * (1.0 - 2.0 * q)
    if variance <= 0.0:
        return _rank_integrand(prizes, stacks, hero, t)
    sigma = math.sqrt(variance)
    try:
        skewness = third * sigma ** -3.0
    except OverflowError:
        skewness = math.copysign(math.inf, third) if third else math.nan

    def cumulative(behind: int) -> float:
        z = (behind + 0.5 - mean) / sigma
        density = 0.0 if -0.5 * z * z <= -690.0 else _PHI_SCALE * math.exp(-0.5 * z * z)
        return _normal_cdf(z) + skewness * (1.0 - z * z) * density / 6.0

    previous = cumulative(len(stacks) - 1)
    value = 0.0
    for rank, prize in enumerate(prizes):
        if rank == len(prizes) - 1 or prize != prizes[rank + 1]:
            current = cumulative(len(stacks) - rank - 2)
            value += prize * (previous - current)
            previous = current
    return _rank_integrand(prizes, stacks, hero, t) if math.isnan(value) else value


def _numbers(values: Iterable[float], name: str, positive: bool) -> tuple[float, ...]:
    try:
        raw = tuple(values)
        if any(isinstance(x, (bool, str, bytes)) for x in raw):
            raise ValueError
        result = tuple(float(x) for x in raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a numeric sequence") from exc
    if any(not math.isfinite(x) or (x <= 0 if positive else x < 0) for x in result):
        raise ValueError(f"{name} must contain finite {'positive' if positive else 'nonnegative'} values")
    return result


@dataclass(frozen=True, init=False)
class Calculator:
    """Immutable configuration; each call uses fresh numerical scratch space."""
    payouts: tuple[float, ...]
    other_stacks: tuple[float, ...]

    def __init__(self, payouts: Iterable[float], other_stacks: Iterable[float] = ()):
        prizes = _numbers(payouts, "payouts", False)
        if not prizes or any(a < b for a, b in zip(prizes, prizes[1:])):
            raise ValueError("payouts must be nonempty and descending")
        object.__setattr__(self, "payouts", prizes)
        object.__setattr__(self, "other_stacks", _numbers(other_stacks, "other_stacks", True))

    @property
    def approximate(self) -> bool:
        return len(self.other_stacks) >= 100

    def equities(self, table_stacks: Iterable[float]) -> list[float]:
        local = _numbers(table_stacks, "table_stacks", True)
        if not local:
            raise ValueError("at least one surviving table player is required")
        field = local + self.other_stacks
        try:
            total = math.fsum(field)
        except OverflowError as exc:
            raise ValueError("field chip total overflows float64") from exc
        if not math.isfinite(total) or (len(field) > 1 and total <= max(field)):
            raise ValueError("field chip ratios exceed stable float64 domain")
        tail = tuple(0.0 if i < 2 else prize for i, prize in enumerate(self.payouts))
        output = []
        for hero, stack in enumerate(local):
            value = 0.0
            if any(tail):
                approx = lambda t: _edgeworth_integrand(tail, field, hero, t)
                integrand = approx if self.approximate else lambda t: _rank_integrand(tail, field, hero, t)
                left = 0.0
                for _ in range(20):
                    if approx((1.0 - left) * 0.75) != 0.0 or value != 0.0:
                        break
                    right = left + (1.0 - left) * 0.75
                    value += _qng(integrand, left, right)
                    left = right
                value += _qng(integrand, left, 1.0)
            value += stack / total * self.payouts[0]
            if len(self.payouts) > 1:
                second = 0.0
                for player, opponent in enumerate(field):
                    if player != hero:
                        second += opponent / total * stack / (total - opponent)
                value += self.payouts[1] * second
            if not math.isfinite(value):
                raise ArithmeticError("MTT approximation produced nonfinite equity")
            output.append(value)
        return output

    __call__ = equities


def mtt_icm_equities(table_stacks: Iterable[float], payouts: Iterable[float], other_stacks: Iterable[float] = ()) -> list[float]:
    return Calculator(payouts, other_stacks).equities(table_stacks)


equities = mtt_icm_equities
