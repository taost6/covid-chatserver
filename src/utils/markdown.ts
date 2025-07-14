/**
 * マークダウンテキストをHTMLに変換するユーティリティ
 */

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
  
  // Escape HTML first (but preserve line breaks)
  const escaped = processed
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
  
  let result = escaped;
  
  // Convert markdown formatting to HTML
  
  // Bold text: **text** or __text__
  result = result.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  result = result.replace(/__(.*?)__/g, '<strong>$1</strong>');
  
  // Italic text: *text* or _text_ (but not if it's part of a bold pattern)
  result = result.replace(/(?<!\*)\*([^*]+?)\*(?!\*)/g, '<em>$1</em>');
  result = result.replace(/(?<!_)_([^_]+?)_(?!_)/g, '<em>$1</em>');
  
  // Code inline: `code`
  result = result.replace(/`([^`]+?)`/g, '<code class="inline-code">$1</code>');
  
  // Code blocks: ```code```
  result = result.replace(/```([\s\S]*?)```/g, '<pre class="code-block"><code>$1</code></pre>');
  
  // Headers: # Header, ## Header, ### Header
  result = result.replace(/^### (.*$)/gm, '<h3 class="markdown-header">$1</h3>');
  result = result.replace(/^## (.*$)/gm, '<h2 class="markdown-header">$1</h2>');
  result = result.replace(/^# (.*$)/gm, '<h1 class="markdown-header">$1</h1>');
  
  // Handle lists separately for better control
  
  // First, mark bullet list items with a temporary marker
  result = result.replace(/^[\s]*[-*+]\s+(.*)$/gm, '{{BULLET_LIST_ITEM}}$1{{/BULLET_LIST_ITEM}}');
  
  // Mark numbered list items with a temporary marker
  result = result.replace(/^[\s]*\d+\.\s+(.*)$/gm, '{{NUMBERED_LIST_ITEM}}$1{{/NUMBERED_LIST_ITEM}}');
  
  // Convert bullet list items to HTML
  result = result.replace(/{{BULLET_LIST_ITEM}}(.*?){{\/BULLET_LIST_ITEM}}/g, '<li class="markdown-list-item">$1</li>');
  
  // Convert numbered list items to HTML
  result = result.replace(/{{NUMBERED_LIST_ITEM}}(.*?){{\/NUMBERED_LIST_ITEM}}/g, '<li class="markdown-numbered-list-item">$1</li>');
  
  // Wrap consecutive bullet list items in ul tags
  result = result.replace(/((?:<li class="markdown-list-item">.*?<\/li>\s*)+)/gs, '<ul class="markdown-list">$1</ul>');
  
  // Wrap consecutive numbered list items in ol tags
  result = result.replace(/((?:<li class="markdown-numbered-list-item">.*?<\/li>\s*)+)/gs, '<ol class="markdown-list">$1</ol>');
  
  // Links: [text](url)
  const linkRegex = /\[([^\]]+)\]\(([^)]+)\)/g;
  result = result.replace(linkRegex, (match, text, url) => {
    // Handle internal routes
    if (url.startsWith('/')) {
      return `<a href="#" onclick="handleInternalLink('${url}'); return false;" class="system-link">${text}</a>`;
    }
    // Handle external links
    return `<a href="${url}" target="_blank" rel="noopener noreferrer" class="system-link">${text}</a>`;
  });
  
  // Blockquotes: > text
  result = result.replace(/^&gt;\s+(.*)$/gm, '<blockquote class="markdown-blockquote">$1</blockquote>');
  
  // Horizontal rules: --- or ***
  result = result.replace(/^(---|\*\*\*)$/gm, '<hr class="markdown-hr">');
  
  return result;
}

// メッセージ用のマークダウン処理（function callフィルタリング有効）
export function processMessage(message: string): string {
  return processMarkdown(message, true);
}

// 評価レポート用のマークダウン処理（function callフィルタリング無効）
export function processEvaluation(text: string): string {
  return processMarkdown(text, false);
}