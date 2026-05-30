import abc
import hashlib
import random
import re
import urllib.parse
from pathlib import Path

import cookiesparser
import execjs
import requests

HOST = 'https://www.douyin.com'
WEBID_URL = 'https://www.douyin.com/?recommend=1'
REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
WEBID_PATTERN = re.compile(r'(?:\\"user_unique_id\\":\\"(\d+)\\"|"user_unique_id"\s*:\s*"(\d+)")')
_SIGNER = None
_DEFAULT_SIGNER = None


class Signer(abc.ABC):
    def sign(self, call_name: str, query: str, user_agent: str) -> str:
        raise NotImplementedError


class LocalJSSigner(Signer):
    def __init__(self, js_path: str | Path | None = None):
        if js_path is None:
            js_path = Path(__file__).with_name('douyin.js')
        self.js_path = Path(js_path)
        self._ctx = None

    @property
    def ctx(self):
        if self._ctx is None:
            with self.js_path.open(encoding='utf-8') as f:
                self._ctx = execjs.compile(f.read())
        return self._ctx

    def sign(self, call_name: str, query: str, user_agent: str) -> str:
        return self.ctx.call(call_name, query, user_agent)


class RemoteAPISigner(Signer):
    def __init__(
        self,
        endpoint: str,
        session: requests.Session | None = None,
        timeout: float = 10,
        response_field: str = 'a_bogus',
    ):
        self.endpoint = endpoint
        self.session = session or requests.Session()
        self.timeout = timeout
        self.response_field = response_field

    def sign(self, call_name: str, query: str, user_agent: str) -> str:
        response = self.session.post(
            self.endpoint,
            json={
                'call_name': call_name,
                'query': query,
                'user_agent': user_agent,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        value = payload.get(self.response_field)
        if value is None:
            raise ValueError(f'missing signer response field: {self.response_field}')
        return str(value)


class MockSigner(Signer):
    def __init__(self, return_value: str = 'mock_a_bogus'):
        self.return_value = return_value
        self.calls: list[dict[str, str]] = []

    def sign(self, call_name: str, query: str, user_agent: str) -> str:
        self.calls.append(
            {
                'call_name': call_name,
                'query': query,
                'user_agent': user_agent,
            }
        )
        return self.return_value


class _LegacyDouyinSign:
    def call(self, call_name: str, query: str, user_agent: str) -> str:
        return get_default_signer().sign(call_name, query, user_agent)


DOUYIN_SIGN = _LegacyDouyinSign()

COMMON_PARAMS = {
    'device_platform': 'webapp',
    'aid': '6383',
    'channel': 'channel_pc_web',
    'update_version_code': '170400',
    'pc_client_type': '1',
    'version_code': '190500',
    'version_name': '19.5.0',
    'cookie_enabled': 'true',
    'screen_width': '2560',
    'screen_height': '1440',
    'browser_language': 'zh-CN',
    'browser_platform': 'Win32',
    'browser_name': 'Chrome',
    'browser_version': '126.0.0.0',
    'browser_online': 'true',
    'engine_name': 'Blink',
    'engine_version': '126.0.0.0',
    'os_name': 'Windows',
    'os_version': '10',
    'cpu_core_num': '24',
    'device_memory': '8',
    'platform': 'PC',
    'downlink': '10',
    'effective_type': '4g',
    'round_trip_time': '50',
}

COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "sec-fetch-site": "same-origin",
    "sec-fetch-mode": "cors",
    "sec-fetch-dest": "empty",
    "sec-ch-ua-platform": "Windows",
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
    "referer": "https://www.douyin.com/?recommend=1",
    "priority": "u=1, i",
    "pragma": "no-cache",
    "cache-control": "no-cache",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
    "accept": "application/json, text/plain, */*",
    "dnt": "1",
}


class WebIdRedirectError(RuntimeError):
    def __init__(self, status_code: int, location: str | None = None):
        self.status_code = status_code
        self.location = location
        message = f'homepage request redirected with status {status_code}'
        if location:
            message = f'{message} to {location}'
        super().__init__(message)


def get_default_signer() -> Signer:
    global _DEFAULT_SIGNER
    if _DEFAULT_SIGNER is None:
        _DEFAULT_SIGNER = LocalJSSigner()
    return _DEFAULT_SIGNER


def set_default_signer(signer: Signer | None) -> None:
    global _DEFAULT_SIGNER, _SIGNER
    _DEFAULT_SIGNER = signer
    _SIGNER = signer._ctx if isinstance(signer, LocalJSSigner) else None


def get_signer():
    global _SIGNER
    if _SIGNER is None:
        _SIGNER = execjs.compile(open('douyin.js', encoding='utf-8').read())
    return _SIGNER


def extract_webid(response_text: str) -> str | None:
    if not response_text:
        return None
    matches = [escaped_match or raw_match for escaped_match, raw_match in WEBID_PATTERN.findall(response_text)]
    if len(matches) != 1:
        return None
    return matches[0]


def infer_webid_from_cookie(cookie_dict: dict) -> str | None:
    direct_keys = ('webid', 'web_id', 'web_id_str')
    for key in direct_keys:
        value = str(cookie_dict.get(key) or '').strip()
        if value.isdigit():
            return value

    seed_keys = ('s_v_web_id', 'verifyFp', 'ttwid', 'msToken')
    for key in seed_keys:
        value = str(cookie_dict.get(key) or '').strip()
        if not value:
            continue
        digit_match = re.search(r'(\d{15,20})', value)
        if digit_match:
            return digit_match.group(1)
        digest = hashlib.sha1(value.encode('utf-8')).hexdigest()
        return str(int(digest, 16))[:19]
    return None


def get_webid(headers: dict, cookie_dict: dict | None = None, max_retries: int = 2):
    request_headers = headers.copy()
    request_headers['sec-fetch-dest'] = 'document'
    attempts = max(1, max_retries + 1)

    for _ in range(attempts):
        try:
            response = requests.get(WEBID_URL, headers=request_headers, allow_redirects=False, timeout=10)
        except requests.RequestException:
            continue

        if response.status_code in REDIRECT_STATUS_CODES:
            raise WebIdRedirectError(response.status_code, response.headers.get('Location'))

        if response.status_code == 200:
            webid = extract_webid(response.text)
            if webid:
                return webid

    return infer_webid_from_cookie(cookie_dict or {})


def deal_params(params: dict, headers: dict) -> dict:
    cookie = headers.get('cookie') or headers.get('Cookie')
    if not cookie:
        return params
    cookie_dict = cookiesparser.parse(cookie)
    params['msToken'] = get_ms_token()
    params['screen_width'] = cookie_dict.get('dy_swidth', 2560)
    params['screen_height'] = cookie_dict.get('dy_sheight', 1440)
    params['cpu_core_num'] = cookie_dict.get('device_web_cpu_core', 24)
    params['device_memory'] = cookie_dict.get('device_web_memory_size', 8)

    verify_fp = cookie_dict.get('s_v_web_id')
    if verify_fp:
        params['verifyFp'] = verify_fp
        params['fp'] = verify_fp
    else:
        params.pop('verifyFp', None)
        params.pop('fp', None)

    webid = get_webid(headers, cookie_dict=cookie_dict)
    if webid:
        params['webid'] = webid
    else:
        params.pop('webid', None)
    return params


def get_ms_token(randomlength=120):
    random_str = ''
    base_str = 'ABCDEFGHIGKLMNOPQRSTUVWXYZabcdefghigklmnopqrstuvwxyz0123456789='
    length = len(base_str) - 1
    for _ in range(randomlength):
        random_str += base_str[random.randint(0, length)]
    return random_str


def resolve_sign_call_name(uri: str) -> str:
    if 'reply' in uri:
        return 'sign_reply'
    return 'sign_datail'


def build_sign_query(params: dict) -> str:
    return '&'.join([f'{key}={urllib.parse.quote(str(value))}' for key, value in params.items()])


def sign_request(uri: str, params: dict, headers: dict, signer: Signer | None = None) -> str:
    active_signer = signer or get_default_signer()
    return active_signer.sign(resolve_sign_call_name(uri), build_sign_query(params), headers['User-Agent'])


def common(uri, params: dict, headers: dict, signer: Signer | None = None) -> tuple[dict, dict]:
    params.update(COMMON_PARAMS)
    headers.update(COMMON_HEADERS)
    params = deal_params(params, headers)
    params['a_bogus'] = sign_request(uri, params, headers, signer=signer)
    return params, headers
