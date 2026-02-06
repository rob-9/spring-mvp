"""
waste detection algorithms.

each detector identifies a specific waste pattern:
- retry_bloat: same operation repeated multiple times
- loop_detection: infinite loops or repeated patterns
- dead_end: work that cost money but produced no value
- context_waste: re-ingesting same context multiple times
- cascade: failures that trigger downstream waste
"""

from .retry_bloat import detect_retry_bloat
from .dead_end import detect_dead_end
from .loop_detection import detect_loops
from .context_waste import detect_context_waste, detect_duplicate_prompts
from .cascade import (
    detect_cascade_failures,
    detect_error_clusters,
    analyze_retry_cascade
)

__all__ = [
    'detect_retry_bloat',
    'detect_dead_end',
    'detect_loops',
    'detect_context_waste',
    'detect_duplicate_prompts',
    'detect_cascade_failures',
    'detect_error_clusters',
    'analyze_retry_cascade',
]
