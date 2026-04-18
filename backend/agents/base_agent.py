"""
BaseAgent — Foundation class for every AI agent in NIV AI.

Every agent (Behavioral, Validation, Presentation, Conversation,
ContextContinuity, DecisionSynthesizer, and all three Roundtable
personas) inherits from this class.

Routing logic:
    All agents use Groq (free tier, no credit card required).
    Two model tiers:
        FAST  — llama-3.1-8b-instant   (all agents except synthesizer)
        SMART — llama-3.3-70b-versatile (DecisionSynthesizer only)

    Fallback: if Groq is down or rate-limited, falls back to local
    Ollama automatically so development never hard-stops.

Setup:
    1. Sign up free at console.groq.com
    2. Create an API key (no credit card needed)
    3. Add to .env:  GROQ_API_KEY=gsk_xxxx
"""

import json
import asyncio
import httpx
import os
from tenacity import retry, stop_after_attempt, wait_exponential
from dotenv import load_dotenv
from typing import AsyncGenerator

load_dotenv()

# ─── Provider config ─────────────────────────────────────────────────────────
GROQ_API_KEY      = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL     = "https://api.groq.com/openai/v1/chat/completions"

# Fast model  — used by every agent except DecisionSynthesizer
# 14,400 free requests/day, ~500 tokens/sec
GROQ_FAST_MODEL   = os.getenv("GROQ_FAST_MODEL",  "llama-3.1-8b-instant")

# Smart model — used only by DecisionSynthesizer for the full audit report
# 1,000 free requests/day, better reasoning depth
GROQ_SMART_MODEL  = os.getenv("GROQ_SMART_MODEL", "llama-3.3-70b-versatile")

# Ollama fallback (already running locally — zero extra setup)
OLLAMA_BASE_URL   = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL      = os.getenv("OLLAMA_MODEL",    "llama3.1:8b")

# Set USE_OLLAMA=true in .env to force local Ollama (offline dev)
USE_OLLAMA        = os.getenv("USE_OLLAMA", "false").lower() == "true"
# ─────────────────────────────────────────────────────────────────────────────


class BaseAgent:

    def __init__(
        self,
        name: str,
        persona: str,
        system_prompt: str,
        use_smart_model: bool = False   # only DecisionSynthesizer sets True
    ):
        self.name             = name
        self.persona          = persona
        self.system_prompt    = system_prompt
        self.use_smart_model  = use_smart_model

        # Resolved at init so every call() knows which model to use
        self._groq_model = GROQ_SMART_MODEL if use_smart_model else GROQ_FAST_MODEL

    # -------------------------------------------------------------------------
    # Public call interface — all agents use this
    # -------------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def call(self, prompt: str) -> dict:
        """
        Send a prompt to Groq and return a parsed dict.
        Falls back to Ollama if USE_OLLAMA=true or if Groq fails.
        Retries up to 3 times with exponential backoff.
        """
        if USE_OLLAMA:
            return await self._call_ollama(prompt)

        try:
            return await self._call_groq(prompt)
        except Exception as e:
            print(f"[{self.name}] Groq failed ({e}), falling back to Ollama")
            return await self._call_ollama(prompt)

    # -------------------------------------------------------------------------
    # Groq path
    # -------------------------------------------------------------------------

    async def _call_groq(self, prompt: str) -> dict:
        """
        Call Groq API (OpenAI-compatible endpoint) and parse response as JSON.
        Uses the fast model by default, smart model for the synthesizer.
        On invalid JSON, retries once with a stricter formatting instruction.
        """
        if not GROQ_API_KEY:
            raise ValueError(
                "GROQ_API_KEY not set. Get a free key at console.groq.com"
            )

        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type":  "application/json"
        }

        payload = {
            "model": self._groq_model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user",   "content": prompt}
            ],
            "temperature": 0.1,
            "max_tokens":  2048,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                GROQ_BASE_URL,
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            data    = response.json()
            content = data["choices"][0]["message"]["content"]

        # First parse attempt
        try:
            return self._parse_json(content)
        except ValueError:
            # Second attempt — append strict JSON instruction
            strict_prompt = (
                prompt
                + "\n\nCRITICAL: Your previous response contained invalid JSON. "
                "Respond with ONLY a raw JSON object. "
                "Start with { and end with }. "
                "No markdown, no backticks, no explanation, nothing outside the JSON."
            )
            payload["messages"][1]["content"] = strict_prompt

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    GROQ_BASE_URL,
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                data    = response.json()
                content = data["choices"][0]["message"]["content"]

            return self._parse_json(content)

    # -------------------------------------------------------------------------
    # Ollama fallback path (unchanged from original)
    # -------------------------------------------------------------------------

    async def _call_ollama(self, prompt: str) -> dict:
        """
        Call local Ollama server. Used as fallback or when USE_OLLAMA=true.
        """
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user",   "content": prompt}
                    ],
                    "stream":  False,
                    "options": {
                        "temperature": 0.1,
                        "num_predict": 2048
                    }
                }
            )
            response.raise_for_status()
            data = response.json()
            return self._parse_json(data["message"]["content"])

    # -------------------------------------------------------------------------
    # Streaming — used by roundtable DiscussionEngine
    # -------------------------------------------------------------------------

    async def stream_call(self, prompt: str) -> AsyncGenerator[str, None]:
        """
        Streaming variant for the live roundtable WebSocket feed.
        Groq supports real token streaming via SSE.
        Falls back to Ollama streaming if USE_OLLAMA=true.
        """
        if USE_OLLAMA:
            async for chunk in self._stream_ollama(prompt):
                yield chunk
        else:
            async for chunk in self._stream_groq(prompt):
                yield chunk

    async def _stream_groq(self, prompt: str) -> AsyncGenerator[str, None]:
        """
        Real token streaming from Groq via Server-Sent Events.
        Groq is fast enough (~500 tok/sec) that streaming feels live.
        """
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type":  "application/json"
        }
        payload = {
            "model": self._groq_model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user",   "content": prompt}
            ],
            "temperature": 0.1,
            "max_tokens":  2048,
            "stream":      True
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                GROQ_BASE_URL,
                headers=headers,
                json=payload
            ) as response:
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[len("data: "):]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        chunk   = json.loads(data_str)
                        delta   = chunk["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except (json.JSONDecodeError, KeyError):
                        continue

    async def _stream_ollama(self, prompt: str) -> AsyncGenerator[str, None]:
        """Real token streaming from local Ollama server."""
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream(
                "POST",
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user",   "content": prompt}
                    ],
                    "stream": True
                }
            ) as response:
                async for line in response.aiter_lines():
                    if line:
                        try:
                            chunk = json.loads(line)
                            if chunk.get("message", {}).get("content"):
                                yield chunk["message"]["content"]
                        except json.JSONDecodeError:
                            continue

    # -------------------------------------------------------------------------
    # Prompt builder — shared by all agents (unchanged)
    # -------------------------------------------------------------------------

    def build_prompt(self, context: dict, task: str) -> str:
        """
        Builds the full prompt string sent to the LLM.
        Context serialised to indented JSON for readability.
        Closing instruction reinforces JSON-only output — critical for
        smaller models which tend to add conversational wrapping.
        """
        context_str = json.dumps(context, indent=2, default=str)
        return (
            f"CONTEXT:\n{context_str}\n\n"
            f"TASK:\n{task}\n\n"
            f"Respond only in valid JSON. "
            f"No markdown fences, no explanation, no text outside the JSON. "
            f"Start your response with {{ and end with }}."
        )

    # -------------------------------------------------------------------------
    # JSON parser — shared by all agents (unchanged, proven working)
    # -------------------------------------------------------------------------

    def _parse_json(self, raw: str) -> dict:
        """
        Robustly parse a JSON object from raw LLM output.
        Handles four failure modes:
        1. Model thinking blocks in <think> tags
        2. Markdown code fences
        3. Leading prose before opening brace
        4. Trailing text after closing brace
        """
        cleaned = raw.strip()

        # Strip thinking blocks (some local models emit these)
        if "<think>" in cleaned and "</think>" in cleaned:
            cleaned = cleaned[cleaned.index("</think>") + len("</think>"):].strip()

        # Strip markdown fences
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        # Skip leading prose
        if not cleaned.startswith("{"):
            start = cleaned.find("{")
            if start != -1:
                cleaned = cleaned[start:]

        # Trim trailing text
        end = cleaned.rfind("}")
        if end != -1:
            cleaned = cleaned[:end + 1]

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"[{self.name}] Invalid JSON from LLM after cleaning: {e}\n"
                f"First 500 chars of raw: {raw[:500]}"
            )

    # -------------------------------------------------------------------------
    # Blackboard helper — shared by all agents (unchanged)
    # -------------------------------------------------------------------------

    def extract_blackboard_context(self, blackboard: dict, keys: list) -> dict:
        """
        Pull only the requested keys from the full blackboard dict.
        Keeps prompts lean — agents only see data they need.
        """
        return {
            k: blackboard.get(k)
            for k in keys
            if blackboard.get(k) is not None
        }