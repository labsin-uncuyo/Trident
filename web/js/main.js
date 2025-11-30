// ============================================
// SMOOTH SCROLLING
// ============================================
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        const href = this.getAttribute('href');

        // Skip if href is just "#"
        if (href === '#') return;

        e.preventDefault();

        const target = document.querySelector(href);
        if (target) {
            const navbar = document.querySelector('#navbar') || document.querySelector('.navbar');
        const navHeight = navbar ? navbar.offsetHeight : 0;
            const targetPosition = target.offsetTop - navHeight;

            window.scrollTo({
                top: targetPosition,
                behavior: 'smooth'
            });

            // Close mobile menu if open
            const navLinks = document.querySelector('.nav-links');
            if (navLinks.classList.contains('active')) {
                navLinks.classList.remove('active');
                menuBtn.setAttribute('aria-expanded', 'false');
            }
        }
    });
});

// ============================================
// MOBILE MENU TOGGLE
// ============================================
const menuBtn = document.querySelector('.menu-toggle');
const nav = document.querySelector('.nav-links');

if (menuBtn && nav) {
    menuBtn.addEventListener('click', () => {
        nav.classList.toggle('active');
        const isExpanded = nav.classList.contains('active');
        menuBtn.setAttribute('aria-expanded', isExpanded);

        // Prevent body scroll when menu is open
        if (isExpanded) {
            document.body.style.overflow = 'hidden';
        } else {
            document.body.style.overflow = '';
        }
    });
}

// Close menu when clicking outside
document.addEventListener('click', (e) => {
    if (nav && nav.classList.contains('active')) {
        if (!nav.contains(e.target) && !menuBtn.contains(e.target)) {
            nav.classList.remove('active');
            menuBtn.setAttribute('aria-expanded', 'false');
            document.body.style.overflow = '';
        }
    }
});

// Close menu on escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && nav && nav.classList.contains('active')) {
        nav.classList.remove('active');
        menuBtn.setAttribute('aria-expanded', 'false');
        document.body.style.overflow = '';
    }
});

// ============================================
// SCROLL ANIMATIONS
// ============================================
const observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -100px 0px'
};

const fadeInObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.style.opacity = '1';
            entry.target.style.transform = 'translateY(0)';
        }
    });
}, observerOptions);

// Apply fade-in animation to sections
document.querySelectorAll('.section').forEach(section => {
    section.style.opacity = '0';
    section.style.transform = 'translateY(30px)';
    section.style.transition = 'opacity 0.6s ease-out, transform 0.6s ease-out';
    fadeInObserver.observe(section);
});

// ============================================
// NAVBAR BACKGROUND ON SCROLL
// ============================================
const navbar = document.querySelector('#navbar') || document.querySelector('.navbar');
let lastScroll = 0;

window.addEventListener('scroll', () => {
    const currentScroll = window.pageYOffset;

    // Add solid background when scrolled
    if (currentScroll > 100) {
        navbar.style.backgroundColor = 'rgba(10, 14, 39, 1)';
    } else {
        navbar.style.backgroundColor = 'rgba(10, 14, 39, 0.95)';
    }

    lastScroll = currentScroll;
});

// ============================================
// ACTIVE NAV LINK HIGHLIGHTING
// ============================================
const sections = document.querySelectorAll('section[id]');
const navLinks = document.querySelectorAll('.nav-links a[href^="#"]');

function highlightNavLink() {
    const scrollPosition = window.pageYOffset + 100;

    sections.forEach(section => {
        const sectionTop = section.offsetTop;
        const sectionHeight = section.offsetHeight;
        const sectionId = section.getAttribute('id');

        if (scrollPosition >= sectionTop && scrollPosition < sectionTop + sectionHeight) {
            navLinks.forEach(link => {
                link.classList.remove('active');
                if (link.getAttribute('href') === `#${sectionId}`) {
                    link.classList.add('active');
                }
            });
        }
    });
}

window.addEventListener('scroll', highlightNavLink);
window.addEventListener('load', highlightNavLink);

// ============================================
// PERFORMANCE: LAZY LOAD IMAGES
// ============================================
if ('loading' in HTMLImageElement.prototype) {
    // Browser supports lazy loading natively
    const images = document.querySelectorAll('img[loading="lazy"]');
    images.forEach(img => {
        img.src = img.dataset.src || img.src;
    });
} else {
    // Fallback for browsers that don't support lazy loading
    const imageObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const img = entry.target;
                img.src = img.dataset.src || img.src;
                imageObserver.unobserve(img);
            }
        });
    });

    document.querySelectorAll('img').forEach(img => {
        imageObserver.observe(img);
    });
}

// ============================================
// ACCESSIBILITY: FOCUS TRAP FOR MOBILE MENU
// ============================================
function trapFocus(element) {
    const focusableElements = element.querySelectorAll(
        'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled])'
    );
    const firstFocusable = focusableElements[0];
    const lastFocusable = focusableElements[focusableElements.length - 1];

    element.addEventListener('keydown', (e) => {
        if (e.key !== 'Tab') return;

        if (e.shiftKey) {
            if (document.activeElement === firstFocusable) {
                lastFocusable.focus();
                e.preventDefault();
            }
        } else {
            if (document.activeElement === lastFocusable) {
                firstFocusable.focus();
                e.preventDefault();
            }
        }
    });
}

if (nav) {
    trapFocus(nav);
}

// ============================================
// CONSOLE MESSAGE
// ============================================
console.log('%c🔱 TRIDENT', 'color: #00D9FF; font-size: 24px; font-weight: bold;');
console.log('%cRealistic Cyber Range for Autonomous Agent Training', 'color: #7B2CBF; font-size: 14px;');
console.log('%cBuilt with ❤️ by Stratosphere Laboratory', 'color: #718096; font-size: 12px;');
console.log('%cGitHub: https://github.com/stratosphereips', 'color: #00D9FF; font-size: 12px;');
