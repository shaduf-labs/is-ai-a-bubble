(() => {
  let observer, network, visible = true;
  function sync() {
    const paused = document.hidden || !visible || matchMedia('(prefers-reduced-motion: reduce)').matches;
    network?.classList.toggle('is-paused', paused);
    if (network) paused ? network.pauseAnimations() : network.unpauseAnimations();
  }
  function mount() {
    observer?.disconnect();
    network = document.querySelector('[data-shaduf-network]');
    if (!network) return;
    visible = true;
    observer = new IntersectionObserver(entries => {
      visible = entries[0].isIntersecting;
      sync();
    });
    observer.observe(network);
    sync();
  }
  document.addEventListener('visibilitychange', sync);
  matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', sync);
  window.ShadufNetwork = {mount};
  mount();
})();
