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

import os
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), '../../.env')
load_dotenv(env_path)

VLM_ENDPOINT = os.environ.get("VLM_ENDPOINT", "ep-20260321164103-gktml")
LLM_ENDPOINT = os.environ.get("LLM_ENDPOINT", "ep-20260321164234-c2cpk")  # 256K model for a short term memory

TTS_APP_ID = os.environ.get("TTS_APP_ID", "")
if TTS_APP_ID == "<TTS_APP_ID>":
    TTS_APP_ID = ""
TTS_ACCESS_TOKEN = os.environ.get("TTS_ACCESS_TOKEN", "")
if TTS_ACCESS_TOKEN == "<TTS_ACCESS_TOKEN>":
    TTS_ACCESS_TOKEN = ""

