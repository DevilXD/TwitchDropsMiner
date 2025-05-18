// Global exports file - Ensures all functions are available across script files

// Export key functions to global scope
window.preloadData = preloadData;
window.setupLazyLoading = setupLazyLoading;
window.setupVirtualRendering = setupVirtualRendering;
window.setupDropsVirtualRendering = setupDropsVirtualRendering;
window.createCampaignCard = createCampaignCard;
window.createDropCard = createDropCard;
window.fetchCampaigns = fetchCampaigns;
window.showToast = showToast;
window.updateCampaignsUI = updateCampaignsUI;

// Export campaign filter functions to make them available to other scripts
window.storeCampaignsData = function(data) {
    if (typeof window.originalCampaignsData === 'undefined') {
        window.originalCampaignsData = [];
    }
    if (data && Array.isArray(data)) {
        window.originalCampaignsData = [...data];
    }
    return data;
};

window.applyCampaignFilters = function() {
    // This function will be overridden by the real implementation in campaign-filters.js
    // This is just a placeholder to avoid errors if called before campaign-filters.js loads
    console.log('Campaign filters not yet loaded');
    return false;
};

// Make sure we don't overwrite existing exports
