import 'package:flutter/material.dart';
import '../utils/theme.dart';
import '../utils/constants.dart';

class AppDrawer extends StatelessWidget {
  const AppDrawer({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Drawer(
      child: Column(
        children: [
          _buildHeader(context),
          Expanded(
            child: _buildMenuItems(context),
          ),
          _buildFooter(context),
        ],
      ),
    );
  }

  Widget _buildHeader(BuildContext context) {
    return DrawerHeader(
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          colors: [AppTheme.primaryColor, AppTheme.secondaryColor],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.end,
        children: [
          const Icon(
            Icons.psychology,
            size: 48,
            color: Colors.white,
          ),
          const SizedBox(height: AppTheme.spacingS),
          Text(
            AppConstants.appName,
            style: Theme.of(context).textTheme.headlineSmall?.copyWith(
              color: Colors.white,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: AppTheme.spacingXS),
          Text(
            'AI Control Panel',
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: Colors.white70,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMenuItems(BuildContext context) {
    final menuItems = [
      {
        'title': 'Dashboard',
        'icon': Icons.dashboard,
        'route': '/dashboard',
        'color': AppTheme.primaryColor,
      },
      {
        'title': 'AI Chat',
        'icon': Icons.chat,
        'route': '/chat',
        'color': AppTheme.successColor,
      },
      {
        'title': 'Conversations',
        'icon': Icons.history,
        'route': '/conversations',
        'color': AppTheme.infoColor,
      },
      {
        'title': 'Memories',
        'icon': Icons.psychology,
        'route': '/memories',
        'color': AppTheme.warningColor,
      },
      {
        'title': 'Schedule',
        'icon': Icons.calendar_today,
        'route': '/schedule',
        'color': AppTheme.errorColor,
      },
      {
        'title': 'Ollama Config',
        'icon': Icons.settings_applications,
        'route': '/ollama-config',
        'color': AppTheme.primaryColor,
      },
      {
        'title': 'Voice Config',
        'icon': Icons.record_voice_over,
        'route': '/voice-config',
        'color': AppTheme.infoColor,
      },
      {
        'title': 'Email Settings',
        'icon': Icons.email,
        'route': '/email-settings',
        'color': AppTheme.textSecondary,
      },
      {
        'title': 'Email Logs',
        'icon': Icons.email_outlined,
        'route': '/email-logs',
        'color': AppTheme.textSecondary,
      },
      {
        'title': 'Persona',
        'icon': Icons.person,
        'route': '/persona',
        'color': AppTheme.successColor,
      },
      {
        'title': 'Advanced Settings',
        'icon': Icons.settings,
        'route': '/advanced-settings',
        'color': AppTheme.warningColor,
      },
      {
        'title': 'Whisper Language',
        'icon': Icons.language,
        'route': '/whisper-language',
        'color': AppTheme.primaryColor,
      },
    ];

    return ListView(
      padding: EdgeInsets.zero,
      children: [
        ...menuItems.map((item) => _buildMenuItem(
          context,
          title: item['title'] as String,
          icon: item['icon'] as IconData,
          route: item['route'] as String,
          color: item['color'] as Color,
        )),
      ],
    );
  }

  Widget _buildMenuItem(
    BuildContext context, {
    required String title,
    required IconData icon,
    required String route,
    required Color color,
  }) {
    return ListTile(
      leading: Container(
        padding: const EdgeInsets.all(AppTheme.spacingS),
        decoration: BoxDecoration(
          color: color.withOpacity(0.1),
          borderRadius: BorderRadius.circular(AppTheme.radiusM),
        ),
        child: Icon(
          icon,
          color: color,
          size: 20,
        ),
      ),
      title: Text(
        title,
        style: Theme.of(context).textTheme.bodyLarge?.copyWith(
          fontWeight: FontWeight.w500,
        ),
      ),
      onTap: () {
        Navigator.pop(context); // Close drawer
        Navigator.pushNamed(context, route);
      },
    );
  }

  Widget _buildFooter(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(AppTheme.spacingM),
      decoration: const BoxDecoration(
        color: AppTheme.backgroundColor,
        border: Border(
          top: BorderSide(color: AppTheme.borderColor),
        ),
      ),
      child: Column(
        children: [
          ListTile(
            leading: const Icon(
              Icons.info_outline,
              color: AppTheme.textSecondary,
            ),
            title: Text(
              'Version ${AppConstants.appVersion}',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: AppTheme.textSecondary,
              ),
            ),
            onTap: () {
              _showAboutDialog(context);
            },
          ),
          ListTile(
            leading: const Icon(
              Icons.settings,
              color: AppTheme.textSecondary,
            ),
            title: Text(
              'Server Settings',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: AppTheme.textSecondary,
              ),
            ),
            onTap: () {
              Navigator.pop(context); // Close drawer
              Navigator.pushNamed(context, '/connect');
            },
          ),
        ],
      ),
    );
  }

  void _showAboutDialog(BuildContext context) {
    showAboutDialog(
      context: context,
      applicationName: AppConstants.appName,
      applicationVersion: AppConstants.appVersion,
      applicationIcon: const Icon(
        Icons.psychology,
        size: 48,
        color: AppTheme.primaryColor,
      ),
      children: [
        const Text(
          'A comprehensive Flutter Android application for managing and controlling the Mumble AI system. This app provides a mobile interface to all the features available in the web control panel, plus additional mobile-specific functionality.',
        ),
        const SizedBox(height: AppTheme.spacingM),
        const Text(
          'Features:',
          style: TextStyle(fontWeight: FontWeight.bold),
        ),
        const Text('• AI Chat Interface'),
        const Text('• Ollama Configuration'),
        const Text('• Voice Configuration'),
        const Text('• Email Management'),
        const Text('• Schedule Manager'),
        const Text('• Memory Management'),
        const Text('• Persona Management'),
        const Text('• Advanced Settings'),
      ],
    );
  }
}
