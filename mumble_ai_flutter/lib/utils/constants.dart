class AppConstants {
  // App Info
  static const String appName = 'Mumble AI Control Panel';
  static const String appVersion = '1.0.0';
  
  // API Endpoints
  static const String healthEndpoint = '/api/stats';
  static const String statsEndpoint = '/api/stats';
  static const String conversationsEndpoint = '/api/conversations';
  static const String memoriesEndpoint = '/api/memories';
  static const String scheduleEndpoint = '/api/schedule';
  static const String emailSettingsEndpoint = '/api/email/settings';
  static const String emailLogsEndpoint = '/api/email/logs';
  static const String emailMappingsEndpoint = '/api/email/mappings';
  static const String ollamaConfigEndpoint = '/api/ollama/config';
  static const String ollamaModelsEndpoint = '/api/ollama/models';
  static const String visionConfigEndpoint = '/api/ollama/vision_config';
  static const String visionModelsEndpoint = '/api/ollama/vision_models';
  static const String memoryModelConfigEndpoint = '/api/ollama/memory_model_config';
  static const String ttsEngineEndpoint = '/api/tts/engine';
  static const String piperVoicesEndpoint = '/api/piper/voices';
  static const String piperCurrentEndpoint = '/api/piper/current';
  static const String piperPreviewEndpoint = '/api/piper/preview';
  static const String sileroVoicesEndpoint = '/api/silero/voices';
  static const String sileroCurrentEndpoint = '/api/silero/current';
  static const String sileroPreviewEndpoint = '/api/silero/preview';
  static const String chatterboxVoicesEndpoint = '/api/chatterbox/voices';
  static const String chatterboxCurrentEndpoint = '/api/chatterbox/current';
  static const String chatterboxPreviewEndpoint = '/api/chatterbox/preview';
  static const String personaEndpoint = '/api/persona';
  static const String personaEnhanceEndpoint = '/api/persona/enhance';
  static const String whisperLanguageEndpoint = '/api/whisper/language';
  static const String advancedSettingsEndpoint = '/api/advanced-settings';
  static const String usersEndpoint = '/api/users';
  static const String scheduleUsersEndpoint = '/api/schedule/users';
  static const String upcomingEventsEndpoint = '/api/schedule/upcoming';
  static const String testEmailEndpoint = '/api/email/test';
  static const String generateSignatureEndpoint = '/api/email/generate-signature';
  static const String retryEmailEndpoint = '/api/email/retry';

  // Default Values
  static const String defaultServerUrl = 'http://192.168.1.100:5002';
  static const int defaultTimeout = 10000; // 10 seconds
  static const int defaultPageSize = 50;
  static const int maxPageSize = 200;

  // Memory Categories
  static const List<String> memoryCategories = [
    'preference',
    'fact',
    'schedule',
    'task',
    'other',
  ];

  // Memory Category Display Names
  static const Map<String, String> memoryCategoryDisplayNames = {
    'preference': 'Preference',
    'fact': 'Fact',
    'schedule': 'Schedule',
    'task': 'Task',
    'other': 'Other',
  };

  // TTS Engines
  static const List<String> ttsEngines = [
    'piper',
    'silero',
    'chatterbox',
  ];

  // TTS Engine Display Names
  static const Map<String, String> ttsEngineDisplayNames = {
    'piper': 'Piper TTS (CPU)',
    'silero': 'Silero TTS (GPU)',
    'chatterbox': 'Chatterbox TTS (Voice Cloning)',
  };

  // Email Types
  static const List<String> emailTypes = [
    'reply',
    'summary',
    'test',
    'other',
  ];

  // Email Directions
  static const List<String> emailDirections = [
    'sent',
    'received',
  ];

  // Email Statuses
  static const List<String> emailStatuses = [
    'success',
    'error',
  ];

  // Reminder Minutes Options
  static const List<int> reminderMinutesOptions = [
    15,
    30,
    60,
    120,
    240,
  ];

  // Reminder Minutes Display Names
  static const Map<int, String> reminderMinutesDisplayNames = {
    15: '15 minutes before',
    30: '30 minutes before',
    60: '1 hour before',
    120: '2 hours before',
    240: '4 hours before',
  };

  // Whisper Languages
  static const List<String> whisperLanguages = [
    'auto',
    'en',
    'es',
    'fr',
    'de',
    'it',
    'pt',
    'ru',
    'ja',
    'ko',
    'zh',
  ];

  // Whisper Language Display Names
  static const Map<String, String> whisperLanguageDisplayNames = {
    'auto': 'Auto-detect',
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
  };

  // Timezones
  static const List<String> timezones = [
    'America/New_York',
    'America/Chicago',
    'America/Denver',
    'America/Los_Angeles',
    'Europe/London',
    'Europe/Paris',
    'Europe/Berlin',
    'Asia/Tokyo',
    'Asia/Shanghai',
    'Australia/Sydney',
  ];

  // Timezone Display Names
  static const Map<String, String> timezoneDisplayNames = {
    'America/New_York': 'Eastern Time (ET)',
    'America/Chicago': 'Central Time (CT)',
    'America/Denver': 'Mountain Time (MT)',
    'America/Los_Angeles': 'Pacific Time (PT)',
    'Europe/London': 'Greenwich Mean Time (GMT)',
    'Europe/Paris': 'Central European Time (CET)',
    'Europe/Berlin': 'Central European Time (CET)',
    'Asia/Tokyo': 'Japan Standard Time (JST)',
    'Asia/Shanghai': 'China Standard Time (CST)',
    'Australia/Sydney': 'Australian Eastern Time (AET)',
  };
}
