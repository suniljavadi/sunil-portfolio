(() => {
  const body = document.body;
  const themeButtons = document.querySelectorAll('.theme-toggle');
  const menuButton = document.querySelector('.menu-toggle');
  const navigation = document.querySelector('.site-nav');
  const savedTheme = localStorage.getItem('portfolio-theme');

  const setTheme = (theme) => {
    body.classList.toggle('dark-mode', theme === 'dark');
    themeButtons.forEach((button) => {
      button.textContent = theme === 'dark' ? 'Light' : 'Dark';
      button.setAttribute('aria-label', theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
    });
  };

  setTheme(savedTheme || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));

  themeButtons.forEach((button) => {
    button.addEventListener('click', () => {
      const nextTheme = body.classList.contains('dark-mode') ? 'light' : 'dark';
      localStorage.setItem('portfolio-theme', nextTheme);
      setTheme(nextTheme);
    });
  });

  if (menuButton && navigation) {
    menuButton.addEventListener('click', () => {
      const isOpen = navigation.classList.toggle('is-open');
      menuButton.setAttribute('aria-expanded', String(isOpen));
      menuButton.textContent = isOpen ? 'Close' : 'Menu';
    });
  }

  const currentPage = window.location.pathname.split('/').pop() || 'index.html';
  document.querySelectorAll('.site-nav a').forEach((link) => {
    if (link.getAttribute('href') === currentPage) {
      link.classList.add('active');
      link.setAttribute('aria-current', 'page');
    }
  });
})();
