"""Reusable Commitizen-based release tooling.

The ``ImpactsCz`` plugin is registered via the ``commitizen.plugin`` entry
point and should be imported from ``release_toolkit.cz_plugin``. We deliberately
do NOT re-export it here to avoid a circular import: importing ``commitizen``
triggers entry-point discovery, which would re-enter this package mid-import.
"""
