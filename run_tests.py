import sys
import os
sys.path.insert(0, '/app/DouyinComments')
os.chdir('/app/DouyinComments')

from unittest.mock import patch, MagicMock
from common import extract_webid, infer_webid_from_cookie, get_webid, deal_params, WebIdRedirectError

results = []

# Test 1: no target string
r = extract_webid('<html>no user_unique_id here</html>')
passed = r is None
results.append(('Test 1 (no target string)', passed, r))

# Test 2: multiple matches
text = '<script>\\"user_unique_id\\":\\"1111111111111111111\\",\\"user_unique_id\\":\\"2222222222222222222\\"</script>'
r = extract_webid(text)
passed = r is None
results.append(('Test 2 (multiple matches)', passed, r))

# Test 3: abnormal escape
text = '<script>\\\\\\"user_unique_id\\\\\\":\\\\\\"3333333333333333333\\\\\\"</script>'
r = extract_webid(text)
passed = r is None
results.append(('Test 3 (abnormal escape)', passed, r))

# Test 4: normal match
text = '<script>\\"user_unique_id\\":\\"7362810250930783783\\"</script>'
r = extract_webid(text)
passed = r == "7362810250930783783"
results.append(('Test 4 (normal match)', passed, r))

# Test 5: 302 redirect
with patch('common.requests.get') as mock_get:
    mock_response = MagicMock()
    mock_response.status_code = 302
    mock_response.headers = {'Location': 'https://www.douyin.com/login'}
    mock_get.return_value = mock_response
    try:
        get_webid({'User-Agent': 'test', 'cookie': 'test=1'})
        results.append(('Test 5 (302 redirect)', False, 'no exception'))
    except WebIdRedirectError as e:
        results.append(('Test 5 (302 redirect)', True, str(e)))

# Test 6: webid=None in deal_params
with patch('common.get_webid') as mock:
    mock.return_value = None
    params = {'aweme_id': '123'}
    headers = {'cookie': 's_v_web_id=verify_test; dy_swidth=1920', 'User-Agent': 'test'}
    result = deal_params(params.copy(), headers.copy())
    passed = 'webid' not in result
    results.append(('Test 6 (webid=None in deal_params)', passed, 'webid' in result))

# Test 7: webid present in deal_params
with patch('common.get_webid') as mock:
    mock.return_value = '7362810250930783783'
    params = {'aweme_id': '123'}
    headers = {'cookie': 's_v_web_id=verify_test; dy_swidth=1920', 'User-Agent': 'test'}
    result = deal_params(params.copy(), headers.copy())
    passed = result.get('webid') == '7362810250930783783'
    results.append(('Test 7 (webid present)', passed, result.get('webid')))

# Test 8: cookie fallback direct
r = infer_webid_from_cookie({'webid': '1234567890123456789'})
passed = r == '1234567890123456789'
results.append(('Test 8 (cookie fallback)', passed, r))

# Test 9: s_v_web_id fallback
r = infer_webid_from_cookie({'s_v_web_id': 'verify_ft1_1234567890123456789_xxxx'})
passed = r == '12345678901234567'
results.append(('Test 9 (s_v_web_id)', passed, r))

# Write results to file
with open('/app/DouyinComments/test_results.txt', 'w') as f:
    passed_count = 0
    for name, passed, value in results:
        status = 'PASS' if passed else 'FAIL'
        if passed:
            passed_count += 1
        f.write(f'{name}: {status} (got {value})\n')
    f.write(f'\nTotal: {passed_count}/{len(results)} passed\n')
