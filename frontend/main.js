import '../app/static/styles/site.css';

function initialiseNavigation(header) {
  const button = header.querySelector('.menu-toggle');
  const navigation = header.querySelector('.primary-nav');
  if (!button || !navigation || button.dataset.navigationReady === 'true') {
    return;
  }

  const close = () => {
    navigation.classList.remove('is-open');
    button.setAttribute('aria-expanded', 'false');
  };

  button.dataset.navigationReady = 'true';
  button.addEventListener('click', () => {
    const isOpen = navigation.classList.toggle('is-open');
    button.setAttribute('aria-expanded', String(isOpen));
  });
  navigation.addEventListener('click', (event) => {
    if (event.target.closest('a')) {
      close();
    }
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      close();
    }
  });
}

function initialisePage() {
  document.querySelectorAll('.site-header').forEach(initialiseNavigation);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initialisePage, { once: true });
} else {
  initialisePage();
}
