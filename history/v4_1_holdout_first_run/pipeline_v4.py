"""v4: unchanged five-condition intervention; grounded review and valid null handling.

The v3 module is retained verbatim for replay of historical experiments.
No network calls on import. This module never executes a recorded tool call.
"""
import copy
import hashlib
from pathlib import Path
import pipeline as v3
from pipeline import (canonical, digest, source_check, materialize, mechanical_check,
                      validate_schema, obj, OUTCOME, NULL_SPAN, GEN_SCHEMA,
                      GENERATOR, REVIEWER, CONDITIONS, POLICY, public_source, aggregate)

VERSION = 'no-jev-edit-review-v4.1'
GEN_SYSTEM = v3.GEN_SYSTEM  # Deliberately identical; cached editor calls remain reusable.
OUTCOME_POLICY = '''
Evaluate fulfillment of the actual user requests, not the benchmark harness's prose/call
format convention. For each user turn list a short completion criterion covering ALL its
mandatory parts, then evaluate ORIGINAL and BASE. Inspect the whole visible trace, including
the tool definitions and errors. A later user request can clarify scope, but a later unrelated
success does not erase a violation of an earlier separate request.

Evidence hierarchy: executed tool results and documented tool semantics establish actions
and state. Assistant claims/plans and function-call-looking text without a result are NOT
proof an action happened. A delivered prose answer/code artifact can itself be evidence for
an answer request; check factual answers against available tool results. Compare the actual
values, units, identifiers, quantities and user-specified conditions. A general healthy/OK
flag does not override the user's different numeric threshold. Inspect contradictory evidence
before concluding success. Cite it even when an assistant confidently claims otherwise.

Distinguish submitting an operation from its completion. An accepted order can satisfy
'place/submit an order'; Pending/Open alone does not establish an executed acquisition or a
requested post-execution notification. Do not invent fills, refunds or asynchronous effects.
If the wording admits materially different completion criteria that cannot be resolved from
context, use unknown and explain the ambiguity. Record the criterion you actually used.

success: evidence supports ALL mandatory parts, with no unresolved contradictory evidence.
failure: identify a specific wrong action/answer, violated constraint, or visible unfinished
required work. A recovered intermediate error is not itself a final failure.
unknown: essential evidence or interpretation is genuinely unavailable, not just inconvenient.
Quote short exact spans from source message content (JSON content as printed in ORIGINAL).
For a missing action, cite the request and the last relevant observed state/response.
Quotes prove grounding only; the reviewer must reason correctly about their meaning.
For each request, put the relevant raw observed state in tool_evidence FIRST, then compare
it to the request in tool_comparison. An earlier tool result can remain the most recent
observation for a later request. Do not discard it just because a new user turn began.
In tool_evidence, only role=tool messages are allowed. Include the actual relevant values,
not merely a general status flag, when the user gave a threshold or quantity. Use the
execution_evidence index to find observations, including contradictions. If there is no
relevant tool observation, leave tool_evidence empty and say why. A pure requested writing
artifact can be evaluated from the delivered artifact; an empirical state claim cannot be
verified by quoting that same assistant claim. The evidence field may also cite user
requirements and delivered answers. Explicitly compare all factual assertions used to
justify success/no action against the observed state; a false no-action justification is
a wrong answer even when the user phrased the action conditionally.
'''

REVIEW_SYSTEM = POLICY + '''
You are an independent REVIEWER, blind to editor rationale, benchmark grade and earlier
verdicts. Judge the ACTUAL deletion and resulting message. Give safe/unsafe/uncertain and
explain the removed completion claim and whether requested content, error disclosure or
other substantive meaning was lost. Check the five annotations and common BASE. Cite source
message IDs. When candidate is null, use unsafe and 'no candidate'; edit_evidence_ids may be
empty. You may propose a concrete minimal alternative, but do not force one. Null is an
ordinary outcome, not an API error. Numbers and punctuation are not automatic vetoes.
''' + OUTCOME_POLICY + '''
Return one ordered requests entry for EVERY user message. The evidence field contains
message_id and exact quote; do not paraphrase inside quote and do not quote added annotations.
Assess ORIGINAL and BASE separately: deleting a claim must not silently change an answer's
correctness. A suggested_deletion is only a proposed repair and requires a fresh independent
review before admission. Return only the requested strict JSON. Keep criteria and reasons
concise; normally 1-3 short evidence quotes per user turn are sufficient.
'''

EVIDENCE = obj({'message_id': {'type': 'string'}, 'quote': {'type': 'string'}})
REVIEW_SCHEMA = obj({
    'edit_verdict': {'type': 'string', 'enum': ['safe', 'unsafe', 'uncertain']},
    'edit_reason': {'type': 'string'},
    'edit_evidence_ids': {'type': 'array', 'items': {'type': 'string'}},
    'requests': {'type': 'array', 'items': obj({
        'user_id': {'type': 'string'}, 'criterion': {'type': 'string'},
        'tool_evidence': {'type': 'array', 'items': EVIDENCE},
        'tool_comparison': {'type': 'string'},
        'original': OUTCOME, 'base': OUTCOME,
        'evidence': {'type': 'array', 'items': EVIDENCE}, 'reason': {'type': 'string'}})},
    'suggested_deletion': NULL_SPAN})


def generation_payload(record, feedback=None):
    return v3.generation_payload(record, feedback)


def review_payload(record, family):
    p = v3.review_payload(record, family)
    p['messages'][0]['content'] = REVIEW_SYSTEM
    data = __import__('json').loads(p['messages'][1]['content'])
    data['execution_evidence'] = [m for m in record['messages'] if m['role'] == 'tool']
    data['execution_evidence_note'] = 'Verbatim index of original observations, not new evidence. Prior observations may govern later user requests.'
    p['messages'][1]['content'] = canonical(data)
    p['response_format']['json_schema'].update(name='review_edit_v4', schema=REVIEW_SCHEMA)
    return p


def decide(record, family, review):
    validate_schema(review, REVIEW_SCHEMA)
    if family is not None:
        mechanical_check(record, family)
    messages = {m['id']: m for m in record['messages']}
    user_ids = [m['id'] for m in record['messages'] if m['role'] == 'user']
    if [r['user_id'] for r in review['requests']] != user_ids:
        raise ValueError('request_coverage')
    for row in review['requests']:
        if not row['reason'].strip() or not row['criterion'].strip() or not row['tool_comparison'].strip() or not row['evidence']:
            raise ValueError('missing_request_evidence_or_criterion')
        for e in row['evidence'] + row['tool_evidence']:
            if e['message_id'] not in messages or not e['quote'].strip():
                raise ValueError('invalid_evidence_reference')
            content = messages[e['message_id']].get('content', '')
            if not isinstance(content, str) or e['quote'] not in content:
                raise ValueError('evidence_quote_not_in_source')
        if any(messages[e['message_id']]['role'] != 'tool' for e in row['tool_evidence']):
            raise ValueError('tool_evidence_must_be_an_actual_tool_message')
    if not review['edit_reason'].strip() or not set(review['edit_evidence_ids']) <= set(messages):
        raise ValueError('invalid_edit_evidence')
    if family is not None and not review['edit_evidence_ids']:
        raise ValueError('missing_edit_evidence_for_actual_candidate')
    if family is None and review['edit_verdict'] == 'safe':
        raise ValueError('null_cannot_be_safe')

    original = aggregate([r['original'] for r in review['requests']])
    base = aggregate([r['base'] for r in review['requests']])
    reasons = []
    if family is None:
        reasons.append('no_candidate')
    if review['edit_verdict'] != 'safe':
        reasons.append('edit_' + review['edit_verdict'])
    # ANY unresolved request prevents admission, even when another request failed.
    # An aggregate failure must not hide unknown correctness of a separate request.
    if any('unknown' in (r['original'], r['base']) for r in review['requests']):
        reasons.append('outcome_unknown')
    if any(r['original'] != r['base'] for r in review['requests']):
        reasons.append('outcome_changed')
    gold = record.get('source_gold')
    if gold not in ('success', 'failure'):
        reasons.append('source_gold_missing')
    elif original != 'unknown' and original != gold:
        reasons.append('source_gold_disagreement')
    if family is None:
        status = 'rejected'  # A missing candidate is never a technical failure/quarantine family.
    elif not reasons:
        status = 'accepted'
    elif any(x in reasons for x in ('outcome_unknown', 'outcome_changed',
             'source_gold_missing', 'source_gold_disagreement', 'edit_uncertain')):
        status = 'quarantined'
    else:
        status = 'rejected'
    return {'status': status, 'reasons': reasons, 'original_outcome': original,
            'base_outcome': base, 'label_policy': 'visible-evidence-and-benchmark-agreement-v1'}


def protocol_state():
    return {'protocol': VERSION, 'code_hash': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'v3_dependency_hash': hashlib.sha256(Path(v3.__file__).read_bytes()).hexdigest(),
            'generation_prompt_hash': digest(GEN_SYSTEM), 'review_prompt_hash': digest(REVIEW_SYSTEM),
            'review_schema_hash': digest(REVIEW_SCHEMA), 'generator': GENERATOR, 'reviewer': REVIEWER,
            'conditions': [list(c) for c in CONDITIONS], 'label_policy': 'visible-evidence-and-benchmark-agreement-v1'}
