"""Single source of truth for the ScenePlay app version.

Served by GET /api/server-info so other ScenePlay boxes (and the network
scanner in discovery.py) can identify this device and its version. Keep this
in step with the version in pyproject.toml.
"""

__version__ = "0.1.0"
