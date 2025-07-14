/**
 * マークダウンテキストをHTMLに変換するユーティリティ（marked.js使用）
 */

import { marked } from 'marked';
import DOMPurify from 'dompurify';

// marked.jsの設定
marked.setOptions({
  breaks: true,        // 改行を<br>に変換
  gfm: true,          // GitHub Flavored Markdown
  silent: false       // エラーを隠さない
});

// カスタムレンダラーを設定
const renderer = new marked.Renderer();

// リンクのカスタム処理
renderer.link = function(href, title, text) {
  const titleAttr = title ? ` title="${title}"` : '';
  if (href?.startsWith('/')) {
    // 内部リンク
    return `<a href="#" onclick="handleInternalLink('${href}'); return false;" class="system-link"${titleAttr}>${text}</a>`;
  }
  // 外部リンク
  return `<a href="${href}" target="_blank" rel="noopener noreferrer" class="system-link"${titleAttr}>${text}</a>`;
};

// コードブロックのカスタム処理
renderer.code = function(code, language) {
  return `<pre class="code-block"><code class="language-${language || ''}">${code}</code></pre>`;
};

// インラインコードのカスタム処理
renderer.codespan = function(code) {
  return `<code class="inline-code">${code}</code>`;
};

// 見出しのカスタム処理
renderer.heading = function(text, level) {
  return `<h${level} class="markdown-header">${text}</h${level}>`;
};

// リストのカスタム処理
renderer.list = function(body, ordered) {
  const tag = ordered ? 'ol' : 'ul';
  return `<${tag} class="markdown-list">${body}</${tag}>`;
};

renderer.listitem = function(text) {
  return `<li class="markdown-list-item">${text}</li>`;
};

// 引用のカスタム処理
renderer.blockquote = function(quote) {
  return `<blockquote class="markdown-blockquote">${quote}</blockquote>`;
};

// 水平線のカスタム処理
renderer.hr = function() {
  return `<hr class="markdown-hr">`;
};

// マークダウンテキストをHTMLに変換する関数
export function processMarkdown(text: string, filterFunctionCalls: boolean = true): string {
  let processed = text;
  
  // Function call関連のテキストを除去（オプション）
  if (filterFunctionCalls) {
    const functionCallPatterns = [
      /end_conversation_and_start_debriefing/g,
      /submit_debriefing_report/g,
      /Tool\s*call\s*detected/gi,
      /Function\s*call/gi,
      /\bfunction\s*:\s*\w+/gi,
      /\btools?\s*=\s*\[?\]?/gi,
      /\btool_choice\s*=/gi,
      /\bassistant_id\s*=/gi,
      /\bthread_id\s*=/gi,
      /\buser_msg\s*=/gi,
      /\bai_role\s*=/gi,
      /^.*end_conversation_and_start_debriefing.*$/gm
    ];
    
    functionCallPatterns.forEach(pattern => {
      processed = processed.replace(pattern, '');
    });
    
    // Clean up any extra whitespace left by filtering (but preserve line breaks)
    processed = processed.replace(/[ \t]+/g, ' ').trim();
  }
  
  // If message is empty after filtering, return original message
  if (!processed && filterFunctionCalls) {
    processed = text;
  }
  
  try {
    // marked.jsでマークダウンをHTMLに変換
    const html = marked(processed, { renderer });
    
    // DOMPurifyでサニタイズ（XSS対策）
    let sanitized = DOMPurify.sanitize(html, {
      ALLOWED_TAGS: [
        'p', 'br', 'strong', 'em', 'u', 's', 'code', 'pre', 
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'ul', 'ol', 'li', 'blockquote', 'hr', 'a'
      ],
      ALLOWED_ATTR: ['href', 'title', 'target', 'rel', 'class', 'onclick'],
      ALLOW_DATA_ATTR: false
    });
    
    // marked.jsがpタグで囲む場合、末尾の不要な改行や空白を除去
    // 単純なテキストの場合、pタグを除去して直接内容を返す
    sanitized = sanitized
      .replace(/^<p>(.+)<\/p>$/s, '$1')  // 単一のpタグで囲まれた場合は除去
      .replace(/^\s+|\s+$/g, '')          // 先頭と末尾の空白文字を除去
      .replace(/\n\s*$/g, '')             // 末尾の改行と空白を除去
      .replace(/<\/p>\s*<p>/g, '</p><p>'); // pタグ間の不要な空白を除去
    
    return sanitized;
  } catch (error) {
    console.error('Markdown processing error:', error);
    // エラー時はプレーンテキストを返す（HTMLエスケープ済み）
    return processed
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }
}

// メッセージ用のマークダウン処理（function callフィルタリング有効）
export function processMessage(message: string): string {
  return processMarkdown(message, true);
}

// 評価レポート用のマークダウン処理（function callフィルタリング無効）
export function processEvaluation(text: string): string {
  return processMarkdown(text, false);
}