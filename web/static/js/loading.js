function addLoadingIndicators() {
    const progressContainer = document.getElementById('progress-container');
    const progressBar = document.getElementById('progress-bar');
    
    if (progressContainer && progressBar) {
        // Make sure it starts hidden
        progressContainer.classList.remove('visible');
        progressBar.style.width = '0%';
    }
}
