#!/usr/bin/env python3
"""
Arabic TTS batch runner (tts-arabic-pytorch).

Usage examples:
  python tts_arabic_words_batch.py --csv words_id.csv --out_dir tts_out --model fastpitch
  python tts_arabic_words_batch.py --model tacotron2 --batch_size 1 --cpu
  python tts_arabic_words_batch.py --model both --vowelizer shakkala

Key parameters:
  --csv                 Input CSV file (default: words_id.csv)
  --out_dir             Output directory (default: tts_out)
  --text_col            Column index for text (default: 0)
  --fallback_col        Use this column if text is empty (default: 1)
  --id_col              Column index for output filename (default: 2)
  --limit               Limit rows to process (0 = all)
  --skip_existing       Skip if output file already exists
  --model               fastpitch | tacotron2 | both (default: fastpitch)
  --fastpitch_checkpoint  Path (relative to repo) for FastPitch checkpoint
  --tacotron_checkpoint   Path (relative to repo) for Tacotron2 checkpoint
  --vocoder_sd          Optional vocoder state dict (relative to repo)
  --vocoder_config      Optional vocoder config (relative to repo)
  --vowelizer           none | shakkala | shakkelha (default: none)
  --batch_size          Batch size (default: 2)
  --speed               Speed (default: 1.0)
  --denoise             Denoise strength (default: 0.005)
  --sample_rate         Output sample rate (default: 22050)
  --ext                 Output extension (default: wav)
  --cpu                 Force CPU (default uses CUDA if available)

Output naming:
  - base name comes from --id_col if that cell is non-empty; otherwise uses row_<index>.
  - output path: {out_dir}/{model_name}/{base}.{ext}

Models:
  - This script uses the local repo at tts-arabic-pytorch (must exist).
  - --model both will generate audio for both FastPitch and Tacotron2.
"""
import argparse
import csv
import os
import re
import sys
from pathlib import Path

import torch
import torchaudio

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR / "tts-arabic-pytorch"


def ensure_repo_on_path() -> None:
    if not REPO_ROOT.exists():
        raise FileNotFoundError(
            f"Repo not found: {REPO_ROOT}. Clone it first."
        )
    # Many repo configs are loaded via relative paths.
    os.chdir(REPO_ROOT)
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))


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


def safe_filename(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    return re.sub(r"[\\/:*?\"<>|]+", "_", value)


def choose_filename(row, id_col: int | None, index: int, ext: str) -> str:
    if id_col is not None and id_col < len(row):
        _id = safe_filename(row[id_col])
        if _id:
            return f"{_id}.{ext}"
    return f"row_{index}.{ext}"


def load_model(model_name: str, checkpoint: str, vocoder_sd: str | None,
               vocoder_config: str | None, device: torch.device,
               vowelizer: str | None):
    if model_name == "fastpitch":
        from models.fastpitch import FastPitch2Wave
        model = FastPitch2Wave(
            checkpoint,
            vocoder_sd=vocoder_sd,
            vocoder_config=vocoder_config,
            vowelizer=vowelizer,
        )
    elif model_name == "tacotron2":
        from models.tacotron2 import Tacotron2Wave
        model = Tacotron2Wave(
            checkpoint,
            vocoder_sd=vocoder_sd,
            vocoder_config=vocoder_config,
            vowelizer=vowelizer,
        )
    else:
        raise ValueError(f"Unsupported model: {model_name}")

    model = model.to(device)
    model.eval()
    return model


def find_invalid_tokens(model, text: str, vowelizer: str | None) -> list[str]:
    try:
        tokens = model.model._tokenize(text, vowelizer=vowelizer)
    except Exception as exc:
        return [f"tokenize_error:{exc}"]

    phon_to_id = getattr(model.model, "phon_to_id", None)
    if not phon_to_id:
        return []

    missing = [tok for tok in tokens if tok not in phon_to_id]
    return missing


def synthesize_csv(
    *,
    model_name: str,
    model,
    csv_path: Path,
    out_dir: Path,
    text_col: int,
    fallback_col: int | None,
    id_col: int | None,
    batch_size: int,
    speed: float | None,
    denoise: float,
    vowelizer: str | None,
    sample_rate: int,
    limit: int,
    skip_existing: bool,
    ext: str,
) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)

    processed = 0
    batch_texts: list[str] = []
    batch_paths: list[Path] = []
    batch_meta: list[tuple[int, str]] = []

    skip_log_path = out_dir / "skipped.csv"
    skip_file = None
    skip_writer = None

    def log_skip(row_index: int, row_id: str, text: str, reason: str) -> None:
        nonlocal skip_file, skip_writer
        if skip_writer is None:
            is_new = not skip_log_path.exists()
            skip_file = skip_log_path.open("a", encoding="utf-8", newline="")
            skip_writer = csv.writer(skip_file)
            if is_new:
                skip_writer.writerow(["row_index", "row_id", "text", "reason"])
        skip_writer.writerow([row_index, row_id, text, reason])

    def flush_batch() -> None:
        nonlocal processed
        if not batch_texts:
            return
        texts = batch_texts
        paths = batch_paths
        metas = batch_meta
        if limit:
            remaining = limit - processed
            if remaining <= 0:
                return
            texts = texts[:remaining]
            paths = paths[:remaining]
            metas = metas[:remaining]

        try:
            wavs = model.tts(
                texts,
                batch_size=batch_size,
                speed=speed,
                denoise=denoise,
                vowelizer=vowelizer,
            )
            for (out_path, wav, meta) in zip(paths, wavs, metas):
                out_path.parent.mkdir(parents=True, exist_ok=True)
                torchaudio.save(str(out_path), wav.unsqueeze(0), sample_rate)
                processed += 1
        except Exception as exc:
            for (text, out_path, meta) in zip(texts, paths, metas):
                row_index, row_id = meta
                try:
                    wav = model.tts(
                        text,
                        batch_size=1,
                        speed=speed,
                        denoise=denoise,
                        vowelizer=vowelizer,
                    )
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    torchaudio.save(str(out_path), wav.unsqueeze(0), sample_rate)
                    processed += 1
                except Exception as exc_item:
                    log_skip(row_index, row_id, text, f"tts_error:{exc_item}")
            log_skip(-1, "", "", f"batch_error:{exc}")

        batch_texts.clear()
        batch_paths.clear()
        batch_meta.clear()

    try:
        for index, row, text in iter_words(csv_path, text_col, fallback_col):
            if not text:
                continue
            filename = choose_filename(row, id_col, index, ext)
            out_path = out_dir / filename
            if skip_existing and out_path.exists():
                continue

            row_id = ""
            if id_col is not None and id_col < len(row):
                row_id = row[id_col].strip()

            missing = find_invalid_tokens(model, text, vowelizer)
            if missing:
                log_skip(index, row_id, text, f"invalid_tokens:{' '.join(missing)}")
                continue

            batch_texts.append(text)
            batch_paths.append(out_path)
            batch_meta.append((index, row_id))

            if len(batch_texts) >= batch_size:
                flush_batch()
                if limit and processed >= limit:
                    break

        flush_batch()
    finally:
        if skip_file is not None:
            skip_file.close()
    return processed


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
    parser.add_argument("--limit", type=int, default=0, help="Limit rows (0=all)")
    parser.add_argument(
        "--skip_existing", action="store_true", help="Skip if file exists"
    )

    parser.add_argument(
        "--model",
        default="fastpitch",
        choices=["fastpitch", "tacotron2", "both"],
        help="Model type",
    )
    parser.add_argument(
        "--fastpitch_checkpoint",
        default="pretrained/fastpitch_ar_adv.pth",
        help="FastPitch checkpoint path (relative to repo)",
    )
    parser.add_argument(
        "--tacotron_checkpoint",
        default="pretrained/tacotron2_ar_adv.pth",
        help="Tacotron2 checkpoint path (relative to repo)",
    )
    parser.add_argument(
        "--vocoder_sd",
        default=None,
        help="Optional vocoder state dict path (relative to repo)",
    )
    parser.add_argument(
        "--vocoder_config",
        default=None,
        help="Optional vocoder config path (relative to repo)",
    )
    parser.add_argument(
        "--vowelizer",
        default="none",
        choices=["none", "shakkala", "shakkelha"],
        help="Optional vowelizer",
    )

    parser.add_argument("--batch_size", type=int, default=2, help="Batch size")
    parser.add_argument("--speed", type=float, default=1.0, help="Speed")
    parser.add_argument("--denoise", type=float, default=0.005, help="Denoise")
    parser.add_argument("--sample_rate", type=int, default=22050, help="Sample rate")
    parser.add_argument("--ext", default="wav", help="Output extension")
    parser.add_argument("--cpu", action="store_true", help="Force CPU")

    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.is_absolute():
        csv_path = (BASE_DIR / csv_path).resolve()

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = (BASE_DIR / out_dir).resolve()

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    ensure_repo_on_path()

    use_cuda = torch.cuda.is_available() and not args.cpu
    device = torch.device("cuda" if use_cuda else "cpu")
    vowelizer = None if args.vowelizer == "none" else args.vowelizer

    total = 0

    if args.model in ("fastpitch", "both"):
        model = load_model(
            "fastpitch",
            args.fastpitch_checkpoint,
            args.vocoder_sd,
            args.vocoder_config,
            device,
            vowelizer,
        )
        fp_out = out_dir / "fastpitch"
        total_fp = synthesize_csv(
            model_name="fastpitch",
            model=model,
            csv_path=csv_path,
            out_dir=fp_out,
            text_col=args.text_col,
            fallback_col=args.fallback_col,
            id_col=args.id_col,
            batch_size=args.batch_size,
            speed=args.speed,
            denoise=args.denoise,
            vowelizer=vowelizer,
            sample_rate=args.sample_rate,
            limit=args.limit,
            skip_existing=args.skip_existing,
            ext=args.ext,
        )
        total += total_fp
        print(f"FastPitch generated: {total_fp}")

    if args.model in ("tacotron2", "both"):
        model = load_model(
            "tacotron2",
            args.tacotron_checkpoint,
            args.vocoder_sd,
            args.vocoder_config,
            device,
            vowelizer,
        )
        tc_out = out_dir / "tacotron2"
        total_tc = synthesize_csv(
            model_name="tacotron2",
            model=model,
            csv_path=csv_path,
            out_dir=tc_out,
            text_col=args.text_col,
            fallback_col=args.fallback_col,
            id_col=args.id_col,
            batch_size=args.batch_size,
            speed=args.speed,
            denoise=args.denoise,
            vowelizer=vowelizer,
            sample_rate=args.sample_rate,
            limit=args.limit,
            skip_existing=args.skip_existing,
            ext=args.ext,
        )
        total += total_tc
        print(f"Tacotron2 generated: {total_tc}")

    print(f"Done. Total generated: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
