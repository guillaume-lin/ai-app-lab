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

import type { AnnoRef } from '@/components/DrawingBoard';
import { useAudioRecorder } from '@/hooks/useAudioRecorder';
import { useMediaStream } from '@/hooks/useMediaStream';
import { usePlayBotAudio } from '@/hooks/usePlayBotAudio';
import { defaultBarsData } from '@/hooks/useTrackUserSpeakWave';
import { useVideoAnnotation } from '@/hooks/useVideoAnnotation';
import { ChatContext, EChatState } from '@/providers/ChatProvider/context';
import { fetchVlmImg } from '@/requests/fetchVlmImg';
import { fetchVlmText } from '@/requests/fetchVlmText';
import { useSyncRef } from '@/useSyncRef';
import { getLlmRespContent } from '@/utils/getLlmRespContent';
import { type FC, type PropsWithChildren, useRef, useState } from 'react';
import { v4 as uuidv4 } from 'uuid';

export const ChatProvider: FC<PropsWithChildren> = ({ children }) => {
  const [previewConfig, setPreviewConfig] = useState({
    showInterruptBtn: true,
    showCaption: true,
  });
  const [chatState, setChatState] = useState<EChatState>(EChatState.Idle);
  const chatStateRef = useSyncRef(chatState);
  const ctxId = useRef(uuidv4());
  const audioPlayingRef = useRef(false);

  const [isCameraOn, setIsCameraOn] = useState(false);

  const streamRef = useRef<MediaStream>();
  const [userAudioWaveHeights, setUserAudioWaveHeights] = useState<{
    bar1: number;
    bar2: number;
    bar3: number;
  }>(defaultBarsData);

  const [userPrompt, setUserPrompt] = useState('');
  const [botContent, setBotContent] = useState('');

  const [isWaitingBotSSEChunk, setIsWaitingBotSSEChunk] = useState(false);
  const isWaitingBotSSEChunkRef = useSyncRef(isWaitingBotSSEChunk);

  const {
    videoRef,
    getMediaStream,
    playVideoWithStream: _playVideoWithStream,
    releaseMediaStream,
  } = useMediaStream();

  const annoRef = useRef<AnnoRef>(null);

  const { frameCanvasRef, startCapture, stopCapture, captureAnnotatedFrame } =
    useVideoAnnotation(videoRef, annoRef, base64data => {
      fetchVlmImg(ctxId.current, base64data);
    });

  //

  const handleBotAudioPlayDone = async () => {
    audioPlayingRef.current = false;
    try {
      await startRecording();
    } catch (e) {
      console.warn("Failed to restart ASR.", e);
    }
    // Only clear the user prompt, leave bot content for reading if no audio was played
    // BUT we shouldn't clear user prompt immediately if we just want to read the text
    // setUserPrompt('');
    setChatState(EChatState.UserSpeaking);
  };
  // const { addToQueue, reset: resetBotAudioPlay } = useBotAudioPlayV2({
  //   hasMoreData: isWaitingBotSSEChunk,
  //   onAudioPlayFinish:handleBotAudioPlayDone
  // });

  const { markAudioDataFinished, addAudio, play, resetAudio } = usePlayBotAudio(
    handleBotAudioPlayDone,
    true,
  );

  const sendTextMessage = async (text: string) => {
    stopRecording();
    setUserPrompt(text);

    const shouldFetch =
      !isWaitingBotSSEChunkRef.current && !audioPlayingRef.current;
    if (shouldFetch || true) { // Always allow fetch for text messages since we disabled audio dependency
      setIsWaitingBotSSEChunk(true);
      const frameNow = await captureAnnotatedFrame();
      setChatState(EChatState.BotThinking);
      setBotContent(''); // Clear any previous bot content when a new request starts
      fetchVlmText(
        ctxId.current,
        frameNow,
        text,
        chunk => {
          const { content: botContent, audio } = getLlmRespContent(chunk);
          console.log('Received bot content in provider:', botContent);
          
          // 如果状态还是 thinking，且有内容，就切到 speaking
          if (chatStateRef.current === EChatState.BotThinking && botContent && botContent !== '【思考中】') {
            annoRef.current?.removeDisplayedPaths();
            setChatState(EChatState.BotSpeaking);
          }

          if (botContent && botContent !== '【思考中】') {
            // 确保能拿到最新的 prev 状态，对于文本模型直接追加
            setBotContent(prev => {
              const newContent = prev + botContent;
              console.log('Updating botContent state to:', newContent);
              return newContent;
            });
          }
          if (audio) {
            addAudio(audio);
            if (!audioPlayingRef.current) {
              play();
              audioPlayingRef.current = true;
            }
          }
        },
        reqId => {
          setIsWaitingBotSSEChunk(false);
          markAudioDataFinished();
          // if there is no audio playing, trigger play done immediately to reset state
          if (!audioPlayingRef.current) {
            handleBotAudioPlayDone();
          }
        },
      );
    }
  };

  const {
    stopRecording,
    startRecording,
    connectAsrWs,
    // pauseRecording, resumeRecording,
  } = useAudioRecorder(
    setUserAudioWaveHeights,
    chatState,
    streamRef,
    text => {
      text && setUserPrompt(text);
    },
    async text => {
      stopRecording();
      // pauseRecording()

      const shouldFetch =
        !isWaitingBotSSEChunkRef.current && !audioPlayingRef.current;
      if (shouldFetch) {
        setIsWaitingBotSSEChunk(true);
        const frameNow = await captureAnnotatedFrame();
        setChatState(EChatState.BotThinking);
        fetchVlmText(
          ctxId.current,
          frameNow,
          text,
          chunk => {
            const { content: botContent, audio } = getLlmRespContent(chunk);
            console.log('Received bot content in provider (voice):', botContent);
            
            if (chatStateRef.current === EChatState.BotThinking && botContent && botContent !== '【思考中】') {
              annoRef.current?.removeDisplayedPaths();
              setChatState(EChatState.BotSpeaking);
            }

            if (botContent && botContent !== '【思考中】') {
              // 确保能拿到最新的 prev 状态，对于文本模型直接追加
              setBotContent(prev => {
                const newContent = prev + botContent;
                console.log('Updating botContent state to (voice):', newContent);
                return newContent;
              });
            }
            if (audio) {
              addAudio(audio);
              if (!audioPlayingRef.current) {
                play();
                audioPlayingRef.current = true;
              }
            }
          },
          reqId => {
            setIsWaitingBotSSEChunk(false);
            markAudioDataFinished(); 
            // if there is no audio playing, trigger play done immediately to reset state
            if (!audioPlayingRef.current) {
              handleBotAudioPlayDone();
            }
          },
        );
      }
    },
  );

  const start = async () => {
    ctxId.current = uuidv4();
    await getMediaStream(streamRef);
    try {
      await connectAsrWs();
      await startRecording();
    } catch (e) {
      console.warn("Failed to connect to ASR. Voice input may not work. You can still use text input.", e);
    }

    startCapture();
    setIsCameraOn(true);
    setChatState(EChatState.UserSpeaking);
  };

  const stop = () => {
    setUserPrompt(''); // 清空用户输入
    // resetBotAudioPlay();
    resetAudio();
    annoRef.current?.clearAnnotations();
    annoRef.current?.removeDisplayedPaths();
    releaseMediaStream(streamRef);
    stopCapture();
    setIsCameraOn(false);
    stopRecording();
    setChatState(EChatState.Idle);
  };

  const interrupt = async () => {
    resetAudio();
    audioPlayingRef.current = false;

    try {
      await connectAsrWs();
      // resumeRecording()
      startRecording();
    } catch (e) {
      console.warn("Failed to connect to ASR. Voice input may not work. You can still use text input.", e);
    }
    annoRef.current?.clearAnnotations();
    annoRef.current?.removeDisplayedPaths();

    setUserPrompt('');
    setBotContent('');

    setChatState(EChatState.UserSpeaking);
  };

  const playVideoWithStream = () => {
    _playVideoWithStream(streamRef);
  };

  return (
    <ChatContext.Provider
      value={{
        previewConfig,
        setPreviewConfig,
        //
        interrupt,
        streamRef,
        chatState,
        isCameraOn,
        //
        start,
        stop,
        //
        userPrompt,
        userAudioWaveHeights,
        botContent,
        sendTextMessage,
        //
        annoRef,
        videoRef,
        playVideoWithStream,
        frameCanvasRef,
        //
      }}
    >
      {children}
    </ChatContext.Provider>
  );
};
