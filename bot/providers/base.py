"""Shared vocabulary for every cinema chain we watch.

Each provider turns whatever its chain's backend gives us into `Session`
objects, and answers two questions:

  check()       - everything at every watched Sydney venue. Heavier; this is
                  the full sweep.
  check_imax()  - only the IMAX screen. Cheap enough to run every minute,
                  because IMAX is what sells out first.
"""

from dataclasses import dataclass, field


@dataclass
class Session:
    chain: str
    cinema: str
    key: str  # stable + unique, so we only alert once per session
    start: str | None = None  # ISO, cinema-local (i.e. Sydney) time
    screen: str | None = None
    seats: int | None = None
    booking_url: str | None = None
    note: str | None = None  # used when there's no per-session detail
    members_only: bool = False  # loyalty-scheme presale; you need an account
    # Set by the provider from the session's own screen type. Never inferred
    # from the venue name: HOYTS Blacktown has an IMAX screen, but most of its
    # sessions are on ordinary screens, and treating them all as IMAX is how a
    # Standard session once got a star in the alert.
    imax: bool = False

    @property
    def is_imax(self) -> bool:
        return self.imax


@dataclass
class ProviderResult:
    chain: str
    sessions: list = field(default_factory=list)
    status: str | None = None  # plain-English one-liner for the status report
    venues: int = 0
    venue_order: list = field(default_factory=list)  # best venues first; drives alert ordering
    movie_url: str | None = None  # the chain's page for the film, for tapping through
    checked: int = 0  # venues that answered this run
    missed: list = field(default_factory=list)  # venues/dates that didn't answer
    last_error: str | None = None  # most recent failure, even a survivable one
    error: str | None = None  # set only when the chain gave us nothing at all

    # The IMAX screen, reported separately because it's the one that matters.
    imax_label: str | None = None  # "IMAX Sydney", "Blacktown IMAX"
    imax_status: str | None = None
    imax_url: str | None = None  # where to book that screen specifically
    imax_error: str | None = None

    @property
    def imax_sessions(self) -> list:
        return [s for s in self.sessions if s.imax]


class Provider:
    """Interface. Neither method should raise - catch and set `.error` /
    `.imax_error` instead, so one bad chain can't sink the others."""

    name = "unnamed"

    def check(self) -> ProviderResult:  # pragma: no cover
        raise NotImplementedError

    def check_imax(self) -> ProviderResult:  # pragma: no cover
        raise NotImplementedError
