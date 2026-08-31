"""DEFAULT DENY. A read capability is a GRANT, never the absence of a ban.

WHY THIS REPLACES A DENYLIST. `TOPSTEPX-PARALLEL-MUTATION-SURFACE-1` removed the
NinjaTrader lane's mutation authority with a proxy that refused a vocabulary of
known mutating names -- `close_position`, `place_order`, `cancel_order`,
`modify_order` and their aliases. That closed the sixth defect, and its own
report had to admit the limit in the same breath:

    KNOWN MUTATIONS DENIED      proven
    STRUCTURALLY READ-ONLY      NOT proven

Those are not the same claim. A denylist can only refuse the synonyms someone
thought of. Add `liquidate_contract`, `flatten_all`, `replace_order` or
`submit_oco` to the adapter tomorrow and a denylist waves them through, because
they are not on it.

The ruling was never "block the four mutator names we know today". It was:

    THIS LANE MAY READ A TOPSTEPX ACCOUNT. IT MAY NOT CHANGE ONE.

Only a grant can establish that. So the boundary is inverted:

    name in the certified read surface   ->  allowed
    anything else                        ->  DENIED

Unknown future names fail CLOSED automatically, which is the actual meaning of
structurally read-only. The corollary is deliberate and is the point:

    ADDING A METHOD TO `TopstepXBrokerAdapter` DOES NOT MAKE IT AVAILABLE HERE.
    A new capability requires an explicit grant, reviewed as a grant.

ONE BOUNDARY, TWO CONSUMERS. The NinjaTrader deterministic lane and the generic
broker factory both need TopstepX reads and neither is a certified execution
authority. Two implementations of one rule is the defect class this whole day
has been about, so the rule lives here and both ask it.

THE NESTED CLIMB. A capability that hands back a raw client is not a capability
at all -- the lane legitimately needs `_client.query_orders` for order
discovery, and returning the live client would put `close_position` one
attribute later. Nested capability objects are re-wrapped with their own
surface, which is itself a grant.

RETURN VALUES ARE A BOUNDARY TOO. An allowlist on the wrapper is worthless if an
ALLOWED read hands the caller an object through which authority is reacquired:

    read capability -> allowed method -> returns object -> object exposes
    mutation

`_require` is the live example. It is granted, and it returns the pinned
account/contract records -- which are ALMOST data. `TopstepXContract` carries
`points_to_ticks`, and both records carry a `from_api` classmethod reachable
from an instance. Calling those harmless today is a judgement about a NAME, and
judging names is the denylist problem one layer deeper.

So every value crossing this boundary is guarded structurally:

    primitives / dates / Decimal     pass through as themselves
    dict / list / tuple / set        guarded RECURSIVELY, contents included
    a declared nested capability     re-wrapped as its own default-deny grant
    any other object                 becomes a DATA VIEW

A DATA VIEW allows attribute reads and refuses EVERY CALLABLE, whatever it is
called. That is what makes the theorem name-independent: a synthetic
`liquidate_contract()` and an innocent `points_to_ticks()` are refused by the
same rule, and reacquiring either requires an explicit grant reviewed as a
grant.

The scenario this exists for is a change nobody predicted. If `_require()`
becomes `SessionContext(client=raw_client, ...)` in six months, the context is
wrapped, `.client` yields another data view, and every method on the live client
is denied -- without anyone having anticipated the shape.

THE WRAPPER IS A BOUNDARY TOO, AND IT WAS THE LEAK. A recursive return guard is
worthless if the wrapper hands back its own backing object:

    capability._obj._client.close_position(...)      -> MUTATED

`__getattr__` runs only when normal lookup FAILS, and `__slots__` installs real
descriptors on the class -- so `_obj` resolved through ordinary attribute
lookup and the policy never ran. Every returned object was guarded and the
front door was open.

`__getattribute__` now refuses the wrapper's own internals, so the backing
adapter is not reachable by ordinary attribute access. Internal code reads its
state through `object.__getattribute__`, which is deliberately not a public
path.

WHAT THIS DOES NOT CLAIM. This is not a defence against hostile reflection
inside one process -- `object.__getattribute__`, `gc`, `ctypes` and name
mangling all remain, and a Python object graph is not a security boundary
against code running in the same interpreter. The theorem is narrower and
mechanically real:

    NORMAL APPLICATION-LEVEL ATTRIBUTE ACCESS THROUGH A CAPABILITY CANNOT
    RECOVER THE BACKING ADAPTER OR CLIENT.

That is the boundary that stops a consumer from accidentally -- or casually --
walking an exposed object graph back to a live account.
"""
from __future__ import annotations

import datetime as _dt
import decimal as _decimal

#: Values that ARE data and cross the boundary as themselves. Dates and Decimal
#: are included because a venue payload legitimately carries them and they are
#: inert -- not because their methods were judged harmless.
DATA_TYPES = (str, bytes, bytearray, bool, int, float, complex, type(None),
              _dt.datetime, _dt.date, _dt.time, _dt.timedelta,
              _decimal.Decimal)

#: The refusal marker. Compared exactly by callers and tests.
CAPABILITY_DENIED = "TOPSTEPX_CAPABILITY_DENIED"

#: READS the adapter may expose. Every name here is a decision, and the list is
#: derived from what the audited consumers actually call -- not from what the
#: adapter happens to implement.
#:
#:   connect/is_connected   authenticate and pin; performs no order action
#:   get_account            balance, can_trade, simulated
#:   get_position           current exposure
#:   bars_1m                market history
#:   name/capability/describe   identity and self-description
#:   _require               the pinned (account, contract) pair, needed to
#:                          address a read; returns plain records
#:   _client                the transport, re-wrapped with CLIENT_READS
ADAPTER_READS = frozenset({
    "connect", "is_connected", "get_account", "get_position", "bars_1m",
    "name", "capability", "describe", "_require", "_client",
})

#: READS the raw client may expose through a capability. Deliberately minimal:
#: order discovery and the terminality oracle, which is what the deterministic
#: lane's `order_summary` needs. Nothing else is granted because nothing else
#: was shown to be needed.
CLIENT_READS = frozenset({
    "query_orders", "order_by_id", "open_orders", "open_positions",
})

#: Attributes that hand back another capability-bearing object, and the surface
#: it is granted. Anything not listed is returned as-is, which is correct for
#: plain records and values -- and is covered by a regression asserting no
#: granted read leaks an object carrying a mutating name.
NESTED = {"_client": CLIENT_READS}


class TopstepXCapabilityDenied(RuntimeError):
    """Raised when a caller reaches past its granted read surface.

    DELIBERATELY NOT a `TopstepXError`. A venue rejection means the account
    exists and said no. This means the caller holds no authority to ask, and
    no request left the process.
    """

    def __init__(self, attribute: str, label: str, detail: str = ""):
        self.attribute = attribute
        self.label = label
        super().__init__(
            f"{CAPABILITY_DENIED}: {label!r} holds a read-only TopstepX "
            f"capability; {attribute!r} is not in its certified read surface "
            f"and was refused before any venue call"
            + (f" ({detail})" if detail else ""))


#: The wrapper's OWN state, plus the reflection attributes that would hand it
#: over wholesale. Refused through ordinary attribute access on every capability
#: object, because a guard that returns its own backing object guards nothing.
WRAPPER_INTERNALS = frozenset({
    "_obj", "_surface", "_label",
    "__dict__", "__wrapped__", "__slots__", "__getattr__", "__getattribute__",
    # names other wrapper idioms use, refused pre-emptively so a future rename
    # of the backing field cannot quietly reopen this door
    "_target", "_wrapped", "_inner", "_raw", "_adapter", "_client_raw",
})


def _refuse_internals(wrapper, name: str, label: str) -> None:
    """BLANKET over the wrapper's own state, not a list of names.

    `WRAPPER_INTERNALS` alone would be a denylist one layer in: a slot added to
    a wrapper tomorrow and forgotten here would be publicly readable. So the
    wrapper's OWN `__slots__` are refused as a class, and the named set only
    adds the reflection attributes that are not slots.
    """
    if name in WRAPPER_INTERNALS:
        raise TopstepXCapabilityDenied(
            name, label, "the wrapper's own backing state is not a read")
    for klass in type(wrapper).__mro__:
        if name in getattr(klass, "__slots__", ()):
            raise TopstepXCapabilityDenied(
                name, label, "the wrapper's own backing state is not a read")


class TopstepXDataView:
    """An object crossing a read boundary carries DATA, never BEHAVIOUR.

    EVERY callable is refused, regardless of name. The rule never asks whether a
    method looks dangerous -- that question is what a denylist gets wrong, and
    asking it here would just move the denylist one object deeper.

    A caller that genuinely needs behaviour from a returned record must be
    granted it explicitly, which is a review rather than an accident.
    """

    __slots__ = ("_obj", "_label")

    def __init__(self, obj, label: str):
        object.__setattr__(self, "_obj", obj)
        object.__setattr__(self, "_label", label)

    def __getattribute__(self, name):
        # RUNS FOR EVERY ACCESS, unlike `__getattr__`. `__slots__` installs
        # descriptors that ordinary lookup finds, so without this the backing
        # record was one attribute away.
        if name.startswith("_"):
            _refuse_internals(self, name,
                              object.__getattribute__(self, "_label"))
        return object.__getattribute__(self, name)

    def __getattr__(self, name):
        label = object.__getattribute__(self, "_label")
        got = getattr(object.__getattribute__(self, "_obj"), name)
        if callable(got):
            raise TopstepXCapabilityDenied(
                name, label, "behaviour returned through a read is not granted")
        return guard(got, f"{label}.{name}")

    def __setattr__(self, name, value):
        raise TopstepXCapabilityDenied(
            name, object.__getattribute__(self, "_label"), "assignment")

    def __repr__(self) -> str:
        return (f"<data view {object.__getattribute__(self, '_label')!r} of "
                f"{type(object.__getattribute__(self, '_obj')).__name__}>")


def guard(value, label: str):
    """Make a value safe to hand across a read boundary. Recursive."""
    if isinstance(value, DATA_TYPES):
        return value
    if isinstance(value, (TopstepXDataView, TopstepXReadCapability)):
        return value
    if isinstance(value, dict):
        return {k: guard(v, f"{label}[{k!r}]") for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        # Rebuilt as a plain sequence: a subclass could carry behaviour of its
        # own, and preserving an exotic container type is not worth a hole.
        items = [guard(v, f"{label}[]") for v in value]
        return tuple(items) if isinstance(value, (tuple, set, frozenset)) \
            else items
    return TopstepXDataView(value, label)


class TopstepXReadCapability:
    """An object exposing ONLY the names it was granted.

    `__getattr__` decides on the NAME at access time against an ALLOWLIST, so a
    method that does not exist yet is already refused. That is what a denylist
    could not do.
    """

    __slots__ = ("_obj", "_surface", "_label")

    def __init__(self, obj, surface, label: str):
        object.__setattr__(self, "_obj", obj)
        object.__setattr__(self, "_surface", frozenset(surface))
        object.__setattr__(self, "_label", label)

    def __getattribute__(self, name):
        # THE FRONT DOOR. `capability._obj` used to return the live adapter,
        # because `__getattr__` only fires when normal lookup fails and a slot
        # descriptor never fails. Every returned object was guarded and the
        # wrapper itself handed the account over.
        if name.startswith("_"):
            _refuse_internals(self, name,
                              object.__getattribute__(self, "_label"))
        return object.__getattribute__(self, name)

    def __getattr__(self, name):
        surface = object.__getattribute__(self, "_surface")
        label = object.__getattribute__(self, "_label")
        if name not in surface:
            raise TopstepXCapabilityDenied(name, label)
        got = getattr(object.__getattribute__(self, "_obj"), name)
        nested = NESTED.get(name)
        if nested:
            return TopstepXReadCapability(got, nested, f"{label}.{name}")
        if callable(got):
            # A GRANTED READ MAY BE CALLED. What it RETURNS is guarded, because
            # the allowlist governs which reads exist, not what they hand back.
            def _guarded(*args, **kwargs):
                return guard(got(*args, **kwargs), f"{label}.{name}()")
            _guarded.__name__ = name
            return _guarded
        return guard(got, f"{label}.{name}")

    def __setattr__(self, name, value):
        # A capability cannot be widened from outside. Grafting a method on --
        # `cap.close_position = ...` -- would otherwise restore in one line what
        # the grant exists to withhold.
        raise TopstepXCapabilityDenied(
            name, object.__getattribute__(self, "_label"), "assignment")

    def __repr__(self) -> str:
        return (f"<read-only TopstepX capability "
                f"{object.__getattribute__(self, '_label')!r}: "
                f"{sorted(object.__getattribute__(self, '_surface'))}>")


def read_only(adapter, *, label: str, surface=ADAPTER_READS):
    """Grant `label` a read-only view of `adapter`. Mutations are unreachable."""
    return TopstepXReadCapability(adapter, surface, label)


def _facade_cap(facade):
    """The facade's own capability, reached deliberately rather than publicly.

    `object.__getattribute__` is not an application-level attribute path, which
    is exactly the distinction the boundary rests on.
    """
    return object.__getattribute__(facade, "_capability")


class ReadOnlyTopstepXBrokerAdapter:
    """What the GENERIC broker factory hands out for `broker="topstepx"`.

    THE GAP THIS CLOSES. `get_adapter(broker="topstepx")` returned a fully
    mutating `TopstepXBrokerAdapter` -- account selected from the environment,
    no certified execution authority anywhere in the path. The audit found no
    operational caller, but "nothing calls it today" is exactly the reasoning
    that left an ungated `close_position` alive in the deterministic lane, and
    the boundary we settled is the brokerage ACCOUNT, not the entrypoint.

    So the generic factory grants READS. It is a real adapter -- it connects,
    reports the account and position, serves bars -- and it has no order
    authority at all. Order authority belongs to the certified production
    organism, which never resolves through this factory.

    Configuration cannot restore it. `TOPSTEPX_ALLOW_LIVE`, `TOPSTEPX_ARM_ORDERS`,
    `TOPSTEPX_ACCOUNT_NAME` and `TOPSTEPX_ACCOUNT_ROLE` select WHICH account is
    read; none of them is an execution authority.
    """

    LABEL = "generic_broker_factory"

    def __init__(self, config=None):
        from broker.topstepx_adapter import TopstepXBrokerAdapter
        self._config = config
        self.account_id = getattr(config, "account_id", None)
        self._capability = read_only(TopstepXBrokerAdapter(config),
                                     label=self.LABEL)

    # ── identity ────────────────────────────────────────────────────────────
    @property
    def name(self) -> str:
        return "topstepx"

    def capability(self):
        return _facade_cap(self).capability()

    def describe(self) -> dict:
        return {"name": self.name, "account_id": self.account_id,
                "order_authority": False,
                "read_surface": sorted(ADAPTER_READS),
                "note": ("generic factory grants TopstepX READS only; order "
                         "authority belongs to the certified production "
                         "organism")}

    # ── reads ───────────────────────────────────────────────────────────────
    def connect(self):
        return _facade_cap(self).connect()

    def is_connected(self) -> bool:
        try:
            return bool(_facade_cap(self).is_connected())
        except Exception:  # noqa: BLE001 -- unconnected is not an error here
            return False

    def get_account(self) -> dict:
        return _facade_cap(self).get_account()

    def get_position(self, symbol: str = "") -> dict:
        return _facade_cap(self).get_position(symbol)

    def bars_1m(self, **kw) -> list:
        return _facade_cap(self).bars_1m(**kw)

    # ── everything else ─────────────────────────────────────────────────────
    # ARITY-TOLERANT, deliberately. These two exist only because the
    # `BrokerAdapter` interface names them; a caller must be refused whatever
    # shape the call takes, and a `TypeError` about arguments would tell them
    # the wrong thing about why nothing happened.
    def submit_order(self, *args, **kwargs):
        raise TopstepXCapabilityDenied("submit_order", self.LABEL)

    def flatten(self, *args, **kwargs):
        raise TopstepXCapabilityDenied("flatten", self.LABEL)

    def __getattribute__(self, name):
        """The facade's own state is not a read either.

        `_capability` is itself a default-deny grant, so exposing it is far less
        severe than exposing a raw adapter -- but a consumer walking the object
        graph should meet the boundary HERE rather than one hop later.
        """
        if name in ("_capability", "_config"):
            raise TopstepXCapabilityDenied(
                name, "generic_broker_factory",
                "the facade's own backing state is not a read")
        return object.__getattribute__(self, name)

    def __getattr__(self, name):
        """DEFAULT DENY, including names that do not exist yet.

        A method added to `TopstepXBrokerAdapter` tomorrow is not reachable
        through this facade unless it is granted here, deliberately.
        """
        raise TopstepXCapabilityDenied(name, self.LABEL)
