"""Ingestion: pull real source data and build a dated, versioned snapshot in the same
shape riskcore consumes. Each source is a module; build_snapshot.py orchestrates them.

Design: downloads are cached under data/cache/ with a manifest; the built snapshot is
written to data/snapshots/snapshot-<date>.json. Nothing here runs at request time; the
live engine only reads a finished snapshot.
"""
