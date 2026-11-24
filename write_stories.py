"""Generate the daily two-story personal-finance digest for the Stories tab.

Topic freshness comes from recent personal-finance RSS headlines. RSS frequency
is not Google/search-volume data; the page labels it as a headline signal.
Each run writes one dated Markdown digest with exactly two short stories, source
links, a practical reflection, and a low-pressure MyFinancial next step.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from llm import call_llm
from write_pf_newsletter import fetch_pf_news

HERE = Path(__file__).parent
ARTS = HERE / "articles"
META = HERE / "data" / "articles" / "stories.json"
IST = ZoneInfo("Asia/Kolkata")

SYSTEM = """You are MyFinancial's editor for short, plain-language Indian personal-finance stories.
Write for everyday Indian readers, including salaried people, self-employed people
and NRIs. The content is educational, never a personal recommendation.
Use current headline input only as a topic/freshness signal. Do not say you have
search-volume or forum analytics. You may connect a verified public business or
person to one money idea only when reliable sources support the connection.
Otherwise use an explicitly labelled fictional composite example. Never invent
quotes, figures, personal details, events or outcomes. Use simple language and
explain jargon immediately. No return promises, fear, buy/sell calls or pressure.
Return exactly valid JSON in the requested schema and no other text."""

def slugify(text: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text[:70].strip("-") or "money-stories"

def build_prompt(items: list[dict], today: dt.date) -> str:
    lines = []
    for item in items[:30]:
        lines.append({
            "publisher": item.get("source", ""),
            "headline": item.get("title", ""),
            "published": item.get("ts"),
            "summary": item.get("summary", ""),
            "url": item.get("link", ""),
        })
    return f"""Date in India: {today.isoformat()}.
Recent personal-finance RSS headlines (these are the only trend signal supplied):
{json.dumps(lines, ensure_ascii=False, indent=2)}

Create exactly two distinct stories based on two timely, reader-relevant topics
from the headlines above. If the feed is repetitive, choose two different
personal-finance lessons from the strongest available topic. Each story should
be about 140–220 words and have ONE main lesson.

Return JSON with this exact shape:
{{
  "stories": [
    {{
      "title": "short reader-friendly title",
      "topic_signal": "briefly name the supplied headline/theme that prompted it",
      "body": "2–4 short paragraphs in Markdown",
      "takeaway": "one sentence the reader can remember",
      "reflection": "one gentle question or small check the reader can do",
      "sources": [{{"title": "source title", "url": "https://..."}}, {{"title": "...", "url": "https://..."}}]
    }},
    {{ "...same fields..." }}
  ]
}}

Source and accuracy rules:
- Include at least two real, relevant source links per story. Use supplied URLs
  where they support the topic. For factual claims about laws, rules, schemes,
  taxes, or financial products, prefer the relevant official Indian source
  (RBI, SEBI, Income Tax Department, AMFI, EPFO, IRDAI, PFRDA or government).
- Google Search grounding is enabled where the configured provider supports it.
  Only include URLs you can identify as real and relevant; never make up a URL.
- If a named business/person is used, sources must support the specific facts
  stated. Do not imply a public figure's personal financial habits. Prefer
  a clearly labelled fictional composite if verification is weak.
- End each story body with an understated invitation to explore MyFinancial's
  financial-planning help, without claiming the reader needs an adviser.
- Avoid direct investment advice and any promise of outcome.
- Do not include a general disclaimer in the JSON; the publishing script adds it.
"""

def main() -> int:
    today = dt.datetime.now(IST).date()
    items = fetch_pf_news(hours_back=36)
    if len(items) < 2:
        raise SystemExit("Fewer than two current personal-finance headlines; Stories were not generated.")
    prompt = build_prompt(items, today)
    result = call_llm(prompt, SYSTEM, temperature=0.35, max_tokens=7000,
                      top_p=0.9, grounding=True, thinking_budget=0)
    if not result:
        raise SystemExit("The configured LLM returned no Stories content.")
    result = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", result.strip())
    try:
        payload = json.loads(result)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Stories output was not valid JSON: {exc}") from exc
    stories = payload.get("stories")
    if not isinstance(stories, list) or len(stories) != 2:
        raise SystemExit("Stories output must contain exactly two stories.")
    for index, story in enumerate(stories, 1):
        if not all(story.get(key) for key in ("title", "topic_signal", "body", "takeaway", "reflection")):
            raise SystemExit(f"Story {index} is missing required text.")
        sources = story.get("sources")
        if not isinstance(sources, list) or len(sources) < 2:
            raise SystemExit(f"Story {index} needs at least two sources.")
        if any(not str(s.get("url", "")).startswith("https://") for s in sources):
            raise SystemExit(f"Story {index} contains a missing or invalid source URL.")

    slug = f"{today.isoformat()}-stories"
    title = f"Two money stories for {today.strftime('%-d %B %Y')}"
    sections = [
        "# Two everyday stories. One clearer money idea.",
        "",
        f"> **Topic signals:** Today's themes were selected from recent personal-finance RSS headlines. This reflects available headline coverage, not measured search volume.",
        "",
    ]
    for i, story in enumerate(stories, 1):
        sections.extend([
            f"## Story {i}: {story['title']}",
            "",
            f"**Topic signal:** {story['topic_signal']}",
            "",
            story["body"].strip(),
            "",
            f"**What to remember:** {story['takeaway']}",
            "",
            f"**A small check for yourself:** {story['reflection']}",
            "",
            "**Sources**",
            *[f"- [{s['title']}]({s['url']})" for s in story["sources"]],
            "",
        ])
    sections.extend([
        "---",
        "",
        "MyFinancial is a SEBI-registered investment adviser. This article is for education only; it is not investment advice or a recommendation. Any advisory service is provided after understanding an individual client's circumstances.",
        "",
    ])
    body = "\n".join(sections)
    filename = f"{slug}.md"
    canonical = f"https://myfinancialria.github.io/myfinancial-content/articles/{slug}/"
    fm_title = title.replace('"', "'")
    frontmatter = (
        "---\n"
        f'title: "{fm_title}"\n'
        f"date: {today.isoformat()}\n"
        "author: MyFinancial Editorial Team\n"
        "category: stories\n"
        'description: "Two simple, source-linked personal-finance stories with practical takeaways."\n'
        "keywords: [personal finance, money stories, financial planning]\n"
        f"canonical: {canonical}\n"
        f"slug: {slug}\n"
        "---\n\n"
    )
    ARTS.mkdir(exist_ok=True)
    (ARTS / filename).write_text(frontmatter + body, encoding="utf-8")
    META.parent.mkdir(parents=True, exist_ok=True)
    META.write_text(json.dumps({
        "date": today.isoformat(), "slug": slug, "filename": filename,
        "category": "stories", "title": title,
        "description": "Two simple, source-linked personal-finance stories with practical takeaways.",
        "canonical": canonical,
        "based_on": [{"source": x.get("source"), "title": x.get("title"), "link": x.get("link")}
                     for x in items[:10]],
        "topic_signal": "recent personal-finance RSS headlines; not search-volume data",
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote exactly two stories to articles/{filename}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
