document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-check-all]').forEach(master => {
    master.addEventListener('change', () => {
      const target = master.dataset.checkAll;
      document.querySelectorAll(target).forEach(c => c.checked = master.checked);
    });
  });
  document.querySelectorAll('[data-copy]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const selector = btn.dataset.copy;
      const el = document.querySelector(selector);
      if (!el) return;
      const text = el.value || el.textContent || '';
      try { await navigator.clipboard.writeText(text); btn.textContent = 'Tersalin'; setTimeout(()=>btn.textContent='Copy Link',1200); }
      catch(e) { el.select?.(); document.execCommand('copy'); }
    });
  });
  const responsibility = document.querySelector('#responsibility');
  const confirmBtn = document.querySelector('#confirmShareBtn');
  if (responsibility && confirmBtn) {
    const sync = () => confirmBtn.disabled = !responsibility.checked;
    responsibility.addEventListener('change', sync); sync();
  }
  const expiry = document.querySelector('#expiry');
  const custom = document.querySelector('#customExpiryWrap');
  if (expiry && custom) {
    const sync = () => custom.style.display = expiry.value === 'custom' ? 'block' : 'none';
    expiry.addEventListener('change', sync); sync();
  }
});
