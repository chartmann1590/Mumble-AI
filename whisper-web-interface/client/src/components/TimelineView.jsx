import React, { useState } from 'react';
import { Copy, Check } from 'lucide-react';
import { formatTimestamp, getSpeakerColor } from '../utils/formatters';

const TimelineView = ({ segments }) => {
  const [copiedIndex, setCopiedIndex] = useState(null);

  const handleCopySegment = async (index, text) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedIndex(index);
      setTimeout(() => setCopiedIndex(null), 2000);
    } catch (error) {
      console.error('Failed to copy:', error);
    }
  };

  if (!segments || segments.length === 0) {
    return (
      <div className="bg-gray-50 rounded-lg p-4 text-gray-500 text-center">
        No segment data available
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Time
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Speaker
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Text
              </th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {segments.map((segment, index) => (
              <tr key={index} className="hover:bg-gray-50 transition-colors">
                <td className="px-4 py-3 whitespace-nowrap text-sm font-mono text-gray-600">
                  {formatTimestamp(segment.start)}
                </td>
                <td className="px-4 py-3 whitespace-nowrap">
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getSpeakerColor(segment.speaker)}`}>
                    {segment.speaker || 'Speaker 1'}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm text-gray-700">
                  {segment.text}
                </td>
                <td className="px-4 py-3 text-right">
                  <button
                    onClick={() => handleCopySegment(index, segment.text)}
                    className="text-gray-400 hover:text-gray-600 transition-colors"
                    title="Copy segment"
                  >
                    {copiedIndex === index ? (
                      <Check className="w-4 h-4 text-green-600" />
                    ) : (
                      <Copy className="w-4 h-4" />
                    )}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default TimelineView;
