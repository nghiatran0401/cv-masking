"""Domain exceptions.

Messages name fields, rules, commands, and states only. They never include the
offending value, so no document-derived data can leak through an exception.
"""


class DomainError(Exception):
    """Base class for all domain rule violations."""


class InvariantError(DomainError):
    """A value or object breaks a structural rule."""


class PolicyError(DomainError):
    """A masking-policy rule is broken (e.g. a mandatory entity is disabled)."""


class InvalidTransitionError(DomainError):
    """A state-changing command is not allowed in the current state."""

    def __init__(self, command: str, state: str, detail: str | None = None) -> None:
        message = f"{command} is not allowed from state {state}"
        if detail is not None:
            message = f"{message}: {detail}"
        super().__init__(message)
        self.command = command
        self.state = state
