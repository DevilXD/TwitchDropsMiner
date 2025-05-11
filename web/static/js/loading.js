function addLoadingIndicators() {
    // Find all cards and content containers that need loading indicators
    const containers = document.querySelectorAll('.bg-white.border.rounded.shadow');
    
    // Add loading indicators to each container
    containers.forEach(container => {
        // Only add if it doesn't already have one
        if (!container.querySelector('.loading-indicator')) {
            container.style.position = 'relative'; // Ensure proper positioning
            const loadingIndicator = document.createElement('div');
            loadingIndicator.className = 'loading-indicator';
            loadingIndicator.innerHTML = '<div class="loading-spinner"></div>';
            container.appendChild(loadingIndicator);
        }
    });
    
    // Add loading indicators to tables as well
    const tables = document.querySelectorAll('table');
    tables.forEach(table => {
        const tableParent = table.parentElement;
        if (tableParent && !tableParent.querySelector('.loading-indicator')) {
            tableParent.style.position = 'relative';
            const loadingIndicator = document.createElement('div');
            loadingIndicator.className = 'loading-indicator';
            loadingIndicator.innerHTML = '<div class="loading-spinner"></div>';
            tableParent.appendChild(loadingIndicator);
        }
    });
}
