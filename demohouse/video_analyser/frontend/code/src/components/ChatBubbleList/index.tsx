// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// Licensed under the 【火山方舟】原型应用软件自用许可协议
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at 
//     https://www.volcengine.com/docs/82379/1433703
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License. 

import { ChatBubble } from '@/components/ChatBubble';

interface IChatBubbleListProps {
  userContent: string;
  botContent: string;
  className?: string;
}
export const ChatBubbleList = ({
  userContent,
  botContent,
  className,
}: IChatBubbleListProps) => {
  console.log('ChatBubbleList render, userContent:', userContent, 'botContent:', botContent);
  return (
    <div className={`flex flex-col gap-[8px] w-full px-[24px] pointer-events-none ${className}`}>
      {userContent && (
        <div className={'self-end max-w-[80%] pointer-events-auto'}>
          <ChatBubble role={'user'} content={userContent} />
        </div>
      )}
      {botContent && (
        <div className={'self-start max-w-[80%] pointer-events-auto'}>
          <ChatBubble role={'bot'} content={botContent} />
        </div>
      )}
    </div>
  );
};
