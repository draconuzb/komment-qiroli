"""Bir nechta AI provayder: Claude, Groq, Mistral. Kalitlar/modellar sozlamalardan.

Har bir provayder bir xil promptdan foydalanadi va {yumor, aqlli, bahsli} qaytaradi.
"""
import json
import time

import settings
import claude_client
from prompts import SYSTEM_PROMPT, build_user_prompt, JSON_INSTRUCTION, build_persona_prompt

_REQUIRED_KEYS = ("yumor", "aqlli", "bahsli")

# Groq rate-limit (429) bo'lganda zaxira modellar (har birida alohida limit).
_GROQ_FALLBACK_MODELS = ["llama-3.1-8b-instant", "llama-3.3-70b-versatile"]


def _is_rate_limit(e: Exception) -> bool:
    m = str(e).lower()
    return "429" in m or "rate limit" in m or "rate_limit" in m or "too many requests" in m


def _groq_chat(caption: str, personality: str) -> str:
    """Groq'ga so'rov: 429 bo'lsa kutib qayta urinadi, keyin zaxira modelga o'tadi."""
    from groq import Groq
    client = Groq(api_key=settings.get("groq_api_key"))
    primary = settings.get("groq_model") or "llama-3.3-70b-versatile"
    models = [primary] + [m for m in _GROQ_FALLBACK_MODELS if m != primary]
    last_err = None
    for model in models:
        for attempt in range(2):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": build_persona_prompt(caption, personality)},
                    ],
                )
                return (resp.choices[0].message.content or "").strip().strip('"').strip()
            except Exception as e:
                last_err = e
                if _is_rate_limit(e) and attempt == 0:
                    time.sleep(25)   # limit tiklanishini kutamiz, keyin qayta
                    continue
                break  # boshqa xato yoki 2-urinish ham 429 -> keyingi modelga
    raise last_err


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


def _one_groq(caption: str, personality: str) -> str:
    return _groq_chat(caption, personality)


def _one_mistral(caption: str, personality: str) -> str:
    client = _mistral_client(settings.get("mistral_api_key"))
    resp = client.chat.complete(
        model=settings.get("mistral_model"),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_persona_prompt(caption, personality)},
        ],
    )
    return (resp.choices[0].message.content or "").strip().strip('"').strip()


def generate_one(caption: str, personality: str, provider: str = "claude") -> str:
    """Bitta akkaunt xususiyatiga mos BITTA komment (matn). Provayder bo'yicha."""
    # Afzal provayder birinchi, keyin qolganlari ZAXIRA sifatida — biri 429/xato bersa
    # keyingisiga avtomatik o'tadi (Groq -> Mistral -> Claude).
    order = [provider] + [p for p in ("groq", "mistral", "claude") if p != provider]
    last_err = None
    for p in order:
        try:
            r = _try_one(p, caption, personality)
        except Exception as e:
            last_err = e
            continue
        if r:
            return r
    if last_err:
        raise last_err
    raise RuntimeError("Hech qanday AI provayder kaliti yo'q.")


def _try_one(provider: str, caption: str, personality: str):
    """Bitta provayderни sinaydi. Kaliti yo'q bo'lsa None (o'tkazib yuboriladi)."""
    if provider == "groq" and settings.get("groq_api_key"):
        return _one_groq(caption, personality)
    if provider == "mistral" and settings.get("mistral_api_key"):
        return _one_mistral(caption, personality)
    if provider == "claude" and settings.get("anthropic_api_key"):
        return claude_client.generate_one(caption, personality)
    return None


def generate_one_from_image(image_bytes: bytes, personality: str, media_type: str = "image/jpeg") -> str:
    """Caption yo'q — rasm + xususiyat asosida BITTA komment (faqat Claude vision)."""
    if not settings.get("anthropic_api_key"):
        raise RuntimeError("Rasm tahlili uchun Anthropic (Claude) API kaliti kerak.")
    return claude_client.generate_one_from_image(image_bytes, personality, media_type)


def generate_comments_from_image(image_bytes: bytes, media_type: str = "image/jpeg") -> dict:
    """Caption yo'q bo'lganda — post rasmi asosida izoh (faqat Claude vision)."""
    if not settings.get("anthropic_api_key"):
        raise RuntimeError(
            "Bu postda matn (caption) yo'q. Rasm asosida izoh yaratish uchun "
            "Anthropic (Claude) API kaliti kerak — Sozlamalardan kiriting."
        )
    return _normalize(claude_client.generate_comments_from_image(image_bytes, media_type))


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
