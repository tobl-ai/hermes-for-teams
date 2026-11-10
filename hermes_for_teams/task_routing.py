"""Conservative intent hints. Native task authority owns identity, branches and controls.

A classifier never receives sender privileges and never grants access from a label.
Unrecognized follow-ups fail closed; explicit independent requests need no command.
"""
import re


def classify(*, text, tasks, reply_task=None):
    independent = bool(re.search(r'별도로|별개로|따로|독립적으로|\b(separately|independently|another task)\b', text, re.I))
    # A control is an imperative, never a noun mentioned in the artifact.
    cancel = bool(re.search(
        r'^/stop\b|(?:멈춰|중단해|중단해줘|중단해\s*줘|취소해|취소해줘|취소해\s*줘)[.!。\s]*$'
        r'|^\s*(?:stop|cancel)\b', text, re.I))
    if reply_task is not None:
        matches = [task for task in tasks if task['id'] == reply_task]
    else:
        matches = [task for task in tasks if task['label'] and task['label'] in text]
    edit = bool(re.search(r'바꿔|수정해|고쳐|변경해|추가해|저장해|작성해|만들어|정리해|\b(change|edit|revise|update)\b', text, re.I))
    question = not cancel and not edit and bool(re.search(
        r'[?？]\s*$|했어|상황|진행.*어때|설명해\s*줘|뭔지\s*알려\s*줘|무엇인지|\b(status|progress|explain|what is|tell me about)\b', text, re.I))
    if question:
        return {'intent': 'question', 'label': label_for(text)}
    if independent and not cancel:
        return {'intent': 'new', 'label': label_for(text)}
    if len(matches) == 1:
        return {'intent': 'cancel' if cancel else 'followup', 'target': matches[0]['id']}
    if not tasks and not cancel and not text.startswith('/'):
        return {'intent': 'new', 'label': label_for(text)}
    return {'intent': 'clarify'}


def label_for(text):
    # These are labels only, not authorization patterns. Unknown domains remain
    # addressable by replying to their authenticated originating message.
    for label in ('계약서', '발표 자료', '보고서', 'contract', 'presentation', 'report'):
        if label in text:
            return label
    return text.strip()[:40] or '작업'


def register_task_routing(ctx):
    if ctx.get_config('same_thread_enabled', False) is not True:
        return
    from gateway.task_routing import TASK_ROUTING_ABI
    if TASK_ROUTING_ABI != 1:
        raise RuntimeError('same-thread routing requires a tested optional native task authority seam')
    ctx.register_middleware('gateway_task_intent', classify)
