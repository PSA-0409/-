"""英→日翻訳（claude / deepl / none）."""

from __future__ import annotations

import requests


class Translator:
    def __init__(self, engine: str = "none", anthropic_api_key: str = "", deepl_api_key: str = ""):
        self.engine = (engine or "none").lower()
        self.anthropic_api_key = anthropic_api_key
        self.deepl_api_key = deepl_api_key

    def translate(self, text: str, max_chars: int = 300) -> str:
        if not text:
            return ""

        if self.engine == "none":
            return text[:max_chars]
        if self.engine == "deepl":
            return self._translate_deepl(text, max_chars)
        if self.engine == "claude":
            return self._translate_claude(text, max_chars)
        return text[:max_chars]

    def _translate_deepl(self, text: str, max_chars: int) -> str:
        if not self.deepl_api_key:
            return text[:max_chars]
        truncated = text[:1500]
        try:
            response = requests.post(
                "https://api-free.deepl.com/v2/translate",
                data={
                    "auth_key": self.deepl_api_key,
                    "text": truncated,
                    "target_lang": "JA",
                },
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            translated = data.get("translations", [{}])[0].get("text", "")
            return translated[:max_chars] if translated else text[:max_chars]
        except Exception:
            return text[:max_chars]

    def _translate_claude(self, text: str, max_chars: int) -> str:
        if not self.anthropic_api_key:
            return text[:max_chars]

        truncated = text[:1500]
        prompt = (
            "以下のプレスリリースのタイトルまたは本文を日本語に翻訳・要約してください。\n"
            "- 投資家向けの重要情報を優先する\n"
            f"- {max_chars}文字以内に収める\n"
            "- 数値・固有名詞はそのまま使用する\n"
            "- 余計な前置きは不要、翻訳結果のみ出力する\n\n"
            f"原文:\n{truncated}"
        )

        try:
            import anthropic

            client = anthropic.Anthropic(api_key=self.anthropic_api_key)
            message = client.messages.create(
                model="claude-3-5-haiku-latest",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            if not message.content:
                return text[:max_chars]
            return message.content[0].text.strip()[:max_chars]
        except Exception:
            return text[:max_chars]
