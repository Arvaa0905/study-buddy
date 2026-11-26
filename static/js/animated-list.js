export function enhanceAnimatedList(track, options = {}) {
  if (!track) return;
  const items = [...track.querySelectorAll(options.itemSelector || '.note-list-item, .note-row, .score-row')];
  if (!items.length) return;

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const stagger = options.stagger ?? 0.045;
  track.classList.add('animated-list-track');
  if (!reduced) track.dataset.alAnimated = '';

  const indicator = document.createElement('span');
  indicator.className = 'animated-list__indicator';
  indicator.setAttribute('aria-hidden', 'true');
  const ring = document.createElement('span');
  ring.className = 'animated-list__ring';
  indicator.append(ring);
  track.append(indicator);

  const motion = { y: 0, h: 0, vy: 0, vh: 0, ty: 0, th: 0, ready: false };
  let selected = -1;
  let raf = 0;
  let last = 0;

  const write = () => {
    indicator.style.transform = `translate3d(0, ${motion.y.toFixed(2)}px, 0)`;
    indicator.style.height = `${motion.h.toFixed(2)}px`;
  };

  const frame = now => {
    raf = 0;
    const dt = Math.min(0.05, (now - last) / 1000 || 0);
    last = now;
    const omega = 30;
    const zeta = 0.78;
    const steps = Math.max(1, Math.ceil(dt / (1 / 240)));
    const h = dt / steps;
    for (let i = 0; i < steps; i++) {
      motion.vy += (omega * omega * (motion.ty - motion.y) - 2 * zeta * omega * motion.vy) * h;
      motion.vh += (omega * omega * (motion.th - motion.h) - 2 * zeta * omega * motion.vh) * h;
      motion.y += motion.vy * h;
      motion.h += motion.vh * h;
    }
    const moving =
      Math.abs(motion.ty - motion.y) > 0.05 ||
      Math.abs(motion.th - motion.h) > 0.05 ||
      Math.abs(motion.vy) + Math.abs(motion.vh) > 0.5;
    if (!moving) {
      motion.y = motion.ty; motion.h = motion.th; motion.vy = motion.vh = 0;
    }
    write();
    if (moving) raf = requestAnimationFrame(frame);
  };

  const place = (index, snap = false) => {
    const item = items[index];
    if (!item) {
      indicator.style.opacity = '0';
      return;
    }
    indicator.style.opacity = '1';
    motion.ty = item.offsetTop;
    motion.th = item.offsetHeight;
    if (snap || reduced || !motion.ready) {
      motion.y = motion.ty; motion.h = motion.th; motion.vy = motion.vh = 0;
      motion.ready = true;
      write();
      return;
    }
    if (!raf) {
      last = performance.now();
      raf = requestAnimationFrame(frame);
    }
  };

  items.forEach((item, index) => {
    item.classList.add('animated-list-item');
    if (!reduced) {
      item.dataset.alState = 'hidden';
      item.style.transitionDelay = `${(index * stagger).toFixed(3)}s, ${(index * stagger).toFixed(3)}s, 0s`;
    } else {
      item.dataset.alState = 'in';
    }
    item.addEventListener('pointerenter', () => {
      selected = index;
      place(index);
    });
    item.addEventListener('focus', () => {
      selected = index;
      place(index);
    });
  });

  track.addEventListener('pointerleave', () => {
    if (selected >= 0 && document.activeElement !== items[selected]) {
      indicator.style.opacity = '0';
    }
  });

  if (!reduced) {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        items.forEach(item => { item.dataset.alState = 'in'; });
      });
    });
  }
}

