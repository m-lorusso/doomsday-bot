from .base import Provider, ProviderResult, Session
from .event import EventProvider
from .hoyts import HoytsProvider
from .palace import PalaceProvider
from .ritz import RitzProvider

REGISTRY = {
    "event": EventProvider,
    "hoyts": HoytsProvider,
    "ritz": RitzProvider,
    "palace": PalaceProvider,
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
