"""
Waste detection algorithms.

Each detector identifies a specific waste pattern:
- retry_bloat: Same operation repeated multiple times
- loop_detection: Infinite loops or repeated patterns
- dead_end: Work that cost money but produced no value
- context_waste: Re-ingesting same context multiple times
- cascade: Failures that trigger downstream waste
"""

from .retry_bloat import detect_retry_bloat

__all__ = ['detect_retry_bloat']
