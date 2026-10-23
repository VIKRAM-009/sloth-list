# 🦥 SlothList

The grocery list app for people who refuse to think about groceries.

Built for **Hacktoberfest 2026 Week 3: "Slow and Steady"** — build something with open-source AI that rewards laziness.

## What it does

1. Snap up to 3 photos of your fridge, freezer, or pantry.
2. A vision model (`gemma4:31b-cloud` on Ollama Cloud, or a local model like `qwen2.5vl:3b`) looks at the photos and spots what's full, low, or empty — no manual entry.
3. A local text model (`llama3.2` via Ollama) merges that with your **staples** (things you always want restocked, set once) into one clean, categorized shopping list.
4. It also writes a ready-to-send WhatsApp message so you can forward it to a partner, roommate, or shopper in one tap.
5. **Feeling extra lazy?** Hit "Reorder last list" to reuse your last scan plus your staples — zero photos, zero thinking, one click.

Runs 100% on a laptop with no GPU. Nothing about your fridge, your home, or your shopping habits leaves your machine except the one photo sent to the vision model.

## Run it

```bash
pip install -r requirements.txt
python3 app.py
```

Open `http://localhost:5000`, or `http://<laptop-ip>:5000` on your phone over the same WiFi so you can snap the photo straight from the fridge.

### Models

| Env var | Default | Purpose |
|---|---|---|
| `TEXT_MODEL` | `llama3.2` | Builds the categorized list and WhatsApp message |
| `VISION_MODEL` | `gemma4:31b-cloud` | Reads the fridge/pantry photos |

For a fully offline setup (no Ollama Cloud), set `VISION_MODEL=qwen2.5vl:3b` — needs about 10 GB of free RAM.

## Why open-weight models

- **Your fridge is private.** A photo of your kitchen can reveal a lot about your household — nobody needs that sitting in a vendor's training data.
- **Zero per-scan cost.** This is a "set it and forget it" tool. A per-call SaaS price would undercut the entire point of a lazy, frictionless habit.
- **Runs on ordinary hardware.** Built and tested on a laptop: Ubuntu, 15 GB RAM, no GPU.

## Stack

- Python 3.10 + Flask, one file (`app.py`)
- Pillow for photo resizing before it hits the vision model
- Ollama for both models, JSON-schema-constrained output
- Local `sloth_data.json` for staples + history (gitignored)

MIT License. Built for Hacktoberfest 2026 (DEV Challenge Week 3: "Slow and Steady").
