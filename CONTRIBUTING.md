# Contributing to TwitchDropsMinerWeb

Thank you for considering contributing to TwitchDropsMinerWeb! This is a fork of the original TwitchDropsMiner project with enhanced web interface capabilities and Docker support.

## How to Contribute

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Web Interface Contributions

If you're making changes to the web interface:

- Place HTML templates in the `web/templates/` directory
- Place CSS and JavaScript files in the `web/static/` directory
- Follow the existing structure for consistency
- Test your changes thoroughly in different browsers

## Docker Contributions

For Docker-related contributions:

- Test your changes both locally and in a clean environment
- Ensure all volumes and configuration options work properly
- Update documentation in DOCKER.md if changing container functionality

## Development Environment Setup

1. Clone the repository
2. Run `setup_env.bat` or `setup_env.sh` depending on your OS
3. Use the development script: `run_dev.bat` to test changes

## Pull Request Process

1. Update the README.md and any other documentation with details of changes
2. Update the CHANGELOG.md with your additions under the "Unreleased" section
3. The version numbers will be updated according to [SemVer](http://semver.org/)
4. Your PR may be merged once it has been reviewed and approved

## Code Style

- Follow the existing code style of the project
- Use meaningful variable and function names
- Add comments for complex sections of code
- Write unit tests for new functionality

Thank you for contributing to TwitchDropsMinerWeb!
