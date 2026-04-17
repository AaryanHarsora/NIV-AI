import json
import asyncio
import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential
from dotenv import load_dotenv
import os
from typing import AsyncGenerator

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))


class BaseAgent:

    def __init__(self, name: str, persona: str, system_prompt: str):
        # Agent name used in roundtable messages eg Aryan Priya Dr. Mehta
        self.name = name
        # Short description of who this agent is
        self.persona = persona
        # Full system prompt defining behavior and output format
        self.system_prompt = system_prompt
        # Always use gemini-2.0-flash
        self.model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            system_instruction=self.system_prompt
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def call(self, prompt: str) -> dict:
        # Sends prompt to Gemini and returns parsed JSON dict
        # Retries up to 3 times on failure with exponential backoff
        response = await asyncio.to_thread(
            self.model.generate_content,
            prompt
        )
        return self._parse_json(response.text)

    async def stream_call(self, prompt: str) -> AsyncGenerator[str, None]:
        # Streams response from Gemini chunk by chunk
        # Used by discussion engine for live roundtable streaming
        response = await asyncio.to_thread(
            self.model.generate_content,
            prompt,
            stream=True
        )
        for chunk in response:
            if chunk.text:
                yield chunk.text

    def build_prompt(self, context: dict, task: str) -> str:
        # Formats context and task into a clean prompt
        # Only passes relevant context keys to keep token count low
        context_str = json.dumps(context, indent=2, default=str)
        return f"CONTEXT:\n{context_str}\n\nTASK:\n{task}\n\nRespond only in valid JSON."

    def _parse_json(self, raw: str) -> dict:
        # Strips markdown fences if present and parses JSON
        # Raises ValueError if response is not valid JSON after cleanup
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # Remove opening fence
            lines = lines[1:]
            # Remove closing fence
            if lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Agent {self.name} returned invalid JSON: {e}\nRaw: {raw[:300]}"
            )

    def extract_blackboard_context(
        self, blackboard: dict, keys: list
    ) -> dict:
        # Extracts only the specified keys from the blackboard
        # Keeps prompts focused and token-efficient
        return {k: blackboard.get(k) for k in keys if blackboard.get(k) is not None}