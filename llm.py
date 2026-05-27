"""Shared LLM client for the content-engine pipeline.

One function: call_llm(prompt, system, **opts) -> str | None.

Provider selected by LLM_PROVIDER env var:
  - gemini    (default) → Gemini 2.5 Flash, free 1,500/day. Google Search
                          grounding ON by default; disable with
                          GEMINI_GROUNDING=0 or grounding=False per call.
  - groq                → Llama 3.3 70B on Groq, free 30 RPM.
  - anthropic           → Claude Sonnet 4.6 (paid).
  - openai | chatgpt    → OpenAI ChatGPT (paid). Default model gpt-4.1-mini.

Gemini multi-key + auto-fallback (consume Pro free quota first, then Flash):
  - GEMINI_API_KEYS=key1,key2,key3,key4   (comma-separated; rotates on
                                           per-day 429 or auth errors)
  - GEMINI_API_KEY=...                    (legacy single-key fallback)
  - GEMINI_MODEL=gemini-2.5-pro           (primary model to try first)
  - GEMINI_FALLBACK_MODEL=gemini-2.5-flash (used after ALL keys hit per-day
                                            quota on the primary; default
                                            gemini-2.5-flash; set to 'none'
                                            to disable fallback)

Per-call overrides (kwargs):
  temperature       float, default 0.6
  max_tokens        int,   default 16000
  top_p             float, default 0.95
  grounding         bool | None — Gemini only. None = env default (ON).
  thinking_budget   int  | None — Gemini only. 0 = skip reasoning.
  provider          str  | None — override env LLM_PROVIDER for this call.

Returns the response text, or None on failure (logged to stderr).
"""
from __future__ import annotations

import os
import sys
import time
from typing import Optional

import requests


def _get_gemini_keys() -> list[str]:
    """Return ordered list of Gemini API keys to try.

    Sources (in priority order):
      - GEMINI_API_KEYS: comma-separated list of keys (rotate through them)
      - GEMINI_API_KEY:  single key (legacy fallback)
    """
    multi = os.environ.get("GEMINI_API_KEYS", "")
    keys = [k.strip() for k in multi.split(",") if k.strip()]
    if not keys:
        single = (os.environ.get("GEMINI_API_KEY") or "").strip()
        if single:
            keys = [single]
    return keys


def _is_per_day_quota_error(body: str) -> bool:
    """Detect Gemini's daily-quota 429 vs the per-minute one. Daily quota
    won't recover with a retry — we must move to a different key."""
    if not body:
        return False
    b = body.lower()
    return ("per day" in b
            or "perday" in b
            or "per_day" in b
            or "generatecontentrequestsperdaypermodelperproject" in b
            or "generaterequestsperdayperprojectpermodel" in b)


def _call_gemini(
    prompt: str,
    system: str,
    *,
    temperature: float,
    max_tokens: int,
    top_p: float,
    grounding: Optional[bool],
    thinking_budget: Optional[int],
) -> Optional[str]:
    keys = _get_gemini_keys()
    if not keys:
        print("No Gemini key (set GEMINI_API_KEY or GEMINI_API_KEYS)",
              file=sys.stderr)
        return None

    primary = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    fb_raw = (os.environ.get("GEMINI_FALLBACK_MODEL") or "gemini-2.5-flash").strip()
    fallback = None if fb_raw.lower() in ("", "none", "off") else fb_raw
    if grounding is None:
        grounding = os.environ.get("GEMINI_GROUNDING", "1") != "0"

    gen_cfg: dict = {
        "temperature": temperature,
        "maxOutputTokens": max_tokens,
        "topP": top_p,
    }
    if thinking_budget is not None:
        gen_cfg["thinkingConfig"] = {"thinkingBudget": thinking_budget}
    payload: dict = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": gen_cfg,
    }
    if grounding:
        payload["tools"] = [{"google_search": {}}]

    # Try primary model with each key in turn; when all keys hit daily
    # quota on primary, fall back to the secondary model (if any).
    models_to_try = [primary]
    if fallback and fallback != primary:
        models_to_try.append(fallback)

    exhausted: list[str] = []

    for model in models_to_try:
        for idx, key in enumerate(keys, 1):
            tag = f"key#{idx}(...{key[-4:]})"
            url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
                   f"{model}:generateContent?key={key}")
            print(f"Gemini try → model={model}  {tag}")

            # Per-attempt retry loop handles transient (5xx, per-minute 429,
            # network blips) but NOT per-day quota — that escapes to the
            # outer loop so we rotate keys/models immediately.
            delays = [10, 30, 60]
            give_up_on_this_key = False
            for attempt in range(len(delays) + 1):
                try:
                    r = requests.post(url, json=payload, timeout=180)
                except requests.exceptions.RequestException as e:
                    if attempt < len(delays):
                        wait = delays[attempt]
                        print(f"  network error — retrying in {wait}s "
                              f"[{attempt+1}/{len(delays)}]: {e}",
                              file=sys.stderr)
                        time.sleep(wait)
                        continue
                    print(f"  network error final: {e}", file=sys.stderr)
                    give_up_on_this_key = True
                    break

                # 4xx (non-429) — bad payload or bad key. If it's an
                # AUTH error (bad key), try next key. Otherwise it's a
                # payload problem that won't fix by rotation — return None.
                if 400 <= r.status_code < 500 and r.status_code != 429:
                    body = r.text[:1500]
                    is_auth = ("API_KEY_INVALID" in body
                               or "API key not valid" in body
                               or r.status_code in (401, 403))
                    print(f"  Gemini {r.status_code} non-retryable:",
                          file=sys.stderr)
                    print(f"  {body[:600]}", file=sys.stderr)
                    if is_auth:
                        give_up_on_this_key = True
                        break  # try next key
                    return None  # bad request — rotation won't help

                # 429: distinguish per-day (skip this key/model) vs
                # per-minute (retry briefly).
                if r.status_code == 429:
                    body = r.text
                    if _is_per_day_quota_error(body):
                        print(f"  Gemini 429 PER-DAY quota — skipping "
                              f"{tag} on {model}", file=sys.stderr)
                        exhausted.append(f"{model}/{tag}")
                        give_up_on_this_key = True
                        break
                    if attempt < len(delays):
                        wait = delays[attempt]
                        print(f"  Gemini 429 per-minute — retrying in "
                              f"{wait}s [{attempt+1}/{len(delays)}]",
                              file=sys.stderr)
                        time.sleep(wait)
                        continue
                    print(f"  Gemini 429 per-minute persisted — moving on",
                          file=sys.stderr)
                    give_up_on_this_key = True
                    break

                if r.status_code in (500, 502, 503, 504):
                    if attempt < len(delays):
                        wait = delays[attempt]
                        print(f"  Gemini {r.status_code} — retrying in "
                              f"{wait}s [{attempt+1}/{len(delays)}]",
                              file=sys.stderr)
                        time.sleep(wait)
                        continue
                    print(f"  Gemini {r.status_code} after retries",
                          file=sys.stderr)
                    give_up_on_this_key = True
                    break

                # 2xx: success path.
                try:
                    r.raise_for_status()
                    j = r.json()
                    cand = j["candidates"][0]
                except Exception as e:
                    print(f"  unexpected response shape: {e}", file=sys.stderr)
                    print(r.text[:400], file=sys.stderr)
                    give_up_on_this_key = True
                    break

                parts = cand.get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts)
                gm = cand.get("groundingMetadata", {})
                if gm:
                    queries = gm.get("webSearchQueries", [])
                    chunks = gm.get("groundingChunks", [])
                    if queries:
                        print(f"  grounding queries ({len(queries)}): "
                              + " | ".join(queries[:5]))
                    if chunks:
                        sources = []
                        for c in chunks[:8]:
                            w = c.get("web", {})
                            if w.get("uri"):
                                sources.append(
                                    f"    - {w.get('title','(no title)')}: {w['uri']}"
                                )
                        if sources:
                            print(f"  grounding sources ({len(chunks)}):")
                            print("\n".join(sources))
                if model != primary:
                    print(f"  (used fallback model: {model})")
                return text

            if give_up_on_this_key:
                continue  # next key
        # All keys on this model are exhausted; try the next model
        if model != models_to_try[-1]:
            print(f"All keys exhausted on {model} — falling back to next model",
                  file=sys.stderr)

    print(f"All Gemini (model, key) combinations failed. "
          f"Daily-exhausted: {exhausted}", file=sys.stderr)
    return None


def _call_groq(
    prompt: str,
    system: str,
    *,
    temperature: float,
    max_tokens: int,
    top_p: float,
) -> Optional[str]:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        print("GROQ_API_KEY not set", file=sys.stderr)
        return None
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "temperature": temperature,
                "top_p": top_p,
                "max_tokens": max_tokens,
            },
            timeout=120,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"Groq call failed: {e}", file=sys.stderr)
        return None


def _call_anthropic(
    prompt: str,
    system: str,
    *,
    temperature: float,
    max_tokens: int,
) -> Optional[str]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set", file=sys.stderr)
        return None
    try:
        from anthropic import Anthropic
    except ImportError:
        print("anthropic SDK not installed (pip install anthropic)",
              file=sys.stderr)
        return None
    client = Anthropic()
    msg = client.messages.create(
        model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        max_tokens=min(max_tokens, 8000),
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def _call_openai(
    prompt: str,
    system: str,
    *,
    temperature: float,
    max_tokens: int,
    top_p: float,
) -> Optional[str]:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        print("OPENAI_API_KEY not set", file=sys.stderr)
        return None
    model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
    delays = [10, 30, 60, 120]
    last_err: Optional[Exception] = None
    for attempt in range(len(delays) + 1):
        try:
            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": temperature,
                    "top_p": top_p,
                    "max_tokens": max_tokens,
                },
                timeout=180,
            )
            if 400 <= r.status_code < 500 and r.status_code != 429:
                print(f"OpenAI {r.status_code} (non-retryable) — body:",
                      file=sys.stderr)
                print(r.text[:1500], file=sys.stderr)
                return None
            if r.status_code in (429, 500, 502, 503, 504):
                if attempt < len(delays):
                    wait = delays[attempt]
                    print(f"OpenAI {r.status_code} (transient) — retrying in "
                          f"{wait}s [{attempt+1}/{len(delays)}]", file=sys.stderr)
                    print(r.text[:300], file=sys.stderr)
                    time.sleep(wait)
                    continue
                print(f"OpenAI failed after retries: HTTP {r.status_code}",
                      file=sys.stderr)
                print(r.text[:400], file=sys.stderr)
                return None
            r.raise_for_status()
            j = r.json()
            usage = j.get("usage", {})
            if usage:
                print(f"OpenAI usage: in={usage.get('prompt_tokens')} "
                      f"out={usage.get('completion_tokens')} "
                      f"total={usage.get('total_tokens')}")
            return j["choices"][0]["message"]["content"]
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt < len(delays):
                wait = delays[attempt]
                print(f"OpenAI network error — retrying in {wait}s "
                      f"[{attempt+1}/{len(delays)}]: {e}", file=sys.stderr)
                time.sleep(wait)
                continue
            break
        except Exception as e:
            print(f"OpenAI call failed (non-retryable): {e}", file=sys.stderr)
            return None
    print(f"OpenAI failed after retries: {last_err}", file=sys.stderr)
    return None


def call_llm(
    prompt: str,
    system: str,
    *,
    temperature: float = 0.6,
    max_tokens: int = 16000,
    top_p: float = 0.95,
    grounding: Optional[bool] = None,
    thinking_budget: Optional[int] = None,
    provider: Optional[str] = None,
) -> Optional[str]:
    p = (provider or os.environ.get("LLM_PROVIDER", "gemini")).lower()
    print(f"LLM provider: {p}  model: "
          f"{os.environ.get({'gemini':'GEMINI_MODEL','groq':'GROQ_MODEL','anthropic':'ANTHROPIC_MODEL','openai':'OPENAI_MODEL','chatgpt':'OPENAI_MODEL'}.get(p,''), '(default)')}")
    if p == "gemini":
        return _call_gemini(
            prompt, system,
            temperature=temperature, max_tokens=max_tokens, top_p=top_p,
            grounding=grounding, thinking_budget=thinking_budget,
        )
    if p == "groq":
        return _call_groq(
            prompt, system,
            temperature=temperature, max_tokens=max_tokens, top_p=top_p,
        )
    if p == "anthropic":
        return _call_anthropic(
            prompt, system,
            temperature=temperature, max_tokens=max_tokens,
        )
    if p in ("openai", "chatgpt"):
        return _call_openai(
            prompt, system,
            temperature=temperature, max_tokens=max_tokens, top_p=top_p,
        )
    print(f"Unknown LLM_PROVIDER: {p}", file=sys.stderr)
    return None
