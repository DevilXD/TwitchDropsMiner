/**
 * Twitch authentication modal component
 * Displays the Twitch OAuth device code login UI
 */

// Ensure getAuthHeaders function is available (fallback if not loaded from main.js)
if (typeof getAuthHeaders === 'undefined') {
    function getAuthHeaders() {
        const token = localStorage.getItem('auth_token');
        return token ? { 'Authorization': `Bearer ${token}` } : {};
    }
}

// Global variables for keeping track of the auth flow state
let authCheckInterval = null;
let authExpiresAt = null;

// Export the login function globally so it can be called from main.js
// Function to initiate the Twitch login with device code
window.initiateLogin = function() {
    // Visual feedback for login button
    const loginButton = document.getElementById('login-button');
    if (loginButton) {
        const originalText = loginButton.innerHTML;
        loginButton.disabled = true;
        loginButton.innerHTML = '<i class="fas fa-circle-notch fa-spin mr-1"></i> Initiating Login...';
          // Show toast notification
        showToast('Login', 'Starting Twitch login process...', 'info');
          // Call the login API endpoint
        fetch('/api/twitch_login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...getAuthHeaders()
            },
            body: JSON.stringify({initiate: true})
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Show the device code modal
                showDeviceCodeModal(data);
                
                // Start polling for auth status
                startAuthPolling(data.interval, data.expires_in);
            } else {
                showToast('Error', data.error || 'Failed to initiate login', 'error');
                resetLoginButton(loginButton, originalText);
            }
        })
        .catch(error => {
            console.error('Login error:', error);
            showToast('Error', 'Failed to connect to server', 'error');
            resetLoginButton(loginButton, originalText);
        });
    }
}

// Function to reset the login button to its original state
window.resetLoginButton = function(button, originalText) {
    button.disabled = false;
    button.innerHTML = originalText;
}

// Function to show the device code modal
window.showDeviceCodeModal = function(data) {
    // Create modal container if it doesn't exist
    let modal = document.getElementById('auth-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'auth-modal';
        modal.className = 'fixed inset-0 flex items-center justify-center z-50';
        document.body.appendChild(modal);
    }
    
    // Calculate expiry time for display
    const expiryDate = new Date();
    expiryDate.setSeconds(expiryDate.getSeconds() + data.expires_in);
    const expiryTimeFormatted = expiryDate.toLocaleTimeString();
    
    // Set the modal content
    modal.innerHTML = `
        <div class="fixed inset-0 bg-black opacity-50"></div>
        <div class="bg-white rounded-lg w-11/12 md:w-1/2 lg:w-1/3 z-50 overflow-hidden shadow-xl">
            <div class="bg-purple-900 text-white px-4 py-2 flex justify-between items-center">
                <h3 class="font-bold text-lg">Login with Twitch</h3>
                <button id="close-modal" class="text-white hover:text-red-300">
                    <i class="fas fa-times"></i>
                </button>
            </div>
            <div class="p-4">
                <div class="flex flex-col items-center mb-4">
                    <div class="text-purple-800 text-4xl font-bold tracking-wider border-2 border-purple-800 rounded-md px-3 py-2 mb-4">${data.user_code}</div>
                    <p class="text-center mb-4">Enter this code at: <a href="${data.verification_uri}" target="_blank" class="text-blue-600 hover:underline">${data.verification_uri}</a></p>
                    <button id="open-twitch" class="bg-purple-600 hover:bg-purple-700 text-white font-bold py-2 px-4 rounded">
                        <i class="fab fa-twitch mr-2"></i>Open Twitch Activation Page
                    </button>
                </div>
                <div class="mt-6">
                    <div class="relative pt-1">
                        <div class="flex mb-2 items-center justify-between">
                            <div>
                                <span id="auth-status-text" class="text-xs font-semibold inline-block py-1 px-2 uppercase rounded-full text-purple-600 bg-purple-200">
                                    Waiting for authorization...
                                </span>
                            </div>
                            <div class="text-right">
                                <span id="auth-timer" class="text-xs font-semibold inline-block text-purple-600">
                                    Expires at ${expiryTimeFormatted}
                                </span>
                            </div>
                        </div>
                        <div class="overflow-hidden h-2 mb-4 text-xs flex rounded bg-purple-200">
                            <div id="auth-progress" style="width: 0%" class="shadow-none flex flex-col text-center whitespace-nowrap text-white justify-center bg-purple-500 transition-all duration-500"></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    // Add event listeners
    document.getElementById('close-modal').addEventListener('click', () => {
        closeDeviceCodeModal();
    });
    
    document.getElementById('open-twitch').addEventListener('click', () => {
        window.open(data.verification_uri, '_blank');
    });
    
    // Show the modal with animation
    setTimeout(() => {
        modal.classList.add('opacity-100');
    }, 10);
}

// Function to close the device code modal
window.closeDeviceCodeModal = function() {
    const modal = document.getElementById('auth-modal');
    if (modal) {
        // Stop polling
        stopAuthPolling();
        
        // Remove modal with animation
        modal.classList.remove('opacity-100');
        setTimeout(() => {
            modal.remove();
        }, 300);
        
        // Reset login button
        const loginButton = document.getElementById('login-button');
        if (loginButton) {
            loginButton.disabled = false;
            loginButton.innerHTML = '<i class="fas fa-sign-in-alt mr-1"></i> Login with Twitch';
        }
    }
}

// Function to start polling for auth status
window.startAuthPolling = function(interval, expiresIn) {
    // Store expiry time
    authExpiresAt = Date.now() + (expiresIn * 1000);
    
    // Calculate initial progress percentage
    updateAuthProgress(expiresIn);
    
    // Clear any existing interval
    stopAuthPolling();
    
    // Start new polling interval
    authCheckInterval = setInterval(() => {
        // Check if expired
        if (Date.now() > authExpiresAt) {
            stopAuthPolling();
            document.getElementById('auth-status-text').innerText = 'Expired';
            document.getElementById('auth-status-text').classList.remove('text-purple-600', 'bg-purple-200');
            document.getElementById('auth-status-text').classList.add('text-red-600', 'bg-red-200');
            showToast('Error', 'Authentication expired. Please try again.', 'error');
            return;
        }
        
        // Update progress bar
        const remainingSeconds = Math.max(0, Math.floor((authExpiresAt - Date.now()) / 1000));
        updateAuthProgress(remainingSeconds, expiresIn);
          // Poll the server for auth status
        fetch('/api/twitch_check_auth', {
            headers: getAuthHeaders()
        })
            .then(response => response.json())
            .then(data => {
                if (data.error && data.expired) {
                    stopAuthPolling();
                    document.getElementById('auth-status-text').innerText = 'Expired';
                    document.getElementById('auth-status-text').classList.remove('text-purple-600', 'bg-purple-200');
                    document.getElementById('auth-status-text').classList.add('text-red-600', 'bg-red-200');
                    showToast('Error', 'Authentication expired. Please try again.', 'error');
                    return;
                }
                
                if (data.success && data.authorized) {
                    // User has authorized, login successful
                    document.getElementById('auth-status-text').innerText = 'Authorized!';
                    document.getElementById('auth-status-text').classList.remove('text-purple-600', 'bg-purple-200');
                    document.getElementById('auth-status-text').classList.add('text-green-600', 'bg-green-200');
                      showToast('Success', 'Login successful!', 'success');
                    
                    // Close the modal after a short delay
                    setTimeout(() => {
                        closeDeviceCodeModal();

                        // Trigger manual refresh to update all data after successful login
                        setTimeout(() => {
                            const manualRefreshButton = document.getElementById('manual-refresh');
                            if (manualRefreshButton) {
                                manualRefreshButton.click();
                            }
                        }, 500); // Small delay to ensure modal is fully closed
                    }, 2000);
                    
                    // Stop polling
                    stopAuthPolling();
                }
            })
            .catch(error => {
                console.error('Auth check error:', error);
            });
    }, interval * 1000); // Convert to milliseconds
}

// Function to stop polling for auth status
window.stopAuthPolling = function() {
    if (authCheckInterval) {
        clearInterval(authCheckInterval);
        authCheckInterval = null;
    }
}

// Function to update the auth progress bar
window.updateAuthProgress = function(remainingSeconds, totalSeconds) {
    const progressBar = document.getElementById('auth-progress');
    const timerText = document.getElementById('auth-timer');
    
    if (progressBar && timerText) {
        // Calculate progress percentage
        const totalSeconds = Math.floor((authExpiresAt - Date.now() + (remainingSeconds * 1000)) / 1000);
        const percentage = 100 - ((remainingSeconds / totalSeconds) * 100);
        
        // Update progress bar
        progressBar.style.width = `${percentage}%`;
        
        // Update timer text
        const minutes = Math.floor(remainingSeconds / 60);
        const seconds = remainingSeconds % 60;
        timerText.innerText = `Expires in ${minutes}:${seconds < 10 ? '0' : ''}${seconds}`;
    }
}
