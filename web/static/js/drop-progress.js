/**
 * Drop Progress Handler
 * This file handles fetching and displaying accurate drop progress information
 * from the active_drop API endpoint
 */

// Poll interval (in milliseconds) for checking drop progress
const DROP_PROGRESS_POLL_INTERVAL = 30000; // 30 seconds
let dropProgressInterval = null;

// Initialize the drop progress poller
function initializeDropProgress() {
    // Start polling for active drop data
    fetchActiveDropData();
    
    // Set up interval for regular polling
    dropProgressInterval = setInterval(fetchActiveDropData, DROP_PROGRESS_POLL_INTERVAL);
    
    // Add resize handler for progress bars
    window.addEventListener('resize', adjustDropProgressLabels);
}

// Fetch data from the active_drop endpoint
function fetchActiveDropData() {
    // Skip if page is not visible to save resources
    if (document.hidden) {
        return;
    }
    
    fetch('/api/active_drop')
        .then(response => response.json())
        .then(data => {
            updateDropProgressUI(data);
        })        .catch(error => {
            // Silent error handling for active drop data fetch errors
        });
}

// Update the UI with drop progress data
function updateDropProgressUI(data) {
    // Exit if no drop data available
    if (!data || data.error || data.active_drop === null) {
        return;
    }
    
    // Update drop name
    const dropValue = document.getElementById('drop-value');
    if (dropValue) {
        dropValue.textContent = data.name || 'None';
    }
    
    // Update drop image
    updateDropImage(data.image_url);
    
    // Update the progress bar
    const progressBar = document.getElementById('drop-progress-bar');
    if (progressBar) {
        // Use the pre-calculated percentage if available
        const percent = data.progress_percentage || 0;
        
        // Apply the percentage to the progress bar
        progressBar.style.width = `${percent}%`;
        progressBar.textContent = `${percent}%`;
        
        // Make text visible even when bar is small
        if (percent < 15) {
            progressBar.classList.add('text-black');
            progressBar.classList.remove('text-white');
            // Position text at the end of the bar
            progressBar.style.textAlign = 'left';
            progressBar.style.paddingLeft = '5px';
        } else {
            progressBar.classList.add('text-white');
            progressBar.classList.remove('text-black');
            progressBar.style.textAlign = 'center';
            progressBar.style.paddingLeft = '0px';
        }
    }
    
    // Update the progress text separately to show fractions
    const progressText = document.getElementById('drop-progress-text');
    if (progressText) {
        progressText.textContent = `${data.current_minutes}/${data.required_minutes} minutes`;
    } else {
        // Create progress text element if it doesn't exist
        createProgressTextElement();
    }
    
    // Update time remaining
    const timeRemaining = document.getElementById('time-remaining');
    if (timeRemaining && data.remaining_minutes !== undefined) {
        timeRemaining.textContent = `Time remaining: ${data.remaining_minutes} minutes`;
    }
      // We've removed the timestamp display that showed "Updated X seconds ago (websocket)"
    const lastSyncElement = document.getElementById('last-drop-sync');
    if (lastSyncElement) {
        // Hide the element completely
        lastSyncElement.style.display = 'none';
    }
}

// Create progress text element if it doesn't exist
function createProgressTextElement() {
    // Find the progress container
    const progressContainer = document.getElementById('drop-progress-container');
    if (!progressContainer) return;
    
    // Create text element
    const progressText = document.createElement('div');
    progressText.id = 'drop-progress-text';
    progressText.className = 'text-sm mt-1 text-gray-600';
    progressContainer.appendChild(progressText);
    
    // We no longer create the last-sync element as we've removed the timestamp display
}

// Adjust progress bar labels based on available width
function adjustDropProgressLabels() {
    const progressBar = document.getElementById('drop-progress-bar');
    if (!progressBar) return;
    
    const percent = parseInt(progressBar.style.width, 10) || 0;
    const containerWidth = progressBar.parentElement?.offsetWidth || 0;
    
    // Adjust text position based on bar width
    if (percent < 15 || containerWidth * percent / 100 < 50) {
        progressBar.classList.add('text-black');
        progressBar.classList.remove('text-white');
        progressBar.style.textAlign = 'left';
        progressBar.style.paddingLeft = '5px'; 
    } else {
        progressBar.classList.add('text-white');
        progressBar.classList.remove('text-black');
        progressBar.style.textAlign = 'center';
        progressBar.style.paddingLeft = '0px';
    }
}

// Update the drop image
function updateDropImage(imageUrl) {
    const imageContainer = document.getElementById('drop-image-container');
    const dropImage = document.getElementById('drop-image');
    const fallbackIcon = document.getElementById('drop-image-fallback');
    
    if (imageUrl) {
        // Use the actual drop image
        dropImage.onload = function() {
            // Only show the image after it's loaded
            dropImage.classList.remove('hidden');
            fallbackIcon.classList.add('hidden');
            
            // Change the background color to better match the Twitch theme
            imageContainer.classList.remove('bg-green-600');
            imageContainer.classList.add('bg-purple-700');
            
            // Ensure proper sizing and centering of the image
            dropImage.style.width = '32px';
            dropImage.style.height = '32px';
        };
          dropImage.onerror = function() {
            // If image fails to load, show the fallback
            dropImage.classList.add('hidden');
            fallbackIcon.classList.remove('hidden');
            
            // Restore default green background
            imageContainer.classList.remove('bg-purple-700');
            imageContainer.classList.add('bg-green-600');
        };
        
        // Set the image source
        dropImage.src = imageUrl;
    } else {
        // Use the fallback gift icon
        dropImage.classList.add('hidden');
        fallbackIcon.classList.remove('hidden');
        
        // Use the default green background
        imageContainer.classList.remove('bg-purple-700');
        imageContainer.classList.add('bg-green-600');
    }
}

// Initialize when the DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    initializeDropProgress();
    
    // Also initialize on tab visibility change
    document.addEventListener('visibilitychange', function() {
        if (!document.hidden) {
            fetchActiveDropData();
        }
    });
      // Clean up on page unload
    window.addEventListener('beforeunload', function() {
        if (dropProgressInterval) {
            clearInterval(dropProgressInterval);
        }
    });
});
