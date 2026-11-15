"""Task artifact creation and local image-engine integration."""

from .common import *

def _safe_filename(filename: str, extension: str) -> str:
    if not isinstance(filename, str) or not filename:
        raise AgentToolError("A filename is required")
    name = Path(filename).name
    if name != filename or not _FILENAME.fullmatch(name):
        raise AgentToolError("Use a simple filename without folders or special characters")
    if Path(name).suffix.lower() != extension:
        name = f"{name}{extension}"
    return name

def _record_artifact(context: AgentToolContext, path: Path, kind: str) -> dict[str, str]:
    artifact = {"name": path.name, "path": str(path), "kind": kind}
    context.artifacts.append(artifact)
    return artifact

def save_text_artifact(context: AgentToolContext, filename: str, content: str) -> dict[str, str]:
    if not isinstance(content, str) or not content.strip() or len(content) > MAX_OUTPUT_CHARS:
        raise AgentToolError("Text output must be non-empty and at most 100,000 characters")
    extension = Path(filename).suffix.lower()
    if extension not in {".txt", ".md", ".csv", ".json", ".html"}:
        raise AgentToolError("Text output must use .txt, .md, .csv, .json, or .html")
    safe_name = _safe_filename(filename, extension)
    path = context.output_dir / safe_name
    try:
        with path.open("x", encoding="utf-8", newline="") as output:
            output.write(content)
    except FileExistsError as err:
        raise AgentToolError("That filename already exists in this task; choose another name") from err
    return _record_artifact(context, path, "file")

def create_office_artifact(
    context: AgentToolContext,
    filename: str,
    kind: str,
    title: str,
    content: str,
) -> dict[str, str]:
    if not isinstance(content, str) or not content.strip() or len(content) > MAX_OUTPUT_CHARS:
        raise AgentToolError("Document content must be non-empty and at most 100,000 characters")
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise AgentToolError("Document title must be between 1 and 200 characters")

    if not isinstance(kind, str):
        raise AgentToolError("Choose a Word document, spreadsheet, or presentation")
    extension = {"word": ".docx", "spreadsheet": ".xlsx", "presentation": ".pptx"}.get(kind)
    if extension is None:
        raise AgentToolError("Choose a Word document, spreadsheet, or presentation")
    path = context.output_dir / _safe_filename(filename, extension)
    if path.exists():
        raise AgentToolError("That filename already exists in this task; choose another name")

    try:
        if kind == "word":
            from docx import Document

            document = Document()
            document.add_heading(title, level=0)
            for paragraph in content.splitlines():
                if paragraph.strip():
                    document.add_paragraph(paragraph[:4000])
            document.save(path)
        elif kind == "spreadsheet":
            from openpyxl import Workbook

            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Task output"
            for row in csv.reader(io.StringIO(content), strict=False):
                sheet.append([cell[:2000] for cell in row[:30]])
                if sheet.max_row >= 1000:
                    break
            workbook.save(path)
        else:
            from pptx import Presentation
            from pptx.util import Pt

            presentation = Presentation()
            paragraphs = [part.strip() for part in re.split(r"\n\s*\n", content) if part.strip()]
            chunks = paragraphs[:20] or [content]
            for index, chunk in enumerate(chunks):
                layout = presentation.slide_layouts[0 if index == 0 else 1]
                slide = presentation.slides.add_slide(layout)
                slide.shapes.title.text = title if index == 0 else f"{title} · {index + 1}"
                body = slide.placeholders[1].text_frame
                body.clear()
                for line in chunk.splitlines()[:16]:
                    paragraph = body.paragraphs[0] if not body.text else body.add_paragraph()
                    paragraph.text = line[:500]
                    paragraph.font.size = Pt(18)
            presentation.save(path)
    except ImportError as err:
        raise AgentToolError(f"The {kind} document writer is unavailable in this installation") from err
    except (OSError, ValueError, csv.Error) as err:
        raise AgentToolError(f"Could not create the requested document: {err}") from err
    return _record_artifact(context, path, kind)

async def image_backend_status() -> dict[str, Any]:
    timeout = aiohttp.ClientTimeout(total=2)
    for engine, base, check_path in (
        ("ComfyUI", "http://127.0.0.1:8188", "/object_info/CheckpointLoaderSimple"),
        ("Stable Diffusion WebUI", "http://127.0.0.1:7860", "/sdapi/v1/options"),
    ):
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(base + check_path) as response:
                    if response.status < 400:
                        return {"available": True, "engine": engine, "base_url": base}
        except (aiohttp.ClientError, asyncio.TimeoutError):
            continue
    return {"available": False, "engine": None, "base_url": None}

async def generate_local_image(
    context: AgentToolContext,
    prompt: str,
    width: int = 768,
    height: int = 768,
) -> dict[str, str]:
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 2000:
        raise AgentToolError("Image prompts must be between 1 and 2,000 characters")
    allowed_dimensions = {512, 640, 768, 896, 1024}
    if not isinstance(width, int) or isinstance(width, bool) or not isinstance(height, int) or isinstance(height, bool):
        raise AgentToolError("Image dimensions must be pixel numbers")
    if width not in allowed_dimensions or height not in allowed_dimensions:
        raise AgentToolError("Image dimensions must be one of 512, 640, 768, 896, or 1024 pixels")
    if context.image_count >= 2:
        raise AgentToolError("A task may generate at most two images")
    context.image_count += 1

    status = await image_backend_status()
    if not status["available"]:
        raise AgentToolError(
            "No local image-generation engine is running. Start ComfyUI on port 8188 or "
            "Stable Diffusion WebUI with its local API on port 7860; no image was sent to a cloud service."
        )
    if status["engine"] == "Stable Diffusion WebUI":
        image_bytes = await _generate_sd_image(status["base_url"], prompt, width, height)
    else:
        image_bytes = await _generate_comfy_image(status["base_url"], prompt, width, height)
    if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES or not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AgentToolError("The local image engine returned an invalid or oversized PNG")
    filename = f"image-{len(context.artifacts) + 1}.png"
    path = context.output_dir / filename
    with path.open("xb") as output:
        output.write(image_bytes)
    return _record_artifact(context, path, "image")

async def _generate_sd_image(base_url: str, prompt: str, width: int, height: int) -> bytes:
    timeout = aiohttp.ClientTimeout(total=180)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{base_url}/sdapi/v1/txt2img",
                json={
                    "prompt": prompt,
                    "width": width,
                    "height": height,
                    "steps": 20,
                    "batch_size": 1,
                    "n_iter": 1,
                },
            ) as response:
                if response.status >= 400:
                    raise AgentToolError(f"Local image engine returned HTTP {response.status}")
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > MAX_IMAGE_BYTES * 2:
                    raise AgentToolError("The local image engine returned an oversized response")
                raw = await response.content.read(MAX_IMAGE_BYTES * 2 + 1)
                if len(raw) > MAX_IMAGE_BYTES * 2:
                    raise AgentToolError("The local image engine returned an oversized response")
                result = json.loads(raw)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
        raise AgentToolError(f"Local Stable Diffusion image generation failed: {err}") from err
    images = result.get("images", [])
    if not images or not isinstance(images[0], str):
        raise AgentToolError("The local image engine did not return an image")
    import base64

    try:
        return base64.b64decode(images[0].split(",", 1)[-1], validate=True)
    except ValueError as err:
        raise AgentToolError("The local image engine returned invalid image data") from err

async def _generate_comfy_image(base_url: str, prompt: str, width: int, height: int) -> bytes:
    timeout = aiohttp.ClientTimeout(total=180, connect=5, sock_read=30)
    client_id = uuid.uuid4().hex
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{base_url}/object_info/CheckpointLoaderSimple") as response:
                response.raise_for_status()
                info = await response.json()
            checkpoints = (
                info.get("CheckpointLoaderSimple", {})
                .get("input", {})
                .get("required", {})
                .get("ckpt_name", [[]])[0]
            )
            if not checkpoints:
                raise AgentToolError("ComfyUI has no checkpoint model installed")
            workflow = {
                "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoints[0]}},
                "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
                "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["1", 1]}},
                "4": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
                "5": {"class_type": "KSampler", "inputs": {
                    "seed": int(time.time_ns() % (2**32)),
                    "steps": 20,
                    "cfg": 7,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1,
                    "model": ["1", 0],
                    "positive": ["2", 0],
                    "negative": ["3", 0],
                    "latent_image": ["4", 0],
                }},
                "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
                "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "pockpock-agent", "images": ["6", 0]}},
            }
            async with session.post(
                f"{base_url}/prompt",
                json={"prompt": workflow, "client_id": client_id},
            ) as response:
                if response.status >= 400:
                    detail = (await response.text())[:300]
                    raise AgentToolError(f"ComfyUI rejected the image workflow: {detail}")
                result = await response.json()
            prompt_id = result.get("prompt_id")
            if not isinstance(prompt_id, str):
                raise AgentToolError("ComfyUI did not return a workflow identifier")

            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                await asyncio.sleep(1)
                async with session.get(f"{base_url}/history/{prompt_id}") as response:
                    response.raise_for_status()
                    history = await response.json()
                outputs = history.get(prompt_id, {}).get("outputs", {})
                images = [
                    image
                    for node in outputs.values()
                    for image in node.get("images", [])
                    if isinstance(image.get("filename"), str)
                ]
                if not images:
                    continue
                image = images[0]
                async with session.get(
                    f"{base_url}/view",
                    params={
                        "filename": image["filename"],
                        "subfolder": image.get("subfolder", ""),
                        "type": image.get("type", "output"),
                    },
                ) as response:
                    response.raise_for_status()
                    data = await response.content.read(MAX_IMAGE_BYTES + 1)
                return data
    except AgentToolError:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
        raise AgentToolError(f"Local ComfyUI image generation failed: {err}") from err
    raise AgentToolError("ComfyUI image generation timed out after 3 minutes")
