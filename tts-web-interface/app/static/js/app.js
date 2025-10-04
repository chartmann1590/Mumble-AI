class TTSApp {
    constructor() {
        this.voices = {};
        this.selectedVoice = null;
        this.selectedEngine = 'piper';
        this.audioContext = null;
        this.init();
    }

    async init() {
        this.setupEventListeners();
        await this.loadVoices();
        this.populateRegionFilter();
        this.updateCharCount();
    }

    setupEventListeners() {
        // Text input
        const textInput = document.getElementById('text-input');
        textInput.addEventListener('input', () => {
            this.updateCharCount();
            this.updateButtonStates();
        });

        // Character count
        textInput.addEventListener('input', this.updateCharCount.bind(this));

        // Engine selection
        document.querySelectorAll('input[name="engine"]').forEach(radio => {
            radio.addEventListener('change', async (e) => {
                this.selectedEngine = e.target.value;
                this.clearSelection();
                await this.loadVoices();
                this.populateRegionFilter();
                this.showStatus(`Switched to ${e.target.value === 'piper' ? 'Piper' : 'Silero'} TTS engine`, 'success');
            });
        });

        // Filter controls
        document.getElementById('region-filter').addEventListener('change', this.filterVoices.bind(this));
        document.getElementById('gender-filter').addEventListener('change', this.filterVoices.bind(this));
        document.getElementById('quality-filter').addEventListener('change', this.filterVoices.bind(this));

        // Buttons
        document.getElementById('preview-btn').addEventListener('click', (e) => {
            e.preventDefault();
            this.previewVoice();
        });
        document.getElementById('generate-btn').addEventListener('click', (e) => {
            e.preventDefault();
            this.generateAudio();
        });

        // Audio player
        const audioPlayer = document.getElementById('audio-player');
        audioPlayer.addEventListener('loadedmetadata', () => {
            const duration = this.formatTime(audioPlayer.duration);
            document.getElementById('audio-duration').textContent = duration;
        });
    }

    async loadVoices() {
        try {
            const response = await fetch(`/api/voices?engine=${this.selectedEngine}`);
            if (!response.ok) {
                throw new Error('Failed to load voices');
            }
            this.voices = await response.json();
            this.renderVoices();
        } catch (error) {
            this.showStatus('Failed to load voices: ' + error.message, 'error');
            console.error('Error loading voices:', error);
        }
    }

    populateRegionFilter() {
        const regionFilter = document.getElementById('region-filter');
        // Clear existing options except the first "All Regions" option
        while (regionFilter.options.length > 1) {
            regionFilter.remove(1);
        }
        // Add new options
        Object.keys(this.voices).forEach(regionCode => {
            const option = document.createElement('option');
            option.value = regionCode;
            option.textContent = this.voices[regionCode].name;
            regionFilter.appendChild(option);
        });
    }

    renderVoices() {
        const voiceGrid = document.getElementById('voice-grid');
        voiceGrid.innerHTML = '';

        Object.entries(this.voices).forEach(([regionCode, regionData]) => {
            Object.entries(regionData.voices).forEach(([gender, voiceList]) => {
                voiceList.forEach(voice => {
                    const voiceCard = this.createVoiceCard(voice, regionData.name, gender);
                    voiceGrid.appendChild(voiceCard);
                });
            });
        });
    }

    createVoiceCard(voice, regionName, gender) {
        const card = document.createElement('div');
        card.className = 'voice-card';
        card.dataset.voiceId = voice.id;
        card.dataset.region = regionName;
        card.dataset.gender = gender;
        card.dataset.quality = voice.quality;

        card.innerHTML = `
            <div class="voice-name">${voice.name}</div>
            <div class="voice-details">
                <span>${regionName}</span>
                <span class="voice-quality quality-${voice.quality}">${voice.quality}</span>
            </div>
        `;

        card.addEventListener('click', () => this.selectVoice(voice, card));
        return card;
    }

    selectVoice(voice, cardElement) {
        // Remove previous selection
        document.querySelectorAll('.voice-card').forEach(card => {
            card.classList.remove('selected');
        });

        // Select new voice
        cardElement.classList.add('selected');
        this.selectedVoice = voice;
        
        // Update selected voice name in audio section
        document.getElementById('selected-voice-name').textContent = voice.name;
        
        this.updateButtonStates();
        this.showStatus(`Selected voice: ${voice.name}`, 'success');
    }

    filterVoices() {
        const regionFilter = document.getElementById('region-filter').value;
        const genderFilter = document.getElementById('gender-filter').value;
        const qualityFilter = document.getElementById('quality-filter').value;

        const voiceCards = document.querySelectorAll('.voice-card');
        
        voiceCards.forEach(card => {
            let show = true;

            if (regionFilter && card.dataset.region !== this.voices[regionFilter]?.name) {
                show = false;
            }

            if (genderFilter && card.dataset.gender !== genderFilter) {
                show = false;
            }

            if (qualityFilter && card.dataset.quality !== qualityFilter) {
                show = false;
            }

            card.style.display = show ? 'block' : 'none';
        });

        // Clear selection if selected voice is hidden
        if (this.selectedVoice) {
            const selectedCard = document.querySelector('.voice-card.selected');
            if (selectedCard && selectedCard.style.display === 'none') {
                this.clearSelection();
            }
        }
    }

    clearSelection() {
        document.querySelectorAll('.voice-card').forEach(card => {
            card.classList.remove('selected');
        });
        this.selectedVoice = null;
        this.updateButtonStates();
    }

    updateCharCount() {
        const textInput = document.getElementById('text-input');
        const charCount = document.getElementById('char-count');
        const count = textInput.value.length;
        charCount.textContent = count;
        
        if (count > 4500) {
            charCount.style.color = '#e53e3e';
        } else if (count > 4000) {
            charCount.style.color = '#dd6b20';
        } else {
            charCount.style.color = '#718096';
        }
    }

    updateButtonStates() {
        const textInput = document.getElementById('text-input');
        const hasText = textInput.value.trim().length > 0;
        const hasVoice = this.selectedVoice !== null;

        document.getElementById('preview-btn').disabled = !hasVoice;
        document.getElementById('generate-btn').disabled = !hasText || !hasVoice;
    }

    async previewVoice() {
        if (!this.selectedVoice) {
            this.showStatus('Please select a voice first', 'error');
            return;
        }

        const previewText = "Hello! This is a preview of this voice. How does it sound?";
        await this.generateAudio(previewText, true);
    }

    async generateAudio(customText = null, isPreview = false) {
        const textInput = document.getElementById('text-input');
        const text = customText || textInput.value.trim();

        console.log('Text input element:', textInput);
        console.log('Text input value:', textInput.value);
        console.log('Text after trim:', text);
        console.log('Text type:', typeof text);

        if (!text) {
            this.showStatus('Please enter some text', 'error');
            return;
        }

        if (!this.selectedVoice) {
            this.showStatus('Please select a voice', 'error');
            return;
        }

        this.showLoading(true);
        this.showStatus(isPreview ? 'Generating preview...' : 'Generating audio...', 'info');

        try {
            const payload = {
                text: text,
                voice: this.selectedVoice.id,
                engine: this.selectedEngine
            };
            console.log('Sending payload:', payload);

            const response = await fetch('/api/synthesize', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Failed to generate audio');
            }

            // Create audio blob and play
            const audioBlob = await response.blob();
            const audioUrl = URL.createObjectURL(audioBlob);
            
            const audioPlayer = document.getElementById('audio-player');
            audioPlayer.src = audioUrl;
            
            // Show audio section
            document.getElementById('audio-section').style.display = 'block';
            
            // Auto-play for preview
            if (isPreview) {
                audioPlayer.play();
            }

            this.showStatus(
                isPreview ? 'Preview generated successfully!' : 'Audio generated successfully! Click play to listen.',
                'success'
            );

            // Clean up old URL after 5 minutes
            setTimeout(() => {
                URL.revokeObjectURL(audioUrl);
            }, 300000);

        } catch (error) {
            this.showStatus('Error: ' + error.message, 'error');
            console.error('Audio generation error:', error);
        } finally {
            this.showLoading(false);
        }
    }

    showLoading(show) {
        const overlay = document.getElementById('loading-overlay');
        if (show) {
            overlay.classList.add('show');
        } else {
            overlay.classList.remove('show');
        }
    }

    showStatus(message, type = 'info') {
        const statusElement = document.getElementById('status-message');
        statusElement.textContent = message;
        statusElement.className = `status-message status-${type}`;
        
        // Auto-hide success messages after 3 seconds
        if (type === 'success') {
            setTimeout(() => {
                statusElement.textContent = '';
                statusElement.className = 'status-message';
            }, 3000);
        }
    }

    formatTime(seconds) {
        if (isNaN(seconds)) return '0:00';
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }
}

// Initialize the app when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new TTSApp();
});

// Handle page visibility change to pause audio when tab is hidden
document.addEventListener('visibilitychange', () => {
    const audioPlayer = document.getElementById('audio-player');
    if (document.hidden && !audioPlayer.paused) {
        audioPlayer.pause();
    }
});

// Handle beforeunload to clean up audio URLs
window.addEventListener('beforeunload', () => {
    const audioPlayer = document.getElementById('audio-player');
    if (audioPlayer.src && audioPlayer.src.startsWith('blob:')) {
        URL.revokeObjectURL(audioPlayer.src);
    }
});
