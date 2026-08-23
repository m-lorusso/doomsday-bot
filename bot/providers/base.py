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
    members_only: bool = False  # loyalty-scheme presale; you need an account

    @property
    def is_imax(self) -> bool:
        """IMAX sells out first, so these float to the top of the alert."""
        return "imax" in f"{self.cinema} {self.screen or ''}".lower()


@dataclass
class ProviderResult:
    chain: str
    sessions: list = field(default_factory=list)
    status: str | None = None  # plain-English one-liner for the heartbeat
    venues: int = 0
    venue_order: list = field(default_factory=list)  # best venues first; drives alert ordering
    movie_url: str | None = None  # the chain's page for the film, for tapping through
    checked: int = 0  # venues that answered this run
    failed_venues: list = field(default_factory=list)
    last_error: str | None = None  # most recent failure, even a survivable one
    error: str | None = None  # set only when the chain gave us nothing at all


class Provider:
    """Interface. `check(deep)` should never raise - catch and set `.error`.

    `deep=True` means "you're allowed to make the expensive request this run".
    Providers that have a cheap signal and an expensive confirmation use it to
    avoid pulling megabytes every few minutes.
    """

    name = "unnamed"

    def check(self, deep: bool = False) -> ProviderResult:  # pragma: no cover
        raise NotImplementedError
