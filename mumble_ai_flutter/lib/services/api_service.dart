import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

class ApiService {
  static ApiService? _instance;
  late Dio _dio;
  String? _baseUrl;

  ApiService._() {
    _dio = Dio();
    _dio.options.connectTimeout = 10000; // 10 seconds
    _dio.options.receiveTimeout = 10000; // 10 seconds
    _dio.options.sendTimeout = 10000; // 10 seconds
    
    // Add interceptors for logging in debug mode
    if (kDebugMode) {
      _dio.interceptors.add(LogInterceptor(
        requestBody: true,
        responseBody: true,
        error: true,
      ));
    }
  }

  static ApiService getInstance() {
    _instance ??= ApiService._();
    return _instance!;
  }

  void setBaseUrl(String url) {
    _baseUrl = url.endsWith('/') ? url.substring(0, url.length - 1) : url;
    _dio.options.baseUrl = _baseUrl!;
  }

  String? get baseUrl => _baseUrl;

  // Test connection to server
  Future<bool> testConnection() async {
    try {
      final response = await _dio.get('/api/stats');
      return response.statusCode == 200;
    } catch (e) {
      return false;
    }
  }

  // Generic GET request
  Future<Response> get(String path, {Map<String, dynamic>? queryParameters}) async {
    try {
      return await _dio.get(path, queryParameters: queryParameters);
    } on DioError catch (e) {
      throw _handleError(e);
    }
  }

  // Generic POST request
  Future<Response> post(String path, {dynamic data, Map<String, dynamic>? queryParameters}) async {
    try {
      return await _dio.post(path, data: data, queryParameters: queryParameters);
    } on DioError catch (e) {
      throw _handleError(e);
    }
  }

  // Generic PUT request
  Future<Response> put(String path, {dynamic data, Map<String, dynamic>? queryParameters}) async {
    try {
      return await _dio.put(path, data: data, queryParameters: queryParameters);
    } on DioError catch (e) {
      throw _handleError(e);
    }
  }

  // Generic DELETE request
  Future<Response> delete(String path, {Map<String, dynamic>? queryParameters}) async {
    try {
      return await _dio.delete(path, queryParameters: queryParameters);
    } on DioError catch (e) {
      throw _handleError(e);
    }
  }

  // Download file (for audio previews)
  Future<Response> download(String path, String savePath) async {
    try {
      return await _dio.download(path, savePath);
    } on DioError catch (e) {
      throw _handleError(e);
    }
  }

  // Handle Dio errors and convert to user-friendly messages
  Exception _handleError(DioError error) {
    if (error.type == DioErrorType.connectTimeout ||
        error.type == DioErrorType.sendTimeout ||
        error.type == DioErrorType.receiveTimeout) {
      return Exception('Connection timeout. Please check your network connection.');
    } else if (error.type == DioErrorType.response) {
      final statusCode = error.response?.statusCode;
      final message = error.response?.data?['error'] ?? 'Server error';
      return Exception('Server error ($statusCode): $message');
    } else if (error.type == DioErrorType.cancel) {
      return Exception('Request was cancelled');
    } else if (error.type == DioErrorType.other) {
      if (error.message.contains('SocketException')) {
        return Exception('Unable to connect to server. Please check the server URL and your network connection.');
      }
      return Exception('Network error: ${error.message}');
    } else {
      return Exception('An unexpected error occurred: ${error.message}');
    }
  }
}
