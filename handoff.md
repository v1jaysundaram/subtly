# App: subtly

**What it does:** Upload a video, get back subtitle (.srt) files in the original spoken language and/or your chosen translated languages.

**Platform:** Web app — built with Streamlit (a Python library that turns a script into a browser-based app with almost no frontend code needed), deployed publicly via **Streamlit Community Cloud** (free hosting that deploys straight from a GitHub repo).

---

## Core Features (v1 only)

- **Upload a video file** — no length cap. Long videos are supported via audio chunking (see tech approach).
- **Audio extraction** — pull the audio track out of the uploaded video using **ffmpeg** (a free command-line tool for converting/cutting audio and video files).
- **Smart chunking** — split the audio using **pydub** (a Python library for slicing audio) at natural silence points, targeting ~15MB per chunk, to stay safely under Whisper's 25MB per-file limit without cutting mid-word or mid-sentence.
- **Transcription** — send each chunk to OpenAI's **Whisper API**, requesting **word-level timestamps** (the exact start/end time of every individual word, not just each sentence). Whisper auto-detects the spoken language — no need to specify it upfront.
- **Timestamp re-stitching** — after all chunks are transcribed, shift each chunk's timestamps forward by the audio time that came before it, producing one continuous, correctly-timed transcript.
- **Language options** — subtitle output choices are:
  - "Original" (the detected source language, transcribed as-is)
  - Multi-select translation into any of a **fixed dropdown of ~10 common languages**
- **User-selectable caption style** — a dropdown letting the user choose how subtitle lines are grouped:
  - **Word-by-word** (one word per caption — TikTok-style)
  - **Phrase** (~6–10 words / ~40 characters per line, broken at natural pauses — standard subtitle practice)
  - **Full sentence** (one caption block per sentence)
  - All three are built from the same underlying word-timestamp data — just grouped differently at the formatting step, so offering all three adds no extra transcription cost or complexity.
- **Translation** — for each selected language, send the full batch of transcript lines to a GPT model in **one batched call** (not line-by-line), so it has context for more natural translation. Reformat the result into .srt syntax using the original timestamps.
- **Two-stage live cost estimate**, shown in the sidebar:
  1. **Instant estimate on upload** — calculated the moment the video is uploaded, based on audio duration × Whisper's per-minute rate. No API call needed for this part.
  2. **Refined estimate after transcription** — once the real transcript exists, use **tiktoken** (OpenAI's own library for counting tokens exactly the way their models bill them — a "token" is roughly ¾ of a word) to get the real token count, multiply by the number of selected translation languages, and show an updated, accurate total cost before the user commits to running translation.
- **Download** — generate and offer a downloadable .srt file per selected subtitle language.
- **API key handling** — user enters their own OpenAI API key into a password-style input field (`st.text_input(type="password")`). The key lives only in Streamlit's `session_state` (memory scoped to that one browser tab) for the duration of their session — never written to disk, a database, or logs on our end.

---

## Tech Approach (plain English)

1. ffmpeg pulls the audio track out of the uploaded video.
2. pydub scans that audio for silence gaps and splits it there, targeting ~15MB chunks — this avoids cutting off mid-word, unlike a rigid fixed-time split.
3. Each chunk goes to the Whisper API for transcription with word-level timestamps; Whisper also detects the spoken language along the way.
4. The app shifts each chunk's timestamps forward based on how much audio came before it, reassembling one full, continuously-timed transcript.
5. Based on the user's chosen caption style, the word-level data gets regrouped into word-by-word, phrase, or sentence-length caption lines.
6. For each selected translation language, the full set of caption lines is sent to GPT in a single batched call for translation, then reformatted into standard .srt syntax reusing the original timestamps.
7. Cost is estimated in two passes: an instant duration-based estimate on upload, then a refined tiktoken-based estimate once real transcript text exists.

This is a **straight-line pipeline** (extract → chunk → transcribe → stitch → format captions → translate → generate .srt) with no branching or looping, so it's built as plain sequential Python functions — no LangGraph needed here. (LangGraph is being saved for Weft, where branching pipeline logic actually justifies it.)

---

## Out of Scope for v1

- Speaker diarization (labeling who said what)
- In-app subtitle editing before download
- Burning captions directly into the video
- Subtitle style/font customization
- Multi-video batch upload

---

## Known Risks / Things to Watch Out For

- **Silence-based chunking isn't foolproof** — audio with no clear pauses (continuous music, dense narration) may not give pydub a good silence point to split on. Worth building a fallback to fixed-time splitting if no silence point is found within a chunk.
- **ffmpeg and pydub both require ffmpeg installed at the system level** — this is separate from a normal `pip install` and must be confirmed working in the actual deployment environment (Streamlit Community Cloud), not just locally, since the hosting environment might not have it by default.
- **Streamlit's default upload limit is 200MB** and needs to be raised via config (`maxUploadSize`) to support longer videos. Streamlit Community Cloud may also have its own separate resource/runtime limits worth checking before deploying.

---

## Start Here

Install ffmpeg and pydub locally, and confirm you can split a test audio file on silence into clean, non-mid-word chunks — before writing any transcription code. This is the one dependency that can quietly block everything else if it's not working first.
