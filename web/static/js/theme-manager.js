/**
 * Dark Mode functionality for Twitch Drops Miner
 */

class ThemeManager {
    constructor() {
        this.darkModeKey = 'tdm-dark-mode';
        this.init();
    }    init() {
        // Apply theme from localStorage
        this.applyTheme();
        
        // Add event listener for theme toggle checkbox
        const themeToggleCheckbox = document.getElementById('theme-toggle-checkbox');
        if (themeToggleCheckbox) {
            // Set initial state based on current theme
            themeToggleCheckbox.checked = this.isDarkMode();
            
            // Add event listener for changes
            themeToggleCheckbox.addEventListener('change', () => {
                this.toggleTheme();
            });
        }
        
        // Add system theme preference media query listener
        this.setupSystemThemeDetection();
    }

    isDarkMode() {
        return localStorage.getItem(this.darkModeKey) === 'true';
    }

    toggleTheme() {
        const currentMode = this.isDarkMode();
        localStorage.setItem(this.darkModeKey, (!currentMode).toString());
        this.applyTheme();
    }    applyTheme() {
        const isDarkMode = this.isDarkMode();
        document.body.classList.toggle('dark-mode', isDarkMode);
        
        // Update checkbox if it exists
        const themeToggleCheckbox = document.getElementById('theme-toggle-checkbox');
        if (themeToggleCheckbox) {
            themeToggleCheckbox.checked = isDarkMode;
            
            // Update tooltip text
            const themeToggleWrapper = document.querySelector('.theme-switch-wrapper');
            if (themeToggleWrapper) {
                themeToggleWrapper.setAttribute('data-tooltip', isDarkMode ? 'Switch to light mode' : 'Switch to dark mode');
            }
        }
        
        // Update the status info on the System Status card
        this.updateStatusDisplay();
    }
      setupSystemThemeDetection() {
        // If user hasn't explicitly set a preference, follow system theme
        if (localStorage.getItem(this.darkModeKey) === null) {
            const prefersDarkScheme = window.matchMedia('(prefers-color-scheme: dark)');
            
            // Set initial theme based on system preference
            localStorage.setItem(this.darkModeKey, prefersDarkScheme.matches.toString());
            this.applyTheme();
            
            // Listen for changes to system theme
            prefersDarkScheme.addEventListener('change', (e) => {
                // Only auto-switch if user hasn't manually set a preference
                if (localStorage.getItem(this.darkModeKey) === null) {
                    localStorage.setItem(this.darkModeKey, e.matches.toString());
                    this.applyTheme();
                }
            });
        }
    }
    
    updateStatusDisplay() {
        // Update the status information in the System Status card
        const isDarkMode = this.isDarkMode();
        
        // Update connection status
        const connectionStatus = document.getElementById('connection-status');
        if (connectionStatus) {
            const statusIndicator = connectionStatus.querySelector('.rounded-full');
            if (statusIndicator) {
                // Don't change the actual status color, just adapt to dark mode if needed
                if (isDarkMode) {
                    statusIndicator.classList.add('shadow-glow');
                } else {
                    statusIndicator.classList.remove('shadow-glow');
                }
            }
            
            // Update text colors for dark mode
            const textElements = connectionStatus.querySelectorAll('span:not(.rounded-full)');
            textElements.forEach(el => {
                el.classList.toggle('text-gray-300', isDarkMode);
                el.classList.toggle('text-gray-700', !isDarkMode);
            });
        }
        
        // Update last refresh time
        const lastRefreshTime = document.getElementById('last-refresh-time');
        if (lastRefreshTime) {
            const textElements = lastRefreshTime.querySelectorAll('span');
            textElements.forEach(el => {
                el.classList.toggle('text-gray-300', isDarkMode);
                el.classList.toggle('text-gray-700', !isDarkMode);
            });
        }
        
        // Update websocket status
        const websocketStatus = document.getElementById('websocket-status-indicator');
        if (websocketStatus) {
            websocketStatus.classList.toggle('text-gray-300', isDarkMode);
            websocketStatus.classList.toggle('text-gray-700', !isDarkMode);
        }
    }
}

// Initialize the theme manager when the DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.themeManager = new ThemeManager();
});
