"""Compatibility wrapper for the root streaks module."""
from streaks import SECONDS_PER_DAY, STREAK_GRACE_SECONDS, StreakService

__all__ = ["StreakService", "SECONDS_PER_DAY", "STREAK_GRACE_SECONDS"]
