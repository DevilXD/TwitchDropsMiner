/**
 * scroll-position.js 
 * Preserves scroll position when refreshing campaigns and inventory tabs
 * Prevents listings from jumping to the top on refresh
 */

// Store scroll positions both in memory and localStorage
const STORAGE_KEY_PREFIX = 'twitch-drops-miner';
let scrollPositions = {
    campaigns: 0,
    inventory: 0
};

// Expose functions to global scope for use by other scripts
window.saveCurrentScrollPosition = saveCurrentScrollPosition;
window.restoreScrollPosition = restoreScrollPosition;

// Initialize - load saved positions from localStorage
(function loadSavedPositions() {
    try {
        const campaignsPos = localStorage.getItem(`${STORAGE_KEY_PREFIX}-campaigns-scroll`);
        const inventoryPos = localStorage.getItem(`${STORAGE_KEY_PREFIX}-inventory-scroll`);
        
        if (campaignsPos) {
            scrollPositions.campaigns = parseInt(campaignsPos, 10);
        }
        if (inventoryPos) {
            scrollPositions.inventory = parseInt(inventoryPos, 10);
        }
          // Loaded saved positions
    } catch (err) {
        // Error loading saved positions
    }
})();

/**
 * Get the scrollable container for a specific tab
 */
function getScrollContainer(tabId) {
    if (!tabId) return null;
    
    try {
        if (tabId === 'campaigns') {
            const list = document.getElementById('campaigns-list');
            return list?.closest('.overflow-y-auto') || null;
        } else if (tabId === 'inventory') {
            const tab = document.getElementById('inventory-tab');
            return tab?.querySelector('.overflow-y-auto') || null;
        }    } catch (err) {
        // Error getting container for tab
    }
    
    return null;
}

/**
 * Save scroll position for the current tab
 */
function saveCurrentScrollPosition() {
    try {
        const currentTabId = window.currentTab;
        if (currentTabId !== 'campaigns' && currentTabId !== 'inventory') return;
        
        const container = getScrollContainer(currentTabId);
        if (!container) return;
        
        // Only save if the scroll position actually changed
        const currentPos = container.scrollTop;
        if (scrollPositions[currentTabId] !== currentPos) {            scrollPositions[currentTabId] = currentPos;
            localStorage.setItem(`${STORAGE_KEY_PREFIX}-${currentTabId}-scroll`, currentPos.toString());
            // Saved scroll position
        }
    } catch (err) {
        // Error saving scroll position
    }
}

/**
 * Restore scroll position for a tab
 */
function restoreScrollPosition(tabId) {
    if (!tabId || (tabId !== 'campaigns' && tabId !== 'inventory')) return;
    
    try {
        const container = getScrollContainer(tabId);
        if (!container) return;
        
        const savedPos = scrollPositions[tabId];
        if (savedPos > 0) {
            // Use a single attempt to restore scroll position to prevent excessive updates
            setTimeout(() => {                container.scrollTop = savedPos;
                // Restored scroll position
            }, 100);
        }
    } catch (err) {
        // Error restoring scroll position
    }
}

/**
 * Set up scroll position tracking
 */
function setupScrollTracking() {
    try {
        // Save scroll position before page unload/refresh
        window.addEventListener('beforeunload', saveCurrentScrollPosition);
        
        // Track tab changes to restore scroll position
        const originalSetupTabNavigation = window.setupTabNavigation;
        if (originalSetupTabNavigation) {
            window.setupTabNavigation = function() {
                // Call original first
                originalSetupTabNavigation();
                
                // Add our scroll tracking
                const tabButtons = document.querySelectorAll('.tab-button');
                tabButtons.forEach(button => {
                    button.addEventListener('click', () => {
                        const prevTab = window.currentTab;
                        const newTab = button.id.replace('tab-btn-', '');
                        
                        // Save position for the tab we're leaving
                        if (prevTab === 'campaigns' || prevTab === 'inventory') {
                            saveCurrentScrollPosition();
                        }
                        
                        // Restore position for the tab we're switching to
                        if (newTab === 'campaigns' || newTab === 'inventory') {
                            restoreScrollPosition(newTab);
                        }
                    });
                });
            };
        }
          // Store scroll position before any content updates
        // but don't auto-restore (which could cause scroll jumping)
        if (window.updateCampaignsUI) {
            const originalUpdateCampaigns = window.updateCampaignsUI;
            window.updateCampaignsUI = function(...args) {
                // Save current position if we're on the campaigns tab
                if (window.currentTab === 'campaigns') {
                    saveCurrentScrollPosition();
                }
                
                // Call original function
                originalUpdateCampaigns.apply(this, args);
            };
        }
        
        if (window.updateInventoryUI) {
            const originalUpdateInventory = window.updateInventoryUI;
            window.updateInventoryUI = function(...args) {
                // Save current position if we're on the inventory tab
                if (window.currentTab === 'inventory') {
                    saveCurrentScrollPosition();
                }
                
                // Call original function
                originalUpdateInventory.apply(this, args);
            };
        }
          // Override the manual refresh button functionality to preserve scroll position
        // Find the manual refresh button and add our custom scroll position handling
        const manualRefreshBtn = document.getElementById('manual-refresh');
        if (manualRefreshBtn) {
            const originalClickHandler = manualRefreshBtn.onclick;
            manualRefreshBtn.onclick = function(event) {
                // Save scroll position before manual refresh
                saveCurrentScrollPosition();
                
                // If there was an original handler, call it
                if (typeof originalClickHandler === 'function') {
                    originalClickHandler.call(this, event);
                } else {
                    // Default refresh behavior if no handler exists
                    refreshData({
                        showLoader: true,
                        refreshChannels: true,
                        refreshCampaigns: true,
                        refreshInventory: true,
                        refreshSettings: true,
                        refreshLogin: true
                    });
                }
            };
        }
        
        // Only save scroll position on user-initiated actions
        // Add scroll event listeners to containers - but don't auto-restore
        const scrollThrottleTime = 300; // ms
        let scrollTimer;
        
        document.addEventListener('scroll', () => {
            if (scrollTimer) return;
            
            scrollTimer = setTimeout(() => {
                saveCurrentScrollPosition();
                scrollTimer = null;
            }, scrollThrottleTime);
        }, { capture: true, passive: true });
        
        // Initial restore on page load
        window.addEventListener('load', () => {
            // One-time restore on initial load
            setTimeout(() => {
                const tab = window.currentTab;
                if (tab === 'campaigns' || tab === 'inventory') {
                    restoreScrollPosition(tab);
                }
            }, 300);
        });        
        // Position tracking initialized
    } catch (err) {
        // Error setting up scroll tracking
    }
}
