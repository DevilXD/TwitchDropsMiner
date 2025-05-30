/**
 * Mode Switcher functionality for Twitch Drops Miner
 */

class ModeSwitcher {
    constructor() {
        this.init();
    }

    init() {
        // Add event listener for mode switch button
        const modeSwitchBtn = document.getElementById('mode-switch-btn');
        if (modeSwitchBtn) {
            modeSwitchBtn.addEventListener('click', () => this.showModeSwitchDialog());
        }
    }

    showModeSwitchDialog() {
        // Create a modal for mode selection
        const modal = document.createElement('div');
        modal.className = 'fixed inset-0 flex items-center justify-center z-50 bg-black bg-opacity-50';
        modal.id = 'mode-switch-modal';

        // Create modal content
        const modalContent = document.createElement('div');
        modalContent.className = 'bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-md w-full';
        
        // Add heading
        const heading = document.createElement('h2');
        heading.className = 'text-xl font-bold mb-4 text-gray-800 dark:text-gray-200';
        heading.textContent = 'Switch Application Mode';
        
        // Add description
        const description = document.createElement('p');
        description.className = 'mb-4 text-gray-600 dark:text-gray-300';
        description.textContent = 'Select the application mode you want to use:';
        
        // Create mode options
        const modeOptions = document.createElement('div');
        modeOptions.className = 'flex flex-col space-y-3 mb-6';
        
        // Define available modes
        const modes = [
            { id: 'web', name: 'Web Mode', icon: 'fa-globe', desc: 'Access via web browser' },
            { id: 'gui', name: 'GUI Mode', icon: 'fa-desktop', desc: 'Native desktop interface' },
            { id: 'tray', name: 'Tray Mode', icon: 'fa-chevron-circle-down', desc: 'Run minimized in system tray' },
            { id: 'headless', name: 'Headless Mode', icon: 'fa-terminal', desc: 'Run with no interface' }
        ];
        
        // Create mode option buttons
        modes.forEach(mode => {
            const option = document.createElement('button');
            option.className = 'flex items-center p-3 border rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors';
            option.dataset.mode = mode.id;
            
            const iconContainer = document.createElement('div');
            iconContainer.className = 'w-10 h-10 rounded-full bg-purple-600 flex items-center justify-center text-white mr-4';
            iconContainer.innerHTML = `<i class="fas ${mode.icon}"></i>`;
            
            const textContainer = document.createElement('div');
            textContainer.className = 'flex-1';
            textContainer.innerHTML = `
                <div class="font-semibold text-gray-800 dark:text-gray-200">${mode.name}</div>
                <div class="text-sm text-gray-600 dark:text-gray-400">${mode.desc}</div>
            `;
            
            option.appendChild(iconContainer);
            option.appendChild(textContainer);
            option.addEventListener('click', () => this.switchMode(mode.id, modal));
            
            modeOptions.appendChild(option);
        });
        
        // Add cancel button
        const cancelButton = document.createElement('button');
        cancelButton.className = 'w-full py-2 bg-gray-200 dark:bg-gray-700 text-gray-800 dark:text-gray-200 rounded-lg hover:bg-gray-300 dark:hover:bg-gray-600 transition-colors';
        cancelButton.textContent = 'Cancel';
        cancelButton.addEventListener('click', () => {
            document.body.removeChild(modal);
        });
        
        // Assemble modal content
        modalContent.appendChild(heading);
        modalContent.appendChild(description);
        modalContent.appendChild(modeOptions);
        modalContent.appendChild(cancelButton);
        modal.appendChild(modalContent);
        
        // Append modal to body
        document.body.appendChild(modal);
        
        // Close modal on background click
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                document.body.removeChild(modal);
            }
        });
    }
    
    switchMode(modeId, modal) {
        // Remove the modal
        if (modal && document.body.contains(modal)) {
            document.body.removeChild(modal);
        }
        
        // Show loading indicator
        const loadingModal = document.createElement('div');
        loadingModal.className = 'fixed inset-0 flex items-center justify-center z-50 bg-black bg-opacity-50';
        
        const loadingContent = document.createElement('div');
        loadingContent.className = 'bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 text-center';
        loadingContent.innerHTML = `
            <div class="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-purple-600 mx-auto mb-4"></div>
            <div class="text-lg text-gray-800 dark:text-gray-200">Switching to ${modeId} mode...</div>
            <div class="text-sm text-gray-600 dark:text-gray-400 mt-2">This may take a moment</div>
        `;
        
        loadingModal.appendChild(loadingContent);
        document.body.appendChild(loadingModal);
          // Make API request to switch mode
        fetch('/api/switch_mode', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...getAuthHeaders()
            },
            body: JSON.stringify({ mode: modeId })
        })
        .then(response => response.json())
        .then(data => {
            // Remove loading indicator
            document.body.removeChild(loadingModal);
            
            if (data.success) {
                if (data.redirect) {
                    // If we need to redirect to a new URL
                    window.location.href = data.redirect;
                } else {
                    // Show success message
                    this.showNotification(`Successfully switched to ${modeId} mode`, 'success');
                    
                    // Reload the page after a short delay
                    setTimeout(() => {
                        window.location.reload();
                    }, 1500);
                }
            } else {
                // Show error message
                this.showNotification(data.message || 'Failed to switch mode', 'error');
            }
        })
        .catch(error => {
            // Remove loading indicator
            document.body.removeChild(loadingModal);
            
            // Show error message
            this.showNotification('Error switching mode: ' + error.message, 'error');
        });
    }
    
    showNotification(message, type = 'info') {
        // Create notification element
        const notification = document.createElement('div');
        notification.className = `fixed top-4 right-4 p-4 rounded-lg shadow-lg z-50 transition-opacity duration-500 ${
            type === 'success' ? 'bg-green-600 text-white' : 
            type === 'error' ? 'bg-red-600 text-white' : 
            'bg-blue-600 text-white'
        }`;
        notification.textContent = message;
        
        // Add to document
        document.body.appendChild(notification);
        
        // Remove after delay
        setTimeout(() => {
            notification.style.opacity = '0';
            setTimeout(() => {
                if (document.body.contains(notification)) {
                    document.body.removeChild(notification);
                }
            }, 500);
        }, 3000);
    }
}

// Initialize the mode switcher when the DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.modeSwitcher = new ModeSwitcher();
});
