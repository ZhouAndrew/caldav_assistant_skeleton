"""Stable v1 public exception hierarchy."""
class CalDAVAssistantError(Exception): pass
class NotFoundError(CalDAVAssistantError): pass
class AmbiguousError(CalDAVAssistantError): pass
class ValidationError(CalDAVAssistantError): pass
class ConflictError(CalDAVAssistantError): pass
class UnavailableError(CalDAVAssistantError): pass
class PermissionError(CalDAVAssistantError): pass
class ExtensionError(CalDAVAssistantError): pass
