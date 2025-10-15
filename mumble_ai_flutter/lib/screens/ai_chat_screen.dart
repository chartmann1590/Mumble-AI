import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:dio/dio.dart';
import '../services/api_service.dart';
import '../services/logging_service.dart';
import '../widgets/message_bubble.dart';
import '../utils/theme.dart';
import '../utils/constants.dart';

class ChatMessage {
  final String message;
  final bool isUser;
  final DateTime timestamp;

  ChatMessage({
    required this.message,
    required this.isUser,
    required this.timestamp,
  });
}

class AiChatScreen extends StatefulWidget {
  const AiChatScreen({Key? key}) : super(key: key);

  @override
  State<AiChatScreen> createState() => _AiChatScreenState();
}

class _AiChatScreenState extends State<AiChatScreen> {
  final _messageController = TextEditingController();
  final _scrollController = ScrollController();
  final List<ChatMessage> _messages = [];
  bool _isLoading = false;
  String? _errorMessage;
  String? _ollamaUrl;
  String? _ollamaModel;
  String? _botPersona;

  @override
  void initState() {
    super.initState();
    _loadOllamaConfig();
    
    // Log screen entry
    final loggingService = Provider.of<LoggingService>(context, listen: false);
    loggingService.logScreenLifecycle('AiChatScreen', 'initState');
  }

  @override
  void dispose() {
    _messageController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _loadOllamaConfig() async {
    final loggingService = Provider.of<LoggingService>(context, listen: false);
    final startTime = DateTime.now();
    
    try {
      final apiService = Provider.of<ApiService>(context, listen: false);
      final response = await apiService.get(AppConstants.ollamaConfigEndpoint);
      
      final data = apiService.safeCastResponseData(response.data);
      if (data != null) {
        setState(() {
          _ollamaUrl = data['url'];
          _ollamaModel = data['model'];
        });
        
        // Load bot persona
        await _loadBotPersona();
        
        final duration = DateTime.now().difference(startTime);
        loggingService.logPerformance('Load Ollama Config', duration, screen: 'AiChatScreen');
        loggingService.info('Ollama config loaded successfully', screen: 'AiChatScreen', data: {
          'ollamaUrl': _ollamaUrl,
          'ollamaModel': _ollamaModel,
        });
      } else {
        throw Exception('Invalid data format received from server');
      }
    } catch (e) {
      final duration = DateTime.now().difference(startTime);
      loggingService.logPerformance('Load Ollama Config (ERROR)', duration, screen: 'AiChatScreen');
      loggingService.logException(e, null, screen: 'AiChatScreen');
      
      setState(() {
        _errorMessage = 'Failed to load Ollama configuration: ${e.toString()}';
      });
    }
  }

  Future<void> _loadBotPersona() async {
    try {
      final apiService = Provider.of<ApiService>(context, listen: false);
      final response = await apiService.get(AppConstants.personaEndpoint);
      
      final data = apiService.safeCastResponseData(response.data);
      if (data != null) {
        setState(() {
          _botPersona = data['persona'] ?? '';
        });
      }
    } catch (e) {
      // Persona is optional, don't fail if it's not available
      final loggingService = Provider.of<LoggingService>(context, listen: false);
      loggingService.warning('Failed to load bot persona: ${e.toString()}', screen: 'AiChatScreen');
    }
  }

  Future<void> _sendMessage() async {
    final message = _messageController.text.trim();
    if (message.isEmpty || _isLoading) return;

    final loggingService = Provider.of<LoggingService>(context, listen: false);
    loggingService.logUserAction('Send AI Chat Message', screen: 'AiChatScreen', data: {
      'messageLength': message.length,
      'hasPersona': _botPersona != null && _botPersona!.isNotEmpty,
    });

    // Add user message
    final userMessage = ChatMessage(
      message: message,
      isUser: true,
      timestamp: DateTime.now(),
    );
    
    setState(() {
      _messages.add(userMessage);
      _isLoading = true;
      _errorMessage = null;
    });

    _messageController.clear();
    _scrollToBottom();

    try {
      // Send message to Ollama
      final response = await _sendToOllama(message);
      
      // Add AI response
      final aiMessage = ChatMessage(
        message: response,
        isUser: false,
        timestamp: DateTime.now(),
      );
      
      setState(() {
        _messages.add(aiMessage);
        _isLoading = false;
      });
      
      loggingService.info('AI Chat response received', screen: 'AiChatScreen', data: {
        'responseLength': response.length,
        'totalMessages': _messages.length,
      });
      
      // Log conversation to server
      await _logConversationToServer(message, response);
      
      _scrollToBottom();
    } catch (e) {
      loggingService.logException(e, null, screen: 'AiChatScreen');
      
      setState(() {
        _isLoading = false;
        _errorMessage = 'Failed to get AI response: ${e.toString()}';
      });
    }
  }

  Future<String> _sendToOllama(String message) async {
    if (_ollamaUrl == null || _ollamaModel == null) {
      throw Exception('Ollama configuration not available');
    }

    final loggingService = Provider.of<LoggingService>(context, listen: false);
    final startTime = DateTime.now();

    // Create a temporary Dio instance for Ollama API
    final dio = Dio();
    dio.options.baseUrl = _ollamaUrl!;
    dio.options.connectTimeout = 180000; // 3 minutes for AI responses
    dio.options.receiveTimeout = 180000; // 3 minutes for AI responses

    try {
      // Build the prompt with persona if available
      String fullPrompt = message;
      if (_botPersona != null && _botPersona!.isNotEmpty) {
        fullPrompt = '${_botPersona}\n\nUser: $message\nAssistant:';
      }

      loggingService.info('Sending message to Ollama', screen: 'AiChatScreen', data: {
        'ollamaUrl': _ollamaUrl,
        'model': _ollamaModel,
        'hasPersona': _botPersona != null && _botPersona!.isNotEmpty,
        'promptLength': fullPrompt.length,
      });

      final response = await dio.post('/api/generate', data: {
        'model': _ollamaModel,
        'prompt': fullPrompt,
        'stream': false,
        'options': {
          'temperature': 0.7,
          'top_p': 0.9,
          'max_tokens': 2048,
        }
      });

      final duration = DateTime.now().difference(startTime);
      loggingService.logPerformance('Ollama API Call', duration, screen: 'AiChatScreen', data: {
        'model': _ollamaModel,
        'responseLength': response.data['response']?.toString().length ?? 0,
      });

      return response.data['response'] ?? 'No response received';
    } catch (e) {
      final duration = DateTime.now().difference(startTime);
      loggingService.logPerformance('Ollama API Call (ERROR)', duration, screen: 'AiChatScreen');
      loggingService.logException(e, null, screen: 'AiChatScreen');
      
      throw Exception('Ollama API error: ${e.toString()}');
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance?.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  void _copyMessage(String message) {
    // TODO: Implement clipboard functionality
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('Copy functionality not implemented yet'),
        duration: Duration(seconds: 2),
      ),
    );
  }

  Future<void> _logConversationToServer(String userMessage, String aiResponse) async {
    try {
      final apiService = Provider.of<ApiService>(context, listen: false);
      final loggingService = Provider.of<LoggingService>(context, listen: false);
      
      await apiService.post('/api/conversations/ai_chat', data: {
        'user_message': userMessage,
        'ai_response': aiResponse,
        'timestamp': DateTime.now().toIso8601String(),
      });
      
      loggingService.info('AI Chat conversation logged to server', screen: 'AiChatScreen');
    } catch (e) {
      final loggingService = Provider.of<LoggingService>(context, listen: false);
      loggingService.warning('Failed to log AI chat conversation to server: ${e.toString()}', screen: 'AiChatScreen');
    }
  }

  void _clearChat() {
    final loggingService = Provider.of<LoggingService>(context, listen: false);
    
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Clear Chat'),
        content: const Text('Are you sure you want to clear all messages?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () {
              loggingService.logUserAction('Clear Chat', screen: 'AiChatScreen', data: {
                'messageCount': _messages.length,
              });
              
              setState(() {
                _messages.clear();
              });
              Navigator.pop(context);
            },
            child: const Text('Clear'),
          ),
        ],
      ),
    );
  }

  String _formatTimestamp(DateTime timestamp) {
    return '${timestamp.hour.toString().padLeft(2, '0')}:${timestamp.minute.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('AI Chat'),
        actions: [
          if (_messages.isNotEmpty)
            IconButton(
              icon: const Icon(Icons.clear_all),
              onPressed: _clearChat,
              tooltip: 'Clear Chat',
            ),
        ],
      ),
      body: Column(
        children: [
          // Error message
          if (_errorMessage != null)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(AppTheme.spacingM),
              color: AppTheme.errorColor.withOpacity(0.1),
              child: Row(
                children: [
                  const Icon(Icons.error_outline, color: AppTheme.errorColor),
                  const SizedBox(width: AppTheme.spacingS),
                  Expanded(
                    child: Text(
                      _errorMessage!,
                      style: const TextStyle(color: AppTheme.errorColor),
                    ),
                  ),
                  IconButton(
                    icon: const Icon(Icons.close, color: AppTheme.errorColor),
                    onPressed: () {
                      setState(() {
                        _errorMessage = null;
                      });
                    },
                  ),
                ],
              ),
            ),
          
          // Messages list
          Expanded(
            child: _messages.isEmpty
                ? Center(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        const Icon(
                          Icons.chat_bubble_outline,
                          size: 64,
                          color: AppTheme.textTertiary,
                        ),
                        const SizedBox(height: AppTheme.spacingM),
                        Text(
                          'Start a conversation',
                          style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                            color: AppTheme.textSecondary,
                          ),
                        ),
                        const SizedBox(height: AppTheme.spacingS),
                        Text(
                          'Send a message to begin chatting with the AI',
                          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                            color: AppTheme.textTertiary,
                          ),
                          textAlign: TextAlign.center,
                        ),
                      ],
                    ),
                  )
                : ListView.builder(
                    controller: _scrollController,
                    padding: const EdgeInsets.symmetric(vertical: AppTheme.spacingM),
                    itemCount: _messages.length + (_isLoading ? 1 : 0),
                    itemBuilder: (context, index) {
                      if (index == _messages.length && _isLoading) {
                        return Padding(
                          padding: const EdgeInsets.all(AppTheme.spacingM),
                          child: Row(
                            children: [
                              const CircleAvatar(
                                radius: 16,
                                backgroundColor: AppTheme.primaryColor,
                                child: Icon(
                                  Icons.smart_toy,
                                  size: 16,
                                  color: Colors.white,
                                ),
                              ),
                              const SizedBox(width: AppTheme.spacingS),
                              Expanded(
                                child: Card(
                                  child: Padding(
                                    padding: const EdgeInsets.all(AppTheme.spacingM),
                                    child: Row(
                                      mainAxisSize: MainAxisSize.min,
                                      children: const [
                                        SizedBox(
                                          width: 16,
                                          height: 16,
                                          child: CircularProgressIndicator(strokeWidth: 2),
                                        ),
                                        SizedBox(width: AppTheme.spacingS),
                                        Text('AI is thinking...'),
                                      ],
                                    ),
                                  ),
                                ),
                              ),
                            ],
                          ),
                        );
                      }

                      final message = _messages[index];
                      return MessageBubble(
                        message: message.message,
                        isUser: message.isUser,
                        timestamp: _formatTimestamp(message.timestamp),
                        onCopy: () => _copyMessage(message.message),
                      );
                    },
                  ),
          ),
          
          // Input area
          Container(
            padding: const EdgeInsets.all(AppTheme.spacingM),
            decoration: BoxDecoration(
              color: Theme.of(context).scaffoldBackgroundColor,
              border: const Border(
                top: BorderSide(color: AppTheme.borderColor),
              ),
            ),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _messageController,
                    decoration: const InputDecoration(
                      hintText: 'Type your message...',
                      border: OutlineInputBorder(),
                      contentPadding: EdgeInsets.symmetric(
                        horizontal: AppTheme.spacingM,
                        vertical: AppTheme.spacingS,
                      ),
                    ),
                    maxLines: null,
                    textInputAction: TextInputAction.send,
                    onSubmitted: (_) => _sendMessage(),
                    enabled: !_isLoading,
                  ),
                ),
                const SizedBox(width: AppTheme.spacingS),
                FloatingActionButton(
                  onPressed: _isLoading ? null : _sendMessage,
                  mini: true,
                  child: _isLoading
                      ? const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                          ),
                        )
                      : const Icon(Icons.send),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
