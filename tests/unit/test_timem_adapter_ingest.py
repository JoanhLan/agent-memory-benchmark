"""Tests for TiMEM adapter ingest payload."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from adapters.timem_adapter import TiMEMAdapter, _message_payload
from models.records import LoCoMoMessage


def test_message_payload_prefers_speaker_over_role():
    msg = LoCoMoMessage(
        role="user1",
        content="hi",
        timestamp="2023-05-08T13:56:00",
        speaker="Caroline",
    )
    assert _message_payload(msg) == {
        "role": "Caroline",
        "content": "hi",
        "timestamp": "2023-05-08T13:56:00",
    }


def test_message_payload_falls_back_to_role_without_speaker():
    msg = LoCoMoMessage(role="user1", content="hi")
    assert _message_payload(msg) == {"role": "user1", "content": "hi"}
    assert "timestamp" not in _message_payload(msg)


def test_message_payload_includes_timestamp_when_present():
    msg = LoCoMoMessage(role="user", content="hi", timestamp="2023-05-08T13:56:00")
    assert _message_payload(msg) == {
        "role": "user",
        "content": "hi",
        "timestamp": "2023-05-08T13:56:00",
    }


def test_message_payload_omits_timestamp_when_absent():
    msg = LoCoMoMessage(role="user", content="hi")
    assert _message_payload(msg) == {"role": "user", "content": "hi"}
    assert "timestamp" not in _message_payload(msg)


@pytest.mark.asyncio
async def test_ingest_chunk_posts_speaker_and_timestamp_in_json_body():
    adapter = TiMEMAdapter(client=httpx.AsyncClient())
    captured: dict = {}

    async def fake_post(url, *, headers=None, json=None):
        captured["json"] = json
        return httpx.Response(
            200,
            json=[{"id": "m1"}],
            request=httpx.Request("POST", url),
        )

    with patch.object(adapter._client, "post", AsyncMock(side_effect=fake_post)):
        result = await adapter._ingest_message_chunk(
            "timem_run_persona",
            "run_session_00",
            [
                LoCoMoMessage(
                    role="user1",
                    content="a",
                    timestamp="2023-05-08T13:56:00",
                    speaker="Caroline",
                ),
                LoCoMoMessage(
                    role="user2",
                    content="b",
                    timestamp="2023-05-08T13:57:00",
                    speaker="Melanie",
                ),
            ],
        )

    assert result.success is True
    messages = captured["json"]["messages"]
    assert messages[0]["role"] == "Caroline"
    assert messages[1]["role"] == "Melanie"
    assert messages[0]["timestamp"] == "2023-05-08T13:56:00"
    assert messages[1]["timestamp"] == "2023-05-08T13:57:00"
    await adapter.close()


@pytest.mark.asyncio
async def test_ingest_chunk_accepts_202_task_without_polling():
    adapter = TiMEMAdapter(client=httpx.AsyncClient())

    async def fake_post(url, *, headers=None, json=None):
        return httpx.Response(
            202,
            json={
                "task_id": "task-1",
                "status": "pending",
                "poll_url": "/api/v1/memory/memory-generation/tasks/task-1",
            },
            request=httpx.Request("POST", url),
        )

    with patch.object(adapter._client, "post", AsyncMock(side_effect=fake_post)):
        result = await adapter._ingest_message_chunk(
            "timem_run_persona",
            "run_session_00",
            [LoCoMoMessage(role="user1", content="a", speaker="Alice")],
        )

    assert result.success is True
    assert result.memory_count == 0
    assert result.raw.get("accepted") is True
    assert result.raw.get("task_id") == "task-1"
    await adapter.close()


@pytest.mark.asyncio
async def test_ingest_chunk_without_timestamps():
    adapter = TiMEMAdapter(client=httpx.AsyncClient())
    captured: dict = {}

    async def fake_post(url, *, headers=None, json=None):
        captured["json"] = json
        return httpx.Response(
            200,
            json=[{"id": "m1"}],
            request=httpx.Request("POST", url),
        )

    with patch.object(adapter._client, "post", AsyncMock(side_effect=fake_post)):
        await adapter._ingest_message_chunk(
            "timem_run_persona",
            "run_session_00",
            [LoCoMoMessage(role="user", content="a")],
        )

    assert "timestamp" not in captured["json"]["messages"][0]
    await adapter.close()
