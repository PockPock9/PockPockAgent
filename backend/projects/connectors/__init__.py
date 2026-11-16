"""External app connectors (GitHub, email, Telegram, ...) and their agent tools."""

from .catalog import BY_ID, CATALOG, TOOLS
from .clients import ConnectorError
from .service import ConnectorService

__all__ = ["BY_ID", "CATALOG", "TOOLS", "ConnectorError", "ConnectorService"]
