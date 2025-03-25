document.querySelectorAll('nav ul li a').forEach(anchor => {
    anchor.addEventListener('click', function(e) {
        const target = this.getAttribute('href');

        // If it's an internal section (e.g., #welcome)
        if (target.startsWith('#')) {
            e.preventDefault();  // Prevent default only for internal links
            document.querySelector(target).scrollIntoView({
                behavior: 'smooth'
            });
        }
        // If it's an external page (e.g., about.html), let the browser navigate normally
    });
});
