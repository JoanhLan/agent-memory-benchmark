"""Tests for optional TiMEM L2 wait during ingest."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adapters.timem_adapter import TiMEMAdapter
from benchmark_jobs import JobOptions
from models.records import LoCoMoMessage, LoCoMoPersona, LoCoMoSession
from runners.ingest_run import _ingest_personas
from utils.config import resolve_ingest_config


def test_job_options_wait_timem_l2_default_false():
    opts = JobOptions.from_dict({})
    assert opts.wait_timem_l2_on_ingest is False


def test_job_options_wait_timem_l2_parses_true():
    opts = JobOptions.from_dict({"wait_timem_l2_on_ingest": True})
    assert opts.wait_timem_l2_on_ingest is True


def test_job_options_memory_language_default_en():
    opts = JobOptions.from_dict({})
    assert opts.memory_language == "en"


def test_job_options_memory_language_parses_zh():
    opts = JobOptions.from_dict({"memory_language": "zh"})
    assert opts.memory_language == "zh"


@pytest.mark.asyncio
async def test_ingest_uses_scoped_timem_session_id():
    adapter = MagicMock(spec=TiMEMAdapter)
    adapter.ingest = AsyncMock(
        return_value=MagicMock(
            success=True,
            latency_ms=1.0,
            memory_count=1,
            error=None,
            metrics={"input_tokens": 1},
            raw={"api_calls": 1, "pair_count": 1, "ingest_mode": "pair"},
        )
    )
    personas = [
        LoCoMoPersona(
            persona_id="conv-26",
            sessions=[
                LoCoMoSession(
                    session_id="conv-26_session_00",
                    persona_id="conv-26",
                    messages=[LoCoMoMessage(role="user", content="hi")],
                )
            ],
            qa_pairs=[],
        )
    ]
    ingest_cfg = resolve_ingest_config()

    with patch("runners.ingest_run.finalize_timem_l2_sessions", new_callable=AsyncMock):
        with patch("runners.ingest_run.run_bounded_tasks_per_key", new_callable=AsyncMock) as mock_bounded:
            async def _run(specs, concurrency, key_concurrency):
                out = []
                for spec in specs:
                    _, _, fn = spec
                    out.append((None, await fn()))
                return out

            mock_bounded.side_effect = _run
            report = await _ingest_personas(
                adapter,
                "timem",
                "LJY-123-new",
                personas,
                ingest_cfg,
                wait_timem_l2_on_ingest=False,
            )

    adapter.ingest.assert_awaited_once()
    call_kwargs = adapter.ingest.await_args.kwargs
    assert call_kwargs["session_id"] == "LJY-123-new_conv-26_session_00"
    assert report.details[0]["session_id"] == "LJY-123-new_conv-26_session_00"
    assert report.details[0]["source_session_id"] == "conv-26_session_00"


@pytest.mark.asyncio
async def test_ingest_skips_l2_finalize_when_disabled():
    adapter = MagicMock(spec=TiMEMAdapter)
    personas = [
        LoCoMoPersona(
            persona_id="p1",
            sessions=[
                LoCoMoSession(
                    session_id="s1",
                    persona_id="p1",
                    messages=[LoCoMoMessage(role="user", content="hi")],
                )
            ],
            qa_pairs=[],
        )
    ]
    ingest_cfg = resolve_ingest_config()

    with patch(
        "runners.ingest_run.finalize_timem_l2_sessions",
        new_callable=AsyncMock,
    ) as mock_finalize:
        with patch("runners.ingest_run.run_bounded_tasks_per_key", new_callable=AsyncMock) as mock_bounded:
            mock_bounded.return_value = [
                (
                    None,
                    {
                        "persona_id": "p1",
                        "user_id": "timem_run_p1",
                        "session_id": "run_s1",
                        "success": True,
                        "latency_ms": 10.0,
                        "input_tokens": 1.0,
                        "memory_count": 1,
                        "api_calls": 1,
                        "pair_count": 1,
                        "error": None,
                    },
                )
            ]
            report = await _ingest_personas(
                adapter,
                "timem",
                "run",
                personas,
                ingest_cfg,
                wait_timem_l2_on_ingest=False,
            )

    mock_finalize.assert_not_called()
    assert report.timem_l2_finalize == {
        "skipped": True,
        "reason": "wait_timem_l2_on_ingest=false",
    }


@pytest.mark.asyncio
async def test_ingest_runs_l2_finalize_when_enabled():
    adapter = MagicMock(spec=TiMEMAdapter)
    personas = [
        LoCoMoPersona(
            persona_id="p1",
            sessions=[
                LoCoMoSession(
                    session_id="s1",
                    persona_id="p1",
                    messages=[LoCoMoMessage(role="user", content="hi")],
                )
            ],
            qa_pairs=[],
        )
    ]
    ingest_cfg = resolve_ingest_config()
    expected_finalize = {"persona_count": 1, "l2_ready_count": 1, "wall_ms": 1.0, "details": []}

    with patch(
        "runners.ingest_run.finalize_timem_l2_sessions",
        new_callable=AsyncMock,
        return_value=expected_finalize,
    ) as mock_finalize:
        with patch("runners.ingest_run.run_bounded_tasks_per_key", new_callable=AsyncMock) as mock_bounded:
            mock_bounded.return_value = [
                (
                    None,
                    {
                        "persona_id": "p1",
                        "user_id": "timem_run_p1",
                        "session_id": "run_s1",
                        "success": True,
                        "latency_ms": 10.0,
                        "input_tokens": 1.0,
                        "memory_count": 1,
                        "api_calls": 1,
                        "pair_count": 1,
                        "error": None,
                    },
                )
            ]
            report = await _ingest_personas(
                adapter,
                "timem",
                "run",
                personas,
                ingest_cfg,
                wait_timem_l2_on_ingest=True,
            )

    mock_finalize.assert_awaited_once()
    assert report.timem_l2_finalize == expected_finalize
