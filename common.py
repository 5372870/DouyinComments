import requests
import execjs
import urllib.parse
import re
import random
import cookiesparser

HOST = 'https://www.douyin.com'

COMMON_PARAMS = {
    'device_platform': 'webapp',
    'aid': '6383',
    'channel': 'channel_pc_web',
    'update_version_code': '170400',
    'pc_client_type': '1',  # Windows
    'version_code': '190500',
    'version_name': '19.5.0',
    'cookie_enabled': 'true',
    'screen_width': '2560',  # from cookie dy_swidth
    'screen_height': '1440',  # from cookie dy_sheight
    'browser_language': 'zh-CN',
    'browser_platform': 'Win32',
    'browser_name': 'Chrome',
    'browser_version': '126.0.0.0',
    'browser_online': 'true',
    'engine_name': 'Blink',
    'engine_version': '126.0.0.0',
    'os_name': 'Windows',
    'os_version': '10',
    'cpu_core_num': '24',  # device_web_cpu_core
    'device_memory': '8',  # device_web_memory_size
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

DOUYIN_SIGN = execjs.compile(open('douyin.js', encoding='utf-8').read())


class RedirectError(Exception):
    pass


def extract_webid_from_text(text: str) -> str | None:
    patterns = [
        r'\\"user_unique_id\\":\\"(\d+)\\"',
        r'\"user_unique_id\":\"(\d+)\"',
        r'\\\\\"user_unique_id\\\\\":\\\\\"(\d+)\\\\\"',
        r'user_unique_id.*?(\d+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def extract_webid_from_cookie(headers: dict) -> str | None:
    cookie = headers.get('cookie') or headers.get('Cookie')
    if not cookie:
        return None
    cookie_dict = cookiesparser.parse(cookie)
    s_v_web_id = cookie_dict.get('s_v_web_id')
    if s_v_web_id:
        match = re.search(r'verify_(\d+)_', s_v_web_id)
        if match:
            return match.group(1)
    return None


def get_webid(headers: dict, max_retries: int = 2) -> str | None:
    url = 'https://www.douyin.com/?recommend=1'
    headers['sec-fetch-dest'] = 'document'
    
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(url, headers=headers, allow_redirects=False)
            
            if response.status_code == 302:
                raise RedirectError(f'Redirect to {response.headers.get("Location")}')
            
            if response.status_code == 200 and response.text:
                webid = extract_webid_from_text(response.text)
                if webid:
                    return webid
        
        except requests.exceptions.RequestException:
            pass
        
        if attempt < max_retries:
            continue
    
    return extract_webid_from_cookie(headers)


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
    params['verifyFp'] = cookie_dict.get('s_v_web_id', None)
    params['fp'] = cookie_dict.get('s_v_web_id', None)
    webid = get_webid(headers)
    if webid:
        params['webid'] = webid
    return params


def get_ms_token(randomlength=120):
    """
    根据传入长度产生随机字符串
    """
    random_str = ''
    base_str = 'ABCDEFGHIGKLMNOPQRSTUVWXYZabcdefghigklmnopqrstuvwxyz0123456789='
    length = len(base_str) - 1
    for _ in range(randomlength):
        random_str += base_str[random.randint(0, length)]
    return random_str


def common(uri, params: dict, headers: dict) -> tuple[dict, dict]:
    params.update(COMMON_PARAMS)
    headers.update(COMMON_HEADERS)
    params = deal_params(params, headers)
    query = '&'.join([f'{k}={urllib.parse.quote(str(v))}' for k, v in params.items()])
    call_name = 'sign_datail'
    if 'reply' in uri:
        call_name = 'sign_reply'
    a_bogus = DOUYIN_SIGN.call(call_name, query, headers["User-Agent"])
    params["a_bogus"] = a_bogus
    return params, headers
