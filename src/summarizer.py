"""Gemini-powered summarization, preferring available YouTube captions."""
import json
import re

from google import genai
from google.genai import types
from google.genai import errors as genai_errors
from youtube_transcript_api import YouTubeTranscriptApi

from . import config

_client = None
_transcript_api = None


class QuotaExhausted(Exception):
    """Raised when Gemini reports a quota or rate-limit error."""


def client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def _video_id(url: str) -> str:
    match = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})", url)
    if not match:
        raise ValueError(f"Cannot extract YouTube video ID from URL: {url}")
    return match.group(1)


def fetch_transcript(url: str) -> str | None:
    """Return captions in the video's original language when available."""
    global _transcript_api
    if _transcript_api is None:
        _transcript_api = YouTubeTranscriptApi()
    video_id = _video_id(url)
    try:
        # Use the original available transcript instead of preferring Chinese or English.
        transcript = _transcript_api.fetch(video_id)
        lines = [str(getattr(item, "text", "")).strip() for item in transcript]
        text = "\\n".join(line for line in lines if line)
        return text or None
    except Exception as e:
        # Captions may be disabled, blocked, or unavailable; fall back to direct video input.
        print(f"[captions] unavailable for {video_id}; falling back to video input: {e}")
        return None


SUMMARY_PROMPT = """You are a faithful video summarizer. Your task is to condense the original video's content into one complete, coherent summary.

LANGUAGE:
- Write the summary in the same language as the video's original spoken language.
- Do not translate the summary into another language.
- For Chinese-language videos, use the same Chinese script/register as the original where possible; do not force Traditional Chinese if the original is Simplified Chinese.

CONTENT AND FIDELITY:
- Cover the entire video, including all major topics from beginning to end.
- Preserve the speaker's main arguments, explanations, reasoning, examples, events, evidence, figures, dates, comparisons, qualifications, and conclusions when they are meaningful to understanding the video.
- Preserve the logical relationships between claims, causes, evidence, counterarguments, and conclusions.
- Include important secondary topics; do not summarize only the opening or the most prominent section.
- Remove repetition, filler, greetings, and redundant wording, but do not remove unique information needed to understand the original.
- Do not add external information, research, personal opinions, recommendations, implications, or analysis that the speaker did not provide.
- Keep facts, opinions, allegations, predictions, and uncertain claims distinct. Do not turn uncertainty into certainty.
- Do not invent or guess details that are unclear or unavailable.

LENGTH:
- Aim for approximately 800 words in the video's original language. This is a guideline, not a strict limit.
- Use more words when necessary to cover a long or information-dense video faithfully. Completeness and accuracy take priority over the approximate length.
- Use fewer words for short or simple videos when that is sufficient to cover their content.

OUTPUT:
Return a valid JSON object with exactly one field: "summary".
The value must be the complete summary as plain text in coherent paragraphs.
Do not include a TL;DR, highlights, key concepts, why-it-matters section, extra headings, bullet lists, or commentary unless those elements are part of the original video's content.
Return only the JSON object."""


def _generate(**kwargs):
    """Make one Gemini request only; never retry inside a short time window."""
    try:
        return client().models.generate_content(**kwargs)
    except genai_errors.ClientError as e:
        if getattr(e, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(e):
            raise QuotaExhausted(str(e)) from e
        raise


def summarize_video(url: str) -> dict:
    """Return a single full summary in the video's original language."""
    transcript = fetch_transcript(url)
    if transcript:
        contents = "VIDEO TRANSCRIPT (captions fetched from YouTube; preserve the original language):\\n\\n" + transcript + "\\n\\n" + SUMMARY_PROMPT
        print(f"[captions] summarizing transcript for {_video_id(url)} ({len(transcript)} characters)")
    else:
        contents = types.Content(parts=[
            types.Part(file_data=types.FileData(file_uri=url)),
            types.Part(text=SUMMARY_PROMPT),
        ])
        print(f"[captions] using Gemini direct-video fallback for {_video_id(url)}")
    resp = _generate(
        model=config.GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )
    result = json.loads(resp.text)
    if not isinstance(result, dict) or not isinstance(result.get("summary"), str) or not result["summary"].strip():
        raise ValueError("Gemini returned an invalid summary JSON object")
    return {"summary": result["summary"].strip()}


def summary_to_telegram(video: dict, channel_title: str, s: dict) -> str:
    """Format only the full summary, without additional analysis sections."""
    summary = s.get("summary", "").strip()
    parts = [
        f"🎬 *{video['title']}*",
        f"_{channel_title} · {video['published'][:10]}_",
        "",
        summary,
        "",
        video["url"],
    ]
    message = "\\n".join(parts)
    # Leave a margin below Telegram's message-length limit.
    if len(message) > 4000:
        suffix = "\\n\\n[摘要因 Telegram 訊息長度限制而截短]\\n\\n" + video["url"]
        message = message[:4000 - len(suffix)] + suffix
    return message
