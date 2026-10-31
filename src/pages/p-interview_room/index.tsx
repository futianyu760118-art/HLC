/* eslint-disable react-hooks/exhaustive-deps -- Legacy page-level one-shot data loads; keep scoped to this file. */
import { useState, useEffect, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import { interviewsApi, jobsApi, resumesApi, Interview, Job, Resume } from '../../utils/api';
import toast from '../../utils/toast';

import AppIcon from '../../components/AppIcon';
// Jitsi Meet 配置
const JITSI_DOMAIN = 'meet.jit.si'; // 使用公共服务器，可替换为自托管

export default function InterviewRoomPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const interviewId = searchParams.get('interviewId');
  
  const [interview, setInterview] = useState<Interview | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [resume, setResume] = useState<Resume | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  
  const [isMeetingActive, setIsMeetingActive] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const [isEnding, setIsEnding] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [recordingTime, setRecordingTime] = useState(0);
  const [isProcessing, setIsProcessing] = useState(false);
  
  const jitsiContainerRef = useRef<HTMLDivElement>(null);
  const jitsiApiRef = useRef<any>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const recordingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    document.title = '在线面试 - 恒聘通';
    loadInterview();
    
    return () => {
      // 清理
      if (jitsiApiRef.current) {
        jitsiApiRef.current.dispose();
      }
      if (recordingTimerRef.current) {
        clearInterval(recordingTimerRef.current);
      }
    };
  }, [interviewId]);

  const loadInterview = async () => {
    if (!interviewId) {
      setError('缺少面试ID');
      setIsLoading(false);
      return;
    }

    try {
      const [interviews, jobs, resumes] = await Promise.all([
        interviewsApi.getAll(),
        jobsApi.getAll(),
        resumesApi.getAll()
      ]);

      const found = interviews.find(i => i.id === interviewId);
      if (found) {
        setInterview(found);
        setJob(jobs.find(j => j.id === found.jobId) || null);
        setResume(resumes.find(r => r.id === found.resumeId) || null);
      } else {
        setError('面试记录不存在');
      }
    } catch (_err) {
      setError('加载失败');
    } finally {
      setIsLoading(false);
    }
  };

  // 初始化Jitsi Meet
  const initJitsi = () => {
    if (!interview?.roomId || !jitsiContainerRef.current) return;
    
    // 加载Jitsi外部API脚本
    const script = document.createElement('script');
    script.src = `https://${JITSI_DOMAIN}/external_api.js`;
    script.async = true;
    script.onload = () => {
      const options = {
        roomName: interview.roomId,
        parentNode: jitsiContainerRef.current,
        width: '100%',
        height: 500,
        configOverwrite: {
          startWithAudioMuted: false,
          startWithVideoMuted: false,
          prejoinPageEnabled: false,
        },
        interfaceConfigOverwrite: {
          TOOLBAR_BUTTONS: [
            'microphone', 'camera', 'closedcaptions', 'desktop', 
            'fullscreen', 'fodeviceselection', 'hangup', 'chat',
            'settings', 'videoquality', 'filmstrip', 'tileview'
          ],
          SHOW_JITSI_WATERMARK: false,
          SHOW_WATERMARK_FOR_GUESTS: false,
        },
        userInfo: {
          displayName: '面试官',
        }
      };
      
      // @ts-ignore
      jitsiApiRef.current = new window.JitsiMeetExternalAPI(JITSI_DOMAIN, options);
      
      // 监听会议事件
      jitsiApiRef.current.addListener('videoConferenceJoined', () => {
        console.log('[Jitsi] 已加入会议');
      });
      
      jitsiApiRef.current.addListener('videoConferenceLeft', () => {
        console.log('[Jitsi] 已离开会议');
      });
    };
    document.body.appendChild(script);
  };

  // 开始面试
  const handleStartMeeting = async () => {
    if (!interview || isStarting) return;
    setIsStarting(true);
    try {
      const updated = await interviewsApi.startMeeting(interview.id);
      setInterview(updated);
      setIsMeetingActive(true);
      initJitsi();
      startRecording();
    } catch (_err) {
      toast.error('开始面试失败');
    } finally {
      setIsStarting(false);
    }
  };

  // 结束面试
  const handleEndMeeting = async () => {
    if (!interview || isEnding || !confirm('确定要结束面试吗？')) return;
    setIsEnding(true);
    try {
      // 停止录音
      await stopRecording();

      // 关闭Jitsi
      if (jitsiApiRef.current) {
        jitsiApiRef.current.dispose();
        jitsiApiRef.current = null;
      }

      // 更新状态
      const updated = await interviewsApi.endMeeting(interview.id);
      setInterview(updated);
      setIsMeetingActive(false);

    } catch (_err) {
      toast.error('结束面试失败');
    } finally {
      setIsEnding(false);
    }
  };

  // 开始录音
  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: 'audio/webm;codecs=opus'
      });
      
      audioChunksRef.current = [];
      
      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };
      
      mediaRecorder.start(1000); // 每秒收集一次数据
      mediaRecorderRef.current = mediaRecorder;
      setIsRecording(true);
      
      // 开始计时
      recordingTimerRef.current = setInterval(() => {
        setRecordingTime(t => t + 1);
      }, 1000);
      
      console.log('[录音] 开始录音');
    } catch (err) {
      console.error('[录音] 无法获取麦克风权限:', err);
      toast.error('无法获取麦克风权限，录音功能不可用');
    }
  };

  // 停止录音并上传
  const stopRecording = async (): Promise<void> => {
    return new Promise((resolve) => {
      if (!mediaRecorderRef.current || mediaRecorderRef.current.state === 'inactive') {
        resolve();
        return;
      }
      
      mediaRecorderRef.current.onstop = async () => {
        console.log('[录音] 录音停止，准备上传');
        
        // 停止计时
        if (recordingTimerRef.current) {
          clearInterval(recordingTimerRef.current);
        }
        setIsRecording(false);
        
        // 创建音频Blob
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        
        if (audioBlob.size > 0 && interview) {
          setIsProcessing(true);
          
          try {
            // 转换为File对象
            const audioFile = new File([audioBlob], `interview_${interview.id}.webm`, {
              type: 'audio/webm'
            });
            
            console.log(`[录音] 上传录音文件，大小: ${(audioFile.size / 1024 / 1024).toFixed(2)} MB`);
            
            // 上传并处理
            const result = await interviewsApi.uploadRecording(interview.id, audioFile);
            
            if (result.success) {
              setInterview(result.interview);
              
              if (result.transcriptSuccess) {
                toast.success('面试录音已上传并完成AI分析');
              } else {
                toast.warning(`录音已上传，但转文字失败: ${result.transcriptError}`);
              }
            }
          } catch (err: any) {
            console.error('[录音] 上传失败:', err);
            toast.error('录音上传失败: ' + (err.message || '未知错误'));
          } finally {
            setIsProcessing(false);
          }
        }
        
        // 停止所有音轨
        mediaRecorderRef.current?.stream.getTracks().forEach(track => track.stop());
        resolve();
      };
      
      mediaRecorderRef.current.stop();
    });
  };

  // 复制邀约链接
  const copyInviteLink = () => {
    if (!interview?.inviteToken) return;
    
    const link = `${window.location.origin}/interview-join?token=${interview.inviteToken}`;
    navigator.clipboard.writeText(link);
    toast.success('邀约链接已复制到剪贴板');
  };

  // 格式化时间
  const formatTime = (seconds: number) => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  if (isLoading) {
    return (
      <Layout>
        <div className="flex items-center justify-center h-64">
          <AppIcon className="fas fa-spinner fa-spin text-3xl text-blue-500" />
        </div>
      </Layout>
    );
  }

  if (error || !interview) {
    return (
      <Layout>
        <div className="text-center py-12">
          <AppIcon className="fas fa-exclamation-circle text-5xl text-gray-400 mb-4" />
          <p className="text-gray-600">{error || '面试记录不存在'}</p>
          <button
            onClick={() => navigate('/interview-manage')}
            className="mt-4 text-blue-600 hover:underline"
          >
            返回列表
          </button>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="max-w-6xl mx-auto">
        {/* 页面头部 */}
        <div className="mb-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-2xl font-bold text-gray-800 mb-2">
                <AppIcon className="fas fa-video text-blue-500 mr-3" />
                在线面试
              </h2>
              <p className="text-gray-600">
                候选人: <span className="font-medium">{resume?.candidateName}</span>
                {' | '}
                岗位: <span className="font-medium">{job?.title}</span>
              </p>
            </div>
            <div className="flex items-center space-x-3">
              <button
                onClick={copyInviteLink}
                className="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50"
              >
                <AppIcon className="fas fa-link mr-2" />
                复制邀约链接
              </button>
              <button
                onClick={() => navigate(`/interview-detail?interviewId=${interview.id}`)}
                className="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50"
              >
                <AppIcon className="fas fa-arrow-left mr-2" />
                返回详情
              </button>
            </div>
          </div>
        </div>

        {/* 面试控制区 */}
        <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center space-x-4">
              {isRecording && (
                <div className="flex items-center text-red-600">
                  <span className="w-3 h-3 bg-red-600 rounded-full animate-pulse mr-2"></span>
                  录音中 {formatTime(recordingTime)}
                </div>
              )}
              {isProcessing && (
                <div className="flex items-center text-blue-600">
                  <AppIcon className="fas fa-spinner fa-spin mr-2" />
                  正在处理录音...
                </div>
              )}
            </div>
            <div className="flex items-center space-x-3">
              {!isMeetingActive ? (
                <button
                  onClick={handleStartMeeting}
                  disabled={isStarting}
                  className="px-6 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors disabled:opacity-50"
                >
                  <AppIcon className="fas fa-play mr-2" />
                  {isStarting ? '启动中…' : '开始面试'}
                </button>
              ) : (
                <button
                  onClick={handleEndMeeting}
                  disabled={isProcessing || isEnding}
                  className="px-6 py-3 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50"
                >
                  <AppIcon className="fas fa-stop mr-2" />
                  {(isProcessing || isEnding) ? '结束中…' : '结束面试'}
                </button>
              )}
            </div>
          </div>

          {/* 邀约信息 */}
          {!isMeetingActive && (
            <div className="bg-blue-50 rounded-lg p-4">
              <h4 className="font-medium text-blue-800 mb-2">
                <AppIcon className="fas fa-info-circle mr-2" />
                面试邀约信息
              </h4>
              <p className="text-sm text-blue-700 mb-2">
                请将以下链接发送给候选人，候选人点击链接即可加入面试：
              </p>
              <div className="flex items-center space-x-2">
                <input
                  type="text"
                  readOnly
                  value={`${window.location.origin}/interview-join?token=${interview.inviteToken}`}
                  className="flex-1 px-3 py-2 bg-white border border-blue-200 rounded text-sm"
                />
                <button
                  onClick={copyInviteLink}
                  className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
                >
                  复制
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Jitsi视频区域 */}
        {isMeetingActive && (
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden mb-6">
            <div ref={jitsiContainerRef} style={{ height: 500 }}></div>
          </div>
        )}

        {/* 面试结果预览 */}
        {interview.aiAnalysis && (
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h3 className="text-lg font-semibold text-gray-800 mb-4">
              <AppIcon className="fas fa-robot text-blue-500 mr-2" />
              AI分析结果
            </h3>
            <div className="grid grid-cols-3 gap-4 mb-4">
              <div className="bg-gray-50 rounded-lg p-4 text-center">
                <p className="text-sm text-gray-500">综合评分</p>
                <p className="text-3xl font-bold text-blue-600">{interview.aiAnalysis.overallScore}</p>
              </div>
              <div className="bg-gray-50 rounded-lg p-4 text-center">
                <p className="text-sm text-gray-500">评估等级</p>
                <p className="text-xl font-medium">{interview.aiAnalysis.overallLevel}</p>
              </div>
              <div className="bg-gray-50 rounded-lg p-4 text-center">
                <p className="text-sm text-gray-500">录用建议</p>
                <p className="text-xl font-medium">{interview.aiAnalysis.recommendation}</p>
              </div>
            </div>
            <button
              onClick={() => navigate(`/interview-detail?interviewId=${interview.id}`)}
              className="w-full py-2 border border-blue-600 text-blue-600 rounded-lg hover:bg-blue-50"
            >
              查看完整分析报告
            </button>
          </div>
        )}
      </div>
    </Layout>
  );
}
