/* eslint-disable react-hooks/exhaustive-deps -- Legacy page-level one-shot data loads; keep scoped to this file. */
import { useState, useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { interviewsApi, InterviewInvite } from '../../utils/api';
import { formatBusinessDateTime } from '../../utils/businessTime';

import AppIcon from '../../components/AppIcon';
import BrandLogo from '../../components/BrandLogo';
// Jitsi Meet 配置
const JITSI_DOMAIN = 'meet.jit.si';

export default function InterviewJoinPage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token');
  
  const [inviteData, setInviteData] = useState<InterviewInvite | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  const [hasJoined, setHasJoined] = useState(false);
  const [candidateName, setCandidateName] = useState('');
  
  const jitsiContainerRef = useRef<HTMLDivElement>(null);
  const jitsiApiRef = useRef<any>(null);

  useEffect(() => {
    document.title = '面试邀约 - 恒聘通';
    loadInvite();
    
    return () => {
      if (jitsiApiRef.current) {
        jitsiApiRef.current.dispose();
      }
    };
  }, [token]);

  const loadInvite = async () => {
    if (!token) {
      setError('无效的邀约链接');
      setIsLoading(false);
      return;
    }

    try {
      const data = await interviewsApi.getInvite(token);
      setInviteData(data);
      setCandidateName(data.candidate.name);
    } catch (err: any) {
      setError(err.message || '邀约链接无效或已过期');
    } finally {
      setIsLoading(false);
    }
  };

  // 加入面试
  const handleJoinMeeting = () => {
    if (!inviteData?.interview.roomId || !jitsiContainerRef.current) return;
    
    // 加载Jitsi外部API脚本
    const script = document.createElement('script');
    script.src = `https://${JITSI_DOMAIN}/external_api.js`;
    script.async = true;
    script.onload = () => {
      const options = {
        roomName: inviteData.interview.roomId,
        parentNode: jitsiContainerRef.current,
        width: '100%',
        height: '100%',
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
          displayName: candidateName || '候选人',
        }
      };
      
      // @ts-ignore
      jitsiApiRef.current = new window.JitsiMeetExternalAPI(JITSI_DOMAIN, options);
      setHasJoined(true);
    };
    document.body.appendChild(script);
  };

  // 格式化日期
  const formatDateTime = (isoString: string) => {
    return formatBusinessDateTime(isoString, {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      weekday: 'long'
    });
  };

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 flex items-center justify-center">
        <div className="text-center">
          <AppIcon className="fas fa-spinner fa-spin text-4xl text-blue-500 mb-4" />
          <p className="text-gray-600">加载中...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 flex items-center justify-center p-4">
        <div className="bg-white rounded-2xl shadow-xl p-8 max-w-md w-full text-center">
          <div className="w-20 h-20 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-6">
            <AppIcon className="fas fa-exclamation-triangle text-3xl text-red-500" />
          </div>
          <h1 className="text-2xl font-bold text-gray-800 mb-2">链接无效</h1>
          <p className="text-gray-600 mb-6">{error}</p>
          <p className="text-sm text-gray-500">
            如有疑问，请联系招聘方确认面试安排
          </p>
        </div>
      </div>
    );
  }

  // 已加入面试 - 全屏显示视频
  if (hasJoined) {
    return (
      <div className="fixed inset-0 bg-black">
        <div ref={jitsiContainerRef} className="w-full h-full"></div>
      </div>
    );
  }

  // 面试邀约页面
  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-xl p-8 max-w-lg w-full">
        {/* Logo */}
        <div className="text-center mb-8">
          <BrandLogo size="lg" stacked className="items-center mb-3" />
          <p className="text-gray-500">在线面试邀约</p>
        </div>

        {/* 面试信息 */}
        <div className="bg-gray-50 rounded-xl p-6 mb-6">
          <div className="space-y-4">
            <div className="flex items-start">
              <div className="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center flex-shrink-0">
                <AppIcon className="fas fa-briefcase text-blue-600" />
              </div>
              <div className="ml-4">
                <p className="text-sm text-gray-500">应聘岗位</p>
                <p className="font-semibold text-gray-800">{inviteData?.job.title}</p>
                {inviteData?.job.department && (
                  <p className="text-sm text-gray-500">{inviteData.job.department}</p>
                )}
              </div>
            </div>
            
            <div className="flex items-start">
              <div className="w-10 h-10 bg-green-100 rounded-lg flex items-center justify-center flex-shrink-0">
                <AppIcon className="fas fa-calendar-alt text-green-600" />
              </div>
              <div className="ml-4">
                <p className="text-sm text-gray-500">面试时间</p>
                <p className="font-semibold text-gray-800">
                  {inviteData?.interview.scheduledAt 
                    ? formatDateTime(inviteData.interview.scheduledAt)
                    : '待定'}
                </p>
              </div>
            </div>
            
            <div className="flex items-start">
              <div className="w-10 h-10 bg-purple-100 rounded-lg flex items-center justify-center flex-shrink-0">
                <AppIcon className="fas fa-user text-purple-600" />
              </div>
              <div className="ml-4">
                <p className="text-sm text-gray-500">候选人</p>
                <p className="font-semibold text-gray-800">{inviteData?.candidate.name}</p>
              </div>
            </div>
          </div>
        </div>

        {/* 姓名确认 */}
        <div className="mb-6">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            确认您的姓名
          </label>
          <input
            type="text"
            value={candidateName}
            onChange={(e) => setCandidateName(e.target.value)}
            placeholder="请输入您的姓名"
            className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        {/* 加入按钮 */}
        <button
          onClick={handleJoinMeeting}
          disabled={!candidateName.trim()}
          className="w-full py-4 bg-blue-600 text-white rounded-xl font-semibold hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <AppIcon className="fas fa-video mr-2" />
          加入面试
        </button>

        {/* 提示 */}
        <div className="mt-6 text-center">
          <p className="text-xs text-gray-400">
            加入面试即表示您同意我们记录本次面试内容用于评估
          </p>
        </div>

        {/* 设备检查提示 */}
        <div className="mt-6 bg-yellow-50 rounded-lg p-4">
          <h4 className="font-medium text-yellow-800 mb-2">
            <AppIcon className="fas fa-lightbulb mr-2" />
            面试前准备
          </h4>
          <ul className="text-sm text-yellow-700 space-y-1">
            <li>• 确保网络连接稳定</li>
            <li>• 检查摄像头和麦克风是否正常</li>
            <li>• 选择安静、光线充足的环境</li>
            <li>• 建议使用Chrome或Edge浏览器</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
