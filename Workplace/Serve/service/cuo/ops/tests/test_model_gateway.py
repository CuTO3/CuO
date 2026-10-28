import json
from types import SimpleNamespace
import httpx,pytest
from Integration.litellm.client import ModelClient

@pytest.mark.asyncio
@pytest.mark.parametrize('protocol',['openai','anthropic'])
async def test_structured_request_passes_provider_options(protocol):
    settings=SimpleNamespace(model_timeout=5,model_api_key='test',model_base_url='https://model.invalid',model_name='test',model_protocol=protocol)
    client=ModelClient(settings)
    async def handle(request):
        body=json.loads(request.content)
        if protocol=='openai':
            assert body['thinking']=={'type':'disabled'}
            assert body['extra_body']=={'thinking':{'type':'disabled'}}
            assert body['response_format']=={'type':'json_object'}
            response={'choices':[{'message':{'content':'{"events":[]}'}}]}
        else:
            assert 'extra_body' not in body
            assert 'thinking' not in body
            response={'content':[{'type':'text','text':'{"events":[]}'}]}
        return httpx.Response(200,json=response)
    await client.client.aclose()
    client.client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
    try:
        assert await client.complete(messages=[{'role':'user','content':'test'}],response_format={'type':'json_object'})=='{"events":[]}'
    finally:await client.close()
