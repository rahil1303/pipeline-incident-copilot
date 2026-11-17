"""Generate a small, deterministic sample of the Spotify Tracks dataset.

The real dataset (114k rows, Kaggle) cannot be redistributed in this repo, so the
pipeline ships with a synthetic sample that has the same columns, types and
value ranges. Swap in the real CSV at dbt_project/seeds/raw_tracks.csv if you
have it; nothing else needs to change.

Usage:
    python scripts/make_seed.py [--rows 600] [--out dbt_project/seeds/raw_tracks.csv]
"""

from __future__ import annotations

import argparse
import csv
import random
import string
from pathlib import Path

COLUMNS = [
    "track_id", "artists", "album_name", "track_name", "popularity", "duration_ms",
    "explicit", "danceability", "energy", "key", "loudness", "mode", "speechiness",
    "acousticness", "instrumentalness", "liveness", "valence", "tempo",
    "time_signature", "track_genre",
]

GENRES = ["acoustic", "pop", "rock", "jazz", "hip-hop", "edm", "classical", "indie", "metal", "latin"]
WORDS = ["night", "blue", "fire", "river", "echo", "gold", "rain", "city", "dream", "storm",
         "light", "heart", "shadow", "wild", "summer", "ocean", "neon", "glass", "silver", "road"]


def _track_id(rng: random.Random) -> str:
    return "".join(rng.choices(string.ascii_letters + string.digits, k=22))


def _title(rng: random.Random, n: int) -> str:
    return " ".join(w.capitalize() for w in rng.sample(WORDS, n))


def make_rows(n: int, seed: int = 1303) -> list[dict]:
    rng = random.Random(seed)
    artists = [f"{_title(rng, 1)} {_title(rng, 1)}" for _ in range(60)]
    rows = []
    for _ in range(n):
        energy = round(rng.betavariate(2.5, 2), 3)
        rows.append({
            "track_id": _track_id(rng),
            "artists": rng.choice(artists),
            "album_name": _title(rng, 2),
            "track_name": _title(rng, rng.randint(1, 3)),
            "popularity": int(min(100, max(0, rng.gauss(40, 20)))),
            "duration_ms": rng.randint(90_000, 420_000),
            "explicit": rng.random() < 0.15,
            "danceability": round(rng.betavariate(3, 2), 3),
            "energy": energy,
            "key": rng.randint(0, 11),
            # Louder tracks tend to be more energetic; keep strictly negative dB.
            "loudness": round(min(-0.5, -25 + 20 * energy + rng.gauss(0, 3)), 3),
            "mode": rng.randint(0, 1),
            "speechiness": round(rng.betavariate(1.2, 10), 4),
            "acousticness": round(rng.betavariate(1.5, 2.5), 4),
            "instrumentalness": round(rng.betavariate(0.5, 4), 4),
            "liveness": round(rng.betavariate(1.5, 6), 4),
            "valence": round(rng.betavariate(2, 2), 3),
            "tempo": round(rng.uniform(60, 200), 3),
            "time_signature": rng.choice([3, 4, 4, 4, 5]),
            "track_genre": rng.choice(GENRES),
        })
    return rows


def write_csv(rows: list[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rows", type=int, default=600)
    parser.add_argument("--out", type=Path, default=Path("dbt_project/seeds/raw_tracks.csv"))
    args = parser.parse_args()
    write_csv(make_rows(args.rows), args.out)
    print(f"wrote {args.rows} rows to {args.out}")


if __name__ == "__main__":
    main()
