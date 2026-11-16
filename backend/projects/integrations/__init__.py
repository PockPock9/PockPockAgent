"""Integration management package: catalog, live status, and routes."""

from .catalog import CATALOG, Integration, get_integration
from .service import IntegrationError, IntegrationService

__all__ = ["CATALOG", "Integration", "IntegrationError", "IntegrationService", "get_integration"]
