"""The static integration catalog.

An integration is one thing PockPock can connect to: a local model server, an
agent, a cloud provider, a data source, or a tool service. The catalog only
describes integrations; live state (connected or not, enabled or not) comes
from :mod:`projects.integrations.service`.

Two kinds of integration exist:

- ``internal`` — something that runs on this PC or is managed on another
  PockPock page (Ollama, OpenClaw, cloud models, ...). No account or
  credential is stored for these.
- ``external`` — a third-party service (GitHub, Gmail, Slack, ...) connected
  from the Integrations page. Each one declares how it authenticates
  (``oauth`` or ``api_token``), the scopes it asks for, and the steps to
  connect it. Connection state for these lives in the gateway settings
  store; see :mod:`projects.integrations.service`.
"""

from __future__ import annotations

from dataclasses import dataclass


CATEGORIES = ("Models", "Agents", "Tools", "Data")

# Display groups for external connectors on the Integrations page. The
# Finance group currently has no connector assigned; it is part of the
# layout vocabulary for a future finance connector.
GROUPS = ("Productivity", "Developer", "Communication", "Social", "Finance")

KIND_INTERNAL = "internal"
KIND_EXTERNAL = "external"

AUTH_LOCAL = "local"
AUTH_OAUTH = "oauth"
AUTH_API_TOKEN = "api_token"


@dataclass(frozen=True)
class Integration:
    """Static description of one integration."""

    id: str
    name: str
    category: str
    description: str
    capabilities: tuple[str, ...]
    setup_hint: str
    manage_hint: str
    kind: str = KIND_INTERNAL
    auth: str = AUTH_LOCAL
    scopes: tuple[str, ...] = ()
    connect_steps: tuple[str, ...] = ()
    featured: bool = False
    group: str = ""
    icon: str = ""
    """Short icon key the UI renders a letter/brand tile from.

    Defaults to the entry id (``github``, ``gmail``, ...); no trademarked
    logo files are used. Internal entries are ungrouped (``group == ""``)
    and never featured.
    """

    def __post_init__(self) -> None:
        if not self.icon:
            object.__setattr__(self, "icon", self.id)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "setup_hint": self.setup_hint,
            "manage_hint": self.manage_hint,
            "kind": self.kind,
            "auth": self.auth,
            "scopes": list(self.scopes),
            "connect_steps": list(self.connect_steps),
            "featured": self.featured,
            "group": self.group,
            "icon": self.icon,
        }


CATALOG: tuple[Integration, ...] = (
    Integration(
        id="ollama",
        name="Local models",
        category="Models",
        description="Run open models on this PC with Ollama.",
        capabilities=("Run local chat models", "List installed models", "Start Ollama on demand"),
        setup_hint="Install Ollama, then use Connect to start it.",
        manage_hint="Services page",
    ),
    Integration(
        id="openclaw",
        name="OpenClaw agent",
        category="Agents",
        description="The OpenClaw agent running on this PC.",
        capabilities=("Run agent turns", "Approve tool actions", "Use installed skills and MCP servers"),
        setup_hint="Install Node.js 24 or newer and the OpenClaw helper, then enable the integration.",
        manage_hint="Services page",
    ),
    Integration(
        id="nemoclaw",
        name="NemoClaw sandbox",
        category="Agents",
        description="A sandboxed agent running in WSL.",
        capabilities=("Run sandboxed agent turns", "Use a local or cloud model"),
        setup_hint="Run Setup in PockPock Agent to create the sandbox.",
        manage_hint="Services page",
    ),
    Integration(
        id="cloud",
        name="Cloud models",
        category="Models",
        description="Cloud models from NVIDIA NIM, OpenRouter, and Alibaba Model Studio.",
        capabilities=("Use cloud chat models", "Tool-capable completions"),
        setup_hint="Add a provider and API key on the Cloud page.",
        manage_hint="Cloud page",
    ),
    Integration(
        id="research",
        name="Public research",
        category="Data",
        description="Fetch named public web pages for research tasks.",
        capabilities=("Fetch a named public page", "Scrape public content for a task"),
        setup_hint="Connect to enable the named-host fetcher.",
        manage_hint="Research settings",
    ),
    Integration(
        id="browser",
        name="Browser automation",
        category="Tools",
        description="Playwright browser automation service.",
        capabilities=("Run browser recipes", "Capture screenshots and page text"),
        setup_hint="Start the browser-automation service.",
        manage_hint="Services page",
    ),
    Integration(
        id="skills",
        name="OpenClaw skills",
        category="Tools",
        description="Skills installed for the OpenClaw agent.",
        capabilities=("Extend the agent with skills", "Enable or disable each skill"),
        setup_hint="Install skills from the Skills page.",
        manage_hint="Skills page",
    ),
    Integration(
        id="mcp",
        name="MCP servers",
        category="Tools",
        description="Model Context Protocol servers providing tools and data.",
        capabilities=("Expose tools from MCP servers", "Enable or disable each server"),
        setup_hint="Add a server from the MCP servers page.",
        manage_hint="MCP servers page",
    ),
    # ----- external connectors -----
    Integration(
        id="github",
        name="GitHub",
        category="Tools",
        description="Read and write GitHub repositories, issues, and pull requests.",
        capabilities=("Read repositories, issues, and pull requests", "Write issues and pull requests"),
        setup_hint="Create a fine-grained personal access token, then paste it in the connect form.",
        manage_hint="Integrations page",
        kind=KIND_EXTERNAL,
        auth=AUTH_API_TOKEN,
        scopes=("Read repositories, issues, and pull requests", "Write issues and pull requests"),
        connect_steps=(
            "Create a fine-grained personal access token in GitHub Settings with repository and issues access.",
            "Paste the token in the connect form. The token stays on this PC only.",
        ),
        featured=True,
        group="Developer",
    ),
    Integration(
        id="gmail",
        name="Gmail",
        category="Data",
        description="Read and send mail and manage labels in Gmail.",
        capabilities=("Read mail", "Send mail", "Manage labels"),
        setup_hint="Sign in with Google and grant PockPock mail access.",
        manage_hint="Integrations page",
        kind=KIND_EXTERNAL,
        auth=AUTH_OAUTH,
        scopes=("Read mail", "Send mail", "Manage labels"),
        connect_steps=(
            "Sign in with your Google account in the connect form.",
            "Grant PockPock permission to read and send mail and manage labels.",
        ),
        featured=True,
        group="Communication",
    ),
    Integration(
        id="outlook_mail",
        name="Outlook Mail",
        category="Data",
        description="Read and send mail in Outlook.",
        capabilities=("Read mail", "Send mail"),
        setup_hint="Sign in with Microsoft and grant PockPock mail access.",
        manage_hint="Integrations page",
        kind=KIND_EXTERNAL,
        auth=AUTH_OAUTH,
        scopes=("Read mail", "Send mail"),
        connect_steps=(
            "Sign in with your Microsoft account in the connect form.",
            "Grant PockPock permission to read and send mail.",
        ),
        group="Communication",
    ),
    Integration(
        id="outlook_calendar",
        name="Outlook Calendar",
        category="Data",
        description="Read and create events in Outlook Calendar.",
        capabilities=("Read events", "Create events"),
        setup_hint="Sign in with Microsoft and grant PockPock calendar access.",
        manage_hint="Integrations page",
        kind=KIND_EXTERNAL,
        auth=AUTH_OAUTH,
        scopes=("Read events", "Create events"),
        connect_steps=(
            "Sign in with your Microsoft account in the connect form.",
            "Grant PockPock permission to read and create calendar events.",
        ),
        group="Productivity",
    ),
    Integration(
        id="google_calendar",
        name="Google Calendar",
        category="Data",
        description="Read and create events in Google Calendar.",
        capabilities=("Read events", "Create events"),
        setup_hint="Sign in with Google and grant PockPock calendar access.",
        manage_hint="Integrations page",
        kind=KIND_EXTERNAL,
        auth=AUTH_OAUTH,
        scopes=("Read events", "Create events"),
        connect_steps=(
            "Sign in with your Google account in the connect form.",
            "Grant PockPock permission to read and create calendar events.",
        ),
        featured=True,
        group="Productivity",
    ),
    Integration(
        id="slack",
        name="Slack",
        category="Tools",
        description="Read and post messages in Slack.",
        capabilities=("Read messages", "Post messages"),
        setup_hint="Sign in to your Slack workspace and grant PockPock access.",
        manage_hint="Integrations page",
        kind=KIND_EXTERNAL,
        auth=AUTH_OAUTH,
        scopes=("Read messages", "Post messages"),
        connect_steps=(
            "Sign in to your Slack workspace in the connect form.",
            "Grant PockPock permission to read and post messages.",
        ),
        group="Communication",
    ),
    Integration(
        id="notion",
        name="Notion",
        category="Data",
        description="Read and write pages in Notion.",
        capabilities=("Read pages", "Write pages"),
        setup_hint="Create a Notion integration token, then paste it in the connect form.",
        manage_hint="Integrations page",
        kind=KIND_EXTERNAL,
        auth=AUTH_API_TOKEN,
        scopes=("Read pages", "Write pages"),
        connect_steps=(
            "Create an internal integration in Notion and copy its token.",
            "Paste the token in the connect form. The token stays on this PC only.",
        ),
        group="Productivity",
    ),
    Integration(
        id="google_drive",
        name="Google Drive",
        category="Data",
        description="Read and write files in Google Drive.",
        capabilities=("Read files", "Write files"),
        setup_hint="Sign in with Google and grant PockPock Drive access.",
        manage_hint="Integrations page",
        kind=KIND_EXTERNAL,
        auth=AUTH_OAUTH,
        scopes=("Read files", "Write files"),
        connect_steps=(
            "Sign in with your Google account in the connect form.",
            "Grant PockPock permission to read and write files in Drive.",
        ),
        group="Productivity",
    ),
    Integration(
        id="google_docs",
        name="Google Docs",
        category="Data",
        description="Read and write documents in Google Docs.",
        capabilities=("Read documents", "Write documents"),
        setup_hint="Sign in with Google and grant PockPock Docs access.",
        manage_hint="Integrations page",
        kind=KIND_EXTERNAL,
        auth=AUTH_OAUTH,
        scopes=("Read documents", "Write documents"),
        connect_steps=(
            "Sign in with your Google account in the connect form.",
            "Grant PockPock permission to read and write documents.",
        ),
        group="Productivity",
    ),
    Integration(
        id="google_sheets",
        name="Google Sheets",
        category="Data",
        description="Read and write spreadsheets in Google Sheets.",
        capabilities=("Read spreadsheets", "Write spreadsheets"),
        setup_hint="Sign in with Google and grant PockPock Sheets access.",
        manage_hint="Integrations page",
        kind=KIND_EXTERNAL,
        auth=AUTH_OAUTH,
        scopes=("Read spreadsheets", "Write spreadsheets"),
        connect_steps=(
            "Sign in with your Google account in the connect form.",
            "Grant PockPock permission to read and write spreadsheets.",
        ),
        group="Productivity",
    ),
    Integration(
        id="instagram",
        name="Instagram",
        category="Data",
        description="Read posts and publish media on Instagram.",
        capabilities=("Read profile and posts", "Publish posts"),
        setup_hint="Sign in with Instagram and grant PockPock access.",
        manage_hint="Integrations page",
        kind=KIND_EXTERNAL,
        auth=AUTH_OAUTH,
        scopes=("Read profile and posts", "Publish posts"),
        connect_steps=(
            "Sign in with your Instagram account in the connect form.",
            "Grant PockPock permission to read your profile and posts and publish on your behalf.",
        ),
        group="Social",
    ),
    Integration(
        id="facebook",
        name="Facebook",
        category="Data",
        description="Read posts and publish on Facebook.",
        capabilities=("Read profile and posts", "Publish posts"),
        setup_hint="Sign in with Facebook and grant PockPock access.",
        manage_hint="Integrations page",
        kind=KIND_EXTERNAL,
        auth=AUTH_OAUTH,
        scopes=("Read profile and posts", "Publish posts"),
        connect_steps=(
            "Sign in with your Facebook account in the connect form.",
            "Grant PockPock permission to read your profile and posts and publish on your behalf.",
        ),
        group="Social",
    ),
    Integration(
        id="threads",
        name="Threads",
        category="Data",
        description="Read posts and publish on Threads.",
        capabilities=("Read profile and posts", "Publish posts"),
        setup_hint="Sign in with Threads and grant PockPock access.",
        manage_hint="Integrations page",
        kind=KIND_EXTERNAL,
        auth=AUTH_OAUTH,
        scopes=("Read profile and posts", "Publish posts"),
        connect_steps=(
            "Sign in with your Threads account in the connect form.",
            "Grant PockPock permission to read your profile and posts and publish on your behalf.",
        ),
        group="Social",
    ),
    Integration(
        id="spotify",
        name="Spotify",
        category="Tools",
        description="Read your library and playlists and control playback on Spotify.",
        capabilities=("Read library and playlists", "Control playback"),
        setup_hint="Sign in with Spotify and grant PockPock access.",
        manage_hint="Integrations page",
        kind=KIND_EXTERNAL,
        auth=AUTH_OAUTH,
        scopes=("Read library and playlists", "Control playback"),
        connect_steps=(
            "Sign in with your Spotify account in the connect form.",
            "Grant PockPock permission to read your library and playlists and control playback.",
        ),
        group="Social",
    ),
    Integration(
        id="messenger",
        name="Messenger",
        category="Tools",
        description="Read and send messages in Facebook Messenger.",
        capabilities=("Read messages", "Send messages"),
        setup_hint="Sign in with Facebook and grant PockPock Messenger access.",
        manage_hint="Integrations page",
        kind=KIND_EXTERNAL,
        auth=AUTH_OAUTH,
        scopes=("Read messages", "Send messages"),
        connect_steps=(
            "Sign in with your Facebook account in the connect form.",
            "Grant PockPock permission to read and send Messenger messages.",
        ),
        group="Communication",
    ),
)

_BY_ID = {item.id: item for item in CATALOG}


def get_integration(integration_id: str) -> Integration | None:
    """The catalog entry for ``integration_id``, or ``None`` when unknown."""
    return _BY_ID.get(integration_id)
