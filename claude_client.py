"""Claude orqali 3 ta komment varianti generatsiyasi (kalit/model sozlamalardan)."""
import base64
import json

import anthropic

import settings
from prompts import SYSTEM_PROMPT, build_user_prompt, build_user_prompt_vision, OUTPUT_SCHEMA


def generate_comments(video_description: str) -> dict:
    """Video tavsifi asosida {yumor, aqlli, bahsli} qaytaradi.

    output_config.format JSON sxemasi javobni qat'iy formatga majburlaydi.
    """
    api_key = settings.get("anthropic_api_key")
    if not api_key:
        raise RuntimeError("Anthropic API kaliti o'rnatilmagan (Sozlamalardan kiriting).")

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=settings.get("claude_model"),
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_prompt(video_description)}],
        output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
    )

    if response.stop_reason == "refusal":
        raise RuntimeError("Claude bu so'rovni rad etdi (xavfsizlik sababli).")

    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise RuntimeError("Claude'dan matn javobi kelmadi.")

    return json.loads(text)


def generate_comments_from_image(image_bytes: bytes, media_type: str = "image/jpeg") -> dict:
    """Caption yo'q — post muqova RASMI asosida {yumor, aqlli, bahsli} qaytaradi (vision)."""
    api_key = settings.get("anthropic_api_key")
    if not api_key:
        raise RuntimeError("Anthropic API kaliti o'rnatilmagan (Sozlamalardan kiriting).")

    b64 = base64.standard_b64encode(image_bytes).decode()
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=settings.get("claude_model"),
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": build_user_prompt_vision()},
            ],
        }],
        output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
    )

    if response.stop_reason == "refusal":
        raise RuntimeError("Claude bu rasmni rad etdi (xavfsizlik sababli).")

    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise RuntimeError("Claude'dan matn javobi kelmadi.")

    return json.loads(text)
