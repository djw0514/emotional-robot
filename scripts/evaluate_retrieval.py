"""Compare keyword and actual local Chinese embedding retrieval on fixed synthetic data."""

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

from emotional_robot.app import create_app
from emotional_robot.config import Settings
from emotional_robot.memory import recall
from emotional_robot.security import issue_user
from fastapi.testclient import TestClient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="evals/results/chinese-retrieval.json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    cases = json.loads((root / "evals/chinese-retrieval.json").read_text(encoding="utf-8"))
    private = root / "data/private"
    private.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="retrieval-eval-", dir=private) as directory:
        settings = Settings(
            database_url="sqlite:///" + str(Path(directory) / "eval.db"),
            demo_mode=False,
            provider="demo",
            auto_worker=False,
            embedding_provider="local",
            embedding_cache_dir=root / "data/private/models",
            deletion_ledger_path=Path(directory) / "deletions.sqlite",
        )
        app = create_app(settings)
        results, durations = [], []
        with app.state.factory.begin() as session:
            user, token = issue_user(session, "合成评测用户")
            user_id = user.id
        headers = {"Authorization": "Bearer " + token}
        with TestClient(app) as client:
            ids = {}
            for memory in cases["memories"]:
                response = client.post(
                    "/v1/memories", headers=headers, json={"content": memory["content"]}
                )
                response.raise_for_status()
                ids[memory["id"]] = response.json()["id"]
            for _ in range(100):
                if not app.state.worker.run_once():
                    break
            for memory in cases["memories"]:
                expected = ids[memory["id"]]
                for query in memory["queries"]:
                    with app.state.factory() as session:
                        lexical = recall(session, user_id, "companion", query, 5)
                    start = time.perf_counter()
                    response = client.get(
                        "/v1/memories", params={"query": query, "limit": 5}, headers=headers
                    )
                    response.raise_for_status()
                    data = response.json()
                    if data["mode"] != "hybrid":
                        raise RuntimeError("Local model unavailable; run robot prepare-model first")
                    durations.append((time.perf_counter() - start) * 1000)
                    dense_ids, lexical_ids = (
                        [x["id"] for x in data["items"]],
                        [x["id"] for x in lexical],
                    )
                    results.append(
                        {
                            "case_id": memory["id"],
                            "query": query,
                            "keyword_top1": bool(lexical_ids and lexical_ids[0] == expected),
                            "keyword_recall5": expected in lexical_ids,
                            "hybrid_top1": bool(dense_ids and dense_ids[0] == expected),
                            "hybrid_recall5": expected in dense_ids,
                        }
                    )
        summary = {
            "questions": len(results),
            "memories": len(cases["memories"]),
            "model": settings.embedding_model,
            "model_id": app.state.retriever.model_id,
            "dimensions": settings.embedding_dimensions,
            "threshold": settings.semantic_min_score,
            "p50_ms": round(statistics.median(durations), 2),
            "p95_ms": round(sorted(durations)[int(0.95 * (len(durations) - 1))], 2),
            **{
                key: round(sum(row[key] for row in results) / len(results), 4)
                for key in ("keyword_top1", "keyword_recall5", "hybrid_top1", "hybrid_recall5")
            },
        }
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
