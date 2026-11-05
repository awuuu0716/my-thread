/* Scroll the nearest scrollable ancestor of the first visible post link by ~one
 * viewport (or back to the top when reset=true). Returns whether it moved.
 * Evaluated by Playwright as page.evaluate(SCROLL, reset); keep it a single function. */
(reset = false) => {
 const links = [...document.querySelectorAll('a[href*="/post/"]')];
 const link = links.find(e => { const r = e.getBoundingClientRect();
   return r.width && r.height && r.bottom > 0 && r.top < innerHeight; }) || links[0];
 let target = document.scrollingElement;
 for (let p = link?.parentElement; p && p !== document.body; p = p.parentElement) {
   if (/(auto|scroll)/.test(getComputedStyle(p).overflowY) && p.scrollHeight > p.clientHeight + 2) {
     target = p; break;
   }
 }
 if (!target) return false;
 const before = target.scrollTop;
 target.scrollBy({top: reset ? -target.scrollHeight : Math.max(200, target.clientHeight * .8), behavior: 'instant'});
 return target.scrollTop > before;
}
