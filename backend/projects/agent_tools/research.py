"""Bounded public-site research and URL safety checks."""

from datetime import datetime, timezone

from .common import *
from .research_contracts import ResearchProviderError, ResearchResponse, deduplicate_sources, named_host_page_record

class _PageTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._ignored = 0
        self._in_title = False
        self._active_link: tuple[str, list[str]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg", "nav", "footer"}:
            self._ignored += 1
        if tag == "a" and not self._ignored:
            href = next((value for name, value in attrs if name == "href" and value), None)
            if href:
                self._active_link = (href, [])
        if tag == "title":
            self._in_title = True
        if tag in {"p", "br", "div", "section", "article", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._active_link:
            href, label_parts = self._active_link
            self.links.append((href, " ".join(label_parts).strip()))
            self._active_link = None
        if tag in {"script", "style", "noscript", "svg", "nav", "footer"} and self._ignored:
            self._ignored -= 1
        if tag == "title":
            self._in_title = False
        if tag in {"p", "br", "div", "section", "article", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored:
            return
        text = data.strip()
        if text:
            self.parts.append(text)
            self.parts.append(" ")
            if self._active_link:
                self._active_link[1].append(text)
            if self._in_title:
                self.title_parts.append(text)

    @property
    def title(self) -> str:
        return " ".join(self.title_parts).strip()

    @property
    def text(self) -> str:
        lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(self.parts).splitlines()]
        return "\n".join(line for line in lines if line)[:MAX_PAGE_TEXT]

class _PinnedResolver(AbstractResolver):
    def __init__(self, host: str, addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address]) -> None:
        self.host = host
        self.addresses = addresses

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET) -> list[dict[str, Any]]:
        if host.lower() != self.host.lower():
            raise OSError("The page attempted to connect to an unapproved host")
        return [
            {
                "hostname": host,
                "host": str(address),
                "port": port,
                "family": socket.AF_INET6 if address.version == 6 else socket.AF_INET,
                "proto": 0,
                "flags": socket.AI_NUMERICHOST,
            }
            for address in self.addresses
            if family in {socket.AF_UNSPEC, socket.AF_INET6 if address.version == 6 else socket.AF_INET}
        ]

    async def close(self) -> None:
        return None

def explicit_task_hosts(task: str) -> set[str]:
    hosts: set[str] = set()
    for match in _DOMAIN_TOKEN.finditer(task):
        candidate = match.group(0)
        candidate = candidate.rstrip(".,;:!?)]}")
        if not re.match(r"https?://", candidate, re.IGNORECASE):
            candidate = f"https://{candidate}"
        try:
            parsed = urlsplit(candidate)
        except ValueError:
            continue
        if parsed.hostname:
            hosts.add(parsed.hostname.lower())
    return hosts

def normalize_public_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise AgentToolError("A public website URL or hostname is required")
    candidate = url.strip()
    if not re.match(r"https?://", candidate, re.IGNORECASE):
        candidate = f"https://{candidate}"
    try:
        parsed = urlsplit(candidate)
    except ValueError as err:
        raise AgentToolError("The page URL is malformed") from err
    return urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path or "/",
        parsed.query,
        parsed.fragment,
    ))

def is_bulk_media_download_request(task: str) -> bool:
    return bool(re.search(
        r"\b(?:download|rip|copy|grab|save|extract)\b.{0,100}"
        r"\b(?:all|every|entire|whole)\b.{0,50}"
        r"\b(?:anime|videos?|episodes?|movies?|films?|series|streams?)\b",
        task,
        flags=re.IGNORECASE | re.DOTALL,
    ))

def requested_artifact_extension(task: str) -> str | None:
    for clause in re.split(r"[.!?;\n]+", non_negated_task_text(task)):
        action = re.search(
            r"\b(?:create|make|write|save|export|build|generate)\b(.{0,120})",
            clause,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not action or re.search(
            r"\b(?:how\s+to|guide\s+to|instructions?\s+to)\s*$",
            clause[:action.start()],
            re.IGNORECASE,
        ):
            continue
        request = action.group(1)
        if re.search(r"\b(?:\.docx|docx|word\s+(?:document|file))\b", request, re.IGNORECASE):
            return ".docx"
        if re.search(r"\b(?:\.xlsx|xlsx|spreadsheet|workbook|excel)\b", request, re.IGNORECASE):
            return ".xlsx"
        if re.search(r"\b(?:\.pptx|pptx|presentation|powerpoint|slides)\b", request, re.IGNORECASE):
            return ".pptx"
        for extension, pattern in (
            (".csv", r"\b(?:\.csv|csv)\b"),
            (".json", r"\b(?:\.json|json)\b"),
            (".html", r"\b(?:\.html|html)\b"),
            (".md", r"\b(?:\.md|markdown)\b"),
            (".txt", r"\b(?:\.txt|text file|plain text)\b"),
        ):
            if re.search(pattern, request, re.IGNORECASE):
                return extension
        if re.search(r"\b(?:game|website|web\s+app|webpage|interactive\s+demo)\b", request, re.IGNORECASE):
            return ".html"
        if re.search(r"\b(?:file|document|report|brief)\b", request, re.IGNORECASE):
            return ".md"
    return None

def _validate_public_url(url: str, allowed_hosts: set[str]) -> tuple[str, int, str]:
    if len(url) > 2048:
        raise AgentToolError("URL is too long")
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").rstrip(".").lower()
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except ValueError as err:
        raise AgentToolError("The page URL is malformed") from err
    if parsed.scheme.lower() not in {"http", "https"} or not host or parsed.username or parsed.password:
        raise AgentToolError("Only public HTTP or HTTPS page URLs are allowed")
    if host not in allowed_hosts:
        raise AgentToolError("Only the public website hostname included in your task may be fetched")
    expected_port = 443 if parsed.scheme.lower() == "https" else 80
    if port != expected_port:
        raise AgentToolError("Only standard HTTP and HTTPS ports may be fetched")
    try:
        literal = ipaddress.ip_address(host)
        addresses = [literal]
    except ValueError:
        addresses = []
    if addresses:
        if not all(address.is_global for address in addresses):
            raise AgentToolError("Private and reserved network addresses cannot be fetched")
    return host, port, parsed.path or "/"

async def _resolve_public(host: str, port: int) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        records = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM),
            timeout=3,
        )
    except (OSError, asyncio.TimeoutError) as err:
        raise AgentToolError(f"Could not resolve the public website hostname: {host}") from err
    addresses = []
    for record in records:
        try:
            address = ipaddress.ip_address(record[4][0])
        except ValueError:
            continue
        if not address.is_global:
            raise AgentToolError("The website resolves to a private or reserved network address")
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise AgentToolError("The website hostname did not resolve to a public address")
    return addresses

def website_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    if os.name != "nt" or not hasattr(ssl, "enum_certificates"):
        return context
    try:
        certificates = ssl.enum_certificates("ROOT")
        server_auth_oid = "1.3.6.1.5.5.7.3.1"
        any_usage_oid = "2.5.29.37.0"
        trust_roots = [
            ssl.DER_cert_to_PEM_cert(certificate)
            for certificate, encoding, trust in certificates
            if encoding == "x509_asn"
            and (
                trust is True
                or isinstance(trust, (set, frozenset))
                and (server_auth_oid in trust or any_usage_oid in trust)
            )
        ]
        if not trust_roots:
            raise AgentToolError("The Windows trusted root store has no HTTPS server certificates")
        context.load_verify_locations(cadata="\n".join(trust_roots))
    except (OSError, ssl.SSLError, ValueError) as err:
        raise AgentToolError(f"Could not load the Windows trusted root certificates: {err}") from err
    return context

async def scrape_public_page(
    url: str,
    allowed_hosts: set[str],
    *,
    include_links: bool = False,
) -> dict[str, Any]:
    current = url
    for redirect_number in range(6):
        host, port, _ = _validate_public_url(current, allowed_hosts)
        addresses = await _resolve_public(host, port)
        async with _DOMAIN_LOCK:
            now = time.monotonic()
            wait = 1.0 - (now - _DOMAIN_REQUESTS.get(host, 0.0))
            if wait > 0:
                await asyncio.sleep(wait)
            _DOMAIN_REQUESTS[host] = time.monotonic()

        resolver = _PinnedResolver(host, addresses)
        connector = aiohttp.TCPConnector(
            resolver=resolver,
            use_dns_cache=False,
            ssl=website_ssl_context(),
        )
        timeout = aiohttp.ClientTimeout(total=15, connect=5, sock_read=10)
        try:
            async with aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={
                    "User-Agent": "PockPockAI/1.0 (local research assistant)",
                    "Accept": "text/html,text/plain,application/json,application/xml;q=0.8,*/*;q=0.1",
                },
            ) as session:
                async with session.get(current, allow_redirects=False) as response:
                    if response.status in {301, 302, 303, 307, 308}:
                        location = response.headers.get("Location")
                        if not location or redirect_number >= 5:
                            raise AgentToolError("The website redirected too many times")
                        current = urljoin(current, location)
                        continue
                    if response.status >= 400:
                        raise AgentToolError(f"The website returned HTTP {response.status}")
                    content_type = response.headers.get("Content-Type", "").lower()
                    if not any(kind in content_type for kind in ("text/", "application/json", "application/xml")):
                        raise AgentToolError("The page is not a supported text or HTML document")
                    content_length = response.headers.get("Content-Length")
                    if content_length and int(content_length) > MAX_PAGE_BYTES:
                        raise AgentToolError("The page exceeds the 2 MB download limit")
                    data = bytearray()
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        data.extend(chunk)
                        if len(data) > MAX_PAGE_BYTES:
                            raise AgentToolError("The page exceeds the 2 MB download limit")
                    charset = response.charset or "utf-8"
                    text = bytes(data).decode(charset, errors="replace")
                    if "html" in content_type:
                        parser = _PageTextParser()
                        parser.feed(text)
                        page: dict[str, Any] = {
                            "url": current,
                            "title": parser.title,
                            "text": parser.text,
                        }
                        if include_links:
                            page["links"] = parser.links[:MAX_LINKS_PER_PAGE]
                        return page
                    return {"url": current, "title": "", "text": text[:MAX_PAGE_TEXT]}
        except AgentToolError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, LookupError) as err:
            raise AgentToolError(f"Could not fetch the public page: {err}") from err
    raise AgentToolError("The website redirected too many times")

async def search_public_site(
    url: str,
    query: str,
    context: AgentToolContext,
) -> dict[str, Any]:
    if not isinstance(query, str) or not query.strip() or len(query) > 500:
        raise AgentToolError("Provide a concise search query of at most 500 characters")
    remaining = MAX_SITE_PAGES - context.scrape_count
    if remaining <= 0:
        raise AgentToolError("A task may scan at most five public pages")
    starting_scrape_count = context.scrape_count

    start_url = normalize_public_url(url)
    _validate_public_url(start_url, context.allowed_hosts)
    queue = [urldefrag(start_url)[0]]
    queued = set(queue)
    query_terms = set(re.findall(r"[a-z0-9]{3,}", query.lower()))
    pages: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    while queue and context.scrape_count - starting_scrape_count < remaining:
        current = queue.pop(0)
        context.scrape_count += 1
        try:
            fetched = await scrape_public_page(current, context.allowed_hosts, include_links=True)
        except AgentToolError as err:
            if not pages:
                raise
            errors.append({"url": current, "error": str(err)})
            continue

        pages.append({
            "url": fetched["url"],
            "title": fetched["title"],
            "text": fetched["text"][:MAX_SITE_PAGE_TEXT],
        })
        candidates: list[tuple[int, int, str]] = []
        for index, (href, label) in enumerate(fetched.get("links", [])):
            destination = urldefrag(urljoin(fetched["url"], href))[0]
            try:
                _validate_public_url(destination, context.allowed_hosts)
            except AgentToolError:
                continue
            parsed = urlsplit(destination)
            if Path(parsed.path).suffix.lower() in _MEDIA_EXTENSIONS or destination in queued:
                continue
            queued.add(destination)
            searchable = f"{label} {parsed.path}".lower()
            score = sum(1 for term in query_terms if term in searchable)
            candidates.append((-score, index, destination))
        candidates.sort()
        queue.extend(destination for _, _, destination in candidates)
        if len(queue) > MAX_LINKS_PER_PAGE:
            queue = queue[:MAX_LINKS_PER_PAGE]

    retrieved_at = datetime.now(timezone.utc)
    records = []
    evidence = []
    for page in pages:
        try:
            record, excerpt = named_host_page_record(page, retrieved_at=retrieved_at)
        except ValueError:
            continue
        records.append(record)
        evidence.append(excerpt)
    unique_records = deduplicate_sources(records)
    unique_ids = {record.source_id for record in unique_records}
    research = ResearchResponse(
        query=query.strip(),
        provider="named_host_fetcher",
        retrieved_at=retrieved_at,
        results=unique_records,
        errors=[ResearchProviderError(
            provider="named_host_fetcher",
            code="upstream_error",
            message="A linked page could not be retrieved.",
            retryable=True,
        ) for _ in errors[:20]],
    )
    unique_evidence = []
    seen_evidence = set()
    for item in evidence:
        if item.source_id in unique_ids and item.source_id not in seen_evidence:
            unique_evidence.append(item.model_dump(mode="json"))
            seen_evidence.add(item.source_id)

    return {
        "query": query.strip(),
        "pages_scanned": len(pages),
        "page_limit": min(MAX_SITE_PAGES, remaining),
        "pages": pages,
        "page_errors": errors,
        "research": research.model_dump(mode="json"),
        "evidence": unique_evidence,
    }
