/**
 * manual-refresh.js - Handle manual refresh with scroll position preservation
 * Specifically focused on preserving scroll position during MANUAL refreshes only,
 * while removing auto-refresh scroll jumping behavior.
 */

// Override the manual refresh button handler to properly preserve scroll positions
document.addEventListener('DOMContentLoaded', () => {
    console.log('[Manual Refresh] Setting up manual refresh handlers');
    
    // Find all manual refresh buttons
    const manualRefreshButtons = document.querySelectorAll('#manual-refresh, #refresh-button');
    
    // We need to track when a manual refresh is in progress to distinguish from auto-refreshes
    window.manualRefreshInProgress = false;
    
    manualRefreshButtons.forEach(button => {
        // Get the button's original click handler if there is one
        const originalClickHandler = button.onclick;
        
        // Replace with our enhanced version
        button.onclick = function(event) {
            // Save the current state before refreshing
            const currentTab = window.currentTab;
            
            console.log(`[Manual Refresh] Manual refresh triggered on ${currentTab} tab`);
            window.manualRefreshInProgress = true;
            
            // Save scroll position if the function exists
            if (window.saveCurrentScrollPosition) {
                console.log(`[Manual Refresh] Saving scroll position for tab: ${currentTab}`);
                window.saveCurrentScrollPosition();
            } else {
                console.warn('[Manual Refresh] saveCurrentScrollPosition function not available');
            }
            
            // If there was an original handler, call it
            if (typeof originalClickHandler === 'function') {
                console.log('[Manual Refresh] Calling original click handler');
                originalClickHandler.call(this, event);
            }
            
            // Add restore functionality after refresh completes
            if ((currentTab === 'campaigns' || currentTab === 'inventory') && window.restoreScrollPosition) {
                // Create a listener for when the refresh operation completes (marked by progress bar hiding)
                const checkForRefreshCompletion = () => {
                    const progressContainer = document.getElementById('progress-container');
                    
                    // Function to create a MutationObserver to watch for when the progress bar is hidden
                    const watchProgressBar = () => {
                        // This will detect when the refresh is complete based on the progress bar being hidden
                        const observer = new MutationObserver((mutationsList) => {
                            for (const mutation of mutationsList) {
                                if (mutation.type === 'attributes' && mutation.attributeName === 'class') {
                                    if (!progressContainer.classList.contains('visible')) {
                                        observer.disconnect();
                                        // After refresh completes, restore position
                                        setTimeout(() => {
                                            console.log(`[Manual Refresh] Refreshing complete, restoring scroll for ${currentTab}`);
                                            window.restoreScrollPosition(currentTab);
                                            window.manualRefreshInProgress = false;
                                        }, 150);
                                    }
                                }
                            }
                        });
                        
                        observer.observe(progressContainer, { attributes: true });
                        
                        // Safety timeout - restore scroll after 5 seconds no matter what
                        setTimeout(() => {
                            observer.disconnect();
                            if (window.manualRefreshInProgress) {
                                console.log(`[Manual Refresh] Safety timeout reached, restoring scroll for ${currentTab}`);
                                window.restoreScrollPosition(currentTab);
                                window.manualRefreshInProgress = false;
                            }
                        }, 5000);
                    };
                    
                    if (progressContainer) {
                        watchProgressBar();
                    } else {
                        // If progress container isn't found, use a simpler timeout approach
                        setTimeout(() => {
                            console.log(`[Manual Refresh] No progress bar found, using timeout for ${currentTab}`);
                            window.restoreScrollPosition(currentTab);
                            window.manualRefreshInProgress = false;
                        }, 1500);
                    }
                };
                
                // Start watching for refresh completion
                checkForRefreshCompletion();
            } else {
                window.manualRefreshInProgress = false;
                console.warn(`[Manual Refresh] Can't restore scroll - tab: ${currentTab}, restoreScrollPosition available: ${!!window.restoreScrollPosition}`);
            }
        };
    });
    
    console.log('[Manual Refresh] Manual refresh handlers initialized');
});
