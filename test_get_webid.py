#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from common import extract_webid_from_text, extract_webid_from_cookie, deal_params, RedirectError
import cookiesparser


def test_case_1_no_target():
    print("测试用例1: 完全不含目标字符串")
    text = "<html><body>这是一个没有user_unique_id的页面</body></html>"
    result = extract_webid_from_text(text)
    print(f"结果: {result}")
    print(f"测试通过: {result is None}\n")
    return result is None


def test_case_2_multiple_matches():
    print("测试用例2: 含多个匹配项")
    text = '''
    \\"user_unique_id\\":\\"123456789\\"
    some other content
    \\"user_unique_id\\":\\"987654321\\"
    '''
    result = extract_webid_from_text(text)
    print(f"结果: {result}")
    print(f"测试通过: {result == '123456789'}\n")
    return result == '123456789'


def test_case_3_escape_backslashes():
    print("测试用例3: 转义反斜杠数量异常")
    text1 = '''\\\\\\"user_unique_id\\\\\\":\\\\\\"111222333\\\\\\"'''
    text2 = '''\\\\\"user_unique_id\\\\\":\\\\\"444555666\\\\\"'''
    result1 = extract_webid_from_text(text1)
    result2 = extract_webid_from_text(text2)
    print(f"结果1: {result1}")
    print(f"结果2: {result2}")
    print(f"测试通过: {result1 == '111222333' or result2 == '444555666'}\n")
    return result1 == '111222333' or result2 == '444555666'


def test_case_4_cookie_fallback():
    print("测试用例4: 从cookie的s_v_web_id推断")
    headers = {
        'cookie': 's_v_web_id=verify_123456789_abcdefg123; other_cookie=value'
    }
    result = extract_webid_from_cookie(headers)
    print(f"结果: {result}")
    print(f"测试通过: {result == '123456789'}\n")
    return result == '123456789'


def test_case_5_deal_params_no_webid():
    print("测试用例5: deal_params在webid为None时不添加该字段")
    headers = {'cookie': 's_v_web_id=verify_000000000_test'}
    params = {}
    result = deal_params(params, headers)
    print(f"结果: {result}")
    has_webid = 'webid' in result
    print(f"测试通过: {not has_webid}\n")
    return not has_webid


def test_case_6_various_formats():
    print("测试用例6: 多种格式匹配")
    test_cases = [
        ('\\\\"user_unique_id\\\\":\\\\"999888777\\\\"', '999888777'),
        ('"user_unique_id":"111222333"', '111222333'),
        ('user_unique_id: "444555666"', '444555666'),
    ]
    all_pass = True
    for text, expected in test_cases:
        result = extract_webid_from_text(text)
        passed = result == expected
        all_pass &= passed
        print(f"  输入: {text[:50]}...")
        print(f"  期望: {expected}, 实际: {result}")
        print(f"  通过: {passed}")
    print(f"测试用例6通过: {all_pass}\n")
    return all_pass


def run_all_tests():
    print("="*50)
    print("开始测试 get_webid 相关函数")
    print("="*50)
    
    tests = [
        test_case_1_no_target,
        test_case_2_multiple_matches,
        test_case_3_escape_backslashes,
        test_case_4_cookie_fallback,
        test_case_5_deal_params_no_webid,
        test_case_6_various_formats,
    ]
    
    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as e:
            print(f"测试 {test.__name__} 抛出异常: {e}")
            results.append(False)
    
    print("="*50)
    total = len(results)
    passed = sum(results)
    print(f"测试完成: {passed}/{total} 个测试通过")
    print("="*50)
    
    return all(results)


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
