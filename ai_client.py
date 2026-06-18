"""Bir nechta AI provayder: Claude, Groq, Mistral. Kalitlar/modellar sozlamalardan.

Har bir provayder bir xil promptdan foydalanadi va {yumor, aqlli, bahsli} qaytaradi.
"""
import json

import settings
import claude_client
from prompts import SYSTEM_PROMPT, build_user_prompt, JSON_INSTRUCTION

_REQUIRED_KEYS = ("yumor", "aqlli", "bahsli")


def available_providers() -> list[dict]:
    """Aktiv (kaliti bor) provayderlar ro'yxati."""
    provs = []
    if settings.get("anthropic_api_key"):
        provs.append({"id": "claude", "name": "Claude", "model": settings.get("claude_model")})
    if settings.get("groq_api_key"):
        provs.append({"id": "groq", "name": "Groq", "model": settings.get("groq_model")})
    if settings.get("mistral_api_key"):
        provs.append({"id": "mistral", "name": "Mistral", "model": settings.get("mistral_model")})
    return provs


def _normalize(data: dict) -> dict:
    result = {k: str(data.get(k, "")).strip() for k in _REQUIRED_KEYS}
    if not any(result.values()):
        raise RuntimeError("AI javobida kutilgan maydonlar topilmadi.")
    return result


def _mistral_client(api_key: str):
    try:
        from mistralai import Mistral
    except ImportError:
        from mistralai.client import Mistral
    return Mistral(api_key=api_key)


def _generate_groq(description: str) -> dict:
    from groq import Groq

    client = Groq(api_key=settings.get("groq_api_key"))
    resp = client.chat.completions.create(
        model=settings.get("groq_model"),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(description) + JSON_INSTRUCTION},
        ],
        response_format={"type": "json_object"},
    )
    return _normalize(json.loads(resp.choices[0].message.content))


def _generate_mistral(description: str) -> dict:
    client = _mistral_client(settings.get("mistral_api_key"))
    resp = client.chat.complete(
        model=settings.get("mistral_model"),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(description) + JSON_INSTRUCTION},
        ],
        response_format={"type": "json_object"},
    )
    return _normalize(json.loads(resp.choices[0].message.content))


def generate_comments(description: str, provider: str = "claude") -> dict:
    if provider == "claude":
        if not settings.get("anthropic_api_key"):
            raise RuntimeError("Anthropic API kaliti o'rnatilmagan.")
        return _normalize(claude_client.generate_comments(description))
    if provider == "groq":
        if not settings.get("groq_api_key"):
            raise RuntimeError("Groq API kaliti o'rnatilmagan.")
        return _generate_groq(description)
    if provider == "mistral":
        if not settings.get("mistral_api_key"):
            raise RuntimeError("Mistral API kaliti o'rnatilmagan.")
        return _generate_mistral(description)
    raise ValueError(f"Noma'lum provayder: {provider}")


def test_provider(provider: str, api_key: str = "", model: str = "") -> str:
    """Provayder kalitini tekshiradi. api_key bo'sh bo'lsa — saqlangani ishlatiladi.

    Muvaffaqiyatda qisqa holat matnini qaytaradi.
    """
    if provider == "claude":
        import anthropic
        key = api_key or settings.get("anthropic_api_key")
        if not key:
            raise RuntimeError("API kalit yo'q")
        anthropic.Anthropic(api_key=key).models.list(limit=1)
        return "Claude ulanishi muvaffaqiyatli"
    if provider == "groq":
        from groq import Groq
        key = api_key or settings.get("groq_api_key")
        if not key:
            raise RuntimeError("API kalit yo'q")
        Groq(api_key=key).models.list()
        return "Groq ulanishi muvaffaqiyatli"
    if provider == "mistral":
        key = api_key or settings.get("mistral_api_key")
        if not key:
            raise RuntimeError("API kalit yo'q")
        _mistral_client(key).models.list()
        return "Mistral ulanishi muvaffaqiyatli"
    raise ValueError(f"Noma'lum provayder: {provider}")
