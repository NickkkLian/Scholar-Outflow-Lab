/* Theme preferences migrate the previous light/dark choice. */
window.Appearance = (() => {
  const root = document.documentElement;
  function bindToggle(button) {
    const sync = () => {
      const dark = root.dataset.theme === 'dark';
      button.setAttribute('aria-pressed', String(dark));
      button.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
      button.title = button.getAttribute('aria-label');
    };
    sync();
    button.addEventListener('click', () => {
      root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem('r3-theme', root.dataset.theme); } catch {}
      sync();
    });
  }
  function shortcutsOn() { try { return localStorage.getItem('nl-shortcuts') !== 'off'; } catch { return true; } }
  return { bindToggle, shortcutsOn };
})();
