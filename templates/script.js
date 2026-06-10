// WAKIM WEALTH — script.js

document.addEventListener('DOMContentLoaded', () => {

  // Nav scroll
  const nav = document.getElementById('nav');
  window.addEventListener('scroll', () => {
    nav.classList.toggle('scrolled', window.scrollY > 40);
  });

  // Hamburger / mobile menu (only wires up if both elements are present)
  const hamburger = document.getElementById('hamburger');
  const mobileMenu = document.getElementById('mobileMenu');

  if (hamburger && mobileMenu) {
    hamburger.addEventListener('click', () => mobileMenu.classList.toggle('open'));

    document.querySelectorAll('.mobile-link').forEach(l =>
      l.addEventListener('click', () => mobileMenu.classList.remove('open'))
    );

    document.addEventListener('click', (e) => {
      if (!mobileMenu.contains(e.target) && !hamburger.contains(e.target))
        mobileMenu.classList.remove('open');
    });
  }

  // Reveal on scroll
  const reveals = document.querySelectorAll('.reveal');
  const ro = new IntersectionObserver((entries) => {
    entries.forEach(e => {
      if (e.isIntersecting) { e.target.classList.add('visible'); ro.unobserve(e.target); }
    });
  }, { threshold: 0.12 });

  reveals.forEach(el => ro.observe(el));

  // Trigger hero immediately
  setTimeout(() => {
    document.querySelectorAll('.hero .reveal').forEach(el => el.classList.add('visible'));
  }, 80);

  // Stat counter
  const statNums = document.querySelectorAll('.stat-num');
  const co = new IntersectionObserver((entries) => {
    entries.forEach(e => { if (e.isIntersecting) { animateCount(e.target); co.unobserve(e.target); } });
  }, { threshold: 0.5 });
  statNums.forEach(el => co.observe(el));

  function animateCount(el) {
    const original = el.textContent;
    const match = original.match(/[\d.]+/);
    if (!match) return;
    const target = parseFloat(match[0]);
    const prefix = original.includes('$') ? '$' : '';
    const suffix = original.replace(/[$\d.]/g, '');
    let start = null;
    const duration = 1200;
    const step = (timestamp) => {
      if (!start) start = timestamp;
      const progress = Math.min((timestamp - start) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const val = Math.round(target * eased);
      el.textContent = `${prefix}${val}${suffix}`;
      if (progress < 1) requestAnimationFrame(step);
      else el.textContent = original;
    };
    requestAnimationFrame(step);
  }

  // Form submit
  const submitBtn = document.getElementById('submitBtn');
  if (submitBtn) {
    submitBtn.addEventListener('click', () => {
      const inputs = document.querySelectorAll('.contact-form input, .contact-form select');
      let valid = true;
      inputs.forEach(input => {
        if (!input.value.trim()) {
          valid = false;
          input.style.borderColor = '#c0392b';
          setTimeout(() => { input.style.borderColor = ''; }, 2000);
        }
      });
      if (valid) {
        submitBtn.textContent = 'Request Received — We\'ll Be in Touch Soon';
        submitBtn.style.background = '#1a5c2a';
        submitBtn.disabled = true;
      }
    });
  }

});
