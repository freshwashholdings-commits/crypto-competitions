"""Tron Address Tracer & Analyzer.

Deterministic FIFO/LIFO fund tracing, controller attribution, and
address clustering for the Tron blockchain. See METHODOLOGY.md for the
full design rationale.
"""

__version__ = "0.1.0"

# Methodology/scoring version recorded on every trace and attribution
# output. Bump on any change to tracing policy or scoring weights.
METHODOLOGY_VERSION = "1.0.0"
