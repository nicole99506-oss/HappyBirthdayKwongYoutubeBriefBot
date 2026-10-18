"""Minimal single-request YouTube video summarization."""
import json

from google import genai
from google.genai import types
from google.genai import errors as genai_errors

from . import config

_client = None


class QuotaExhausted(Exception):
    """Gemini reported a quota or rate-limit error."""


def client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


SUMMARY_PROMPT = """Summarize this YouTube video for a busy reader.
First detect the main spoken language.
If it is Mandarin or Cantonese Chinese, write in Traditional Chinese.
Otherwise write in English.
Return ONLY a JSON object with one field: "summary".
Write one concise but useful summary: about 180-280 Chinese characters
or 100-150 English words. Cover the central claim, the most important
reasoning or evidence, and the conclusion. Do not add a title, bullets,
key concepts, recommendations, or extra fields. Do not invent details.
"""


def summarize_video(url: str) -> dict:
    """Make exactly one generation request; never retry automatically."""
    try:
        resp = client().models.generate_content(
            model=config.GEMINI_MODEL,
            contents=types.Content(parts=[
                types.Part(file_data=types.FileData(file_uri=url)),
                types.Part(text=SUMMARY_PROMPT),
            ]),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
                max_output_tokens=500,
            ),
        )
    except genai_errors.ClientError as e:
        if getattr(e, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(e):
            raise QuotaExhausted(str(e)) from e
        raise
    # Deliberately no retries: the next scheduled run can try again after a delay.
    return json.loads(resp.text)


def summary_to_telegram(video: dict, channel_title: str, summary: dict) -> str:
    text = str(summary.get("summary", "")).strip()
    if not text:
        raise ValueError("Gemini returned an empty summary")
    return (
        f"🎬 *{video['title']}*\n"
        f"_{channel_title} · {video['published'][:10]}_\n\n"
        f"{text}\n\n{video['url']}"
    )[:4000]
