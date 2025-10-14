import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/storage_service.dart';
import '../services/api_service.dart';
import '../models/stats.dart';
import '../models/schedule_event.dart';
import '../widgets/stat_card.dart';
import '../widgets/loading_indicator.dart';
import '../utils/theme.dart';
import '../utils/constants.dart';
import 'main_scaffold.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({Key? key}) : super(key: key);

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  Stats? _stats;
  List<ScheduleEvent> _upcomingEvents = [];
  bool _isLoading = true;
  String? _errorMessage;

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  Future<void> _loadData() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final apiService = Provider.of<ApiService>(context, listen: false);
      final storageService = Provider.of<StorageService>(context, listen: false);
      
      // Load saved server URL
      final savedUrl = await storageService.getServerUrl();
      if (savedUrl != null) {
        apiService.setBaseUrl(savedUrl);
      }

      // Load stats and upcoming events in parallel
      await Future.wait([
        _loadStats(),
        _loadUpcomingEvents(),
      ]);

      if (mounted) {
        setState(() {
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isLoading = false;
          _errorMessage = 'Failed to load data: ${e.toString()}';
        });
      }
    }
  }

  Future<void> _loadStats() async {
    try {
      final apiService = Provider.of<ApiService>(context, listen: false);
      final response = await apiService.get(AppConstants.statsEndpoint);
      final stats = Stats.fromJson(response.data);
      
      if (mounted) {
        setState(() {
          _stats = stats;
        });
      }
    } catch (e) {
      throw Exception('Failed to load statistics: $e');
    }
  }

  Future<void> _loadUpcomingEvents() async {
    try {
      final apiService = Provider.of<ApiService>(context, listen: false);
      final response = await apiService.get(
        AppConstants.upcomingEventsEndpoint,
        queryParameters: {'days': 7, 'limit': 5},
      );
      
      final events = (response.data as List)
          .map((json) => ScheduleEvent.fromJson(json))
          .toList();
      
      if (mounted) {
        setState(() {
          _upcomingEvents = events;
        });
      }
    } catch (e) {
      // Don't throw error for upcoming events, just log it
      if (mounted) {
        setState(() {
          _upcomingEvents = [];
        });
      }
    }
  }


  @override
  Widget build(BuildContext context) {
    return MainScaffold(
      title: 'Dashboard',
      actions: [
        IconButton(
          icon: const Icon(Icons.refresh),
          onPressed: _loadData,
        ),
          PopupMenuButton<String>(
            onSelected: (value) {
              switch (value) {
                case 'settings':
                  // TODO: Navigate to settings
                  break;
                case 'disconnect':
                  _disconnect();
                  break;
              }
            },
            itemBuilder: (context) => [
              const PopupMenuItem(
                value: 'settings',
                child: ListTile(
                  leading: Icon(Icons.settings),
                  title: Text('Settings'),
                  contentPadding: EdgeInsets.zero,
                ),
              ),
              const PopupMenuItem(
                value: 'disconnect',
                child: ListTile(
                  leading: Icon(Icons.logout),
                  title: Text('Disconnect'),
                  contentPadding: EdgeInsets.zero,
                ),
              ),
            ],
          ),
        ],
      body: _isLoading
          ? const LoadingIndicator(message: 'Loading dashboard...')
          : _errorMessage != null
              ? _buildErrorState()
              : RefreshIndicator(
                  onRefresh: _loadData,
                  child: SingleChildScrollView(
                    physics: const AlwaysScrollableScrollPhysics(),
                    padding: const EdgeInsets.all(AppTheme.spacingM),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        // Statistics Cards
                        Text(
                          'Statistics',
                          style: Theme.of(context).textTheme.headlineSmall,
                        ),
                        const SizedBox(height: AppTheme.spacingM),
                        GridView.count(
                          crossAxisCount: 2,
                          shrinkWrap: true,
                          physics: const NeverScrollableScrollPhysics(),
                          childAspectRatio: 1.5,
                          crossAxisSpacing: AppTheme.spacingM,
                          mainAxisSpacing: AppTheme.spacingM,
                          children: [
                            StatCard(
                              title: 'Total Messages',
                              value: _stats?.totalMessages.toString() ?? '0',
                              icon: Icons.message,
                              iconColor: AppTheme.primaryColor,
                            ),
                            StatCard(
                              title: 'Unique Users',
                              value: _stats?.uniqueUsers.toString() ?? '0',
                              icon: Icons.people,
                              iconColor: AppTheme.infoColor,
                            ),
                            StatCard(
                              title: 'Voice Messages',
                              value: _stats?.voiceMessages.toString() ?? '0',
                              icon: Icons.mic,
                              iconColor: AppTheme.successColor,
                            ),
                            StatCard(
                              title: 'Text Messages',
                              value: _stats?.textMessages.toString() ?? '0',
                              icon: Icons.chat,
                              iconColor: AppTheme.warningColor,
                            ),
                          ],
                        ),
                        const SizedBox(height: AppTheme.spacingXL),
                        
                        // Upcoming Events
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Text(
                              'Upcoming Events',
                              style: Theme.of(context).textTheme.headlineSmall,
                            ),
                            TextButton(
                              onPressed: () {
                                // TODO: Navigate to schedule screen
                              },
                              child: const Text('View All'),
                            ),
                          ],
                        ),
                        const SizedBox(height: AppTheme.spacingM),
                        _buildUpcomingEvents(),
                        const SizedBox(height: AppTheme.spacingXL),
                        
                        // Quick Actions
                        Text(
                          'Quick Actions',
                          style: Theme.of(context).textTheme.headlineSmall,
                        ),
                        const SizedBox(height: AppTheme.spacingM),
                        _buildQuickActions(),
                      ],
                    ),
                  ),
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
              'Connection Error',
              style: Theme.of(context).textTheme.headlineSmall,
            ),
            const SizedBox(height: AppTheme.spacingS),
            Text(
              _errorMessage ?? 'Unknown error occurred',
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
            const SizedBox(height: AppTheme.spacingM),
            OutlinedButton.icon(
              onPressed: _disconnect,
              icon: const Icon(Icons.logout),
              label: const Text('Change Server'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildUpcomingEvents() {
    if (_upcomingEvents.isEmpty) {
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(AppTheme.spacingL),
          child: Column(
            children: [
              const Icon(
                Icons.event_available,
                size: 48,
                color: AppTheme.textTertiary,
              ),
              const SizedBox(height: AppTheme.spacingM),
              Text(
                'No upcoming events',
                style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  color: AppTheme.textSecondary,
                ),
              ),
              const SizedBox(height: AppTheme.spacingS),
              Text(
                'Events scheduled for the next 7 days will appear here',
                style: Theme.of(context).textTheme.bodySmall,
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      );
    }

    return Column(
      children: _upcomingEvents.map((event) => Card(
        margin: const EdgeInsets.only(bottom: AppTheme.spacingS),
        child: ListTile(
          leading: CircleAvatar(
            backgroundColor: _getEventColor(event.importance),
            child: Text(
              event.importance.toString(),
              style: const TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
          title: Text(event.title),
          subtitle: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('👤 ${event.userName}'),
              Text('📅 ${event.formattedDate}${event.hasTime ? ' at ${event.formattedTime}' : ''}'),
              if (event.description != null && event.description!.isNotEmpty)
                Text('📝 ${event.description}'),
            ],
          ),
          trailing: const Icon(Icons.chevron_right),
          onTap: () {
            // TODO: Navigate to event details
          },
        ),
      )).toList(),
    );
  }

  Widget _buildQuickActions() {
    final actions = [
      {
        'title': 'AI Chat',
        'subtitle': 'Chat with the AI',
        'icon': Icons.chat,
        'color': AppTheme.primaryColor,
        'onTap': () {
          Navigator.pushNamed(context, '/chat');
        },
      },
      {
        'title': 'Conversations',
        'subtitle': 'View chat history',
        'icon': Icons.history,
        'color': AppTheme.infoColor,
        'onTap': () {
          Navigator.pushNamed(context, '/conversations');
        },
      },
      {
        'title': 'Memories',
        'subtitle': 'Manage AI memories',
        'icon': Icons.psychology,
        'color': AppTheme.successColor,
        'onTap': () {
          Navigator.pushNamed(context, '/memories');
        },
      },
      {
        'title': 'Schedule',
        'subtitle': 'Manage events',
        'icon': Icons.calendar_today,
        'color': AppTheme.warningColor,
        'onTap': () {
          Navigator.pushNamed(context, '/schedule');
        },
      },
      {
        'title': 'Voice Config',
        'subtitle': 'Configure TTS voices',
        'icon': Icons.record_voice_over,
        'color': AppTheme.infoColor,
        'onTap': () {
          Navigator.pushNamed(context, '/voice-config');
        },
      },
      {
        'title': 'Ollama Config',
        'subtitle': 'Configure AI models',
        'icon': Icons.psychology,
        'color': AppTheme.primaryColor,
        'onTap': () {
          Navigator.pushNamed(context, '/ollama-config');
        },
      },
      {
        'title': 'Email Settings',
        'subtitle': 'Configure email settings',
        'icon': Icons.email,
        'color': AppTheme.infoColor,
        'onTap': () {
          Navigator.pushNamed(context, '/email-settings');
        },
      },
      {
        'title': 'Email Logs',
        'subtitle': 'View email history',
        'icon': Icons.history,
        'color': AppTheme.textSecondary,
        'onTap': () {
          Navigator.pushNamed(context, '/email-logs');
        },
      },
      {
        'title': 'Persona',
        'subtitle': 'Manage AI personality',
        'icon': Icons.person,
        'color': AppTheme.successColor,
        'onTap': () {
          Navigator.pushNamed(context, '/persona');
        },
      },
      {
        'title': 'Advanced Settings',
        'subtitle': 'Fine-tune AI behavior',
        'icon': Icons.settings,
        'color': AppTheme.warningColor,
        'onTap': () {
          Navigator.pushNamed(context, '/advanced-settings');
        },
      },
      {
        'title': 'Whisper Language',
        'subtitle': 'Set speech recognition language',
        'icon': Icons.language,
        'color': AppTheme.primaryColor,
        'onTap': () {
          Navigator.pushNamed(context, '/whisper-language');
        },
      },
    ];

    return GridView.count(
      crossAxisCount: 2,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      childAspectRatio: 1.2,
      crossAxisSpacing: AppTheme.spacingM,
      mainAxisSpacing: AppTheme.spacingM,
      children: actions.map((action) => Card(
        child: InkWell(
          onTap: action['onTap'] as VoidCallback,
          borderRadius: BorderRadius.circular(AppTheme.radiusL),
          child: Padding(
            padding: const EdgeInsets.all(AppTheme.spacingM),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(
                  action['icon'] as IconData,
                  size: 32,
                  color: action['color'] as Color,
                ),
                const SizedBox(height: AppTheme.spacingS),
                Text(
                  action['title'] as String,
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                    fontWeight: FontWeight.w600,
                  ),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: AppTheme.spacingXS),
                Text(
                  action['subtitle'] as String,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: AppTheme.textSecondary,
                  ),
                  textAlign: TextAlign.center,
                ),
              ],
            ),
          ),
        ),
      )).toList(),
    );
  }

  Color _getEventColor(int importance) {
    if (importance >= 8) return AppTheme.errorColor;
    if (importance >= 5) return AppTheme.warningColor;
    return AppTheme.primaryColor;
  }

  Future<void> _disconnect() async {
    final storageService = Provider.of<StorageService>(context, listen: false);
    await storageService.removeServerUrl();
    if (mounted) {
      Navigator.pushReplacementNamed(context, '/connect');
    }
  }
}
