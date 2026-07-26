from .base import Provider, ProviderResult, Session
from .event import EventProvider
from .hoyts import HoytsProvider

REGISTRY = {
    "event": EventProvider,
    "hoyts": HoytsProvider,
}


def build(cfg) -> list:
    """Instantiate the providers named in cfg.CHAINS, in that order."""
    out = []
    for name in cfg.CHAINS:
        cls = REGISTRY.get(name)
        if cls is None:
            raise ValueError(f"unknown chain {name!r}; known: {sorted(REGISTRY)}")
        out.append(cls(cfg))
    return out


__all__ = ["Provider", "ProviderResult", "Session", "REGISTRY", "build"]
