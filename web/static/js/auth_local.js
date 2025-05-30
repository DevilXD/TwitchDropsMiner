/**
 * Twitch Drops Miner - Local Authentication
 * auth_local.js - Handles local login functionality
 */

document.addEventListener('DOMContentLoaded', () => {
    // Check if this is a first-time setup
    checkFirstTimeSetup();

    // Setup login form
    const loginForm = document.getElementById('login-form');
    if (loginForm) {
        loginForm.addEventListener('submit', handleLogin);
    }
});

// Function to check if this is the first time setup
function checkFirstTimeSetup() {
    fetch('/api/auth/check-setup')
        .then(response => response.json())
        .then(data => {
            const firstUserSetup = document.getElementById('first-user-setup');
            const loginButton = document.getElementById('login-button');
            
            if (data.needsSetup) {
                // This is the first time setup
                if (firstUserSetup) {
                    firstUserSetup.classList.remove('hidden');
                }
                
                if (loginButton) {
                    loginButton.textContent = 'Create Account';
                }
            }
        })
        .catch(error => {
            console.error('Error checking setup status:', error);
        });
}

// Function to handle login form submission
function handleLogin(event) {
    event.preventDefault();
    
    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;
    const loginButton = document.getElementById('login-button');
    const errorMessage = document.getElementById('error-message');
    const errorText = document.querySelector('.error-text');
    
    // Basic validation
    if (!username || !password) {
        if (errorMessage) {
            errorMessage.classList.remove('hidden');
            if (errorText) {
                errorText.textContent = 'Please enter both username and password';
            }
        }
        return;
    }
    
    // Disable button and show loading state
    if (loginButton) {
        loginButton.disabled = true;
        loginButton.innerHTML = '<i class="fas fa-circle-notch fa-spin mr-1"></i> Please wait...';
    }
    
    // Hide any previous error message
    if (errorMessage) {
        errorMessage.classList.add('hidden');
    }
    
    // Prepare login data
    const loginData = {
        username: username,
        password: password
    };
    
    // Send login request to the API
    fetch('/api/auth/login', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(loginData)
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('Login failed');
        }
        return response.json();
    })
    .then(data => {
        if (data.success) {
            // Store the token in localStorage
            localStorage.setItem('auth_token', data.token);
            
            // Redirect to the dashboard
            window.location.href = '/';
        } else {
            // Show error message
            if (errorMessage) {
                errorMessage.classList.remove('hidden');
                if (errorText) {
                    errorText.textContent = data.message || 'Login failed';
                }
            }
            
            // Reset button state
            if (loginButton) {
                loginButton.disabled = false;
                loginButton.innerHTML = 'Sign in';
            }
        }
    })
    .catch(error => {
        console.error('Login error:', error);
        
        // Show error message
        if (errorMessage) {
            errorMessage.classList.remove('hidden');
            if (errorText) {
                errorText.textContent = 'Login failed. Please try again.';
            }
        }
        
        // Reset button state
        if (loginButton) {
            loginButton.disabled = false;
            loginButton.innerHTML = 'Sign in';
        }
    });
}
