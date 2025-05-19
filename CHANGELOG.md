# Changelog

All notable changes to TwitchDropsMinerWeb will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Docker support with multi-stage build for efficient images
- Docker Compose configuration for easy deployment
- Setup scripts for both Windows (PowerShell) and Linux/macOS (Bash)
- GitHub Actions workflows for automated Docker image building
- Security scanning with Trivy in CI pipeline
- Dependency auto-update workflow
- Comprehensive documentation for Docker usage

### Changed
- Updated repository references from DevilXD/TwitchDropsMiner to Kaysharp42/TwitchDropsMinerWeb
- Enhanced documentation with details about web interface features
- Improved web interface styling and usability

### Fixed
- Security vulnerabilities in Docker configuration by implementing best practices
- Fixed web interface accessibility on Docker deployments

## [0.1.0] - 2025-05-19

### Added
- Initial fork from DevilXD/TwitchDropsMiner
- New web interface features
- Docker configuration files

[Unreleased]: https://github.com/Kaysharp42/TwitchDropsMinerWeb/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Kaysharp42/TwitchDropsMinerWeb/releases/tag/v0.1.0
