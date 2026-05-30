import re
from common import extract_webid, get_webid, deal_params

def test_extract_webid():
    texts = [
        # ① 完全不含目标字符串
        ("完全不含目标字符串", "nothing here", None),
        # ② 含多个匹配项
        ("含多个匹配项", r'\"user_unique_id\":\"12345\" and \"user_unique_id\":\"67890\"', None),
        # ③ 转义反斜杠数量异常
        ("转义反斜杠数量异常", r'\\\\"user_unique_id\\\\":\\\\"12345\\\\"', None),
        # 正常情况
        ("正常匹配情况 1", r'\"user_unique_id\":\"12345\"', '12345'),
        ("正常匹配情况 2", r'"user_unique_id":"67890"', '67890'),
    ]

    print("=== 测试 extract_webid ===")
    for desc, text, expected in texts:
        result = extract_webid(text)
        status = "通过" if result == expected else f"失败 (期望 {expected}, 实际 {result})"
        print(f"[{status}] {desc}:")
        print(f"  输入: {text}")
        print(f"  输出: {result}\n")

def test_deal_params_fallback():
    print("=== 测试 deal_params 兜底逻辑 ===")
    # 模拟 get_webid 返回 None 的情况
    # 为了测试，我们传入一个空的 cookie 和 headers，get_webid 会请求失败或重试耗尽后返回 None
    # 预期 deal_params 会生成一个 19 位的随机数字作为 webid
    params = {'aweme_id': '123456'}
    headers = {'cookie': 'dummy=1'}
    
    # 模拟 deal_params 的调用
    new_params = deal_params(params, headers)
    webid = new_params.get('webid')
    
    if webid and len(str(webid)) == 19 and str(webid).isdigit():
        print(f"[通过] 上层调用兜底成功，生成了随机 webid: {webid}")
    else:
        print(f"[失败] 兜底逻辑未生效，webid 为: {webid}")

if __name__ == "__main__":
    test_extract_webid()
    test_deal_params_fallback()
