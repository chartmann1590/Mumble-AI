import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/api_service.dart';
import '../services/storage_service.dart';
import '../services/logging_service.dart';
import '../models/memory.dart';
import '../widgets/loading_indicator.dart';
import '../utils/theme.dart';
import '../utils/constants.dart';

class MemoriesScreen extends StatefulWidget {
  const MemoriesScreen({Key? key}) : super(key: key);

  @override
  State<MemoriesScreen> createState() => _MemoriesScreenState();
}

class _MemoriesScreenState extends State<MemoriesScreen> {
  List<Memory> _memories = [];
  List<String> _users = [];
  bool _isLoading = true;
  String? _errorMessage;
  String? _selectedUser;
  String? _selectedCategory;

  @override
  void initState() {
    super.initState();
    
    // Log screen entry
    final loggingService = Provider.of<LoggingService>(context, listen: false);
    loggingService.logScreenLifecycle('MemoriesScreen', 'initState');
    
    _loadData();
  }

  Future<void> _loadData() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      // Load memories and users in parallel
      await Future.wait([
        _loadMemories(),
        _loadUsers(),
      ]);

      setState(() {
        _isLoading = false;
      });
    } catch (e, stackTrace) {
      final loggingService = Provider.of<LoggingService>(context, listen: false);
      loggingService.logException(e, stackTrace, screen: 'MemoriesScreen');
      
      setState(() {
        _isLoading = false;
        _errorMessage = 'Failed to load data: ${e.toString()}';
      });
    }
  }

  Future<void> _loadMemories() async {
    try {
      final apiService = Provider.of<ApiService>(context, listen: false);
      final storageService = Provider.of<StorageService>(context, listen: false);
      final loggingService = Provider.of<LoggingService>(context, listen: false);
      
      final queryParams = <String, dynamic>{};
      
      // Always include the selected user from storage
      final currentUser = await storageService.getSelectedUser();
      if (currentUser != null) {
        queryParams['user'] = currentUser;
      }
      
      if (_selectedCategory != null) {
        queryParams['category'] = _selectedCategory;
      }

      final response = await apiService.get(
        AppConstants.memoriesEndpoint,
        queryParameters: queryParams,
      );

      final memories = (response.data as List)
          .map((json) => Memory.fromJson(json))
          .toList();

      setState(() {
        _memories = memories;
      });
      
      loggingService.info('Memories loaded successfully', screen: 'MemoriesScreen', data: {
        'count': memories.length,
        'user': currentUser,
        'category': _selectedCategory,
      });
    } catch (e, stackTrace) {
      final loggingService = Provider.of<LoggingService>(context, listen: false);
      loggingService.logException(e, stackTrace, screen: 'MemoriesScreen');
      throw Exception('Failed to load memories: $e');
    }
  }

  Future<void> _loadUsers() async {
    try {
      final apiService = Provider.of<ApiService>(context, listen: false);
      final response = await apiService.get(AppConstants.usersEndpoint);
      
      setState(() {
        _users = (response.data as List).map((item) => item.toString()).toList();
      });
    } catch (e, stackTrace) {
      final loggingService = Provider.of<LoggingService>(context, listen: false);
      loggingService.logException(e, stackTrace, screen: 'MemoriesScreen');
      
      // Don't throw error for users, just log it
      setState(() {
        _users = [];
      });
    }
  }

  Future<void> _deleteMemory(int memoryId) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete Memory'),
        content: const Text('Are you sure you want to delete this memory?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            style: TextButton.styleFrom(primary: AppTheme.errorColor),
            child: const Text('Delete'),
          ),
        ],
      ),
    );

    if (confirmed == true) {
      try {
        final apiService = Provider.of<ApiService>(context, listen: false);
        final loggingService = Provider.of<LoggingService>(context, listen: false);
        
        loggingService.logUserAction('Delete Memory', screen: 'MemoriesScreen', data: {
          'memoryId': memoryId,
        });
        
        await apiService.delete('${AppConstants.memoriesEndpoint}/$memoryId');
        
        setState(() {
          _memories.removeWhere((memory) => memory.id == memoryId);
        });

        loggingService.info('Memory deleted successfully', screen: 'MemoriesScreen', data: {
          'memoryId': memoryId,
        });

        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Memory deleted successfully'),
              backgroundColor: AppTheme.successColor,
            ),
          );
        }
      } catch (e, stackTrace) {
        final loggingService = Provider.of<LoggingService>(context, listen: false);
        loggingService.logException(e, stackTrace, screen: 'MemoriesScreen');
        
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('Failed to delete memory: ${e.toString()}'),
              backgroundColor: AppTheme.errorColor,
            ),
          );
        }
      }
    }
  }

  void _showAddMemoryDialog() {
    showDialog(
      context: context,
      builder: (context) => _AddMemoryDialog(
        users: _users,
        onMemoryAdded: () {
          _loadMemories();
        },
      ),
    );
  }

  void _showEditMemoryDialog(Memory memory) {
    showDialog(
      context: context,
      builder: (context) => _EditMemoryDialog(
        memory: memory,
        users: _users,
        onMemoryUpdated: () {
          _loadMemories();
        },
      ),
    );
  }

  Color _getImportanceColor(int importance) {
    if (importance >= 8) return AppTheme.errorColor;
    if (importance >= 5) return AppTheme.warningColor;
    return AppTheme.primaryColor;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Memories'),
        actions: [
          IconButton(
            icon: const Icon(Icons.chat),
            onPressed: () {
              Navigator.pushNamed(context, '/chat');
            },
            tooltip: 'Ask AI about your memories',
          ),
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadData,
            tooltip: 'Refresh',
          ),
        ],
      ),
      body: _isLoading
          ? const LoadingIndicator(message: 'Loading memories...')
          : _errorMessage != null
              ? _buildErrorState()
              : _memories.isEmpty
                  ? _buildEmptyState()
                  : Column(
                      children: [
                        _buildFilters(),
                        Expanded(
                          child: RefreshIndicator(
                            onRefresh: _loadMemories,
                            child: ListView.builder(
                              padding: const EdgeInsets.all(AppTheme.spacingM),
                              itemCount: _memories.length,
                              itemBuilder: (context, index) {
                                final memory = _memories[index];
                                return _buildMemoryCard(memory);
                              },
                            ),
                          ),
                        ),
                      ],
                    ),
      floatingActionButton: FloatingActionButton(
        onPressed: _showAddMemoryDialog,
        child: const Icon(Icons.add),
      ),
    );
  }

  Widget _buildErrorState() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppTheme.spacingL),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(
              Icons.error_outline,
              size: 64,
              color: AppTheme.errorColor,
            ),
            const SizedBox(height: AppTheme.spacingM),
            Text(
              'Error Loading Memories',
              style: Theme.of(context).textTheme.headlineSmall,
            ),
            const SizedBox(height: AppTheme.spacingS),
            Text(
              _errorMessage!,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: AppTheme.textSecondary,
              ),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: AppTheme.spacingL),
            ElevatedButton.icon(
              onPressed: _loadData,
              icon: const Icon(Icons.refresh),
              label: const Text('Retry'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppTheme.spacingL),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(
              Icons.psychology_outlined,
              size: 64,
              color: AppTheme.textTertiary,
            ),
            const SizedBox(height: AppTheme.spacingM),
            Text(
              'No Memories',
              style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                color: AppTheme.textSecondary,
              ),
            ),
            const SizedBox(height: AppTheme.spacingS),
            Text(
              'Memories will appear here as the AI learns about users',
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: AppTheme.textTertiary,
              ),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: AppTheme.spacingL),
            ElevatedButton.icon(
              onPressed: _showAddMemoryDialog,
              icon: const Icon(Icons.add),
              label: const Text('Add Memory'),
            ),
            const SizedBox(height: AppTheme.spacingM),
            TextButton.icon(
              onPressed: () {
                Navigator.pushNamed(context, '/chat');
              },
              icon: const Icon(Icons.chat),
              label: const Text('Ask AI about memories'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildFilters() {
    return Container(
      padding: const EdgeInsets.all(AppTheme.spacingM),
      decoration: BoxDecoration(
        color: Theme.of(context).scaffoldBackgroundColor,
        border: const Border(
          bottom: BorderSide(color: AppTheme.borderColor),
        ),
      ),
      child: Row(
        children: [
          Expanded(
            child: DropdownButtonFormField<String>(
              value: _selectedUser,
              decoration: const InputDecoration(
                labelText: 'User',
                border: OutlineInputBorder(),
                contentPadding: EdgeInsets.symmetric(
                  horizontal: AppTheme.spacingM,
                  vertical: AppTheme.spacingS,
                ),
              ),
              items: [
                const DropdownMenuItem<String>(
                  value: null,
                  child: Text('All Users'),
                ),
                ..._users.map((user) => DropdownMenuItem<String>(
                  value: user,
                  child: Text(user),
                )),
              ],
              onChanged: (value) {
                setState(() {
                  _selectedUser = value;
                });
                _loadMemories();
              },
            ),
          ),
          const SizedBox(width: AppTheme.spacingM),
          Expanded(
            child: DropdownButtonFormField<String>(
              value: _selectedCategory,
              decoration: const InputDecoration(
                labelText: 'Category',
                border: OutlineInputBorder(),
                contentPadding: EdgeInsets.symmetric(
                  horizontal: AppTheme.spacingM,
                  vertical: AppTheme.spacingS,
                ),
              ),
              items: [
                const DropdownMenuItem<String>(
                  value: null,
                  child: Text('All Categories'),
                ),
                ...AppConstants.memoryCategories.map((category) => DropdownMenuItem<String>(
                  value: category,
                  child: Text(AppConstants.memoryCategoryDisplayNames[category] ?? category),
                )),
              ],
              onChanged: (value) {
                setState(() {
                  _selectedCategory = value;
                });
                _loadMemories();
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMemoryCard(Memory memory) {
    return Card(
      margin: const EdgeInsets.only(bottom: AppTheme.spacingS),
      child: InkWell(
        onTap: () => _showEditMemoryDialog(memory),
        borderRadius: BorderRadius.circular(AppTheme.radiusL),
        child: Padding(
          padding: const EdgeInsets.all(AppTheme.spacingM),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: AppTheme.spacingS,
                      vertical: AppTheme.spacingXS,
                    ),
                    decoration: BoxDecoration(
                      color: _getImportanceColor(memory.importance).withOpacity(0.1),
                      borderRadius: BorderRadius.circular(AppTheme.radiusS),
                      border: Border.all(
                        color: _getImportanceColor(memory.importance).withOpacity(0.3),
                      ),
                    ),
                    child: Text(
                      memory.importanceLevel,
                      style: TextStyle(
                        color: _getImportanceColor(memory.importance),
                        fontWeight: FontWeight.w600,
                        fontSize: 12,
                      ),
                    ),
                  ),
                  const SizedBox(width: AppTheme.spacingS),
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: AppTheme.spacingS,
                      vertical: AppTheme.spacingXS,
                    ),
                    decoration: BoxDecoration(
                      color: AppTheme.primaryColor.withOpacity(0.1),
                      borderRadius: BorderRadius.circular(AppTheme.radiusS),
                      border: Border.all(
                        color: AppTheme.primaryColor.withOpacity(0.3),
                      ),
                    ),
                    child: Text(
                      memory.categoryDisplay,
                      style: const TextStyle(
                        color: AppTheme.primaryColor,
                        fontWeight: FontWeight.w600,
                        fontSize: 12,
                      ),
                    ),
                  ),
                  const Spacer(),
                  PopupMenuButton<String>(
                    onSelected: (value) {
                      if (value == 'edit') {
                        _showEditMemoryDialog(memory);
                      } else if (value == 'delete') {
                        _deleteMemory(memory.id);
                      }
                    },
                    itemBuilder: (context) => [
                      const PopupMenuItem(
                        value: 'edit',
                        child: ListTile(
                          leading: Icon(Icons.edit),
                          title: Text('Edit'),
                          contentPadding: EdgeInsets.zero,
                        ),
                      ),
                      const PopupMenuItem(
                        value: 'delete',
                        child: ListTile(
                          leading: Icon(Icons.delete, color: AppTheme.errorColor),
                          title: Text('Delete', style: TextStyle(color: AppTheme.errorColor)),
                          contentPadding: EdgeInsets.zero,
                        ),
                      ),
                    ],
                  ),
                ],
              ),
              const SizedBox(height: AppTheme.spacingS),
              Text(
                memory.userName,
                style: Theme.of(context).textTheme.titleSmall?.copyWith(
                  fontWeight: FontWeight.w600,
                  color: AppTheme.textSecondary,
                ),
              ),
              const SizedBox(height: AppTheme.spacingS),
              Text(
                memory.content,
                style: AppTheme.messageBubbleStyle,
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
              ),
              if (memory.tags.isNotEmpty) ...[
                const SizedBox(height: AppTheme.spacingS),
                Wrap(
                  spacing: AppTheme.spacingXS,
                  runSpacing: AppTheme.spacingXS,
                  children: memory.tags.map((tag) => Chip(
                    label: Text(tag),
                    backgroundColor: AppTheme.backgroundColor,
                    labelStyle: const TextStyle(fontSize: 12),
                  )).toList(),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _AddMemoryDialog extends StatefulWidget {
  final List<String> users;
  final VoidCallback onMemoryAdded;

  const _AddMemoryDialog({
    Key? key,
    required this.users,
    required this.onMemoryAdded,
  }) : super(key: key);

  @override
  State<_AddMemoryDialog> createState() => _AddMemoryDialogState();
}

class _AddMemoryDialogState extends State<_AddMemoryDialog> {
  final _formKey = GlobalKey<FormState>();
  final _userController = TextEditingController();
  final _contentController = TextEditingController();
  String _selectedCategory = 'other';
  int _importance = 5;

  @override
  void dispose() {
    _userController.dispose();
    _contentController.dispose();
    super.dispose();
  }

  Future<void> _saveMemory() async {
    if (!_formKey.currentState!.validate()) return;

    try {
      final apiService = Provider.of<ApiService>(context, listen: false);
      final loggingService = Provider.of<LoggingService>(context, listen: false);
      
      loggingService.logUserAction('Add Memory', screen: 'MemoriesScreen', data: {
        'user': _userController.text.trim(),
        'category': _selectedCategory,
        'importance': _importance,
      });
      
      await apiService.post(AppConstants.memoriesEndpoint, data: {
        'user_name': _userController.text.trim(),
        'category': _selectedCategory,
        'content': _contentController.text.trim(),
        'importance': _importance,
        'tags': [],
      });

      loggingService.info('Memory added successfully', screen: 'MemoriesScreen');

      widget.onMemoryAdded();
      Navigator.pop(context);

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Memory added successfully'),
            backgroundColor: AppTheme.successColor,
          ),
        );
      }
    } catch (e, stackTrace) {
      final loggingService = Provider.of<LoggingService>(context, listen: false);
      loggingService.logException(e, stackTrace, screen: 'MemoriesScreen');
      
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Failed to add memory: ${e.toString()}'),
            backgroundColor: AppTheme.errorColor,
          ),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Add Memory'),
      content: Form(
        key: _formKey,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextFormField(
                controller: _userController,
                decoration: const InputDecoration(
                  labelText: 'User Name',
                  border: OutlineInputBorder(),
                ),
                validator: (value) {
                  if (value == null || value.trim().isEmpty) {
                    return 'Please enter a user name';
                  }
                  return null;
                },
              ),
              const SizedBox(height: AppTheme.spacingM),
              DropdownButtonFormField<String>(
                value: _selectedCategory,
                decoration: const InputDecoration(
                  labelText: 'Category',
                  border: OutlineInputBorder(),
                ),
                items: AppConstants.memoryCategories.map((category) => DropdownMenuItem<String>(
                  value: category,
                  child: Text(AppConstants.memoryCategoryDisplayNames[category] ?? category),
                )).toList(),
                onChanged: (value) {
                  setState(() {
                    _selectedCategory = value!;
                  });
                },
              ),
              const SizedBox(height: AppTheme.spacingM),
              TextFormField(
                controller: _contentController,
                decoration: const InputDecoration(
                  labelText: 'Content',
                  border: OutlineInputBorder(),
                ),
                maxLines: 3,
                validator: (value) {
                  if (value == null || value.trim().isEmpty) {
                    return 'Please enter memory content';
                  }
                  return null;
                },
              ),
              const SizedBox(height: AppTheme.spacingM),
              Row(
                children: [
                  const Text('Importance: '),
                  Expanded(
                    child: Slider(
                      value: _importance.toDouble(),
                      min: 1,
                      max: 10,
                      divisions: 9,
                      label: _importance.toString(),
                      onChanged: (value) {
                        setState(() {
                          _importance = value.round();
                        });
                      },
                    ),
                  ),
                  Text(_importance.toString()),
                ],
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        ElevatedButton(
          onPressed: _saveMemory,
          child: const Text('Save'),
        ),
      ],
    );
  }
}

class _EditMemoryDialog extends StatefulWidget {
  final Memory memory;
  final List<String> users;
  final VoidCallback onMemoryUpdated;

  const _EditMemoryDialog({
    Key? key,
    required this.memory,
    required this.users,
    required this.onMemoryUpdated,
  }) : super(key: key);

  @override
  State<_EditMemoryDialog> createState() => _EditMemoryDialogState();
}

class _EditMemoryDialogState extends State<_EditMemoryDialog> {
  final _formKey = GlobalKey<FormState>();
  late TextEditingController _userController;
  late TextEditingController _contentController;
  late String _selectedCategory;
  late int _importance;

  @override
  void initState() {
    super.initState();
    _userController = TextEditingController(text: widget.memory.userName);
    _contentController = TextEditingController(text: widget.memory.content);
    _selectedCategory = widget.memory.category;
    _importance = widget.memory.importance;
  }

  @override
  void dispose() {
    _userController.dispose();
    _contentController.dispose();
    super.dispose();
  }

  Future<void> _updateMemory() async {
    if (!_formKey.currentState!.validate()) return;

    try {
      final apiService = Provider.of<ApiService>(context, listen: false);
      final loggingService = Provider.of<LoggingService>(context, listen: false);
      
      loggingService.logUserAction('Update Memory', screen: 'MemoriesScreen', data: {
        'memoryId': widget.memory.id,
        'user': _userController.text.trim(),
        'category': _selectedCategory,
        'importance': _importance,
      });
      
      await apiService.put('${AppConstants.memoriesEndpoint}/${widget.memory.id}', data: {
        'user_name': _userController.text.trim(),
        'category': _selectedCategory,
        'content': _contentController.text.trim(),
        'importance': _importance,
        'tags': widget.memory.tags,
      });

      loggingService.info('Memory updated successfully', screen: 'MemoriesScreen', data: {
        'memoryId': widget.memory.id,
      });

      widget.onMemoryUpdated();
      Navigator.pop(context);

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Memory updated successfully'),
            backgroundColor: AppTheme.successColor,
          ),
        );
      }
    } catch (e, stackTrace) {
      final loggingService = Provider.of<LoggingService>(context, listen: false);
      loggingService.logException(e, stackTrace, screen: 'MemoriesScreen');
      
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Failed to update memory: ${e.toString()}'),
            backgroundColor: AppTheme.errorColor,
          ),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Edit Memory'),
      content: Form(
        key: _formKey,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextFormField(
                controller: _userController,
                decoration: const InputDecoration(
                  labelText: 'User Name',
                  border: OutlineInputBorder(),
                ),
                validator: (value) {
                  if (value == null || value.trim().isEmpty) {
                    return 'Please enter a user name';
                  }
                  return null;
                },
              ),
              const SizedBox(height: AppTheme.spacingM),
              DropdownButtonFormField<String>(
                value: _selectedCategory,
                decoration: const InputDecoration(
                  labelText: 'Category',
                  border: OutlineInputBorder(),
                ),
                items: AppConstants.memoryCategories.map((category) => DropdownMenuItem<String>(
                  value: category,
                  child: Text(AppConstants.memoryCategoryDisplayNames[category] ?? category),
                )).toList(),
                onChanged: (value) {
                  setState(() {
                    _selectedCategory = value!;
                  });
                },
              ),
              const SizedBox(height: AppTheme.spacingM),
              TextFormField(
                controller: _contentController,
                decoration: const InputDecoration(
                  labelText: 'Content',
                  border: OutlineInputBorder(),
                ),
                maxLines: 3,
                validator: (value) {
                  if (value == null || value.trim().isEmpty) {
                    return 'Please enter memory content';
                  }
                  return null;
                },
              ),
              const SizedBox(height: AppTheme.spacingM),
              Row(
                children: [
                  const Text('Importance: '),
                  Expanded(
                    child: Slider(
                      value: _importance.toDouble(),
                      min: 1,
                      max: 10,
                      divisions: 9,
                      label: _importance.toString(),
                      onChanged: (value) {
                        setState(() {
                          _importance = value.round();
                        });
                      },
                    ),
                  ),
                  Text(_importance.toString()),
                ],
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        ElevatedButton(
          onPressed: _updateMemory,
          child: const Text('Update'),
        ),
      ],
    );
  }
}
