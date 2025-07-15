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
  console.log('[Markdown] Link processing:', { href, title, text, hrefType: typeof href, textType: typeof text });
  
  // パラメータの型チェックと安全な変換
  let actualHref: string = '';
  let actualText: string = '';
  let actualTitle: string = '';
  
  // hrefの処理
  if (typeof href === 'string') {
    actualHref = href;
  } else if (typeof href === 'object' && href !== null) {
    console.warn('[Markdown] href is object:', href);
    if ('href' in href && typeof href.href === 'string') {
      actualHref = href.href;
    } else if ('raw' in href && typeof href.raw === 'string') {
      actualHref = href.raw;
    } else {
      actualHref = String(href);
    }
  } else {
    actualHref = String(href || '');
  }
  
  // textの処理
  if (typeof text === 'string') {
    actualText = text;
  } else if (typeof text === 'object' && text !== null) {
    console.warn('[Markdown] text is object:', text);
    console.log('[Markdown] text object keys:', Object.keys(text));
    console.log('[Markdown] text object values:', Object.values(text));
    
    // オブジェクトの場合、適切な文字列表現を取得
    if ('text' in text && typeof text.text === 'string') {
      actualText = text.text;
    } else if ('content' in text && typeof text.content === 'string') {
      actualText = text.content;
    } else if ('raw' in text && typeof text.raw === 'string') {
      actualText = text.raw;
    } else if ('value' in text && typeof text.value === 'string') {
      actualText = text.value;
    } else if ('label' in text && typeof text.label === 'string') {
      actualText = text.label;
    } else {
      // オブジェクトの最初の文字列プロパティを使用
      const stringValue = Object.values(text).find(val => typeof val === 'string' && val.trim() !== '');
      if (stringValue) {
        actualText = stringValue as string;
      } else {
        actualText = String(text);
      }
    }
  } else {
    actualText = String(text || '');
  }
  
  // textが空の場合はエラーを出力
  if (!actualText || actualText.trim() === '') {
    console.error('[Markdown] Link text is empty!', { originalText: text, processedText: actualText });
    actualText = 'リンク'; // デフォルトテキスト
  }
  
  // titleの処理
  if (typeof title === 'string') {
    actualTitle = title;
  } else if (typeof title === 'object' && title !== null) {
    if ('raw' in title && typeof title.raw === 'string') {
      actualTitle = title.raw;
    } else {
      actualTitle = String(title);
    }
  } else if (title !== null && title !== undefined) {
    actualTitle = String(title);
  }
  
  const titleAttr = actualTitle ? ` title="${actualTitle}"` : '';
  
  console.log('[Markdown] Processed link params:', { actualHref, actualText, actualTitle });
  
  if (actualHref.startsWith('/')) {
    // 内部リンク
    console.log('[Markdown] Creating internal link:', actualHref);
    const result = `<a href="#" onclick="handleInternalLink('${actualHref}'); return false;" class="system-link"${titleAttr}>${actualText}</a>`;
    console.log('[Markdown] Internal link result:', result);
    return result;
  }
  // 外部リンク
  console.log('[Markdown] Creating external link:', actualHref);
  const result = `<a href="${actualHref}" target="_blank" rel="noopener noreferrer" class="system-link"${titleAttr}>${actualText}</a>`;
  console.log('[Markdown] External link result:', result);
  return result;
};

// コードブロックのカスタム処理
renderer.code = function(code, language) {
  console.log('[Markdown] Code renderer:', { code, language, codeType: typeof code, languageType: typeof language });
  
  let safeCode = '';
  if (typeof code === 'string') {
    safeCode = code;
  } else if (typeof code === 'object' && code !== null) {
    console.warn('[Markdown] Code is object:', code);
    if (code.raw && typeof code.raw === 'string') {
      safeCode = code.raw;
    } else if (code.text && typeof code.text === 'string') {
      safeCode = code.text;
    } else if (code.content && typeof code.content === 'string') {
      safeCode = code.content;
    } else {
      safeCode = String(code);
    }
  } else {
    safeCode = String(code || '');
  }
  
  let safeLanguage = '';
  if (typeof language === 'string') {
    safeLanguage = language;
  } else if (typeof language === 'object' && language !== null) {
    safeLanguage = String(language);
  } else {
    safeLanguage = String(language || '');
  }
  
  console.log('[Markdown] Processed code:', { safeCode, safeLanguage });
  return `<pre class="code-block"><code class="language-${safeLanguage}">${safeCode}</code></pre>`;
};

// インラインコードのカスタム処理
renderer.codespan = function(code) {
  console.log('[Markdown] Codespan renderer:', { code, codeType: typeof code });
  
  let safeCode = '';
  if (typeof code === 'string') {
    safeCode = code;
  } else if (typeof code === 'object' && code !== null) {
    console.warn('[Markdown] Codespan is object:', code);
    if (code.raw && typeof code.raw === 'string') {
      safeCode = code.raw;
    } else if (code.text && typeof code.text === 'string') {
      safeCode = code.text;
    } else if (code.content && typeof code.content === 'string') {
      safeCode = code.content;
    } else {
      safeCode = String(code);
    }
  } else {
    safeCode = String(code || '');
  }
  
  console.log('[Markdown] Processed codespan:', { safeCode });
  return `<code class="inline-code">${safeCode}</code>`;
};

// 見出しのカスタム処理
renderer.heading = function(text, level) {
  console.log('[Markdown] Heading renderer:', { text, level, textType: typeof text, levelType: typeof level });
  
  let safeText = '';
  if (typeof text === 'string') {
    safeText = text;
  } else if (typeof text === 'object' && text !== null) {
    console.warn('[Markdown] Heading text is object:', text);
    // オブジェクトの場合、適切な文字列プロパティを探す
    if (text.raw && typeof text.raw === 'string') {
      safeText = text.raw;
    } else if (text.text && typeof text.text === 'string') {
      safeText = text.text;
    } else if (text.content && typeof text.content === 'string') {
      safeText = text.content;
    } else {
      safeText = JSON.stringify(text);
    }
  } else {
    safeText = String(text || '');
  }
  
  const safeLevel = typeof level === 'number' ? level : parseInt(String(level || '1'));
  console.log('[Markdown] Processed heading:', { safeText, safeLevel });
  return `<h${safeLevel} class="markdown-header">${safeText}</h${safeLevel}>`;
};

// リストのカスタム処理
renderer.list = function(body, ordered) {
  console.log('[Markdown] List renderer:', { body, ordered, bodyType: typeof body });
  
  let safeBody = '';
  if (typeof body === 'string') {
    safeBody = body;
  } else if (typeof body === 'object' && body !== null) {
    console.warn('[Markdown] List body is object:', body);
    if (body.raw && typeof body.raw === 'string') {
      safeBody = body.raw;
    } else if (body.text && typeof body.text === 'string') {
      safeBody = body.text;
    } else if (body.content && typeof body.content === 'string') {
      safeBody = body.content;
    } else {
      safeBody = String(body);
    }
  } else {
    safeBody = String(body || '');
  }
  
  const tag = ordered ? 'ol' : 'ul';
  console.log('[Markdown] Processed list:', { safeBody, tag });
  return `<${tag} class="markdown-list">${safeBody}</${tag}>`;
};

renderer.listitem = function(text) {
  console.log('[Markdown] List item renderer:', { text, textType: typeof text });
  
  let safeText = '';
  if (typeof text === 'string') {
    safeText = text;
  } else if (typeof text === 'object' && text !== null) {
    console.warn('[Markdown] List item text is object:', text);
    if (text.raw && typeof text.raw === 'string') {
      safeText = text.raw;
    } else if (text.text && typeof text.text === 'string') {
      safeText = text.text;
    } else if (text.content && typeof text.content === 'string') {
      safeText = text.content;
    } else {
      safeText = String(text);
    }
  } else {
    safeText = String(text || '');
  }
  
  console.log('[Markdown] Processed list item:', { safeText });
  return `<li class="markdown-list-item">${safeText}</li>`;
};

// 引用のカスタム処理
renderer.blockquote = function(quote) {
  console.log('[Markdown] Blockquote renderer:', { quote, quoteType: typeof quote });
  
  let safeQuote = '';
  if (typeof quote === 'string') {
    safeQuote = quote;
  } else if (typeof quote === 'object' && quote !== null) {
    console.warn('[Markdown] Blockquote is object:', quote);
    if (quote.raw && typeof quote.raw === 'string') {
      safeQuote = quote.raw;
    } else if (quote.text && typeof quote.text === 'string') {
      safeQuote = quote.text;
    } else if (quote.content && typeof quote.content === 'string') {
      safeQuote = quote.content;
    } else {
      safeQuote = String(quote);
    }
  } else {
    safeQuote = String(quote || '');
  }
  
  console.log('[Markdown] Processed blockquote:', { safeQuote });
  return `<blockquote class="markdown-blockquote">${safeQuote}</blockquote>`;
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