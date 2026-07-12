"""Sanitized organization failures safe for user-facing presentation."""


class OrganizationError(RuntimeError):
    """Base class whose message must never contain raw story/provider output."""


class ProviderUnavailableError(OrganizationError):
    pass


class ConsentRequiredError(OrganizationError):
    pass


class ProviderRefusalError(OrganizationError):
    pass


class ProviderRateLimitError(OrganizationError):
    pass


class ProviderTimeoutError(OrganizationError):
    pass


class OrganizationCancelledError(OrganizationError):
    pass


class PolicyViolationError(OrganizationError):
    pass


class InvalidProviderOutputError(OrganizationError):
    pass
