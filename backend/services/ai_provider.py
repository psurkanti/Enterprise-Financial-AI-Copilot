from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore

try:
    import google.generativeai as genai
except Exception:  # pragma: no cover
    genai = None  # type: ignore


class AIProviderRouter:
    """OpenAI-first provider router with Gemini fallback."""

    def __init__(self) -> None:
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
        self._openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        self._gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        self._openai = OpenAI(api_key=self._openai_key) if (self._openai_key and OpenAI) else None
        if self._gemini_key and genai:
            try:
                genai.configure(api_key=self._gemini_key)
                self._gemini = genai.GenerativeModel(self.gemini_model)
            except Exception:
                self._gemini = None
        else:
            self._gemini = None

    def available(self) -> bool:
        return self._openai is not None or self._gemini is not None

    def complete_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 300,
    ) -> str:
        text = self._openai_complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if text:
            return text
        return self._gemini_complete(system_prompt=system_prompt, user_prompt=user_prompt)

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 500,
    ) -> Dict[str, Any]:
        raw = self.complete_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except Exception:
            # Try to recover JSON object if wrapped in markdown/code fences.
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(raw[start : end + 1])
                except Exception:
                    return {}
            return {}

    def _openai_complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        if not self._openai:
            return ""
        try:
            completion = self._openai.chat.completions.create(
                model=self.openai_model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return (completion.choices[0].message.content or "").strip()
        except Exception:
            return ""

    def _gemini_complete(self, *, system_prompt: str, user_prompt: str) -> str:
        if not self._gemini:
            return ""
        try:
            prompt = f"{system_prompt}\n\n{user_prompt}"
            resp = self._gemini.generate_content(prompt)
            return (getattr(resp, "text", "") or "").strip()
        except Exception:
            return ""
