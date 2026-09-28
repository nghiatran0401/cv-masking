"""Detection adapters. Consume the format-neutral text model only."""

from cv_masking.adapters.detection.detector import PatternDetector, PresidioDetector

__all__ = ["PatternDetector", "PresidioDetector"]
