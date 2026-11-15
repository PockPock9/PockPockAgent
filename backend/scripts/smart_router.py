"""Smart Router: picks a local Ollama model for each request.

Originally an Open WebUI pipe; now used only by the PockPock gateway. Next-generation cognitive router. Features multi-turn context awareness, fast heuristic intent gating, dynamic hyperparameter morphing (temperature/top_p), specialized system prompt injection, and automated circuit-breaker fallbacks across 12 local Ollama models.
"""

from pydantic import BaseModel, Field
from typing import Optional, AsyncGenerator, List, Dict, Any
import json
import re
import aiohttp
import asyncio
import logging
import time
import uuid


logger = logging.getLogger(__name__)


class Pipe:
    """
    Ultra-Intelligent Cognitive Router Pipe for Open WebUI.
    Dynamically orchestrates local LLM execution based on semantic intent,
    conversational trajectory, complexity scoring, and hardware optimization.
    """

    class Valves(BaseModel):
        """Dynamic configuration controllable from Open WebUI admin panel."""
        router_model: str = Field(
            default="qwen2.5:1.5b",
            description="Ultra-fast micro-model for semantic query classification"
        )
        code_model: str = Field(
            default="qwen2.5-coder:7b",
            description="Fast specialist for everyday programming, debugging, and scripts"
        )
        heavy_code_model: str = Field(
            default="qwen2.5-coder:14b",
            description="State-of-the-art specialist for complex code architecture, CI/CD pipelines, and DevOps manifests"
        )
        reasoning_model: str = Field(
            default="deepseek-r1:14b",
            description="Specialist for complex logic, math, multi-step deduction, and formal proofs"
        )
        general_model: str = Field(
            default="qwen2.5:14b",
            description="High-capacity generalist for deep writing, nuance, analysis, and synthesis"
        )
        quick_model: str = Field(
            default="qwen2.5:7b",
            description="Low-latency conversationalist for quick lookups, trivia, definitions, and short Q&A"
        )
        vision_model: str = Field(
            default="llava:7b",
            description="Multimodal model for images, screenshots, OCR, diagrams, and visual queries"
        )
        agentic_model: str = Field(
            default="mistral-nemo:12b",
            description="Specialist for tool execution, structured function calling, and automated workflows"
        )
        uncensored_model: str = Field(
            default="dolphin-mistral:7b",
            description="Unfiltered model for creative fiction, boundary-testing, and unconstrained generation"
        )
        show_telemetry_hud: bool = Field(
            default=True,
            description="Render expandable HUD displaying routing confidence, intent classification, and tuned parameters"
        )
        enable_dynamic_parameter_morphing: bool = Field(
            default=True,
            description="Automatically tune temperature and top_p per task type"
        )
        enable_system_prompt_enhancement: bool = Field(
            default=True,
            description="Inject specialized cognitive directives tailored to each model's strengths"
        )
        ollama_base_url: str = Field(
            default="http://localhost:11434",
            description="Base URL for the local Ollama instance"
        )
        dashboard_base_url: str = Field(
            default="http://127.0.0.1:8765",
            description="Optional local observability dashboard; ignored when it is not running"
        )

    def __init__(self, model_client: Optional[Any] = None):
        self.valves = self.Valves()
        self._dashboard_available = False
        self._dashboard_event_lock = asyncio.Lock()
        self.model_client = model_client

    def pipes(self) -> List[Dict[str, str]]:
        """Registers as a unified model in Open WebUI dropdown."""
        return [
            {
                "id": "ultra-smart-router",
                "name": "🧠 Ultra-Smart Router (Cognitive AI Dispatcher)",
            }
        ]

    def _queue_dashboard_event(self, event: Dict[str, Any]) -> None:
        event["timestamp"] = time.time()
        try:
            asyncio.create_task(self._send_dashboard_event(event))
        except RuntimeError as err:
            logger.debug("Dashboard telemetry was not queued: %s", err)

    async def _send_dashboard_event(self, event: Dict[str, Any]) -> None:
        try:
            timeout = aiohttp.ClientTimeout(total=0.15)
            async with self._dashboard_event_lock:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        f"{self.valves.dashboard_base_url}/api/events",
                        json=event,
                    ) as response:
                        response.raise_for_status()
            self._dashboard_available = True
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            self._dashboard_available = False
            logger.debug("Optional dashboard telemetry unavailable: %s", err)

    async def _dashboard_override(self) -> Optional[str]:
        try:
            timeout = aiohttp.ClientTimeout(total=0.2)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    f"{self.valves.dashboard_base_url}/api/override",
                ) as response:
                    response.raise_for_status()
                    result = await response.json()
                    self._dashboard_available = True
                    model = result.get("model")
                    return model if isinstance(model, str) and model else None
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            self._dashboard_available = False
            logger.debug("Optional dashboard override unavailable: %s", err)
            return None

    async def _complete_dashboard_event(self, event: Dict[str, Any]) -> None:
        if self._dashboard_available:
            await self._send_dashboard_event(event)
        else:
            self._queue_dashboard_event(event)

    # --- STAGE 1: ULTRA-FAST HEURISTIC GATING (<5ms) ---
    def _heuristic_check(self, text: str, messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Instant pattern analyzer for unambiguous intents to eliminate routing latency.
        """
        # Complex CI/CD, DevOps & Infrastructure patterns
        devops_patterns = [
            r"\b(github actions|gitlab-ci|\.github/workflows|dockerfile|docker-compose|k8s|kubernetes|helm chart|terraform|jenkinsfile|ci/cd|cicd pipeline)\b",
        ]
        if any(re.search(p, text, re.IGNORECASE) for p in devops_patterns):
            return {
                "category": "code",
                "reason": "High-complexity CI/CD, DevOps, or Infrastructure manifest detected",
                "confidence": 0.98,
                "complexity": 9,
                "model": self.valves.heavy_code_model,
            }

        # Multimodal / Vision check: check for image attachments or image URLs
        for msg in messages:
            if "images" in msg and msg["images"]:
                return {
                    "category": "vision",
                    "reason": "Multimodal image payload detected in prompt context",
                    "confidence": 1.0,
                    "complexity": 7,
                    "model": self.valves.vision_model,
                }

        # LaTeX / Math Proof check
        math_patterns = [
            r"\\(frac|sum|int|sqrt|partial|infty|alpha|beta|theta|lambda)\b",
            r"\b(prove that|proof by induction|qed|eigenvalue|diophantine|isomorphism|calculus|differential equation)\b",
        ]
        if any(re.search(p, text, re.IGNORECASE) for p in math_patterns):
            return {
                "category": "reasoning",
                "reason": "High-density mathematical proof or formal logic pattern detected",
                "confidence": 0.95,
                "complexity": 9,
                "model": self.valves.reasoning_model,
            }

        # Code block / Stack trace / Syntactic check
        code_patterns = [
            r"```[\w]*\n",
            r"\b(def |class |public static void|fn main|#include|import React|SELECT .* FROM|docker-compose|traceback|syntaxerror)\b",
            r"\b(git commit|k8s|kubernetes|npm install|cargo build|pip install)\b",
        ]
        if any(re.search(p, text, re.IGNORECASE) for p in code_patterns):
            return {
                "category": "code",
                "reason": "Syntax elements, code block, or programming symbols identified",
                "confidence": 0.96,
                "complexity": 7,
                "model": self.valves.code_model,
            }

        # Quick conversational & simple lookups check (< 45 chars, common conversational openings)
        quick_patterns = [
            r"^(hi|hello|hey|good morning|good evening|howdy|what's up)\b",
            r"^(who is|what is (the )?|what does .* mean|define |when was|where is)\b",
        ]
        if len(text.strip()) < 60 and any(re.search(p, text, re.IGNORECASE) for p in quick_patterns):
            # Ensure it doesn't contain code or math keywords
            if not any(k in text.lower() for k in ["code", "function", "formula", "proof", "prove", "solve", "algorithm", "python", "rust"]):
                return {
                    "category": "quick",
                    "reason": "Direct factual lookup or conversational greeting pattern identified",
                    "confidence": 0.98,
                    "complexity": 1,
                    "model": self.valves.quick_model,
                }

        return None

    # --- STAGE 2: MULTI-TURN CONTEXT DISTILLATION & DEEP CLASSIFIER ---
    async def _deep_classify(
        self,
        messages: List[Dict[str, Any]],
        request_id: str,
    ) -> Dict[str, Any]:
        """
        Multi-turn cognitive classifier. Analyzes current intent in the context of recent chat history.
        """
        # Distill recent conversation context (up to last 3 messages)
        recent_turns = []
        for msg in messages[-3:]:
            role = msg.get("role", "user")
            content = str(msg.get("content", ""))[:300]
            recent_turns.append(f"{role.upper()}: {content}")
        context_block = "\n".join(recent_turns)

        latest_query = messages[-1].get("content", "")

        classification_prompt = f"""You are a master AI dispatcher. Analyze the conversation history and the latest user query.
Classify the user's intent into EXACTLY ONE category and assess task complexity.

Categories:
- "code": Programming, debugging, architecture, refactoring, algorithms, SQL, shell scripts, APIs.
- "reasoning": Complex math, logic puzzles, step-by-step analytical deductions, philosophical proofs, hard science.
- "agentic": Automated action plans, function calling, tool use, executing multi-step workflows, web scraping.
- "vision": Visual descriptions, diagram analysis, image questions, OCR.
- "uncensored": Creative fiction, jailbreak tests, unconstrained roleplay, controversial/sensitive topics.
- "general": Deep essays, long explanations, structured articles, professional correspondence, nuanced synthesis.
- "quick": Simple factual lookups (e.g. capitals, dates, definitions), basic translations, greetings, short everyday Q&A.

Examples:
- "What is the capital of France?" -> {{"category": "quick", "confidence": 0.99, "complexity": 1, "reason": "Simple factual geographical lookup."}}
- "Write a quicksort in C++" -> {{"category": "code", "confidence": 0.98, "complexity": 5, "reason": "Algorithm implementation in C++."}}
- "Prove that there are infinitely many primes" -> {{"category": "reasoning", "confidence": 0.98, "complexity": 8, "reason": "Mathematical theorem proof."}}
- "Plan an automated script to back up files every midnight" -> {{"category": "agentic", "confidence": 0.95, "complexity": 6, "reason": "Automated workflow and scripting."}}

Conversation Context:
{context_block}

Latest Query: "{latest_query}"

Respond with ONLY a JSON object:
{{
  "category": "chosen_category",
  "confidence": 0.95,
  "complexity": 5,
  "reason": "tactical explanation"
}}"""

        call_id = uuid.uuid4().hex
        call_started = time.monotonic()
        self._queue_dashboard_event({
            "event": "model_call_started",
            "request_id": request_id,
            "call_id": call_id,
            "model": self.valves.router_model,
            "role": "classifier",
        })
        classifier_status = "success"
        classifier_error = ""
        try:
            model_client = getattr(self, "model_client", None)
            if model_client is not None:
                from projects.model_router import ChatCompletionRequest

                result = await model_client.complete(
                    ChatCompletionRequest(
                        model=self.valves.router_model,
                        messages=[{"role": "user", "content": classification_prompt}],
                        temperature=0.05,
                        max_tokens=120,
                        response_format={"type": "json_object"},
                    ),
                    timeout=aiohttp.ClientTimeout(total=30),
                )
                raw = result["choices"][0]["message"]["content"].strip()
            else:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{self.valves.ollama_base_url}/api/generate",
                        json={
                            "model": self.valves.router_model,
                            "prompt": classification_prompt,
                            "stream": False,
                            "options": {"temperature": 0.05, "num_predict": 120},
                        },
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as resp:
                        if resp.status != 200:
                            classifier_status = "error"
                            classifier_error = f"HTTP {resp.status}"
                        result = await resp.json()
                        raw = result.get("response", "").strip()

            # Extract JSON payload safely
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                parsed = json.loads(match.group())
                raw_cat = str(parsed.get("category", "general")).lower()
                valid_cats = ["code", "reasoning", "agentic", "vision", "uncensored", "general", "quick"]
                cat = next((c for c in valid_cats if c in raw_cat), "general")
                conf = float(parsed.get("confidence", 0.9))
                comp = int(parsed.get("complexity", 5))
                reason = parsed.get("reason", "Semantic classification applied.")
            else:
                cat, conf, comp, reason = "general", 0.75, 5, "Fallback classification default."
        except Exception as e:
            classifier_status = "error"
            classifier_error = str(e)
            logger.warning("Semantic routing classification failed: %s", e)
            cat, conf, comp, reason = "general", 0.50, 5, f"Router classification timeout ({e}), using default."
        finally:
            await self._complete_dashboard_event({
                "event": "model_call_completed",
                "request_id": request_id,
                "call_id": call_id,
                "model": self.valves.router_model,
                "role": "classifier",
                "status": classifier_status,
                "error": classifier_error[:240],
                "duration_ms": round((time.monotonic() - call_started) * 1000),
            })

        # Map to designated model valve (with intelligent tiering for code complexity)
        if cat == "code" and comp >= 7:
            selected_model = self.valves.heavy_code_model
        else:
            model_map = {
                "code": self.valves.code_model,
                "reasoning": self.valves.reasoning_model,
                "agentic": self.valves.agentic_model,
                "vision": self.valves.vision_model,
                "uncensored": self.valves.uncensored_model,
                "general": self.valves.general_model,
                "quick": self.valves.quick_model,
            }
            selected_model = model_map.get(cat, self.valves.general_model)

        return {
            "category": cat,
            "confidence": conf,
            "complexity": comp,
            "reason": reason,
            "model": selected_model,
        }

    # --- STAGE 3: COGNITIVE SYSTEM PROMPT & PARAMETER MORPHING ---
    def _tune_execution_parameters(self, category: str, complexity: int) -> Dict[str, Any]:
        """
        Dynamically adapts generation parameters (temperature, top_p) and injects specialized cognitive personas.
        """
        profiles = {
            "code": {
                "temperature": 0.15,
                "top_p": 0.90,
                "system_directive": (
                    "You are a Principal Software Engineer. Write production-ready, clean, idiomatic code with "
                    "thorough type hints, edge-case coverage, and concise architectural comments. Avoid fluff."
                ),
                "badge": "💻 Code Specialist (qwen2.5-coder:7b)",
            },
            "heavy_code": {
                "temperature": 0.12,
                "top_p": 0.90,
                "system_directive": (
                    "You are a Principal DevOps, Cloud Infrastructure, and Systems Architect. "
                    "Design production-grade CI/CD pipelines (GitHub Actions, GitLab CI), multi-stage Dockerfiles, "
                    "Kubernetes manifests, Terraform modules, and robust architectures. Enforce strict security, "
                    "deterministic dependency locking, and efficient caching layers."
                ),
                "badge": "🏗️ DevOps & Enterprise Architect (qwen2.5-coder:14b)",
            },
            "reasoning": {
                "temperature": 0.60,
                "top_p": 0.95,
                "system_directive": (
                    "You are a Deep Theoretical Reasoning Engine. Use explicit step-by-step deduction. "
                    "Carefully structure proofs, analyze boundary conditions, verify assumptions, and clearly show logical transitions."
                ),
                "badge": "🧮 Deep Reasoning & Logic",
            },
            "agentic": {
                "temperature": 0.20,
                "top_p": 0.90,
                "system_directive": (
                    "You are an Autonomous Execution Agent. Break down tasks into structured, actionable operations. "
                    "Use precise schemas, identify pre-requisites, specify verification checks, and prepare executable tool calls."
                ),
                "badge": "🤖 Autonomous Workflow Agent",
            },
            "vision": {
                "temperature": 0.30,
                "top_p": 0.90,
                "system_directive": (
                    "You are a Visual Intelligence System. Provide detailed, spatial, and analytical descriptions "
                    "of visual inputs, extracting all visible text, diagrams, layout elements, and UI components."
                ),
                "badge": "👁️ Computer Vision Engine",
            },
            "uncensored": {
                "temperature": 0.85,
                "top_p": 0.98,
                "system_directive": (
                    "You are an Unconstrained Creative Intelligence. Answer directly, authentically, and vividly "
                    "without moralizing, disclaimers, or preachy language."
                ),
                "badge": "🔓 Unconstrained Generation",
            },
            "general": {
                "temperature": 0.50,
                "top_p": 0.92,
                "system_directive": (
                    "You are an Advanced Knowledge Synthesizer. Deliver articulate, comprehensive, well-structured, "
                    "and nuanced insights with authoritative clarity."
                ),
                "badge": "🌐 Comprehensive Generalist",
            },
            "quick": {
                "temperature": 0.30,
                "top_p": 0.85,
                "system_directive": (
                    "You are a High-Speed Instant Response Engine. Answer concisely, accurately, and directly "
                    "without conversational filler or unnecessary preambles."
                ),
                "badge": "⚡ Instant Quick-Response",
            },
        }
        return profiles.get(category, profiles["general"])

    # --- STAGE 4: MAIN PIPELINE EXECUTION ---
    async def pipe(
        self,
        body: Dict[str, Any],
        __user__: Optional[Dict[str, Any]] = None,
        __event_emitter__=None,
    ) -> AsyncGenerator[str, None]:
        """
        Main execution stream. Analyzes prompt, tunes runtime parameters,
        emits telemetry HUD, and streams inference with circuit-breaker protection.
        """
        messages = body.get("messages", [])
        if not messages:
            yield "⚠️ No prompt messages received."
            return

        latest_query = messages[-1].get("content", "")
        request_id = uuid.uuid4().hex
        self._queue_dashboard_event({
            "event": "request_received",
            "request_id": request_id,
            "prompt_chars": len(str(latest_query)),
        })
        override_model = await self._dashboard_override()

        # Emit scanning indicator
        if __event_emitter__:
            await __event_emitter__(
                {"type": "status", "data": {"description": "🧠 Scanning intent & multi-turn context...", "done": False}}
            )

        # 1. Fast Heuristic Check
        decision = self._heuristic_check(latest_query, messages)
        decision_source = "heuristic" if decision else "semantic"

        # 2. Deep LLM Semantic Classification (if heuristic didn't trigger)
        if not decision:
            decision = await self._deep_classify(messages, request_id)

        # A dashboard override affects only requests routed after it is selected.
        automatic_model = decision["model"]
        if override_model:
            decision["model"] = override_model
            decision_source = "manual"

        self._queue_dashboard_event({
            "event": "route_decision",
            "request_id": request_id,
            "model": decision["model"],
            "automatic_model": automatic_model,
            "category": decision["category"],
            "source": decision_source,
            "reason": str(decision.get("reason", ""))[:240],
            "confidence": decision.get("confidence"),
            "complexity": decision.get("complexity"),
        })

        # 3. Parameter & Persona Morphing
        profile_key = "heavy_code" if decision.get("model") == self.valves.heavy_code_model else decision["category"]
        profile = self._tune_execution_parameters(profile_key, decision.get("complexity", 5))

        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": f"🎯 Dispatched to {decision['model']} ({profile['badge']})",
                        "done": True,
                    },
                }
            )

        # 4. Render Telemetry HUD
        if self.valves.show_telemetry_hud:
            confidence_pct = int(decision.get("confidence", 0.9) * 100)
            complexity = decision.get("complexity", 5)
            hud = f"""<details>
<summary>🧭 <b>Router Intelligence:</b> <code>{decision['model']}</code> · {profile['badge']} (Confidence: {confidence_pct}% | Complexity: {complexity}/10)</summary>

| Metric | Valuation |
| :--- | :--- |
| **Target Model** | `{decision['model']}` |
| **Classification** | **{decision['category'].upper()}** — *{decision['reason']}* |
| **Dynamic Tuning** | Temperature: `{profile['temperature']}` · Top-P: `{profile['top_p']}` |
| **Cognitive Directive** | *{profile['system_directive'][:110]}...* |

</details>

"""
            yield hud

        # 5. Prepare Enhanced Payload
        adjusted_messages = list(messages)
        if self.valves.enable_system_prompt_enhancement:
            # Check if system message already exists; if so, append directive
            has_system = False
            for m in adjusted_messages:
                if m.get("role") == "system":
                    m["content"] = f"{m.get('content', '')}\n\n[DIRECTIVE]: {profile['system_directive']}"
                    has_system = True
                    break
            if not has_system:
                adjusted_messages.insert(0, {"role": "system", "content": profile["system_directive"]})

        payload = {
            "model": decision["model"],
            "messages": adjusted_messages,
            "stream": True,
            "options": {
                "temperature": profile["temperature"] if self.valves.enable_dynamic_parameter_morphing else 0.7,
                "top_p": profile["top_p"] if self.valves.enable_dynamic_parameter_morphing else 0.9,
            },
        }

        # 6. Stream with Automated Circuit-Breaker Fallback
        success = False
        primary_call_id = uuid.uuid4().hex
        primary_started = time.monotonic()
        primary_error = ""
        self._queue_dashboard_event({
            "event": "model_call_started",
            "request_id": request_id,
            "call_id": primary_call_id,
            "model": decision["model"],
            "role": "response",
        })
        try:
            if self.model_client is not None:
                from projects.model_router import ChatCompletionRequest

                request = ChatCompletionRequest(
                    model=decision["model"],
                    messages=adjusted_messages,
                    temperature=payload["options"]["temperature"],
                    top_p=payload["options"]["top_p"],
                )
                async for token in self.model_client.stream_tokens(
                    request,
                    timeout=aiohttp.ClientTimeout(total=400),
                ):
                    yield token
                success = True
            else:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{self.valves.ollama_base_url}/api/chat",
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=400),
                    ) as resp:
                        if resp.status == 200:
                            async for line in resp.content:
                                line = line.strip()
                                if not line:
                                    continue
                                try:
                                    chunk = json.loads(line)
                                    token = chunk.get("message", {}).get("content", "")
                                    if token:
                                        yield token
                                except json.JSONDecodeError:
                                    continue
                            success = True
                        else:
                            primary_error = f"HTTP {resp.status}"
                            yield f"\n\n> ⚠️ *Primary target `{decision['model']}` returned HTTP {resp.status}. Activating fallback...*\n\n"
        except Exception as err:
            primary_error = str(err)
            yield f"\n\n> ⚠️ *Encountered execution interruption on `{decision['model']}` ({err}). Engaging failover...*\n\n"
        finally:
            await self._complete_dashboard_event({
                "event": "model_call_completed",
                "request_id": request_id,
                "call_id": primary_call_id,
                "model": decision["model"],
                "role": "response",
                "status": "success" if success else "error",
                "error": primary_error[:240],
                "duration_ms": round((time.monotonic() - primary_started) * 1000),
            })

        # 7. Fallback Cascade if primary failed
        if not success:
            fallback_model = self.valves.general_model
            fallback_call_id = uuid.uuid4().hex
            fallback_started = time.monotonic()
            fallback_status = "error"
            fallback_error = ""
            self._queue_dashboard_event({
                "event": "model_call_started",
                "request_id": request_id,
                "call_id": fallback_call_id,
                "model": fallback_model,
                "role": "fallback",
            })
            try:
                payload["model"] = fallback_model
                if self.model_client is not None:
                    from projects.model_router import ChatCompletionRequest

                    request = ChatCompletionRequest(
                        model=fallback_model,
                        messages=adjusted_messages,
                        temperature=payload["options"]["temperature"],
                        top_p=payload["options"]["top_p"],
                    )
                    async for token in self.model_client.stream_tokens(
                        request,
                        timeout=aiohttp.ClientTimeout(total=300),
                    ):
                        yield token
                    fallback_status = "success"
                else:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            f"{self.valves.ollama_base_url}/api/chat",
                            json=payload,
                            timeout=aiohttp.ClientTimeout(total=300),
                        ) as resp:
                            if resp.status == 200:
                                fallback_status = "success"
                            else:
                                fallback_error = f"HTTP {resp.status}"
                            async for line in resp.content:
                                line = line.strip()
                                if not line:
                                    continue
                                try:
                                    chunk = json.loads(line)
                                    token = chunk.get("message", {}).get("content", "")
                                    if token:
                                        yield token
                                except json.JSONDecodeError:
                                    continue
            except Exception as fallback_err:
                fallback_error = str(fallback_err)
                yield f"\n\n❌ All model cascades failed: {fallback_err}"
            finally:
                await self._complete_dashboard_event({
                    "event": "model_call_completed",
                    "request_id": request_id,
                    "call_id": fallback_call_id,
                    "model": fallback_model,
                    "role": "fallback",
                    "status": fallback_status,
                    "error": fallback_error[:240],
                    "duration_ms": round((time.monotonic() - fallback_started) * 1000),
                })
