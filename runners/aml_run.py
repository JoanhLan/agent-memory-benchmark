"""Run the platform side of an AML text evaluation: Add, Search, then local score."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from adapters.aml_client import AmlClient
from benchmark_data.aml_contract import add_body, search_body
from benchmark_data.aml_loaders import load_samples
from benchmark_data.aml_models import EvalQuestion, EvalSample
from benchmark_data.chunking import chunk_messages
from evaluators.aml_score import (
    answer_prompt,
    complete_chat,
    format_memories,
    judge_prompt,
    parse_boxed_score,
    parse_correct_label,
    score_mcq,
)
from utils.config import PROJECT_ROOT, get_settings

REPORTS = PROJECT_ROOT / "reports"


def _run_dir(run_id: str) -> Path:
    path = REPORTS / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _question_row(sample: EvalSample, question: EvalQuestion) -> dict[str, Any]:
    return {
        "dataset_id": sample.dataset_id,
        "sample_id": sample.sample_id,
        "question_id": question.question_id,
        "question": question.question,
        "gold": question.gold,
        "category": question.category,
        "options": question.options,
        "preference": question.preference,
    }


def run_add(
    *,
    run_id: str,
    dataset_id: str,
    limit: int | None = None,
    paper: dict[str, Any] | None = None,
    paper_path: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    client = AmlClient(
        add_url=settings.aml_add_url,
        search_url=settings.aml_search_url,
        api_key=settings.aml_api_key,
        auth=settings.aml_auth,
        health_url=settings.aml_health_url,
    )
    client.health()
    from benchmark_data.aml_papers import ensure_runnable_dataset

    ensure_runnable_dataset(dataset_id, paper)
    samples = load_samples(dataset_id, limit=limit if paper is None else None, paper=paper)
    chunks_out: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    for sample in samples:
        for question in sample.questions:
            questions.append(_question_row(sample, question))
        for index, chunk in enumerate(chunk_messages(sample.messages)):
            body = add_body(
                run_id=run_id,
                dataset_id=sample.dataset_id,
                sample_id=sample.sample_id,
                chunk_index=index,
                messages=chunk,
            )
            response = client.add(body)
            chunks_out.append(
                {
                    "request_id": body["request_id"],
                    "user_id": body["user_id"],
                    "session_id": body["session_id"],
                    "messages": len(chunk),
                    "success": response.get("success") is True,
                }
            )
    report = {
        "run_id": run_id,
        "dataset_id": dataset_id,
        "paper_id": (paper or {}).get("paper_id"),
        "paper_path": paper_path,
        "paper_tier": (paper or {}).get("tier"),
        "samples": len(samples),
        "questions": len(questions),
        "chunks": len(chunks_out),
        "word_count": "approximate: CJK character or Latin/number token; punctuation is a separator",
        "chunk_rule": "20 messages or 2000 approximate words, whichever comes first",
        "adds": chunks_out,
    }
    directory = _run_dir(run_id)
    _write(directory / "aml_add.json", report)
    _write(
        directory / "aml_questions.json",
        {
            "run_id": run_id,
            "dataset_id": dataset_id,
            "paper_id": (paper or {}).get("paper_id"),
            "paper_path": paper_path,
            "questions": questions,
        },
    )
    return report


def run_search(*, run_id: str) -> dict[str, Any]:
    settings = get_settings()
    client = AmlClient(
        add_url=settings.aml_add_url,
        search_url=settings.aml_search_url,
        api_key=settings.aml_api_key,
        auth=settings.aml_auth,
    )
    manifest = json.loads((_run_dir(run_id) / "aml_questions.json").read_text(encoding="utf-8"))
    hits: list[dict[str, Any]] = []
    for row in manifest["questions"]:
        question = EvalQuestion(
            question_id=row["question_id"],
            question=row["question"],
            gold=row.get("gold") or "",
            category=row.get("category"),
            options=row.get("options"),
            preference=row.get("preference"),
        )
        body = search_body(
            run_id=run_id,
            dataset_id=row["dataset_id"],
            sample_id=row["sample_id"],
            question=question,
        )
        response = client.search(body)
        hits.append(
            {
                "question_id": row["question_id"],
                "user_id": body["user_id"],
                "returned": len(response.get("data") or []),
                "data": response.get("data") or [],
            }
        )
    report = {"run_id": run_id, "dataset_id": manifest["dataset_id"], "top_k": 100, "results": hits}
    _write(_run_dir(run_id) / "aml_search.json", report)
    return report


async def run_score(*, run_id: str) -> dict[str, Any]:
    settings = get_settings()
    answer_key = settings.answer_api_key or settings.ark_api_key
    answer_base = settings.answer_api_base or settings.ark_api_base
    answer_model = settings.answer_model or settings.judge_model
    judge_key = settings.judge_api_key or settings.ark_api_key
    judge_base = settings.judge_api_base or settings.ark_api_base
    judge_model = settings.judge_model
    directory = _run_dir(run_id)
    manifest = json.loads((directory / "aml_questions.json").read_text(encoding="utf-8"))
    search = json.loads((directory / "aml_search.json").read_text(encoding="utf-8"))
    by_id = {row["question_id"]: row for row in search["results"]}
    rows: list[dict[str, Any]] = []
    correct = 0
    for item in manifest["questions"]:
        question = EvalQuestion(
            question_id=item["question_id"],
            question=item["question"],
            gold=item.get("gold") or "",
            category=item.get("category"),
            options=item.get("options"),
            preference=item.get("preference"),
        )
        memories = format_memories(
            (by_id.get(item["question_id"]) or {}).get("data") or [],
            question=question.question,
            options=question.options,
        )
        generated = await complete_chat(
            base_url=answer_base,
            api_key=answer_key,
            model=answer_model,
            prompt=answer_prompt(item["dataset_id"], question, memories),
        )
        prompt = judge_prompt(item["dataset_id"], question, generated)
        if prompt is None:
            verdict = score_mcq(question, generated)
        else:
            judged = await complete_chat(
                base_url=judge_base,
                api_key=judge_key,
                model=judge_model,
                prompt=prompt,
            )
            if item["dataset_id"].startswith("personamem_v2"):
                value = parse_boxed_score(judged)
                verdict = {"correct": value >= 0.5, "score": value, "method": "preference_judge"}
            else:
                ok = parse_correct_label(judged)
                verdict = {"correct": ok, "score": 1.0 if ok else 0.0, "method": "correct_wrong"}
        if verdict["correct"]:
            correct += 1
        rows.append({"question_id": item["question_id"], "category": item.get("category"), **verdict})
    total = len(rows)
    report = {
        "run_id": run_id,
        "dataset_id": manifest["dataset_id"],
        "official": False,
        "note": "Local score uses the public answer-then-judge prompts. It is not the leaderboard score.",
        "answer_model": answer_model,
        "judge_model": judge_model,
        "total": total,
        "correct": correct,
        "accuracy": (correct / total) if total else 0.0,
        "results": rows,
    }
    _write(directory / "aml_score.json", report)
    return report
