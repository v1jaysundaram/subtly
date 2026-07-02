# subtly — Claude Workspace

## What is subtly?
subtly is a web app where you upload a video and get back subtitle (`.srt`) files
— in the original spoken language and/or any of ~10 common languages you pick to
translate into. It's aimed at anyone who needs clean, correctly-timed captions
without editing them by hand: creators, teachers, anyone posting video.

Upload a video → get downloadable subtitle files. That's the whole promise.

## The Core of This Product
**The single word-level timestamp transcript from Whisper is the load-bearing
asset.** Whisper gives back the exact start/end time of every individual word.
Everything downstream — the three caption styles (word-by-word, phrase, full
sentence) and every translated language — is just a *regrouping or re-render* of
that one timestamp dataset. There is no separate transcription per style or per
language. So: get the timestamps right once (transcribe cleanly, stitch chunk
offsets correctly), and everything after it is pure formatting. If the timestamps
are wrong, nothing downstream can save it.

## How This Workspace is Organised
- `CLAUDE.md` — this file. Identity and permanent rules. Rarely changes.
- `CONTEXT.md` — live build status. Read every session, update at the end of every session.
- `handoff.md` — the original full product spec. Reference when the plan is unclear.

(No `stages/` or `references/` folders — this is a simple straight-line build.
The pipeline lives as a checklist inside `CONTEXT.md`.)

## How to Start Any Session
1. Read this file (CLAUDE.md).
2. Read CONTEXT.md — understand what's built and what the current/next step is.
3. Summarise the plan for the current step in plain English and confirm before
   building. The checklist is a flexible guide, not a contract.

## Stack
- **Python** — plain sequential functions, one per pipeline step (no LangGraph;
  there's no branching to justify it — that's saved for Weft).
- **Streamlit** — the UI and the whole app. Deployed publicly on **Streamlit
  Community Cloud** (free, deploys straight from a GitHub repo).
- **ffmpeg** — extracts the audio track from the uploaded video. System-level
  dependency (not just a pip install).
- **pydub** — splits audio at natural silence points into ~15MB chunks.
- **OpenAI Whisper API** — transcribes each chunk with word-level timestamps;
  auto-detects the spoken language.
- **GPT** — translates the full batch of caption lines in one call per language.
- **tiktoken** — counts tokens exactly for the refined cost estimate.
- The user enters their **own OpenAI API key** at runtime (password-style input).

## Hard Rules — Never Break These
1. **Write intermediate pipeline outputs to disk as readable files** — extracted
   audio, each chunk, the raw transcript JSON, each per-language `.srt`. Never
   keep pipeline state only in memory. This is what makes a run debuggable.
2. **Never persist the user's OpenAI API key.** It lives only in Streamlit
   `session_state` for that one session — never written to disk, a database, or
   logs. Not on our end, not anywhere.
3. **Silence-based chunking must have a fixed-time fallback.** If pydub finds no
   silence point within a chunk (continuous music, dense narration), fall back to
   a fixed-time split rather than failing or producing a giant chunk.
4. **ffmpeg is a system-level dependency.** Confirm it actually works in the
   Streamlit Community Cloud deploy (via a `packages.txt` file), not just locally.
   This is the #1 thing that silently breaks in the hosted environment.
5. **Never cut a chunk mid-word.** Target ~15MB per chunk to stay safely under
   Whisper's 25MB per-file limit.
5a. **Preserve silence gaps — never stretch a caption to fill a pause.** Each
   caption block's end time must be the last word's real end time, and its start
   the first word's real start. Silence between speech = no caption block at all
   (an `.srt` is just timed blocks; a gap is the absence of one). This is what
   lets the finished `.srt` be dropped straight onto the original video and line
   up exactly — subtitles show only while someone is talking.
5b. **Pin deploy-level installs from day one.** Even though we build locally
   first, keep `requirements.txt` (Python packages) and `packages.txt` (system
   apt packages — `ffmpeg`) current as libraries are added. Streamlit Community
   Cloud installs system deps *only* from `packages.txt`; a `pip install` will
   never get ffmpeg there.
6. **Explain in plain English before implementing.** The builder learns by
   building — walk through what a step does and why before writing the code.
7. **Keep pipeline steps as separate, single-responsibility functions.** One
   function does one job (extract, chunk, transcribe, stitch, format, translate,
   generate). No function does two.

## Who is Building This
A vibe-coder / non-engineer who learns by building. Wants concise, plain-English
explanations of what each piece does and why *before* the code — not walls of
jargon, not AI-sounding filler. Explain the trade-off, then implement.
