/**
 * Responsive header enhancements for TwitchDropsMiner
 */

document.addEventListener('DOMContentLoaded', function() {
    // On small screens, we'll create a mobile menu toggle
    setupMobileHeaderToggle();
    
    // Handle window resize events to adjust display
    window.addEventListener('resize', handleWindowResize);
    
    // Initial check
    handleWindowResize();
});

function setupMobileHeaderToggle() {
    const header = document.getElementById('header');
    
    // Only proceed if we have the header
    if (!header) return;
    
    // Get the controls container
    const headerControls = header.querySelector('.header-controls');
    
    // Only proceed if we have the controls container
    if (!headerControls) return;
    
    // On small screens, we may need to collapse some items
    const headerControlItems = headerControls.children;
    
    // Create a responsive classes map for different screen sizes
    const responsiveClasses = {
        'xs': { show: [], hide: [2, 3] },  // Hide last refresh and some buttons on extra small screens
        'sm': { show: [], hide: [2] },     // Hide last refresh on small screens
        'md': { show: [2, 3], hide: [] },  // Show everything on medium and up
    };
    
    // Apply initial responsive classes based on screen width
    applyResponsiveClasses(headerControlItems, responsiveClasses);
}

function handleWindowResize() {
    const header = document.getElementById('header');
    if (!header) return;
    
    const headerControls = header.querySelector('.header-controls');
    if (!headerControls) return;
    
    // Get all control items
    const headerControlItems = headerControls.children;
    
    // Create a responsive classes map for different screen sizes
    const responsiveClasses = {
        'xs': { show: [], hide: [2] },     // Hide last refresh on extra small screens
        'sm': { show: [], hide: [] },      // Show everything on small and up
        'md': { show: [2], hide: [] },     // Explicitly show last refresh on medium and up
    };
    
    // Apply responsive classes based on current screen width
    applyResponsiveClasses(headerControlItems, responsiveClasses);
}

function applyResponsiveClasses(elements, classesMap) {
    // Get current screen size
    const width = window.innerWidth;
    let currentSize = 'xs';
    
    if (width >= 1024) {
        currentSize = 'lg';
    } else if (width >= 768) {
        currentSize = 'md';
    } else if (width >= 640) {
        currentSize = 'sm';
    }
    
    // Apply classes based on current size
    // Start from xs and apply all applicable rules up to current size
    const sizes = ['xs', 'sm', 'md', 'lg'];
    const applicableSizes = sizes.slice(0, sizes.indexOf(currentSize) + 1);
    
    let itemsToShow = [];
    let itemsToHide = [];
    
    // Collect all items to show/hide
    applicableSizes.forEach(size => {
        if (classesMap[size]) {
            if (classesMap[size].show) {
                itemsToShow = [...itemsToShow, ...classesMap[size].show];
            }
            if (classesMap[size].hide) {
                itemsToHide = [...itemsToHide, ...classesMap[size].hide];
            }
        }
    });
    
    // Remove duplicates and resolve conflicts (show takes precedence over hide)
    itemsToHide = itemsToHide.filter(item => !itemsToShow.includes(item));
    
    // Apply visibility
    Array.from(elements).forEach((element, index) => {
        if (itemsToHide.includes(index)) {
            element.classList.add('hidden');
            element.classList.remove('block');
        } else {
            element.classList.remove('hidden');
            element.classList.add('block');
        }
    });
}
