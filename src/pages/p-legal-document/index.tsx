import { useEffect, useState, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import { Link } from 'react-router-dom';
import rehypeSanitize from 'rehype-sanitize';
import remarkGfm from 'remark-gfm';
import AppIcon from '../../components/AppIcon';

type LegalDocumentType = 'terms' | 'privacy';

interface LegalSection {
  id: string;
  title: string;
}

interface LegalDocumentDefinition {
  title: string;
  source: string;
  sections: LegalSection[];
}

const LEGAL_DOCUMENTS: Record<LegalDocumentType, LegalDocumentDefinition> = {
  terms: {
    title: '服务条款',
    source: '/docs/compliance/terms-of-service.md',
    sections: [
      { id: 'scope', title: '一、适用范围' },
      { id: 'subscription', title: '二、服务与订阅' },
      { id: 'accounts', title: '三、账号与管理员' },
      { id: 'customer-data', title: '四、客户数据' },
      { id: 'acceptable-use', title: '五、使用限制' },
      { id: 'fees', title: '六、费用与续费' },
      { id: 'maintenance', title: '七、维护与变更' },
      { id: 'third-party', title: '八、第三方服务' },
      { id: 'intellectual-property', title: '九、知识产权' },
      { id: 'security', title: '十、保密与安全' },
      { id: 'termination', title: '十一、暂停与终止' },
      { id: 'liability', title: '十二、责任' },
      { id: 'notices', title: '十三、通知与条款更新' },
      { id: 'disputes', title: '十四、法律适用与争议解决' },
    ],
  },
  privacy: {
    title: '隐私政策',
    source: '/docs/compliance/privacy-policy.md',
    sections: [
      { id: 'scope', title: '一、适用范围与处理角色' },
      { id: 'information', title: '二、处理的信息' },
      { id: 'purposes', title: '三、处理目的' },
      { id: 'sensitive-information', title: '四、敏感个人信息' },
      { id: 'sources', title: '五、信息来源' },
      { id: 'cookies', title: '六、Cookie 与本地存储' },
      { id: 'sharing', title: '七、委托处理、共享与转移' },
      { id: 'retention', title: '八、保存与删除' },
      { id: 'security', title: '九、安全措施与事件处置' },
      { id: 'rights', title: '十、个人信息权利' },
      { id: 'minors', title: '十一、未成年人信息' },
      { id: 'updates', title: '十二、政策更新' },
      { id: 'contact', title: '十三、联系与请求' },
    ],
  },
};

function childrenText(children: ReactNode): string {
  if (Array.isArray(children)) return children.map(childrenText).join('');
  return typeof children === 'string' || typeof children === 'number' ? String(children) : '';
}

function DocumentNavigation({ sections }: { sections: LegalSection[] }) {
  return (
    <nav aria-label="协议目录">
      <p className="mb-3 text-xs font-semibold text-slate-500">目录</p>
      <ol className="space-y-2 border-l border-slate-200">
        {sections.map(section => (
          <li key={section.id}>
            <a href={`#${section.id}`} className="block border-l-2 border-transparent py-0.5 pl-4 text-sm leading-5 text-slate-500 hover:border-blue-600 hover:text-slate-900">
              {section.title}
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}

export default function LegalDocumentPage({ type }: { type: LegalDocumentType }) {
  const document = LEGAL_DOCUMENTS[type];
  const [content, setContent] = useState('');
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const originalTitle = window.document.title;
    window.document.title = `${document.title} - 恒聘通 HRM`;
    return () => { window.document.title = originalTitle; };
  }, [document.title]);

  useEffect(() => {
    const controller = new AbortController();
    setStatus('loading');
    setContent('');

    fetch(document.source, {
      headers: { Accept: 'text/markdown' },
      signal: controller.signal,
    })
      .then(response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.text();
      })
      .then(markdown => {
        setContent(markdown);
        setStatus('ready');
      })
      .catch(error => {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setStatus('error');
      });

    return () => controller.abort();
  }, [document.source, reloadKey]);

  const headingId = (children: ReactNode) => (
    document.sections.find(section => section.title === childrenText(children))?.id
  );

  return (
    <div className="min-h-screen bg-white text-slate-800">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5 sm:px-8">
          <Link to="/login" className="flex items-center gap-3 text-slate-950" aria-label="恒聘通 HRM 登录页">
            <span className="flex h-8 w-8 items-center justify-center bg-blue-600 text-xs font-bold text-white">HPT</span>
            <span className="text-sm font-semibold">恒聘通 HRM</span>
          </Link>
          <Link to="/login" className="inline-flex h-9 items-center gap-2 text-sm font-medium text-slate-600 hover:text-blue-700">
            <AppIcon className="fas fa-arrow-left text-xs" />
            返回登录
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-5 py-8 sm:px-8 sm:py-12">
        <details className="mb-8 border-y border-slate-200 py-3 lg:hidden">
          <summary className="cursor-pointer text-sm font-semibold text-slate-700">目录</summary>
          <div className="mt-4">
            <DocumentNavigation sections={document.sections} />
          </div>
        </details>

        <div className="grid items-start gap-12 lg:grid-cols-[220px_minmax(0,760px)] lg:justify-center">
          <aside className="sticky top-24 hidden max-h-[calc(100vh-7rem)] overflow-y-auto pr-4 lg:block">
            <DocumentNavigation sections={document.sections} />
          </aside>

          <article className="min-w-0" aria-busy={status === 'loading'}>
            {status === 'loading' && (
              <div className="min-h-[420px] border-t-2 border-slate-900 pt-8" role="status">
                <div className="flex items-center gap-3 text-sm text-slate-500">
                  <AppIcon className="fas fa-spinner fa-spin text-blue-600" />
                  正在加载协议正文
                </div>
                <div className="mt-10 space-y-4" aria-hidden="true">
                  <div className="h-8 w-2/3 bg-slate-100" />
                  <div className="h-4 w-full bg-slate-100" />
                  <div className="h-4 w-5/6 bg-slate-100" />
                  <div className="mt-10 h-6 w-1/3 bg-slate-100" />
                  <div className="h-4 w-full bg-slate-100" />
                </div>
              </div>
            )}

            {status === 'error' && (
              <div className="min-h-[420px] border-t-2 border-slate-900 pt-8" role="alert">
                <h1 className="text-2xl font-semibold text-slate-950">协议正文加载失败</h1>
                <p className="mt-3 text-sm leading-6 text-slate-600">请检查网络连接后重新加载。</p>
                <button type="button" onClick={() => setReloadKey(key => key + 1)} className="mt-6 inline-flex h-9 items-center gap-2 border border-slate-300 px-4 text-sm font-medium text-slate-700 hover:border-slate-500 hover:text-slate-950">
                  <AppIcon className="fas fa-rotate-right text-xs" />
                  重新加载
                </button>
              </div>
            )}

            {status === 'ready' && (
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeSanitize]}
                components={{
                  h1: ({ children }) => <h1 className="border-t-2 border-slate-950 pt-8 text-3xl font-semibold leading-tight text-slate-950 sm:text-4xl">{children}</h1>,
                  h2: ({ children }) => <h2 id={headingId(children)} className="scroll-mt-24 border-t border-slate-200 pt-8 text-xl font-semibold leading-8 text-slate-950 first:border-t-0">{children}</h2>,
                  h3: ({ children }) => <h3 className="mt-7 text-base font-semibold text-slate-900">{children}</h3>,
                  p: ({ children }) => <p className="mt-4 text-[15px] leading-8 text-slate-700">{children}</p>,
                  blockquote: ({ children }) => <div className="mt-4 border-l-2 border-blue-600 pl-4 text-sm text-slate-500">{children}</div>,
                  ul: ({ children }) => <ul className="mt-4 list-disc space-y-2 pl-6 text-[15px] leading-7 text-slate-700">{children}</ul>,
                  ol: ({ children }) => <ol className="mt-4 list-decimal space-y-2 pl-6 text-[15px] leading-7 text-slate-700">{children}</ol>,
                  li: ({ children }) => <li className="pl-1">{children}</li>,
                  strong: ({ children }) => <strong className="font-semibold text-slate-950">{children}</strong>,
                  a: ({ href, children }) => <a href={href} target="_blank" rel="noreferrer" className="font-medium text-blue-700 underline decoration-blue-200 underline-offset-4 hover:decoration-blue-700">{children}</a>,
                }}
              >
                {content}
              </ReactMarkdown>
            )}
          </article>
        </div>
      </main>
    </div>
  );
}
