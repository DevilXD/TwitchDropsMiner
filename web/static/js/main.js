/**
 * Twitch Drops Miner - Web Interface
 * main.js - Frontend functionality for the web interface
 */

// Global variables
let currentTab = 'channels';
let refreshInterval = null;
let channelsData = [];
let campaignsData = [];
let inventoryData = { claimed: [], pending: [] };
let settingsData = {};
let isDataLoading = false;

// Initialize the application when the page loads
document.addEventListener('DOMContentLoaded', () => {
    setupTabNavigation();
    setupEventListeners();
    
    // Restore scroll positions on initial load
    const activeTabButton = document.querySelector('.tab-button.border-purple-600');
    if (activeTabButton) {
        const tabId = activeTabButton.id.replace('tab-btn-', '');
        if (tabId === 'campaigns' || tabId === 'inventory') {
            setTimeout(() => restoreScrollPosition(tabId), 500); // Delay for content to load
        }
    }
    
    // Track when the window gets focus for browsers that might not properly support visibilitychange
    let windowBlurred = false;
    window.addEventListener('blur', () => {
        windowBlurred = true;
        console.log('Window lost focus');
    });
      window.addEventListener('focus', () => {
        if (windowBlurred) {
            windowBlurred = false;
            console.log('Window regained focus, refreshing only status and channels...');
            
            // Save scroll position first
            if (window.saveCurrentScrollPosition) {
                window.saveCurrentScrollPosition();
            }
            
            // Small delay to ensure the window is fully focused
            setTimeout(() => {
                // Only refresh status and channels, not campaigns or inventory to prevent scroll jump
                refreshData({
                    refreshChannels: true,
                    refreshCampaigns: false,  // Don't auto-refresh campaigns on focus
                    refreshInventory: false,  // Don't auto-refresh inventory on focus
                    refreshSettings: false,
                    refreshLogin: true
                });
            }, 300);
        }
    });
        // Initial data fetch with full loading indicator
    refreshData({ showLoader: true }).then(() => {
        // Set up auto-refresh every 10 seconds only after initial load completes
        // Only auto-refresh status and channels, don't show loader
        refreshInterval = setInterval(() => {
            // Save scroll position first if needed (especially for active campaign/inventory tabs)
            if (window.saveCurrentScrollPosition && 
                (window.currentTab === 'campaigns' || window.currentTab === 'inventory')) {
                window.saveCurrentScrollPosition();
            }
            
            refreshData({
                showLoader: false,
                refreshChannels: true,
                refreshCampaigns: false,  // Never auto-refresh campaigns in background
                refreshInventory: false,  // Never auto-refresh inventory in background
                refreshSettings: false,
                refreshLogin: false
            }).catch(error => {
                console.error('Auto-refresh error:', error);
                // Even if there's an error, we want to continue with future refreshes
            });
        }, 10000);
    });
});

// The scroll position preservation is now handled by scroll-position.js

// Function to reload the miner
function reloadMiner() {
    // Visual feedback for reload button
    const reloadButton = document.getElementById('reload-button');
    if (reloadButton) {
        const originalText = reloadButton.innerHTML;
        reloadButton.disabled = true;
        reloadButton.innerHTML = '<i class="fas fa-sync fa-spin mr-1"></i> Reloading...';
        
        // Show toast notification
        showToast('Reloading', 'Reloading the Twitch Drops Miner...', 'info');
        
        // Call the reload API endpoint
        fetch('/api/reload', {
            method: 'POST'
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showToast('Success', 'Miner successfully reloaded', 'success');
                // Refresh data after a short delay
                setTimeout(refreshData, 2000);
            } else {
                showToast('Error', data.error || 'Failed to reload the miner', 'error');
            }
        })
        .catch(error => {
            console.error('Error reloading the miner:', error);
            showToast('Error', 'Failed to reload the miner. Check console for details.', 'error');
        })
        .finally(() => {
            setTimeout(() => {
                reloadButton.disabled = false;
                reloadButton.innerHTML = originalText;
            }, 2000);
        });
    }
}

// Function to manually refresh inventory

function manualRefreshInventory() {
    // Visual feedback for refresh button
    const refreshButton = document.getElementById('refresh-inventory');
    if (refreshButton) {
        const originalText = refreshButton.innerHTML;
        refreshButton.disabled = true;
        refreshButton.innerHTML = '<i class="fas fa-circle-notch fa-spin mr-1"></i> Refreshing...';
        
        // Show toast notification
        showToast('Refreshing', 'Refreshing inventory data...', 'info');
        
        // Call the refresh inventory API endpoint
        fetch('/api/refresh_inventory', {
            method: 'POST'
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showToast('Success', data.message || 'Inventory refresh initiated', 'success');
                // Refresh data after a short delay
                setTimeout(refreshData, 2000);
            } else {
                showToast('Error', data.error || 'Failed to refresh inventory', 'error');
            }
        })
        .catch(error => {
            console.error('Error refreshing inventory:', error);
            showToast('Error', 'Failed to refresh inventory. Check console for details.', 'error');
        })
        .finally(() => {
            setTimeout(() => {
                refreshButton.disabled = false;
                refreshButton.innerHTML = originalText;
            }, 2000);
        });
    }
}

// Function to initiate Twitch logout
function initiateLogout() {
    // Visual feedback for logout button
    const logoutButton = document.getElementById('logout-button');
    if (logoutButton) {
        const originalText = logoutButton.innerHTML;
        logoutButton.disabled = true;
        logoutButton.innerHTML = '<i class="fas fa-circle-notch fa-spin mr-1"></i> Logging Out...';
        
        // Show toast notification
        showToast('Logout', 'Logging out from Twitch...', 'info');
        
        // Call the logout API endpoint
        fetch('/api/logout', {
            method: 'POST'
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showToast('Success', 'Successfully logged out', 'success');
                // Refresh data after a short delay
                setTimeout(refreshData, 2000);
            } else {
                showToast('Error', data.error || 'Failed to logout', 'error');
            }
        })
        .catch(error => {
            console.error('Error during logout:', error);
            showToast('Error', 'Failed to logout. Check console for details.', 'error');
        })
        .finally(() => {
            setTimeout(() => {
                logoutButton.disabled = false;
                logoutButton.innerHTML = originalText;
            }, 2000);
        });
    }
}

// Set up tab navigation
function setupTabNavigation() {
    const tabButtons = document.querySelectorAll('.tab-button');
    const tabPanels = document.querySelectorAll('.tab-panel');
    
    tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            // Get the tab ID from the button ID
            const tabId = button.id.replace('tab-btn-', '');
            
            // Start preloading data for the selected tab
            if (tabId === 'campaigns') {
                // If we're switching to campaigns, preload campaigns data
                preloadData('campaigns');
            } else if (tabId === 'inventory') {
                // If we're switching to inventory, preload inventory data
                preloadData('inventory');
            } else if (tabId === 'channels') {
                // If we're switching to channels, preload channels data
                preloadData('channels');
            }
            
            // Save scroll position for current tab before switching
            if (currentTab === 'campaigns' || currentTab === 'inventory') {
                saveScrollPosition(currentTab);
            }
            
            // Update active tab button
            tabButtons.forEach(btn => {
                if (btn === button) {
                    btn.classList.add('border-purple-600', 'text-purple-600');
                    btn.classList.remove('border-transparent', 'text-gray-500');
                } else {
                    btn.classList.remove('border-purple-600', 'text-purple-600');
                    btn.classList.add('border-transparent', 'text-gray-500');
                }
            });
            
            // Show/hide tab panels
            tabPanels.forEach(panel => {
                if (panel.id === `${tabId}-tab`) {
                    panel.classList.remove('hidden');
                    
                    // When a tab becomes visible, make sure lazy loading is set up
                    setTimeout(() => setupLazyLoading(), 100);
                    
                    // Restore scroll position for the tab we're switching to
                    if (tabId === 'campaigns' || tabId === 'inventory') {
                        restoreScrollPosition(tabId);
                    }
                } else {
                    panel.classList.add('hidden');
                }
            });
            
            // Update current tab
            currentTab = tabId;
        });
    });
}

// Set up event listeners
function setupEventListeners() {
    // Page visibility change event to refresh data when user returns to the tab
    let wasHidden = false;      // Check if the page was hidden
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'hidden') {
            wasHidden = true;
            console.log('Tab hidden, marking for refresh on return');
        } else if (document.visibilityState === 'visible' && wasHidden) {
            wasHidden = false;
            console.log('Tab became visible after being hidden, refreshing status and channels only...');
            
            // Save scroll position first
            if (window.saveCurrentScrollPosition) {
                window.saveCurrentScrollPosition();
            }
            
            // Small delay to ensure the tab is fully active
            setTimeout(() => {
                refreshData({
                    refreshChannels: true,
                    refreshCampaigns: false,  // Don't auto-refresh campaigns on visibility change
                    refreshInventory: false,  // Don't auto-refresh inventory on visibility change 
                    refreshSettings: false,
                    refreshLogin: true
                });
            }, 300);
        }
    });

    // Channel search
    const channelSearch = document.getElementById('channel-search');
    if (channelSearch) {
        channelSearch.addEventListener('input', (event) => {
            filterChannels(event.target.value.toLowerCase());
        });
    }
    
    // Settings-related event listeners
    const saveSettingsButton = document.getElementById('save-settings-button');
    if (saveSettingsButton) {
        saveSettingsButton.addEventListener('click', () => saveSettings(false));
    }
    
    // Reload button in settings tab (save and reload)
    const reloadButton = document.getElementById('reload-button');
    if (reloadButton) {
        reloadButton.addEventListener('click', () => saveSettings(true));
    }
    
    // Add priority game button
    const addPriorityButton = document.getElementById('add-priority-game');
    if (addPriorityButton) {
        addPriorityButton.addEventListener('click', addPriorityGame);
    }
    
    // Add exclusion game button
    const addExcludeButton = document.getElementById('add-exclude-game');
    if (addExcludeButton) {
        addExcludeButton.addEventListener('click', addExclusionGame);
    }
      // Login button
    const loginButton = document.getElementById('login-button');
    if (loginButton) {
        loginButton.addEventListener('click', initiateLogin);
    }
    
    // Logout button
    const logoutButton = document.getElementById('logout-button');
    if (logoutButton) {
        logoutButton.addEventListener('click', initiateLogout);
    }
      // Manual refresh button in header
    const manualRefreshButton = document.getElementById('manual-refresh');
    if (manualRefreshButton) {
        manualRefreshButton.addEventListener('click', () => {
            // Visual feedback for refresh
            const icon = manualRefreshButton.querySelector('i');
            manualRefreshButton.disabled = true;
            icon.classList.add('fa-spin');
            
            // Full refresh with progress bar
            refreshData({
                refreshChannels: true,
                refreshCampaigns: true,
                refreshInventory: true,
                refreshSettings: true,
                refreshLogin: true
            }).finally(() => {
                // Reset button state after refresh completes
                setTimeout(() => {
                    manualRefreshButton.disabled = false;
                    icon.classList.remove('fa-spin');
                }, 500);
            });
        });
    }// Manual refresh button in the main content
    const refreshButton = document.getElementById('refresh-button');
    if (refreshButton) {
        refreshButton.addEventListener('click', () => {
            // Visual feedback for refresh
            const icon = refreshButton.querySelector('i');
            refreshButton.disabled = true;
            icon.classList.add('fa-spin');
            
            // Show toast notification
            showToast('Refreshing', 'Fetching latest data from the miner...', 'info');
            
            // Perform full refresh with loader and handle the promise
            refreshData({
                showLoader: true,
                refreshChannels: true,
                refreshCampaigns: true,
                refreshInventory: true,
                refreshSettings: true,
                refreshLogin: true
            })
                .catch(error => {
                    console.error('Manual refresh error:', error);
                    showToast('Refresh Error', 'There was an error refreshing the data.', 'error');
                })
                .finally(() => {
                    // Reset button after completion
                    setTimeout(() => {
                        icon.classList.remove('fa-spin');
                        refreshButton.disabled = false;
                    }, 500);
                });
        });
    }
    
    // Header refresh button
    const headerRefreshButton = document.getElementById('manual-refresh');
    if (headerRefreshButton) {
        headerRefreshButton.addEventListener('click', () => {
            // Visual feedback for refresh
            const icon = headerRefreshButton.querySelector('i');
            headerRefreshButton.disabled = true;
            icon.classList.add('fa-spin');
              // Show toast notification
            showToast('Refreshing', 'Fetching latest data from the miner...', 'info');
            
            // Perform full refresh with loader and handle the promise
            refreshData({
                showLoader: true,
                refreshChannels: true,
                refreshCampaigns: true,
                refreshInventory: true,
                refreshSettings: true,
                refreshLogin: true
            })
                .catch(error => {
                    console.error('Manual refresh error:', error);
                    showToast('Refresh Error', 'There was an error refreshing the data.', 'error');
                })
                .finally(() => {
                    // Reset button after completion
                    setTimeout(() => {
                        icon.classList.remove('fa-spin');
                        headerRefreshButton.disabled = false;
                    }, 500);
                });
        });
    }
    
    // Diagnostic panel buttons
    const fetchDiagnosticsButton = document.getElementById('fetch-diagnostics');
    if (fetchDiagnosticsButton) {
        fetchDiagnosticsButton.addEventListener('click', () => {
            // Visual feedback
            const originalText = fetchDiagnosticsButton.innerHTML;
            fetchDiagnosticsButton.disabled = true;
            fetchDiagnosticsButton.innerHTML = '<i class="fas fa-circle-notch fa-spin mr-1"></i> Checking...';
            
            // Fetch diagnostics
            fetchDiagnostics()
                .finally(() => {
                    setTimeout(() => {
                        fetchDiagnosticsButton.disabled = false;
                        fetchDiagnosticsButton.innerHTML = originalText;
                    }, 1000);
                });
        });
    }
    
    // Refresh inventory button
    const refreshInventoryButton = document.getElementById('refresh-inventory');
    if (refreshInventoryButton) {
        refreshInventoryButton.addEventListener('click', manualRefreshInventory);
    }
    
    // Reconnect websocket button
    const reconnectWebsocketButton = document.getElementById('reconnect-websocket');
    if (reconnectWebsocketButton) {
        reconnectWebsocketButton.addEventListener('click', () => {
            // Visual feedback
            const originalText = reconnectWebsocketButton.innerHTML;
            reconnectWebsocketButton.disabled = true;
            reconnectWebsocketButton.innerHTML = '<i class="fas fa-circle-notch fa-spin mr-1"></i> Reconnecting...';
            
            // Show toast notification
            showToast('Reconnecting', 'Attempting to reconnect to the miner...', 'info');
            
            // Force a refresh to trigger reconnection
            refreshData()
                .finally(() => {
                    setTimeout(() => {
                        reconnectWebsocketButton.disabled = false;
                        reconnectWebsocketButton.innerHTML = originalText;
                        
                        // Fetch diagnostics to update connection status
                        fetchDiagnostics();                    }, 2000);
                });
        });
    }
} // End of setupEventListeners function

// Filter channels based on search input
function filterChannels(searchValue) {
    const rows = document.querySelectorAll('#channels-table-body tr');
    
    rows.forEach(row => {
        const channelName = row.querySelector('.channel-name').textContent.toLowerCase();
        const gameName = row.querySelector('.game-name')?.textContent.toLowerCase() || '';
        
        if (channelName.includes(searchValue) || gameName.includes(searchValue)) {
            row.style.display = '';
        } else {
            row.style.display = 'none';
        }
    });
}

// Refresh all data with option to show loading indicators and refresh specific tabs
function refreshData(options = {}) {
    const defaults = {
        showLoader: false,
        refreshChannels: true,
        refreshCampaigns: true,
        refreshInventory: true,
        refreshSettings: true,
        refreshLogin: true
    };
    
    const config = { ...defaults, ...options };
    
    if (isDataLoading) return Promise.resolve(); // Prevent multiple concurrent refreshes without rejecting the promise
    
    // Scroll position saving is now handled by scroll-position.js
    
    isDataLoading = true;
    
    // Update last refresh time indicator
    const lastRefreshTime = document.querySelector('#last-refresh-time span');
    if (lastRefreshTime) {
        const now = new Date();
        const timeString = now.toLocaleTimeString();
        lastRefreshTime.textContent = `Refreshing...`;
    }
    
    // Show the progress bar
    const progressContainer = document.getElementById('progress-container');
    const progressBar = document.getElementById('progress-bar');
    if (progressContainer && progressBar) {
        progressContainer.classList.add('visible');
        progressBar.style.width = '15%'; // Start with small width
        
        // Simulate progress
        let width = 15;
        const interval = setInterval(() => {
            if (width < 90) { // Only go up to 90%, will go to 100% when completed
                width += (90 - width) / 10;
                progressBar.style.width = `${width}%`;
            }
        }, 200);
        
        // Store the interval ID for cleanup
        window.progressInterval = interval;
    }
    
    // Create a promise for each data fetch based on config
    const fetchPromises = [
        fetchStatus().catch(error => ({ error })), // Always fetch status
    ];
    
    // Only add these fetches if configured to do so
    if (config.refreshChannels) {
        fetchPromises.push(fetchChannels().catch(error => ({ error })));
    }
    
    if (config.refreshCampaigns) {
        fetchPromises.push(fetchCampaigns().catch(error => ({ error })));
    }
    
    if (config.refreshInventory) {
        fetchPromises.push(fetchInventory().catch(error => ({ error })));
    }
    
    if (config.refreshLogin) {
        fetchPromises.push(checkLoginStatus().catch(error => ({ error })));
    }
    
    if (config.refreshSettings) {
        fetchPromises.push(fetchSettings().catch(error => ({ error })));
    }
    
    // Occasionally fetch diagnostics (every 3rd refresh)
    const refreshCount = parseInt(localStorage.getItem('refreshCount') || '0', 10) + 1;
    localStorage.setItem('refreshCount', refreshCount.toString());
    
    if (refreshCount % 3 === 0) {
        fetchPromises.push(fetchDiagnostics().catch(error => ({ error })));
    }
      // When all fetches are complete, update the state
    return Promise.all(fetchPromises)
        .catch(error => {
            // This should never happen with the individual catch handlers
            console.error('Error during data refresh:', error);
            return []; // Return empty array to allow execution to continue
        })        .finally(() => {
            // Complete the progress bar
            const progressContainer = document.getElementById('progress-container');
            const progressBar = document.getElementById('progress-bar');
            if (progressContainer && progressBar) {
                // Clear any existing interval
                if (window.progressInterval) {
                    clearInterval(window.progressInterval);
                    window.progressInterval = null;
                }
                
                // Complete the progress
                progressBar.style.width = '100%';
                
                // Hide after completion
                setTimeout(() => {
                    progressContainer.classList.remove('visible');
                    // Reset progress bar for next time
                    setTimeout(() => {
                        progressBar.style.width = '0%';
                    }, 300);
                }, 500);
            }            // Always reset the isDataLoading flag
            isDataLoading = false;
            
            // Update the last refresh time
            const lastRefreshElement = document.getElementById('last-refresh-time');
            if (lastRefreshElement && lastRefreshElement.querySelector) {
                const lastRefreshSpan = lastRefreshElement.querySelector('span');
                if (lastRefreshSpan) {
                    const now = new Date();
                    const timeString = now.toLocaleTimeString();
                    lastRefreshSpan.textContent = `Last updated: ${timeString}`;
                }
            }
            
            // Scroll position restoration is now handled by scroll-position.js
        });
}

// Fetch the current miner status
let statusRetryCount = 0;
const maxStatusRetries = 3; // Max number of consecutive retries

function fetchStatus() {
    return new Promise((resolve) => {
        fetch('/api/status')
            .then(response => {
                if (!response.ok) {
                    throw new Error(`Status API returned ${response.status}: ${response.statusText}`);
                }
                // Reset retry count on success
                statusRetryCount = 0; 
                return response.json();
            })
            .then(data => {
                if (data.error) {
                    throw new Error(data.error);
                }
                
                // Update the UI with status information
                updateStatusUI(data);
                  // Update connection status indicator
                const connectionStatus = document.getElementById('connection-status');
                if (connectionStatus) {
                    connectionStatus.textContent = 'Connected';
                    connectionStatus.classList.add('text-green-500');
                    connectionStatus.classList.remove('text-red-500', 'text-yellow-500');
                }
                
                // Add a timestamp to local storage to track last successful communication
                localStorage.setItem('lastStatusUpdate', new Date().toISOString());
                
                resolve(data);
            })            .catch(error => {
                console.error('Error fetching status:', error);
                  // Update UI to show error
                updateStatusUIError();
                
                // Update connection status indicator
                const connectionStatus = document.getElementById('connection-status');
                if (connectionStatus) {
                    connectionStatus.textContent = 'Disconnected';
                    connectionStatus.classList.add('text-red-500');
                    connectionStatus.classList.remove('text-green-500', 'text-yellow-500');
                }
                
                // Handle automatic reconnection attempts
                statusRetryCount++;
                if (statusRetryCount <= maxStatusRetries) {                    
                    console.log(`Retry attempt ${statusRetryCount}/${maxStatusRetries} in 2 seconds...`);
                    const connectionStatus = document.getElementById('connection-status');
                    if (connectionStatus) {
                        connectionStatus.textContent = `Reconnecting (${statusRetryCount}/${maxStatusRetries})`;
                        connectionStatus.classList.add('text-yellow-500');
                        connectionStatus.classList.remove('text-green-500', 'text-red-500');
                    }
                    
                    // Always resolve the current promise, and initiate a new retry after a delay
                    resolve({ error: 'Connection error, retrying...' });
                    
                    setTimeout(() => {
                        fetchStatus();  // Don't chain to the current promise
                    }, 2000);
                } else {
                    // Reset retry count and resolve with error to allow next refresh cycle
                    statusRetryCount = 0;
                    resolve({ error: 'Max retries reached' });
                }
            });
    });
}

// Update the status UI with error state
function updateStatusUIError() {
    // Update mining status
    const miningStatus = document.getElementById('mining-status');
    if (miningStatus) {
        miningStatus.textContent = 'Connection Error';
        miningStatus.className = 'font-bold text-2xl text-red-500';
    }
    
    // Update state
    const stateValue = document.getElementById('state-value');
    if (stateValue) stateValue.textContent = 'ERROR';
    
    // Clear other fields
    const usernameValue = document.getElementById('username-value');
    if (usernameValue) usernameValue.textContent = 'Unknown';
    
    const channelValue = document.getElementById('channel-value');
    if (channelValue) channelValue.textContent = 'Unknown';
    
    const gameValue = document.getElementById('game-value');
    if (gameValue) gameValue.textContent = 'Unknown';
    
    const dropValue = document.getElementById('drop-value');
    if (dropValue) dropValue.textContent = 'Unknown';
    
    // Reset progress bar
    const progressBar = document.getElementById('drop-progress-bar');
    if (progressBar) {
        progressBar.style.width = '0%';
        progressBar.textContent = '0%';
    }
    
    // Clear time remaining
    const timeRemaining = document.getElementById('time-remaining');
    if (timeRemaining) {
        timeRemaining.textContent = 'Connection lost';
    }
}

// Fetch diagnostic information
function fetchDiagnostics() {
    return new Promise((resolve) => {
        fetch('/api/diagnostic')
            .then(response => {
                if (!response.ok) {
                    throw new Error(`Diagnostic API returned ${response.status}: ${response.statusText}`);
                }
                return response.json();
            })
            .then(data => {
                if (data.error) {
                    throw new Error(data.error);
                }
                
                // Update diagnostic UI
                updateDiagnosticUI(data);
                resolve(data);
            })
            .catch(error => {
                console.error('Error fetching diagnostics:', error);
                updateDiagnosticUIError();
                // Still resolve the promise to avoid cascading failures
                resolve({ error: 'Failed to fetch diagnostics' });
            });
    });
}

// Update diagnostic UI with error
function updateDiagnosticUIError() {
    const elements = {
        'app-version': el => { if (el) el.textContent = 'Error'; },
        'connection-detail': el => { if (el) el.innerHTML = '<span class="h-3 w-3 rounded-full bg-red-500 mr-2"></span>Error'; },
        'websocket-status': el => { if (el) el.innerHTML = '<span class="h-3 w-3 rounded-full bg-red-500 mr-2"></span>Error'; },
        'login-status': el => { if (el) el.innerHTML = '<span class="h-3 w-3 rounded-full bg-red-500 mr-2"></span>Error'; },
        'campaigns-count': el => { if (el) el.textContent = '0'; },
        'channels-count': el => { if (el) el.textContent = '0'; },
        'drops-count': el => { if (el) el.textContent = '0'; }
    };
    
    // Update all elements with null checks
    Object.keys(elements).forEach(id => {
        const element = document.getElementById(id);
        if (element) {
            elements[id](element);
        }
    });
    
    // Show error toast
    showToast('Error', 'Failed to fetch diagnostic information. Check console for details.', 'error');
}

// Fetch available channels
function fetchChannels() {
    return new Promise((resolve) => {
        // Check if we have valid preloaded data
        // if (hasValidPreloadedData('channels')) {
        //     console.log('Using preloaded channels data');
        //     channelsData = preloadedData.channels;
        //     updateChannelsUI(preloadedData.channels);
        //     resolve(preloadedData.channels);
        //     // After using preloaded data, refresh it in background to keep it updated
        //     setTimeout(() => preloadData('channels'), 100);
        //     return;
        // }
        
        fetch('/api/channels')
            .then(response => {
                if (!response.ok) {
                    throw new Error(`Channels API returned ${response.status}: ${response.statusText}`);
                }
                return response.json();
            })
            .then(data => {
                if (data.error) {
                    console.error('Error from channels API:', data.error);                    
                    const channelsTable = document.getElementById('channels-table-body');
                    if (channelsTable) {
                        channelsTable.innerHTML = `<tr><td colspan="5" class="text-center py-4 text-red-500">Error: ${data.error}</td></tr>`;
                    }
                    throw new Error(data.error);
                }
                channelsData = data;
                // Update preloaded data
                preloadedData.channels = data;
                preloadedData.lastPreloadTime.channels = Date.now();
                
                updateChannelsUI(data);
                resolve(data);
            })
            .catch(error => {
                console.error('Error fetching channels:', error);
                const channelsTable = document.getElementById('channels-table-body');
                if (channelsTable) {
                    channelsTable.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-red-500">Failed to load channels. Please check your connection.</td></tr>';
                }
                // Still resolve the promise to avoid cascading failures
                resolve({ error: 'Failed to fetch channels' });
            });
    });
}

// Fetch drop campaigns
function fetchCampaigns() {
    return new Promise((resolve) => {
        // Check if we have valid preloaded data
        // if (hasValidPreloadedData('campaigns')) {
        //     console.log('Using preloaded campaigns data');
        //     campaignsData = preloadedData.campaigns;
        //     updateCampaignsUI(preloadedData.campaigns);
        //     resolve(preloadedData.campaigns);
        //     // After using preloaded data, refresh it in background to keep it updated
        //     setTimeout(() => {
        //         preloadData('campaigns');
        //     }, 100);
        //     return;
        // }
        
        fetch('/api/campaigns')
            .then(response => {
                if (!response.ok) {
                    throw new Error(`Campaigns API returned ${response.status}: ${response.statusText}`);
                }
                return response.json();
            })
            .then(data => {
                if (data.error) {
                    console.error('Error from campaigns API:', data.error);
                    const campaignsList = document.getElementById('campaigns-list');
                    if (campaignsList) {
                        campaignsList.innerHTML = `<div class="col-span-full p-4 bg-white rounded shadow text-red-500">Error: ${data.error}</div>`;
                    }
                    throw new Error(data.error);
                }
                campaignsData = data;
                // Update preloaded data
                preloadedData.campaigns = data;
                preloadedData.lastPreloadTime.campaigns = Date.now();
                
                updateCampaignsUI(data);
                resolve(data);
            })
            .catch(error => {
                console.error('Error fetching campaigns:', error);
                const campaignsList = document.getElementById('campaigns-list');
                if (campaignsList) {
                    campaignsList.innerHTML = '<div class="col-span-full p-4 bg-white rounded shadow text-red-500">Failed to load campaigns. Please check your connection.</div>';
                }
                // Still resolve the promise to avoid cascading failures
                resolve({ error: 'Failed to fetch campaigns' });
            });
    });
}

// Fetch inventory (claimed and pending drops)
function fetchInventory() {
    return new Promise((resolve) => {
        // Check if we have valid preloaded data
        // if (hasValidPreloadedData('inventory')) {
        //     console.log('Using preloaded inventory data');
        //     inventoryData = preloadedData.inventory;
        //     updateInventoryUI(preloadedData.inventory);
        //     resolve(preloadedData.inventory);
        //     // After using preloaded data, refresh it in background to keep it updated
        //     setTimeout(() => preloadData('inventory'), 100);
        //     return;
        // }
        
        fetch('/api/inventory')
            .then(response => {
                if (!response.ok) {
                    throw new Error(`Inventory API returned ${response.status}: ${response.statusText}`);
                }
                return response.json();
            })
            .then(data => {
                if (data.error) {
                    console.error('Error from inventory API:', data.error);
                    const pendingDrops = document.getElementById('pending-drops');
                    const claimedDrops = document.getElementById('claimed-drops');
                    
                    if (pendingDrops) {
                        pendingDrops.innerHTML = `<div class="p-4 bg-white rounded shadow text-red-500">Error: ${data.error}</div>`;
                    }
                    
                    if (claimedDrops) {
                        claimedDrops.innerHTML = `<div class="p-4 bg-white rounded shadow text-red-500">Error: ${data.error}</div>`;
                    }
                    throw new Error(data.error);
                }
                inventoryData = data;
                // Update preloaded data
                preloadedData.inventory = data;
                preloadedData.lastPreloadTime.inventory = Date.now();
                
                updateInventoryUI(data);
                resolve(data);
            })
            .catch(error => {
                console.error('Error fetching inventory:', error);
                const pendingDrops = document.getElementById('pending-drops');
                const claimedDrops = document.getElementById('claimed-drops');
                
                if (pendingDrops) {
                    pendingDrops.innerHTML = '<div class="p-4 bg-white rounded shadow text-red-500">Failed to load inventory. Please check your connection.</div>';
                }
                
                if (claimedDrops) {
                    claimedDrops.innerHTML = '<div class="p-4 bg-white rounded shadow text-red-500">Failed to load inventory. Please check your connection.</div>';
                }
                // Still resolve the promise to avoid cascading failures
                resolve({ error: 'Failed to fetch inventory' });
            });
    });
}

// Check login status
function checkLoginStatus() {
    return new Promise((resolve) => {
        fetch('/api/status')
            .then(response => {
                if (!response.ok) {
                    throw new Error(`Status API returned ${response.status}: ${response.statusText}`);
                }
                return response.json();
            })
            .then(data => {
                const userStatus = document.getElementById('user-status');
                const loggedInDiv = document.getElementById('logged-in');
                const notLoggedInDiv = document.getElementById('not-logged-in');
                const usernameDisplay = document.getElementById('username-display');
                const loginMessage = document.getElementById('login-message');
                
                if (data.username) {
                    // User is logged in
                    if (userStatus) {
                        userStatus.innerHTML = `<i class="fas fa-user mr-1"></i><span>Logged in as: ${data.username}</span>`;
                        userStatus.classList.add('text-green-400');
                        userStatus.classList.remove('text-yellow-400');
                    }
                    
                    if (loggedInDiv && notLoggedInDiv) {
                        loggedInDiv.classList.remove('hidden');
                        notLoggedInDiv.classList.add('hidden');
                        if (usernameDisplay) usernameDisplay.textContent = data.username;
                        if (loginMessage) loginMessage.textContent = `You are currently logged in to Twitch as ${data.username}`;
                    }
                } else {
                    // User is not logged in
                    if (userStatus) {
                        userStatus.innerHTML = `<i class="fas fa-user mr-1"></i><span>Not logged in</span>`;
                        userStatus.classList.add('text-yellow-400');
                        userStatus.classList.remove('text-green-400');
                    }
                    
                    if (loggedInDiv && notLoggedInDiv) {
                        loggedInDiv.classList.add('hidden');
                        notLoggedInDiv.classList.remove('hidden');
                        if (loginMessage) loginMessage.textContent = 'You are not currently logged in to Twitch';
                    }
                }
                resolve(data);
            })
            .catch(error => {
                console.error('Error checking login status:', error);
                // Still resolve the promise to avoid cascading failures
                resolve({ error: 'Failed to check login status' });
            });
    });
}

// Update the status UI with data received from API
function updateStatusUI(data) {
    // Update mining status text
    const miningStatus = document.getElementById('mining-status');
    if (miningStatus) {
        let statusText = 'Unknown';
        let statusColor = 'text-gray-800';
        
        switch (data.state) {
            case 'INITIALIZING':
                statusText = 'Initializing...';
                statusColor = 'text-blue-500';
                break;
            case 'INVENTORY_FETCH':
                statusText = 'Fetching Inventory...';
                statusColor = 'text-blue-500';
                break;
            case 'CHANNEL_WATCH':
                statusText = 'Watching Channel';
                statusColor = 'text-green-500';
                break;
            case 'DROP_CLAIM':
                statusText = 'Claiming Drop';
                statusColor = 'text-purple-500';
                break;
            case 'ERROR':
                statusText = 'Error';
                statusColor = 'text-red-500';
                break;
            case 'CHANNEL_SWITCH':
                statusText = 'Watching Channel...';
                statusColor = 'text-green-500';
                break;
            default:
                statusText = data.state || 'Unknown';
        }
        
        miningStatus.textContent = statusText;
        miningStatus.className = `font-bold text-2xl ${statusColor}`;
    }
    
    // Update state value
    const stateValue = document.getElementById('state-value');
    if (stateValue) stateValue.textContent = data.state || 'Unknown';
    
    // Update username value
    const usernameValue = document.getElementById('username-value');
    if (usernameValue) usernameValue.textContent = data.username || 'Not logged in';
    
    // Update channel value
    const channelValue = document.getElementById('channel-value');
    if (channelValue) channelValue.textContent = data.current_channel || 'None';
    
    // Update game value
    const gameValue = document.getElementById('game-value');
    if (gameValue) gameValue.textContent = data.current_game || 'None';
    
    // Update drop value
    const dropValue = document.getElementById('drop-value');
    if (dropValue) dropValue.textContent = data.current_drop || 'None';
    
    // Update progress bar
    const progressBar = document.getElementById('drop-progress-bar');
    if (progressBar && data.drop_progress !== undefined && data.drop_progress !== null) {
        const percent = Math.round(data.drop_progress * 100);
        progressBar.style.width = `${percent}%`;
        progressBar.textContent = `${percent}%`;
    } else if (progressBar) {
        progressBar.style.width = '0%';
        progressBar.textContent = '0%';
    }
    
    // Update time remaining
    const timeRemaining = document.getElementById('time-remaining');
    if (timeRemaining && data.time_remaining) {
        timeRemaining.textContent = `Time remaining: ${data.time_remaining}`;
    } else if (timeRemaining) {
        timeRemaining.textContent = '';
    }
    
    // Update current channel info card
    const currentChannel = document.getElementById('current-channel');
    if (currentChannel) {
        currentChannel.textContent = data.current_channel || 'None';
        if (!data.current_channel) {
            currentChannel.classList.add('text-gray-500');
        } else {
            currentChannel.classList.remove('text-gray-500');
        }
    }
    
    // Update current game info card
    const currentGame = document.getElementById('current-game');
    if (currentGame) {
        currentGame.textContent = data.current_game || 'None';
        if (!data.current_game) {
            currentGame.classList.add('text-gray-500');
        } else {
            currentGame.classList.remove('text-gray-500');
        }
    }
    
    // Update current drop info card
    const currentDrop = document.getElementById('current-drop');
    if (currentDrop) {
        currentDrop.textContent = data.current_drop || 'None';
        if (!data.current_drop) {
            currentDrop.classList.add('text-gray-500');
        } else {
            currentDrop.classList.remove('text-gray-500');
        }
    }
}

// Update the channels UI with data
function updateChannelsUI(data) {
    const channelsTable = document.getElementById('channels-table-body');
    if (!channelsTable) return;
    
    // Clear existing content
    channelsTable.innerHTML = '';
      if (!data || data.length === 0) {
        channelsTable.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-gray-500">No channels available.</td></tr>';
        return;
    }
    
    // Add channels rows
    data.forEach(channel => {
        const row = document.createElement('tr');
        
        // Highlight current channel
        if (channel.current) {
            row.classList.add('bg-purple-100');
        }
          // Channel name with status indicator
        const statusClass = channel.status === 'ONLINE' ? 'bg-green-500' : 'bg-gray-400';
        row.innerHTML = `
            <td class="px-4 py-3 border-b border-gray-200">
                <div class="flex items-center">
                    <span class="h-3 w-3 rounded-full ${statusClass} mr-2"></span>
                    <span class="channel-name font-medium ${channel.current ? 'text-purple-600 font-bold' : ''}">${channel.name}</span>
                </div>
            </td>
            <td class="px-4 py-3 border-b border-gray-200 game-name">${channel.game || 'Unknown'}</td>
            <td class="px-4 py-3 border-b border-gray-200 text-right">${channel.status === 'ONLINE' ? channel.viewers.toLocaleString() : '-'}</td>
            <td class="px-4 py-3 border-b border-gray-200 text-center">${channel.has_drops ? '<span class="text-green-500"><i class="fas fa-check"></i></span>' : ''}</td>            <td class="px-4 py-3 border-b border-gray-200 text-right">
                <button class="watch-channel-btn bg-blue-500 hover:bg-blue-700 text-white py-1 px-2 rounded text-xs" data-channel="${channel.name}">
                    <i class="fas fa-tv mr-1"></i> Watch <i class="fas fa-external-link-alt text-xs"></i>
                </button>
            </td>
        `;
        
        channelsTable.appendChild(row);
    });    // Add event listeners to watch buttons
    document.querySelectorAll('.watch-channel-btn').forEach(button => {
        button.addEventListener('click', () => {
            const channelName = button.getAttribute('data-channel');
            // Only open the URL directly, don't call watchChannel function to avoid errors
            window.open(`https://www.twitch.tv/${channelName}`, '_blank');
        });
    });
}

// Watch a channel
function watchChannel(channelName) {
    // Visual feedback
    showToast('Switching Channel', `Switching to channel: ${channelName}`, 'info');
    
    // Call the API
    fetch(`/api/set_channel/${channelName}`, {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast('Success', data.message || `Now watching ${channelName}`, 'success');
            // Refresh data after a short delay
            setTimeout(refreshData, 2000);
        } else {
            showToast('Error', data.error || `Failed to switch to ${channelName}`, 'error');
        }
    })
    .catch(error => {
        console.error('Error switching channel:', error);
        showToast('Error', `Failed to switch to ${channelName}. Check console for details.`, 'error');
    });
}

// Update the campaigns UI with data
function updateCampaignsUI(data) {
    const campaignsList = document.getElementById('campaigns-list');
    if (!campaignsList) return;
    
    // Clear existing content
    campaignsList.innerHTML = '';
    
    if (!data || data.length === 0) {
        campaignsList.innerHTML = '<div class="col-span-full p-4 bg-white rounded shadow text-gray-500 text-center">No campaigns available.</div>';
        return;
    }
    
    // Create a document fragment for better performance
    const fragment = document.createDocumentFragment();
    
    // Calculate how many campaigns to render initially (just visible ones plus a few more)
    // Determine approximately how many campaigns fit in the viewport
    const containerHeight = campaignsList.clientHeight;
    const approxCardHeight = 120; // Estimated height of a campaign card
    const visibleCards = Math.ceil(containerHeight / approxCardHeight) * 3; // Multiply by columns
    const initialRenderCount = Math.min(visibleCards + 10, data.length); // Render visible + 10 more
    
    // Add campaigns cards using virtual rendering approach
    for (let i = 0; i < initialRenderCount; i++) {
        const campaign = data[i];
        const card = createCampaignCard(campaign);
        fragment.appendChild(card);
    }
    
    // Append all cards at once for better performance
    campaignsList.appendChild(fragment);
    
    // Setup intersection observer for lazy loading images
    setupLazyLoading();
    
    // Setup intersection observer for virtual rendering
    if (data.length > initialRenderCount) {
        setupVirtualRendering(campaignsList, data, initialRenderCount);
    }
    
    // Scroll position restoration is now handled by scroll-position.js
}

// Helper function to create a campaign card
// Helper function to create campaign card - moved to lazy-loader.js

// This function is now moved to lazy-loader.js
// function setupVirtualRendering(container, data, startIndex)

// Update the inventory UI with data
function updateInventoryUI(data) {
    const pendingDrops = document.getElementById('pending-drops');
    const claimedDrops = document.getElementById('claimed-drops');
    
    if (!pendingDrops || !claimedDrops) return;
    
    // Clear existing content
    pendingDrops.innerHTML = '';
    claimedDrops.innerHTML = '';
    
    // Process drops - check for 100% completed drops and move them to claimed
    const pendingItems = [];
    const claimedItems = data.claimed ? [...data.claimed] : [];
    
    if (data.pending && data.pending.length > 0) {
        data.pending.forEach(drop => {
            // Calculate progress
            const progress = drop.current_minutes / drop.required_minutes;
            
            // If progress is 1.0 (100%), treat it as claimed
            if (progress >= 1.0) {
                // Add additional property to show it's auto-moved
                drop.autoMoved = true;
                claimedItems.push(drop);
            } else {
                pendingItems.push(drop);
            }
        });
    }
    
    // Create document fragments for better performance
    const pendingFragment = document.createDocumentFragment();
    const claimedFragment = document.createDocumentFragment();
    
    // Handle pending drops
    if (pendingItems.length === 0) {
        const emptyMessage = document.createElement('div');
        emptyMessage.className = 'p-4 bg-white rounded shadow text-center text-gray-500';
        emptyMessage.textContent = 'No pending drops.';
        pendingFragment.appendChild(emptyMessage);
    } else {
        // Only render the first batch of items initially
        const initialRenderCount = Math.min(10, pendingItems.length);
        
        for (let i = 0; i < initialRenderCount; i++) {
            const drop = pendingItems[i];
            const dropCard = createDropCard(drop, 'pending');
            pendingFragment.appendChild(dropCard);
        }
    }
    
    pendingDrops.appendChild(pendingFragment);
    
    // Handle claimed drops
    if (claimedItems.length === 0) {
        const emptyMessage = document.createElement('div');
        emptyMessage.className = 'p-4 bg-white rounded shadow text-center text-gray-500';
        emptyMessage.textContent = 'No claimed drops.';
        claimedFragment.appendChild(emptyMessage);
    } else {
        // Only render the first batch of items initially
        const initialRenderCount = Math.min(10, claimedItems.length);
        
        for (let i = 0; i < initialRenderCount; i++) {
            const drop = claimedItems[i];
            const dropCard = createDropCard(drop, 'claimed');
            claimedFragment.appendChild(dropCard);
        }
    }
    
    claimedDrops.appendChild(claimedFragment);
    
    // Setup lazy loading for images
    setupLazyLoading();    // Setup virtual rendering if needed
    if (pendingItems.length > 10) {
        setupDropsVirtualRendering(pendingDrops, pendingItems, 10, 'pending');
    }
    
    if (claimedItems.length > 10) {
        setupDropsVirtualRendering(claimedDrops, claimedItems, 10, 'claimed');
    }
    
    // Scroll position restoration is now handled by scroll-position.js
}

// Helper function to create a drop card - moved to lazy-loader.js

// Set up virtual rendering for drops lists - Now defined in lazy-loader.js
    
// Add event listeners to claim buttons in the pending section
document.querySelectorAll('.claim-drop-btn').forEach(button => {
    button.addEventListener('click', () => {
        const dropId = button.getAttribute('data-drop-id');
        claimDrop(dropId);
    });
});

// Claim a drop
function claimDrop(dropId) {
    // Visual feedback
    showToast('Claiming Drop', `Attempting to claim drop...`, 'info');
    
    // Call the API
    fetch(`/api/claim/${dropId}`, {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast('Success', data.message, 'success');
            // Refresh data after a short delay
            setTimeout(refreshData, 2000);
        } else {
            showToast('Error', data.message || 'Failed to claim drop', 'error');
        }
    })
    .catch(error => {
        console.error('Error claiming drop:', error);
        showToast('Error', 'Failed to claim drop. Check console for details.', 'error');
    });
}

// Update diagnostic UI with data
function updateDiagnosticUI(data) {
    // Update version
    const appVersion = document.getElementById('app-version');
    if (appVersion) appVersion.textContent = data.system_info.version || 'Unknown';
    
    // Update connection status
    const connectionDetail = document.getElementById('connection-detail');
    if (connectionDetail) {
        if (data.miner_state.session_active) {
            connectionDetail.innerHTML = '<span class="h-3 w-3 rounded-full bg-green-500 mr-2"></span>Connected';
        } else {
            connectionDetail.innerHTML = '<span class="h-3 w-3 rounded-full bg-red-500 mr-2"></span>Disconnected';
        }
    }
    
    // Update websocket status
    const websocketStatus = document.getElementById('websocket-status');
    if (websocketStatus) {
        if (data.miner_state.websocket_connected) {
            websocketStatus.innerHTML = '<span class="h-3 w-3 rounded-full bg-green-500 mr-2"></span>Connected';
        } else {
            websocketStatus.innerHTML = '<span class="h-3 w-3 rounded-full bg-red-500 mr-2"></span>Disconnected';
        }
    }
    
    // Update login status
    const loginStatus = document.getElementById('login-status');
    if (loginStatus) {
        if (data.miner_state.auth_valid) {
            loginStatus.innerHTML = '<span class="h-3 w-3 rounded-full bg-green-500 mr-2"></span>Logged In';
        } else {
            loginStatus.innerHTML = '<span class="h-3 w-3 rounded-full bg-red-500 mr-2"></span>Not Logged In';
        }
    }
    
    // Update stats
    const campaignsCount = document.getElementById('campaigns-count');
    if (campaignsCount) campaignsCount.textContent = data.stats.campaigns_count || 0;
    
    const channelsCount = document.getElementById('channels-count');
    if (channelsCount) channelsCount.textContent = data.stats.channels_count || 0;
    
    const dropsCount = document.getElementById('drops-count');
    if (dropsCount) dropsCount.textContent = data.stats.drops_count || 0;
}

// Toast notification system
function showToast(title, message, type = 'info') {
    // Create toast container if it doesn't exist
    let toastContainer = document.getElementById('toast-container');
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.id = 'toast-container';
        toastContainer.className = 'fixed top-4 right-4 z-50 flex flex-col gap-2';
        document.body.appendChild(toastContainer);
    }
    
    // Create toast
    const toast = document.createElement('div');
    toast.className = 'bg-white rounded shadow-lg border-l-4 p-4 max-w-sm transform transition-all duration-300 opacity-0 translate-x-full';
    
    // Set color based on type
    let bgColor = 'border-blue-500';
    let iconClass = 'fas fa-info-circle text-blue-500';
    
    if (type === 'success') {
        bgColor = 'border-green-500';
        iconClass = 'fas fa-check-circle text-green-500';
    } else if (type === 'error') {
        bgColor = 'border-red-500';
        iconClass = 'fas fa-exclamation-circle text-red-500';
    } else if (type === 'warning') {
        bgColor = 'border-yellow-500';
        iconClass = 'fas fa-exclamation-triangle text-yellow-500';
    }
    
    toast.classList.add(bgColor);
    
    // Add content
    toast.innerHTML = `
        <div class="flex items-start">
            <div class="flex-shrink-0">
                <i class="${iconClass} text-lg"></i>
            </div>
            <div class="ml-3 w-full">
                <div class="flex justify-between">
                    <p class="font-bold">${title}</p>
                    <button class="close-toast ml-4 text-gray-400 hover:text-gray-600">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
                <p class="text-sm text-gray-600 mt-1">${message}</p>
            </div>
        </div>
    `;
    
    // Add to container
    toastContainer.appendChild(toast);
    
    // Animate in
    setTimeout(() => {
        toast.classList.remove('opacity-0', 'translate-x-full');
    }, 10);
    
    // Add close handler
    toast.querySelector('.close-toast').addEventListener('click', () => {
        removeToast(toast);
    });
    
    // Auto remove after 5 seconds
    setTimeout(() => {
        removeToast(toast);
    }, 5000);
}

// Remove toast with animation
function removeToast(toast) {
    toast.classList.add('opacity-0', 'translate-x-full');
    setTimeout(() => {
        toast.remove();
    }, 300);
}

// Function to fetch settings
function fetchSettings() {
    return new Promise((resolve) => {
        fetch('/api/settings')
            .then(response => {
                if (!response.ok) {
                    throw new Error(`Settings API returned ${response.status}: ${response.statusText}`);
                }
                return response.json();
            })
            .then(data => {
                if (data.error) {
                    throw new Error(data.error);
                }
                
                // Update global settings object
                settingsData = data;
                
                // Update the UI with settings information
                updateSettingsUI(data);
                resolve(data);
            })
            .catch(error => {
                console.error('Error fetching settings:', error);
                showToast('Error', 'Failed to fetch settings. Check console for details.', 'error');
                resolve({ error: 'Failed to fetch settings' });
            });
    });
}

// Function to update settings UI
function updateSettingsUI(data) {
    // Update Priority Mode select
    const priorityModeSelect = document.getElementById('priority-mode');
    if (priorityModeSelect && data.priority_mode) {
        priorityModeSelect.value = data.priority_mode;
    }
    
    // Update Connection Quality select
    const connectionQualitySelect = document.getElementById('connection-quality');
    if (connectionQualitySelect && data.connection_quality) {
        connectionQualitySelect.value = data.connection_quality.toString();
    }
    
    // Update Language select
    const languageSelect = document.getElementById('language-select');
    if (languageSelect && data.language && data.available_languages) {
        // Clear existing options
        languageSelect.innerHTML = '';
        
        // Add available languages
        data.available_languages.forEach(lang => {
            const option = document.createElement('option');
            option.value = lang;
            option.textContent = lang;
            languageSelect.appendChild(option);
        });
        
        // Set current language
        languageSelect.value = data.language;
    }
    
    // Update proxy field
    const proxyInput = document.getElementById('proxy-input');
    if (proxyInput) {
        proxyInput.value = data.proxy || '';
    }
    
    // Update checkboxes
    const autostartCheckbox = document.getElementById('autostart-checkbox');
    if (autostartCheckbox) {
        // This is handled separately via registry, so we don't have this info
        // For now, leave it unchecked
        autostartCheckbox.checked = false;
        autostartCheckbox.disabled = true; // Disable it in web UI as it needs registry access
    }
    
    const startTrayCheckbox = document.getElementById('start-tray-checkbox');
    if (startTrayCheckbox && data.hasOwnProperty('autostart_tray')) {
        startTrayCheckbox.checked = data.autostart_tray;
    }
    
    const trayNotificationsCheckbox = document.getElementById('tray-notifications-checkbox');
    if (trayNotificationsCheckbox && data.hasOwnProperty('tray_notifications')) {
        trayNotificationsCheckbox.checked = data.tray_notifications;
    }
    
    // Update Priority List
    updatePriorityList(data.priority || []);
    
    // Update Exclusion List
    updateExclusionList(data.exclude || []);
    
    // Update game dropdowns
    updateGameSelectOptions(data.available_games || []);
}

// Function to update priority list in the UI
function updatePriorityList(priorityList) {
    const priorityListElement = document.getElementById('priority-list');
    if (!priorityListElement) return;
    
    priorityListElement.innerHTML = '';
    
    if (priorityList.length === 0) {
        const emptyItem = document.createElement('div');
        emptyItem.className = 'py-3 px-4 text-gray-500 italic';
        emptyItem.textContent = 'No priority games added yet';
        priorityListElement.appendChild(emptyItem);
        return;
    }
    
    priorityList.forEach((game, index) => {
        const item = document.createElement('div');
        item.className = 'py-3 px-4 flex items-center justify-between';
        
        const gameNameSpan = document.createElement('span');
        gameNameSpan.textContent = game;
        gameNameSpan.className = 'font-medium text-gray-900';
        
        const buttonGroup = document.createElement('div');
        buttonGroup.className = 'flex space-x-2';
        
        if (index > 0) {
            const upButton = document.createElement('button');
            upButton.innerHTML = '<i class="fas fa-arrow-up"></i>';
            upButton.className = 'text-gray-400 hover:text-gray-600';
            upButton.title = 'Move up';
            upButton.onclick = () => movePriorityItem(index, 1);
            buttonGroup.appendChild(upButton);
        }
        
        if (index < priorityList.length - 1) {
            const downButton = document.createElement('button');
            downButton.innerHTML = '<i class="fas fa-arrow-down"></i>';
            downButton.className = 'text-gray-400 hover:text-gray-600';
            downButton.title = 'Move down';
            downButton.onclick = () => movePriorityItem(index, -1);
            buttonGroup.appendChild(downButton);
        }
        
        const deleteButton = document.createElement('button');
        deleteButton.innerHTML = '<i class="fas fa-times"></i>';
        deleteButton.className = 'text-red-400 hover:text-red-600';
        deleteButton.title = 'Remove';
        deleteButton.onclick = () => removePriorityItem(index);
        buttonGroup.appendChild(deleteButton);
        
        item.appendChild(gameNameSpan);
        item.appendChild(buttonGroup);
        priorityListElement.appendChild(item);
    });
}

// Function to update exclusion list in the UI
function updateExclusionList(exclusionList) {
    const exclusionListElement = document.getElementById('exclusion-list');
    if (!exclusionListElement) return;
    
    exclusionListElement.innerHTML = '';
    
    if (exclusionList.length === 0) {
        const emptyItem = document.createElement('div');
        emptyItem.className = 'py-3 px-4 text-gray-500 italic';
        emptyItem.textContent = 'No excluded games added yet';
        exclusionListElement.appendChild(emptyItem);
        return;
    }
    
    exclusionList.forEach(game => {
        const item = document.createElement('div');
        item.className = 'py-3 px-4 flex items-center justify-between';
        
        const gameNameSpan = document.createElement('span');
        gameNameSpan.textContent = game;
        gameNameSpan.className = 'font-medium text-gray-900';
        
        const deleteButton = document.createElement('button');
        deleteButton.innerHTML = '<i class="fas fa-times"></i>';
        deleteButton.className = 'text-red-400 hover:text-red-600';
        deleteButton.title = 'Remove';
        deleteButton.onclick = () => removeExclusionItem(game);
        
        item.appendChild(gameNameSpan);
        item.appendChild(deleteButton);
        exclusionListElement.appendChild(item);
    });
}

// Function to update game selection dropdowns
function updateGameSelectOptions(games) {
    const prioritySelect = document.getElementById('game-select-priority');
    const excludeSelect = document.getElementById('game-select-exclude');
    
    if (!prioritySelect || !excludeSelect) return;
    
    // Sort games alphabetically
    games.sort();
    
    // Reset dropdowns
    prioritySelect.innerHTML = '';
    excludeSelect.innerHTML = '';
    
    // Add placeholder option
    const priorityPlaceholder = document.createElement('option');
    priorityPlaceholder.value = '';
    priorityPlaceholder.textContent = 'Select a game to add to priority';
    priorityPlaceholder.disabled = true;
    priorityPlaceholder.selected = true;
    prioritySelect.appendChild(priorityPlaceholder);
    
    const excludePlaceholder = document.createElement('option');
    excludePlaceholder.value = '';
    excludePlaceholder.textContent = 'Select a game to exclude';
    excludePlaceholder.disabled = true;
    excludePlaceholder.selected = true;
    excludeSelect.appendChild(excludePlaceholder);
    
    // Add game options
    games.forEach(game => {
        // For priority list
        const priorityOption = document.createElement('option');
        priorityOption.value = game;
        priorityOption.textContent = game;
        prioritySelect.appendChild(priorityOption);
        
        // For exclusion list
        const excludeOption = document.createElement('option');
        excludeOption.value = game;
        excludeOption.textContent = game;
        excludeSelect.appendChild(excludeOption);
    });
}

// Function to add a game to the priority list
function addPriorityGame() {
    const selectElement = document.getElementById('game-select-priority');
    if (!selectElement || !selectElement.value) return;
    
    const game = selectElement.value;
    
    // Reset selection
    selectElement.selectedIndex = 0;
    
    // Check if game is already in priority list
    if (settingsData.priority && settingsData.priority.includes(game)) {
        showToast('Info', 'This game is already in your priority list', 'info');
        return;
    }
    
    fetch('/api/settings/priority', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            action: 'add',
            game: game
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            settingsData.priority = data.priority;
            updatePriorityList(data.priority);
            showToast('Success', `Added ${game} to priority list`, 'success');
        } else {
            throw new Error(data.error || 'Failed to add game to priority list');
        }
    })
    .catch(error => {
        console.error('Error adding to priority list:', error);
        showToast('Error', error.message, 'error');
    });
}

// Function to remove a game from the priority list
function removePriorityItem(index) {
    fetch('/api/settings/priority', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            action: 'remove',
            index: index
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            settingsData.priority = data.priority;
            updatePriorityList(data.priority);
            showToast('Success', 'Removed game from priority list', 'success');
        } else {
            throw new Error(data.error || 'Failed to remove game from priority list');
        }
    })
    .catch(error => {
        console.error('Error removing from priority list:', error);
        showToast('Error', error.message, 'error');
    });
}

// Function to move an item in the priority list
function movePriorityItem(index, direction) {
    fetch('/api/settings/priority', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            action: 'move',
            index: index,
            direction: direction
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            settingsData.priority = data.priority;
            updatePriorityList(data.priority);
        } else {
            throw new Error(data.error || 'Failed to move game in priority list');
        }
    })
    .catch(error => {
        console.error('Error moving item in priority list:', error);
        showToast('Error', error.message, 'error');
    });
}

// Function to add a game to the exclusion list
function addExclusionGame() {
    const selectElement = document.getElementById('game-select-exclude');
    if (!selectElement || !selectElement.value) return;
    
    const game = selectElement.value;
    
    // Reset selection
    selectElement.selectedIndex = 0;
    
    // Check if game is already in exclusion list
    if (settingsData.exclude && settingsData.exclude.includes(game)) {
        showToast('Info', 'This game is already in your exclusion list', 'info');
        return;
    }
    
    fetch('/api/settings/exclude', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            action: 'add',
            game: game
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            settingsData.exclude = data.exclude;
            updateExclusionList(data.exclude);
            showToast('Success', `Added ${game} to exclusion list`, 'success');
        } else {
            throw new Error(data.error || 'Failed to add game to exclusion list');
        }
    })
    .catch(error => {
        console.error('Error adding to exclusion list:', error);
        showToast('Error', error.message, 'error');
    });
}

// Function to remove a game from the exclusion list
function removeExclusionItem(game) {
    fetch('/api/settings/exclude', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            action: 'remove',
            game: game
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            settingsData.exclude = data.exclude;
            updateExclusionList(data.exclude);
            showToast('Success', 'Removed game from exclusion list', 'success');
        } else {
            throw new Error(data.error || 'Failed to remove game from exclusion list');
        }
    })
    .catch(error => {
        console.error('Error removing from exclusion list:', error);
        showToast('Error', error.message, 'error');
    });
}

// Function to save all settings
function saveSettings(reloadAfterSave = false) {
    // Collect data from the form
    const settings = {
        priority_mode: document.getElementById('priority-mode').value,
        proxy: document.getElementById('proxy-input').value,
        language: document.getElementById('language-select').value,
        connection_quality: parseInt(document.getElementById('connection-quality').value, 10),
        autostart_tray: document.getElementById('start-tray-checkbox').checked,
        tray_notifications: document.getElementById('tray-notifications-checkbox').checked,
        reload: reloadAfterSave
    };
    
    // Send to the API
    fetch('/api/settings', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(settings)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast('Success', reloadAfterSave ? 'Settings saved and miner reloaded' : 'Settings saved successfully', 'success');
            
            // If we're reloading, refresh the data after a delay to reflect changes
            if (reloadAfterSave) {
                setTimeout(() => {
                    refreshData();
                }, 2000);
            }
        } else {
            throw new Error(data.error || 'Failed to save settings');
        }
    })
    .catch(error => {
        console.error('Error saving settings:', error);
        showToast('Error', error.message, 'error');
    });
}

// These functions are now moved to lazy-loader.js
// setupLazyLoading()
// setupVirtualRendering()
// setupDropsVirtualRendering()
// preloadData()
// preloadAllData()
// hasValidPreloadedData()
