# Trident - Realistic Cyber Range for Autonomous Agent Training

A simple, clean website for the Trident research project - a lightweight framework to train and test cyber agents (benign, attacker, defender) in real-like Docker environments.

## 🚀 Quick Start

This is a static website built with pure HTML, CSS, and JavaScript. No build tools or dependencies required!

### Local Development

1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-username/trident-webpage.git
   cd trident-webpage
   ```

2. **Open in browser:**
   Simply open `index.html` in your web browser:
   ```bash
   # On macOS
   open index.html

   # On Linux
   xdg-open index.html

   # On Windows
   start index.html
   ```

   Or use a local server (recommended):
   ```bash
   # Python 3
   python -m http.server 8000

   # Python 2
   python -m SimpleHTTPServer 8000

   # Node.js (with npx)
   npx serve

   # PHP
   php -S localhost:8000
   ```

   Then visit `http://localhost:8000`

## 📁 Project Structure

```
trident-webpage/
├── index.html              # Main HTML file
├── css/
│   └── styles.css         # All styles
├── js/
│   └── main.js            # JavaScript functionality
├── assets/
│   └── images/
│       ├── logo.svg       # Trident logo
│       └── architecture.svg  # System architecture diagram
├── docs/
│   └── dockerized-netsecgame.pdf  # Project documentation
└── README.md              # This file
```

## 🌐 Deployment

### GitHub Pages (Recommended)

1. **Push to GitHub:**
   ```bash
   git init
   git add .
   git commit -m "Initial commit: Trident webpage"
   git branch -M main
   git remote add origin https://github.com/your-username/trident-webpage.git
   git push -u origin main
   ```

2. **Enable GitHub Pages:**
   - Go to your repository settings
   - Navigate to "Pages" section
   - Under "Source", select `main` branch and `/ (root)` folder
   - Click "Save"
   - Your site will be live at: `https://your-username.github.io/trident-webpage/`

3. **Optional: Custom Domain:**
   - Add a `CNAME` file with your domain name
   - Configure DNS settings with your domain provider
   - Enable HTTPS in GitHub Pages settings

### Netlify

1. **Connect repository:**
   - Log in to [Netlify](https://www.netlify.com)
   - Click "New site from Git"
   - Connect your GitHub account
   - Select the `trident-webpage` repository

2. **Configure build settings:**
   - Build command: (leave empty)
   - Publish directory: `/`
   - Click "Deploy site"

3. **Your site is live!**
   - Access at: `https://random-name.netlify.app`
   - Customize the domain in Netlify settings

### Vercel

1. **Deploy:**
   ```bash
   npx vercel
   ```

2. **Follow the prompts:**
   - Link to existing project or create new
   - Confirm settings
   - Deploy!

## ✨ Features

- **Clean, Modern Design:** Professional cybersecurity-themed design
- **Fully Responsive:** Works on mobile, tablet, and desktop
- **Accessible:** WCAG 2.1 AA compliant
- **Fast Loading:** Optimized for performance (< 1MB total)
- **No Build Tools:** Pure HTML/CSS/JavaScript
- **SEO Optimized:** Meta tags, structured data, semantic HTML

## 🎨 Customization

### Colors

Edit CSS variables in `css/styles.css`:

```css
:root {
    --color-dark: #0A0E27;
    --color-primary: #00D9FF;
    --color-secondary: #7B2CBF;
    --color-success: #39FF14;
    /* ... more colors */
}
```

### Content

Edit `index.html` directly. All content is in semantic HTML sections:
- Hero section: Line ~80
- About section: Line ~120
- Architecture section: Line ~220
- Tasks section: Line ~280
- And so on...

### Adding Images

Place images in `assets/images/` and reference them:
```html
<img src="assets/images/your-image.jpg" alt="Description">
```

## 🔧 Technologies Used

- **HTML5:** Semantic markup
- **CSS3:** Modern styling with flexbox and grid
- **JavaScript (ES6+):** Smooth scrolling, mobile menu
- **Font Awesome 6:** Icons
- **Google Fonts:** Inter and Fira Code

## 📱 Browser Support

- Chrome (latest)
- Firefox (latest)
- Safari (latest)
- Edge (latest)
- Mobile browsers (iOS Safari, Chrome Android)

## ♿ Accessibility

- Keyboard navigation support
- Screen reader friendly
- ARIA labels and landmarks
- Color contrast WCAG AA compliant
- Focus visible indicators
- Skip navigation link

## 🚧 Future Enhancements

- [ ] Add GitHub repository links when available
- [ ] Add team member photos
- [ ] Interactive architecture diagram
- [ ] Blog/news section for updates
- [ ] Publication list
- [ ] Dark/light mode toggle
- [ ] Multilingual support (Spanish, Czech)

## 📄 License

This project is open source. Built with support from [NLnet Foundation](https://nlnet.nl).

## 🤝 Contributing

This is a research project website. For inquiries about collaboration or contributions:
- Visit [Stratosphere Laboratory](https://www.stratosphereips.org)
- Contact [Czech Technical University](https://www.cvut.cz/en)

## 📞 Contact

For questions or feedback:
- **Stratosphere Laboratory:** https://www.stratosphereips.org/contact
- **Project Documentation:** [docs/dockerized-netsecgame.pdf](docs/dockerized-netsecgame.pdf)

## 🙏 Acknowledgments

- **Stratosphere Laboratory** at Czech Technical University (CTU)
- **NLnet Foundation** for funding support
- All contributors and collaborators

---

Built with ❤️ by the Trident team | © 2025
