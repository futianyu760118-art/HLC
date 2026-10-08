// @ts-nocheck
/**
 * 我的证书（员工门户）— 证书墙 + 下载 + 验证
 */
import React, { useEffect, useState } from 'react';
import { Layout } from '../../components/Layout';
import { PageHeader, EmptyState } from '../../components/PageParts';
import { fileApi } from '../../utils/api';
import apiClient from '../../utils/api';
import toast from '../../utils/toast';
import AppIcon from '../../components/AppIcon';
import { ProtectedImage } from '../../components/ProtectedFile';

export default function P_portal_certificates() {
  const [certs, setCerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [preview, setPreview] = useState(null);

  const load = () => {
    setLoading(true);
    setLoadError(false);
    apiClient.get('/portal/certificates').then(setCerts)
      .catch(e => { toast.error(e.message); setLoadError(true); }).finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  return (
    <Layout>
      <div className="max-w-5xl mx-auto px-4 md:px-6 py-6">
        <PageHeader icon="fa-certificate" title="我的证书" subtitle="完成课程后自动颁发，可下载分享" />

        {loading ? (
          <div className="flex justify-center py-20"><AppIcon className="fas fa-spinner fa-spin text-2xl text-primary" /></div>
        ) : loadError ? (
          <div className="p-10 text-center"><p className="text-danger mb-3">证书数据加载失败</p><button onClick={load} className="text-sm text-primary hover:underline">重试</button></div>
        ) : certs.length === 0 ? (
          <EmptyState icon="fa-certificate" title="还没有证书" hint="完成课程学习后，系统将自动为你颁发证书" />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {certs.map(c => (
              <div key={c.id} className="group bg-white rounded-xl border border-border-light overflow-hidden hover:shadow-card-hover transition-all">
                {/* 证书预览（缩略图）*/}
                <div className="relative aspect-[1200/850] bg-gradient-to-br from-amber-50 to-yellow-50 cursor-pointer overflow-hidden" onClick={() => setPreview(c)}>
                  {c.imageUrl ? (
                    <ProtectedImage fileUrl={c.imageUrl} alt={c.courseTitle} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500" />
                  ) : (
                    <div className="w-full h-full flex flex-col items-center justify-center p-4 border-4 border-amber-300/40 m-2">
                      <AppIcon className="fas fa-certificate text-4xl text-amber-400 mb-2" />
                      <div className="text-sm font-bold text-amber-700 text-center">{c.courseTitle}</div>
                    </div>
                  )}
                </div>
                {/* 信息 */}
                <div className="p-3">
                  <div className="font-medium text-text-primary text-sm line-clamp-1">{c.courseTitle}</div>
                  <div className="text-xs text-text-secondary mt-1">编号：{c.certNo}</div>
                  <div className="text-xs text-text-secondary">{new Date(c.issuedAt).toLocaleDateString('zh-CN')}</div>
                  <div className="mt-2 flex gap-2">
                    {c.imageUrl && (
                      <button type="button" onClick={() => fileApi.download(c.imageUrl, `${c.courseTitle || 'certificate'}.png`).catch((e: any) => toast.error(e.message || '下载失败'))} className="flex-1 text-xs py-1 border border-border-light rounded text-center text-primary hover:bg-primary/5 flex items-center justify-center gap-1">
                        <AppIcon className="fas fa-download text-xs" /> 下载
                      </button>
                    )}
                    <button onClick={() => setPreview(c)} className="flex-1 text-xs py-1 border border-border-light rounded text-center text-text-secondary hover:bg-bg-light flex items-center justify-center gap-1">
                      <AppIcon className="fas fa-eye text-xs" /> 查看
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* 大图预览弹窗 */}
        {preview && (
          <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4" onClick={() => setPreview(null)}>
            <div className="max-w-4xl max-h-[90vh] relative" onClick={e => e.stopPropagation()}>
              {preview.imageUrl ? (
                <ProtectedImage fileUrl={preview.imageUrl} alt="" className="max-w-full max-h-[85vh] rounded-lg shadow-2xl" />
              ) : (
                <div className="bg-gradient-to-br from-amber-50 to-yellow-50 border-4 border-amber-300/40 rounded-lg p-12 flex flex-col items-center justify-center min-h-[60vh]">
                  <AppIcon className="fas fa-certificate text-6xl text-amber-400 mb-4" />
                  <div className="text-xl font-bold text-amber-700 text-center">{preview.courseTitle}</div>
                  <div className="text-sm text-amber-600 mt-2">{preview.employeeName}</div>
                </div>
              )}
              <div className="mt-3 text-center">
                <div className="text-white font-medium">{preview.courseTitle}</div>
                <div className="text-white/60 text-sm">证书编号：{preview.certNo}</div>
              </div>
              <button onClick={() => setPreview(null)} className="absolute -top-3 -right-3 w-8 h-8 bg-white rounded-full flex items-center justify-center shadow-lg">
                <AppIcon className="fas fa-times text-text-secondary" />
              </button>
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
}
