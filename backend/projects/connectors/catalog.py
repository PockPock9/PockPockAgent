"""The connector catalog: external apps the agent can connect to and use as tools.

Only apps outside PockPock belong here (GitHub, email, Telegram, ...). Things that run on this
computer or have their own page (Ollama, OpenClaw, NemoClaw, cloud models, skills, MCP servers) are
not connectors. Every connector is connected with a credential the user creates in that app, which
PockPock checks with the app before saving, and every connector gives the agent a fixed set of tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

GROUPS = ("Developer", "Communication", "Productivity")


@dataclass(frozen=True)
class Field:
    """One input of a connector's connect form."""

    key: str
    label: str
    secret: bool = False
    placeholder: str = ""
    help: str = ""
    options: tuple[tuple[str, str], ...] = ()  # (value, label): a choice instead of free text
    required: bool = True
    only_when: tuple[str, str] | None = None  # (other field, value): shown only for that choice
    max_length: int = 400

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "label": self.label, "secret": self.secret, "placeholder": self.placeholder, "help": self.help,
            "options": [{"value": value, "label": label} for value, label in self.options],
            "required": self.required, "only_when": list(self.only_when) if self.only_when else None,
        }


@dataclass(frozen=True)
class Tool:
    """One action the agent can take with a connected app. ``write`` tools change something outside PockPock."""

    name: str
    title: str
    description: str
    write: bool = False
    properties: dict[str, dict[str, Any]] = field(default_factory=dict)
    required: tuple[str, ...] = ()

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": self.properties, "required": list(self.required), "additionalProperties": False}


@dataclass(frozen=True)
class Connector:
    id: str
    name: str
    group: str
    about: str
    fields: tuple[Field, ...]
    steps: tuple[str, ...]
    key_url: str
    tools: tuple[Tool, ...]
    featured: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "group": self.group, "about": self.about, "featured": self.featured,
            "fields": [item.to_dict() for item in self.fields], "steps": list(self.steps), "key_url": self.key_url,
            "tools": [{"name": tool.name, "title": tool.title, "write": tool.write} for tool in self.tools],
        }


def _text(description: str, max_length: int = 2000) -> dict[str, Any]:
    return {"type": "string", "description": description, "maxLength": max_length}


def _count(description: str, default: int = 10, maximum: int = 30) -> dict[str, Any]:
    return {"type": "integer", "description": f"{description} (default {default}, at most {maximum})", "minimum": 1, "maximum": maximum}


REPO = _text("Repository as owner/name", 140)

# Mail servers for the email connector. Outlook.com and Microsoft 365 are not listed: Microsoft
# accepts only OAuth sign-in for IMAP, which needs an app registration PockPock does not have.
EMAIL_SERVERS: dict[str, tuple[str, str]] = {
    "gmail": ("imap.gmail.com", "smtp.gmail.com"),
    "icloud": ("imap.mail.me.com", "smtp.mail.me.com"),
    "yahoo": ("imap.mail.yahoo.com", "smtp.mail.yahoo.com"),
    "fastmail": ("imap.fastmail.com", "smtp.fastmail.com"),
}

CATALOG: tuple[Connector, ...] = (
    Connector(
        id="github", name="GitHub", group="Developer", featured=True,
        about="Read repositories, issues and pull requests, and open or comment on issues.",
        fields=(Field("token", "Personal access token", secret=True, placeholder="github_pat_… or ghp_…", help="A fine-grained token limited to the repositories you choose is safest."),),
        steps=(
            "On GitHub open Settings → Developer settings → Personal access tokens → Fine-grained tokens.",
            "Generate a token for the repositories the agent may use. Give it read access to Contents, Issues and Pull requests, and write access to Issues if it may open or comment on issues.",
            "Copy the token and paste it here.",
        ),
        key_url="https://github.com/settings/personal-access-tokens",
        tools=(
            Tool("github_list_repos", "List your repositories", "List repositories the connected GitHub account can use, most recently updated first.", properties={"limit": _count("How many repositories")}),
            Tool("github_search_issues", "Search issues and pull requests", "Search GitHub issues and pull requests with GitHub's search syntax, for example `repo:owner/name is:open label:bug`.", properties={"query": _text("Search query", 400), "limit": _count("How many results")}, required=("query",)),
            Tool("github_get_issue", "Read an issue or pull request", "Read one issue or pull request with its latest comments.", properties={"repo": REPO, "number": {"type": "integer", "minimum": 1, "description": "Issue or pull request number"}}, required=("repo", "number")),
            Tool("github_list_pull_requests", "List pull requests", "List pull requests of a repository.", properties={"repo": REPO, "state": {"type": "string", "enum": ["open", "closed", "all"], "description": "Which pull requests (default open)"}, "limit": _count("How many pull requests")}, required=("repo",)),
            Tool("github_get_file", "Read a file", "Read a text file from a repository.", properties={"repo": REPO, "path": _text("File path in the repository", 400), "ref": _text("Branch, tag or commit (default: the default branch)", 200)}, required=("repo", "path")),
            Tool("github_create_issue", "Open an issue", "Open a new issue in a repository.", write=True, properties={"repo": REPO, "title": _text("Issue title", 256), "body": _text("Issue text in Markdown", 20000)}, required=("repo", "title")),
            Tool("github_comment", "Comment on an issue or pull request", "Add a comment to an issue or pull request.", write=True, properties={"repo": REPO, "number": {"type": "integer", "minimum": 1, "description": "Issue or pull request number"}, "body": _text("Comment text in Markdown", 20000)}, required=("repo", "number", "body")),
        ),
    ),
    Connector(
        id="email", name="Email", group="Communication", featured=True,
        about="Read and search your inbox and send email, through your mail provider's IMAP and SMTP servers.",
        fields=(
            Field("provider", "Mail provider", options=(("gmail", "Gmail"), ("icloud", "iCloud Mail"), ("yahoo", "Yahoo Mail"), ("fastmail", "Fastmail"), ("custom", "Another provider (IMAP)"))),
            Field("address", "Email address", placeholder="you@example.com", max_length=254),
            Field("password", "App password", secret=True, help="An app password made for PockPock, not your normal sign-in password."),
            Field("imap_host", "IMAP server", placeholder="imap.example.com", only_when=("provider", "custom"), max_length=253),
            Field("smtp_host", "SMTP server", placeholder="smtp.example.com", only_when=("provider", "custom"), max_length=253),
        ),
        steps=(
            "Turn on two-step verification for your mail account if it is not on yet.",
            "Create an app password for PockPock (Gmail: Google Account → Security → App passwords; iCloud: appleid.apple.com → Sign-In and Security → App-Specific Passwords).",
            "Enter your email address and that app password here.",
            "Outlook.com and Microsoft 365 mailboxes cannot be connected this way, because Microsoft no longer accepts app passwords for mail.",
        ),
        key_url="https://myaccount.google.com/apppasswords",
        tools=(
            Tool("email_list_recent", "List recent email", "List the newest messages in the inbox with sender, subject and date.", properties={"limit": _count("How many messages"), "unread_only": {"type": "boolean", "description": "Only unread messages"}}),
            Tool("email_search", "Search email", "Search the inbox for messages containing some text.", properties={"text": _text("Text to look for in the message", 200), "limit": _count("How many messages")}, required=("text",)),
            Tool("email_read", "Read an email", "Read one message by the id that a list or search returned.", properties={"id": _text("Message id from email_list_recent or email_search", 20)}, required=("id",)),
            Tool("email_send", "Send an email", "Send a plain-text email from the connected address.", write=True, properties={"to": _text("Recipient addresses, separated by commas", 1000), "subject": _text("Subject", 300), "body": _text("Message text", 50000)}, required=("to", "subject", "body")),
        ),
    ),
    Connector(
        id="telegram", name="Telegram", group="Communication", featured=True,
        about="Send messages from your own Telegram bot and read the messages people send it.",
        fields=(Field("token", "Bot token", secret=True, placeholder="123456789:AA…", help="The token BotFather gives you for your bot."),),
        steps=(
            "In Telegram, open a chat with @BotFather and send /newbot (or /mybots for a bot you already have).",
            "Copy the bot token BotFather shows and paste it here.",
            "Send your bot a message, or add it to a group. A bot can only write to chats that have messaged it first.",
        ),
        key_url="https://t.me/BotFather",
        tools=(
            Tool("telegram_get_messages", "Read new messages", "Read the latest messages sent to the bot. Each one has the chat id needed to reply.", properties={"limit": _count("How many messages")}),
            Tool("telegram_send_message", "Send a message", "Send a text message from the bot to a chat.", write=True, properties={"chat_id": _text("Chat id from telegram_get_messages, or @channelname", 64), "text": _text("Message text", 4096)}, required=("chat_id", "text")),
        ),
    ),
    Connector(
        id="slack", name="Slack", group="Communication",
        about="Read channels and post messages as your Slack app's bot.",
        fields=(Field("token", "Bot token", secret=True, placeholder="xoxb-…", help="The Bot User OAuth Token of a Slack app installed in your workspace."),),
        steps=(
            "At api.slack.com/apps create an app for your workspace.",
            "Under OAuth & Permissions add the bot scopes channels:read, channels:history and chat:write, then install the app to the workspace.",
            "Copy the Bot User OAuth Token and paste it here. Invite the bot to the channels it should read or post in.",
        ),
        key_url="https://api.slack.com/apps",
        tools=(
            Tool("slack_list_channels", "List channels", "List the public channels of the workspace.", properties={"limit": _count("How many channels", 30, 100)}),
            Tool("slack_read_channel", "Read a channel", "Read the latest messages of a channel the bot is in.", properties={"channel": _text("Channel id, for example C0123456789", 40), "limit": _count("How many messages")}, required=("channel",)),
            Tool("slack_post_message", "Post a message", "Post a message to a channel the bot is in.", write=True, properties={"channel": _text("Channel id or #name", 80), "text": _text("Message text", 8000)}, required=("channel", "text")),
        ),
    ),
    Connector(
        id="discord", name="Discord", group="Communication",
        about="Read and send messages in your servers as your Discord bot.",
        fields=(Field("token", "Bot token", secret=True, help="The token on your application's Bot page."),),
        steps=(
            "At discord.com/developers/applications create an application and add a bot to it.",
            "On the Bot page turn on Message Content Intent, then reset and copy the token.",
            "Invite the bot to your server with the permissions View Channels, Read Message History and Send Messages, and paste the token here.",
        ),
        key_url="https://discord.com/developers/applications",
        tools=(
            Tool("discord_list_channels", "List servers and channels", "List the servers the bot is in and their text channels."),
            Tool("discord_read_channel", "Read a channel", "Read the latest messages of a channel.", properties={"channel_id": _text("Channel id", 30), "limit": _count("How many messages")}, required=("channel_id",)),
            Tool("discord_send_message", "Send a message", "Send a message to a channel.", write=True, properties={"channel_id": _text("Channel id", 30), "text": _text("Message text", 2000)}, required=("channel_id", "text")),
        ),
    ),
    Connector(
        id="notion", name="Notion", group="Productivity",
        about="Search and read the Notion pages you share with PockPock, and add new pages.",
        fields=(Field("token", "Integration secret", secret=True, placeholder="ntn_… or secret_…", help="The Internal Integration Secret of an integration you create."),),
        steps=(
            "At notion.so/profile/integrations create an internal integration for your workspace.",
            "Copy its Internal Integration Secret and paste it here.",
            "In Notion, open each page the agent may use, choose ⋯ → Connections, and add your integration.",
        ),
        key_url="https://www.notion.so/profile/integrations",
        tools=(
            Tool("notion_search", "Search pages", "Search the pages and databases shared with the integration by title.", properties={"query": _text("Words in the title (empty lists everything shared)", 200), "limit": _count("How many results")}),
            Tool("notion_read_page", "Read a page", "Read the text of a page.", properties={"page_id": _text("Page id from notion_search", 64)}, required=("page_id",)),
            Tool("notion_create_page", "Add a page", "Create a new page under a page shared with the integration.", write=True, properties={"parent_page_id": _text("Id of the page to add it under", 64), "title": _text("Page title", 300), "text": _text("Page text; blank lines separate paragraphs", 20000)}, required=("parent_page_id", "title")),
        ),
    ),
)

BY_ID = {connector.id: connector for connector in CATALOG}
TOOLS = {tool.name: (connector, tool) for connector in CATALOG for tool in connector.tools}
