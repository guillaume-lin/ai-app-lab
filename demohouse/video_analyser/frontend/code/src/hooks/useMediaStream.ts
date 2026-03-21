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

import { type MutableRefObject, useRef } from 'react';

import { ScreenHeight, ScreenWidth } from '@/const';
import { getBestVideoSettings } from '@/utils/getBestVideoSettings';
import { toast } from '@/utils/toast';

export const useMediaStream = () => {
  const videoRef = useRef<HTMLVideoElement>(null);

  const getMediaStream = async (
    streamRef: MutableRefObject<MediaStream | undefined>,
  ) => {
    try {
      // 检查是否有mediaDevices支持，部分老旧iOS浏览器（非https环境下）可能不支持
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error('当前环境不支持访问媒体设备，请确保使用 HTTPS');
      }

      // 获取初始媒体流
      const initialStream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: 'environment',
        },
        audio: true,
      });

      // 获取设备列表
      const devices = await navigator.mediaDevices.enumerateDevices();

      // 过滤出视频输入设备
      const videoDevices = devices.filter(
        device => device.kind === 'videoinput',
      );

      // 获取最佳的视频设置
      const { deviceId, maxHeight, maxWidth, maxFramerate } =
        await getBestVideoSettings(
          initialStream,
          videoDevices,
          ScreenWidth,
          ScreenHeight,
        );

      // 停止初始媒体流
      const tracks = initialStream.getTracks();
      // biome-ignore lint/complexity/noForEach: <explanation>
      tracks.forEach(track => {
        track.stop();
      });

      // 使用最佳设置获取媒体流
      let stream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: {
            deviceId: deviceId ? { exact: deviceId } : undefined,
            facingMode: 'environment',
            width: { ideal: maxWidth },
            height: { ideal: maxHeight },
            frameRate: { ideal: maxFramerate },
          },
          audio: true,
        });
      } catch (e) {
        console.warn("Failed to get optimized stream, falling back to basic stream:", e);
        // Fallback for iOS/Safari which sometimes rejects complex constraints
        stream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: 'environment'
          },
          audio: true,
        });
      }

      // 将媒体流赋值给引用
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.volume = 0;
        videoRef.current.muted = true;
        // 在iOS上，必须加上 playsInline 属性才能自动播放
        videoRef.current.setAttribute('playsinline', 'true');
        videoRef.current.srcObject = stream;
      }
    } catch (error) {
      console.error('Camera access error:', error);
      toast(error instanceof Error ? error.message : '获取媒体流失败，请检查摄像头权限');
    }
  };

  const releaseMediaStream = (
    streamRef: MutableRefObject<MediaStream | undefined>,
  ) => {
    if (streamRef.current) {
      const tracks = streamRef.current.getTracks();
      // biome-ignore lint/complexity/noForEach: <explanation>
      tracks.forEach(track => {
        track.stop();
      });

      streamRef.current = undefined;
    }

    if (videoRef.current) {
      videoRef.current.pause();
      videoRef.current.srcObject = null;
    }
  };

  const playVideoWithStream = (
    streamRef: MutableRefObject<MediaStream | undefined>,
  ) => {
    if (videoRef.current && streamRef.current) {
      videoRef.current.srcObject = streamRef.current;
      videoRef.current.play();
    }
  };
  return { videoRef, getMediaStream, playVideoWithStream, releaseMediaStream };
};
