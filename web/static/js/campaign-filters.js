/**
 * campaign-filters.js - Handles campaign filtering functionality
 * Similar to the GUI implementation, adds filters for Not linked, Upcoming, Expired, Excluded, and Finished campaigns
 */

// Use global variable set in global-exports.js
if (typeof window.originalCampaignsData === 'undefined') {
    window.originalCampaignsData = [];
}

// Initialize campaign filters
function initCampaignFilters() {
    // Get filter checkboxes
    const filterCheckboxes = document.querySelectorAll('.campaign-filter');
    if (!filterCheckboxes.length) return;
    
    // Add change event to each filter checkbox
    filterCheckboxes.forEach(checkbox => {
        checkbox.addEventListener('change', () => {
            applyCampaignFilters();
        });    });
    
    // Add refresh button event listener
    const refreshCampaignsButton = document.getElementById('refresh-campaigns');
    if (refreshCampaignsButton) {
        refreshCampaignsButton.addEventListener('click', () => {
            // Visual feedback for refresh
            const originalText = refreshCampaignsButton.innerHTML;
            refreshCampaignsButton.disabled = true;
            refreshCampaignsButton.innerHTML = '<i class="fas fa-sync fa-spin mr-1"></i> Refreshing...';
            
            // Save scroll position before refreshing
            if (window.saveCurrentScrollPosition) {
                window.saveCurrentScrollPosition();
            }            // Refresh campaigns data
            if (typeof window.fetchCampaigns !== 'function') {
                window.showToast('Error', 'Refresh functionality not available', 'error');
                refreshCampaignsButton.disabled = false;
                refreshCampaignsButton.innerHTML = originalText;
                return;
            }
            
            window.fetchCampaigns()
                .then(data => {
                    window.originalCampaignsData = [...data]; // Keep original data for filtering
                    applyCampaignFilters(); // Apply filters to the new data
                })                .catch(error => {
                    if (typeof window.showToast === 'function') {
                        window.showToast('Error', 'Failed to refresh campaigns', 'error');
                    }
                })
                .finally(() => {
                    // Reset the button
                    setTimeout(() => {
                        refreshCampaignsButton.disabled = false;
                        refreshCampaignsButton.innerHTML = originalText;
                    }, 500);
                });
        });
    }    
    // Campaign Filters initialized
}

// Apply campaign filters based on checkbox states
function applyCampaignFilters() {
    // If no campaigns data, nothing to filter
    if (!window.originalCampaignsData || !window.originalCampaignsData.length) return;
    // Get filter states
    const filterNotLinked = document.getElementById('filter-not-linked').checked;
    const filterUpcoming = document.getElementById('filter-upcoming').checked;
    const filterExpired = document.getElementById('filter-expired').checked;
    const filterExcluded = document.getElementById('filter-excluded').checked;
    const filterFinished = document.getElementById('filter-finished').checked;
      // Create a copy of the original data to filter
    let filteredData = [...window.originalCampaignsData];
    
    // Apply filters (similar to GUI implementation in InventoryOverview._update_visibility)
    filteredData = filteredData.filter(campaign => {
        // Filter by linked status
        if (!filterNotLinked && !(campaign.linked || campaign.eligible)) {
            return false;
        }
        
        // Filter by campaign status
        if (!(
            campaign.active || 
            (filterUpcoming && campaign.upcoming) || 
            (filterExpired && campaign.expired)
        )) {
            return false;
        }
        
        // Filter by exclusion status (check if game is in exclude list)
        // Since we don't have direct access to the exclude list in the frontend,
        // we'll use the 'excluded' property provided by the API
        if (!filterExcluded && campaign.excluded) {
            return false;
        }
        
        // Filter by finished status
        if (!filterFinished && campaign.finished) {
            return false;
        }
        
        return true;
    });
    
    // Update campaigns UI with filtered data
    if (typeof window.updateCampaignsUI === 'function') {
        window.updateCampaignsUI(filteredData);
    } 
    // If function not available, silently fail
}

// Override the global placeholder function
window.applyCampaignFilters = applyCampaignFilters;

// Add listener for tab changes to apply filters when switching to campaigns tab
function addTabChangeListener() {
    const tabButtons = document.querySelectorAll('.tab-button');
    tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            const tabId = button.id.replace('tab-btn-', '');
            if (tabId === 'campaigns' && typeof applyCampaignFilters === 'function') {
                // Small delay to ensure tab is fully visible
                setTimeout(() => {
                    applyCampaignFilters();
                }, 100);
            }
        });
    });
}

// Init on page load
document.addEventListener('DOMContentLoaded', () => {
    // Increased delay to ensure main.js has fully loaded and all functions are defined
    setTimeout(() => {
        initCampaignFilters();
        addTabChangeListener();
    }, 300);
});
