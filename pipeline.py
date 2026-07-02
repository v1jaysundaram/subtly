"""
subtly — the pipeline.

This file is the machine, not the UI. It's a straight line of single-responsibility
functions (Hard Rule 7), one per step:

    extract_audio -> chunk_audio -> transcribe_chunk -> stitch
        -> format_captions -> translate_blocks -> blocks_to_srt

The load-bearing asset is the word-level timestamp list produced by `stitch`. Every
caption style and every translated language is just a re-grouping / re-render of that
one list — there is no separate transcription per style or per language.

Every step writes a readable file to disk under runs/<timestamp>/ (Hard Rule 1) so a
run can be inspected after the fact. Nothing important lives only in memory.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from pydub import AudioSegment
from pydub.silence import detect_silence

# ~15 MB target per chunk — a safe margin under Whisper's 25 MB per-file limit (Rule 5).
TARGET_CHUNK_BYTES = 15 * 1024 * 1024

# Translation languages offered in the UI — alphabetical, and English is included so a
# user who uploads a non-English video can translate into English.
LANGUAGES = sorted([
    "Arabic", "Chinese", "English", "French", "German", "Hindi",
    "Japanese", "Korean", "Portuguese", "Russian", "Spanish",
])


# ---------------------------------------------------------------------------
# Run directory
# ---------------------------------------------------------------------------
def new_run_dir(base: str = "runs") -> Path:
    """Make a fresh timestamped folder for this run's intermediate files."""
    run_dir = Path(base) / datetime.now().strftime("%Y%m%d_%H%M%S")
    (run_dir / "chunks").mkdir(parents=True, exist_ok=True)
    return run_dir


# ---------------------------------------------------------------------------
# Step 1 — Extract audio
# ---------------------------------------------------------------------------
def extract_audio(video_path: str | Path, out_dir: str | Path) -> Path:
    """
    Pull the audio track out of the uploaded video with ffmpeg.

    We normalise to 16 kHz mono 16-bit WAV. That's what Whisper wants, and it makes
    the file size perfectly predictable (exactly 32,000 bytes per second), which is
    what lets `chunk_audio` hit its size target without guessing.
    """
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg is not on PATH. It's a system-level dependency — install it "
            "locally, and on Streamlit Cloud it comes from packages.txt."
        )

    out_path = Path(out_dir) / "audio.wav"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn",                 # drop the video stream
        "-ac", "1",            # mono
        "-ar", "16000",        # 16 kHz
        "-c:a", "pcm_s16le",   # 16-bit PCM
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed to extract audio:\n{result.stderr[-2000:]}")
    return out_path


# ---------------------------------------------------------------------------
# Step 2 — Chunk audio on silence (with a fixed-time fallback)
# ---------------------------------------------------------------------------
def _find_cut(segment: AudioSegment, target_ms: int, search_ms: int,
              min_silence_len: int, silence_thresh: int) -> int:
    """
    Decide where to cut the *front* off `segment`.

    Prefer a real silence point near the size target so we never slice mid-word
    (Rule 5). If there's no silence in the search window (continuous music, dense
    narration), fall back to a hard cut at the target — that's the mandated
    fixed-time fallback (Rule 3).
    """
    if len(segment) <= target_ms:
        return len(segment)  # last chunk: take everything that's left

    lo = max(0, target_ms - search_ms)
    hi = target_ms
    window = segment[lo:hi]
    silences = detect_silence(
        window, min_silence_len=min_silence_len, silence_thresh=silence_thresh
    )
    if silences:
        # Cut at the midpoint of the last silence in the window — deepest into the
        # chunk while still landing in a pause.
        s, e = silences[-1]
        return lo + (s + e) // 2
    return target_ms  # fixed-time fallback


def chunk_audio(audio_path: str | Path, out_dir: str | Path,
                target_bytes: int = TARGET_CHUNK_BYTES,
                search_ms: int = 20_000,
                min_silence_len: int = 400) -> list[dict]:
    """
    Split the extracted audio into ~15 MB chunks, cutting at silence where possible.

    Returns a list of chunk records: {"path", "start_ms", "duration_ms"}. `start_ms`
    is the chunk's exact position in the original audio — this is the ground-truth
    offset `stitch` later uses to rebuild one continuous timeline.
    """
    audio = AudioSegment.from_file(audio_path)
    out_dir = Path(out_dir)
    chunks_dir = out_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    # Bytes per millisecond for this exact format -> convert the size target to a
    # duration target. (16 kHz * 1 channel * 2 bytes = 32 bytes/ms.)
    bytes_per_ms = audio.frame_rate * audio.channels * audio.sample_width / 1000.0
    target_ms = int(target_bytes / bytes_per_ms)

    # Silence threshold relative to the clip's own loudness, so it adapts to quiet or
    # loud source material instead of using one fixed dB level.
    silence_thresh = int(audio.dBFS - 16) if audio.dBFS != float("-inf") else -50

    records: list[dict] = []
    remaining = audio
    offset_ms = 0
    index = 0
    while len(remaining) > 0:
        cut = _find_cut(remaining, target_ms, search_ms, min_silence_len, silence_thresh)
        piece = remaining[:cut]
        path = chunks_dir / f"{index:03d}.wav"
        piece.export(path, format="wav")
        records.append({
            "path": str(path),
            "start_ms": offset_ms,
            "duration_ms": len(piece),
        })
        offset_ms += len(piece)
        remaining = remaining[cut:]
        index += 1

    # Save the chunk map so the run is inspectable.
    (out_dir / "chunks.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    return records


# ---------------------------------------------------------------------------
# Step 3 — Transcribe one chunk (Whisper, word-level timestamps)
# ---------------------------------------------------------------------------
def transcribe_chunk(client, chunk_path: str | Path) -> dict:
    """
    Send one chunk to Whisper and get word-level timestamps back.

    whisper-1 + verbose_json + timestamp_granularities=["word"] is the ONLY path to
    per-word start/end times (the newer gpt-4o-transcribe models don't return them).
    Times here are relative to the START OF THIS CHUNK; `stitch` shifts them later.
    """
    with open(chunk_path, "rb") as f:
        resp = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="verbose_json",
            # Ask for BOTH: word times (the load-bearing asset) and segment times.
            # Segment text keeps its punctuation, so segments are our reliable source
            # of sentence boundaries even when the word tokens have none. Segments add
            # no extra latency.
            timestamp_granularities=["word", "segment"],
        )
    data = resp.model_dump()
    words = [
        {"word": w["word"], "start": w["start"], "end": w["end"]}
        for w in (data.get("words") or [])
    ]
    segments = [
        {"text": s.get("text", ""), "start": s["start"], "end": s["end"]}
        for s in (data.get("segments") or [])
    ]
    return {
        "language": data.get("language"),
        "duration": data.get("duration"),
        "text": data.get("text", ""),
        "words": words,
        "segments": segments,
    }


# ---------------------------------------------------------------------------
# Step 4 — Re-stitch chunk timestamps into one continuous transcript
# ---------------------------------------------------------------------------
def stitch(transcribed_chunks: list[dict], out_dir: str | Path | None = None) -> dict:
    """
    Shift every chunk's word times forward by that chunk's real start offset, so the
    separately-transcribed chunks become one continuously-timed word list.

    Each item of `transcribed_chunks` must carry {"start_ms", "language", "words"}
    and optionally "segments". Silence gaps are preserved for free: words keep their
    real times, so a pause is simply time that no word covers.

    We also collect `sentence_ends`: the end-times of segments whose (punctuated)
    text finishes a sentence. These are the reliable sentence boundaries the caption
    formatter uses, since word tokens may not carry punctuation.
    """
    words: list[dict] = []
    sentence_ends: list[float] = []
    language = None
    for chunk in transcribed_chunks:
        if language is None:
            language = chunk.get("language")
        offset_s = chunk["start_ms"] / 1000.0
        for w in chunk["words"]:
            words.append({
                "word": w["word"],
                "start": round(w["start"] + offset_s, 3),
                "end": round(w["end"] + offset_s, 3),
            })
        for seg in chunk.get("segments", []):
            if (seg.get("text") or "").strip().endswith((".", "?", "!", "…")):
                sentence_ends.append(round(seg["end"] + offset_s, 3))

    transcript = {"language": language, "words": words, "sentence_ends": sorted(sentence_ends)}
    if out_dir is not None:
        (Path(out_dir) / "transcript.json").write_text(
            json.dumps(transcript, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return transcript


# ---------------------------------------------------------------------------
# Step 5 — Format captions (regroup the one word list into blocks)
# ---------------------------------------------------------------------------
def format_captions(words: list[dict], style: str = "phrase",
                    gap_break_s: float = 0.7,
                    max_words: int = 10, max_chars: int = 42,
                    sentence_max_words: int = 20,
                    sentence_ends: list[float] | None = None,
                    sentence_end_tol: float = 0.5) -> list[dict]:
    """
    Regroup the word-timestamp list into caption blocks for the chosen style.

    Styles:
      - "word":     one word per block (TikTok-style).
      - "phrase":   broken at natural pauses AND sentence ends; a char cap is only a
                    safety net for run-on sentences.
      - "sentence": one block per sentence.

    `sentence_ends` (from `stitch`) are the end-times of punctuated segments — the
    reliable sentence boundaries. We map each to the nearest word so both "phrase" and
    "sentence" can hard-break there even when the word tokens carry no punctuation.
    (We still also honour punctuation on a word, if present, as a fallback.)

    A block is {"start", "end", "text"} where start/end are the REAL first/last word
    times — never stretched to fill a pause (Rule 5a). In every style, a silence gap
    longer than `gap_break_s` forces a break, so a pause becomes uncovered time (no
    caption block), which is exactly what makes the .srt drop cleanly onto the video.
    """
    if not words:
        return []

    blocks: list[dict] = []

    def flush(group: list[dict]):
        if not group:
            return
        text = " ".join(w["word"].strip() for w in group).strip()
        if text:
            blocks.append({"start": group[0]["start"], "end": group[-1]["end"], "text": text})

    if style == "word":
        for w in words:
            flush([w])
        return blocks

    # Mark which word indices land on a real sentence boundary: for each sentence-end
    # time, tag the word whose end time is closest (within tolerance).
    sentence_end_idx: set[int] = set()
    for t in (sentence_ends or []):
        best_i, best_d = None, sentence_end_tol
        for i, w in enumerate(words):
            d = abs(w["end"] - t)
            if d <= best_d:
                best_d, best_i = d, i
        if best_i is not None:
            sentence_end_idx.add(best_i)

    group: list[dict] = []
    for i, w in enumerate(words):
        if group:
            gap = w["start"] - group[-1]["end"]
            cur_text = " ".join(x["word"].strip() for x in group)
            prev_word = group[-1]["word"].strip()
            # The previous word is always words[i-1] (we append every word in order),
            # so its sentence-boundary flag is simply (i-1) in sentence_end_idx.
            ends_sentence = prev_word.endswith((".", "?", "!", "…")) or (i - 1) in sentence_end_idx

            if style == "phrase":
                # Natural boundaries first (pause or sentence end); the char cap is
                # only a safety net so a long run-on still wraps to stay readable.
                over_len = len(cur_text) + 1 + len(w["word"]) > max_chars
                if gap > gap_break_s or ends_sentence or over_len:
                    flush(group)
                    group = []
            elif style == "sentence":
                if ends_sentence or gap > gap_break_s or len(group) >= sentence_max_words:
                    flush(group)
                    group = []
        group.append(w)
    flush(group)
    return blocks


# ---------------------------------------------------------------------------
# Step 6 — Translate a whole set of caption blocks in one batched call
# ---------------------------------------------------------------------------
def translate_blocks(client, blocks: list[dict], target_lang: str,
                     model: str = "gpt-4o-mini") -> list[dict]:
    """
    Translate every caption line into `target_lang` in ONE call (Key Decision:
    batched, not line-by-line, so the model has full context for natural phrasing).

    We send the lines as a numbered JSON array and require the same number of lines
    back in the same order, then re-attach the ORIGINAL timestamps unchanged. The
    timestamps are never re-derived from the translation — translation is pure text.
    """
    if not blocks:
        return []

    source_lines = [b["text"] for b in blocks]
    system = (
        "You are a professional subtitle translator. Translate each subtitle line "
        f"into {target_lang}. Keep each line natural, concise, and suitable for "
        "on-screen captions. Do NOT merge, split, reorder, or renumber lines. "
        'Return ONLY a JSON object of the form {"lines": [...]} whose "lines" array '
        "has exactly the same number of items, in the same order, as the input."
    )
    user = json.dumps({"lines": source_lines}, ensure_ascii=False)

    resp = client.chat.completions.create(
        model=model,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    parsed = json.loads(resp.choices[0].message.content)
    translated = parsed.get("lines", [])

    # Be defensive: if the model returns the wrong count, pad/truncate so we never
    # crash or misalign a line onto the wrong timestamp.
    if len(translated) != len(blocks):
        translated = (translated + source_lines)[:len(blocks)]

    return [
        {"start": b["start"], "end": b["end"], "text": str(t)}
        for b, t in zip(blocks, translated)
    ]


def translate_many(client, blocks: list[dict], target_langs: list[str],
                   model: str = "gpt-4o-mini", max_workers: int = 5) -> dict[str, list[dict]]:
    """
    Translate the same caption blocks into several languages CONCURRENTLY.

    Each language is still its own independent `translate_blocks` call — we just fire
    them together instead of one-after-another, so total wall-clock time is roughly a
    single call rather than N. Concurrency is capped (`max_workers`) so we don't burst
    past OpenAI's rate limits. Returns {language: translated_blocks}, and any error
    (e.g. a bad API key) propagates to the caller unchanged.

    Note: this must stay UI-free — it runs in worker threads, so no Streamlit calls.
    """
    if not target_langs:
        return {}

    workers = min(len(target_langs), max_workers)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        # dict preserves submission order = the user's language order
        futures = {
            lang: pool.submit(translate_blocks, client, blocks, lang, model)
            for lang in target_langs
        }
        return {lang: fut.result() for lang, fut in futures.items()}


# ---------------------------------------------------------------------------
# Step 7 — Render blocks to .srt text
# ---------------------------------------------------------------------------
def _fmt_ts(seconds: float) -> str:
    """Seconds -> SRT timestamp HH:MM:SS,mmm."""
    if seconds < 0:
        seconds = 0
    ms_total = int(round(seconds * 1000))
    h, ms_total = divmod(ms_total, 3_600_000)
    m, ms_total = divmod(ms_total, 60_000)
    s, ms = divmod(ms_total, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def blocks_to_srt(blocks: list[dict]) -> str:
    """Build standard .srt text from caption blocks (numbered, timed, blank-separated)."""
    out: list[str] = []
    for i, b in enumerate(blocks, start=1):
        out.append(str(i))
        out.append(f"{_fmt_ts(b['start'])} --> {_fmt_ts(b['end'])}")
        out.append(b["text"])
        out.append("")
    return "\n".join(out)


def write_srt(blocks: list[dict], out_dir: str | Path, name: str) -> Path:
    """Render blocks to .srt and write <name>.srt to the run directory. Returns path."""
    path = Path(out_dir) / f"{name}.srt"
    path.write_text(blocks_to_srt(blocks), encoding="utf-8")
    return path
