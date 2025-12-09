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
// SCROLL ANIMATIONS - AOS ENHANCEMENT
// ============================================
// Ensure AOS works properly throughout the entire page

// Refresh AOS on scroll to catch any missed elements
let scrollTimer;
window.addEventListener('scroll', function() {
    if (scrollTimer) {
        clearTimeout(scrollTimer);
    }
    scrollTimer = setTimeout(function() {
        if (typeof AOS !== 'undefined') {
            AOS.refresh();
        }
    }, 100);
});

// Also refresh AOS on window resize
window.addEventListener('resize', function() {
    if (typeof AOS !== 'undefined') {
        AOS.refresh();
    }
});

// Force AOS refresh after page is fully loaded
window.addEventListener('load', function() {
    setTimeout(function() {
        if (typeof AOS !== 'undefined') {
            AOS.refresh();
        }
    }, 500);
});

// Special handling for affiliations section at the bottom of the page
function checkAffiliationsSection() {
    const affiliationsEl = document.querySelector('.affiliations');
    if (affiliationsEl && !affiliationsEl.classList.contains('aos-animate')) {
        const rect = affiliationsEl.getBoundingClientRect();
        const isVisible = rect.top < window.innerHeight && rect.bottom > 0;

        if (isVisible) {
            // Manually trigger the animation if AOS hasn't caught it
            affiliationsEl.classList.add('aos-animate');
            console.log('Manually triggered affiliations animation');
        }
    }
}

// Check affiliations section on scroll
window.addEventListener('scroll', function() {
    checkAffiliationsSection();
});

// Also check after initial load
setTimeout(function() {
    checkAffiliationsSection();
}, 1000);



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
// FASTER ANIMATIONS - Override AOS delays
// ============================================
// Add custom CSS to make animations faster
const fasterAnimationsCSS = `
  [data-aos] {
    transition-delay: 0ms !important;
  }

  .txt-fx .letter {
    transition-delay: 0ms !important;
  }
`;

const styleSheet = document.createElement('style');
styleSheet.textContent = fasterAnimationsCSS;
document.head.appendChild(styleSheet);

// ============================================
// CONSOLE MESSAGE
// ============================================
console.log('%c🔱 TRIDENT', 'color: #00D9FF; font-size: 24px; font-weight: bold;');
console.log('%cRealistic Cyber Range for Autonomous Agent Training', 'color: #7B2CBF; font-size: 14px;');
console.log('%cBuilt with ❤️ by Stratosphere Laboratory', 'color: #718096; font-size: 12px;');
console.log('%cGitHub: https://github.com/stratosphereips', 'color: #00D9FF; font-size: 12px;');
