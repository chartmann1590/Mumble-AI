import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'utils/theme.dart';
import 'utils/constants.dart';
import 'services/storage_service.dart';
import 'services/api_service.dart';
import 'services/audio_service.dart';
import 'screens/server_connect_screen.dart';
import 'screens/dashboard_screen.dart';
import 'screens/ai_chat_screen.dart';
import 'screens/conversations_screen.dart';
import 'screens/memories_screen.dart';
import 'screens/schedule_screen.dart';
import 'screens/voice_config_screen.dart';
import 'screens/ollama_config_screen.dart';
import 'screens/email_settings_screen.dart';
import 'screens/email_logs_screen.dart';
import 'screens/persona_screen.dart';
import 'screens/advanced_settings_screen.dart';
import 'screens/whisper_language_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  
  // Initialize services
  final storageService = await StorageService.getInstance();
  final apiService = ApiService.getInstance();
  final audioService = AudioService.getInstance();
  
  runApp(MyApp(
    storageService: storageService,
    apiService: apiService,
    audioService: audioService,
  ));
}

class MyApp extends StatelessWidget {
  final StorageService storageService;
  final ApiService apiService;
  final AudioService audioService;

  const MyApp({
    Key? key,
    required this.storageService,
    required this.apiService,
    required this.audioService,
  }) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        Provider<StorageService>.value(value: storageService),
        Provider<ApiService>.value(value: apiService),
        Provider<AudioService>.value(value: audioService),
      ],
      child: MaterialApp(
        title: AppConstants.appName,
        theme: AppTheme.lightTheme,
        home: const ServerConnectScreen(),
                routes: {
                  '/connect': (context) => const ServerConnectScreen(),
                  '/dashboard': (context) => const DashboardScreen(),
                  '/chat': (context) => const AiChatScreen(),
                  '/conversations': (context) => const ConversationsScreen(),
                  '/memories': (context) => const MemoriesScreen(),
                  '/schedule': (context) => const ScheduleScreen(),
                  '/voice-config': (context) => const VoiceConfigScreen(),
                  '/ollama-config': (context) => const OllamaConfigScreen(),
                  '/email-settings': (context) => const EmailSettingsScreen(),
                  '/email-logs': (context) => const EmailLogsScreen(),
                  '/persona': (context) => const PersonaScreen(),
                  '/advanced-settings': (context) => const AdvancedSettingsScreen(),
                  '/whisper-language': (context) => const WhisperLanguageScreen(),
                },
        debugShowCheckedModeBanner: false,
      ),
    );
  }
}