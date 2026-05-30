import sys
sys.path.insert(0, '/app/DouyinComments')
from unittest.mock import patch, MagicMock


def test_mock_signer_injection():
    print('=== Test 1: MockSigner injection without douyin.js ===')
    from common import MockSigner, common, set_default_signer, Signer

    with patch('common.execjs.compile') as mock_compile:
        signer = MockSigner('signed-by-mock')
        params, headers = common(
            'https://www.douyin.com/aweme/v1/web/comment/list/',
            {'aweme_id': '123'},
            {},
            signer=signer,
        )
        assert params['a_bogus'] == 'signed-by-mock'
        assert len(signer.calls) == 1
        assert signer.calls[0]['call_name'] == 'sign_datail'
        assert 'aweme_id=123' in signer.calls[0]['query']
        mock_compile.assert_not_called()
        print('PASSED')


def test_sign_request_independent():
    print()
    print('=== Test 2: sign_request independent testing ===')
    from common import sign_request, build_sign_query, MockSigner

    signer = MockSigner('request-signature')
    result = sign_request(
        'https://www.douyin.com/aweme/v1/web/comment/list/reply/',
        {'cursor': 1, 'text': 'hello world'},
        {'User-Agent': 'test-agent'},
        signer=signer,
    )
    assert result == 'request-signature'
    assert signer.calls[0]['call_name'] == 'sign_reply'
    assert signer.calls[0]['query'] == build_sign_query({'cursor': 1, 'text': 'hello world'})
    assert signer.calls[0]['user_agent'] == 'test-agent'
    print('PASSED')


def test_douyin_sign_backward_compat():
    print()
    print('=== Test 3: DOUYIN_SIGN backward compatibility ===')
    from common import DOUYIN_SIGN, MockSigner, set_default_signer

    set_default_signer(None)
    signer = MockSigner('legacy-signature')
    set_default_signer(signer)

    result = DOUYIN_SIGN.call('sign_reply', 'cursor=1', 'test-agent')
    assert result == 'legacy-signature'
    assert signer.calls[-1]['call_name'] == 'sign_reply'
    assert signer.calls[-1]['query'] == 'cursor=1'
    assert signer.calls[-1]['user_agent'] == 'test-agent'
    print('PASSED')


def test_remote_api_signer():
    print()
    print('=== Test 4: RemoteAPISigner ===')
    from common import RemoteAPISigner

    session = MagicMock()
    response = MagicMock()
    response.json.return_value = {'a_bogus': 'remote-signature'}
    session.post.return_value = response

    signer = RemoteAPISigner('https://signer.example/api', session=session, timeout=3)
    result = signer.sign('sign_datail', 'aweme_id=1', 'agent')
    assert result == 'remote-signature'
    session.post.assert_called_once_with(
        'https://signer.example/api',
        json={'call_name': 'sign_datail', 'query': 'aweme_id=1', 'user_agent': 'agent'},
        timeout=3,
    )
    response.raise_for_status.assert_called_once()
    print('PASSED')


def test_set_default_signer_reset():
    print()
    print('=== Test 5: set_default_signer reset ===')
    from common import set_default_signer, _DEFAULT_SIGNER
    set_default_signer(None)
    assert _DEFAULT_SIGNER is None
    print('PASSED')


def test_common_no_signer_uses_default():
    print()
    print('=== Test 6: common() without signer uses default ===')
    from common import common, MockSigner, set_default_signer

    set_default_signer(None)
    signer = MockSigner('default-signature')
    set_default_signer(signer)

    params, headers = common(
        'https://www.douyin.com/aweme/v1/web/comment/list/',
        {'aweme_id': '456'},
        {},
    )
    assert params['a_bogus'] == 'default-signature'
    print('PASSED')


def test_resolve_sign_call_name():
    print()
    print('=== Test 7: resolve_sign_call_name ===')
    from common import resolve_sign_call_name

    assert resolve_sign_call_name('/aweme/v1/web/comment/list/') == 'sign_datail'
    assert resolve_sign_call_name('/aweme/v1/web/comment/list/reply/') == 'sign_reply'
    print('PASSED')


if __name__ == '__main__':
    test_mock_signer_injection()
    test_sign_request_independent()
    test_douyin_sign_backward_compat()
    test_remote_api_signer()
    test_set_default_signer_reset()
    test_common_no_signer_uses_default()
    test_resolve_sign_call_name()
    print()
    print('All tests passed!')