/**
 * Mode Manager functionality for Twitch Drops Miner
 * Allows switching between different application modes
 */

class ModeManager {
    constructor() {
        this.modeStorageKey = 'tdm-app-mode';
        this.availableModes = ['normal', 'compact', 'advanced'];
        this.modeIcons = {
            'normal': 'fas fa-user',
            'compact': 'fas fa-compress',
            'advanced': 'fas fa-cogs'
        };
        this.modeLabels = {
            'normal': 'Normal',
            'compact': 'Compact',
            'advanced': 'Advanced'
        };
        this.modeDescriptions = {
            'normal': 'Standard view with all features',
            'compact': 'Streamlined interface for smaller screens',
            'advanced': 'Additional options and detailed information'
        };
        this.init();
    }

    init() {
        // Set up event listener for mode switch button
        const modeSwitchBtn = document.getElementById('mode-switch-btn');
        if (modeSwitchBtn) {
            modeSwitchBtn.addEventListener('click', () => this.showModeSelector());
        }

        // Apply current mode on page load
        this.applyCurrentMode();
    }

    getCurrentMode() {
        const savedMode = localStorage.getItem(this.modeStorageKey);
        return this.availableModes.includes(savedMode) ? savedMode : 'normal';
    }    applyCurrentMode() {
        const currentMode = this.getCurrentMode();
        
        // Remove all mode classes first
        document.body.classList.remove(...this.availableModes.map(mode => `mode-${mode}`));
        
        // Add current mode class
        document.body.classList.add(`mode-${currentMode}`);
        
        // Update the mode button text
        const modeSwitchBtn = document.getElementById('mode-switch-btn');
        if (modeSwitchBtn) {
            const iconElement = `<i class="${this.modeIcons[currentMode]}"></i>`;
            const labelElement = `<span>${this.modeLabels[currentMode]}</span>`;
            modeSwitchBtn.innerHTML = iconElement + labelElement;
            modeSwitchBtn.title = `Current mode: ${this.modeLabels[currentMode]} - Click to change`;
        }
    }

    showModeSelector() {
        // Create a modal for mode selection if it doesn't exist yet
        let modeModal = document.getElementById('mode-selector-modal');
        
        if (!modeModal) {
            modeModal = document.createElement('div');
            modeModal.id = 'mode-selector-modal';
            modeModal.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50';
            document.body.appendChild(modeModal);
        }

        const currentMode = this.getCurrentMode();
        const isDarkMode = document.body.classList.contains('dark-mode');
        
        modeModal.innerHTML = `
            <div class="${isDarkMode ? 'bg-gray-800' : 'bg-white'} rounded-lg shadow-xl p-6 max-w-md w-full">
                <div class="flex justify-between items-center mb-4">
                    <h3 class="text-lg font-bold ${isDarkMode ? 'text-white' : 'text-gray-800'}">Select Application Mode</h3>
                    <button id="close-mode-modal" class="text-gray-500 hover:text-gray-700">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
                <div class="space-y-3">
                    ${this.availableModes.map(mode => `
                        <button class="mode-option w-full text-left p-3 rounded flex items-center ${currentMode === mode ? 
                            (isDarkMode ? 'bg-purple-900 text-white' : 'bg-purple-100 text-purple-800') : 
                            (isDarkMode ? 'bg-gray-700 text-gray-200 hover:bg-gray-600' : 'bg-gray-100 text-gray-800 hover:bg-gray-200')
                        }" data-mode="${mode}">
                            <div class="rounded-full ${currentMode === mode ? 'bg-purple-500' : 'bg-gray-400'} h-10 w-10 flex items-center justify-center mr-3">
                                <i class="${this.modeIcons[mode]} text-white"></i>
                            </div>
                            <div>
                                <div class="font-medium">${this.modeLabels[mode]}</div>
                                <div class="text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}">
                                    ${this.modeDescriptions[mode]}
                                </div>
                            </div>
                            ${currentMode === mode ? 
                                `<div class="ml-auto"><i class="fas fa-check-circle ${isDarkMode ? 'text-purple-300' : 'text-purple-500'}"></i></div>` : 
                                ''}
                        </button>
                    `).join('')}
                </div>
            </div>
        `;

        // Add event listeners to the mode options
        modeModal.querySelectorAll('.mode-option').forEach(button => {
            button.addEventListener('click', () => {
                const mode = button.getAttribute('data-mode');
                this.setMode(mode);
                modeModal.remove();
            });
        });

        // Add event listener to close button
        modeModal.querySelector('#close-mode-modal').addEventListener('click', () => {
            modeModal.remove();
        });

        // Close modal when clicking outside
        modeModal.addEventListener('click', (e) => {
            if (e.target === modeModal) {
                modeModal.remove();
            }
        });
    }

    setMode(mode) {
        if (this.availableModes.includes(mode)) {
            localStorage.setItem(this.modeStorageKey, mode);
            this.applyCurrentMode();        }
    }
}

// Initialize mode manager when the DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.modeManager = new ModeManager();
});
