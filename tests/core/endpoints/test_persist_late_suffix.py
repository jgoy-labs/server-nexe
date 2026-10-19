"""Review 19/10, finding 2: a /v1 JSON reply is persisted with the question `emit` adds later."""
from fastapi import BackgroundTasks

from core.endpoints import chat as chat_mod


def test_the_queued_task_reads_the_question_when_it_runs(monkeypatch):
    seen = []
    monkeypatch.setattr(chat_mod, "persist_v1_turn", lambda app_state, sid, text, **kw: seen.append(text))
    tasks, suffix = BackgroundTasks(), {}
    response = {"choices": [{"message": {"content": "Got it."}, "finish_reason": "stop"}]}
    chat_mod._persist_v1_turn_from_response(response, tasks, object(), "sid", suffix=suffix)
    suffix["question"] = "Vols que ho canviï?"  # `emit` runs after the task was queued
    for task in tasks.tasks:
        task.func(*task.args, **task.kwargs)
    assert seen == ["Got it.\n\nVols que ho canviï?"]


def test_without_a_question_the_reply_is_persisted_as_it_was(monkeypatch):
    seen = []
    monkeypatch.setattr(chat_mod, "persist_v1_turn", lambda app_state, sid, text, **kw: seen.append(text))
    tasks = BackgroundTasks()
    chat_mod._persist_v1_turn_from_response({"choices": [{"message": {"content": "Hi"}}]}, tasks, object(), "sid")
    for task in tasks.tasks:
        task.func(*task.args, **task.kwargs)
    assert seen == ["Hi"]
