#!/usr/bin/env python3
from common import Signer, LocalJsSigner, MockSigner, set_default_signer, common


def test_mock_signer():
    print("测试 MockSigner...")
    mock_signer = MockSigner(return_value="test_mock_value")
    
    uri = "https://www.douyin.com/aweme/v1/web/comment/list/"
    params = {"aweme_id": "1234567890"}
    headers = {"User-Agent": "Test Agent"}
    
    result_params, result_headers = common(uri, params, headers, signer=mock_signer)
    assert result_params['a_bogus'] == "test_mock_value"
    print("✓ MockSigner 测试通过")


def test_local_js_signer():
    print("\n测试 LocalJsSigner...")
    try:
        local_signer = LocalJsSigner()
        
        uri = "https://www.douyin.com/aweme/v1/web/comment/list/"
        params = {"aweme_id": "1234567890"}
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        
        result_params, result_headers = common(uri, params, headers, signer=local_signer)
        assert 'a_bogus' in result_params
        assert len(result_params['a_bogus']) > 0
        print(f"✓ LocalJsSigner 测试通过，生成的签名: {result_params['a_bogus']}")
    except Exception as e:
        print(f"✗ LocalJsSigner 测试失败: {e}")


def test_set_default_signer():
    print("\n测试 set_default_signer...")
    test_signer = MockSigner(return_value="default_mock")
    set_default_signer(test_signer)
    
    uri = "https://www.douyin.com/aweme/v1/web/comment/list/"
    params = {"aweme_id": "1234567890"}
    headers = {"User-Agent": "Test Agent"}
    
    result_params, result_headers = common(uri, params, headers)
    assert result_params['a_bogus'] == "default_mock"
    print("✓ set_default_signer 测试通过")


if __name__ == "__main__":
    test_mock_signer()
    test_local_js_signer()
    test_set_default_signer()
    print("\n✅ 所有测试完成！")
