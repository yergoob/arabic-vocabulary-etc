#!/usr/bin/env python3
"""
XTTS batch TTS runner.

Usage examples:
  python xtts_batch_three_voices.py --csv words_id.csv --out_dir tts_out --voice_1 path/to/voice.wav
  python xtts_batch_three_voices.py --voice_1 v1.wav --voice_2 v2.wav --voice_3 v3.wav
  python xtts_batch_three_voices.py --voice_1 v1.wav --voice_2 v2.wav --voice_3 v3.wav --voice_4 v4.wav \
      --voice_names voice1,voice2,voice3,voice4
  python xtts_batch_three_voices.py --voice_1 speaker:en_0

Key parameters:
  --csv            Input CSV file (default: words_id.csv)
  --out_dir        Output directory (default: tts_out)
  --text_col       Column index for text (default: 0)
  --fallback_col   Use this column if text is empty (default: 1)
  --id_col         Column index for output filename (default: 2)
  --start_row      Start from CSV row index (1-based, after header)
  --end_row        End at CSV row index (0 = to end)
  --limit          Limit rows to process (0 = all)
  --skip_existing  Skip if output wav already exists
  --model_name     XTTS model name (default: tts_models/multilingual/multi-dataset/xtts_v2)
  --language       Language code (default: ar)
  --gpu            Use CUDA if available
  --trim_silence   Trim leading/trailing silence
  --top_db         Silence threshold for trimming (default: 30)
  --voice_1        Required. wav/dir or speaker:<name>
  --voice_2        Optional. wav/dir or speaker:<name>
  --voice_3        Optional. wav/dir or speaker:<name>
  --voice_4        Optional. wav/dir or speaker:<name>
  --voice_names    Comma-separated output folder names; count must match voices

Defaults for voice_names (when not provided):
  1 voice -> voice1
  2 voices -> voice1,voice2
  3 voices -> voice1,voice2,voice3
  4 voices -> voice1,voice2,voice3,voice4

Row range:
  --start_row/--end_row apply to CSV data rows (1-based, after header).
  Example: --start_row 101 --end_row 200

Voice input rules:
  - Each --voice_N can be a single wav, a directory of wavs, or speaker:<name>.
  - If a directory is provided, all *.wav files inside are used.
  - --trim_silence removes leading/trailing silence (uses librosa); adjust with --top_db.

Output naming:
  - base name comes from --id_col if that cell is non-empty; otherwise uses row_<index>.
  - output path: {out_dir}/{voice_name}/{base}.wav

Models:
  This script loads one XTTS model per run (set by --model_name).
  To list available models in your environment, try:
    python -m TTS --list_models
    tts --list_models
"""
import argparse
import csv
import sys
from pathlib import Path

from TTS.api import TTS


def trim_wav(path: Path, top_db: int) -> None:
    # Lazy import to keep base deps small when trimming is not used.
    try:
        import librosa
        import soundfile as sf
    except Exception as exc:  # pragma: no cover - runtime env dependent
        raise RuntimeError(
            "Trim requested but librosa/soundfile not available. "
            "Install with: python -m pip install librosa soundfile"
        ) from exc

    y, sr = librosa.load(str(path), sr=None, mono=True)
    y_trim, _ = librosa.effects.trim(y, top_db=top_db)
    sf.write(str(path), y_trim, sr)


def iter_words(csv_path: Path, text_col: int, fallback_col: int | None):
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            return
        for i, row in enumerate(reader, start=1):
            if not row:
                continue
            text = row[text_col] if text_col < len(row) else ""
            if not text and fallback_col is not None and fallback_col < len(row):
                text = row[fallback_col]
            yield i, row, text


def collect_wavs(path: Path) -> list[str]:
    if path.is_dir():
        return [str(p) for p in sorted(path.glob("*.wav"))]
    return [str(path)]


def parse_voice_arg(value: str):
    value = value.strip()
    if value.startswith("speaker:"):
        return {
            "speaker": value.split(":", 1)[1].strip(),
            "speaker_wav": None,
        }
    parts = [p.strip() for p in value.split(",") if p.strip()]
    wavs: list[str] = []
    for part in parts:
        p = Path(part).expanduser()
        if not p.exists():
            raise FileNotFoundError(f"Voice path not found: {p}")
        wavs.extend(collect_wavs(p))
    return {"speaker": None, "speaker_wav": wavs}


def choose_filename(row, id_col: int | None, index: int) -> str:
    if id_col is not None and id_col < len(row):
        _id = row[id_col].strip()
        if _id:
            return _id
    return f"row_{index}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="words_id.csv", help="CSV file path")
    parser.add_argument("--out_dir", default="tts_out", help="Output directory")
    parser.add_argument("--text_col", type=int, default=0, help="Text column index")
    parser.add_argument(
        "--fallback_col",
        type=int,
        default=1,
        help="Fallback column index when text is empty",
    )
    parser.add_argument(
        "--id_col", type=int, default=2, help="Column index used for filename"
    )
    parser.add_argument(
        "--start_row",
        type=int,
        default=1,
        help="Start from CSV row index (1-based, after header)",
    )
    parser.add_argument(
        "--end_row",
        type=int,
        default=0,
        help="End at CSV row index (0 = to end)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Limit rows (0=all)")
    parser.add_argument(
        "--skip_existing", action="store_true", help="Skip if file exists"
    )
    parser.add_argument(
        "--model_name",
        default="tts_models/multilingual/multi-dataset/xtts_v2",
        help="XTTS model name",
    )
    parser.add_argument("--language", default="ar", help="Language code")
    parser.add_argument(
        "--gpu", action="store_true", help="Use GPU (CUDA) if available"
    )
    parser.add_argument(
        "--trim_silence", action="store_true", help="Trim leading/trailing silence"
    )
    parser.add_argument(
        "--top_db",
        type=int,
        default=30,
        help="Silence threshold for trimming (higher trims more)",
    )
    parser.add_argument(
        "--log_every",
        type=int,
        default=50,
        help="Print progress every N rows (0=off)",
    )

    parser.add_argument(
        "--voice_1",
        dest="voice_1",
        required=True,
        help="Voice 1 wav/dir or speaker:<name>",
    )
    parser.add_argument(
        "--voice_2",
        dest="voice_2",
        default="",
        help="Voice 2 wav/dir or speaker:<name>",
    )
    parser.add_argument(
        "--voice_3",
        dest="voice_3",
        default="",
        help="Voice 3 wav/dir or speaker:<name>",
    )
    parser.add_argument(
        "--voice_4",
        dest="voice_4",
        default="",
        help="Voice 4 wav/dir or speaker:<name>",
    )
    parser.add_argument(
        "--voice_names",
        default=None,
        help="Comma-separated folder names for outputs",
    )

    args = parser.parse_args()

    if args.end_row and args.end_row < args.start_row:
        print("--end_row must be >= --start_row (or 0 for no end).", file=sys.stderr)
        return 2

    voice_values = [
        args.voice_1,
        args.voice_2,
        args.voice_3,
        args.voice_4,
    ]
    voice_values = [v.strip() for v in voice_values if v and v.strip()]
    if not voice_values:
        print("At least one voice is required.", file=sys.stderr)
        return 2

    if args.voice_names is None:
        if len(voice_values) == 1:
            voice_names = ["voice1"]
        elif len(voice_values) == 2:
            voice_names = ["voice1", "voice2"]
        elif len(voice_values) == 3:
            voice_names = ["voice1", "voice2", "voice3"]
        else:
            voice_names = ["voice1", "voice2", "voice3", "voice4"]
    else:
        voice_names = [v.strip() for v in args.voice_names.split(",") if v.strip()]
        if len(voice_names) != len(voice_values):
            print(
                "voice_names count must match the number of provided voices.",
                file=sys.stderr,
            )
            return 2

    voices = []
    for name, voice_value in zip(voice_names, voice_values):
        voices.append((name, parse_voice_arg(voice_value)))

    print(f"Voices: {len(voices)}")
    for name, voice in voices:
        if voice["speaker"]:
            print(f"- {name}: speaker={voice['speaker']}")
        else:
            count = len(voice["speaker_wav"])
            print(f"- {name}: {count} wavs")

    out_dir = Path(args.out_dir)
    for name, _ in voices:
        (out_dir / name).mkdir(parents=True, exist_ok=True)

    tts = TTS(args.model_name, gpu=args.gpu)

    processed = 0
    end_row = args.end_row if args.end_row > 0 else None
    for index, row, text in iter_words(Path(args.csv), args.text_col, args.fallback_col):
        if index < args.start_row:
            continue
        if end_row is not None and index > end_row:
            break
        if not text:
            continue
        base = choose_filename(row, args.id_col, index)
        for name, voice in voices:
            out_path = out_dir / name / f"{base}.wav"
            if args.skip_existing and out_path.exists():
                continue
            if voice["speaker"]:
                tts.tts_to_file(
                    text=text,
                    file_path=str(out_path),
                    speaker=voice["speaker"],
                    language=args.language,
                )
            else:
                tts.tts_to_file(
                    text=text,
                    file_path=str(out_path),
                    speaker_wav=voice["speaker_wav"],
                    language=args.language,
                )
            if args.trim_silence:
                trim_wav(out_path, args.top_db)
        processed += 1
        if args.log_every and processed % args.log_every == 0:
            print(f"Processed {processed} rows. Last row index: {index}")
        if args.limit and processed >= args.limit:
            break

    print(f"Done. Generated {processed} words x {len(voices)} voices.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
