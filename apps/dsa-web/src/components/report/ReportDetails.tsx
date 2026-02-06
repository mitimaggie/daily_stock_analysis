import type React from 'react';
import { useState } from 'react';
import type { ReportDetails as ReportDetailsType } from '../../types/analysis';
import { Card } from '../common';

// 可选：用 markdown 渲染长文本，无依赖时降级为纯文本
function MarkdownOrText({ text }: { text: string }) {
  if (!text || typeof text !== 'string') return null;
  const normalized = text.replace(/^```(?:json)?\s*\n?/i, '').replace(/\n?```\s*$/i, '').trim();
  try {
    const ReactMarkdown = require('react-markdown');
    return (
      <div className="prose prose-invert prose-sm max-w-none text-left text-white/90 leading-relaxed [&_strong]:text-white [&_p]:mb-2">
        <ReactMarkdown>{normalized}</ReactMarkdown>
      </div>
    );
  } catch {
    return (
      <div className="text-sm text-white/90 whitespace-pre-wrap leading-relaxed">
        {normalized}
      </div>
    );
  }
}

/** 从原始结果中抽出可读文本块并渲染为 markdown/文本 */
function renderRawAsText(data: Record<string, unknown> | undefined) {
  if (!data || typeof data !== 'object') return null;
  const texts: { label: string; value: string }[] = [];
  const rawResponse = data.rawResponse ?? data.raw_response;
  const analysisSummary = data.analysisSummary ?? data.analysis_summary;
  const riskWarning = data.riskWarning ?? data.risk_warning;
  if (typeof rawResponse === 'string' && rawResponse.length > 0) {
    texts.push({ label: '原始输出', value: rawResponse });
  }
  if (typeof analysisSummary === 'string' && analysisSummary.length > 0 && !texts.some(t => t.value === analysisSummary)) {
    texts.push({ label: '分析结论', value: analysisSummary });
  }
  if (typeof riskWarning === 'string' && riskWarning.length > 0) {
    texts.push({ label: '风险提示', value: riskWarning });
  }
  if (texts.length === 0) return null;
  return (
    <div className="space-y-4">
      {texts.map(({ label, value }) => (
        <div key={label}>
          <span className="text-xs text-muted block mb-1">{label}</span>
          <MarkdownOrText text={value} />
        </div>
      ))}
    </div>
  );
}

interface ReportDetailsProps {
  details?: ReportDetailsType;
  queryId?: string;
}

/**
 * 透明度与追溯区组件 - 终端风格，支持 markdown/文本展示
 */
export const ReportDetails: React.FC<ReportDetailsProps> = ({
  details,
  queryId,
}) => {
  const [showRaw, setShowRaw] = useState(false);
  const [showSnapshot, setShowSnapshot] = useState(false);
  const [showAsCode, setShowAsCode] = useState(false);
  const [copied, setCopied] = useState(false);

  if (!details?.rawResult && !details?.contextSnapshot && !queryId) {
    return null;
  }

  const copyToClipboard = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Copy failed:', err);
    }
  };

  const renderJson = (data: unknown) => {
    const jsonStr = JSON.stringify(data, null, 2);
    return (
      <div className="relative overflow-hidden">
        <button
          type="button"
          onClick={() => copyToClipboard(jsonStr)}
          className="absolute top-2 right-2 text-xs text-muted hover:text-cyan transition-colors"
        >
          {copied ? 'Copied!' : 'Copy'}
        </button>
        <pre className="text-xs text-secondary font-mono overflow-x-auto p-3 bg-base rounded-lg max-h-80 overflow-y-auto text-left w-0 min-w-full">
          {jsonStr}
        </pre>
      </div>
    );
  };

  return (
    <Card variant="bordered" padding="md" className="text-left">
      <div className="mb-3 flex items-baseline gap-2">
        <span className="label-uppercase">TRANSPARENCY</span>
        <h3 className="text-base font-semibold text-white mt-0.5">数据追溯</h3>
      </div>

      {/* Query ID */}
      {queryId && (
        <div className="flex items-center gap-2 text-xs text-muted mb-3 pb-3 border-b border-white/5">
          <span>Query ID:</span>
          <code className="font-mono text-xs text-cyan bg-cyan/10 px-1.5 py-0.5 rounded">
            {queryId}
          </code>
        </div>
      )}

      {/* 折叠区域 */}
      <div className="space-y-2">
        {/* 原始分析结果 */}
        {details?.rawResult && (
          <div>
            <button
              type="button"
              onClick={() => setShowRaw(!showRaw)}
              className="w-full flex items-center justify-between p-2.5 rounded-lg bg-elevated hover:bg-hover transition-colors"
            >
              <span className="text-xs text-white">原始分析结果</span>
              <svg
                className={`w-3.5 h-3.5 text-muted transition-transform ${showRaw ? 'rotate-180' : ''}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
            {showRaw && (() => {
              const rawObj = details.rawResult as Record<string, unknown> | undefined;
              const textBlock = rawObj ? renderRawAsText(rawObj) : null;
              return (
                <div className="mt-2 animate-fade-in min-w-0 overflow-hidden space-y-3">
                  {!showAsCode && textBlock}
                  {!showAsCode && textBlock && (
                    <button
                      type="button"
                      onClick={() => setShowAsCode(true)}
                      className="text-xs text-muted hover:text-cyan"
                    >
                      显示完整 JSON
                    </button>
                  )}
                  {showAsCode && (
                    <>
                      <button
                        type="button"
                        onClick={() => setShowAsCode(false)}
                        className="text-xs text-muted hover:text-cyan"
                      >
                        显示文本
                      </button>
                      {renderJson(details.rawResult)}
                    </>
                  )}
                  {!showAsCode && !textBlock && renderJson(details.rawResult)}
                </div>
              );
            })()}
          </div>
        )}

        {/* 分析快照 */}
        {details?.contextSnapshot && (
          <div>
            <button
              type="button"
              onClick={() => setShowSnapshot(!showSnapshot)}
              className="w-full flex items-center justify-between p-2.5 rounded-lg bg-elevated hover:bg-hover transition-colors"
            >
              <span className="text-xs text-white">分析快照</span>
              <svg
                className={`w-3.5 h-3.5 text-muted transition-transform ${showSnapshot ? 'rotate-180' : ''}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
            {showSnapshot && (
              <div className="mt-2 animate-fade-in min-w-0 overflow-hidden">
                {typeof details.contextSnapshot === 'object' && details.contextSnapshot !== null && (
                  <div className="space-y-2">
                    {(['analysis_summary', 'history_summary', 'technical_analysis_report'] as const).map(key => {
                      const v = (details.contextSnapshot as Record<string, unknown>)?.[key];
                      if (typeof v !== 'string' || !v) return null;
                      return (
                        <div key={key}>
                          <span className="text-xs text-muted block mb-1">{key}</span>
                          <MarkdownOrText text={v} />
                        </div>
                      );
                    })}
                  </div>
                )}
                {(!details.contextSnapshot || typeof details.contextSnapshot !== 'object' || Object.keys(details.contextSnapshot).length === 0) && renderJson(details.contextSnapshot)}
                {details.contextSnapshot && typeof details.contextSnapshot === 'object' && Object.keys(details.contextSnapshot).length > 0 && (
                  <details className="mt-2">
                    <summary className="text-xs text-muted cursor-pointer">完整快照 (JSON)</summary>
                    <div className="mt-1">{renderJson(details.contextSnapshot)}</div>
                  </details>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  );
};
