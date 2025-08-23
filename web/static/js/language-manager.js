/**
 * Language Manager for Twitch Drops Miner Web Interface
 * This module handles translations for the web interface
 */

class LanguageManager {
    constructor() {
        this.currentLanguage = 'English';
        this.translations = {};
        this.translationElements = [];
        this.hooksInstalled = false;
        this.installDOMHooks();
        this.domReadyInitialized = false;
        
        // Initialize once the DOM is fully loaded
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => {
                this.domContentLoaded();
            });
        } else {
            // DOM already loaded
            setTimeout(() => this.domContentLoaded(), 0);
        }
    }
    
    /**
     * Called when DOM content is loaded
     * Initialize language selector and apply translations
     */
    domContentLoaded() {
        if (this.domReadyInitialized) return;
        
        this.initializeLanguageSelector();
        this.loadCurrentLanguage();
        this.domReadyInitialized = true;
    }
    
    /**
     * Try to load the current language from settings or storage
     */
    loadCurrentLanguage() {
        // Try to load language from localStorage
        const savedLanguage = localStorage.getItem('preferredLanguage');
        
        if (savedLanguage) {
            this.currentLanguage = savedLanguage;
            this.loadLanguageData(savedLanguage).then(() => {
                this.applyTranslations(false);
            });
            
            // Update language selector if it exists
            const languageSelect = document.getElementById('language-select');
            if (languageSelect && languageSelect.value !== savedLanguage) {
                languageSelect.value = savedLanguage;
            }
        } else {
            // Default to English
            this.loadLanguageData('English').then(() => {
                this.applyTranslations(false);
            });
        }
    }

    /**
     * Initialize the language selector dropdown
     */
    initializeLanguageSelector() {
        const languageSelect = document.getElementById('language-select');
        
        if (languageSelect) {
            // Set up event listener for language change
            languageSelect.addEventListener('change', (e) => {
                this.handleLanguageChange(e.target.value);
            });
        }
    }    /**
     * Handle language change event
     * @param {string} language - The selected language
     */
    handleLanguageChange(language) {
        if (language === this.currentLanguage) return;

        this.currentLanguage = language;
        
        // Save the language preference to localStorage
        localStorage.setItem('preferredLanguage', language);
        
        // First load the translations if they're not already loaded
        this.loadLanguageData(language).then(() => {
            // Then apply the translations to the UI
            this.applyTranslations();
            
            // Update document language attribute for accessibility
            document.documentElement.lang = language.toLowerCase();
        });
    }

    /**
     * Load language data from the server
     * @param {string} language - The language to load
     * @returns {Promise<Object>} - Promise that resolves when translations are loaded
     */    async loadLanguageData(language) {
        // If we already have this language loaded, no need to fetch again
        if (this.translations[language]) {
            return this.translations[language];
        }

        try {
            const response = await fetch(`/api/translations/${language}`, {
                headers: getAuthHeaders()
            });

            if (!response.ok) {
                throw new Error(`Failed to load translations for ${language}`);
            }

            const data = await response.json();
            this.translations[language] = data;
            return data;
        } catch (error) {
            console.error('Error loading translations:', error);
            showToast('Error', `Failed to load translations for ${language}`, 'error');
            
            // If this was the first language we tried to load, try to load English as fallback
            if (language !== 'English' && Object.keys(this.translations).length === 0) {
                console.log('Attempting to load English as fallback');
                return this.loadLanguageData('English');
            }
            
            return null;
        }
    }

    /**
     * Translate settings UI elements
     */
    translateSettingsUI() {
        if (!this.translations[this.currentLanguage]) return;
        
        const translation = this.translations[this.currentLanguage];
        
        // Translate priority mode options
        const priorityModeSelect = document.getElementById('priority-mode');
        if (priorityModeSelect) {
            const options = priorityModeSelect.options;
            for (let i = 0; i < options.length; i++) {
                const option = options[i];
                const modeKey = option.value;
                const translationKey = `gui.settings.priority_modes.${modeKey.toLowerCase()}`;
                const translatedText = this.getTranslatedText(translationKey, translation);
                if (translatedText) {
                    option.textContent = translatedText;
                }
            }
        }
        
        // Translate settings section headers
        const settingSectionHeaders = document.querySelectorAll('.settings-section-header');
        settingSectionHeaders.forEach(header => {
            const key = header.getAttribute('data-i18n');
            if (key) {
                const translatedText = this.getTranslatedText(key, translation);
                if (translatedText) {
                    header.textContent = translatedText;
                }
            }
        });
        
        // Translate priority and exclusion list headers
        const priorityListHeader = document.querySelector('.priority-list-header');
        if (priorityListHeader) {
            const translatedText = this.getTranslatedText('gui.settings.priority', translation);
            if (translatedText) priorityListHeader.textContent = translatedText;
        }
        
        const excludeListHeader = document.querySelector('.exclude-list-header');
        if (excludeListHeader) {
            const translatedText = this.getTranslatedText('gui.settings.exclude', translation);
            if (translatedText) excludeListHeader.textContent = translatedText;
        }
    }
      /**
     * Translate dynamic UI components
     */
    translateDynamicElements() {
        if (!this.translations[this.currentLanguage]) return;
        
        const translation = this.translations[this.currentLanguage];
        
        // Translate channel status text
        document.querySelectorAll('.channel-status').forEach(el => {
            const status = el.getAttribute('data-status');
            if (status === 'online') {
                el.textContent = this.getTranslatedText('gui.channels.online', translation) || el.textContent;
            } else if (status === 'pending') {
                el.textContent = this.getTranslatedText('gui.channels.pending', translation) || el.textContent;
            } else if (status === 'offline') {
                el.textContent = this.getTranslatedText('gui.channels.offline', translation) || el.textContent;
            }
        });
        
        // Translate settings UI elements
        this.translateSettingsUI();
        
        // Translate inventory status text
        document.querySelectorAll('.inventory-status').forEach(el => {
            const status = el.getAttribute('data-status');
            if (status && this.getTranslatedText(`gui.inventory.status.${status}`, translation)) {
                el.textContent = this.getTranslatedText(`gui.inventory.status.${status}`, translation);
            }
        });
        
        // Translate buttons
        const switchBtn = document.getElementById('switch-channel');
        if (switchBtn) {
            if (!switchBtn.hasAttribute('data-original-text')) {
                switchBtn.setAttribute('data-original-text', switchBtn.textContent);
            }
            const switchText = this.getTranslatedText('gui.channels.switch', translation);
            if (switchText) switchBtn.textContent = switchText;
        }

        // Translate all section headers (h2, h3, h4)
        document.querySelectorAll('h2, h3, h4').forEach(header => {
            // Skip elements with existing data-i18n attribute as they're handled separately
            if (header.hasAttribute('data-i18n')) return;
            
            // Try to match common headers with translation keys
            const textContent = header.textContent.trim();
            let translatedText = null;
            
            // Common section titles
            const commonSections = {
                'Channels': 'gui.channels.name',
                'Available Channels': 'gui.channels.name',
                'Inventory': 'gui.tabs.inventory',
                'All Campaigns': 'gui.tabs.inventory',
                'Settings': 'gui.tabs.settings',
                'General Settings': 'gui.settings.general.name',
                'Priority Settings': 'gui.settings.priority',
                'Priority List': 'gui.settings.priority',
                'Exclude List': 'gui.settings.exclude',
                'Login': 'gui.login.name',
                'Status': 'gui.status.name',
                'Progress': 'gui.progress.name'
            };
            
            if (commonSections[textContent]) {
                translatedText = this.getTranslatedText(commonSections[textContent], translation);
                if (translatedText) header.textContent = translatedText;
            }
        });
        
        // Translate common labels and buttons that don't have data-i18n attribute
        document.querySelectorAll('label, button, span').forEach(element => {
            if (element.hasAttribute('data-i18n')) return;
            
            const textContent = element.textContent.trim();
            if (!textContent) return;
            
            // Common UI elements
            const commonTexts = {
                'Switch': 'gui.channels.switch',
                'Channel': 'gui.channels.headings.channel',
                'Status': 'gui.channels.headings.status', 
                'Game': 'gui.channels.headings.game',
                'Viewers': 'gui.channels.headings.viewers',
                'Login': 'gui.login.button',
                'Logout': 'gui.login.button',
                'Priority': 'gui.settings.priority',
                'Exclude': 'gui.settings.exclude',
                'Add': 'gui.settings.add',
                'Refresh': 'gui.inventory.filter.refresh',
                'Save': 'gui.settings.save',
                'Reload': 'gui.settings.reload'
            };
            
            if (commonTexts[textContent]) {
                const translatedText = this.getTranslatedText(commonTexts[textContent], translation);
                if (translatedText) element.textContent = translatedText;
            }
        });
        
        // Handle table headers
        document.querySelectorAll('th').forEach(th => {
            if (th.hasAttribute('data-i18n')) return;
            
            const textContent = th.textContent.trim();
            if (!textContent) return;
            
            // Common table headers
            const commonHeaders = {
                'Channel': 'gui.channels.headings.channel',
                'Status': 'gui.channels.headings.status',
                'Game': 'gui.channels.headings.game',
                'Viewers': 'gui.channels.headings.viewers',
                'Actions': 'gui.channels.actions'
            };
            
            if (commonHeaders[textContent]) {
                const translatedText = this.getTranslatedText(commonHeaders[textContent], translation);
                if (translatedText) th.textContent = translatedText;
            }
        });
        
        // Handle placeholders
        document.querySelectorAll('input[placeholder], textarea[placeholder]').forEach(input => {
            const placeholder = input.getAttribute('placeholder');
            if (!placeholder) return;
            
            // Common placeholders
            const commonPlaceholders = {
                'Search channels...': 'gui.channels.search',
                'Username': 'gui.login.username',
                'Password': 'gui.login.password',
                'http://username:password@address:port': 'gui.settings.general.proxy'
            };
            
            if (commonPlaceholders[placeholder]) {
                const translatedText = this.getTranslatedText(commonPlaceholders[placeholder], translation);
                if (translatedText) input.setAttribute('placeholder', translatedText);
            }
        });
        
        // Translate error messages
        document.querySelectorAll('.error-text, .text-red-500').forEach(element => {
            const text = element.textContent;
            if (text.includes('Failed to load')) {
                element.textContent = this.getTranslatedText('error.no_connection', translation) || text;
            } else if (text.includes('Error:')) {
                element.textContent = text.replace('Error:', this.getTranslatedText('error.general', translation) || 'Error:');
            }
        });
    }    /**
     * Apply translations to the UI
     * @param {boolean} showNotification - Whether to show a toast notification
     */
    applyTranslations(showNotification = true) {
        if (!this.translations[this.currentLanguage]) {
            console.warn(`No translations loaded for ${this.currentLanguage}`);
            return;
        }

        const translation = this.translations[this.currentLanguage];
        
        // First, set document title if it has data-i18n
        const titleElement = document.querySelector('title[data-i18n]');
        if (titleElement) {
            const key = titleElement.getAttribute('data-i18n');
            const translatedText = this.getTranslatedText(key, translation);
            if (translatedText) {
                document.title = translatedText;
            }
        }

        // Translate all elements with data-i18n attribute
        document.querySelectorAll('[data-i18n]').forEach(element => {
            const key = element.getAttribute('data-i18n');
            const translatedText = this.getTranslatedText(key, translation);
              if (translatedText) {
                // For input placeholders
                if (element.hasAttribute('placeholder')) {
                    element.setAttribute('placeholder', translatedText);
                } else {
                    element.textContent = translatedText;
                }
            }
        });
        
        // Handle elements with data-i18n-placeholder attribute specifically for placeholders
        document.querySelectorAll('[data-i18n-placeholder]').forEach(element => {
            const key = element.getAttribute('data-i18n-placeholder');
            const translatedText = this.getTranslatedText(key, translation);
            
            if (translatedText) {
                element.setAttribute('placeholder', translatedText);
            }
        });
        
        // Translate dynamic elements
        this.translateDynamicElements();

        // Show toast notification if requested
        if (showNotification) {
            showToast('Language Changed', `Interface language changed to ${this.currentLanguage}`, 'info');
        }
    }

    /**
     * Get translated text for a given key from the translation object
     * @param {string} key - The translation key in dot notation (e.g., "gui.tabs.main")
     * @param {Object} translation - The translation object
     * @returns {string|null} - The translated text or null if not found
     */
    getTranslatedText(key, translation) {
        const parts = key.split('.');
        let value = translation;

        for (const part of parts) {
            if (value && typeof value === 'object' && part in value) {
                value = value[part];
            } else {
                return null;
            }
        }

        return typeof value === 'string' ? value : null;
    }    /**
     * Scan the page and register all elements that need translation
     * This can help identify missing translations
     * @param {boolean} reportOnly - If true, only reports untranslated elements without modifying them
     */
    scanForTranslatableElements(reportOnly = true) {
        const untranslated = [];
        const translation = this.translations[this.currentLanguage];
        if (!translation) return untranslated;
        
        // Common UI elements to scan for
        const textElements = document.querySelectorAll('h1, h2, h3, h4, h5, h6, p, span, button, a, label, th, td');
        const inputElements = document.querySelectorAll('input[placeholder], textarea[placeholder]');
        
        textElements.forEach(element => {
            // Skip already translated elements
            if (element.hasAttribute('data-i18n') || !element.textContent.trim()) return;
            
            // Skip elements with only icons or very short text (likely not needing translation)
            if (element.children.length > 0 && element.textContent.trim().length < 3) return;
            
            untranslated.push({
                element,
                type: 'text',
                content: element.textContent.trim()
            });
        });
        
        inputElements.forEach(element => {
            if (element.hasAttribute('data-i18n-placeholder') || !element.getAttribute('placeholder')) return;
            
            untranslated.push({
                element,
                type: 'placeholder',
                content: element.getAttribute('placeholder')
            });
        });
        
        if (reportOnly) {
            console.log('Untranslated elements:', untranslated);
            return untranslated;
        } else {
            // For future: automatically add data-i18n attributes or suggest translations
            return untranslated;
        }
    }/**
     * Initialize the manager with the current language
     * @param {string} language - The current language
     */
    init(language) {
        if (!language) {
            console.warn('No language provided to initialize language manager');
            language = 'English'; // Default to English
        }
        
        this.currentLanguage = language;
        // Load the current language data
        this.loadLanguageData(language).then((data) => {
            if (data) {
                // Initially translate the UI, but don't show notification on initial load
                this.applyTranslations(false);
            }
        });
    }
    
    /**
     * Translate HTML content before it's inserted into the DOM
     * This is useful for translating dynamically created elements
     * @param {string} htmlContent - The HTML content to translate
     * @returns {string} - The translated HTML content
     */
    translateHTML(htmlContent) {
        if (!this.translations[this.currentLanguage]) return htmlContent;
        
        const translation = this.translations[this.currentLanguage];
        
        // Replace common texts in the HTML content
        const replacements = [
            // Channels tab
            { original: 'Watching: ', translation: this.getTranslatedText('status.watching', translation)?.replace('{channel}', '') || 'Watching: ' },
            { original: 'ONLINE', translation: this.getTranslatedText('gui.channels.online', translation)?.trim() || 'ONLINE' },
            { original: 'OFFLINE', translation: this.getTranslatedText('gui.channels.offline', translation)?.trim() || 'OFFLINE' },
            { original: 'Switch', translation: this.getTranslatedText('gui.channels.switch', translation) || 'Switch' },
            { original: 'Failed to load channels', translation: this.getTranslatedText('web.channels.connection_error', translation) || 'Failed to load channels' },
            
            // Campaigns & Inventory
            { original: 'Failed to load campaigns', translation: this.getTranslatedText('web.campaigns.connection_error', translation) || 'Failed to load campaigns' },
            { original: 'Failed to load inventory', translation: this.getTranslatedText('web.inventory.connection_error', translation) || 'Failed to load inventory' },
            
            // Status messages
            { original: 'No available channels to watch', translation: this.getTranslatedText('status.no_channel', translation)?.split('.')[0] || 'No available channels to watch' },
            { original: 'No active campaigns', translation: this.getTranslatedText('status.no_campaign', translation)?.split('.')[0] || 'No active campaigns' },
            
            // Headers
            { original: 'Channel', translation: this.getTranslatedText('gui.channels.headings.channel', translation) || 'Channel' },
            { original: 'Status', translation: this.getTranslatedText('gui.channels.headings.status', translation) || 'Status' },
            { original: 'Game', translation: this.getTranslatedText('gui.channels.headings.game', translation) || 'Game' }, 
            { original: 'Viewers', translation: this.getTranslatedText('gui.channels.headings.viewers', translation) || 'Viewers' },
            { original: 'Actions', translation: this.getTranslatedText('web.channels.actions', translation) || 'Actions' },
            
            // Login Messages
            { original: 'Logged in as:', translation: this.getTranslatedText('gui.login.labels', translation)?.split('\n')[0] || 'Logged in as:' },
            { original: 'Login required', translation: this.getTranslatedText('gui.login.required', translation) || 'Login required' },
            { original: 'Please log in to continue.', translation: this.getTranslatedText('gui.login.request', translation) || 'Please log in to continue.' },
            { original: 'Logging in...', translation: this.getTranslatedText('gui.login.logging_in', translation) || 'Logging in...' },
            
            // Settings
            { original: 'Priority Only', translation: this.getTranslatedText('gui.settings.priority_modes.priority_only', translation) || 'Priority Only' },
            { original: 'Ending Soonest', translation: this.getTranslatedText('gui.settings.priority_modes.ending_soonest', translation) || 'Ending Soonest' },
            { original: 'Low Availability First', translation: this.getTranslatedText('gui.settings.priority_modes.low_availability', translation) || 'Low Availability First' },
            
            // Buttons
            { original: 'Add', translation: this.getTranslatedText('web.settings.add', translation) || 'Add' },
            { original: 'Save Settings', translation: this.getTranslatedText('web.settings.save', translation) || 'Save Settings' },
            { original: 'Reload', translation: this.getTranslatedText('gui.settings.reload', translation) || 'Reload' }
        ];
        
        let result = htmlContent;
        for (const { original, translation } of replacements) {
            if (translation && original !== translation) {
                const regex = new RegExp(original.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g');
                result = result.replace(regex, translation);
            }
        }
        
        return result;
    }
      /**
     * Install a hook to intercept and translate innerHTML assignments
     * This will translate content before it's inserted into the DOM
     */
    installDOMHooks() {
        if (this.hooksInstalled) return;
        
        const originalInnerHTMLSetter = Object.getOwnPropertyDescriptor(Element.prototype, 'innerHTML').set;
        const originalTextContentSetter = Object.getOwnPropertyDescriptor(Node.prototype, 'textContent').set;
        const originalSetAttribute = Element.prototype.setAttribute;
        
        const languageManager = this;
        
        // Hook innerHTML
        Object.defineProperty(Element.prototype, 'innerHTML', {
            set(value) {
                // Translate the content before setting it
                if (typeof value === 'string' && value.length > 0) {
                    const translatedValue = languageManager.translateHTML(value);
                    originalInnerHTMLSetter.call(this, translatedValue);
                } else {
                    originalInnerHTMLSetter.call(this, value);
                }
            }
        });
        
        // Hook textContent (for smaller UI updates)
        Object.defineProperty(Node.prototype, 'textContent', {
            set(value) {
                // Only translate certain elements like span, p, div, button, etc.
                const translateableElements = ['SPAN', 'P', 'DIV', 'BUTTON', 'A', 'LABEL', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'LI'];
                
                if (this.nodeType === 1 && 
                    translateableElements.includes(this.nodeName) &&
                    typeof value === 'string' && 
                    value.length > 0 && 
                    !this.hasAttribute('data-no-translate')) {
                        
                    const translatedValue = languageManager.translateTextContent(value);
                    originalTextContentSetter.call(this, translatedValue);
                } else {
                    originalTextContentSetter.call(this, value);
                }
            }
        });
        
        // Hook setAttribute for placeholders
        Element.prototype.setAttribute = function(name, value) {
            if (name === 'placeholder' && typeof value === 'string' && value.length > 0) {
                const translatedValue = languageManager.translatePlaceholder(value);
                originalSetAttribute.call(this, name, translatedValue);
            } else {
                originalSetAttribute.call(this, name, value);
            }
        };
        
        this.hooksInstalled = true;
        console.log('DOM translation hooks installed');
    }
    
    /**
     * Translate placeholder text
     * @param {string} text - The placeholder text to translate
     * @returns {string} - The translated text
     */
    translatePlaceholder(text) {
        if (!this.translations[this.currentLanguage]) return text;
        
        const translation = this.translations[this.currentLanguage];
        
        // Common placeholders to translate
        const commonPlaceholders = {
            'Username': 'web.login.username',
            'Password': 'web.login.password',
            'Search channels...': 'web.channels.search',
            'http://username:password@address:port': 'gui.settings.general.proxy',
            'Search...': 'web.common.search',
            'Enter text...': 'web.common.enter_text'
        };
        
        if (commonPlaceholders[text]) {
            const translatedText = this.getTranslatedText(commonPlaceholders[text], translation);
            if (translatedText) return translatedText;
        }
        
        return text;
    }
    
    /**
     * Translate text content when assigned to nodes
     * @param {string} text - The text content to translate
     * @returns {string} - The translated text
     */
    translateTextContent(text) {
        if (!this.translations[this.currentLanguage]) return text;
        
        const translation = this.translations[this.currentLanguage];
        
        // List of common UI texts with their translation keys
        const commonTexts = {
            'Loading...': 'web.common.loading',
            'Error': 'web.common.error',
            'Success': 'web.common.success',
            'Warning': 'web.common.warning',
            'Information': 'web.common.info',
            'Yes': 'web.common.yes',
            'No': 'web.common.no',
            'OK': 'web.common.ok',
            'Cancel': 'web.common.cancel',
            'Sign in': 'web.login.login_button',
            'Logout': 'web.header.logout',
            'Refresh': 'web.header.refresh',
            'Save Settings': 'web.settings.save',
            'Add': 'web.settings.add',
            'Update': 'web.settings.update'
        };
        
        if (commonTexts[text]) {
            const translatedText = this.getTranslatedText(commonTexts[text], translation);
            if (translatedText) return translatedText;
        }
        
        return text;
    }
}

// Create the language manager instance immediately
window.languageManager = new LanguageManager();
