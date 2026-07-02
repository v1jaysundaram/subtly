"""
subtly — the Streamlit app.

This file is only the UI + orchestration. Every real step lives in pipeline.py as a
plain function; here we just collect input, call the steps in order, show progress,
and hand back downloadable .srt files.

Hard Rule 2: the user's OpenAI API key lives ONLY in session_state for this session.
It is never written to disk, a database, or logs by this app.
"""

import io
import json
import os
import random
import time
import zipfile
from pathlib import Path

import openai
import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

import pipeline as p

# Rough timing prior (refined live from real chunk times during a run). Whisper
# transcribes very roughly ~8s of wall-clock per minute of audio; each translation
# language adds a few seconds. Only used to show a "how long to wait" ballpark.
SECONDS_PER_AUDIO_MINUTE = 8.0
SECONDS_PER_LANGUAGE = 4.0

# Load a local .env if present (dev convenience only). This lets us pre-fill the key
# field on your own machine. .env is gitignored and never committed.
load_dotenv()

LOGO = Path("assets/logo.png")

st.set_page_config(
    page_title="subtly.",
    page_icon=str(LOGO) if LOGO.exists() else None,  # browser-tab favicon (logo when present)
    layout="centered",
)

# Caption styles, ordered simplest grouping -> largest grouping. "phrase" is the default.
CAPTION_STYLES = {
    "Word-by-word (TikTok-style)": "word",
    "Phrase (~6-10 words, standard subtitles)": "phrase",
    "Full sentence": "sentence",
}
DEFAULT_STYLE_INDEX = list(CAPTION_STYLES.values()).index("phrase")


# Pin the credit to the very bottom of the sidebar. Streamlit lays sidebar widgets
# out in a flex column (stVerticalBlock); we make that column tall and give its LAST
# child margin-top:auto so it's pushed all the way down.
st.markdown(
    """
    <style>
    /* Make the sidebar column full height and push its LAST child (the footer) to
       the very bottom. */
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        min-height: calc(100vh - 8rem);
    }
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:last-child {
        margin-top: auto;
    }
    /* But keep NESTED sidebar blocks (the stats container and its metric columns)
       natural — otherwise they'd inherit the full-height stretch above. */
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] [data-testid="stVerticalBlock"] {
        min-height: 0;
    }
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] [data-testid="stVerticalBlock"] > div:last-child {
        margin-top: 0;
    }
    .sidebar-footer {
        padding-top: 2rem;
        font-size: 0.9rem;
        opacity: 0.85;
    }
    /* Make the "This run" stats a touch smaller so they stay unobtrusive. */
    [data-testid="stSidebar"] [data-testid="stMetricValue"] {
        font-size: 1.25rem;
    }
    [data-testid="stSidebar"] [data-testid="stMetricLabel"] p {
        font-size: 0.72rem;
    }
    /* Hide Streamlit's built-in "Limit 2GB per file • FORMATS" line under the
       uploader — we surface that info as a tooltip on the label instead. */
    [data-testid="stFileUploaderDropzoneInstructions"] small {
        display: none;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar — API key (top) + credit (pinned to bottom)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Setup")
    api_key = st.text_input(
        "OpenAI API key",
        type="password",
        value=os.environ.get("OPENAI_API_KEY", ""),
        help="Used only for this session - never saved to disk or logs.",
    )
    if api_key:
        # Kept in session_state (memory) only, for this session.
        st.session_state["api_key"] = api_key

    # This-run stats get rendered here (after a run) — see the bottom of the file.
    stats_slot = st.container()

    st.markdown(
        '<div class="sidebar-footer">Made with ❤️ by '
        '<a href="https://www.linkedin.com/in/vijay-sundaram/" target="_blank">Vijay</a></div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Main — upload, options, run
# ---------------------------------------------------------------------------
st.title("subtly.")
st.caption("Upload a video or audio file and get clean, correctly-timed subtitle (.srt) files.")

# A bumpable key lets the "Generate new subtitles" button fully clear the uploader.
st.session_state.setdefault("uploader_key", 0)
uploaded = st.file_uploader(
    "Upload a video or audio file",
    type=["mp4", "mov", "mp3", "wav"],
    key=f"uploader_{st.session_state['uploader_key']}",
)

# When a NEW file arrives, save it once so ffmpeg has a real path to work from.
if uploaded is not None:
    file_key = f"{uploaded.name}:{uploaded.size}"
    if st.session_state.get("file_key") != file_key:
        scratch = Path("runs") / "_uploads"
        scratch.mkdir(parents=True, exist_ok=True)
        tmp_path = scratch / uploaded.name
        tmp_path.write_bytes(uploaded.getbuffer())
        st.session_state["file_key"] = file_key
        st.session_state["upload_path"] = str(tmp_path)
        st.session_state["results"] = None

# Let the user eyeball what they uploaded before spending anything to run it.
if uploaded is not None:
    if Path(uploaded.name).suffix.lower() in {".mp3", ".wav", ".m4a"}:
        st.audio(uploaded)
    else:
        st.video(uploaded)

# --- Options ---
col1, col2 = st.columns(2)
with col1:
    style_label = st.selectbox(
        "Caption style", list(CAPTION_STYLES.keys()),
        index=DEFAULT_STYLE_INDEX, key="opt_style",
    )
    style = CAPTION_STYLES[style_label]
with col2:
    include_original = st.checkbox("Original language", value=True, key="opt_original")

# If the user doesn't want the original language, a translation is required.
translate_required = not include_original
target_langs = st.multiselect(
    "Translate into" + (" (required)" if translate_required else ""),
    p.LANGUAGES, key="opt_langs",
)
if translate_required and not target_langs:
    st.info("Original language is off - pick at least one language to translate into.")

# The run is only valid with a file AND at least one chosen output.
can_run = uploaded is not None and (include_original or bool(target_langs))
run = st.button("Generate Subtitles", type="primary", disabled=not can_run)
st.caption("⏱ Longer videos take longer - you'll get a live time estimate once it starts.")


# --- Playful, non-technical status messages (picked at random for variety) ---
FUN = {
    "extract": [
        "🎧 Prying the audio out of your video…",
        "🎧 Separating the talking from the pictures…",
    ],
    "chunk": [
        "✂️ Slicing the audio into bite-sized pieces…",
        "✂️ Chopping things up at the quiet bits…",
    ],
    "stitch": [
        "🧵 Sewing the timeline back together…",
        "🧩 Snapping all the pieces back into place…",
    ],
    "format": [
        "✍️ Arranging your captions just so…",
        "✨ Tidying every line into place…",
    ],
    "done": [
        "🎉 Ta-da! Your subtitles are ready.",
        "🍿 All done — grab your captions below!",
    ],
}


def fun(stage: str) -> str:
    return random.choice(FUN[stage])


def clock(seconds: float) -> str:
    """Friendly duration like '45s' or '2m 05s'."""
    seconds = int(round(seconds))
    return f"{seconds}s" if seconds < 60 else f"{seconds // 60}m {seconds % 60:02d}s"


def reset_app():
    """Clear this run AND the user's selections, then start fresh."""
    for k in ("results", "stats", "file_key", "upload_path",
              "opt_style", "opt_original", "opt_langs"):
        st.session_state.pop(k, None)
    st.session_state["uploader_key"] += 1  # bump = uploader clears too
    st.rerun()


# ---------------------------------------------------------------------------
# Run the pipeline
# ---------------------------------------------------------------------------
if run:
    if not st.session_state.get("api_key"):
        st.error("🔑 Please add your OpenAI API key in the sidebar to continue.")
        st.stop()

    client = OpenAI(api_key=st.session_state["api_key"])
    run_dir = p.new_run_dir()
    start_time = time.time()

    # The live time estimate lives OUTSIDE the status box, so it's always visible
    # without opening the collapsible "detailed notes".
    eta_box = st.empty()

    try:
        with st.status("Warming up…", expanded=False) as status:
            # 1. Extract audio
            status.update(label=fun("extract"))
            video_path = st.session_state["upload_path"]
            audio_path = p.extract_audio(video_path, run_dir)

            # 2. Chunk on silence
            status.update(label=fun("chunk"))
            chunks = p.chunk_audio(audio_path, run_dir)
            st.write(f"Broke your audio into **{len(chunks)}** piece(s).")

            # Upfront "how long to wait" ballpark — available for EVERY video (even a
            # single-chunk short one), based on total audio length + languages chosen.
            audio_minutes = sum(c["duration_ms"] for c in chunks) / 60_000.0
            est_total = audio_minutes * SECONDS_PER_AUDIO_MINUTE + len(target_langs) * SECONDS_PER_LANGUAGE
            eta_box.info(f"⏳ Estimated time: about **{clock(est_total)}**")

            # 3. Transcribe each chunk (word-level timestamps).
            #    We time each piece so we can refine the estimate of time remaining.
            transcribed = []
            chunk_secs = []
            for i, ch in enumerate(chunks):
                t0 = time.time()
                result = p.transcribe_chunk(client, ch["path"])
                chunk_secs.append(time.time() - t0)

                result["start_ms"] = ch["start_ms"]
                # Save raw per-chunk transcription so the run is debuggable.
                (run_dir / f"chunk_{i:03d}.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                transcribed.append(result)

                done = i + 1
                avg = sum(chunk_secs) / len(chunk_secs)
                eta = avg * (len(chunks) - done)
                if done < len(chunks):
                    eta_box.info(f"⏳ About **{clock(eta)}** left…")
                status.update(label=f"👂 Listening closely — piece {done} of {len(chunks)}")

            # 4. Stitch into one continuous transcript
            status.update(label=fun("stitch"))
            transcript = p.stitch(transcribed, run_dir)
            language = transcript.get("language") or "original"
            st.write(f"Heard **{language}** · {len(transcript['words'])} words.")

            # 5. Format captions in the chosen style
            status.update(label=fun("format"))
            base_blocks = p.format_captions(
                transcript["words"], style=style,
                sentence_ends=transcript.get("sentence_ends"),
            )

            results = []  # (label, filename, srt_text)

            # Name outputs after the uploaded file: "<original name>_<language>.srt".
            base_name = Path(st.session_state["upload_path"]).stem

            # Original language output
            if include_original:
                path = p.write_srt(base_blocks, run_dir, f"{base_name}_{language.title()}")
                results.append((f"Original ({language})", path.name, path.read_text(encoding="utf-8")))

            # 6. Translate all selected languages at once (concurrent calls).
            if target_langs:
                langs_word = "language" if len(target_langs) == 1 else "languages"
                status.update(label=f"🌍 Teaching your captions {len(target_langs)} new {langs_word} at once…")
                translations = p.translate_many(client, base_blocks, target_langs)
                for lang in target_langs:
                    path = p.write_srt(translations[lang], run_dir, f"{base_name}_{lang}")
                    results.append((lang, path.name, path.read_text(encoding="utf-8")))

            elapsed = time.time() - start_time
            st.session_state["results"] = results
            st.session_state["stats"] = {
                "language": language,
                "duration_s": audio_minutes * 60.0,
                "words": len(transcript["words"]),
                "files": len(results),
                "elapsed_s": elapsed,
            }
            eta_box.success(f"✅ Done in **{clock(elapsed)}**")
            status.update(label=fun("done"), state="complete")

    except (openai.AuthenticationError, openai.PermissionDeniedError):
        st.error("🔑 That didn't work — please double-check your OpenAI API key in the sidebar.")
        st.stop()
    except Exception as e:
        st.error("😕 Something went wrong while making your subtitles. Please try again.")
        with st.expander("Technical details"):
            st.code(str(e))
        st.stop()


# ---------------------------------------------------------------------------
# Results — badge, stats, downloads, zip (persist across reruns via session_state)
# ---------------------------------------------------------------------------
results = st.session_state.get("results")
if results:
    st.subheader("Your subtitles")

    # Download everything at once — handy when several languages were generated.
    if len(results) > 1:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for _label, filename, srt_text in results:
                zf.writestr(filename, srt_text)
        st.download_button(
            "⬇ Download all (.zip)",
            data=buf.getvalue(),
            file_name="subtitles.zip",
            mime="application/zip",
            type="primary",
            key="dl_zip",
        )

    # Individual files, each with a preview
    for label, filename, srt_text in results:
        st.download_button(
            label=f"⬇ {label}  ({filename})",
            data=srt_text,
            file_name=filename,
            mime="text/plain",
            key=f"dl_{filename}",
        )
        with st.expander(f"Preview - {label}"):
            preview = "\n".join(srt_text.splitlines()[:24])
            st.code(preview or "(empty)", language="text")

    st.divider()
    if st.button("✨ Generate new subtitles"):
        reset_app()


# ---------------------------------------------------------------------------
# This-run stats — rendered into the sidebar slot (keeps the main panel clean)
# ---------------------------------------------------------------------------
stats = st.session_state.get("stats")
if stats:
    with stats_slot:
        st.divider()
        st.caption("This run")
        if stats.get("language"):
            st.badge(f"🗣️ {stats['language'].title()}", color="green")
        a, b = st.columns(2)
        a.metric("Duration", clock(stats.get("duration_s", 0)))
        b.metric("Words", f"{stats.get('words', 0):,}")
        c, d = st.columns(2)
        c.metric("Files", stats.get("files", 0))
        d.metric("Time", clock(stats.get("elapsed_s", 0)))
