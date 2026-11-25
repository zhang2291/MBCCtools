#!/usr/bin/env python3
"""Sync S-Rank Sinner square avatars from path-to-nowhere.fandom.com into resource/base/image/avatars."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import io
import json
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request
import uuid

try:
    from PIL import Image, ImageOps
except ImportError:
    Image = None
    ImageOps = None

WIKI_API = "https://path-to-nowhere.fandom.com/api.php"
USER_AGENT = "MBCCtools-AvatarSync/1.0"
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "resource" / "base" / "image" / "avatars"

CN_LINE_RE = re.compile(r"\|\s*Name_CN\s*=\s*([^\n|{}]+)")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
TAG_RE = re.compile(r"<[^>]+>")
SEP_RE = re.compile(r"[•・·]")
FORBIDDEN_FS_RE = re.compile(r'[\\/:*?"<>|]')


def api_get(params: dict[str, str | int]) -> dict:
    query = urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(f"{WIKI_API}?{query}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_s_rank_titles() -> list[str]:
    titles: list[str] = []
    cmcontinue: str | None = None
    while True:
        params: dict[str, str | int] = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": "Category:S-Rank_Sinners",
            "cmtype": "page",
            "cmlimit": 500,
        }
        if cmcontinue:
            params["cmcontinue"] = cmcontinue
        data = api_get(params)
        for item in data.get("query", {}).get("categorymembers", []):
            title = str(item.get("title", "")).strip()
            if title:
                titles.append(title)
        cmcontinue = data.get("continue", {}).get("cmcontinue")
        if not cmcontinue:
            break
    return sorted(dict.fromkeys(titles))


def parse_cn_name(page_title: str, wikitext: str) -> str:
    cleaned = COMMENT_RE.sub("", wikitext)
    m = CN_LINE_RE.search(cleaned)
    raw = m.group(1) if m else ""
    raw = raw.split("<br")[0]
    raw = TAG_RE.sub("", raw)
    raw = raw.split("/")[0]
    raw = raw.replace("[[", "").replace("]]", "").strip()
    raw = raw.strip("+ ").strip()
    raw = SEP_RE.sub("·", raw)
    raw = FORBIDDEN_FS_RE.sub("", raw).strip("+ ").strip()
    if raw:
        return raw
    return FORBIDDEN_FS_RE.sub("", SEP_RE.sub("·", page_title)).strip()


def fetch_cn_names(titles: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for i in range(0, len(titles), 40):
        chunk = titles[i : i + 40]
        data = api_get({
            "action": "query",
            "titles": "|".join(chunk),
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
        })
        for page in data.get("query", {}).get("pages", {}).values():
            title = str(page.get("title", "")).strip()
            if not title or "missing" in page:
                continue
            revs = page.get("revisions", [])
            wikitext = revs[0].get("slots", {}).get("main", {}).get("*", "") if revs else ""
            mapping[title] = parse_cn_name(title, wikitext)
    return mapping


def _wiki_file_key(file_title: str) -> str:
    return file_title.removeprefix("File:").replace(" ", "_")


def resolve_image_urls(titles: list[str]) -> dict[str, str]:
    urls: dict[str, str] = {}
    remaining = list(titles)
    for suffix in ("_Icon.png", "_Prisonphoto_Icon.png"):
        if not remaining:
            break
        expected = {f"{t.replace(' ', '_')}{suffix}": t for t in remaining}
        file_titles = [f"File:{k}" for k in expected]
        for i in range(0, len(file_titles), 40):
            chunk = file_titles[i : i + 40]
            data = api_get({
                "action": "query",
                "titles": "|".join(chunk),
                "prop": "imageinfo",
                "iiprop": "url|size",
            })
            norm_map: dict[str, str] = {}
            for entry in data.get("query", {}).get("normalized", []):
                norm_map[entry["to"]] = entry["from"]
            for page in data.get("query", {}).get("pages", {}).values():
                if "missing" in page or not page.get("imageinfo"):
                    continue
                ii = page["imageinfo"][0]
                url = ii.get("url")
                if not url:
                    continue
                page_title = page.get("title", "")
                orig = norm_map.get(page_title, page_title)
                key = _wiki_file_key(orig)
                sinner = expected.get(key) or expected.get(_wiki_file_key(page_title))
                if sinner and sinner not in urls:
                    urls[sinner] = url
        remaining = [t for t in remaining if t not in urls]
    return urls


def strip_viewer_backdrop(rgba: "Image.Image") -> "Image.Image":
    """Clear Chromium standalone-image #e6e6e6 corner fill back to transparent alpha."""
    w, h = rgba.size
    if w <= 0 or h <= 0:
        return rgba
    px = rgba.load()
    corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]

    def is_gray_bg(c: tuple[int, int, int, int]) -> bool:
        r, g, b, a = c
        return a >= 250 and abs(r - 230) <= 8 and abs(g - 230) <= 8 and abs(b - 230) <= 8

    stack = [pt for pt in corners if is_gray_bg(px[pt[0], pt[1]])]
    if not stack:
        return rgba
    visited = set(stack)
    while stack:
        x, y = stack.pop()
        px[x, y] = (0, 0, 0, 0)
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited and is_gray_bg(px[nx, ny]):
                visited.add((nx, ny))
                stack.append((nx, ny))
    return rgba


def save_avatar_bytes(raw_bytes: bytes, dest: Path, size: int, strip_backdrop: bool = False) -> None:
    tmp = dest.with_name(f".tmp-{uuid.uuid4().hex}{dest.suffix}")
    try:
        if Image is not None and ImageOps is not None and dest.suffix.lower() == ".webp":
            with Image.open(io.BytesIO(raw_bytes)) as im:
                rgba = im.convert("RGBA")
                if strip_backdrop:
                    rgba = strip_viewer_backdrop(rgba)
                fitted = ImageOps.fit(rgba, (size, size), method=Image.Resampling.LANCZOS)
                fitted.save(tmp, format="WEBP", quality=85, method=6)
        else:
            tmp.write_bytes(raw_bytes)
        tmp.replace(dest)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def import_local_dir(src_dir: Path, out_dir: Path, size: int, force: bool) -> int:
    titles = fetch_s_rank_titles()
    cn_names = fetch_cn_names(titles)
    lookup: dict[str, str] = {}
    for title in titles:
        cn = cn_names.get(title, title)
        lookup[re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "", title).lower()] = cn
        lookup[re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "", cn).lower()] = cn
    out_dir.mkdir(parents=True, exist_ok=True)
    imported = 0
    for src in sorted(src_dir.iterdir()):
        if not src.is_file() or src.suffix.lower() not in (".png", ".webp", ".jpg", ".jpeg"):
            continue
        stem = re.sub(r"^(?:step_\d+_shot_\d+_)", "", src.stem)
        stem = re.sub(r"(?:_Prisonphoto_Icon|_Icon)$", "", stem)
        key = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "", stem).lower()
        cn = lookup.get(key)
        if not cn:
            print(f"[SKIP-UNMAPPED] {src.name}")
            continue
        dest = out_dir / f"{cn}.webp"
        if dest.is_file() and not force:
            continue
        save_avatar_bytes(src.read_bytes(), dest, size, strip_backdrop=True)
        imported += 1
        print(f"[IMPORTED] {src.name} -> {dest.name} ({dest.stat().st_size / 1024:.1f} KB)")
    return imported


def download_one(url: str, targets: list[Path], size: int) -> tuple[str, int]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=25) as resp:
        data = resp.read()
    for target in targets:
        save_avatar_bytes(data, target, size)
    return targets[0].name, targets[0].stat().st_size


def main() -> int:
    parser = argparse.ArgumentParser(description="Download S-Rank Sinner avatars from path-to-nowhere.fandom.com")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output avatar directory")
    parser.add_argument("--size", type=int, default=128, help="Output square pixel size (default: 128)")
    parser.add_argument("--from-dir", type=Path, help="Import & compress local PNG/WebP icons instead of downloading")
    parser.add_argument("--force", action="store_true", help="Overwrite existing avatar files")
    parser.add_argument("--dry-run", action="store_true", help="Print resolved names & URLs without downloading")
    args = parser.parse_args()

    if args.from_dir is not None:
        imported = import_local_dir(args.from_dir, args.out, args.size, args.force)
        print(f"Imported {imported} avatar(s) from {args.from_dir} -> {args.out}")
        return 0

    ext = ".webp" if Image is not None else ".png"
    titles = fetch_s_rank_titles()
    cn_names = fetch_cn_names(titles)
    urls = resolve_image_urls(titles)

    missing_urls = [t for t in titles if t not in urls]
    if not args.dry_run:
        args.out.mkdir(parents=True, exist_ok=True)

    jobs: list[tuple[str, str, list[Path]]] = []
    skipped = 0
    for title in titles:
        url = urls.get(title)
        if not url:
            continue
        cn_name = cn_names.get(title, title)
        names = [cn_name]
        # Nox's official CN name is NOX, while game OCR or older records can use 诺克斯
        if cn_name.upper() == "NOX" and "诺克斯" not in names:
            names.append("诺克斯")
        targets = [args.out / f"{n}{ext}" for n in names]
        if not args.force and all((args.out / f"{n}{e}").is_file() for n in names for e in (".webp", ".png") if e == ext):
            skipped += 1
            continue
        jobs.append((title, url, targets))

    if args.dry_run:
        for title, url, targets in jobs:
            print(f"[DRY-RUN] {title} -> {[t.name for t in targets]} : {url}")
        print(f"Total discovered: {len(titles)}, resolvable: {len(urls)}, missing url: {missing_urls}")
        return 0

    downloaded = 0
    failed: list[tuple[str, str]] = []
    if jobs:
        with ThreadPoolExecutor(max_workers=6) as pool:
            future_map = {
                pool.submit(download_one, url, targets, args.size): title
                for title, url, targets in jobs
            }
            for fut in as_completed(future_map):
                title = future_map[fut]
                try:
                    name, size_bytes = fut.result()
                    downloaded += 1
                    print(f"[OK] {title} -> {name} ({size_bytes / 1024:.1f} KB)")
                except Exception as exc:
                    failed.append((title, str(exc)))
                    print(f"[ERR] {title}: {exc}", file=sys.stderr)

    files = [p for p in args.out.iterdir() if p.is_file() and p.suffix.lower() in (".webp", ".png", ".jpg", ".jpeg")]
    total_kb = sum(p.stat().st_size for p in files) / 1024.0
    print(
        f"\nSummary: discovered={len(titles)}, downloaded={downloaded}, skipped={skipped}, "
        f"missing_url={len(missing_urls)} {missing_urls}, failed={len(failed)}, "
        f"total_files={len(files)}, total_size={total_kb:.1f} KB -> {args.out}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
