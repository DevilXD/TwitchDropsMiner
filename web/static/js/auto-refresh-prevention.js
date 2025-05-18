/**
 * auto-refresh-prevention.js - Prevent auto-refresh from affecting scroll positions
 * 
 * This module modifies the window focus/blur and visibility change handlers
 * to prevent automatic refreshing of campaigns and inventory tabs when returning to the page,
 * which helps avoid scroll position jumps.
 */

document.addEventListener('DOMContentLoaded', () => {
    /**
     * Override auto-refresh behaviors that could cause scroll jumping
     */
    function setupAutoRefreshPrevention() {
        try {
            // Store original setInterval to intercept auto-refresh calls
            const originalSetInterval = window.setInterval;
            
            // Replace setInterval to intercept any automatic refresh calls
            window.setInterval = function(callback, delay, ...args) {
                // Wrap the callback function to save scroll position before refreshing
                const wrappedCallback = function() {
                    // If this is a refresh call and we're on campaigns/inventory tab, save scroll position
                    if (window.currentTab === 'campaigns' || window.currentTab === 'inventory') {
                        if (window.saveCurrentScrollPosition) {
                            window.saveCurrentScrollPosition();
                        }
                    }
                    
                    // Call original callback function
                    return callback.apply(this, args);
                };
                
                // Forward to original setInterval with wrapped callback
                return originalSetInterval.call(this, wrappedCallback, delay, ...args);
            };
            
            // Handle focus events - prevent refreshing campaigns/inventory when window regains focus
            const originalOnFocus = window.onfocus;
            window.addEventListener('focus', () => {
                console.log('[Auto-Refresh Prevention] Window focus gained - preventing campaigns/inventory refresh');
                
                // Save current scroll position if needed
                if (window.saveCurrentScrollPosition && 
                   (window.currentTab === 'campaigns' || window.currentTab === 'inventory')) {
                    window.saveCurrentScrollPosition();
                }
                
                // If there was an originalOnFocus handler, call it
                if (typeof originalOnFocus === 'function') {
                    originalOnFocus.call(window);
                }
            });
            
            // Handle visibility change events
            document.addEventListener('visibilitychange', () => {
                if (document.visibilityState === 'visible') {
                    
                    // Save current scroll position if needed
                    if (window.saveCurrentScrollPosition && 
                       (window.currentTab === 'campaigns' || window.currentTab === 'inventory')) {
                        window.saveCurrentScrollPosition();
                    }
                }
            }, true);
            
        } catch (err) {
            console.error('[Auto-Refresh Prevention] Error during initialization:', err);
        }
    }
    
    // Execute the setup
    setupAutoRefreshPrevention();
    
    // Override the refreshData function (if it exists) to respect the current tab
    if (window.refreshData) {
        const originalRefreshData = window.refreshData;
        
        window.refreshData = function(options = {}) {
            // If we're on campaigns or inventory tab, prevent auto-refreshing those tabs
            // unless it's explicitly a manual refresh (detected by the manual-refresh.js module)
            if (!window.manualRefreshInProgress) {
                if (window.currentTab === 'campaigns') {
                    options.refreshCampaigns = false;
                }
                if (window.currentTab === 'inventory') {
                    options.refreshInventory = false;
                }
            }
            
            // Call the original function with our modified options
            return originalRefreshData.call(this, options);
        };
        
    } else {
        console.warn('[Auto-Refresh Prevention] Could not find refreshData function to override');
    }
});
