/**
 * WD Wireless Tools — shared navigation, theme, and topbar code.
 * Included by all tool pages to avoid duplicating menu logic.
 * v1.0
 */

/* ── Theme ── */
function wdToggleTheme() {
  const cur = document.documentElement.getAttribute('data-theme') || 'dark';
  const next = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  try { localStorage.setItem('wd-theme', next); } catch (e) {}
  wdSyncThemeIcons();
}

function wdSyncThemeIcons() {
  const dark = (document.documentElement.getAttribute('data-theme') || 'dark') === 'dark';
  document.querySelectorAll('.wd-theme-btn').forEach(b => { b.textContent = dark ? '🌙' : '☀️'; });
}

/* ── Hamburger menu toggle (works for any menu pair) ── */
function wdToggleMenu(btnOrEvent, menuId) {
  const e = btnOrEvent instanceof Event ? btnOrEvent : null;
  if (e) e.stopPropagation();
  const menu = document.getElementById(menuId);
  if (!menu) return;
  const wasOpen = menu.classList.contains('open');
  // Close all WD menus first
  document.querySelectorAll('.wd-menu').forEach(m => m.classList.remove('open'));
  if (!wasOpen) {
    menu.classList.add('open');
    setTimeout(() => {
      document.addEventListener('click', function handler() {
        menu.classList.remove('open');
        document.removeEventListener('click', handler);
      }, { once: true });
    }, 0);
  }
}

/* ── Shared topbar CSS (injected once) ── */
(function injectNavStyles() {
  if (document.getElementById('wd-nav-styles')) return;
  const style = document.createElement('style');
  style.id = 'wd-nav-styles';
  style.textContent = `
    /* WD shared topbar */
    .wd-topbar { background: #0e1b26; color: white; padding: 8px 16px; display: flex; align-items: center; flex-shrink: 0; }
    .wd-topbar-left { display: flex; align-items: center; gap: 10px; }
    .wd-topbar-center { flex: 1; display: flex; justify-content: center; align-items: center; gap: 12px; }
    .wd-topbar-right { display: flex; align-items: center; gap: 10px; }
    .wd-topbar h1 { font-size: 16px; font-weight: 600; color: white; margin: 0; }
    .wd-topbar h1 .wd-brand { color: #6bb3e0; }
    .wd-topbar h1 .wd-ver { color: #9aa0a6; font-weight: 400; font-size: 11px; margin-left: 3px; }
    .wd-topbar .wd-dot { width: 6px; height: 6px; border-radius: 50%; background: #34d399; display: inline-block; }
    .wd-topbar .wd-email { font-size: 11px; color: #9aa0a6; }
    /* Hamburger button */
    .wd-hamburger { display: flex; flex-direction: column; justify-content: center; gap: 3px; width: 28px; height: 22px; background: none; border: 1px solid rgba(255,255,255,0.18); border-radius: 4px; cursor: pointer; padding: 0 6px; }
    .wd-hamburger span { display: block; height: 2px; background: #cbd5e1; border-radius: 1px; }
    .wd-hamburger:hover { background: rgba(255,255,255,0.10); }
    /* Theme / action buttons in topbar */
    .wd-theme-btn, .wd-topbar-btn { background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.18); color: #cbd5e1; padding: 5px 12px; border-radius: 4px; font-size: 12px; font-weight: 500; cursor: pointer; transition: background 0.1s; }
    .wd-theme-btn:hover, .wd-topbar-btn:hover { background: rgba(255,255,255,0.15); color: #fff; }
    /* Drop-down menu */
    .wd-menu { position: absolute; top: 100%; left: 0; margin-top: 6px; background: var(--surface, #18212c); border: 1px solid var(--border, #273240); border-radius: 8px; box-shadow: 0 12px 36px rgba(0,0,0,0.45); min-width: 230px; padding: 8px 0; z-index: 300; display: none; }
    .wd-menu.open { display: block; }
    .wd-menu .wd-menu-section { padding: 10px 16px 4px; font-size: 10px; font-weight: 700; letter-spacing: 1.2px; text-transform: uppercase; color: var(--text-3, #6b7684); }
    .wd-menu .wd-menu-section:first-child { padding-top: 6px; }
    .wd-menu .wd-menu-item { display: block; width: 100%; text-align: left; background: none; border: none; color: var(--text-2, #9aa5b1); font-size: 13px; padding: 7px 16px 7px 20px; cursor: pointer; text-decoration: none; box-sizing: border-box; transition: color 0.1s; }
    .wd-menu .wd-menu-item:hover { color: var(--text, #e7ebf0); background: rgba(30,119,172,0.08); }
    .wd-menu .wd-menu-item.active { color: var(--blue, #1e77ac); font-weight: 600; }
    .wd-menu .wd-menu-sep { height: 1px; background: var(--border, #273240); margin: 6px 12px; }
  `;
  document.head.appendChild(style);
})();

/* ── Init on load ── */
document.addEventListener('DOMContentLoaded', wdSyncThemeIcons);
