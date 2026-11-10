"""Independent preflop game and Monte Carlo CFR research engine."""

from .core import ResearchSolver, default_config, icm_equities
from .cards import HAND_LABELS, hand_labels

__all__ = ["ResearchSolver", "default_config", "icm_equities", "HAND_LABELS", "hand_labels"]
