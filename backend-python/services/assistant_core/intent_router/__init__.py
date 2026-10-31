"""Intent-router compatibility API.

The old IntentRouter v2 pipeline has been retired from the public name and now
lives in ``legacy_pipeline`` / ``legacy_routing``.  Public imports from this
package route through the Skill-first Agent Kernel projection.
"""

from .pipeline import (
    _EmbeddingClientFacade,
    _ensure_index_built,
    _on_task_registry_reload,
    route,
)
from .routing import route as route_dispatch

__all__ = [
    'route',
    'route_dispatch',
    '_ensure_index_built',
    '_on_task_registry_reload',
    '_EmbeddingClientFacade',
]
