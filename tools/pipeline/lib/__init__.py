"""Shared building blocks for the territory generation pipeline.

Nothing in here does GIS work. These modules exist so that every stage measures
distance the same way, writes files the same way, and derives identifiers the
same way. Stage bodies (Phase B) should reach for these rather than reinventing
them, because determinism is a whole-pipeline property: one stage sorting its
output differently is enough to break it.
"""
