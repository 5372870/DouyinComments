import unittest
from unittest.mock import Mock, patch

import common


class DummySigner:
    def __init__(self):
        self.calls = []

    def call(self, call_name, query, user_agent):
        self.calls.append((call_name, query, user_agent))
        return 'signed-value'


def make_response(status_code=200, text='', headers=None):
    response = Mock()
    response.status_code = status_code
    response.text = text
    response.headers = headers or {}
    return response


class CommonTestCase(unittest.TestCase):
    def setUp(self):
        self.signer = DummySigner()
        common._SIGNER = self.signer

    @patch('common.requests.get')
    def test_get_webid_returns_none_when_target_missing(self, mock_get):
        mock_get.return_value = make_response(200, '<html>empty</html>')

        webid = common.get_webid({}, cookie_dict={}, max_retries=0)

        self.assertIsNone(webid)

    @patch('common.requests.get')
    def test_get_webid_returns_none_when_multiple_matches_exist(self, mock_get):
        mock_get.return_value = make_response(
            200,
            r'{\"user_unique_id\":\"123\"}{\"user_unique_id\":\"456\"}',
        )

        webid = common.get_webid({}, cookie_dict={}, max_retries=0)

        self.assertIsNone(webid)

    @patch('common.requests.get')
    def test_get_webid_returns_none_when_escape_count_is_abnormal(self, mock_get):
        mock_get.return_value = make_response(
            200,
            r'\\"user_unique_id\\":\\"123\\"',
        )

        webid = common.get_webid({}, cookie_dict={}, max_retries=0)

        self.assertIsNone(webid)

    @patch('common.requests.get')
    def test_get_webid_retries_and_falls_back_to_cookie(self, mock_get):
        mock_get.side_effect = [
            make_response(200, '<html>first miss</html>'),
            make_response(200, '<html>second miss</html>'),
        ]

        webid = common.get_webid({}, cookie_dict={'s_v_web_id': 'verify_test_seed'}, max_retries=1)

        self.assertEqual(mock_get.call_count, 2)
        self.assertIsNotNone(webid)
        self.assertTrue(webid.isdigit())

    @patch('common.requests.get')
    def test_get_webid_raises_distinguishable_redirect_error(self, mock_get):
        mock_get.return_value = make_response(302, headers={'Location': 'https://www.douyin.com/passport'})

        with self.assertRaises(common.WebIdRedirectError) as error_context:
            common.get_webid({}, cookie_dict={}, max_retries=0)

        self.assertEqual(error_context.exception.status_code, 302)
        self.assertEqual(error_context.exception.location, 'https://www.douyin.com/passport')

    @patch('common.get_ms_token', return_value='fixed-token')
    @patch('common.get_webid', return_value=None)
    def test_common_does_not_sign_with_webid_none(self, mock_get_webid, mock_get_ms_token):
        params, headers = common.common(
            'https://www.douyin.com/aweme/v1/web/comment/list/',
            {},
            {'cookie': 'dy_swidth=1920; dy_sheight=1080; device_web_cpu_core=8; device_web_memory_size=16'},
        )

        self.assertNotIn('webid', params)
        self.assertEqual(params['a_bogus'], 'signed-value')
        self.assertEqual(mock_get_webid.call_count, 1)
        self.assertEqual(mock_get_ms_token.call_count, 1)
        _, signed_query, user_agent = self.signer.calls[0]
        self.assertNotIn('webid=None', signed_query)
        self.assertIn('msToken=fixed-token', signed_query)
        self.assertEqual(user_agent, headers['User-Agent'])


if __name__ == '__main__':
    unittest.main()
