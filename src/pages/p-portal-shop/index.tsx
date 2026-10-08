// @ts-nocheck
/**
 * 积分商城（员工门户）— 商品网格 + 兑换 + 记录
 */
import React, { useEffect, useState } from 'react';
import { Layout } from '../../components/Layout';
import { PageHeader, EmptyState } from '../../components/PageParts';
import apiClient from '../../utils/api';
import toast from '../../utils/toast';
import confirm from '../../components/ConfirmDialog';
import AppIcon from '../../components/AppIcon';

const TYPE_LABELS = { virtual: '虚拟权益', physical: '实物', badge: '徽章' };
const TYPE_COLORS = { virtual: 'from-purple-500 to-pink-500', physical: 'from-blue-500 to-cyan-500', badge: 'from-amber-500 to-orange-500' };

export default function P_portal_shop() {
  const [data, setData] = useState({ items: [], myPoints: 0 });
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [exchangingId, setExchangingId] = useState<string | null>(null);
  const [tab, setTab] = useState<'shop' | 'records'>('shop');

  const load = async () => {
    setLoading(true);
    try {
      const [r, recs] = await Promise.all([
        apiClient.get('/portal/rewards'),
        apiClient.get('/portal/exchange-records'),
      ]);
      setData(r); setRecords(recs || []);
    } catch (e) { toast.error(e.message); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const exchange = async (reward) => {
    if (exchangingId) return;
    if (data.myPoints < reward.pointsCost) { toast.error('积分不足'); return; }
    if (!await confirm(`用 ${reward.pointsCost} 积分兑换「${reward.name}」？`)) return;
    setExchangingId(reward.id);
    try {
      const r = await apiClient.post(`/portal/rewards/${reward.id}/exchange`);
      toast.success(r.redeemCode ? `兑换成功！兑换码：${r.redeemCode}` : '兑换成功！');
      load();
    } catch (e) { toast.error(e.message); }
    finally { setExchangingId(null); }
  };

  return (
    <Layout>
      <div className="max-w-5xl mx-auto px-4 md:px-6 py-6">
        <PageHeader icon="fa-store" title="积分商城" subtitle={`${data.myPoints} 积分可用`}
          actions={<div className="flex gap-1 bg-bg-light rounded-lg p-1">
            <button onClick={() => setTab('shop')} className={`px-3 py-1.5 rounded-md text-sm ${tab === 'shop' ? 'bg-white shadow-sm font-medium text-primary' : 'text-text-secondary'}`}>商城</button>
            <button onClick={() => setTab('records')} className={`px-3 py-1.5 rounded-md text-sm ${tab === 'records' ? 'bg-white shadow-sm font-medium text-primary' : 'text-text-secondary'}`}>兑换记录</button>
          </div>} />

        {loading ? (
          <div className="flex justify-center py-20"><AppIcon className="fas fa-spinner fa-spin text-2xl text-primary" /></div>
        ) : tab === 'shop' ? (
          data.items.length === 0 ? (
            <EmptyState icon="fa-store" title="商城暂无商品" hint={`您有 ${data.myPoints} 积分，管理员正在上架商品`}
              action={<button onClick={() => window.location.href = '/portal/my-courses'} className="mt-3 text-sm text-primary hover:underline">去学习赚积分 →</button>} />
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
              {data.items.map(r => {
                const canAfford = data.myPoints >= r.pointsCost;
                return (
                  <div key={r.id} className="bg-white rounded-xl border border-border-light overflow-hidden hover:shadow-card transition-shadow">
                    <div className={`aspect-square bg-gradient-to-br ${TYPE_COLORS[r.rewardType] || TYPE_COLORS.virtual} flex items-center justify-center relative`}>
                      <AppIcon className={`fas ${r.icon || 'fa-gift'} text-white text-4xl`} />
                      <span className="absolute top-2 right-2 px-2 py-0.5 rounded text-xs text-white bg-black/40 backdrop-blur-sm">{TYPE_LABELS[r.rewardType]}</span>
                    </div>
                    <div className="p-3">
                      <h3 className="font-medium text-text-primary text-sm line-clamp-1">{r.name}</h3>
                      {r.description && <p className="text-xs text-text-secondary mt-1 line-clamp-2">{r.description}</p>}
                      <div className="mt-2 flex items-center justify-between">
                        <span className="text-warning font-bold flex items-center gap-0.5">
                          <AppIcon className="fas fa-coins text-xs" /> {r.pointsCost}
                        </span>
                        {r.stock !== -1 && <span className="text-xs text-text-secondary">剩{r.stock}</span>}
                      </div>
                      <button onClick={() => exchange(r)} disabled={!canAfford || !r.inStock}
                        className={`mt-2 w-full py-1.5 rounded-lg text-sm font-medium transition-colors ${
                          canAfford && r.inStock ? 'bg-primary text-white hover:bg-blue-700' : 'bg-bg-light text-text-secondary cursor-not-allowed'
                        }`}>
                        {!r.inStock ? '已兑完' : canAfford ? '兑换' : '积分不足'}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )
        ) : (
          /* 兑换记录 */
          records.length === 0 ? (
            <EmptyState icon="fa-receipt" title="暂无兑换记录" hint="去商城兑换心仪的奖品吧" />
          ) : (
            <div className="bg-white rounded-xl border border-border-light overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-bg-light/50 text-text-secondary">
                  <tr><th className="text-left px-4 py-2">商品</th><th className="text-left px-4 py-2">消耗积分</th><th className="text-left px-4 py-2">兑换码</th><th className="text-left px-4 py-2">时间</th></tr>
                </thead>
                <tbody className="divide-y divide-border-light">
                  {records.map(r => (
                    <tr key={r.id} className="hover:bg-bg-light/30">
                      <td className="px-4 py-2 font-medium text-text-primary">{r.rewardName}</td>
                      <td className="px-4 py-2 text-warning">-{r.pointsCost}</td>
                      <td className="px-4 py-2 font-mono text-xs text-primary">{r.redeemCode || '-'}</td>
                      <td className="px-4 py-2 text-text-secondary text-xs">{new Date(r.createdAt).toLocaleDateString('zh-CN')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}
      </div>
    </Layout>
  );
}
