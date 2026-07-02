# subtly — Current Build Status

Last updated: 2026-07-02

## Pipeline Checklist
The whole app is this straight line. Check items off as they're built and working.
All seven steps are built as single-responsibility functions in `pipeline.py`,
wired together by the Streamlit UI in `app.py`.

- [x] 1. **Extract audio** — `extract_audio()`; ffmpeg → 16 kHz mono 16-bit WAV
      (predictable size so chunking can hit its byte target exactly).
- [x] 2. **Chunk audio** — `chunk_audio()`; localized silence search near the ~15MB
      target, with the mandated fixed-time fallback. **Fallback verified locally**
      on a silence-free tone (4 exact contiguous chunks).
- [x] 3. **Transcribe** — `transcribe_chunk()`; whisper-1 + verbose_json +
      timestamp_granularities=["word"]. *(Built; not yet run against real API.)*
- [x] 4. **Re-stitch timestamps** — `stitch()`; shifts each chunk's word times by its
      real `start_ms` offset into one continuous transcript. *(Built; needs a real
      multi-chunk run to eyeball a chunk boundary.)*
- [x] 5. **Format captions** — `format_captions()`; word / phrase / sentence. Breaks
      on silence gaps > 0.7s (pause = no block) AND on real sentence boundaries
      (see the sentence-boundary note below). Verified locally.
- [x] 6. **Translate** — `translate_blocks()` (one gpt-4o-mini JSON call per language)
      plus `translate_many()` which fires all selected languages **concurrently**
      (ThreadPoolExecutor, capped at 5) and re-attaches original timestamps.
      *(Built; not yet run against API.)*
- [x] 7. **Generate + download** — `blocks_to_srt()` / `write_srt()` + `st.download_button`
      per language, plus a "Download all (.zip)". Output files are named
      `<original filename>_<language>.srt`. Verified `.srt` formatting locally.

## UI / UX (current state of `app.py`)
- **Sidebar:** OpenAI API-key password input (session_state only, pre-fills from
  local `.env`); a "This run" stats block (language badge + Duration / Words /
  Files / Time metrics, small font) that appears after a run; "Made with ❤️ by
  Vijay" footer pinned to the bottom (LinkedIn link). `assets/logo.png` is the
  browser-tab favicon.
- **Main panel (kept deliberately minimal):** title → uploader → inline media
  preview (`st.video`/`st.audio`) → options → generate → results.
- **Options:** caption-style dropdown ordered word-by-word → phrase → **phrase is
  the default**; "Original language" checkbox; "Translate into" multiselect
  (alphabetical, includes **English**, becomes *required* when Original is off).
  All three option widgets have keys so "Generate new subtitles" can fully reset
  them along with the uploaded file (`reset_app()` + a bumped uploader key).
- **Progress:** playful randomized status messages in a collapsed `st.status`;
  a live time estimate shown OUTSIDE it ("about Xs" → "about Ys left" → "Done in
  Zs"). No progress bar (removed by request).
- **Results:** per-language download + a preview expander (first ~24 `.srt` lines);
  "Download all (.zip)" when >1 file. (Balloons + toast were tried and removed.)
- **Errors:** blank/invalid key → friendly "check your OpenAI API key" message;
  other failures → soft message with details tucked in an expander (no raw dump).
- **Uploader:** accepts mp4/mov/mp3/wav; Streamlit's built-in "Limit • formats"
  line is hidden via CSS. Accepts audio-only files (ffmpeg `-vn` is a harmless
  no-op then).

**Cost estimate REMOVED (2026-07-01, builder's call):** OpenAI has no pricing API,
so any estimate is hardcoded prices that drift silently. Rather than show a number
that could be wrong, we dropped it entirely — sidebar box, the two estimator
functions, and `tiktoken`-token plumbing. This reverses the spec's "two-stage cost
estimate"; kept out on purpose until a reliable source exists.

## Currently In Progress
End-to-end build is complete and compiles. Env (`.venv`, Python 3.13.2), deps,
`.gitignore`, `packages.txt`, `requirements.txt`, `.streamlit/config.toml`,
`pipeline.py`, and `app.py` are all in place. Pure functions + the silence/fallback
chunking are verified locally (no API cost). The only thing not yet exercised is the
paid path (Whisper + GPT), which the builder will run.

## Up Next (current step)
**Run a real paid end-to-end test** (builder-driven):
1. `.\.venv\Scripts\Activate.ps1` then `streamlit run app.py`.
2. Paste an OpenAI key (or leave it — it pre-fills from local `.env`), upload a
   short clip with a clear spoken pause, pick a style + one translation language.
3. After it runs, open the newest `runs/<timestamp>/` folder and check:
   - `transcript.json` word times look continuous across a chunk boundary;
   - a spoken pause produced NO caption block (gap between blocks in the `.srt`);
   - the original `.srt` drops onto the source video perfectly aligned.
Then deploy: push to GitHub and point Streamlit Community Cloud at it — confirm
ffmpeg comes through from `packages.txt`.

## Sentence boundaries in captions (2026-07-02)
**Problem:** Whisper's word-level tokens frequently carry NO punctuation, so
detecting sentence ends from words alone silently fails — "phrase" style would only
break on pauses / the char cap, never at a full stop with no pause.
**Fix:** the transcription request now asks for `["word", "segment"]` (segments add
no latency). Segment *text is punctuated* and has real end-times. `stitch()` collects
the end-times of segments ending in `. ? ! …` as `sentence_ends` (offset per chunk).
`format_captions()` maps each to the nearest word (±0.5s) and hard-breaks there, for
both "phrase" and "sentence" styles. Pauses + a ~42-char safety cap remain as
fallbacks; a word carrying punctuation is still honoured too.
**Still to confirm on a real run:** that Whisper returns sensible segment text/times
on live audio. The raw per-chunk JSON is saved (`runs/<ts>/chunk_000.json`) — inspect
its `words` (do they have punctuation?) and `segments` arrays to verify.

## Python 3.13 note (important)
The stdlib `audioop` module pydub relies on was removed in Python 3.13 (PEP 594).
Fixed by adding `audioop-lts` to `requirements.txt` (guarded to 3.13+). Without it,
`from pydub import AudioSegment` fails at import.

## Key Decisions Made (and why)
- **Plain sequential functions, no LangGraph** — the pipeline is a straight line
  with no branching or looping, so orchestration would be overkill. (LangGraph is
  saved for Weft, where branching logic actually justifies it.)
- **Batched translation, not line-by-line** — sending all caption lines to GPT in
  one call per language gives it context, so translations read more naturally.
- **Concurrent multi-language translation (2026-07-02)** — languages translate in
  parallel (capped at 5) instead of sequentially, so total time ≈ one call, not N.
  Whisper's native translate was rejected: English-only + a second audio inference
  per language + it would discard the shared word-timestamp asset.
- **~~Two-stage cost estimate~~ (SUPERSEDED 2026-07-01)** — originally planned, now
  removed; see the "Cost estimate REMOVED" note above for why.
- **English is a translation target** — added so someone who uploads non-English
  audio can translate *into* English.
- **Output filenames `<original name>_<language>.srt`** — recognisable per upload.
- **Sentence breaks come from segments, not word punctuation (2026-07-02)** — word
  tokens may lack punctuation, so we use Whisper's punctuated segment end-times as
  the reliable sentence boundaries. See the dedicated note below.
- **~15MB chunk target** — safety margin under Whisper's 25MB per-file limit.
- **User-supplied API key** — the user brings their own OpenAI key; we never store it.
- **Key is required for ANY run** — transcription itself is the Whisper API, so a
  key is needed even for original-language-only output (not just translation).

## Watch List
- **Local-first, deploy later** — building/running on local Streamlit for now,
  deploying to Streamlit Community Cloud afterward. Keep `requirements.txt`
  (Python deps) and `packages.txt` (system apt deps: `ffmpeg`) updated as we go
  so the deploy just works. Don't leave deploy config for the end.
- **ffmpeg on Streamlit Cloud** — must be provided via `packages.txt`; confirm it
  works in the hosted environment, not just locally.
- **Silence gaps in output** — verify on a real clip that during a spoken pause
  no subtitle shows, and the `.srt` drops onto the source video perfectly aligned.
- **Streamlit upload limit** — default `maxUploadSize` is 200MB; raise it in config
  to support longer videos.
- **Silence-chunking fallback** — validate the fixed-time fallback on audio with no
  clear pauses (continuous music, dense narration).
- **Streamlit Cloud runtime/resource limits** — check before deploying long-video runs.

---

## How to Update This File
At the end of every session: check off finished pipeline steps, update "Currently
In Progress," set the new "Up Next" step, and append any new decisions or
watch-list items (never delete old decisions — they're the record of *why*).
