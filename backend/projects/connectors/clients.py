"""Talks to the connected apps: one credential check and the tool calls for each connector.

Every web address here is a constant; nothing the model or the user types becomes a host name
(the email connector's custom mail servers are the one exception, and they are the user's own
setting). Credentials are used for the request and never returned, logged or put in an error.
"""

from __future__ import annotations

import asyncio
import base64
import email
import email.policy
import imaplib
import re
import smtplib
import socket
import ssl
from email.message import EmailMessage
from email.utils import getaddresses
from typing import Any, Awaitable, Callable, Mapping

import aiohttp

from .catalog import EMAIL_SERVERS

HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30, sock_connect=10)
MAIL_TIMEOUT_SECONDS = 25
MAX_TEXT = 6000
REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9._-]{1,100}$")
HOST = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$")
ADDRESS = re.compile(r"^[^@\s<>,;]{1,64}@[^@\s<>,;]{1,255}$")

# (method, url, headers, params, json) -> (status, parsed JSON or text)
Http = Callable[..., Awaitable[tuple[int, Any]]]


class ConnectorError(Exception):
    """A connector call failed in a way the user or the agent can act on. Never contains a credential."""

    def __init__(self, message: str, *, status_code: int = 502, code: str = "failed"):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


async def http_request(method: str, url: str, *, headers: Mapping[str, str] | None = None, params: Mapping[str, Any] | None = None, json: Any = None) -> tuple[int, Any]:
    try:
        async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT) as session:
            async with session.request(method, url, headers=dict(headers or {}), params=dict(params or {}), json=json, allow_redirects=False) as response:
                try:
                    return response.status, await response.json(content_type=None)
                except ValueError:
                    return response.status, (await response.text())[:500]
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        raise ConnectorError(f"The service could not be reached ({type(err).__name__}). Check the internet connection.", code="unreachable") from err


def clip(value: Any, limit: int = MAX_TEXT) -> str:
    text = str(value or "")
    return text if len(text) <= limit else f"{text[:limit]}… [cut, {len(text) - limit} more characters]"


def _limit(args: Mapping[str, Any], default: int = 10, maximum: int = 30) -> int:
    try:
        return max(1, min(maximum, int(args.get("limit") or default)))
    except (TypeError, ValueError):
        return default


def _need(args: Mapping[str, Any], key: str, pattern: re.Pattern[str] | None = None) -> str:
    value = str(args.get(key) or "").strip()
    if not value or (pattern and not pattern.fullmatch(value)):
        raise ConnectorError(f"`{key}` is missing or not valid.", status_code=400, code="bad_input")
    return value


def _fail(name: str, status: int, data: Any) -> ConnectorError:
    detail = ""
    if isinstance(data, dict):
        detail = str(data.get("message") or data.get("description") or data.get("error") or "")
    elif isinstance(data, str):
        detail = data
    reason = {401: "the saved credential was refused; reconnect it on the Connectors page", 403: "the credential is not allowed to do this", 404: "that item was not found, or the credential cannot see it", 429: "the service is limiting requests; try again in a minute"}.get(status)
    return ConnectorError(f"{name} answered with an error (HTTP {status}): {reason or clip(detail, 200) or 'no details'}.", status_code=409 if status in (401, 403) else 502, code="refused" if status in (401, 403) else "failed")


# --------------------------------------------------------------------------- GitHub

GITHUB = "https://api.github.com"


def _github_headers(creds: Mapping[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {creds['token']}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "PockPock-Agent"}


async def github_verify(creds: Mapping[str, str], http: Http) -> str:
    status, data = await http("GET", f"{GITHUB}/user", headers=_github_headers(creds))
    if status != 200 or not isinstance(data, dict) or not data.get("login"):
        raise _fail("GitHub", status, data)
    return str(data["login"])


async def _github(creds: Mapping[str, str], http: Http, method: str, path: str, **kwargs: Any) -> Any:
    status, data = await http(method, f"{GITHUB}{path}", headers=_github_headers(creds), **kwargs)
    if status >= 400:
        raise _fail("GitHub", status, data)
    return data


def _issue(item: Mapping[str, Any]) -> dict[str, Any]:
    return {"number": item.get("number"), "title": item.get("title"), "state": item.get("state"), "is_pull_request": "pull_request" in item or "head" in item, "author": (item.get("user") or {}).get("login"), "url": item.get("html_url"), "updated_at": item.get("updated_at")}


async def github_list_repos(creds, args, http):
    data = await _github(creds, http, "GET", "/user/repos", params={"sort": "updated", "per_page": _limit(args)})
    return {"repositories": [{"name": repo.get("full_name"), "private": repo.get("private"), "description": repo.get("description"), "default_branch": repo.get("default_branch"), "updated_at": repo.get("updated_at")} for repo in data]}


async def github_search_issues(creds, args, http):
    data = await _github(creds, http, "GET", "/search/issues", params={"q": _need(args, "query"), "per_page": _limit(args)})
    return {"total": data.get("total_count"), "results": [{**_issue(item), "repo": str(item.get("repository_url", "")).split("/repos/")[-1]} for item in data.get("items", [])]}


async def github_get_issue(creds, args, http):
    repo, number = _need(args, "repo", REPO), int(_need(args, "number"))
    item = await _github(creds, http, "GET", f"/repos/{repo}/issues/{number}")
    comments = await _github(creds, http, "GET", f"/repos/{repo}/issues/{number}/comments", params={"per_page": 10, "page": max(1, -(-int(item.get("comments") or 0) // 10))})
    return {**_issue(item), "body": clip(item.get("body")), "labels": [label.get("name") for label in item.get("labels", [])], "comments": [{"author": (comment.get("user") or {}).get("login"), "created_at": comment.get("created_at"), "body": clip(comment.get("body"), 2000)} for comment in comments]}


async def github_list_pull_requests(creds, args, http):
    state = str(args.get("state") or "open")
    data = await _github(creds, http, "GET", f"/repos/{_need(args, 'repo', REPO)}/pulls", params={"state": state if state in ("open", "closed", "all") else "open", "per_page": _limit(args)})
    return {"pull_requests": [{**_issue(item), "draft": item.get("draft"), "branch": (item.get("head") or {}).get("ref")} for item in data]}


async def github_get_file(creds, args, http):
    path = _need(args, "path").lstrip("/")
    if ".." in path.split("/"):
        raise ConnectorError("`path` is not valid.", status_code=400, code="bad_input")
    params = {"ref": str(args["ref"])} if args.get("ref") else {}
    data = await _github(creds, http, "GET", f"/repos/{_need(args, 'repo', REPO)}/contents/{path}", params=params)
    if not isinstance(data, dict) or data.get("type") != "file":
        return {"path": path, "entries": [{"name": entry.get("name"), "type": entry.get("type")} for entry in data][:200] if isinstance(data, list) else []}
    try:
        text = base64.b64decode(data.get("content") or "").decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        raise ConnectorError("That file is not text, so it cannot be read here.", status_code=400, code="bad_input") from None
    return {"path": data.get("path"), "size": data.get("size"), "url": data.get("html_url"), "text": clip(text, 20000)}


async def github_create_issue(creds, args, http):
    item = await _github(creds, http, "POST", f"/repos/{_need(args, 'repo', REPO)}/issues", json={"title": _need(args, "title")[:256], "body": str(args.get("body") or "")[:20000]})
    return {"created": True, **_issue(item)}


async def github_comment(creds, args, http):
    comment = await _github(creds, http, "POST", f"/repos/{_need(args, 'repo', REPO)}/issues/{int(_need(args, 'number'))}/comments", json={"body": _need(args, "body")[:20000]})
    return {"created": True, "url": comment.get("html_url")}


# --------------------------------------------------------------------------- Telegram

async def _telegram(creds: Mapping[str, str], http: Http, method: str, payload: Mapping[str, Any] | None = None) -> Any:
    status, data = await http("POST", f"https://api.telegram.org/bot{creds['token']}/{method}", json=dict(payload or {}))
    if status != 200 or not isinstance(data, dict) or not data.get("ok"):
        raise _fail("Telegram", status, data)
    return data.get("result")


async def telegram_verify(creds, http):
    if not re.fullmatch(r"\d{5,15}:[A-Za-z0-9_-]{30,60}", creds.get("token", "")):
        raise ConnectorError("That does not look like a bot token. Copy the whole token from BotFather, for example 123456789:AA….", status_code=409, code="refused")
    bot = await _telegram(creds, http, "getMe")
    return f"@{bot.get('username')}"


async def telegram_get_messages(creds, args, http):
    updates = await _telegram(creds, http, "getUpdates", {"limit": 100, "timeout": 0, "allowed_updates": ["message", "channel_post"]})
    messages = []
    for update in updates[-_limit(args):]:
        message = update.get("message") or update.get("channel_post") or {}
        chat, sender = message.get("chat") or {}, message.get("from") or {}
        messages.append({"chat_id": chat.get("id"), "chat": chat.get("title") or chat.get("username") or chat.get("first_name"), "from": sender.get("username") or sender.get("first_name"), "date": message.get("date"), "text": clip(message.get("text") or message.get("caption") or "[not a text message]", 2000)})
    return {"messages": messages, "note": "" if messages else "No recent messages. A bot only sees messages sent to it or in groups it was added to."}


async def telegram_send_message(creds, args, http):
    chat = _need(args, "chat_id")
    sent = await _telegram(creds, http, "sendMessage", {"chat_id": int(chat) if re.fullmatch(r"-?\d+", chat) else chat, "text": _need(args, "text")[:4096]})
    return {"sent": True, "message_id": sent.get("message_id"), "chat_id": (sent.get("chat") or {}).get("id")}


# --------------------------------------------------------------------------- Slack

async def _slack(creds: Mapping[str, str], http: Http, method: str, *, params: Mapping[str, Any] | None = None, json: Any = None) -> dict[str, Any]:
    status, data = await http("POST" if json is not None else "GET", f"https://slack.com/api/{method}", headers={"Authorization": f"Bearer {creds['token']}"}, params=params, json=json)
    if status != 200 or not isinstance(data, dict):
        raise _fail("Slack", status, data)
    if not data.get("ok"):
        error = str(data.get("error") or "unknown_error")
        refused = error in {"invalid_auth", "not_authed", "account_inactive", "token_revoked", "token_expired"}
        hint = {"missing_scope": f"the Slack app needs the scope {data.get('needed', '')}", "not_in_channel": "invite the bot to that channel first", "channel_not_found": "that channel was not found"}.get(error, error.replace("_", " "))
        raise ConnectorError(f"Slack refused the request: {'the bot token is not valid' if refused else hint}.", status_code=409 if refused else 502, code="refused" if refused else "failed")
    return data


async def slack_verify(creds, http):
    data = await _slack(creds, http, "auth.test")
    return f"{data.get('user')} in {data.get('team')}"


async def slack_list_channels(creds, args, http):
    data = await _slack(creds, http, "conversations.list", params={"limit": _limit(args, 30, 100), "exclude_archived": "true", "types": "public_channel"})
    return {"channels": [{"id": channel.get("id"), "name": channel.get("name"), "bot_is_member": channel.get("is_member"), "topic": (channel.get("topic") or {}).get("value")} for channel in data.get("channels", [])]}


async def slack_read_channel(creds, args, http):
    data = await _slack(creds, http, "conversations.history", params={"channel": _need(args, "channel"), "limit": _limit(args)})
    return {"messages": [{"user": message.get("user") or message.get("username"), "time": message.get("ts"), "text": clip(message.get("text"), 2000)} for message in data.get("messages", [])]}


async def slack_post_message(creds, args, http):
    data = await _slack(creds, http, "chat.postMessage", json={"channel": _need(args, "channel"), "text": _need(args, "text")[:8000]})
    return {"sent": True, "channel": data.get("channel"), "time": data.get("ts")}


# --------------------------------------------------------------------------- Discord

DISCORD = "https://discord.com/api/v10"
SNOWFLAKE = re.compile(r"^\d{15,22}$")


async def _discord(creds: Mapping[str, str], http: Http, method: str, path: str, **kwargs: Any) -> Any:
    status, data = await http(method, f"{DISCORD}{path}", headers={"Authorization": f"Bot {creds['token']}", "User-Agent": "DiscordBot (https://github.com/PockPock9/PockPockAgent, 1.0)"}, **kwargs)
    if status >= 400:
        raise _fail("Discord", status, data)
    return data


async def discord_verify(creds, http):
    bot = await _discord(creds, http, "GET", "/users/@me")
    return str(bot.get("username"))


async def discord_list_channels(creds, args, http):
    servers = []
    for guild in (await _discord(creds, http, "GET", "/users/@me/guilds"))[:10]:
        channels = await _discord(creds, http, "GET", f"/guilds/{guild['id']}/channels")
        servers.append({"server": guild.get("name"), "channels": [{"id": channel.get("id"), "name": channel.get("name")} for channel in channels if channel.get("type") in (0, 5)][:100]})
    return {"servers": servers, "note": "" if servers else "The bot is not in any server yet. Invite it first."}


async def discord_read_channel(creds, args, http):
    data = await _discord(creds, http, "GET", f"/channels/{_need(args, 'channel_id', SNOWFLAKE)}/messages", params={"limit": _limit(args)})
    return {"messages": [{"author": (message.get("author") or {}).get("username"), "time": message.get("timestamp"), "text": clip(message.get("content"), 2000)} for message in data]}


async def discord_send_message(creds, args, http):
    sent = await _discord(creds, http, "POST", f"/channels/{_need(args, 'channel_id', SNOWFLAKE)}/messages", json={"content": _need(args, "text")[:2000], "allowed_mentions": {"parse": []}})
    return {"sent": True, "message_id": sent.get("id")}


# --------------------------------------------------------------------------- Notion

NOTION = "https://api.notion.com/v1"
NOTION_ID = re.compile(r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$")


async def _notion(creds: Mapping[str, str], http: Http, method: str, path: str, **kwargs: Any) -> Any:
    status, data = await http(method, f"{NOTION}{path}", headers={"Authorization": f"Bearer {creds['token']}", "Notion-Version": "2022-06-28"}, **kwargs)
    if status >= 400:
        raise _fail("Notion", status, data)
    return data


def _plain(rich: Any) -> str:
    return "".join(str(part.get("plain_text") or "") for part in rich) if isinstance(rich, list) else ""


def _notion_title(item: Mapping[str, Any]) -> str:
    if item.get("object") == "database":
        return _plain(item.get("title"))
    for value in (item.get("properties") or {}).values():
        if isinstance(value, dict) and value.get("type") == "title":
            return _plain(value.get("title"))
    return ""


async def notion_verify(creds, http):
    data = await _notion(creds, http, "GET", "/users/me")
    workspace = ((data.get("bot") or {}).get("workspace_name")) or ""
    return f"{data.get('name') or 'integration'}{f' in {workspace}' if workspace else ''}"


async def notion_search(creds, args, http):
    data = await _notion(creds, http, "POST", "/search", json={"query": str(args.get("query") or "")[:200], "page_size": _limit(args)})
    results = [{"id": item.get("id"), "type": item.get("object"), "title": _notion_title(item) or "(untitled)", "url": item.get("url"), "edited": item.get("last_edited_time")} for item in data.get("results", [])]
    return {"results": results, "note": "" if results else "Nothing is shared with the integration yet. In Notion, open a page, choose ⋯ → Connections and add it."}


async def notion_read_page(creds, args, http):
    page_id = _need(args, "page_id", NOTION_ID)
    page = await _notion(creds, http, "GET", f"/pages/{page_id}")
    blocks = await _notion(creds, http, "GET", f"/blocks/{page_id}/children", params={"page_size": 100})
    lines = []
    for block in blocks.get("results", []):
        kind = block.get("type")
        text = _plain((block.get(kind) or {}).get("rich_text")) if isinstance(block.get(kind), dict) else ""
        if kind == "child_page":
            text = f"[sub-page: {(block.get(kind) or {}).get('title')}]"
        if text:
            lines.append(f"{'# ' if str(kind).startswith('heading') else '- ' if 'list_item' in str(kind) or kind == 'to_do' else ''}{text}")
    return {"title": _notion_title(page), "url": page.get("url"), "text": clip("\n".join(lines), 20000), "more": bool(blocks.get("has_more"))}


async def notion_create_page(creds, args, http):
    paragraphs = [part.strip() for part in str(args.get("text") or "").split("\n\n") if part.strip()][:90]
    children = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": part[:1900]}}]}} for part in paragraphs]
    page = await _notion(creds, http, "POST", "/pages", json={"parent": {"page_id": _need(args, "parent_page_id", NOTION_ID)}, "properties": {"title": {"title": [{"type": "text", "text": {"content": _need(args, "title")[:300]}}]}}, "children": children})
    return {"created": True, "id": page.get("id"), "url": page.get("url")}


# --------------------------------------------------------------------------- Email (IMAP and SMTP)

def email_servers(creds: Mapping[str, str]) -> tuple[str, str]:
    provider = creds.get("provider", "")
    if provider in EMAIL_SERVERS:
        return EMAIL_SERVERS[provider]
    imap_host, smtp_host = creds.get("imap_host", "").strip().lower(), creds.get("smtp_host", "").strip().lower()
    if provider != "custom" or not HOST.fullmatch(imap_host) or not HOST.fullmatch(smtp_host):
        raise ConnectorError("Enter the IMAP and SMTP server names of your mail provider, for example imap.example.com.", status_code=400, code="bad_input")
    return imap_host, smtp_host


def _mail_error(err: Exception) -> ConnectorError:
    if isinstance(err, (imaplib.IMAP4.error, smtplib.SMTPAuthenticationError)):
        return ConnectorError("The mail server refused the sign-in. Use an app password made for PockPock (not your normal password), and check the address.", status_code=409, code="refused")
    if isinstance(err, (socket.gaierror, TimeoutError, ConnectionError, ssl.SSLError, OSError)):
        return ConnectorError(f"The mail server could not be reached ({type(err).__name__}). Check the server name and the internet connection.", code="unreachable")
    return ConnectorError(f"The mail server reported an error ({type(err).__name__}).")


def _imap(creds: Mapping[str, str]) -> imaplib.IMAP4_SSL:
    host, _ = email_servers(creds)
    client = imaplib.IMAP4_SSL(host, 993, ssl_context=ssl.create_default_context(), timeout=MAIL_TIMEOUT_SECONDS)
    client.login(creds["address"], creds["password"])
    return client


def _summary(uid: bytes, raw: bytes) -> dict[str, Any]:
    message = email.message_from_bytes(raw, policy=email.policy.default)
    return {"id": uid.decode(), "from": clip(message.get("From"), 200), "subject": clip(message.get("Subject"), 300), "date": str(message.get("Date") or "")}


def _email_list_sync(creds: Mapping[str, str], criteria: list[str], limit: int) -> dict[str, Any]:
    client = _imap(creds)
    try:
        client.select("INBOX", readonly=True)
        _, found = client.uid("SEARCH", None, *criteria)
        uids = (found[0] or b"").split()[-limit:][::-1]
        messages = []
        for uid in uids:
            _, data = client.uid("FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if data and isinstance(data[0], tuple):
                messages.append(_summary(uid, data[0][1]))
        return {"messages": messages}
    finally:
        try:
            client.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


def _email_read_sync(creds: Mapping[str, str], uid: str) -> dict[str, Any]:
    client = _imap(creds)
    try:
        client.select("INBOX", readonly=True)
        _, data = client.uid("FETCH", uid, "(BODY.PEEK[])")
        if not data or not isinstance(data[0], tuple):
            raise ConnectorError("That message was not found in the inbox.", status_code=404, code="not_found")
        message = email.message_from_bytes(data[0][1], policy=email.policy.default)
        body = message.get_body(preferencelist=("plain", "html"))
        text = body.get_content() if body is not None else ""
        if body is not None and body.get_content_type() == "text/html":
            text = re.sub(r"\s+\n", "\n", re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", " ", text)))
        attachments = [part.get_filename() for part in message.iter_attachments() if part.get_filename()]
        return {"id": uid, "from": clip(message.get("From"), 200), "to": clip(message.get("To"), 400), "subject": clip(message.get("Subject"), 300), "date": str(message.get("Date") or ""), "text": clip(text.strip(), 20000), "attachments": attachments[:20]}
    finally:
        try:
            client.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


def _email_send_sync(creds: Mapping[str, str], to: list[str], subject: str, body: str) -> dict[str, Any]:
    _, host = email_servers(creds)
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = creds["address"], ", ".join(to), subject
    message.set_content(body)
    with smtplib.SMTP_SSL(host, 465, context=ssl.create_default_context(), timeout=MAIL_TIMEOUT_SECONDS) as client:
        client.login(creds["address"], creds["password"])
        client.send_message(message)
    return {"sent": True, "to": to}


async def _mail(function: Callable[..., Any], *args: Any) -> Any:
    try:
        return await asyncio.to_thread(function, *args)
    except ConnectorError:
        raise
    except Exception as err:  # imaplib, smtplib, ssl and socket errors
        raise _mail_error(err) from None


async def email_verify(creds, http):
    if not ADDRESS.fullmatch(creds.get("address", "")):
        raise ConnectorError("Enter the full email address.", status_code=400, code="bad_input")

    def check() -> None:
        _imap(creds).logout()

    await _mail(check)
    return creds["address"]


async def email_list_recent(creds, args, http):
    return await _mail(_email_list_sync, creds, ["UNSEEN"] if args.get("unread_only") else ["ALL"], _limit(args))


async def email_search(creds, args, http):
    text = _need(args, "text")[:200].replace("\\", " ").replace('"', " ")
    return await _mail(_email_list_sync, creds, ["TEXT", f'"{text}"'], _limit(args))


async def email_read(creds, args, http):
    return await _mail(_email_read_sync, creds, _need(args, "id", re.compile(r"^\d{1,12}$")))


async def email_send(creds, args, http):
    recipients = [address for _, address in getaddresses([_need(args, "to")])][:20]
    if not recipients or any(not ADDRESS.fullmatch(address) for address in recipients):
        raise ConnectorError("`to` must be one or more email addresses, separated by commas.", status_code=400, code="bad_input")
    subject = " ".join(_need(args, "subject").splitlines())[:300]
    return await _mail(_email_send_sync, creds, recipients, subject, _need(args, "body")[:50000])


VERIFY: dict[str, Callable[..., Awaitable[str]]] = {
    "github": github_verify, "email": email_verify, "telegram": telegram_verify, "slack": slack_verify, "discord": discord_verify, "notion": notion_verify,
}

HANDLERS: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {
    function.__name__: function for function in (
        github_list_repos, github_search_issues, github_get_issue, github_list_pull_requests, github_get_file, github_create_issue, github_comment,
        email_list_recent, email_search, email_read, email_send,
        telegram_get_messages, telegram_send_message,
        slack_list_channels, slack_read_channel, slack_post_message,
        discord_list_channels, discord_read_channel, discord_send_message,
        notion_search, notion_read_page, notion_create_page,
    )
}
