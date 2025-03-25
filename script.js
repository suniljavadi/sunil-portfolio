// Smooth scrolling for internal section links with offset adjustment
document.querySelector('nav').addEventListener('click', function (e) {
    const anchor = e.target.closest('a'); // Ensure the target is an <a> element
    if (!anchor || !anchor.getAttribute('href')) return;

    const target = anchor.getAttribute('href');

    // Handle internal links only
    if (target.startsWith('#')) {
        e.preventDefault(); // Prevent default navigation
        const section = document.querySelector(target);

        if (section) {
            const offset = 80; // Adjust if a sticky header exists
            const position = section.getBoundingClientRect().top + window.scrollY - offset;

            window.scrollTo({
                top: position,
                behavior: 'smooth'
            });
        }
    }
});
