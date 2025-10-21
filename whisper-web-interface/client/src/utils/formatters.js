export const formatFileSize = (bytes) => {
  if (bytes === 0) return '0 Bytes';
  
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
};

export const formatDuration = (seconds) => {
  if (!seconds) return 'Unknown';
  
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  
  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  } else {
    return `${minutes}:${secs.toString().padStart(2, '0')}`;
  }
};

export const formatDate = (dateString) => {
  if (!dateString) return 'Unknown';
  
  const date = new Date(dateString);
  return date.toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
};

export const formatLanguage = (language, probability) => {
  if (!language || typeof language !== 'string') return 'Unknown';
  
  const langNames = {
    'en': 'English',
    'es': 'Spanish',
    'fr': 'French',
    'de': 'German',
    'it': 'Italian',
    'pt': 'Portuguese',
    'ru': 'Russian',
    'ja': 'Japanese',
    'ko': 'Korean',
    'zh': 'Chinese',
    'ar': 'Arabic',
    'hi': 'Hindi',
  };
  
  const langName = langNames[language] || language.toUpperCase();
  const confidence = probability ? ` (${Math.round(probability * 100)}%)` : '';
  
  return `${langName}${confidence}`;
};

export const formatText = (text) => {
  if (!text) return '';
  
  // Split text into sentences and add proper spacing
  return text
    .replace(/([.!?])\s*([A-Z])/g, '$1\n\n$2') // Add paragraph breaks after sentences
    .replace(/([.!?])\s*([A-Z][a-z])/g, '$1\n\n$2') // Handle lowercase after periods
    .replace(/\n{3,}/g, '\n\n') // Remove excessive line breaks
    .trim();
};

export const formatTimestamp = (seconds) => {
  if (typeof seconds !== 'number') return '0:00';
  
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  
  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  }
  return `${minutes}:${secs.toString().padStart(2, '0')}`;
};

export const formatSegmentText = (segments) => {
  if (!segments || !Array.isArray(segments)) return '';
  
  let result = '';
  let currentSpeaker = null;
  
  for (const seg of segments) {
    const timestamp = formatTimestamp(seg.start);
    const speaker = seg.speaker || 'Speaker 1';
    
    if (speaker !== currentSpeaker) {
      currentSpeaker = speaker;
      result += `\n\n[${timestamp}] ${speaker}:\n${seg.text}`;
    } else {
      result += ` [${timestamp}] ${seg.text}`;
    }
  }
  
  return result.trim();
};

export const getSpeakerCount = (segments) => {
  if (!segments || !Array.isArray(segments)) return 0;
  const speakers = new Set(segments.map(s => s.speaker));
  return speakers.size;
};

export const getSpeakerColor = (speaker) => {
  const colors = {
    'Speaker 1': 'bg-blue-100 text-blue-800',
    'Speaker 2': 'bg-green-100 text-green-800',
    'Speaker 3': 'bg-purple-100 text-purple-800',
    'Speaker 4': 'bg-orange-100 text-orange-800',
    'Speaker 5': 'bg-pink-100 text-pink-800',
  };
  return colors[speaker] || 'bg-gray-100 text-gray-800';
};