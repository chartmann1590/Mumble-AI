import React, { useState } from 'react';
import { Mic, FileText, Upload as UploadIcon } from 'lucide-react';
import UploadZone from './components/UploadZone';
import TranscriptionList from './components/TranscriptionList';
import LoadingSpinner from './components/LoadingSpinner';
import { uploadFile, transcribeFile } from './services/api';

const SUPPORTED_FORMATS = ['.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a', '.mp4', '.webm', '.avi', '.mov', '.mkv'];

function App() {
  const [activeTab, setActiveTab] = useState('upload');
  const [selectedFile, setSelectedFile] = useState(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [transcriptionProgress, setTranscriptionProgress] = useState('');
  const [transcriptionResult, setTranscriptionResult] = useState(null);
  const [error, setError] = useState('');
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  const handleFileSelect = (file) => {
    setSelectedFile(file);
    setError('');
    setTranscriptionResult(null);
  };

  const handleUpload = async () => {
    if (!selectedFile) return;

    setIsUploading(true);
    setError('');

    try {
      const uploadResult = await uploadFile(selectedFile);
      setSelectedFile({ ...selectedFile, ...uploadResult });
    } catch (error) {
      console.error('Upload error:', error);
      setError('Upload failed. Please try again.');
    } finally {
      setIsUploading(false);
    }
  };

  const handleTranscribe = async () => {
    if (!selectedFile || !selectedFile.temp_path) return;

    setIsTranscribing(true);
    setError('');
    setTranscriptionProgress('Preparing audio file...');

    try {
      // Estimate progress based on file duration
      const duration = selectedFile.duration_seconds || 60;
      const isVideo = ['.mp4', '.webm', '.avi', '.mov', '.mkv'].includes('.' + selectedFile.original_format);

      // Show different progress messages
      setTimeout(() => {
        if (isVideo) {
          setTranscriptionProgress('Extracting audio from video...');
        } else if (selectedFile.original_format !== 'wav') {
          setTranscriptionProgress('Converting audio to WAV format...');
        } else {
          setTranscriptionProgress('Processing audio file...');
        }
      }, 1000);

      setTimeout(() => {
        setTranscriptionProgress(`Transcribing with large model (GPU accelerated)... This may take several minutes for long files.`);
      }, 3000);

      // Every 10 seconds, update progress message to show it's still working
      const progressInterval = setInterval(() => {
        setTranscriptionProgress(prev => {
          if (prev.includes('still working')) {
            return `Transcribing with large model... Processing ${Math.floor(duration / 60)} minute file. Please wait.`;
          }
          return prev + ' (still working...)';
        });
      }, 10000);

      const transcriptionResult = await transcribeFile(selectedFile);

      clearInterval(progressInterval);
      setTranscriptionProgress('Saving transcription...');

      setTranscriptionResult(transcriptionResult);
      setRefreshTrigger(prev => prev + 1);
      setTranscriptionProgress('');
    } catch (error) {
      console.error('Transcription error:', error);
      setError('Transcription failed. Please try again.');
      setTranscriptionProgress('');
    } finally {
      setIsTranscribing(false);
    }
  };

  const handleReset = () => {
    setSelectedFile(null);
    setTranscriptionResult(null);
    setError('');
  };

  const handleRefresh = () => {
    setRefreshTrigger(prev => prev + 1);
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="flex items-center justify-center space-x-3 mb-4">
            <Mic className="w-8 h-8 text-primary-600" />
            <h1 className="text-3xl font-bold text-gray-900">
              Whisper Transcription Interface
            </h1>
          </div>
          <p className="text-gray-600 max-w-2xl mx-auto">
            Upload audio or video files up to 100MB and get accurate transcriptions using AI. 
            Optionally generate summaries with Ollama.
          </p>
        </div>

        {/* Tabs */}
        <div className="flex space-x-1 mb-8 bg-gray-100 p-1 rounded-lg w-fit mx-auto">
          <button
            onClick={() => setActiveTab('upload')}
            className={`flex items-center space-x-2 px-4 py-2 rounded-md transition-colors ${
              activeTab === 'upload'
                ? 'bg-white text-primary-600 shadow-sm'
                : 'text-gray-600 hover:text-gray-900'
            }`}
          >
            <UploadIcon className="w-4 h-4" />
            <span>Upload & Transcribe</span>
          </button>
          <button
            onClick={() => setActiveTab('history')}
            className={`flex items-center space-x-2 px-4 py-2 rounded-md transition-colors ${
              activeTab === 'history'
                ? 'bg-white text-primary-600 shadow-sm'
                : 'text-gray-600 hover:text-gray-900'
            }`}
          >
            <FileText className="w-4 h-4" />
            <span>Transcription History</span>
          </button>
        </div>

        {/* Upload Tab */}
        {activeTab === 'upload' && (
          <div className="max-w-4xl mx-auto">
            <div className="card">
              <h2 className="text-xl font-semibold text-gray-900 mb-6">
                Upload Audio or Video File
              </h2>

              <UploadZone
                onFileSelect={handleFileSelect}
                isUploading={isUploading}
                supportedFormats={SUPPORTED_FORMATS}
              />

              {selectedFile && (
                <div className="mt-6 space-y-4">
                  <div className="bg-green-50 border border-green-200 rounded-lg p-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <h3 className="font-medium text-green-900">
                          {selectedFile.filename}
                        </h3>
                        <p className="text-sm text-green-700">
                          {selectedFile.original_format ? selectedFile.original_format.toUpperCase() : 'UNKNOWN'} • 
                          {(selectedFile.file_size_bytes / (1024 * 1024)).toFixed(1)} MB
                          {selectedFile.duration_seconds && 
                            ` • ${Math.floor(selectedFile.duration_seconds / 60)}:${Math.floor(selectedFile.duration_seconds % 60).toString().padStart(2, '0')}`
                          }
                        </p>
                      </div>
                      <button
                        onClick={handleReset}
                        className="text-green-600 hover:text-green-700 text-sm font-medium"
                      >
                        Change File
                      </button>
                    </div>
                  </div>

                  <div className="flex space-x-3">
                    {!selectedFile.temp_path && (
                      <button
                        onClick={handleUpload}
                        disabled={isUploading}
                        className="btn-primary"
                      >
                        {isUploading ? (
                          <LoadingSpinner size="small" text="Uploading..." />
                        ) : (
                          'Upload File'
                        )}
                      </button>
                    )}

                    {selectedFile.temp_path && !transcriptionResult && (
                      <button
                        onClick={handleTranscribe}
                        disabled={isTranscribing}
                        className="btn-primary"
                      >
                        {isTranscribing ? (
                          <LoadingSpinner size="small" text={transcriptionProgress || "Transcribing..."} />
                        ) : (
                          'Start Transcription'
                        )}
                      </button>
                    )}

                    {transcriptionResult && (
                      <button
                        onClick={handleReset}
                        className="btn-secondary"
                      >
                        Upload Another File
                      </button>
                    )}
                  </div>

                  {/* Progress indicator */}
                  {isTranscribing && transcriptionProgress && (
                    <div className="mt-4 bg-blue-50 border border-blue-200 rounded-lg p-4">
                      <div className="flex items-center space-x-3">
                        <div className="flex-shrink-0">
                          <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600"></div>
                        </div>
                        <div className="flex-1">
                          <p className="text-sm font-medium text-blue-900">{transcriptionProgress}</p>
                          <p className="text-xs text-blue-700 mt-1">
                            Large audio files may take up to 30 minutes. Please be patient.
                          </p>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {transcriptionResult && (
                <div className="mt-6 space-y-4">
                  <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                    <h3 className="font-medium text-blue-900 mb-2">Transcription Complete!</h3>
                    <div className="text-sm text-blue-700 space-y-1">
                      <p><strong>Language:</strong> {transcriptionResult.language} ({Math.round(transcriptionResult.language_probability * 100)}% confidence)</p>
                      <p><strong>Processing Time:</strong> {transcriptionResult.processing_time_seconds.toFixed(1)} seconds</p>
                    </div>
                  </div>

                  <div className="bg-gray-50 rounded-lg p-4">
                    <h4 className="font-medium text-gray-700 mb-2">Transcription</h4>
                    <p className="text-gray-700 leading-relaxed whitespace-pre-wrap">
                      {transcriptionResult.transcription_text}
                    </p>
                  </div>
                </div>
              )}

              {error && (
                <div className="mt-4 bg-red-50 border border-red-200 rounded-lg p-4">
                  <p className="text-red-600">{error}</p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* History Tab */}
        {activeTab === 'history' && (
          <div className="max-w-6xl mx-auto">
            <TranscriptionList 
              refreshTrigger={refreshTrigger}
              onRefresh={handleRefresh}
            />
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
