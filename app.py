#!/usr/bin/env python3
"""SlothList - a grocery list for people who refuse to think about groceries.

It uses open-weight models through Ollama:
  - a vision model looks at photos of your fridge/pantry and spots what's low or empty
    (Gemma 4 on Ollama Cloud by default, or a local one like qwen2.5vl:3b)
  - a local text model turns that into one clean, categorized shopping list,
    merges in your "staples" (things you always want restocked), and writes
    a ready-to-send WhatsApp message

Built for Hacktoberfest 2026 Week 3: "Slow and Steady" - reward laziness.
"""

import base64
import io
import json
import os
import re
import urllib.request
from datetime import date

from flask import Flask, redirect, render_template_string, request, url_for
from PIL import Image, ImageOps

OLLAMA = "http://localhost:11434/api/chat"
TEXT_MODEL = os.environ.get("TEXT_MODEL", "llama3.2")
VISION_MODEL = os.environ.get("VISION_MODEL", "gemma4:31b-cloud")
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sloth_data.json")

app = Flask(__name__)


# ---------- storage ----------

def load():
    try:
        with open(DATA_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"staples": [], "history": []}


def save(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ---------- local/cloud models ----------

def ask_model(model, prompt, schema, images=None):
    """Ask an Ollama model and get JSON back in the exact shape of `schema`."""
    msg = {"role": "user", "content": prompt}
    if images:
        msg["images"] = images
    body = json.dumps({"model": model, "messages": [msg], "stream": False, "format": schema,
                       "options": {"temperature": 0.3}}).encode()
    req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        content = json.loads(resp.read())["message"]["content"]
    # Some models wrap the JSON in ```json ... ``` fences, so cut them off.
    content = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", content)
    return json.loads(content)


def schema(**props):
    return {"type": "object", "properties": props, "required": list(props)}


SCAN_PROMPT = """You are scanning a photo of someone's fridge, freezer, or pantry shelf so they
don't have to think about what they're running out of. Look carefully at what is visible.

Only list food, drink, or household items you can actually see. Do not invent items.
If the photo is blurry or isn't a fridge/pantry/shelf, say so in "observed" and return an empty list.

Reply with JSON only:
{"items": [{"name": "item name", "status": "full, low, or empty", "note": "very short note"}],
 "observed": "one sentence describing what you looked at"}"""

SCAN_SCHEMA = schema(
    items={"type": "array", "items": schema(name={"type": "string"}, status={"type": "string"}, note={"type": "string"})},
    observed={"type": "string"},
)

LIST_PROMPT = """You are a grocery list assistant for someone who wants to do as little thinking
as possible. Build ONE clean, categorized shopping list from this:

Items spotted as low or empty in their fridge/pantry photos: {seen}
Staple items they always want restocked (include every single one, no matter what): {staples}
Extra notes from the person: {notes}

Rules:
- Merge duplicates and near-duplicates (e.g. "milk" and "whole milk" -> one line).
- Give each item a realistic restock quantity (e.g. "1 dozen", "2 L", "500 g", "1 pack").
- Group into categories: Produce, Dairy & Eggs, Pantry & Staples, Frozen, Household, Other.
  Skip empty categories.
- Keep it short and practical. This person does not want a 40-item list.

Reply with JSON only:
{{"categories": [{{"name": "category name", "items": [{{"item": "name", "qty": "amount"}}]}}],
 "whatsapp_message": "a short, casual grocery list for a WhatsApp message to a partner, roommate,
   or shopper - one friendly opening line, then the items as a bullet/emoji list"}}"""

LIST_SCHEMA = schema(
    categories={"type": "array", "items": schema(
        name={"type": "string"},
        items={"type": "array", "items": schema(item={"type": "string"}, qty={"type": "string"})},
    )},
    whatsapp_message={"type": "string"},
)


def photo_to_b64(file):
    """Shrink phone photos so the vision model runs fast on a laptop CPU."""
    img = ImageOps.exif_transpose(Image.open(file.stream)).convert("RGB")
    img.thumbnail((768, 768))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def scan_photo(b64):
    r = ask_model(VISION_MODEL, SCAN_PROMPT, SCAN_SCHEMA, images=[b64])
    items = r.get("items") or []
    return [{"name": str(i.get("name", "")), "status": str(i.get("status", "")), "note": str(i.get("note", ""))}
            for i in items if i.get("name")], str(r.get("observed", ""))


def build_list(seen_low, staples, notes):
    seen_text = "; ".join(f"{i['name']} ({i['status']})" for i in seen_low) or "none spotted"
    r = ask_model(TEXT_MODEL, LIST_PROMPT.format(seen=seen_text, staples=", ".join(staples) or "none", notes=notes or "none"), LIST_SCHEMA)
    categories = [{"name": str(c.get("name", "Other")),
                   "items": [{"item": str(i.get("item", "")), "qty": str(i.get("qty", ""))}
                             for i in (c.get("items") or []) if i.get("item")]}
                  for c in (r.get("categories") or [])]
    categories = [c for c in categories if c["items"]]
    return {"categories": categories, "whatsapp_message": str(r.get("whatsapp_message", ""))}


# ---------- page ----------

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SlothList</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 0; background: #fbf3e7; color: #3a2e1f; }
  main { max-width: 560px; margin: 0 auto; padding: 16px; }
  h1 { margin: 8px 0 4px; font-size: 1.7rem; } h2 { margin: 0 0 10px; font-size: 1.25rem; }
  .card { background: #fff; border-radius: 16px; padding: 18px; margin: 14px 0; box-shadow: 0 1px 4px #0001; }
  .muted { color: #8a7a62; font-size: .9rem; }
  button, .btn { box-sizing: border-box; display: block; width: 100%; padding: 14px; border: 0; border-radius: 12px;
                 font-size: 1rem; background: #c2793a; color: #fff; text-align: center; text-decoration: none; margin-top: 10px; cursor: pointer; }
  .btn.light { background: #f1e4d0; color: #3a2e1f; }
  .btn.copy { background: #2e7d4f; }
  input[type=text] { width: 100%; box-sizing: border-box; padding: 12px; border-radius: 10px; border: 1px solid #e3d2b8; font-size: 1rem; }
  input[type=file] { width: 100%; margin-top: 8px; }
  ul.items { list-style: none; padding: 0; margin: 0 0 14px; }
  ul.items li { padding: 6px 0; border-bottom: 1px dashed #eee0c9; display: flex; justify-content: space-between; }
  .cat-title { font-weight: 700; margin-top: 14px; color: #c2793a; }
  pre.wa { white-space: pre-wrap; background: #eafbf0; border-radius: 10px; padding: 12px; font-family: inherit; }
  .error { background: #fde8e4; color: #8a2a12; }
  .tag { font-size: .75rem; padding: 2px 8px; border-radius: 10px; }
  .tag.low { background: #fde9cf; color: #9a5b00; } .tag.empty { background: #fde0dc; color: #9a1f0b; }
</style>
<script>
  function busy(f, msg){ f.querySelector('button').innerText = msg; f.querySelector('button').disabled = true; }
  function copyWA(){ var t = document.getElementById('wa-text').innerText;
    navigator.clipboard.writeText(t).then(function(){ var b = document.getElementById('copy-btn'); b.innerText = 'Copied!'; }); }
</script>
</head><body><main>
<h1>🦥 SlothList</h1>
<p class="muted">The grocery list app for people who refuse to think about groceries.</p>
{% if error %}<div class="card error">{{ error }}</div>{% endif %}

{% if result %}
  <div class="card">
    <h2>Your list is ready</h2>
    {% if result.observed %}<p class="muted">👀 {{ result.observed }}</p>{% endif %}
    {% for cat in result.list.categories %}
      <div class="cat-title">{{ cat.name }}</div>
      <ul class="items">{% for it in cat['items'] %}<li><span>{{ it.item }}</span><span class="muted">{{ it.qty }}</span></li>{% endfor %}</ul>
    {% endfor %}
    {% if not result.list.categories %}<p class="muted">Nothing needed right now. Nice.</p>{% endif %}
  </div>
  <div class="card">
    <h2>📱 Ready to send</h2>
    <pre class="wa" id="wa-text">{{ result.list.whatsapp_message }}</pre>
    <button class="btn copy" id="copy-btn" onclick="copyWA()">Copy WhatsApp Message</button>
  </div>
  <a class="btn light" href="{{ url_for('home') }}">Back to SlothList</a>

{% else %}
  <div class="stats muted">{{ data.history|length }} list(s) made so far</div>

  {% if data.history %}
  <div class="card">
    <h2>😴 Feeling extra lazy?</h2>
    <p class="muted">Skip the photos. Reuse your last list plus your staples, instantly, with zero effort.</p>
    <form method="post" action="{{ url_for('reorder') }}"><button class="btn light">Reorder last list</button></form>
  </div>
  {% endif %}

  <div class="card">
    <h2>1. Your staples (always restocked)</h2>
    <p class="muted">Set these once. Every list will always include them, scan or no scan.</p>
    <form method="post" action="{{ url_for('set_staples') }}" onsubmit="busy(this, 'Saving...')">
      <input type="text" name="staples" placeholder="e.g. milk, eggs, bread, coffee" value="{{ data.staples|join(', ') }}">
      <button>Save Staples</button>
    </form>
  </div>

  <div class="card">
    <h2>2. Snap your fridge or pantry</h2>
    <p class="muted">Up to 3 photos. A vision model spots what's low or empty, then builds your list.</p>
    <form method="post" action="{{ url_for('scan') }}" enctype="multipart/form-data" onsubmit="busy(this, 'Looking... (up to a minute)')">
      <input type="file" name="photos" accept="image/*" multiple required>
      <input type="text" name="notes" placeholder="optional note, e.g. 'skip snacks, on a diet'" style="margin-top:8px">
      <button>Build My List</button>
    </form>
  </div>
{% endif %}
</main></body></html>"""


@app.route("/")
def home(error=None):
    return render_template_string(PAGE, data=load(), error=error, result=None)


@app.post("/staples")
def set_staples():
    data = load()
    raw = request.form.get("staples", "")
    data["staples"] = [s.strip() for s in raw.split(",") if s.strip()]
    save(data)
    return redirect(url_for("home"))


@app.post("/scan")
def scan():
    data = load()
    files = request.files.getlist("photos")[:3]
    if not files or not any(f.filename for f in files):
        return render_template_string(PAGE, data=data, result=None, error="Add at least one photo first.")

    all_items, observed_notes = [], []
    for file in files:
        try:
            b64 = photo_to_b64(file)
        except Exception:
            continue
        items, observed = scan_photo(b64)
        all_items.extend(items)
        if observed:
            observed_notes.append(observed)

    seen_low = [i for i in all_items if i["status"].lower() in ("low", "empty")]
    notes = request.form.get("notes", "")
    shopping_list = build_list(seen_low, data["staples"], notes)

    today = date.today().isoformat()
    data["history"].append({"date": today, "seen_low": seen_low, "list": shopping_list})
    data["history"] = data["history"][-20:]
    save(data)

    result = {"list": shopping_list, "observed": " ".join(observed_notes)}
    return render_template_string(PAGE, data=data, result=result, error=None)


@app.post("/reorder")
def reorder():
    data = load()
    if not data["history"]:
        return redirect(url_for("home"))
    last = data["history"][-1]
    shopping_list = build_list(last.get("seen_low", []), data["staples"], "reorder of the last list")
    today = date.today().isoformat()
    data["history"].append({"date": today, "seen_low": last.get("seen_low", []), "list": shopping_list})
    data["history"] = data["history"][-20:]
    save(data)
    return render_template_string(PAGE, data=data, result={"list": shopping_list, "observed": ""}, error=None)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting SlothList on http://0.0.0.0:{port}")
    print(f"Text model: {TEXT_MODEL} | Vision model: {VISION_MODEL} ({OLLAMA})")
    app.run(host="0.0.0.0", port=port, debug=True)
