"""Task controls must be imperative, not incidental words in document edits."""
import pytest
from hermes_for_teams.task_routing import classify


@pytest.mark.parametrize('text,intent', [
    ('계약서 취소 조항을 추가해', 'followup'),
    ('계약서 상황을 정리해서 파일에 저장해', 'followup'),
    ('계약서 중단 조건을 수정해', 'followup'),
    ('계약서 변경 이력은?', 'question'),
    ('계약서 작업 멈춰', 'cancel'),
    ('계약서 작업 취소해', 'cancel'),
    ('계약서 작업 중단해', 'cancel'),
    ('cancel contract', 'cancel'),
    ('update contract cancellation clause', 'followup'),
])
def test_control_intent(text, intent):
    assert classify(text=text, tasks=[{'id': 'a', 'label': '계약서' if '계약서' in text else 'contract'}])['intent'] == intent
