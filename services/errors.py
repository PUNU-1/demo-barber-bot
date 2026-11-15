"""Exceptions shared across services."""


class ServiceUnavailable(Exception):
    """An external dependency (Sheets, Calendar, local storage) could not be used right now."""


class KnowledgeUnavailable(ServiceUnavailable):
    """The FAQ data could not be loaded and there is no cached copy to fall back on."""


class ScheduleUnavailable(ServiceUnavailable):
    """The booking storage (bookings.json or Google Calendar) failed."""


class KnowledgeError(ValueError):
    """The FAQ data is present but invalid (bad hours, missing service fields, ...)."""
