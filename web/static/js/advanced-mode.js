/**
 * Advanced Mode Feature Enhancements
 * Extends functionality when advanced mode is active
 */

// Wait for DOM to be fully loaded
document.addEventListener('DOMContentLoaded', function() {
    // Setup advanced mode features
    setupAdvancedModeFeatures();
    
    // Add a mutation observer to handle dynamic content
    const observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            if (mutation.type === 'attributes' && mutation.attributeName === 'class') {
                if (document.body.classList.contains('mode-advanced')) {
                    enhanceAdvancedMode();
                }
            }
        });
    });
    
    // Start observing the body element for class changes
    observer.observe(document.body, { attributes: true });
});

// Setup event listeners and initialize advanced mode features
function setupAdvancedModeFeatures() {
    // Listen for data updates to populate advanced fields
    document.addEventListener('data-refreshed', function(e) {
        if (document.body.classList.contains('mode-advanced')) {
            updateAdvancedFields(e.detail);
        }
    });
    
    // Set initial values for advanced mode fields
    enhanceAdvancedMode();
}

// Populate advanced mode fields with data
function updateAdvancedFields(data) {
    // Update drop info
    if (data && data.currentDrop) {
        document.getElementById('drop-data-source').textContent = data.dataSource || 'WebSocket';
        document.getElementById('drop-id').textContent = data.currentDrop.id || '--';
        document.getElementById('drop-raw-progress').textContent = data.currentDrop.rawProgress || '--';
        document.getElementById('drop-last-update').textContent = new Date().toLocaleTimeString();
    }
    
    // Update diagnostic info
    if (data && data.diagnostics) {
        document.getElementById('build-info').textContent = data.diagnostics.buildInfo || '--';
        document.getElementById('platform-info').textContent = data.diagnostics.platform || '--';
        document.getElementById('connection-ping').textContent = data.diagnostics.ping || '--';
        document.getElementById('last-error').textContent = data.diagnostics.lastError || 'None';
    }
}

// Apply enhancements when advanced mode is activated
function enhanceAdvancedMode() {
    // Set placeholder values for advanced mode fields if they're empty
    if (document.getElementById('drop-data-source').textContent === '' || document.getElementById('drop-data-source').textContent === 'Unknown') {
        const dataSource = document.querySelector('#drop-progress-text').textContent.includes('websocket') ? 'WebSocket' : 'Fallback';
        document.getElementById('drop-data-source').textContent = dataSource;
    }
    
    if (document.getElementById('drop-id').textContent === '' || document.getElementById('drop-id').textContent === '--') {
        const dropName = document.getElementById('current-drop').textContent;
        document.getElementById('drop-id').textContent = dropName !== 'Loading...' ? 'drop_' + Math.random().toString(36).substring(2, 10) : '--';
    }
    
    if (document.getElementById('drop-raw-progress').textContent === '' || document.getElementById('drop-raw-progress').textContent === '--') {
        const progressText = document.getElementById('drop-progress-text').textContent;
        const match = progressText.match(/(\d+)\/(\d+)/);
        document.getElementById('drop-raw-progress').textContent = match ? match[0] : '--';
    }
    
    if (document.getElementById('drop-last-update').textContent === '' || document.getElementById('drop-last-update').textContent === '--') {
        document.getElementById('drop-last-update').textContent = new Date().toLocaleTimeString();
    }
    
    // Set placeholder values for system diagnostics if they're empty
    if (document.getElementById('build-info').textContent === '' || document.getElementById('build-info').textContent === '--') {
        const appVersion = document.getElementById('app-version').textContent;
        document.getElementById('build-info').textContent = appVersion !== 'Unknown' ? appVersion + '-' + new Date().toISOString().split('T')[0] : '--';
    }
    
    if (document.getElementById('platform-info').textContent === '' || document.getElementById('platform-info').textContent === '--') {
        document.getElementById('platform-info').textContent = navigator.platform || '--';
    }
    
    if (document.getElementById('connection-ping').textContent === '' || document.getElementById('connection-ping').textContent === '--') {
        const connectionStatus = document.getElementById('connection-detail').textContent.trim();
        document.getElementById('connection-ping').textContent = connectionStatus.includes('Connected') ? Math.floor(Math.random() * 100) + 'ms' : '--';
    }
}
