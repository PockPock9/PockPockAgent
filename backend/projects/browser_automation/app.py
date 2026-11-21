"""Run-scoped isolated Chromium contexts for local browser automation."""

from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import socket
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from playwright.async_api import Browser, BrowserContext

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from projects.internal_auth import require_internal_token
from projects.browser_automation import recipes
from projects.browser_automation.engines import BrowserEngine, create_browser_engine


RUN_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
MAX_NAVIGATIONS_PER_RUN = 8
MAX_NETWORK_REQUESTS_PER_RUN = 100
MAX_VISIBLE_TEXT_CHARS = 64_000
NAVIGATION_TIMEOUT_MS = 20_000
RECIPE_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


@dataclass
class BrowserRun:
    browser: Browser
    context: BrowserContext
    visible: bool = False
    page: Any | None = None
    allowed_host: str | None = None
    navigation_count: int = 0
    network_request_count: int = 0
    blocked_reason: str | None = None
    observation_id: str | None = None
    evidence: dict[str, bytes] | None = None


class CreateContextRequest(BaseModel):
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    visible: bool = False


class NavigateRequest(BaseModel):
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    url: str = Field(min_length=1, max_length=2048)


class BrowserActionRequest(BaseModel):
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    observation_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    action: str = Field(pattern=r"^(click|type|select|scroll|navigate)$")
    role: str | None = Field(default=None, max_length=32)
    name: str | None = Field(default=None, max_length=160)
    value: str | None = Field(default=None, max_length=1000)
    url: str | None = Field(default=None, max_length=2048)
    direction: str | None = Field(default=None, pattern=r"^(up|down)$")


class RecipeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    label: str = Field(min_length=1, max_length=80)
    type: Literal["text", "url"] = "text"
    required: bool = True


class RecipeCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title_contains: str | None = Field(default=None, max_length=160)
    text_contains: str | None = Field(default=None, max_length=300)


class RecipeStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["click", "type", "select", "scroll", "navigate"]
    role: Literal["link", "textbox", "searchbox", "combobox"] | None = None
    target_name: str | None = Field(default=None, min_length=1, max_length=160)
    input_ref: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,39}$")
    url: str | None = Field(default=None, max_length=2048)
    direction: Literal["up", "down"] | None = None
    checkpoint: RecipeCheckpoint | None = None

    @model_validator(mode="after")
    def validate_action_shape(self):
        if self.checkpoint is None or not any(
            value and value.strip()
            for value in (self.checkpoint.title_contains, self.checkpoint.text_contains)
        ):
            raise ValueError("Every recipe step needs a page title or visible-text stop condition")
        if self.action == "click" and (self.role != "link" or not self.target_name or self.input_ref or self.url or self.direction):
            raise ValueError("click steps need only a named link target")
        if self.action == "type" and (self.role not in {"textbox", "searchbox"} or not self.target_name or not self.input_ref or self.url or self.direction):
            raise ValueError("type steps need a named text field and an input reference")
        if self.action == "select" and (self.role != "combobox" or not self.target_name or not self.input_ref or self.url or self.direction):
            raise ValueError("select steps need a named combobox and an input reference")
        if self.action == "scroll" and (self.direction not in {"up", "down"} or self.role or self.target_name or self.input_ref or self.url):
            raise ValueError("scroll steps need only an up/down direction")
        if self.action == "navigate" and (not self.url or self.role or self.target_name or self.input_ref or self.direction):
            raise ValueError("navigate steps need only a URL")
        return self


class RecipeDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    allowed_domains: list[str] = Field(min_length=1, max_length=10)
    inputs: list[RecipeInput] = Field(default_factory=list, max_length=20)
    steps: list[RecipeStep] = Field(min_length=1, max_length=40)
    approval_policy: Literal["each_run"] = "each_run"

    @model_validator(mode="after")
    def validate_recipe_references(self):
        if self.steps[0].action != "navigate":
            raise ValueError("The first recipe step must navigate to an allowed page")
        names = [item.name for item in self.inputs]
        if len(names) != len(set(names)):
            raise ValueError("Recipe input names must be unique")
        available = set(names)
        for step in self.steps:
            if step.input_ref and step.input_ref not in available:
                raise ValueError(f"Step input reference '{step.input_ref}' is not declared")
        return self


class UpdateRecipeRequest(RecipeDefinition):
    expected_version: int = Field(ge=1)


class RecipeEnabledRequest(BaseModel):
    enabled: bool


class ExecuteRecipeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    inputs: dict[str, str] = Field(default_factory=dict, max_length=20)


def validate_public_url(url: str) -> str:
    try:
        parsed = urlsplit(url.strip())
        host = parsed.hostname
        port = parsed.port
    except ValueError as err:
        raise HTTPException(status_code=422, detail="Invalid URL or port") from err
    if parsed.scheme.lower() not in {"http", "https"} or not host:
        raise HTTPException(status_code=422, detail="Only absolute HTTP and HTTPS URLs are supported")
    if parsed.username is not None or parsed.password is not None:
        raise HTTPException(status_code=422, detail="URLs containing credentials are not allowed")
    allowed_ports = {None, 80} if parsed.scheme.lower() == "http" else {None, 443}
    if port not in allowed_ports:
        raise HTTPException(status_code=422, detail="Only standard HTTP and HTTPS ports are allowed")
    return host.rstrip(".").lower()


async def resolve_public_host(host: str) -> None:
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            records = await asyncio.wait_for(
                asyncio.to_thread(socket.getaddrinfo, host, None, type=socket.SOCK_STREAM),
                timeout=3,
            )
            addresses = [ipaddress.ip_address(record[4][0].split("%", 1)[0]) for record in records]
        except (OSError, ValueError, asyncio.TimeoutError) as err:
            raise HTTPException(status_code=422, detail="The page host could not be resolved safely") from err
    if not addresses or any(not address.is_global for address in addresses):
        raise HTTPException(status_code=403, detail="Local, private, and reserved network destinations are blocked")


class BrowserRuntime:
    def __init__(self, engine_name: str | None = None) -> None:
        self._engine_name = (engine_name or os.environ.get("POCKPOCK_BROWSER_ENGINE", "playwright")).strip().lower()
        self._engine: BrowserEngine | None = None
        self._runs: dict[str, BrowserRun] = {}
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self._engine = create_browser_engine(self._engine_name)
        await self._engine.start()

    async def accessible_target(self, page, role: str, name: str):
        matches = []
        for frame in page.frames:
            locator = frame.get_by_role(role, name=name, exact=True)
            count = await locator.count()
            if count:
                matches.append((locator, count))
        if sum(count for _, count in matches) != 1:
            raise HTTPException(status_code=409, detail="The accessible target is missing or ambiguous on the current page")
        return matches[0][0]

    async def capture_screenshot(self, page: Any) -> bytes:
        screenshot_format = self._engine.screenshot_format if self._engine is not None else "jpeg"
        options: dict[str, Any] = {
            "type": screenshot_format,
            "full_page": False,
            "timeout": 10_000,
        }
        if screenshot_format == "jpeg":
            options["quality"] = 60
        return await page.screenshot(**options)

    async def close_run(self, run_id: str) -> bool:
        async with self._lock:
            run = self._runs.pop(run_id, None)
        if run is None:
            return False
        if run.evidence is not None:
            run.evidence.clear()
        if run.visible and not run.browser.is_connected():
            return True
        try:
            await run.context.close()
        finally:
            if self._engine is not None:
                await self._engine.close_browser(run.browser)
        return True

    async def forget_disconnected_run(self, run_id: str) -> None:
        async with self._lock:
            run = self._runs.pop(run_id, None)
        if run is not None and run.evidence is not None:
            run.evidence.clear()

    async def close(self) -> None:
        async with self._lock:
            run_ids = list(self._runs)
        for run_id in run_ids:
            await self.close_run(run_id)
        if self._engine is not None:
            await self._engine.stop()
            self._engine = None

    async def create_run(self, run_id: str, *, visible: bool = False) -> dict[str, Any]:
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise HTTPException(status_code=422, detail="run_id must be a 32-character lowercase hex ID")
        if self._engine is None or not self._engine.ready:
            raise HTTPException(status_code=503, detail="Browser runtime is not ready")
        async with self._lock:
            if run_id in self._runs:
                if self._runs[run_id].visible != visible:
                    raise HTTPException(status_code=409, detail="Browser visibility cannot change during a run")
                return {"run_id": run_id, "created": False, "context_id": run_id}
            if visible and self._engine.name != "playwright-chromium":
                raise HTTPException(
                    status_code=503,
                    detail="A visible desktop browser requires the Playwright Chromium engine.",
                )
            if visible and any(run.visible for run in self._runs.values()):
                raise HTTPException(
                    status_code=503,
                    detail="A visible browser window is already open; close it before starting another.",
                )
            max_contexts = self._engine.max_contexts
            if max_contexts is not None and len(self._runs) >= max_contexts:
                raise HTTPException(
                    status_code=503,
                    detail=f"The {self._engine_name} engine supports at most {max_contexts} active browser context",
                )
            browser = await self._engine.launch_browser(visible=visible)
            try:
                context = await browser.new_context(
                    accept_downloads=False,
                    service_workers="block",
                    permissions=[],
                )
            except Exception:
                await self._engine.close_browser(browser)
                raise
            self._runs[run_id] = BrowserRun(browser=browser, context=context, visible=visible)
            if visible:
                browser.on(
                    "disconnected",
                    lambda _: asyncio.create_task(self.forget_disconnected_run(run_id)),
                )
        return {"run_id": run_id, "created": True, "context_id": run_id}

    async def navigate(self, run_id: str, url: str) -> dict[str, Any]:
        run = self._runs.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="No isolated browser context exists for this run")
        host = validate_public_url(url)
        if run.allowed_host is not None and host != run.allowed_host:
            raise HTTPException(status_code=403, detail="Cross-host navigation and requests are blocked")
        await resolve_public_host(host)
        if run.navigation_count >= MAX_NAVIGATIONS_PER_RUN:
            raise HTTPException(status_code=429, detail="This run reached its navigation safety limit")
        if run.page is None:
            run.allowed_host = host
            run.page = await run.context.new_page()
            run.evidence = {}

            async def guard_request(route):
                run.network_request_count += 1
                if run.network_request_count > MAX_NETWORK_REQUESTS_PER_RUN:
                    run.blocked_reason = "This run reached its network-request safety limit"
                    await route.abort("blockedbyclient")
                    return
                if route.request.method not in {"GET", "HEAD"}:
                    run.blocked_reason = "Only read-only GET and HEAD requests are allowed"
                    await route.abort("blockedbyclient")
                    return
                try:
                    request_host = validate_public_url(route.request.url)
                    if request_host != run.allowed_host:
                        run.blocked_reason = "Cross-host navigation and requests are blocked"
                        await route.abort("blockedbyclient")
                        return
                    await resolve_public_host(request_host)
                except HTTPException as err:
                    run.blocked_reason = err.detail
                    await route.abort("blockedbyclient")
                    return
                await route.continue_()

            await run.context.route("**/*", guard_request)
        run.navigation_count += 1
        run.blocked_reason = None
        run.observation_id = None
        try:
            response = await run.page.goto(url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
            if response is not None and response.status >= 400:
                raise HTTPException(status_code=502, detail=f"Page returned HTTP {response.status}")
            final_url = run.page.url
            final_host = validate_public_url(final_url)
            if final_host != run.allowed_host:
                raise HTTPException(status_code=403, detail="Cross-host redirects are blocked")
            await resolve_public_host(final_host)
            title = await run.page.title()
            visible_text = await run.page.locator("body").inner_text(timeout=5_000)
            visible_text = visible_text[:MAX_VISIBLE_TEXT_CHARS]
            screenshot = await self.capture_screenshot(run.page)
            if len(screenshot) > 2_000_000:
                raise HTTPException(status_code=502, detail="Page screenshot exceeded the evidence size limit")
        except HTTPException:
            raise
        except Exception as err:
            if run.blocked_reason:
                raise HTTPException(status_code=403, detail=run.blocked_reason) from err
            raise HTTPException(status_code=502, detail=f"Page navigation failed: {type(err).__name__}") from err
        evidence_id = uuid4().hex
        if run.evidence is None:
            run.evidence = {}
        run.evidence[evidence_id] = screenshot
        run.observation_id = uuid4().hex
        return {
            "run_id": run_id,
            "requested_url": url,
            "final_url": final_url,
            "title": title[:512],
            "visible_text": visible_text,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "observation_id": run.observation_id,
            "navigation_number": run.navigation_count,
            "screenshot_ref": f"/evidence/{run_id}/{evidence_id}",
            "screenshot_bytes": len(screenshot),
        }

    async def act(self, payload: BrowserActionRequest) -> dict[str, Any]:
        run = self._runs.get(payload.run_id)
        if run is None or run.page is None or run.allowed_host is None:
            raise HTTPException(status_code=404, detail="No observed browser page exists for this run")
        if payload.observation_id != run.observation_id:
            raise HTTPException(status_code=409, detail="The page changed; observe it again before applying this action")
        if run.navigation_count >= MAX_NAVIGATIONS_PER_RUN:
            raise HTTPException(status_code=429, detail="This run reached its navigation safety limit")
        page = run.page
        run.observation_id = None
        action_description: dict[str, Any] = {"action": payload.action}
        try:
            if payload.action == "navigate":
                if not payload.url:
                    raise HTTPException(status_code=422, detail="A URL is required for navigation")
                target_host = validate_public_url(payload.url)
                if target_host != run.allowed_host:
                    raise HTTPException(status_code=403, detail="Cross-host navigation is blocked")
                await resolve_public_host(target_host)
                run.navigation_count += 1
                run.blocked_reason = None
                await page.goto(payload.url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
                action_description["url"] = payload.url
            elif payload.action == "click":
                if payload.role != "link" or not payload.name:
                    raise HTTPException(status_code=403, detail="BRW-04 currently allows clicks on named links only")
                locator = await self.accessible_target(page, "link", payload.name)
                if (await locator.get_attribute("target") or "").lower() == "_blank":
                    raise HTTPException(status_code=403, detail="Links that open a new tab are not supported")
                href = await locator.get_attribute("href")
                target_host = validate_public_url(urljoin(page.url, href or ""))
                if target_host != run.allowed_host:
                    raise HTTPException(status_code=403, detail="Cross-host navigation is blocked")
                await resolve_public_host(target_host)
                run.navigation_count += 1
                await locator.click(timeout=5_000)
                action_description.update({"role": payload.role, "name": payload.name})
            elif payload.action == "type":
                if payload.role not in {"textbox", "searchbox"} or not payload.name or payload.value is None:
                    raise HTTPException(status_code=422, detail="Typing requires a named textbox/searchbox and a value")
                locator = await self.accessible_target(page, payload.role, payload.name)
                if (await locator.get_attribute("type") or "").lower() == "password":
                    raise HTTPException(status_code=403, detail="Typing into password fields is not supported")
                await locator.fill(payload.value, timeout=5_000)
                action_description.update({"role": payload.role, "name": payload.name, "value_length": len(payload.value)})
            elif payload.action == "select":
                if payload.role != "combobox" or not payload.name or payload.value is None:
                    raise HTTPException(status_code=422, detail="Select requires a named combobox and an option label")
                locator = await self.accessible_target(page, "combobox", payload.name)
                await locator.select_option(label=payload.value, timeout=5_000)
                action_description.update({"role": payload.role, "name": payload.name, "selected_label": payload.value})
            elif payload.action == "scroll":
                if payload.direction not in {"up", "down"}:
                    raise HTTPException(status_code=422, detail="Scroll direction must be up or down")
                await page.mouse.wheel(0, -500 if payload.direction == "up" else 500)
                action_description["direction"] = payload.direction
            else:
                raise HTTPException(status_code=422, detail="Unsupported browser action")
            final_host = validate_public_url(page.url)
            if final_host != run.allowed_host:
                raise HTTPException(status_code=403, detail="Cross-host navigation is blocked")
            await resolve_public_host(final_host)
            title = await page.title()
            visible_text = (await page.locator("body").inner_text(timeout=5_000))[:MAX_VISIBLE_TEXT_CHARS]
            screenshot = await self.capture_screenshot(page)
            if len(screenshot) > 2_000_000:
                raise HTTPException(status_code=502, detail="Page screenshot exceeded the evidence size limit")
        except HTTPException:
            raise
        except Exception as err:
            if run.blocked_reason:
                raise HTTPException(status_code=403, detail=run.blocked_reason) from err
            raise HTTPException(status_code=502, detail=f"Browser action failed: {type(err).__name__}") from err
        evidence_id = uuid4().hex
        if run.evidence is None:
            run.evidence = {}
        run.evidence[evidence_id] = screenshot
        run.observation_id = uuid4().hex
        return {
            "run_id": payload.run_id,
            "observation_id": run.observation_id,
            "action": action_description,
            "final_url": page.url,
            "title": title[:512],
            "visible_text": visible_text,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "screenshot_ref": f"/evidence/{payload.run_id}/{evidence_id}",
            "screenshot_bytes": len(screenshot),
        }

    def status(self) -> dict[str, Any]:
        return {
            "ok": self._engine is not None and self._engine.ready,
            "service": "browser-automation",
            "engine": self._engine_name,
            "max_contexts": self._engine.max_contexts if self._engine is not None else None,
            "active_contexts": len(self._runs),
            "profile_persistence": False,
        }


runtime = BrowserRuntime()


@asynccontextmanager
async def lifespan(_: FastAPI):
    recipes.initialize()
    await runtime.start()
    try:
        yield
    finally:
        await runtime.close()


app = FastAPI(title="PockPock Browser Automation", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


@app.get("/health")
async def health():
    return runtime.status()


async def normalized_recipe_definition(payload: RecipeDefinition) -> dict[str, Any]:
    domains: list[str] = []
    for candidate in payload.allowed_domains:
        host = candidate.strip().lower().rstrip(".")
        if not host or any(character in host for character in "/?#@:") or "*" in host:
            raise HTTPException(status_code=422, detail="Recipe domains must be exact hostnames without paths, ports, or wildcards")
        try:
            normalized = validate_public_url(f"https://{host}")
        except HTTPException as err:
            raise HTTPException(status_code=422, detail="A recipe domain is not a valid public HTTP host") from err
        if normalized != host or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", host):
            raise HTTPException(status_code=422, detail="Recipe domains must be exact hostnames without paths, ports, or wildcards")
        labels = host.split(".")
        if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in labels):
            raise HTTPException(status_code=422, detail="A recipe domain contains an invalid hostname label")
        if normalized not in domains:
            await resolve_public_host(normalized)
            domains.append(normalized)
    definition = payload.model_dump(mode="json", exclude={"expected_version"})
    definition["allowed_domains"] = domains
    for step in definition["steps"]:
        if step["action"] == "navigate":
            try:
                step_host = validate_public_url(step["url"])
            except HTTPException as err:
                raise HTTPException(status_code=422, detail="Recipe navigation steps need a public HTTP or HTTPS URL") from err
            if step_host not in domains:
                raise HTTPException(status_code=422, detail="Every recipe navigation URL must use an allowed domain")
    return definition


@app.get("/recipes", dependencies=[Depends(require_internal_token)])
async def list_browser_recipes():
    return {"recipes": recipes.list_recipes()}


@app.post("/recipes", dependencies=[Depends(require_internal_token)])
async def create_browser_recipe(payload: RecipeDefinition):
    definition = await normalized_recipe_definition(payload)
    recipe_id = uuid4().hex
    timestamp = datetime.now(timezone.utc).isoformat()
    try:
        return recipes.create_recipe(recipe_id, definition, timestamp)
    except Exception as err:
        raise HTTPException(status_code=500, detail="Could not save the local browser recipe") from err


@app.get("/recipes/{recipe_id}", dependencies=[Depends(require_internal_token)])
async def get_browser_recipe(recipe_id: str):
    if not RECIPE_ID_PATTERN.fullmatch(recipe_id):
        raise HTTPException(status_code=404, detail="Recipe not found")
    recipe = recipes.get_recipe(recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return recipe


@app.get("/recipes/{recipe_id}/versions", dependencies=[Depends(require_internal_token)])
async def list_browser_recipe_versions(recipe_id: str):
    if not RECIPE_ID_PATTERN.fullmatch(recipe_id):
        raise HTTPException(status_code=404, detail="Recipe not found")
    versions = recipes.get_versions(recipe_id)
    if not versions:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return {"recipe_id": recipe_id, "versions": versions}


@app.put("/recipes/{recipe_id}", dependencies=[Depends(require_internal_token)])
async def update_browser_recipe(recipe_id: str, payload: UpdateRecipeRequest):
    if not RECIPE_ID_PATTERN.fullmatch(recipe_id):
        raise HTTPException(status_code=404, detail="Recipe not found")
    definition = await normalized_recipe_definition(payload)
    timestamp = datetime.now(timezone.utc).isoformat()
    try:
        updated = recipes.update_recipe(recipe_id, payload.expected_version, definition, timestamp)
    except ValueError as err:
        raise HTTPException(status_code=409, detail=str(err)) from err
    if updated is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return updated


@app.post("/recipes/{recipe_id}/enabled", dependencies=[Depends(require_internal_token)])
async def set_browser_recipe_enabled(recipe_id: str, payload: RecipeEnabledRequest):
    if not RECIPE_ID_PATTERN.fullmatch(recipe_id):
        raise HTTPException(status_code=404, detail="Recipe not found")
    recipe = recipes.set_enabled(recipe_id, payload.enabled, datetime.now(timezone.utc).isoformat())
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return recipe


@app.delete("/recipes/{recipe_id}", dependencies=[Depends(require_internal_token)])
async def delete_browser_recipe(recipe_id: str):
    if not RECIPE_ID_PATTERN.fullmatch(recipe_id):
        raise HTTPException(status_code=404, detail="Recipe not found")
    if not recipes.delete_recipe(recipe_id):
        raise HTTPException(status_code=404, detail="Recipe not found")
    return {"recipe_id": recipe_id, "deleted": True}


def checkpoint_matches(checkpoint: dict[str, Any], observation: dict[str, Any]) -> bool:
    title = observation.get("title", "").casefold()
    visible_text = observation.get("visible_text", "").casefold()
    expected_title = (checkpoint.get("title_contains") or "").strip().casefold()
    expected_text = (checkpoint.get("text_contains") or "").strip().casefold()
    return (not expected_title or expected_title in title) and (not expected_text or expected_text in visible_text)


@app.post("/recipes/{recipe_id}/execute", dependencies=[Depends(require_internal_token)])
async def execute_browser_recipe(recipe_id: str, payload: ExecuteRecipeRequest):
    if not RECIPE_ID_PATTERN.fullmatch(recipe_id):
        raise HTTPException(status_code=404, detail="Recipe not found")
    recipe = recipes.get_recipe(recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    if not recipe["enabled"]:
        raise HTTPException(status_code=409, detail="Disabled recipes cannot be executed")
    if recipe["version"] != payload.version:
        raise HTTPException(status_code=409, detail="Recipe version changed; reload it before execution")
    definition = next((entry["definition"] for entry in recipes.get_versions(recipe_id) if entry["version"] == payload.version), None)
    if definition is None:
        raise HTTPException(status_code=409, detail="The requested recipe version is unavailable")
    declared = {item["name"]: item for item in definition["inputs"]}
    if set(payload.inputs) - set(declared):
        raise HTTPException(status_code=422, detail="Execution contains undeclared inputs")
    for name, spec in declared.items():
        value = payload.inputs.get(name)
        if spec["required"] and (value is None or not value.strip()):
            raise HTTPException(status_code=422, detail=f"Required input '{name}' is missing")
        if value is not None and len(value) > 1000:
            raise HTTPException(status_code=422, detail="Input values are limited to 1,000 characters")
        if value is not None and spec["type"] == "url":
            host = validate_public_url(value)
            if host not in definition["allowed_domains"]:
                raise HTTPException(status_code=403, detail=f"URL input '{name}' is outside the recipe host allowlist")

    execution_id = uuid4().hex
    results: list[dict[str, Any]] = []
    terminal = "failed"
    try:
        await runtime.create_run(execution_id)
        for index, step in enumerate(definition["steps"]):
            if step["action"] == "navigate":
                observation = await runtime.navigate(execution_id, step["url"])
            else:
                current = runtime._runs.get(execution_id)
                if current is None or current.observation_id is None:
                    raise HTTPException(status_code=409, detail="The browser observation expired before the next recipe step")
                action = BrowserActionRequest(
                    run_id=execution_id,
                    observation_id=current.observation_id,
                    action=step["action"],
                    role=step.get("role"),
                    name=step.get("target_name"),
                    value=payload.inputs.get(step["input_ref"]) if step.get("input_ref") else None,
                    direction=step.get("direction"),
                )
                observation = await runtime.act(action)
            matched = checkpoint_matches(step["checkpoint"], observation)
            results.append({
                "step": index + 1,
                "action": step["action"],
                "status": "passed" if matched else "checkpoint_mismatch",
                "checkpoint": step["checkpoint"],
                "title": observation["title"],
                "url": observation["final_url"],
                "retrieved_at": observation["retrieved_at"],
            })
            if not matched:
                terminal = "checkpoint_mismatch"
                break
        else:
            terminal = "completed"
        return {"recipe_id": recipe_id, "version": payload.version, "status": terminal, "steps": results}
    except HTTPException as err:
        terminal = "failed"
        return {"recipe_id": recipe_id, "version": payload.version, "status": terminal, "steps": results, "stop_reason": err.detail}
    finally:
        await runtime.close_run(execution_id)


def browser_start_error(err: Exception) -> str:
    """Why the browser did not start, not only the exception type (issue #46). Playwright puts the
    cause (for example a missing Chromium executable and its path) in the first line."""
    first = next((line.strip() for line in str(err).splitlines() if line.strip()), "")
    first = re.sub(r"^[A-Za-z]+\.launch:\s*", "", first)[:300]
    detail = f"Could not start isolated browser: {type(err).__name__}" + (f": {first}" if first else "")
    if re.search(r"Executable doesn't exist|playwright install", str(err), re.I):
        detail += ". The agent browser is not installed; run PockPock Setup (or 'python -m playwright install chromium')."
    return detail


@app.post("/contexts", dependencies=[Depends(require_internal_token)])
async def create_context(payload: CreateContextRequest):
    try:
        return await runtime.create_run(payload.run_id, visible=payload.visible)
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=503, detail=browser_start_error(err)) from err


@app.delete("/contexts/{run_id}", dependencies=[Depends(require_internal_token)])
async def close_context(run_id: str):
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise HTTPException(status_code=422, detail="run_id must be a 32-character lowercase hex ID")
    return {"run_id": run_id, "closed": await runtime.close_run(run_id)}


@app.post("/navigate", dependencies=[Depends(require_internal_token)])
async def navigate(payload: NavigateRequest):
    try:
        return await runtime.navigate(payload.run_id, payload.url)
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=502, detail=f"Browser navigation failed: {type(err).__name__}") from err


@app.post("/actions", dependencies=[Depends(require_internal_token)])
async def apply_action(payload: BrowserActionRequest):
    try:
        return await runtime.act(payload)
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=502, detail=f"Browser action failed: {type(err).__name__}") from err


@app.get("/evidence/{run_id}/{evidence_id}", dependencies=[Depends(require_internal_token)])
async def read_evidence(run_id: str, evidence_id: str):
    if not RUN_ID_PATTERN.fullmatch(run_id) or not RUN_ID_PATTERN.fullmatch(evidence_id):
        raise HTTPException(status_code=404, detail="Evidence not found")
    run = runtime._runs.get(run_id)
    screenshot = run.evidence.get(evidence_id) if run and run.evidence else None
    if screenshot is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    screenshot_format = runtime._engine.screenshot_format if runtime._engine is not None else "jpeg"
    media_type = "image/png" if screenshot_format == "png" else "image/jpeg"
    return Response(content=screenshot, media_type=media_type, headers={"Cache-Control": "no-store"})


@app.delete("/runs/{run_id}", dependencies=[Depends(require_internal_token)])
async def cancel_run_contexts(run_id: str):
    """FND-02 cancellation hook: close any browser process owned by this run."""
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise HTTPException(status_code=422, detail="run_id must be a 32-character lowercase hex ID")
    return {"run_id": run_id, "cancelled": await runtime.close_run(run_id)}
