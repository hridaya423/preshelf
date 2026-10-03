"""Download a contiguous subset of RGB frames from the SLAM&Render zip on Zenodo.

Zenodo throttles to ~1 MB/s per IP, so instead of the full 1.7 GB zip this
fetches only the byte ranges covering the wanted entries (plus the central
directory) into a sparse file, then extracts them with zipfile.
"""
import concurrent.futures as cf
import os
import urllib.request
import zipfile

URL = "https://zenodo.org/api/records/15000694/files/3-natural-tr.zip/content"
TOTAL = 1734485275
ZIP_PATH = "data/3-natural-tr-partial.zip"
N_FRAMES = 900  # 30 s at 30 fps
START_IDX = 900
CHUNK = 16 * 1024 * 1024
WORKERS = 12
# Byte ranges already present in ZIP_PATH (from earlier runs).
HAVE = [(1142000280, 1490585821)]


def fetch_range(start: int, end: int, retries: int = 4) -> bytes:
    req = urllib.request.Request(URL, headers={"Range": f"bytes={start}-{end}"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if len(data) == end - start + 1:
                return data
        except Exception as e:
            print(f"range {start}-{end} attempt {attempt + 1}: {e}", flush=True)
    raise RuntimeError(f"failed range {start}-{end}")


def main() -> None:
    if not os.path.exists(ZIP_PATH):
        # Central directory lives at the end of the file; fetch the last 2 MB.
        tail = fetch_range(TOTAL - 2 * 1024 * 1024, TOTAL - 1)
        with open(ZIP_PATH, "wb") as f:
            f.truncate(TOTAL)
            f.seek(TOTAL - len(tail))
            f.write(tail)

    zf = zipfile.ZipFile(ZIP_PATH)
    rgb = sorted(
        (i for i in zf.infolist()
         if i.filename.startswith("3-natural-tr/rgb/")
         and i.filename.endswith(".png")
         and not os.path.basename(i.filename).startswith("._")),
        key=lambda i: i.filename,
    )
    wanted = rgb[START_IDX:START_IDX + N_FRAMES]
    print(f"{len(rgb)} rgb frames; fetching {len(wanted)} starting at {wanted[0].filename}")

    # Each entry occupies [header_offset, next entry's header_offset).
    infos = zf.infolist()
    sorted_offsets = sorted(i.header_offset for i in infos)
    end_of = {off: (sorted_offsets[k + 1] if k + 1 < len(sorted_offsets) else TOTAL)
              for k, off in enumerate(sorted_offsets)}
    ranges = sorted((i.header_offset, end_of[i.header_offset]) for i in wanted)

    # Merge ranges separated by small gaps (interleaved depth entries).
    merged = []
    for s, e in ranges:
        if merged and s - merged[-1][1] < 262144:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])

    # Subtract ranges we already have.
    pieces = []
    for s, e in merged:
        for hs, he in HAVE:
            if hs <= s < he:
                s = he
            if s < hs < e:
                pieces.append((s, hs))
                s = he
        if s < e:
            pieces.append((s, e))
    total_bytes = sum(e - s for s, e in pieces)
    print(f"byte ranges: {len(pieces)} pieces, {total_bytes / 1e6:.0f} MB to fetch")

    chunks = []
    for s, e in pieces:
        chunks += [(c, min(c + CHUNK, e) - 1) for c in range(s, e, CHUNK)]
    done = 0
    with cf.ThreadPoolExecutor(WORKERS) as ex, open(ZIP_PATH, "r+b") as f:
        futs = {ex.submit(fetch_range, s, e): s for s, e in chunks}
        for fut in cf.as_completed(futs):
            f.seek(futs[fut])
            f.write(fut.result())
            done += 1
            print(f"{done}/{len(chunks)} chunks", flush=True)

    zf = zipfile.ZipFile(ZIP_PATH)
    os.makedirs("data/3-natural-tr/rgb", exist_ok=True)
    for i in wanted:
        zf.extract(i, "data")
    print("extracted", len(wanted))


if __name__ == "__main__":
    main()
