// static/bg-boomerang.js
(function () {
  function safePlay(v) {
    if (!v) return;
    v.muted = true;
    v.defaultMuted = true;
    v.playsInline = true;

    const p = v.play();
    if (p && typeof p.catch === "function") p.catch(() => {});
  }

  function setSrc(v, src) {
    if (!v) return;
    if (v.src !== src) v.src = src;
    v.load();
  }

  /**
   * Crossfade boomerang background.
   * Usage:
   *   setupBoomerangBackground("bgVideoA", "bgVideoB");
   *
   * Each <video> must have:
   *   data-forward="/static/intro-bg.mp4"
   *   data-reverse="/static/intro-bg-rev.mp4"
   */
  function setupBoomerangBackground(videoAId, videoBId) {
    const a = document.getElementById(videoAId);
    if (!a) return;

    const b = videoBId ? document.getElementById(videoBId) : null;

    const forwardBase = a.dataset.forward || (b && b.dataset.forward);
    const reverseBase = a.dataset.reverse || (b && b.dataset.reverse);

    if (!forwardBase || !reverseBase) {
      console.warn("[boomerang] Missing data-forward or data-reverse on <video>.");
      return;
    }

    // Small time offset avoids some “black first frame” issues
    const forwardSrc = forwardBase + "#t=0.001";
    const reverseSrc = reverseBase + "#t=0.001";

    const reduceMotion =
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // ----------------------------
    // SINGLE VIDEO fallback (no crossfade)
    // ----------------------------
    if (!b) {
      let forward = true;

      a.loop = false;
      setSrc(a, forwardSrc);

      if (reduceMotion) {
        a.loop = true;
        safePlay(a);
        return;
      }

      a.addEventListener("ended", () => {
        forward = !forward;
        setSrc(a, forward ? forwardSrc : reverseSrc);
        safePlay(a);
      });

      a.addEventListener("canplay", () => safePlay(a));
      document.addEventListener("click", () => safePlay(a), { once: true });

      safePlay(a);
      return;
    }

    // ----------------------------
    // CROSSFADING TWO-VIDEO MODE
    // ----------------------------
    const FADE_MS = 520;

    [a, b].forEach((v) => {
      v.muted = true;
      v.defaultMuted = true;
      v.playsInline = true;
      v.loop = false;
      v.preload = "auto";
    });

    // Reduced motion: just loop forward on A
    if (reduceMotion) {
      setSrc(a, forwardSrc);
      a.loop = true;
      a.classList.add("is-active");
      b.classList.remove("is-active");
      safePlay(a);
      return;
    }

    let current = a;
    let next = b;
    let currentDir = "forward"; // what CURRENT is playing right now

    function srcFor(dir) {
      return dir === "forward" ? forwardSrc : reverseSrc;
    }

    function loadDir(v, dir) {
      v.dataset.dir = dir;
      setSrc(v, srcFor(dir));
    }

    function activate(v) {
      v.classList.add("is-active");
    }

    function deactivate(v) {
      v.classList.remove("is-active");
    }

    // Prime both directions
    loadDir(current, "forward");
    loadDir(next, "reverse");

    activate(current);
    deactivate(next);

    // Keep the hidden one paused until needed
    try { next.pause(); } catch {}

    // Autoplay reliability
    safePlay(current);
    current.addEventListener("canplay", () => safePlay(current));
    next.addEventListener("canplay", () => safePlay(current));
    document.addEventListener("click", () => safePlay(current), { once: true });

    function swapToNext() {
      const nextDir = currentDir === "forward" ? "reverse" : "forward";

      // Ensure NEXT has correct direction loaded
      if (next.dataset.dir !== nextDir) {
        loadDir(next, nextDir);
      }

      // Restart next from the beginning
      try { next.currentTime = 0; } catch {}

      // Start next and crossfade
      safePlay(next);
      activate(next);
      deactivate(current);

      // After fade: pause old, swap refs, preload upcoming opposite into hidden
      setTimeout(() => {
        try { current.pause(); } catch {}

        const old = current;
        current = next;
        next = old;

        currentDir = nextDir;

        const upcoming = currentDir === "forward" ? "reverse" : "forward";
        loadDir(next, upcoming);
        try { next.pause(); } catch {}
      }, FADE_MS + 40);
    }

    function onEnded(e) {
      if (e.target !== current) return;
      swapToNext();
    }

    a.addEventListener("ended", onEnded);
    b.addEventListener("ended", onEnded);
  }

  window.setupBoomerangBackground = setupBoomerangBackground;
})();
