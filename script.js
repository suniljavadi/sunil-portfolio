// Smooth scrolling for internal section links
document.querySelectorAll('nav ul li a').forEach(anchor => {
    anchor.addEventListener('click', function(e) {
        const target = this.getAttribute('href');

        // If the target is an internal section (e.g., #welcome)
        if (target.startsWith('#')) {
            e.preventDefault();  // Prevent default only for internal links
            const section = document.querySelector(target);
            if (section) {
                section.scrollIntoView({
                    behavior: 'smooth'
                });
            }
        }
        // If it's an external link (e.g., about.html), do nothing (allow normal navigation)
    });
});
