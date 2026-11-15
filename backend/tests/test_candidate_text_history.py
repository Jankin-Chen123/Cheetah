from types import SimpleNamespace

from app.modules.outreach.router import candidate_view


def test_candidate_history_restores_only_own_submitted_turns_without_internal_data():
    case = SimpleNamespace(
        revision=4,
        status="ended",
        stop_status="none",
        snapshot={"fixture_only": True},
        session_data={
            "preflight": {"interested": True, "confirmed": True},
            "answers": [
                {
                    "id": "a1",
                    "text": "本人的回答",
                    "question": {"question": "本人职责？"},
                    "actor_type": "candidate_invitation",
                    "internal": "private",
                },
                {
                    "text": "后台隔离样例",
                    "question": {"question": "开发问题"},
                    "actor_type": "fixture",
                },
            ],
        },
    )
    history = candidate_view(case)["turn_history"]
    assert history == [{"question": "本人职责？", "answer": "本人的回答"}]
