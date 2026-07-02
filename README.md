<p align="center">
  <img src="assets/logo.png" alt="subtly Logo" width="120"/>
</p>

<h1 align="center"><b>subtly</b></h1>

<p align="center">
  <a href="https://www.youtube.com/@vijai_sundaram"><img src="https://img.shields.io/badge/YouTube-Subscribe-red?style=flat&logo=youtube" alt="YouTube"/></a>
  <a href="https://www.linkedin.com/in/vijay-sundaram/"><img src="https://img.shields.io/badge/LinkedIn-Connect-blue?style=flat&logo=linkedin" alt="LinkedIn"/></a>
  <a href="https://x.com/VijaySundaram_"><img src="https://img.shields.io/badge/X-Follow-black?style=flat&logo=x" alt="X"/></a>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=v1jaysundaram.subtly" alt="Views"/>
  <img src="https://img.shields.io/github/stars/v1jaysundaram/subtly?style=flat&color=yellow" alt="Stars"/>
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat" alt="License"/>
</p>

---

## Upload a video, get clean, perfectly-timed subtitles - in the original language or any of 10 others.

subtly turns any video or audio file into ready-to-use `.srt` subtitle files. It transcribes what's said with word-level timing, groups it into readable captions, and can translate the whole thing into ten languages - no manual timing, no editing by hand. It's for creators, teachers, and anyone who needs correct captions without the busywork.

---

## Demo

<p align="center">
  <img src="assets/demo.gif" alt="Demo" width="700"/>
</p>

<p align="center">
  <a href="http://subtly-ai.streamlit.app/">🚀 Try the live app</a> &nbsp;·&nbsp;
  <a href="https://youtu.be/NySKpDXzuC8">▶️ Watch the detailed walkthrough on YouTube</a>
</p>

---

## Why I Built This

Honestly, I just wanted to vibe code somehting - I wanted to see whether I could get the whole thing built end-to-end, from a raw upload to finished, correctly-timed subtitles.
Timing captions by hand is tedious, so it was a genuinely satisfying problem to actually solve.

Plus, most subtitle apps out there are so bloated - fonts, styles, editors, endless options. I just wanted something dead simple: you upload, you pick a language, you get your subtitles. Nothing else.

---

## Features

- **Preview your upload** - see your video or audio right in the app before you start.
- **3 caption styles** - pick word-by-word, phrase, or full sentence.
- **Automatic language detection** - no need to tell it what's being spoken; it figures it out.
- **Translate into 10 languages** - choose as many as you want.
- **Preview before you download** - peek at a snippet of your subtitles to check they look right.
- **One-click downloads** - grab each language on its own, or all of them together as a `.zip`.

---

## Architecture

subtly is a straight-line pipeline. The **single word-level timestamp transcript is the load-bearing asset** - every caption style and every translated language is just a re-grouping or re-render of that
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
---

## Tech Stack

| Tool | Purpose |
|------|---------|
| Streamlit | The UI and the app server - the whole frontend in Python |
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
├── pipeline.py        # The core - one single-responsibility function per step
├── requirements.txt   # Python dependencies
├── packages.txt       # System dependency (ffmpeg) for Streamlit Community Cloud
└── .streamlit/
    └── config.toml    # Upload size limit and app config
```

---

## Getting Started

**Prerequisites**
- Python 3.10+ (works through 3.13 - `audioop-lts` is included for it)
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

No config file is required - you paste your OpenAI API key into the app's sidebar at runtime, and it lives only in that session. For local convenience you can optionally create a `.env` to pre-fill it:
```bash
echo "OPENAI_API_KEY=sk-..." > .env
```

**Run**
```bash
streamlit run app.py
```

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
