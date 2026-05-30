import unittest
from unittest.mock import patch, MagicMock

import requests

from common import (
    extract_webid,
    infer_webid_from_cookie,
    get_webid,
    deal_params,
    WebIdRedirectError,
    WEBID_PATTERN,
    WEBID_URL,
)


class TestExtractWebid(unittest.TestCase):

    def test_no_target_string_returns_none(self):
        """① 完全不含目标字符串 → 返回 None"""
        responses = [
            "",
            "<html><body>no user_unique_id here</body></html>",
            '{"user_id": 123, "name": "test"}',
            "<script>window.data = {}</script>",
        ]
        for text in responses:
            with self.subTest(text=text[:80]):
                self.assertIsNone(extract_webid(text))

    def test_multiple_matches_returns_none(self):
        """② 含多个匹配项 → 返回 None（歧义，无法确定哪个是正确的）"""
        text = (
            '<script>'
            'window.__INITIAL_STATE__ = {'
            '\\"user_unique_id\\":\\"1111111111111111111\\",'
            '"other": "data",'
            '\\"user_unique_id\\":\\"2222222222222222222\\"'
            '}'
            '</script>'
        )
        self.assertIsNone(extract_webid(text))

    def test_abnormal_escape_backslashes_returns_none(self):
        """③ 转义反斜杠数量异常（如 \\\\\"）→ 返回 None"""
        text = (
            '<script>'
            'window.__INITIAL_STATE__ = {'
            '\\\\"user_unique_id\\\\":\\\\"3333333333333333333\\\\"'
            '}'
            '</script>'
        )
        self.assertIsNone(extract_webid(text))

    def test_normal_escaped_json_extracts_webid(self):
        text = (
            '<script>'
            'window.__INITIAL_STATE__ = {'
            '\\"user_unique_id\\":\\"7362810250930783783\\"'
            '}'
            '</script>'
        )
        result = extract_webid(text)
        self.assertEqual(result, "7362810250930783783")

    def test_normal_json_extracts_webid(self):
        text = '{"user_unique_id": "7362810250930783783"}'
        result = extract_webid(text)
        self.assertEqual(result, "7362810250930783783")

    def test_normal_json_no_space_extracts_webid(self):
        text = '{"user_unique_id":"7362810250930783783"}'
        result = extract_webid(text)
        self.assertEqual(result, "7362810250930783783")


class TestInferWebidFromCookie(unittest.TestCase):

    def test_direct_webid_key(self):
        self.assertEqual(infer_webid_from_cookie({"webid": "1234567890123456789"}), "1234567890123456789")

    def test_direct_web_id_key(self):
        self.assertEqual(infer_webid_from_cookie({"web_id": "9876543210987654321"}), "9876543210987654321")

    def test_s_v_web_id_fallback(self):
        self.assertEqual(
            infer_webid_from_cookie({"s_v_web_id": "verify_ft1_1234567890123456789_xxxx"}),
            "12345678901234567",
        )

    def test_no_digit_in_seed_fallback_to_hash(self):
        result = infer_webid_from_cookie({"s_v_web_id": "no_digits_here"})
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 19)
        self.assertTrue(result.isdigit())

    def test_empty_cookie_returns_none(self):
        self.assertIsNone(infer_webid_from_cookie({}))

    def test_none_cookie_is_handled(self):
        with self.assertRaises(TypeError):
            infer_webid_from_cookie(None)


class TestGetWebid(unittest.TestCase):

    def setUp(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0",
            "cookie": "test=1",
        }

    @patch("common.requests.get")
    def test_redirect_302_raises_error(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 302
        mock_response.headers = {"Location": "https://www.douyin.com/login"}
        mock_get.return_value = mock_response

        with self.assertRaises(WebIdRedirectError) as ctx:
            get_webid(self.headers)
        self.assertEqual(ctx.exception.status_code, 302)
        self.assertIn("302", str(ctx.exception))
        self.assertIn("login", str(ctx.exception))

    @patch("common.requests.get")
    def test_redirect_301_raises_error(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 301
        mock_response.headers = {}
        mock_get.return_value = mock_response

        with self.assertRaises(WebIdRedirectError) as ctx:
            get_webid(self.headers)
        self.assertEqual(ctx.exception.status_code, 301)
        self.assertIn("301", str(ctx.exception))

    @patch("common.requests.get")
    def test_successful_extraction_on_first_try(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = (
            '<script>'
            '\\"user_unique_id\\":\\"7362810250930783783\\"'
            '</script>'
        )
        mock_get.return_value = mock_response

        result = get_webid(self.headers)
        self.assertEqual(result, "7362810250930783783")
        mock_get.assert_called_once()

    @patch("common.requests.get")
    def test_retry_on_request_exception(self, mock_get):
        mock_success = MagicMock()
        mock_success.status_code = 200
        mock_success.text = (
            '<script>'
            '\\"user_unique_id\\":\\"5555555555555555555\\"'
            '</script>'
        )
        mock_get.side_effect = [
            requests.ConnectionError("network error"),
            mock_success,
        ]

        result = get_webid(self.headers)
        self.assertEqual(result, "5555555555555555555")
        self.assertEqual(mock_get.call_count, 2)

    @patch("common.requests.get")
    def test_retry_on_non_200_then_success(self, mock_get):
        mock_fail = MagicMock()
        mock_fail.status_code = 500
        mock_success = MagicMock()
        mock_success.status_code = 200
        mock_success.text = (
            '<script>'
            '\\"user_unique_id\\":\\"9999999999999999999\\"'
            '</script>'
        )
        mock_get.side_effect = [mock_fail, mock_success]

        result = get_webid(self.headers)
        self.assertEqual(result, "9999999999999999999")
        self.assertEqual(mock_get.call_count, 2)

    @patch("common.requests.get")
    def test_all_retries_fail_falls_back_to_cookie(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html>no match ever</html>"
        mock_get.return_value = mock_response

        result = get_webid(self.headers, cookie_dict={"webid": "1111111111111111111"})
        self.assertEqual(result, "1111111111111111111")

    @patch("common.requests.get")
    def test_retry_count_respected(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html>no match ever</html>"
        mock_get.return_value = mock_response

        result = get_webid(self.headers, cookie_dict={"webid": "1111111111111111111"}, max_retries=1)
        self.assertEqual(result, "1111111111111111111")
        self.assertEqual(mock_get.call_count, 2)


class TestDealParams(unittest.TestCase):

    def setUp(self):
        self.base_params = {"aweme_id": "123", "cursor": "0"}
        self.base_headers = {
            "cookie": "s_v_web_id=verify_test; dy_swidth=1920; dy_sheight=1080",
            "User-Agent": "Mozilla/5.0",
        }

    @patch("common.get_webid")
    def test_webid_none_is_popped_from_params(self, mock_get_webid):
        """webid=None 时不应出现在 params 中，避免签名错误"""
        mock_get_webid.return_value = None

        result = deal_params(self.base_params.copy(), self.base_headers.copy())
        self.assertNotIn("webid", result)
        self.assertIn("msToken", result)

    @patch("common.get_webid")
    def test_webid_present_is_included(self, mock_get_webid):
        mock_get_webid.return_value = "7362810250930783783"

        result = deal_params(self.base_params.copy(), self.base_headers.copy())
        self.assertEqual(result["webid"], "7362810250930783783")

    def test_no_cookie_returns_params_unchanged(self):
        headers = {"User-Agent": "Mozilla/5.0"}
        result = deal_params(self.base_params.copy(), headers)
        self.assertEqual(result, self.base_params)

    @patch("common.get_webid")
    def test_signing_does_not_crash_when_webid_none(self, mock_get_webid):
        """验证上层 common() 不会因 webid=None 而崩溃"""
        import os
        mock_get_webid.return_value = None

        has_js_runtime = os.path.isfile("douyin.js")

        from common import common
        try:
            params, headers = common(
                "https://www.douyin.com/aweme/v1/web/comment/list/",
                self.base_params.copy(),
                self.base_headers.copy(),
            )
        except Exception as e:
            if has_js_runtime:
                self.fail(f"common() raised {type(e).__name__}: {e}")
            else:
                self.skipTest(f"JS runtime unavailable, skipping integration test: {e}")
                return

        self.assertNotIn("webid", params)
        if has_js_runtime:
            self.assertIn("a_bogus", params)


if __name__ == "__main__":
    unittest.main()
