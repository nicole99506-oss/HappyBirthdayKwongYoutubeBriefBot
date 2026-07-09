"""Gemini-powered summarization.

Gemini reads the YouTube URL directly (video + audio), so videos WITHOUT
captions work too -- no downloading, no Whisper, no bot walls.
"""
import json

from google import genai
from google.genai import types
from google.genai import errors as genai_errors

from . import config

_client = None


class QuotaExhausted(Exception):
    """Raised when the free-tier quota is used up. Never costs money -- the
    request simply fails and we retry on a later run."""


def client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


SUMMARY_PROMPT = """You are writing a briefing for a sophisticated reader who follows
global political economy closely. Watch this video and produce a JSON object with
exactly these fields.

LANGUAGE RULE: First detect the video's primary spoken language. If it is Chinese
(Mandarin or Cantonese), write ALL field values in Traditional Chinese (繁體中文).
For any other language, write ALL field values in English. Never mix languages.

- "tldr": one sentence (max 30 words / 40 Chinese characters) capturing the single most important takeaway.
- "summary": 2-3 tight paragraphs (180-260 words in English, or 300-450 characters
  in Chinese) covering the core argument, key evidence/data cited, and the speaker's
  conclusion. Write like the Economist: dense, precise, no filler.
- "highlights": 3-5 bullet strings, each one concrete claim, number, or quote-worthy
  point from the video.
- "key_concepts": 2-4 objects of {"term": ..., "explanation": ...} -- frameworks,
  jargon, or mechanisms a reader should learn from this video. Explanation max 25 words.
- "why_it_matters": one sentence connecting this to the bigger macro/geopolitical picture.

Target total reading time: 1-2 minutes. Return ONLY the JSON object.
"""


def summarize_video(url: str) -> dict:
    try:
        resp = client().models.generate_content(
            model=config.GEMINI_MODEL,
            contents=types.Content(parts=[
                types.Part(file_data=types.FileData(file_uri=url)),
                types.Part(text=SUMMARY_PROMPT),
            ]),
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


MERGE_PROMPT = """You maintain a knowledge tree for the YouTube channel "{channel}".
The tree is a JSON object: {{"name": <topic>, "children": [<same shape>...]}}.
Root name must stay "{channel}".

Current tree:
{tree}

A new video was just summarized. Its key concepts and highlights:
{concepts}

Update the tree: place new concepts under the most fitting existing branch, create a
new top-level branch only when genuinely new territory, merge duplicates, keep node
names under 6 words (or 10 Chinese characters). Write node names in the same
language as the incoming concepts. Keep the whole tree under {max_nodes} nodes -- if needed,
consolidate leaf nodes into their parents. Return ONLY the updated JSON tree.
"""


def merge_into_tree(channel_title: str, tree: dict | None, summary: dict) -> dict:
    if tree is None:
        tree = {"name": channel_title, "children": []}
    concepts = {
        "video_tldr": summary.get("tldr", ""),
        "key_concepts": summary.get("key_concepts", []),
        "highlights": summary.get("highlights", []),
    }
    prompt = MERGE_PROMPT.format(
        channel=channel_title,
        tree=json.dumps(tree, ensure_ascii=False),
        concepts=json.dumps(concepts, ensure_ascii=False),
        max_nodes=config.MINDMAP_MAX_NODES,
    )
    try:
        resp = client().models.generate_content(
            model=config.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
        new_tree = json.loads(resp.text)
        if isinstance(new_tree, dict) and new_tree.get("name"):
            return new_tree
    except genai_errors.ClientError as e:
        if getattr(e, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(e):
            raise QuotaExhausted(str(e)) from e
        raise
    except (json.JSONDecodeError, TypeError):
        pass
    return tree  # never lose the old tree on a bad response


def summary_to_markdown(video: dict, channel_title: str, s: dict) -> str:
    lines = [
        f"# {video['title']}",
        "",
        f"**Channel:** {channel_title}  ",
        f"**Published:** {video['published'][:10]}  ",
        f"**Link:** {video['url']}",
        "",
        f"> **The Gist** — {s.get('tldr', '')}",
        "",
        "## Summary",
        "",
        s.get("summary", ""),
        "",
        "## Highlights",
        "",
    ]
    lines += [f"- {h}" for h in s.get("highlights", [])]
    lines += ["", "## Key Concepts", ""]
    for kc in s.get("key_concepts", []):
        lines.append(f"- **{kc.get('term', '')}** — {kc.get('explanation', '')}")
    lines += ["", "## Why It Matters", "", s.get("why_it_matters", ""), ""]
    return "\n".join(lines)


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
    kcs = s.get("key_concepts", [])
    if kcs:
        parts += ["", "*Key Concepts*"]
        parts += [f"• *{k.get('term','')}* — {k.get('explanation','')}" for k in kcs]
    parts += ["", f"🌍 {s.get('why_it_matters', '')}", "", video["url"]]
    text = "\n".join(parts)
    return text[:4000]  # Telegram hard limit is 4096
