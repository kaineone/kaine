import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable, List, Optional

import numpy as np
import soundfile as sf


SAMPLE_RATE = 8000
DEFAULT_MAX_DURATION_SEC = 30.0
DEFAULT_WPM = 140.0


def normalize_text(raw: str) -> str:
    """Normalize whitespace and Unicode for stable chunking."""
    text = unicodedata.normalize("NFKC", raw)
    text = "".join(
        character if character.isprintable() or character.isspace() else " "
        for character in text
    )
    return " ".join(text.split())


def split_sentences(text: str) -> List[str]:
    """Split normalized text into sentences on sentence boundaries."""
    normalized = normalize_text(text)
    if not normalized:
        return []
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", normalized)
        if sentence.strip()
    ]
    return sentences or [normalized]


def estimate_duration_sec(word_count: int, wpm: float = DEFAULT_WPM) -> float:
    """Estimate speech duration from a word count at the given WPM."""
    if word_count <= 0 or wpm <= 0:
        return 0.0
    return word_count * 60.0 / wpm


def chunk_text(
    text: str,
    max_duration_sec: float = DEFAULT_MAX_DURATION_SEC,
    wpm: float = DEFAULT_WPM,
) -> List[str]:
    """Chunk text into utterances no longer than max_duration_sec.

    Sentence boundaries are preferred. A sentence longer than the limit is
    split into word-limited pieces so every chunk still satisfies the
    duration constraint.
    """
    max_words = max(1, int(max_duration_sec * wpm / 60.0))
    chunks: List[str] = []
    current: List[str] = []
    current_words = 0

    for sentence in split_sentences(text):
        words = sentence.split()
        word_count = len(words)

        if word_count > max_words:
            if current:
                chunks.append(" ".join(current))
                current = []
                current_words = 0
            for start in range(0, word_count, max_words):
                chunks.append(" ".join(words[start : start + max_words]))
            continue

        if current and current_words + word_count > max_words:
            chunks.append(" ".join(current))
            current = [sentence]
            current_words = word_count
        else:
            current.append(sentence)
            current_words += word_count

    if current:
        chunks.append(" ".join(current))

    return chunks


def render_take(text: str) -> np.ndarray:
    """Placeholder for qwen3-TTS synthesis.

    TODO: Implement qwen3-TTS CLI invocation and return synthesized 8 kHz
    mono audio as a NumPy array. Stage-1 scaffolding intentionally does not
    execute synthesis.
    """
    raise NotImplementedError(
        "render_take is a stage-1 placeholder; TTS synthesis is not implemented."
    )


def _placeholder_audio(duration_sec: float) -> np.ndarray:
    """Create deterministic silent placeholder audio for a chunk duration."""
    sample_count = max(0, int(round(duration_sec * SAMPLE_RATE)))
    return np.zeros(sample_count, dtype=np.float32)


def write_wav(path: Path, audio: np.ndarray) -> None:
    """Write a mono WAV at the configured 8 kHz sample rate."""
    sf.write(
        str(path),
        audio,
        SAMPLE_RATE,
        format="WAV",
        subtype="PCM_16",
    )


def build_manifest_patch(
    chapter: str,
    source_path: Path,
    output_dir: Path,
    chunks: Iterable[str],
    max_duration_sec: float,
    wpm: float,
) -> dict:
    """Build a manifest patch describing chunk takes and placeholder hashes."""
    items = []
    chunk_list = list(chunks)

    for index, text in enumerate(chunk_list, start=1):
        word_count = len(text.split())
        duration_sec = estimate_duration_sec(word_count, wpm)
        filename = f"chunk_{index:04d}.wav"
        audio_path = output_dir / filename
        write_wav(audio_path, _placeholder_audio(duration_sec))

        take = {
            "path": filename,
            "sample_rate": SAMPLE_RATE,
            "channels": 1,
            "format": "WAV",
            "duration_sec": duration_sec,
            "sha256": None,
        }

        items.append(
            {
                "id": f"chunk_{index:04d}",
                "index": index,
                "text": text,
                "word_count": word_count,
                "duration_sec": duration_sec,
                "takes": [take],
            }
        )

    return {
        "patch_type": "render_maternal_story",
        "stage": 1,
        "chapter": chapter,
        "source_text": str(source_path),
        "output_dir": str(output_dir),
        "sample_rate": SAMPLE_RATE,
        "max_duration_sec": max_duration_sec,
        "wpm": wpm,
        "item_count": len(items),
        "items": items,
    }


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage-1 scaffolding for rendering maternal story chapters."
    )
    parser.add_argument("text_path", nargs="?", help="Path to input plain-text file")
    parser.add_argument("chapter_title", nargs="?", help="Chapter title")
    parser.add_argument("--text", "-t", dest="text_option", help="Path to input plain-text file")
    parser.add_argument("--chapter", "-c", dest="chapter_option", help="Chapter title")
    parser.add_argument("--output-dir", "-o", default="render_maternal_story_output")
    parser.add_argument("--manifest", default=None, help="Output manifest patch JSON path")
    parser.add_argument("--max-duration", type=float, default=DEFAULT_MAX_DURATION_SEC)
    parser.add_argument("--wpm", type=float, default=DEFAULT_WPM)
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)

    text_path_value = args.text_option or args.text_path
    chapter_value = args.chapter_option or args.chapter_title
    if not text_path_value:
        raise SystemExit("error: a text file path is required")
    if not chapter_value:
        raise SystemExit("error: a chapter title is required")

    source_path = Path(text_path_value)
    if not source_path.is_file():
        raise SystemExit(f"error: text file does not exist: {source_path}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_text = source_path.read_text(encoding="utf-8")
    chunks = chunk_text(raw_text, args.max_duration, args.wpm)

    manifest = build_manifest_patch(
        chapter=chapter_value,
        source_path=source_path,
        output_dir=output_dir,
        chunks=chunks,
        max_duration_sec=args.max_duration,
        wpm=args.wpm,
    )

    manifest_path = (
        Path(args.manifest) if args.manifest else output_dir / "manifest_patch.json"
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {len(chunks)} placeholder WAV files to {output_dir}")
    print(f"Wrote manifest patch to {manifest_path}")


if __name__ == "__main__":
    main()
