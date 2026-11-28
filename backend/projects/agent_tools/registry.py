"""Versioned tool registration and compatibility dispatch interface."""

from typing import Any

from . import artifacts, browser, research, workspace
from .common import *
from .contracts import ToolContract, build_tool_registry

def agent_tool_specs() -> list[dict[str, Any]]:
    specs = [{'type': 'function', 'function': {'name': 'search_public_site', 'description': 'Search a user-supplied public website by crawling at most five same-host text/HTML pages. Accepts a bare hostname. Never fetches video, audio, or other media files.', 'parameters': {'type': 'object', 'properties': {'url': {'type': 'string', 'description': 'The public hostname or HTTP/HTTPS URL supplied in the task'}, 'query': {'type': 'string', 'description': 'A concise phrase describing the public text information to find'}}, 'required': ['url', 'query']}}}, {'type': 'function', 'function': {'name': 'scrape_public_page', 'description': "Fetch and extract readable text from a public page explicitly included in the user's task. Read-only, same-host only, bounded download.", 'parameters': {'type': 'object', 'properties': {'url': {'type': 'string', 'description': 'A public HTTP/HTTPS URL on a host the user supplied'}}, 'required': ['url']}}}, {'type': 'function', 'function': {'name': 'read_selected_file', 'description': 'Read text from a file explicitly attached to this task. Never reads arbitrary paths.', 'parameters': {'type': 'object', 'properties': {'name': {'type': 'string', 'description': 'The exact uploaded filename'}}, 'required': ['name']}}}, {'type': 'function', 'function': {'name': 'save_text_artifact', 'description': "Save a new text file (Markdown, CSV, JSON, HTML, CSS, JavaScript, SVG, Python and similar) in this task's dedicated output folder. Existing files are never overwritten.", 'parameters': {'type': 'object', 'properties': {'filename': {'type': 'string'}, 'content': {'type': 'string', 'description': 'Complete artifact contents'}}, 'required': ['filename', 'content']}}}, {'type': 'function', 'function': {'name': 'create_office_document', 'description': 'Create a new Word document, PDF, spreadsheet, or PowerPoint presentation in the task output folder. Write Word and PDF content as light Markdown: # headings, - bullet lists, **bold**. Spreadsheet content is CSV text. In a presentation, each # heading starts a slide.', 'parameters': {'type': 'object', 'properties': {'filename': {'type': 'string'}, 'kind': {'type': 'string', 'enum': ['word', 'pdf', 'spreadsheet', 'presentation']}, 'title': {'type': 'string'}, 'content': {'type': 'string', 'description': 'Light Markdown for word, pdf and presentation; CSV for spreadsheet'}}, 'required': ['filename', 'kind', 'title', 'content']}}}, {'type': 'function', 'function': {'name': 'generate_local_image', 'description': 'Generate a PNG with an already-running local ComfyUI or Stable Diffusion WebUI engine. Never uses a cloud image service.', 'parameters': {'type': 'object', 'properties': {'prompt': {'type': 'string'}, 'width': {'type': 'integer', 'enum': [512, 640, 768, 896, 1024]}, 'height': {'type': 'integer', 'enum': [512, 640, 768, 896, 1024]}}, 'required': ['prompt']}}}]
    specs.append({'type': 'function', 'function': {'name': 'browse_public_page', 'description': 'Open one public web page in a fresh isolated browser context and return its visible text plus a saved screenshot. The runtime opens a visible Chromium window only when the original user task explicitly asks to open/show a browser or window; otherwise it stays headless. Explicit headless/background requests override visible intent. The page hostname must have been explicitly named in the user task. Read-only: does not click, type, submit forms, or use browser logins.', 'parameters': {'type': 'object', 'properties': {'url': {'type': 'string', 'description': 'Public HTTP/HTTPS URL explicitly supplied by the user'}}, 'required': ['url']}}})
    specs.append({'type': 'function', 'function': {'name': 'browser_action', 'description': 'Apply one state-bound action to the most recent browser observation, then return a fresh observation and screenshot. Actions are click (named links only), type (named textbox/searchbox; never passwords), select (named combobox), scroll (up/down), and same-host navigate. Do not submit forms or click buttons. Use the exact observation_id returned by browse_public_page or the previous browser_action.', 'parameters': {'type': 'object', 'properties': {'observation_id': {'type': 'string', 'minLength': 32, 'maxLength': 32}, 'action': {'type': 'string', 'enum': ['click', 'type', 'select', 'scroll', 'navigate']}, 'role': {'type': 'string', 'enum': ['link', 'textbox', 'searchbox', 'combobox']}, 'name': {'type': 'string', 'maxLength': 160}, 'value': {'type': 'string', 'maxLength': 1000}, 'url': {'type': 'string', 'maxLength': 2048}, 'direction': {'type': 'string', 'enum': ['up', 'down']}}, 'required': ['observation_id', 'action']}}})
    specs.append({'type': 'function', 'function': {'name': 'search_tools', 'description': 'Search the one-line index of permitted tools for tools that fit a follow-up need, when the tools selected for this task do not include the right one. Returns matching tools with one-line descriptions and scores; the full schemas of the matches are then added to your available tools for the next turn, so call search_tools first and use the new tools afterwards. Read-only: never runs another tool.', 'parameters': {'type': 'object', 'properties': {'query': {'type': 'string', 'description': 'What the tool should do, in plain words'}, 'top_k': {'type': 'integer', 'minimum': 1, 'maximum': 10, 'description': 'How many matches to return (default 5)'}}, 'required': ['query']}}})
    return specs

def project_agent_tool_specs() -> list[dict[str, Any]]:
    return [
        {'type': 'function', 'function': {'name': 'list_project_files', 'description': 'List readable source and document files in the selected task workspace.', 'parameters': {'type': 'object', 'properties': {}, 'required': []}}},
        {'type': 'function', 'function': {'name': 'search_project', 'description': 'Search source files in the selected task workspace for a literal phrase.', 'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']}}},
        {'type': 'function', 'function': {'name': 'read_project_file', 'description': 'Read a bounded line range from one UTF-8 file in the selected task workspace.', 'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}, 'start_line': {'type': 'integer', 'minimum': 1}, 'end_line': {'type': 'integer', 'minimum': 1}}, 'required': ['path']}}},
        {'type': 'function', 'function': {'name': 'propose_project_edit', 'description': 'Apply a localized exact-text replacement to a previously inspected file in the selected task workspace.', 'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}, 'old_text': {'type': 'string'}, 'new_text': {'type': 'string'}, 'summary': {'type': 'string'}}, 'required': ['path', 'old_text', 'new_text', 'summary']}}},
        {'type': 'function', 'function': {'name': 'propose_project_patch', 'description': 'Create or replace one source file in the selected task workspace. Read existing files fully before replacing.', 'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}, 'content': {'type': 'string'}, 'summary': {'type': 'string', 'description': 'One line on the change; optional'}}, 'required': ['path', 'content']}}},
        {'type': 'function', 'function': {'name': 'validate_project', 'description': 'Before reporting completion, validate the workspace: check Python and JavaScript syntax and local HTML references. Under Full Access, also run existing npm build and test scripts in a hidden subprocess with captured output. Fix failures and rerun this tool; report the real results.', 'parameters': {'type': 'object', 'properties': {}, 'required': []}}},
    ]

def registered_tool_contracts() -> dict[str, ToolContract]:
    """Return the validated registry for every model-callable agent tool."""
    return build_tool_registry(agent_tool_specs() + project_agent_tool_specs())

def registered_tool_specs() -> list[dict[str, Any]]:
    """Return the model-facing schemas generated from the typed registry."""
    return [contract.model_spec() for contract in registered_tool_contracts().values()]

async def execute_project_tool(name: str, arguments: dict[str, Any], context: ProjectAgentContext) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise AgentToolError("Tool arguments must be a JSON object")
    if name == "list_project_files":
        return {"files": workspace.list_project_files(context)}
    handlers = {
        "validate_project": lambda: workspace.validate_project_service(context),
        "search_project": lambda: workspace.search_project(context, arguments.get("query")),
        "read_project_file": lambda: workspace.read_project_file(
            context, arguments.get("path"), arguments.get("start_line"), arguments.get("end_line")
        ),
        "propose_project_edit": lambda: workspace.propose_project_edit(
            context, arguments.get("path"), arguments.get("old_text"), arguments.get("new_text"), arguments.get("summary")
        ),
        "propose_project_patch": lambda: workspace.propose_project_patch(
            context, arguments.get("path"), arguments.get("content"), arguments.get("summary")
        ),
    }
    handler = handlers.get(name)
    if handler is None:
        raise AgentToolError("The requested project tool is not available")
    result = handler()
    return await result if hasattr(result, "__await__") else result

async def execute_agent_tool(name: str, arguments: dict[str, Any], context: AgentToolContext) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise AgentToolError("Tool arguments must be a JSON object")
    if name == "search_public_site":
        url, query = arguments.get("url"), arguments.get("query")
        if not isinstance(url, str):
            raise AgentToolError("A public website URL or hostname is required")
        return await research.search_public_site(url, query, context)
    if name == "scrape_public_page":
        if context.scrape_count >= 5:
            raise AgentToolError("A task may fetch at most five public pages")
        url = arguments.get("url")
        if not isinstance(url, str):
            raise AgentToolError("A page URL is required")
        context.scrape_count += 1
        return await research.scrape_public_page(url, context.allowed_hosts)
    if name == "browse_public_page":
        url = arguments.get("url")
        if not isinstance(url, str):
            raise AgentToolError("A public page URL is required")
        return await browser.browse_public_page(url, context)
    if name == "browser_action":
        return await browser.apply_browser_action(arguments, context)
    if name == "read_selected_file":
        filename = arguments.get("name")
        if not isinstance(filename, str) or filename not in context.attachments:
            # Say what is attached and what to do, so the agent asks the user instead of retrying
            # (reports 2026-11-22: five replans on "That file was not attached to this task").
            if context.attachments:
                raise AgentToolError(
                    "That file was not attached to this task. Attached files: "
                    + ", ".join(sorted(context.attachments)[:10])
                    + ". Use one of these exact names."
                )
            raise AgentToolError(
                "No file is attached to this task. Do not try again: in your final answer, ask the user to "
                "attach the file with the paperclip button (or open the folder that contains it) and send the request again."
            )
        return {"name": filename, "text": context.attachments[filename]}
    if name == "save_text_artifact":
        return {"saved": True, **artifacts.save_text_artifact(context, arguments.get("filename"), arguments.get("content"))}
    if name == "create_office_document":
        return {"saved": True, **artifacts.create_office_artifact(
            context, arguments.get("filename"), arguments.get("kind"), arguments.get("title"), arguments.get("content")
        )}
    if name == "generate_local_image":
        return {"generated": True, **await artifacts.generate_local_image(
            context, arguments.get("prompt"), arguments.get("width", 768), arguments.get("height", 768)
        )}
    if name == "search_tools":
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise AgentToolError("A search query is required")
        top_k = arguments.get("top_k", 5)
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1 or top_k > 10:
            raise AgentToolError("top_k must be an integer between 1 and 10")
        # Lazy import: tool_retriever imports this registry module.
        from .tool_retriever import SEARCH_TOOL_NAME, ToolRetriever

        permitted = context.permitted_tools
        if permitted is None:
            # No run context (direct registry call): only read-only tools,
            # so a context-free search can never surface a write/high-risk tool.
            permitted = frozenset(
                tool_name
                for tool_name, contract in registered_tool_contracts().items()
                if contract.risk_level == "read"
            )
        retriever = ToolRetriever()
        retrieval = retriever.retrieve(
            query.strip(),
            top_k=top_k,
            permitted=sorted(permitted),
            permission_mode=context.permission_mode,
        )
        results = [
            {
                "name": tool_name,
                "one_line": retriever.by_name[tool_name].one_line,
                "score": retrieval.scores.get(tool_name, 0.0),
            }
            for tool_name in sorted(
                retrieval.scores, key=lambda item: retrieval.scores[item], reverse=True
            )[:top_k]
            if tool_name != SEARCH_TOOL_NAME
        ]
        return {"query": query.strip(), "results": results, "method": retrieval.method}
    raise AgentToolError("The requested tool is not available in this bounded agent")
