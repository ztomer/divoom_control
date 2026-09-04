"""Marks this directory a REGULAR package, which is load-bearing.

`textstat` (0.7.13) installs a top-level `tests` package into site-packages.
A regular package beats a namespace package no matter what `sys.path` order
says -- `pythonpath = .` in pytest.ini does not help -- so every
`from tests.support import ...` resolved `tests` to textstat's and aborted
collection with ModuleNotFoundError. 52 modules, 0 of them running.
An empty `__init__.py` makes this directory regular too, and the repo root
comes first.
"""
