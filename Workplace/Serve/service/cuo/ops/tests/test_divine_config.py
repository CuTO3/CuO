import pytest

from Core.module_config import APP_ROOT, DivineAIConfig, load_module_config


def test_divine_config_paths_are_independent_of_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = load_module_config(
        'src/backend/Function/divine/son_function/AI_divine_config.toml',
        DivineAIConfig,
        config_root=APP_ROOT / 'ops/config-templates',
    )
    assert config.divine_ai_evidence_prompt_file.is_absolute()
    assert config.divine_ai_evidence_prompt_file.is_file()
    assert config.divine_ai_response_max_tokens == 700


def test_old_ambiguous_names_are_rejected_without_echoing_values(tmp_path):
    (tmp_path / 'ai.toml').write_text('max_tokens = "private-test-value"', encoding='utf-8')
    with pytest.raises(ValueError) as error:
        load_module_config('ai.toml', DivineAIConfig, config_root=tmp_path)
    assert 'max_tokens' in str(error.value)
    assert 'private-test-value' not in str(error.value)


def test_missing_config_does_not_fall_back_to_template(tmp_path):
    with pytest.raises(ValueError, match='missing.toml'):
        load_module_config('missing.toml', DivineAIConfig, config_root=tmp_path)


def test_invalid_advice_length_bounds_are_rejected(tmp_path):
    source = APP_ROOT / 'ops/config-templates/src/backend/Function/divine/son_function/AI_divine_config.toml'
    text = source.read_text(encoding='utf-8').replace('divine_ai_advice_min_characters = 15', 'divine_ai_advice_min_characters = 101')
    (tmp_path / 'ai.toml').write_text(text, encoding='utf-8')
    with pytest.raises(ValueError, match='长度范围'):
        load_module_config('ai.toml', DivineAIConfig, config_root=tmp_path)


def test_enabling_ai_requires_private_connection_config(tmp_path):
    source = APP_ROOT / 'ops/config-templates/src/backend/Function/divine/son_function/AI_divine_config.toml'
    (tmp_path / 'ai.toml').write_text(source.read_text(encoding='utf-8').replace('divine_ai_enabled = false', 'divine_ai_enabled = true'), encoding='utf-8')
    with pytest.raises(ValueError, match='LiteLLM'):
        load_module_config('ai.toml', DivineAIConfig, config_root=tmp_path)


def test_api_key_is_redacted_from_config_display():
    source = APP_ROOT / 'ops/config-templates/src/backend/Function/divine/son_function/AI_divine_config.toml'
    import tomllib
    values = tomllib.loads(source.read_text(encoding='utf-8'))
    values['divine_ai_api_key'] = 'synthetic-divine-test-key'
    config = DivineAIConfig.model_validate(values)
    assert 'synthetic-divine-test-key' not in repr(config)
    assert 'synthetic-divine-test-key' not in config.model_dump_json()


@pytest.mark.parametrize('invalid_responses', [0, 1, 2])
async def test_divine_uses_own_litellm_key_and_closes_client(monkeypatch, invalid_responses):
    import json
    import httpx
    from pydantic import SecretStr
    from Function.divine.son_function import AI_divine as ai
    from Function.divine.son_function.zhou_yi import from_lines
    from Function.divine.son_function.readings import select_reading

    config = ai.DIVINE_AI_CONFIG.model_copy(update={
        'divine_ai_enabled': True,
        'divine_ai_api_key': SecretStr('synthetic-divine-test-key'),
        'divine_ai_base_url': 'https://litellm.example.invalid/v1',
        'divine_ai_model_name': 'synthetic-divine-model',
    })
    monkeypatch.setattr(ai, 'DIVINE_AI_CONFIG', config)
    calls = []
    clients = []
    expected = {'keyword': '测试', 'refs': ['m00001'], 'advice': '这是一段合成测试内容，请按自己的节奏安排今天的事情。'}

    def handler(request):
        calls.append(request)
        text = 'invalid json' if len(calls) <= invalid_responses else json.dumps(expected, ensure_ascii=False)
        return httpx.Response(200, json={'choices': [{'message': {'content': text}}]})

    original = httpx.AsyncClient
    def create_client(**kwargs):
        client = original(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(client)
        return client
    monkeypatch.setattr(httpx, 'AsyncClient', create_client)
    zhou = from_lines([7] * 6)
    reading = select_reading(zhou)
    result = await ai.generate(zhou, {}, {'primary': reading['primary']}, [{'keyword': '测试', 'refs': ['m00001']}], 0, object())
    assert result == (ai.fallback(zhou) if invalid_responses == 2 else expected)
    assert len(calls) == min(invalid_responses + 1, 2)
    for request in calls:
        assert str(request.url) == 'https://litellm.example.invalid/v1/chat/completions'
        assert request.headers['Authorization'] == 'Bearer synthetic-divine-test-key'
        body = json.loads(request.content)
        assert body['model'] == 'synthetic-divine-model'
        assert body['max_tokens'] == config.divine_ai_response_max_tokens
    assert all(client.is_closed for client in clients)


async def test_disabled_divine_ai_does_not_construct_client(monkeypatch):
    from Function.divine.son_function import AI_divine as ai
    from Function.divine.son_function.zhou_yi import from_lines
    monkeypatch.setattr(ai, 'DIVINE_AI_CONFIG', ai.DIVINE_AI_CONFIG.model_copy(update={'divine_ai_enabled': False}))
    def unexpected_client(*args, **kwargs):
        pytest.fail('disabled AI must not construct a model client')
    monkeypatch.setattr(ai, 'ModelClient', unexpected_client)
    zhou = from_lines([7] * 6)
    assert await ai.generate(zhou, {}, {}, [{'keyword': '测试'}], 0, object()) == ai.fallback(zhou)
