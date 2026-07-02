<p align="center">
  <img src="assets/logo.png" alt="subtly Logo" width="120"/>
</p>

<p align="center">
  <a href="https://www.youtube.com/@vijai_sundaram"><img src="https://img.shields.io/badge/YouTube-Subscribe-red?style=flat&logo=youtube" alt="YouTube"/></a>
  <a href="https://www.linkedin.com/in/vijay-sundaram/"><img src="https://img.shields.io/badge/LinkedIn-Connect-blue?style=flat&logo=linkedin" alt="LinkedIn"/></a>
  <a href="https://x.com/VijaySundaram_"><img src="https://img.shields.io/badge/X-Follow-black?style=flat&logo=x" alt="X"/></a>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=v1jaysundaram.subtly" alt="Views"/>
  <img src="https://img.shields.io/github/stars/v1jaysundaram/subtly?style=flat&color=yellow" alt="Stars"/>
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat" alt="License"/>
</p>

---

## Upload a video, get clean, perfectly-timed subtitles — in the original language or any of 10 others.

subtly turns any video or audio file into ready-to-use `.srt` subtitle files. It transcribes what's
said with word-level timing, groups it into readable captions, and can translate the whole thing into
ten common languages — no manual timing, no editing by hand. It's for creators, teachers, and anyone
who needs correct captions without the busywork.

---

## Demo

<p align="center">
  <img src="assets/demo.gif" alt="Demo" width="700"/>
</p>

<p align="center">
  <a href="https://youtu.be/your-video-id">▶️ Watch the full build on YouTube</a>
</p>

---

## Features

- **Word-level transcription** — Whisper returns the exact start/end time of every word, with the spoken language auto-detected.
- **Three caption styles from one transcript** — word-by-word (TikTok-style), phrase, or full sentence, all re-rendered from the same timing data at no extra cost.
- **Translation into 10 languages, concurrently** — each language is a single batched GPT call, and all selected languages run in parallel so the wait stays close to one call.
- **Silence-aware chunking** — long files are split at natural pauses to stay under Whisper's size limit, with a fixed-time fallback when there's no silence to cut on.
- **Real sentence breaks** — captions split at actual sentence endings using Whisper's segment data, not just at a word count.
- **Bring your own key** — you enter your own OpenAI API key at runtime; it's never written to disk, a database, or logs.
- **Flexible downloads** — grab a `.srt` per language, or download everything at once as a `.zip`.

---

## Architecture

subtly is a straight-line pipeline. The **single word-level timestamp transcript is the load-bearing
asset** — every caption style and every translated language is just a re-grouping or re-render of that
one dataset, so the timing only has to be right once.

```
Upload (video/audio)
      │
      ▼
1. Extract audio        ffmpeg → 16 kHz mono WAV (predictable size)
      │
      ▼
2. Chunk on silence     pydub splits at pauses near ~15 MB, with a fixed-time fallback
      │
      ▼
3. Transcribe           each chunk → Whisper (word + segment timestamps)
      │
      ▼
4. Stitch               shift each chunk's times by its real offset → one continuous transcript
      │
      ▼
5. Format captions      regroup words into word / phrase / sentence blocks (segment-based breaks)
      │
      ▼
6. Translate            batched GPT call per language, run concurrently, original timings reused
      │
      ▼
7. Generate .srt        per-language downloads + "download all" zip
```

Every intermediate output (extracted audio, each chunk, the raw transcript JSON, each `.srt`) is
written to disk under `runs/<timestamp>/`, so any run is fully inspectable after the fact.

---

## Tech Stack

| Tool | Purpose |
|------|---------|
| Streamlit | The UI and the app server — the whole frontend in Python |
| OpenAI Whisper API (`whisper-1`) | Transcription with word + segment timestamps and language auto-detection |
| OpenAI GPT (`gpt-4o-mini`) | Batched, context-aware translation |
| ffmpeg | Extracts the audio track from the upload (system-level dependency) |
| pydub | Splits audio at natural silence points into safe-sized chunks |
| python-dotenv | Optional local convenience for pre-filling the API key |

---

## Folder Structure

```
subtly/
├── app.py             # Streamlit UI + pipeline orchestration
├── pipeline.py        # The core — one single-responsibility function per step
├── requirements.txt   # Python dependencies
├── packages.txt       # System dependency (ffmpeg) for Streamlit Community Cloud
├── .streamlit/
│   └── config.toml    # Upload size limit and app config
├── assets/
│   └── logo.png
├── CLAUDE.md          # Project identity and rules (Claude Code workspace)
├── CONTEXT.md         # Live build status
└── handoff.md         # Original product spec
```

---

## Getting Started

**Prerequisites**
- Python 3.10+ (works through 3.13 — `audioop-lts` is included for it)
- ffmpeg installed system-wide (`brew install ffmpeg` · `sudo apt install ffmpeg` · `choco install ffmpeg`)
- An OpenAI API key

**Clone and install**
```bash
git clone https://github.com/v1jaysundaram/subtly.git
cd subtly
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows:     .venv\Scripts\activate
pip install -r requirements.txt
```

**Configure**

No config file is required — you paste your OpenAI API key into the app's sidebar at runtime, and it
lives only in that session. For local convenience you can optionally create a `.env` to pre-fill it:
```bash
echo "OPENAI_API_KEY=sk-..." > .env
```

**Run**
```bash
streamlit run app.py
```

---

## Why I Built This

Honestly, mostly to see if I could build the whole thing end-to-end myself — from a raw upload all the
way to finished, correctly-timed subtitles. Timing captions by hand is tedious, so it was a genuinely
satisfying problem to actually solve rather than just read about.

---

## License

MIT © Vijay Sundaram Mohana

---

## Connect

If you found this helpful, a ⭐ on the repo goes a long way.

<p align="left">
  <a href="https://www.youtube.com/@vijai_sundaram">YouTube</a> &nbsp;·&nbsp;
  <a href="https://www.linkedin.com/in/vijay-sundaram/">LinkedIn</a> &nbsp;·&nbsp;
  <a href="https://x.com/VijaySundaram_">X</a>
</p>
