/**
 * Authentication utilities for Twitch Drops Miner web interface
 */

/**
 * Check if the user is authenticated
 * @returns {boolean} True if authenticated, false otherwise
 */
function isAuthenticated() {
    return !!localStorage.getItem('auth_token');
}

/**
 * Get the authentication token
 * @returns {string|null} The authentication token or null if not authenticated
 */
function getAuthToken() {
    return localStorage.getItem('auth_token');
}

/**
 * Check if the authentication token is valid
 * @returns {Promise<boolean>} Promise that resolves to true if valid, false otherwise
 */
async function validateAuthToken() {
    if (!isAuthenticated()) return false;

    try {
        const response = await fetch('/api/auth/validate', {
            headers: {
                'Authorization': `Bearer ${getAuthToken()}`
            }
        });

        return response.ok;
    } catch (error) {
        console.error('Error validating auth token:', error);
        return false;
    }
}

/**
 * Perform logout
 * @returns {Promise<void>} Promise that resolves when logout is complete
 */
async function logout() {
    try {
        await fetch('/api/auth/logout', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${getAuthToken()}`
            }
        });
    } catch (error) {
        console.error('Error logging out:', error);
    }

    // Clear local storage regardless of API response
    localStorage.removeItem('auth_token');
    localStorage.removeItem('username');

    // Redirect to login page
    window.location.href = '/login';
}

/**
 * Initialize authentication
 * This function should be called on every page load
 */
function initAuth() {
    // If we're on the login page, skip validation
    if (window.location.pathname === '/login') return;

    // If we're not authenticated, redirect to login page
    if (!isAuthenticated()) {
        window.location.href = '/login';
        return;
    }
    
    // Validate token on page load
    validateAuthToken().catch(() => {
        // If token is invalid, clear it and redirect to login
        localStorage.removeItem('auth_token');
        localStorage.removeItem('username');
        window.location.href = '/login';
    });

    // Add logout button event listener
    const logoutBtn = document.getElementById('local-logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', logout);
    }
}

// Auto-initialize when the script is loaded
document.addEventListener('DOMContentLoaded', initAuth);
