import React, { useState } from 'react';
import { Sparkles, FileText, List, Target, CheckSquare, ListOrdered, FileCheck, MessageSquare, Loader2 } from 'lucide-react';
import { generateAIContent } from '../services/api';

const AIGenerationPanel = ({ transcriptionText }) => {
  const [generating, setGenerating] = useState(false);
  const [currentType, setCurrentType] = useState(null);
  const [generatedContent, setGeneratedContent] = useState({});
  const [expandedType, setExpandedType] = useState(null);

  const generationOptions = [
    {
      type: 'brief_summary',
      label: 'Brief Summary',
      description: '1-2 paragraph concise summary',
      icon: FileText,
      color: 'blue'
    },
    {
      type: 'detailed_summary',
      label: 'Detailed Summary',
      description: 'Comprehensive summary with all details',
      icon: FileCheck,
      color: 'indigo'
    },
    {
      type: 'bullet_points',
      label: 'Bullet Points',
      description: 'Key points in bullet format',
      icon: List,
      color: 'green'
    },
    {
      type: 'key_takeaways',
      label: 'Key Takeaways',
      description: '5-10 most important insights',
      icon: Target,
      color: 'purple'
    },
    {
      type: 'action_items',
      label: 'Action Items',
      description: 'Extract tasks and next steps',
      icon: CheckSquare,
      color: 'orange'
    },
    {
      type: 'outline',
      label: 'Outline',
      description: 'Hierarchical structure outline',
      icon: ListOrdered,
      color: 'teal'
    },
    {
      type: 'meeting_notes',
      label: 'Meeting Notes',
      description: 'Structured meeting notes format',
      icon: FileText,
      color: 'pink'
    },
    {
      type: 'qa_format',
      label: 'Q&A Format',
      description: 'Questions and answers extracted',
      icon: MessageSquare,
      color: 'cyan'
    }
  ];

  const handleGenerate = async (type) => {
    if (!transcriptionText) {
      alert('No transcription text available');
      return;
    }

    if (!window.confirm(`Generate ${generationOptions.find(o => o.type === type)?.label}? This may take up to 5 minutes.`)) {
      return;
    }

    setGenerating(true);
    setCurrentType(type);

    try {
      const result = await generateAIContent(transcriptionText, type);
      setGeneratedContent(prev => ({
        ...prev,
        [type]: {
          content: result.content,
          model: result.model
        }
      }));
      setExpandedType(type);
      alert('AI generation completed successfully!');
    } catch (error) {
      console.error('Error generating AI content:', error);
      alert(`Failed to generate content: ${error.response?.data?.error || error.message}`);
    } finally {
      setGenerating(false);
      setCurrentType(null);
    }
  };

  const getColorClasses = (color) => {
    const colors = {
      blue: 'bg-blue-600 hover:bg-blue-700 text-white',
      indigo: 'bg-indigo-600 hover:bg-indigo-700 text-white',
      green: 'bg-green-600 hover:bg-green-700 text-white',
      purple: 'bg-purple-600 hover:bg-purple-700 text-white',
      orange: 'bg-orange-600 hover:bg-orange-700 text-white',
      teal: 'bg-teal-600 hover:bg-teal-700 text-white',
      pink: 'bg-pink-600 hover:bg-pink-700 text-white',
      cyan: 'bg-cyan-600 hover:bg-cyan-700 text-white'
    };
    return colors[color] || colors.blue;
  };

  return (
    <div className="bg-white rounded-lg shadow-md p-6">
      <div className="flex items-center mb-6">
        <Sparkles className="w-6 h-6 text-purple-600 mr-3" />
        <div>
          <h2 className="text-xl font-semibold text-gray-900">AI Generation Options</h2>
          <p className="text-sm text-gray-500">Generate various AI-powered content from your transcription</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {generationOptions.map((option) => {
          const Icon = option.icon;
          const isGenerating = generating && currentType === option.type;
          const hasContent = generatedContent[option.type];

          return (
            <div key={option.type} className="relative">
              <button
                onClick={() => handleGenerate(option.type)}
                disabled={generating}
                className={`w-full p-4 rounded-lg transition-all duration-200 ${
                  getColorClasses(option.color)
                } disabled:opacity-50 disabled:cursor-not-allowed flex flex-col items-start text-left ${
                  hasContent ? 'ring-2 ring-offset-2 ring-green-500' : ''
                }`}
              >
                <div className="flex items-center justify-between w-full mb-2">
                  <Icon className={`w-5 h-5 ${isGenerating ? 'animate-spin' : ''}`} />
                  {hasContent && !isGenerating && (
                    <CheckSquare className="w-4 h-4" />
                  )}
                  {isGenerating && (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  )}
                </div>
                <div className="font-semibold text-sm mb-1">{option.label}</div>
                <div className="text-xs opacity-90">{option.description}</div>
              </button>
            </div>
          );
        })}
      </div>

      {/* Display generated content */}
      {Object.keys(generatedContent).length > 0 && (
        <div className="space-y-4">
          <h3 className="text-lg font-semibold text-gray-900 mb-3">Generated Content</h3>
          {Object.entries(generatedContent).map(([type, data]) => {
            const option = generationOptions.find(o => o.type === type);
            const isExpanded = expandedType === type;

            return (
              <div key={type} className="border border-gray-200 rounded-lg overflow-hidden">
                <button
                  onClick={() => setExpandedType(isExpanded ? null : type)}
                  className="w-full px-4 py-3 bg-gray-50 hover:bg-gray-100 transition-colors flex items-center justify-between"
                >
                  <div className="flex items-center">
                    {React.createElement(option.icon, { className: 'w-5 h-5 mr-2 text-gray-600' })}
                    <span className="font-semibold text-gray-900">{option.label}</span>
                    {data.model && (
                      <span className="ml-2 text-xs text-gray-500 bg-gray-200 px-2 py-1 rounded">
                        {data.model}
                      </span>
                    )}
                  </div>
                  <svg
                    className={`w-5 h-5 text-gray-500 transition-transform ${
                      isExpanded ? 'transform rotate-180' : ''
                    }`}
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </button>
                {isExpanded && (
                  <div className="p-4 bg-white">
                    <div className="prose prose-sm max-w-none">
                      <div className="text-gray-800 leading-relaxed whitespace-pre-wrap">
                        {data.content}
                      </div>
                    </div>
                    <div className="mt-4 flex gap-2">
                      <button
                        onClick={() => navigator.clipboard.writeText(data.content)}
                        className="text-sm text-blue-600 hover:text-blue-700 underline"
                      >
                        Copy to Clipboard
                      </button>
                      <button
                        onClick={() => handleGenerate(type)}
                        disabled={generating}
                        className="text-sm text-purple-600 hover:text-purple-700 underline disabled:opacity-50"
                      >
                        Regenerate
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {generating && (
        <div className="mt-4 p-4 bg-blue-50 border border-blue-200 rounded-lg">
          <div className="flex items-center">
            <Loader2 className="w-5 h-5 animate-spin text-blue-600 mr-3" />
            <div>
              <div className="font-semibold text-blue-900">
                Generating {generationOptions.find(o => o.type === currentType)?.label}...
              </div>
              <div className="text-sm text-blue-700">
                This may take up to 5 minutes. Please wait...
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AIGenerationPanel;
