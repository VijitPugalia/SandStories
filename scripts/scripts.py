"""Compatibility shim for directly executed scripts in this directory.

When ``complete_depth_any2full.py`` is executed by file path, Python places this
directory (rather than the repository root) on ``sys.path``. Expose the sibling
session reader under the same name used by package/module execution.
"""

import importlib


visualize_sandstories_session = importlib.import_module("visualize_sandstories_session")
