"""Synthetic TypeSafe transport contracts."""
import json

import httpx
import pytest


@pytest.mark.parametrize('status,expected_calls', [(302, 1), (401, 1), (429, 3), (529, 3)])
def test_redirects_errors_and_retry_bound(status, expected_calls):
    from hermes_cli.skills_select_provider import score_payloads, MODEL
    calls = []
    def handler(request):
        calls.append(request)
        assert request.extensions['timeout'] == {'connect': 10, 'read': 30, 'write': 30, 'pool': 30}
        return httpx.Response(status, headers={'location': 'https://elsewhere.invalid'}, text='PRIVATE ERROR BODY')
    with pytest.raises(ValueError, match=f'HTTP {status}') as error:
        score_payloads([{'model': MODEL, 'state': {}, 'questions': {'x': {}}}], 'synthetic-key',
                       transport=httpx.MockTransport(handler), sleep=lambda _: None)
    assert len(calls) == expected_calls
    assert 'PRIVATE ERROR BODY' not in str(error.value)


def test_timeout_is_not_retried_or_leaked():
    from hermes_cli.skills_select_provider import score_payloads
    def handler(request):
        raise httpx.ReadTimeout('synthetic-key and private task')
    with pytest.raises(ValueError, match='transport failed') as error:
        score_payloads([{'questions': {}}], 'synthetic-key', transport=httpx.MockTransport(handler))
    assert 'synthetic-key' not in str(error.value)


def test_oversized_state_rejected_before_network():
    from hermes_cli.skills_select import Skill
    from hermes_cli.skills_select_provider import build_payloads
    with pytest.raises(ValueError, match='safe request limit'):
        build_payloads([Skill('x', 'x', 'small', '')], '漢' * 9000)


def test_duplicate_response_keys_rejected():
    from hermes_cli.skills_select_provider import score_payloads, MODEL
    response = ('{"model":"' + MODEL + '","answers":{"x":{"type":"score","score":9,"score":7,"confidence":1}},'
                '"usage":{"input_tokens":1,"output_tokens":1}}')
    with pytest.raises(ValueError, match='invalid JSON'):
        score_payloads([{'questions': {'x': {}}}], 'synthetic-key',
                       transport=httpx.MockTransport(lambda request: httpx.Response(200, text=response)))



def test_provider_batches_only_metadata_retries_and_keeps_decimals():
    from hermes_cli.skills_select import Skill
    from hermes_cli.skills_select_provider import build_payloads, score_payloads, MODEL, ENDPOINT
    skills = [Skill(str(i), f'name-{i}', 'description', 'PRIVATE BODY') for i in range(3)]
    payloads = build_payloads(skills, 'task', 'context', max_request_bytes=2300)
    assert len(payloads) > 1
    assert 'PRIVATE BODY' not in json.dumps(payloads)
    assert sum(len(p['questions']) for p in payloads) == len(skills)
    calls, sleeps = [], []
    def handler(request):
        calls.append(request)
        assert str(request.url) == ENDPOINT
        assert request.headers['Authorization'] == 'Bearer synthetic-key'
        if len(calls) == 1:
            return httpx.Response(529)
        payload = json.loads(request.content)
        for question in payload['questions'].values():
            assert question['instructions']['skill']['name'].startswith('name-')
            assert len(question['criteria']) == 10
        return httpx.Response(200, json={'model': MODEL, 'answers': {
            k: {'type': 'score', 'score': 7.25, 'confidence': .8} for k in payload['questions']},
            'usage': {'input_tokens': 10, 'output_tokens': 2}})
    scores, usage = score_payloads(payloads, 'synthetic-key', transport=httpx.MockTransport(handler), sleep=sleeps.append)
    assert {s['score'] for s in scores.values()} == {7.25}
    assert len(sleeps) == 1
    assert usage['input_tokens'] == len(payloads) * 10


@pytest.mark.parametrize('answer', [
    {}, {'x': {'type': 'noul', 'score': 8, 'confidence': .8}},
    {'x': {'type': 'score', 'score': float('nan'), 'confidence': .8}},
    {'x': {'type': 'score', 'score': 10, 'confidence': .8}},
    {'x': {'type': 'score', 'score': True, 'confidence': .8}},
    {'x': {'type': 'score', 'score': 10 ** 400, 'confidence': .8}},
    {'unexpected': {'type': 'score', 'score': 8, 'confidence': .8}},
    {'x': {'type': 'score', 'score': '8', 'confidence': .8}},
    {'x': {'type': 'score', 'score': 8, 'confidence': 2}},
])
def test_invalid_answers_fail_closed(answer):
    from hermes_cli.skills_select_provider import validate_response, MODEL
    with pytest.raises(ValueError):
        validate_response({'model': MODEL, 'answers': answer,
                           'usage': {'input_tokens': 1, 'output_tokens': 1}}, {'x'})
