// File: lazy-loader.js - Handles lazy loading of images and content
// This file contains utility functions for optimizing page performance

// Setup lazy loading for images
function setupLazyLoading() {
    // If Intersection Observer isn't supported, load all images immediately
    if (!('IntersectionObserver' in window)) {
        const lazyImages = document.querySelectorAll('.lazy-image');
        lazyImages.forEach(img => {
            if (img.dataset.src) {
                img.src = img.dataset.src;
            }
        });
        return;
    }

    const imageObserver = new IntersectionObserver((entries, observer) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const img = entry.target;
                img.src = img.dataset.src;
                img.classList.remove('lazy-image');
                imageObserver.unobserve(img);
            }
        });
    });

    const lazyImages = document.querySelectorAll('.lazy-image');
    lazyImages.forEach(img => {
        imageObserver.observe(img);
    });
}

// Scroll position management is now handled by scroll-position.js

// These functions are provided for backwards compatibility
// They will be overridden by the scroll-position.js implementations
function saveScrollPosition(tabId) {
    // This is now handled by scroll-position.js
    // Empty implementation for backward compatibility
}

function restoreScrollPosition(tabId) {
    // This is now handled by scroll-position.js
    // Empty implementation for backward compatibility
}

// This will be replaced by the implementation in scroll-position.js
function setupScrollTracking() {
    // Empty implementation for backward compatibility
}

// Preload data in the background
// Make preloadedData available globally for other scripts
window.preloadedData = {
    campaigns: null,
    inventory: null,
    channels: null,
    lastPreloadTime: {
        campaigns: 0,
        inventory: 0,
        channels: 0
    }
};

// For backwards compatibility
let preloadedData = window.preloadedData;

// Preload data for a specific type with cache invalidation
function preloadData(dataType) {
    const now = Date.now();
    const cacheTime = 60000; // 1 minute cache
    
    // If we have recently preloaded this data, don't do it again
    if (now - preloadedData.lastPreloadTime[dataType] < cacheTime) {
        return Promise.resolve(preloadedData[dataType]);
    }
    
    // Set loading state
    // We don't show the progress bar for preloading to avoid distracting the user
    
    let fetchPromise;
    switch (dataType) {
        case 'campaigns':
            fetchPromise = fetch('/api/campaigns')
                .then(response => response.ok ? response.json() : Promise.reject('Error'))
                .then(data => {
                    if (!data.error) {
                        preloadedData.campaigns = data;
                        preloadedData.lastPreloadTime.campaigns = now;
                    }
                    return data;
                });
            break;
        case 'inventory':
            fetchPromise = fetch('/api/inventory')
                .then(response => response.ok ? response.json() : Promise.reject('Error'))
                .then(data => {
                    if (!data.error) {
                        preloadedData.inventory = data;
                        preloadedData.lastPreloadTime.inventory = now;
                    }
                    return data;
                });
            break;
        case 'channels':
            fetchPromise = fetch('/api/channels')
                .then(response => response.ok ? response.json() : Promise.reject('Error'))
                .then(data => {
                    if (!data.error) {
                        preloadedData.channels = data;
                        preloadedData.lastPreloadTime.channels = now;
                    }
                    return data;
                });
            break;
        default:
            return Promise.reject('Invalid data type');
    }
      return fetchPromise.catch(error => {
        // Failed to preload data, silently handle error
        return null;
    });
}

// Preload all data types in the background
function preloadAllData() {
    // Stagger the preloads to avoid overloading the server
    setTimeout(() => preloadData('campaigns'), 500);
    setTimeout(() => preloadData('inventory'), 1000);
    setTimeout(() => preloadData('channels'), 1500);
}

// Check if we have valid preloaded data - make it globally available
function hasValidPreloadedData(dataType) {
    const now = Date.now();
    const cacheTime = 60000; // 1 minute cache
    return preloadedData[dataType] && (now - preloadedData.lastPreloadTime[dataType] < cacheTime);
}

// Make this function available globally for other scripts
window.hasValidPreloadedData = hasValidPreloadedData;

// Get preloaded data if available, otherwise fetch it
function getDataWithPreload(dataType, fetchFunction) {
    if (hasValidPreloadedData(dataType)) {
        // Using preloaded data
        return Promise.resolve(preloadedData[dataType]);
    } else {
        return fetchFunction().then(data => {
            preloadedData[dataType] = data;
            preloadedData.lastPreloadTime[dataType] = Date.now();
            return data;
        });
    }
}

// Set up virtual rendering for campaigns list
// Helper function to create a campaign card - moved from main.js
function createCampaignCard(campaign) {
    const statusClass = campaign.status === 'ACTIVE' ? 'bg-green-100 border-green-500' : 'bg-gray-100 border-gray-400';
    const statusText = campaign.status === 'ACTIVE' ? 'Active' : 'Inactive';
    const statusTextColor = campaign.status === 'ACTIVE' ? 'text-green-800' : 'text-gray-600';
    
    const campaignCard = document.createElement('div');
    campaignCard.className = 'col-span-1 p-3 bg-white rounded shadow border-l-4 ' + statusClass;
    
    // Use data placeholder for images that will be lazy loaded
    const imageHtml = campaign.image_url ? 
        `<div class="mr-2 flex-shrink-0">
            <img data-src="${campaign.image_url}" alt="${campaign.name}" class="w-12 h-12 object-cover rounded lazy-image" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'%3E%3C/svg%3E">
         </div>` : 
        '';
    
    campaignCard.innerHTML = `
        <div class="flex items-center">
            ${imageHtml}
            <div class="flex-grow">
                <div class="flex justify-between items-start">
                    <div>
                        <h3 class="font-bold text-base text-gray-800">${campaign.name}</h3>
                        <p class="text-gray-600 text-xs">${campaign.game || 'No game specified'}</p>
                    </div>
                    <span class="px-1.5 py-0.5 rounded text-xs font-semibold ${statusTextColor} bg-opacity-50">${statusText}</span>
                </div>
                <div class="mt-2 text-xs">
                    <p><span class="text-gray-600">Drops:</span> <span class="font-semibold">${campaign.drops_count}</span></p>
                    ${campaign.start_time ? `<p><span class="text-gray-600">Start:</span> ${new Date(campaign.start_time).toLocaleDateString()}</p>` : ''}
                    ${campaign.end_time ? `<p><span class="text-gray-600">End:</span> ${new Date(campaign.end_time).toLocaleDateString()}</p>` : ''}
                </div>
            </div>
        </div>
    `;
    
    return campaignCard;
}

function setupVirtualRendering(container, data, startIndex) {
    // Create a sentinel element that will trigger loading more campaigns when it becomes visible
    const sentinel = document.createElement('div');
    sentinel.className = 'virtual-sentinel';
    sentinel.style.height = '1px';
    sentinel.style.width = '100%';
    container.appendChild(sentinel);
    
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                // Load more items
                const fragment = document.createDocumentFragment();
                const batchSize = 20; // Number of items to load at once
                const endIndex = Math.min(startIndex + batchSize, data.length);
                
                for (let i = startIndex; i < endIndex; i++) {
                    const campaign = data[i];
                    const card = createCampaignCard(campaign);
                    fragment.appendChild(card);
                }
                
                // Remove sentinel before appending
                sentinel.remove();
                
                // Append new campaigns before the sentinel
                container.appendChild(fragment);
                
                // If there are more campaigns, add sentinel again and update startIndex
                if (endIndex < data.length) {
                    container.appendChild(sentinel);
                    setupLazyLoading(); // Setup lazy loading for newly added images
                    startIndex = endIndex;
                } else {
                    // Disconnect the observer when all campaigns are loaded
                    observer.disconnect();
                }
            }
        });
    }, { rootMargin: '200px' }); // Start loading more content when sentinel is 200px away from viewport
    
    observer.observe(sentinel);
}

// Set up virtual rendering for drops lists
// Helper function to create a drop card
function createDropCard(drop, type) {
    const dropCard = document.createElement('div');
    
    if (type === 'pending') {
        dropCard.className = 'bg-white rounded shadow mb-4 overflow-hidden';
        
        // Calculate progress
        const progress = drop.current_minutes / drop.required_minutes;
        const percent = Math.round(progress * 100);
        const isReady = drop.current_minutes >= drop.required_minutes;
        const statusClass = isReady ? 'bg-green-100 border-green-500' : 'bg-blue-100 border-blue-500';
        const actionButton = isReady ? 
            `<button class="claim-drop-btn bg-green-500 hover:bg-green-600 text-white py-1 px-3 rounded text-sm" data-drop-id="${drop.id}">
                <i class="fas fa-gift mr-1"></i> Claim Now
            </button>` : 
            '';
        
        const imageHtml = drop.image_url ? 
            `<div class="mr-3 flex-shrink-0">
                <img data-src="${drop.image_url}" alt="${drop.name}" class="w-16 h-16 object-cover rounded lazy-image" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'%3E%3C/svg%3E">
            </div>` : 
            '';
        
        dropCard.innerHTML = `
            <div class="border-l-4 ${statusClass} p-4">
                <div class="flex items-center mb-2">
                    ${imageHtml}
                    <div class="flex-grow">
                        <div class="flex justify-between items-start w-full">
                            <div>
                                <h3 class="font-bold text-lg text-gray-800">${drop.name}</h3>
                                <p class="text-gray-600">${drop.game || 'Unknown Game'}</p>
                            </div>
                            <div>
                                ${actionButton}
                            </div>
                        </div>
                        <div class="mt-3">
                            <div class="shadow w-full bg-gray-200 rounded">
                                <div class="bg-purple-600 text-xs leading-none py-1 text-center text-white rounded" style="width: ${percent}%">${percent}%</div>
                            </div>
                            <p class="mt-1 text-sm text-gray-500">${drop.current_minutes}/${drop.required_minutes} minutes watched</p>
                        </div>
                    </div>
                </div>
            </div>
        `;
    } else {
        dropCard.className = 'bg-green-50 rounded shadow mb-4 border-l-4 border-green-500 p-4';
        
        // Use the same claimed status badge for all drops in this section
        const statusBadge = '<span class="px-2 py-1 rounded text-xs font-semibold bg-green-100 text-green-800">Claimed</span>';
        
        // For auto-moved drops, show completion status; for actually claimed drops, show claim time
        const timeInfo = drop.autoMoved ?
            `<p class="mt-2 text-sm text-gray-500">100% Complete</p>` :
            (drop.claim_time ? `<p class="mt-2 text-sm text-gray-500">Claimed on ${new Date(drop.claim_time).toLocaleString()}</p>` : '');
        
        const imageHtml = drop.image_url ? 
            `<div class="mr-3 flex-shrink-0">
                <img data-src="${drop.image_url}" alt="${drop.name}" class="w-16 h-16 object-cover rounded lazy-image" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'%3E%3C/svg%3E">
            </div>` : 
            '';
        
        dropCard.innerHTML = `
            <div class="flex items-center">
                ${imageHtml}
                <div class="flex-grow">
                    <div class="flex justify-between items-start w-full">
                        <div>
                            <h3 class="font-bold text-lg text-gray-800">${drop.name}</h3>
                            <p class="text-gray-600">${drop.game || 'Unknown Game'}</p>
                        </div>
                        ${statusBadge}
                    </div>
                    ${timeInfo}
                </div>
            </div>
        `;
    }
    
    return dropCard;
}

function setupDropsVirtualRendering(container, items, startIndex, type) {
    // Create a sentinel element that will trigger loading more items when it becomes visible
    const sentinel = document.createElement('div');
    sentinel.className = 'virtual-sentinel';
    sentinel.style.height = '1px';
    sentinel.style.width = '100%';
    container.appendChild(sentinel);
    
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                // Load more items
                const fragment = document.createDocumentFragment();
                const batchSize = 10; // Number of items to load at once
                const endIndex = Math.min(startIndex + batchSize, items.length);
                
                for (let i = startIndex; i < endIndex; i++) {
                    const drop = items[i];
                    const dropCard = createDropCard(drop, type);
                    fragment.appendChild(dropCard);
                }
                
                // Remove sentinel before appending
                sentinel.remove();
                
                // Append new items before the sentinel
                container.appendChild(fragment);
                
                // If there are more items, add sentinel again and update startIndex
                if (endIndex < items.length) {
                    container.appendChild(sentinel);
                    setupLazyLoading(); // Setup lazy loading for newly added images
                    startIndex = endIndex;
                } else {
                    // Disconnect the observer when all items are loaded
                    observer.disconnect();
                }
            }
        });
    }, { rootMargin: '200px' }); // Start loading more content when sentinel is 200px away from viewport
    
    observer.observe(sentinel);
}
