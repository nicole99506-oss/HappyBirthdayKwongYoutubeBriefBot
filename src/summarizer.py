"""Gemini-powered summarization, preferring available YouTube captions."""
import json
import re
import time

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
    """Return available captions as text; None when captions cannot be fetched."""
    global _transcript_api
    if _transcript_api is None:
        _transcript_api = YouTubeTranscriptApi()
    video_id = _video_id(url)
    try:
        transcript = _transcript_api.fetch(video_id, languages=[
            "zh-Hant", "zh-TW", "zh", "zh-Hans", "en"
        ])
        lines = [str(getattr(item, "text", "")).strip() for item in transcript]
        text = "\n".join(line for line in lines if line)
        return text or None
    except Exception as e:
        # Captions may be disabled, blocked, or unavailable in preferred languages.
        # This is not a Gemini request; fallback to Gemini's direct video understanding.
        print(f"[captions] unavailable for {video_id}; falling back to video input: {e}")
        return None


SUMMARY_PROMPT = "You are writing a briefing for a sophisticated reader who follows\nglobal political economy closely. Watch this video and produce a JSON object with\nexactly these fields.\n\nLANGUAGE RULE: First detect the video's primary spoken language. If it is Chinese\n(Mandarin or Cantonese), write ALL field values in Traditional Chinese (繁體中文).\nFor any other language, write ALL field values in English. Never mix languages.\n\n- \"tldr\": one sentence (max 30 words / 40 Chinese characters) capturing the single most important takeaway.\n- \"summary\": 2-3 tight paragraphs (180-260 words in English, or 300-450 characters\n  in Chinese) covering the core argument, key evidence/data cited, and the speaker's\n  conclusion. Write like the Economist: dense, precise, no filler.\n- \"highlights\": 3-5 bullet strings, each one concrete claim, number, or quote-worthy\n  point from the video.\n- \"key_concepts\": 2-4 objects of {\"term\": ..., \"explanation\": ...} -- frameworks,\n  jargon, or mechanisms a reader should learn from this video. Explanation max 25 words.\n- \"why_it_matters\": one sentence connecting this to the bigger macro/geopolitical picture.\n\nTarget total reading time: 1-2 minutes. Return ONLY the JSON object."


def _generate(**kwargs):
    """Retry transient server overloads only; quota errors are never retried."""
    last = None
    for attempt in range(3):
        try:
            return client().models.generate_content(**kwargs)
        except genai_errors.ClientError as e:
            if getattr(e, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(e):
                raise QuotaExhausted(str(e)) from e
            raise
        except genai_errors.ServerError as e:
            last = e
            print(f"[gemini] server error (attempt {attempt + 1}/3): {e}")
            if attempt < 2:
                time.sleep(20 * (attempt + 1))
    raise last


def summarize_video(url: str) -> dict:
    """Summarize captions when available; otherwise send the video URL to Gemini."""
    transcript = fetch_transcript(url)
    if transcript:
        contents = "VIDEO TRANSCRIPT (captions fetched from YouTube):\n\n" + transcript + "\n\n" + SUMMARY_PROMPT
        print(f"[captions] summarizing transcript for {_video_id(url)} ({len(transcript)} characters)")
    else:
        contents = types.Content(parts=[
            types.Part(file_data=types.FileData(file_uri=url)),
            types.Part(text=SUMMARY_PROMPT),
        ])
        print(f"[captions] using Gemini direct-video fallback for {_video_id(url)}")
    try:
        resp = _generate(
            model=config.GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )
    except genai_errors.ClientError as e:
        if getattr(e, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(e):
            raise QuotaExhausted(str(e)) from e
        raise
    return json.loads(resp.text)


def summary_to_telegram(video: dict, channel_title: str, s: dict) -> str:
    parts = [
        f"🎬 *{video['title']}*",
        f"_{channel_title} · {video['published'][:10]}_",
        "",
        f"💡 *The Gist* — {s.get('tldr', '')}",
        "",
        s.get("summary", ""),
        "",
        "*Highlights*",
    ]
    parts += [f"• {h}" for h in s.get("highlights", [])]
    concepts = s.get("key_concepts", [])
    if concepts:
        parts += ["", "*Key Concepts*"]
        parts += [f"• *{k.get('term', '')}* — {k.get('explanation', '')}" for k in concepts]
    parts += ["", f"🌍 {s.get('why_it_matters', '')}", "", video["url"]]
    return "\n".join(parts)[:4000]
