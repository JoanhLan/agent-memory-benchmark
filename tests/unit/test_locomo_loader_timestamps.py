"""Tests for LoCoMo loader timestamp population."""

from __future__ import annotations

from benchmark_data.locomo_loader import _parse_official_locomo_row


def test_parse_official_locomo_row_assigns_message_timestamps():
    row = {
        "sample_id": "conv-test",
        "conversation": {
            "session_1_date_time": "1:56 pm on 8 May, 2023",
            "session_1": [
                {"speaker": "Alice", "text": "Hello"},
                {"speaker": "Bob", "text": "Hi there"},
            ],
        },
        "qa": [],
    }
    persona = _parse_official_locomo_row(row, 0)
    assert persona is not None
    assert len(persona.sessions) == 1
    session = persona.sessions[0]
    assert session.started_at == "2023-05-08T13:56:00"
    assert len(session.messages) == 2
    assert session.messages[0].timestamp == "2023-05-08T13:56:00"
    assert session.messages[1].timestamp == "2023-05-08T13:57:00"
    assert session.messages[0].role == "user1"
    assert session.messages[1].role == "user2"
    assert session.messages[0].speaker == "Alice"
    assert session.messages[1].speaker == "Bob"


def test_parse_official_locomo_row_maps_speakers_to_user1_user2():
    row = {
        "sample_id": "conv-test",
        "conversation": {
            "session_1": [
                {"speaker": "Caroline", "text": "Hello"},
                {"speaker": "Melanie", "text": "Hi"},
                {"speaker": "Caroline", "text": "Again"},
            ],
        },
        "qa": [],
    }
    persona = _parse_official_locomo_row(row, 0)
    assert persona is not None
    msgs = persona.sessions[0].messages
    assert [m.role for m in msgs] == ["user1", "user2", "user1"]
    assert [m.speaker for m in msgs] == ["Caroline", "Melanie", "Caroline"]


def test_parse_official_locomo_row_no_date_time_leaves_timestamps_none():
    row = {
        "sample_id": "conv-test",
        "conversation": {
            "session_1": [
                {"speaker": "Alice", "text": "Hello"},
            ],
        },
        "qa": [],
    }
    persona = _parse_official_locomo_row(row, 0)
    assert persona is not None
    assert persona.sessions[0].started_at is None
    assert persona.sessions[0].messages[0].timestamp is None
