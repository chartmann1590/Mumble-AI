import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:dio/dio.dart';
import '../services/api_service.dart';
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

  @override
  void initState() {
    super.initState();
    _loadOllamaConfig();
  }

  @override
  void dispose() {
    _messageController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _loadOllamaConfig() async {
    try {
      final apiService = Provider.of<ApiService>(context, listen: false);
      final response = await apiService.get(AppConstants.ollamaConfigEndpoint);
      final config = response.data;
      
      setState(() {
        _ollamaUrl = config['url'];
        _ollamaModel = config['model'];
      });
    } catch (e) {
      setState(() {
        _errorMessage = 'Failed to load Ollama configuration: ${e.toString()}';
      });
    }
  }

  Future<void> _sendMessage() async {
    final message = _messageController.text.trim();
    if (message.isEmpty || _isLoading) return;

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
      
      _scrollToBottom();
    } catch (e) {
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

    // Create a temporary Dio instance for Ollama API
    final dio = Dio();
    dio.options.baseUrl = _ollamaUrl!;
    dio.options.connectTimeout = 30000; // 30 seconds for AI responses
    dio.options.receiveTimeout = 30000;

    try {
      final response = await dio.post('/api/generate', data: {
        'model': _ollamaModel,
        'prompt': message,
        'stream': false,
      });

      return response.data['response'] ?? 'No response received';
    } catch (e) {
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

  void _clearChat() {
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
