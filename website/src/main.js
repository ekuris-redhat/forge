// Forge Marketing Website JavaScript Entrypoint
document.addEventListener('DOMContentLoaded', () => {
  console.log('Forge Marketing Website initialized successfully!');

  // Setup smooth scrolling for navigation links
  const links = document.querySelectorAll('.nav-link, .hero-actions a, .footer-link');
  links.forEach(link => {
    link.addEventListener('click', (e) => {
      const href = link.getAttribute('href');
      if (href && href.startsWith('#') && href.length > 1) {
        e.preventDefault();
        const targetElement = document.querySelector(href);
        if (targetElement) {
          targetElement.scrollIntoView({
            behavior: 'smooth',
            block: 'start'
          });
        }
      }
    });
  });
});
