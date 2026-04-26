"""One-shot sanity-stat pass over training_data/raw/."""

import json
import random
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent / "training_data" / "raw"
EXPECTED_SOURCE_KEYS = {
    "nhtsa_complaints", "nhtsa_recalls", "repairpal", "carcomplaints", "reddit",
}


def nhtsa_count(blob):
    if not isinstance(blob, dict) or "error" in blob:
        return 0
    for k in ("count", "Count"):
        if k in blob and isinstance(blob[k], int):
            return blob[k]
    r = blob.get("results")
    return len(r) if isinstance(r, list) else 0


def repairpal_count(blob):
    if not isinstance(blob, dict) or "error" in blob:
        return 0
    return len(blob.get("common_repairs", [])) + len(blob.get("common_problems", []))


def carcomp_count(blob):
    if not isinstance(blob, dict) or "error" in blob:
        return 0
    return len(blob.get("worst_problems", [])) + len(blob.get("engine_problems", []))


def reddit_count(blob):
    if not isinstance(blob, dict) or "error" in blob:
        return 0
    return len(blob.get("posts", [])) + len(blob.get("top_post_comments", []))


# Walk the corpus
all_files = sorted(ROOT.rglob("*.json"))
vehicle_dirs = sorted(p for p in ROOT.iterdir() if p.is_dir())

total_bytes = sum(f.stat().st_size for f in all_files)
file_sizes = [f.stat().st_size for f in all_files]

# Distribution by make
make_vehicles = defaultdict(set)
for d in vehicle_dirs:
    parts = d.name.split("_", 2)
    if len(parts) >= 2:
        make_vehicles[parts[1]].add(d.name)

# Per-vehicle source counts (vehicle-level sources are memoized,
# so any one file per vehicle has the same data)
vehicle_stats = {}
reddit_per_combo = []
mm_reddit_totals = defaultdict(list)  # (make, model) -> [reddit counts]
parse_errors = []

for f in all_files:
    vehicle = f.parent.name
    try:
        with f.open(encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception as e:
        parse_errors.append((str(f), repr(e)))
        continue
    sources = d.get("sources", {})

    # Reddit per combo
    r = reddit_count(sources.get("reddit", {}))
    reddit_per_combo.append(r)

    # Per-(make, model) Reddit aggregation
    veh_meta = d.get("vehicle", {})
    mm_key = (veh_meta.get("make", "?"), veh_meta.get("model", "?"))
    mm_reddit_totals[mm_key].append(r)

    # Vehicle-level sources (record once per vehicle)
    if vehicle not in vehicle_stats:
        vehicle_stats[vehicle] = {
            "nhtsa_c": nhtsa_count(sources.get("nhtsa_complaints", {})),
            "nhtsa_r": nhtsa_count(sources.get("nhtsa_recalls", {})),
            "repairpal": repairpal_count(sources.get("repairpal", {})),
            "carcomp": carcomp_count(sources.get("carcomplaints", {})),
        }


def stats_line(label, key):
    vals = [s[key] for s in vehicle_stats.values()]
    avg = sum(vals) / len(vals)
    zeros = sum(1 for v in vals if v == 0)
    return (
        f"  {label:18s} avg={avg:8.1f}  min={min(vals):5d}  "
        f"max={max(vals):6d}  median={int(statistics.median(vals)):5d}  "
        f"vehicles_with_zero={zeros:3d}/{len(vals)}"
    )


# --- Output -------------------------------------------------------------

print(f"Total disk size:  {total_bytes / (1024*1024):.1f} MB  ({total_bytes:,} bytes)")
print(f"Total JSON files: {len(all_files):,}")
print(f"Vehicle dirs:     {len(vehicle_dirs)}")
print(
    f"File size:        min={min(file_sizes):,} B  "
    f"median={int(statistics.median(file_sizes)):,} B  "
    f"max={max(file_sizes):,} B"
)
print()

print(f"=== Distribution by make ({len(make_vehicles)} makes) ===")
for make in sorted(make_vehicles, key=lambda m: -len(make_vehicles[m])):
    print(f"  {make:15s} {len(make_vehicles[make])}")
print()

print(f"=== Per-source coverage (n={len(vehicle_stats)} vehicles) ===")
print(stats_line("NHTSA complaints", "nhtsa_c"))
print(stats_line("NHTSA recalls",    "nhtsa_r"))
print(stats_line("RepairPal items",  "repairpal"))
print(stats_line("CarComplaints",    "carcomp"))
print()
n_combos = len(reddit_per_combo)
reddit_avg = sum(reddit_per_combo) / n_combos
reddit_zeros = sum(1 for x in reddit_per_combo if x == 0)
print(f"=== Reddit per (vehicle, code) (n={n_combos:,} combos) ===")
print(
    f"  avg={reddit_avg:.2f}  min={min(reddit_per_combo)}  "
    f"max={max(reddit_per_combo)}  median={int(statistics.median(reddit_per_combo))}  "
    f"combos_with_zero={reddit_zeros:,} ({100*reddit_zeros/n_combos:.1f}%)"
)
print()

# Sample integrity
random.seed(42)
sample = random.sample(all_files, 5)
print("=== Sample integrity (5 random files) ===")
for f in sample:
    try:
        with f.open(encoding="utf-8") as fh:
            d = json.load(fh)
        keys = set(d.get("sources", {}).keys())
        missing = EXPECTED_SOURCE_KEYS - keys
        extra = keys - EXPECTED_SOURCE_KEYS
        if not missing and not extra:
            status = "OK   "
            note = "all 5 source keys present"
        else:
            status = "FAIL "
            bits = []
            if missing: bits.append(f"missing={sorted(missing)}")
            if extra: bits.append(f"extra={sorted(extra)}")
            note = "; ".join(bits)
        print(f"  [{status}] {f.parent.name}/{f.name}  {note}")
    except Exception as e:
        print(f"  [FAIL ] {f.parent.name}/{f.name}  parse_error={e!r}")
print()

# --- Extras worth noting ------------------------------------------------

print("=== Worth noting ===")

if parse_errors:
    print(f"  {len(parse_errors)} parse errors (showing up to 3):")
    for path, err in parse_errors[:3]:
        print(f"    {path}: {err}")
else:
    print("  All 15,000 files parsed cleanly (no JSON corruption).")

# Reddit recall by (make, model)
mm_reddit_avg = {
    mm: sum(vals) / len(vals)
    for mm, vals in mm_reddit_totals.items()
}
worst_reddit = sorted(mm_reddit_avg.items(), key=lambda kv: kv[1])[:5]
best_reddit = sorted(mm_reddit_avg.items(), key=lambda kv: -kv[1])[:5]
print()
print("  Worst Reddit recall by (make, model) [avg items/code]:")
for (make, model), avg in worst_reddit:
    print(f"    {make} {model}: {avg:.2f}")
print()
print("  Best Reddit recall by (make, model) [avg items/code]:")
for (make, model), avg in best_reddit:
    print(f"    {make} {model}: {avg:.2f}")

# Largest / smallest vehicle by total file size in its dir
dir_sizes = []
for d in vehicle_dirs:
    sz = sum(f.stat().st_size for f in d.iterdir() if f.is_file())
    dir_sizes.append((d.name, sz))
dir_sizes.sort(key=lambda kv: -kv[1])
print()
print("  Largest vehicles by total dir size:")
for name, sz in dir_sizes[:3]:
    print(f"    {name}: {sz / (1024*1024):.2f} MB")
print("  Smallest vehicles by total dir size:")
for name, sz in dir_sizes[-3:]:
    print(f"    {name}: {sz / (1024*1024):.2f} MB")

# Vehicles where ALL four memoized sources returned 0
all_zero = [
    v for v, s in vehicle_stats.items()
    if s["nhtsa_c"] == 0 and s["nhtsa_r"] == 0 and s["repairpal"] == 0 and s["carcomp"] == 0
]
print()
print(f"  Vehicles where ALL four memoized sources returned 0: {len(all_zero)}")
for v in all_zero[:10]:
    print(f"    {v}")
