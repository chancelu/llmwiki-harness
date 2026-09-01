"""Engine benchmark — how do the three search engines scale with vault size?

Generates synthetic vaults of N Markdown notes, then measures:
  - index build time (sqlite; python/ripgrep have no build step)
  - per-query latency for representative queries (EN multiword, CJK, rare token)
  - LinkGraph.rebuild() cost
  - memory-strength bookkeeping overhead (record_recall / strengths)

Run from the repo root:  python bench/bench_engines.py [N ...]
Default scales: 1000 10000 30000
"""

import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llmwiki.core.graph import LinkGraph
from llmwiki.core.indexer import IndexRegistry

SCHEMA_DIRS = ["entities", "concepts", "chronicle/daily"]

VOCAB = (
    "agent memory context retrieval embedding vector database index token "
    "prompt injection sandbox workflow pipeline cache latency throughput "
    "scheduler planner executor monitor adapter registry fusion ranking"
).split()
CJK_VOCAB = ["知识", "图谱", "记忆", "检索", "模型", "上下文", "向量", "索引", "遗忘", "曲线"]

# Queries: multiword EN, CJK bigram-split, rare single token
QUERIES = [
    "zorblax handshake design",
    "知识图谱遗忘曲线",
    "quixotic",
]


def generate_vault(root: Path, n: int, seed: int = 42) -> None:
    rng = random.Random(seed)
    for d in ("entities", "concepts"):
        (root / d).mkdir(parents=True, exist_ok=True)
    for i in range(n):
        layer = "entities" if i % 5 else "concepts"
        words = " ".join(rng.choice(VOCAB) for _ in range(40))
        cjk = "".join(rng.choice(CJK_VOCAB) for _ in range(20))
        extra = ""
        if i % 97 == 0:
            extra += "\nThe zorblax handshake design notes.\n"
        if i % 89 == 0:
            extra += "\n讨论知识图谱与遗忘曲线的结合。\n"
        if i % 331 == 0:
            extra += "\nA quixotic detour.\n"
        link = f"\nSee [[note-{(i + 1) % n}]].\n" if i % 3 == 0 else ""
        text = f"# Note {i}\n\n{words}\n\n{cjk}\n{extra}{link}"
        (root / layer / f"note-{i}.md").write_text(text, encoding="utf-8")


def bench_scale(root: Path, n: int) -> dict:
    vault = root / f"vault-{n}"
    vault.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    generate_vault(vault, n)
    gen_s = time.perf_counter() - t0

    out = {"notes": n, "generate_s": round(gen_s, 2), "engines": {}}

    for engine in ("python", "ripgrep", "sqlite"):
        reg = IndexRegistry(vault, SCHEMA_DIRS, engine_names=[engine])
        if engine not in reg.engines:
            out["engines"][engine] = "unavailable"
            continue
        try:
            t0 = time.perf_counter()
            reg.build(force=True)
            build_s = time.perf_counter() - t0

            lat = []
            hits = 0
            for q in QUERIES:
                t1 = time.perf_counter()
                res = reg.search(q, top_k=5)
                lat.append(time.perf_counter() - t1)
                hits += len(res)
            out["engines"][engine] = {
                "build_s": round(build_s, 2),
                "query_ms": [round(x * 1000, 1) for x in lat],
                "avg_ms": round(sum(lat) / len(lat) * 1000, 1),
                "hits": hits,
            }
        finally:
            reg.close()

    graph = LinkGraph(vault)
    try:
        t0 = time.perf_counter()
        stats = graph.rebuild()
        graph_build_s = time.perf_counter() - t0

        recall_paths = [f"entities/note-{i}.md" for i in range(0, min(n, 1000))]
        t0 = time.perf_counter()
        graph.record_recall(recall_paths)
        recall_ms = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        graph.strengths(recall_paths)
        strengths_ms = (time.perf_counter() - t0) * 1000

        out["graph"] = {
            "rebuild_s": round(graph_build_s, 2),
            "edges": stats["links"],
            "record_recall_1k_ms": round(recall_ms, 1),
            "strengths_1k_ms": round(strengths_ms, 1),
        }
    finally:
        graph.close()

    return out


def main() -> None:
    scales = [int(x) for x in sys.argv[1:]] or [1000, 10000, 30000]
    bench_root = Path(sys.argv[0]).resolve().parent / ".bench_data"
    bench_root.mkdir(exist_ok=True)

    results = []
    for n in scales:
        print(f"=== {n} notes ===", flush=True)
        r = bench_scale(bench_root, n)
        results.append(r)
        print(json.dumps(r, ensure_ascii=False, indent=2), flush=True)

    out_path = bench_root / "results.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nresults → {out_path}")


if __name__ == "__main__":
    main()
