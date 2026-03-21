# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     https://www.volcengine.com/docs/82379/1433703
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Video Analyser: Realtime vision and speech analysis
"""

import asyncio
import logging
import os
from typing import AsyncIterable, List, Optional, Tuple, Union
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

import prompt
import utils
from config import LLM_ENDPOINT, VLM_ENDPOINT, TTS_ACCESS_TOKEN, TTS_APP_ID

from arkitect.core.component.llm import BaseChatLanguageModel
from arkitect.core.component.llm.model import (
    ArkChatCompletionChunk,
    ArkChatParameters,
    ArkChatRequest,
    ArkChatResponse,
    ArkMessage,
    ChatCompletionMessageTextPart,
    Response,
)
from arkitect.core.component.tts import (
    AudioParams,
    ConnectionParams,
    AsyncTTSClient,
    create_bot_audio_responses,
)
from arkitect.launcher.local.serve import launch_serve
from arkitect.telemetry.trace import task
from arkitect.utils.context import get_headers, get_reqid

FRAME_DESCRIPTION_PREFIX = "视频帧描述："
LAST_HISTORY_MESSAGES = 180  # truncate history messages to 180

logger = logging.getLogger(__name__)


@task(watch_io=False)
async def get_request_messages_for_llm(
    contexts: utils.Storage,
    context_id: str,
    request: ArkChatRequest,
    prompt: str,
) -> List[ArkMessage]:
    request_messages = await contexts.get_history(context_id)
    if isinstance(request.messages[-1].content, list):
        assert isinstance(
            request.messages[-1].content[0], ChatCompletionMessageTextPart
        )
        text = request.messages[-1].content[0].text
    else:
        text = request.messages[-1].content
    request_messages = request_messages + [ArkMessage(role="user", content=text)]
    request_messages = request_messages[-LAST_HISTORY_MESSAGES:]
    return [ArkMessage(role="system", content=prompt)] + request_messages


@task(watch_io=False)
async def chat_with_vlm(
    request: ArkChatRequest,
    parameters: ArkChatParameters,
) -> Tuple[bool, Optional[AsyncIterable[ArkChatCompletionChunk]]]:
    vlm = BaseChatLanguageModel(
        endpoint_id=VLM_ENDPOINT,
        messages=[ArkMessage(role="system", content=prompt.VLM_CHAT_PROMPT)]
        + [request.messages[-1]],
        parameters=parameters,
    )

    iterator = vlm.astream()
    message = ""
    first_resp = await iterator.__anext__()
    if first_resp.choices and first_resp.choices[0].delta.content != "":
        message += first_resp.choices[0].delta.content
    second_resp = await iterator.__anext__()
    if second_resp.choices and second_resp.choices[0].delta.content != "":
        message += second_resp.choices[0].delta.content
    if message.startswith("不知道"):
        return False, None

    async def stream_vlm_outputs():
        yield first_resp
        yield second_resp
        async for resp in iterator:
            yield resp

    return True, stream_vlm_outputs()


@task(watch_io=False)
async def llm_answer(
    contexts, context_id, request, parameters: ArkChatParameters
) -> Tuple[bool, Optional[AsyncIterable[ArkChatCompletionChunk]]]:
    request_messages = await get_request_messages_for_llm(
        contexts, context_id, request, prompt.LLM_PROMPT
    )
    llm = BaseChatLanguageModel(
        endpoint_id=LLM_ENDPOINT,
        messages=request_messages,
        parameters=parameters,
    )

    iterator = llm.astream()
    first_resp = await iterator.__anext__()

    async def stream_llm_outputs():
        yield first_resp
        async for resp in iterator:
            yield resp

    return True, stream_llm_outputs()


@task(watch_io=False)
async def chat_with_llm(
    contexts: utils.Storage,
    request: ArkChatRequest,
    parameters: ArkChatParameters,
    context_id: str,
) -> Tuple[bool, Optional[AsyncIterable[ArkChatCompletionChunk]]]:
    response_task = asyncio.create_task(
        llm_answer(contexts, context_id, request, parameters)
    )
    logger.info("llm can respond")
    return await response_task


@task(watch_io=False)
async def chat_with_branches(
    contexts: utils.Storage,
    request: ArkChatRequest,
    parameters: ArkChatParameters,
    context_id: str,
) -> AsyncIterable[Union[ArkChatCompletionChunk, ArkChatResponse]]:
    """
    Launch two tasks to attempt answering with/without long term memory

    If VLM can answer with current frame only, use VLM's answer.
    If VLM cannot answer, use the answer with long term memory (from LLM)
    """
    vlm_task = asyncio.create_task(chat_with_vlm(request, parameters))
    llm_task = asyncio.create_task(
        chat_with_llm(contexts, request, parameters, context_id)
    )
    can_response, vlm_iter = await vlm_task
    if can_response:
        logger.info("vlm responded, using vlm's answer")
        llm_task.cancel()
        return vlm_iter
    else:
        can_response, llm_iter = await llm_task
        logger.info(f"type I got from llm: {type(llm_iter)}")
        return llm_iter


@task(watch_io=False)
async def summarize_image(
    contexts: utils.Storage,
    request: ArkChatRequest,
    parameters: ArkChatParameters,
    context_id: str,
):
    """
    Summarize the image and append the summary to the context.
    """
    request_messages = [
        ArkMessage(role="system", content=prompt.VLM_PROMPT)
    ] + request.messages
    vlm = BaseChatLanguageModel(
        endpoint_id=VLM_ENDPOINT,
        messages=request_messages,
        parameters=parameters,
    )
    resp = await vlm.arun()
    message = resp.choices[0].message.content
    message = FRAME_DESCRIPTION_PREFIX + message
    await contexts.append(context_id, ArkMessage(role="assistant", content=message))


@task(watch_io=False)
async def default_model_calling(
    request: ArkChatRequest,
) -> AsyncIterable[Union[ArkChatCompletionChunk, ArkChatResponse]]:
    # local in-memory storage should be changed to other storage in production
    context_id: Optional[str] = get_headers().get("X-Context-Id", None)
    assert context_id is not None
    contexts: utils.Storage = utils.CoroutineSafeMap.get_instance_sync()
    if not await contexts.contains(context_id):
        await contexts.set(context_id, utils.Context())

    # If a list is passed and the first text is empty
    # Use VLM to summarize the image asynchronously and return immediately
    is_image = (
        isinstance(request.messages[-1].content, list)
        and isinstance(request.messages[-1].content[0], ChatCompletionMessageTextPart)
        and request.messages[-1].content[0].text == ""
    )
    parameters = ArkChatParameters(**request.__dict__)
    if is_image:
        _ = asyncio.create_task(
            summarize_image(contexts, request, parameters, context_id)
        )
        return

    # Initialize TTS connection asynchronously before launching LLM request to reduce latency
    if TTS_APP_ID and TTS_ACCESS_TOKEN:
        tts_client = AsyncTTSClient(
            connection_params=ConnectionParams(
                speaker="zh_female_tianmeixiaoyuan_moon_bigtts",
                audio_params=AudioParams(
                    format="mp3",
                    sample_rate=24000,
                ),
            ),
            access_key=TTS_ACCESS_TOKEN,
            app_key=TTS_APP_ID,
            conn_id=get_reqid(),
            log_id=get_reqid(),
        )
        connection_task = asyncio.create_task(tts_client.init())
    else:
        tts_client = None
        connection_task = None

    # Use LLM and VLM to answer user's question
    # Received a response iterator from LLM or VLM
    response_iter = await chat_with_branches(contexts, request, parameters, context_id)
    if connection_task:
        await connection_task
    message = ""
    
    if tts_client:
        tts_stream_output = tts_client.tts(response_iter, stream=request.stream)
        async for resp in create_bot_audio_responses(tts_stream_output, request):
            if isinstance(resp, ArkChatCompletionChunk):
                if len(resp.choices) > 0 and hasattr(resp.choices[0].delta, "audio"):
                    message += resp.choices[0].delta.audio.get("transcript", "")
            else:
                if len(resp.choices) > 0 and resp.choices[0].message.audio:
                    message += resp.choices[0].message.audio.transcript
            yield resp
        await tts_client.close()
    else:
        async for resp in response_iter:
            logger.info(f"Got resp: {type(resp)}")
            if isinstance(resp, ArkChatCompletionChunk):
                if len(resp.choices) > 0:
                    delta = resp.choices[0].delta
                    # Dynamically set audio property to delta
                    if hasattr(delta, "content") and delta.content:
                        message += delta.content
                        
                        safe_content = delta.content.replace('\\', '\\\\').replace('\n', '\\n').replace('"', '\\"')
                        logger.info(f"Sending stream chunk: {safe_content}")
                        
                        # Instead of returning a string with JSON or a Pydantic model
                        # Arkitect expects raw strings prefixed with "data: " for SSE
                        import json
                        chunk_dict = {
                            "id": resp.id,
                            "object": resp.object,
                            "created": resp.created,
                            "model": resp.model,
                            "choices": [{
                                "index": 0,
                                "delta": {
                                    "content": delta.content,
                                    "role": "assistant",
                                    "audio": {
                                        "transcript": delta.content,
                                        "data": ""
                                    }
                                }
                            }]
                        }
                        
                        # We must yield an object that arkitect streaming layer understands
                        # The Arkitect framework expects an object that can be serialized or an already serialized chunk object
                        class FallbackChunk(ArkChatCompletionChunk):
                            def model_dump(self, *args, **kwargs):
                                return chunk_dict
                                
                            def model_dump_json(self, *args, **kwargs):
                                return json.dumps(chunk_dict, ensure_ascii=False)
                                
                            def __dict__(self):
                                return chunk_dict
                        
                        # Set up the fallback object with basic required attributes
                        fb_chunk = FallbackChunk(id=resp.id, object=resp.object, created=resp.created, model=resp.model, choices=[])
                        yield fb_chunk
                        continue
            else:
                if len(resp.choices) > 0:
                    msg = resp.choices[0].message
                    if hasattr(msg, "content") and msg.content:
                        message += msg.content
                        
                        safe_content = msg.content.replace('\\', '\\\\').replace('\n', '\\n').replace('"', '\\"')
                        logger.info(f"Sending message chunk: {safe_content}")
                        
                        import json
                        msg_dict = {
                            "id": resp.id,
                            "object": resp.object,
                            "created": resp.created,
                            "model": resp.model,
                            "choices": [{
                                "index": 0,
                                "message": {
                                    "content": msg.content,
                                    "role": "assistant",
                                    "audio": {
                                        "transcript": msg.content,
                                        "data": ""
                                    }
                                }
                            }]
                        }
                        
                        class FallbackMsgChunk(ArkChatCompletionChunk):
                            def model_dump(self, *args, **kwargs):
                                return msg_dict
                                
                            def model_dump_json(self, *args, **kwargs):
                                return json.dumps(msg_dict, ensure_ascii=False)
                                
                            def __dict__(self):
                                return msg_dict
                        
                        fb_msg_chunk = FallbackMsgChunk(id=resp.id, object=resp.object, created=resp.created, model=resp.model, choices=[])
                        yield fb_msg_chunk
                        continue
            yield resp
    text = ""
    if isinstance(request.messages[-1].content, list) and isinstance(
        request.messages[-1].content[0], ChatCompletionMessageTextPart
    ):
        text = request.messages[-1].content[0].text
    elif isinstance(request.messages[-1].content, str):
        text = request.messages[-1].content
    await contexts.append(
        context_id,
        ArkMessage(role="user", content=text),
    )
    await contexts.append(context_id, ArkMessage(role="assistant", content=message))


@task(watch_io=False)
async def main(request: ArkChatRequest) -> AsyncIterable[Response]:
    async for resp in default_model_calling(request):
        yield resp


if __name__ == "__main__":
    import os
    port = os.getenv("_FAAS_RUNTIME_PORT")
    port = int(port) if port else 8888
    
    from arkitect.utils.context import set_resource_type, set_resource_id, set_account_id
    from arkitect.telemetry.trace import setup_tracing
    from arkitect.launcher.runner import get_default_client_configs, get_endpoint_config, get_runner
    from arkitect.core.runtime import load_function
    from arkitect.core.component.bot import BotServer
    from fastapi import Request
    from starlette.exceptions import HTTPException as StarletteHTTPException
    
    set_resource_type(os.getenv("RESOURCE_TYPE") or "")
    set_resource_id(os.getenv("RESOURCE_ID") or "")
    set_account_id(os.getenv("ACCOUNT_ID") or "")
    setup_tracing(endpoint=os.getenv("TRACE_ENDPOINT"), trace_on=True)

    runnable_func = load_function("main", "main")

    server = BotServer(
        runner=get_runner(runnable_func),
        health_check_path="/v1/ping",
        endpoint_config=get_endpoint_config("/api/v3/bots/chat/completions", runnable_func),
        clients={},
    )
    
    app = server.app
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    
    if os.path.isdir(static_dir):
        # Mount assets from static/static/ (Modern.js output structure)
        assets_dir = os.path.join(static_dir, "static")
        if os.path.isdir(assets_dir):
            app.mount("/static", StaticFiles(directory=assets_dir), name="static")
            
        # For other static files if any
        @app.get("/{filename:path}")
        async def serve_root_files(request: Request, filename: str):
            file_path = os.path.join(static_dir, filename)
            if os.path.isfile(file_path):
                return FileResponse(file_path)
            # If not found, and not an API route, serve index.html for React Router
            if not filename.startswith("api/") and not filename.startswith("v1/"):
                index_path = os.path.join(static_dir, "html", "main", "index.html")
                if os.path.isfile(index_path):
                    return FileResponse(index_path)
            raise StarletteHTTPException(status_code=404, detail="Not Found")

        @app.get("/")
        async def serve_index():
            index_path = os.path.join(static_dir, "html", "main", "index.html")
            if os.path.isfile(index_path):
                return FileResponse(index_path)
            raise StarletteHTTPException(status_code=404, detail="Not Found")
            
    server.run(app=app, host="0.0.0.0", port=port)
