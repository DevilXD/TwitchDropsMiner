# Changelog

All notable changes to TwitchDropsMinerWeb will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.4] - 2025-08-24

### Added
- Enhanced headless GUI implementation for better Docker/web mode compatibility
- Improved drop progress tracking with proper timeout mechanism
- Better error handling for critical task failures

### Changed
- Cleaned up debug code and unnecessary print statements
- Improved timing consistency in watch loop functionality
- Enhanced rate limiting protection for Twitch API calls

### Fixed
- **Critical:** Fixed Docker container exit issue caused by GUI attribute access in headless mode
- Fixed NameError for undefined variables in watch loop
- Fixed critical task wrapper failures that caused application shutdown
- Resolved GUI compatibility issues when running in headless mode
- Fixed timeout handling for drop progress updates in both GUI and headless modes

## [0.1.0] - 2025-05-19

### Added
- Initial fork from DevilXD/TwitchDropsMiner
- New web interface features
- Docker configuration files

[Unreleased]: https://github.com/Kaysharp42/TwitchDropsMinerWeb/compare/v0.1.4...HEAD
[0.1.4]: https://github.com/Kaysharp42/TwitchDropsMinerWeb/compare/v0.1.0...v0.1.4
[0.1.0]: https://github.com/Kaysharp42/TwitchDropsMinerWeb/releases/tag/v0.1.0
