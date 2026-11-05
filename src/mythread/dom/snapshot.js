/* Read-only snapshot of visible post cards. Every DOM/layout assumption about
 * Threads lives here; unknown layouts must fail closed (rows=[]), never guess.
 * Evaluated as page.evaluate(SNAPSHOT, options); keep it a single function.
 *   options.replies   scope to <main> and stop at the 'suggested posts' heading
 *   options.parent_id only return cards after this post's permalink
 * Returns {rows:[{permalink,text,reply_count}], candidates, anchor_found,
 *          diagnostics, login, loading, empty} -> consumed by browser.classify().
 * The reply-count number pattern must equal model.COUNT_PATTERN. */
(options = {}) => {
 options = options || {};
 const visible = e => !!(e.getClientRects().length) && getComputedStyle(e).visibility !== 'hidden';
 const boundary = options.replies ? [...document.querySelectorAll('h1,h2,h3,[role="heading"]')].find(e =>
   visible(e) && /推薦|相關貼文|更多貼文|suggested|recommended|related posts|more posts/i.test(e.innerText)) : null;
 const main = [...document.querySelectorAll('main, [role="main"]')].find(visible);
 const allLinks = [...document.querySelectorAll('a[href*="/post/"]')].filter(visible);
 const links = allLinks.filter(e =>
   (!options.replies || (main ? main.contains(e) : !e.closest('nav, aside, [role="navigation"]'))) &&
   (!boundary || !(boundary.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING)));
 const postId = e => new URL(e.href).pathname.match(/\/post\/([A-Za-z0-9_-]+)\/?$/)?.[1];
 // The original post can have an unsupported body (e.g. a quote), but its
 // visible permalink still establishes ordering without inventing its text.
 const anchor = options.parent_id ? links.find(e => postId(e) === options.parent_id) : null;
 const rows = [];
 const replyCount = root => {
   const number = '(?:\\d{1,3}(?:,\\d{3})+|\\d+)(?:\\.\\d+)?\\s*[KMB萬万億亿]?';
   const name = '(?:replies|reply|comments?|回覆|回复|留言|則留言|条回复)';
   const numeric = new RegExp('^' + number + '$', 'i');
   const labelled = new RegExp('^(?:' + name + '\\s*[:：]?\\s*(' + number + ')|(' + number + ')\\s*' + name + ')$', 'i');
   for (const control of root.querySelectorAll('button, [role="button"], a[role="link"]')) {
     // Never read a whole clickable card or a toolbar containing several counts.
     if (!visible(control) || control.querySelector('button, [role="button"]')) continue;
     const labels = [control.getAttribute('aria-label') || '',
       ...[...control.querySelectorAll('[aria-label], title')].map(e => e.getAttribute('aria-label') || e.textContent || '')];
     const text = (control.innerText || '').trim();
     for (const value of [...labels, text]) {
       const match = value.trim().match(labelled);
       if (match) return (match[1] || match[2]).trim();
     }
     if (labels.some(label => new RegExp('^' + name + '$', 'i').test(label.trim())) && numeric.test(text)) return text;
   }
   return null;
 };
 const metadata = text => /^(?:\d+\s*(?:秒|分鐘|分鐘前|分|小時|天|週|周|個月|年|seconds?|minutes?|hours?|days?|weeks?|months?|years?|[smhdwy])(?:前| ago)?|剛剛|just now)$/i.test(text);
 const blocksIn = root => [...root.querySelectorAll('[dir="auto"]')].filter(e => {
   const text = e.innerText.trim();
   if (!visible(e) || !text || metadata(text) || e.querySelector('[dir="auto"]')) return false;
   // Only exclude controls inside the candidate, not an enclosing clickable card.
   for (let p = e; p && p !== root; p = p.parentElement) {
     if (p.matches('button, [role="button"], a, [role="link"], time')) return false;
   }
   const article = e.closest('article, [role="article"]');
   return !article || article === root;
 });
 for (const link of links) {
   if (anchor && (postId(link) === options.parent_id ||
       !(anchor.compareDocumentPosition(link) & Node.DOCUMENT_POSITION_FOLLOWING))) continue;
   let root = link.closest('article, [role="article"]');
   if (!root) {
     // Use the smallest ancestor containing both a permalink and text blocks.
     for (let p = link.parentElement; p && p !== document.body; p = p.parentElement) {
       const paths = new Set([...p.querySelectorAll('a[href*="/post/"]')].map(a => new URL(a.href).pathname));
       if (paths.size > 1) break;
       if (blocksIn(p).length && p.querySelector('a[href*="/@"]')) { root = p; break; }
     }
   }
   if (!root) continue;
   // Ambiguous quotes/threads require a dedicated adapter; do not merge authors.
   if (new Set([...root.querySelectorAll('a[href*="/post/"]')].map(a => new URL(a.href).pathname)).size > 1) continue;
   const blocks = blocksIn(root);
   const text = blocks.map(e => e.innerText.trim()).filter(Boolean).join('\n');
   // Avatars in a header are not evidence of a media-only post.
   if (text || root.querySelector('video, img[alt]:not([alt=""]):not([alt*="profile"]):not([alt*="大頭"])')) rows.push({permalink: link.href, text, reply_count: replyCount(root)});
 }
 const signals = [...document.querySelectorAll('[role="status"], main h1, main h2')].filter(visible).map(e => e.innerText.trim());
 return {rows, candidates: links.length, anchor_found: !!anchor,
   diagnostics: {visible_links: allLinks.length, scoped_links: links.length,
     main: !!main, anchor: !!anchor, cards: rows.length},
   login: !![...document.querySelectorAll('input[type="password"], a[href*="/login"]')].find(visible),
   loading: !![...document.querySelectorAll('[role="progressbar"], [aria-busy="true"]')].find(visible),
   empty: signals.some(s => /^(No posts yet|No results found|尚無貼文|沒有貼文|找不到結果)[。.!！]?$/.test(s))};
}
