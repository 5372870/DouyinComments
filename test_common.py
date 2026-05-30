import unittest
from unittest.mock import MagicMock, patch

from common import DOUYIN_SIGN, MockSigner, RemoteApiSigner, build_sign_query, common, set_default_signer, sign_request


class CommonSignerInjectionTestCase(unittest.TestCase):
    def tearDown(self):
        set_default_signer(None)

    @patch('common.execjs.compile')
    def test_common_accepts_mock_signer_without_loading_js(self, mock_compile):
        signer = MockSigner('signed-by-mock')
        params, headers = common(
            'https://www.douyin.com/aweme/v1/web/comment/list/',
            {'aweme_id': '123'},
            {},
            signer=signer,
        )

        self.assertEqual(params['a_bogus'], 'signed-by-mock')
        self.assertEqual(signer.calls[0]['call_name'], 'sign_datail')
        self.assertIn('aweme_id=123', signer.calls[0]['query'])
        self.assertEqual(signer.calls[0]['user_agent'], headers['User-Agent'])
        mock_compile.assert_not_called()

    def test_legacy_douyin_sign_uses_injected_default_signer(self):
        signer = MockSigner('legacy-signature')
        set_default_signer(signer)

        result = DOUYIN_SIGN.call('sign_reply', 'cursor=1', 'test-agent')

        self.assertEqual(result, 'legacy-signature')
        self.assertEqual(
            signer.calls,
            [
                {
                    'call_name': 'sign_reply',
                    'query': 'cursor=1',
                    'user_agent': 'test-agent',
                }
            ],
        )

    def test_sign_request_can_be_tested_independently(self):
        signer = MockSigner('request-signature')

        result = sign_request(
            'https://www.douyin.com/aweme/v1/web/comment/list/reply/',
            {'cursor': 1, 'text': 'hello world'},
            {'User-Agent': 'agent'},
            signer=signer,
        )

        self.assertEqual(result, 'request-signature')
        self.assertEqual(signer.calls[0]['call_name'], 'sign_reply')
        self.assertEqual(signer.calls[0]['query'], build_sign_query({'cursor': 1, 'text': 'hello world'}))


class RemoteApiSignerTestCase(unittest.TestCase):
    def test_remote_api_signer_reads_signature_from_response(self):
        session = MagicMock()
        response = MagicMock()
        response.json.return_value = {'a_bogus': 'remote-signature'}
        session.post.return_value = response
        signer = RemoteApiSigner('https://signer.example/api', session=session, timeout=3)

        result = signer.sign('sign_datail', 'aweme_id=1', 'agent')

        self.assertEqual(result, 'remote-signature')
        session.post.assert_called_once_with(
            'https://signer.example/api',
            json={
                'call_name': 'sign_datail',
                'query': 'aweme_id=1',
                'user_agent': 'agent',
            },
            timeout=3,
        )
        response.raise_for_status.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
