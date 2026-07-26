"""Shared vocabulary for every cinema chain we watch.

Each provider turns whatever its chain's backend gives us into a list of
`Session` objects. Providers that can only tell us "yes, it's bookable" without
listing times (single-venue sites, page-level signals) return one Session with
`start=None` — that still fires an alert, it just carries less detail.
"""

from dataclasses import dataclass, field


@dataclass
class Session:
    chain: str
    cinema: str
    key: str  # stable + unique, so we only alert once per session
    start: str | None = None  # ISO local time
    screen: str | None = None
    seats: int | None = None
    booking_url: str | None = None
    note: str | None = None  # used when there's no per-session detail


@dataclass
class ProviderResult:
    chain: str
    sessions: list = field(default_factory=list)
    status: str | None = None  # one-line "here's how far ahead they're selling"
    error: str | None = None


class Provider:
    """Interface. `check(deep)` should never raise - catch and set `.error`.

    `deep=True` means "you're allowed to make the expensive request this run".
    Providers that have a cheap signal and an expensive confirmation use it to
    avoid pulling megabytes every few minutes.
    """

    name = "unnamed"

    def check(self, deep: bool = False) -> ProviderResult:  # pragma: no cover
        raise NotImplementedError
