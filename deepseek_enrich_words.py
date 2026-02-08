import argparse
import csv
import json
import os
import shutil
import sys
import time
import urllib.request
import urllib.error

def normalize_item(item):
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, list):
        return "；".join(str(x).strip() for x in item if str(x).strip())
    if isinstance(item, dict):
        pos = item.get("词性") or item.get("pos") or item.get("part_of_speech")
        meanings = item.get("词义") or item.get("meaning") or item.get("meanings")
        if isinstance(meanings, list):
            meanings = "；".join(str(x).strip() for x in meanings if str(x).strip())
        if pos and meanings:
            return f"{pos}：{str(meanings).strip()}"
        return json.dumps(item, ensure_ascii=False)
    return str(item).strip()

def extract_json_array(text):
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            snippet = text[start:end + 1]
            try:
                return json.loads(snippet)
            except json.JSONDecodeError:
                return None
    return None

def call_deepseek(words, model, api_key, base_url, timeout, senses):
    system_text = (
        "你是阿拉伯语词典助手。"
        "请按顺序为每个词提供简洁的中文‘词义和词性’。"
        "若词有常见多义，给最多{n}个义项，用“；”分隔；只有一个义项就只给一个。"
        "每个数组元素必须是字符串，格式为“词性：义项1；义项2”。"
        "只输出 JSON 数组，不要输出任何多余文字。"
        "数组长度必须与输入词数一致。"
    )
    system_text = system_text.format(n=senses)
    user_text = "词列表：\n" + "\n".join(f"{i + 1}. {w}" for i, w in enumerate(words))

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.2,
        "top_p": 1,
        "max_tokens": 800,
        "stream": False,
    }

    url = base_url.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")

    raw = raw.lstrip()
    data = json.loads(raw)

    if "error" in data:
        raise RuntimeError(f"API error: {data['error']}")

    content = data["choices"][0]["message"]["content"]
    arr = extract_json_array(content)
    if not isinstance(arr, list):
        raise ValueError("Model output is not a JSON array")
    return arr

def call_with_retries(words, model, api_key, base_url, timeout, retries, backoff, senses):
    last_err = None
    for attempt in range(retries):
        try:
            result = call_deepseek(words, model, api_key, base_url, timeout, senses)
            if len(result) != len(words):
                raise ValueError("Output length mismatch")
            return result
        except Exception as exc:
            last_err = exc
            wait = backoff * (2 ** attempt)
            print(f"[retry {attempt + 1}/{retries}] {exc}. sleep {wait:.1f}s", file=sys.stderr)
            time.sleep(wait)
    raise last_err

def count_existing_rows(path, expected_header):
    if not os.path.exists(path):
        return 0
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header != expected_header:
            raise SystemExit("Output header mismatch. Use --overwrite to rebuild.")
        return sum(1 for _ in reader)

def rewrite_first_rows(input_path, output_path, count, model, api_key, base_url, timeout, retries, backoff, senses):
    if count < 1:
        raise SystemExit("--rewrite-first must be >= 1")

    with open(input_path, "r", encoding="utf-8-sig", newline="") as fin:
        reader = csv.DictReader(fin)
        if not reader.fieldnames or "word" not in reader.fieldnames:
            raise SystemExit("Input CSV must contain a 'word' column")
        words = []
        for row in reader:
            if len(words) >= count:
                break
            words.append(row.get("word", "").strip())

    if len(words) < count:
        raise SystemExit("Input has fewer rows than --rewrite-first")

    results = call_with_retries(
        words,
        model,
        api_key,
        base_url,
        timeout,
        retries,
        backoff,
        senses,
    )
    if len(results) != count:
        raise SystemExit("Output length mismatch")

    results = [normalize_item(x) for x in results]

    with open(output_path, "r", encoding="utf-8-sig", newline="") as fout:
        out_reader = csv.DictReader(fout)
        headers = out_reader.fieldnames or []
        if "meaning_pos" not in headers:
            raise SystemExit("Output missing meaning_pos column")
        rows = list(out_reader)

    if len(rows) < count:
        raise SystemExit("Output has fewer rows than --rewrite-first")

    for i in range(count):
        rows[i]["meaning_pos"] = results[i]

    backup = output_path + ".bak_rewrite"
    shutil.copy2(output_path, backup)

    tmp_path = output_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

    os.replace(tmp_path, output_path)
    print(f"Rewrote first {count} rows. Backup: {backup}")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="common_words_wid.csv")
    p.add_argument("--output", default="common_words_wid_enriched.csv")
    p.add_argument("--batch", type=int, default=10)
    p.add_argument("--limit", type=int, default=0, help="0 means no limit")
    p.add_argument("--start", type=int, default=1, help="1-based row index in input (excluding header)")
    p.add_argument("--senses", type=int, default=1, help="max common senses per word")
    p.add_argument("--rewrite-first", type=int, default=0, help="re-translate first N rows in output")
    p.add_argument("--model", default=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"))
    p.add_argument("--base-url", default=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--retries", type=int, default=3)
    p.add_argument("--backoff", type=float, default=2.0)
    p.add_argument("--sleep", type=float, default=0.0, help="sleep between batches")
    p.add_argument("--overwrite", action="store_true")
    resume_group = p.add_mutually_exclusive_group()
    resume_group.add_argument("--resume", action="store_true", help="resume from existing output if present")
    resume_group.add_argument("--no-resume", action="store_true", help="ignore existing output and start fresh")
    args = p.parse_args()

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("Missing DEEPSEEK_API_KEY")

    if args.rewrite_first:
        rewrite_first_rows(
            args.input,
            args.output,
            args.rewrite_first,
            args.model,
            api_key,
            args.base_url,
            args.timeout,
            args.retries,
            args.backoff,
            args.senses,
        )
        return

    with open(args.input, "r", encoding="utf-8-sig", newline="") as fin:
        reader = csv.DictReader(fin)
        if not reader.fieldnames:
            raise SystemExit("Input CSV has no header")
        if "word" not in reader.fieldnames:
            raise SystemExit("Input CSV must contain a 'word' column")

        out_fields = list(reader.fieldnames) + ["meaning_pos"]

        resume_allowed = not args.no_resume
        if args.resume:
            resume_allowed = True

        processed = 0
        if os.path.exists(args.output) and not args.overwrite and resume_allowed:
            processed = count_existing_rows(args.output, out_fields)
            fout = open(args.output, "a", encoding="utf-8-sig", newline="")
            writer = csv.DictWriter(fout, fieldnames=out_fields)
        else:
            if os.path.exists(args.output) and not args.overwrite and not resume_allowed:
                raise SystemExit("Output exists. Use --overwrite or --resume.")
            fout = open(args.output, "w", encoding="utf-8-sig", newline="")
            writer = csv.DictWriter(fout, fieldnames=out_fields)
            writer.writeheader()

        try:
            if args.start < 1:
                raise SystemExit("--start must be >= 1")
            skip_target = max(processed, args.start - 1)
            skipped = 0
            for _ in range(skip_target):
                if next(reader, None) is None:
                    break
                skipped += 1
            if skipped < skip_target:
                raise SystemExit("Skip target exceeds input rows; aborting.")

            total_written = processed
            batch_rows = []
            batch_words = []

            for row in reader:
                if args.limit and total_written >= args.limit:
                    break

                word = row.get("word", "").strip()
                batch_rows.append(row)
                batch_words.append(word)

                if len(batch_words) == args.batch:
                    results = call_with_retries(
                        batch_words,
                        args.model,
                        api_key,
                        args.base_url,
                        args.timeout,
                        args.retries,
                        args.backoff,
                        args.senses,
                    )
                    for r, meaning in zip(batch_rows, results):
                        r = dict(r)
                        r["meaning_pos"] = normalize_item(meaning)
                        writer.writerow(r)
                        total_written += 1
                    batch_rows = []
                    batch_words = []
                    if args.sleep > 0:
                        time.sleep(args.sleep)

            if batch_words and (not args.limit or total_written < args.limit):
                results = call_with_retries(
                    batch_words,
                    args.model,
                    api_key,
                    args.base_url,
                    args.timeout,
                    args.retries,
                    args.backoff,
                    args.senses,
                )
                for r, meaning in zip(batch_rows, results):
                    r = dict(r)
                    r["meaning_pos"] = normalize_item(meaning)
                    writer.writerow(r)
                    total_written += 1

            print(f"Done. Wrote {total_written} rows to {args.output}")
        finally:
            fout.close()

if __name__ == "__main__":
    main()
