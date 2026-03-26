# Changelog

All notable changes to **TireStorageManager** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!--
  HOW TO USE:
  1. When working on changes, add entries under [Unreleased].
  2. When the CI bumps the version, the release job extracts the
     [Unreleased] section as the release notes body.
  3. After a release, move [Unreleased] entries into a versioned
     section (manually or via the bump script).

  Categories: Added, Changed, Fixed, Removed, Security
-->

## [Unreleased]

## [1.5.0] – 2026-03-26
### Added
- **German licence-plate validation** — wheelset form enforces standard German plate format (`ORT-KK 1234`, optional `E`/`H` suffix) in the browser (live validity indicator, Bootstrap feedback) and on the server (`utils.py` regex). Invalid plates are rejected before saving.
- Licence plate input auto-uppercases while typing; no silent reformatting of the entered value.
- Delete-confirmation input also auto-uppercases to prevent case mismatches.
- **Update Management UI** – check for updates from Settings, see release notes, trigger immediate updates.
- Auto-update toggle in Settings (runs automatically on service restart at 03:00).
- Update-available banner on every page with release notes preview.
- AJAX-based update check with 10-minute server-side cache.
### Changed
- **CI/CD pipeline restructured**: order is now `test → build → bump → release`. Version is only bumped after all tests and the full EXE build (including smoke test) pass.
- Version bump and release restricted to `master`/`develop`; `test` and `build` run on every branch and pull-request.
- Version bump only triggered when app source files change (`tsm/`, `templates/`, `static/`, `config.py`, `requirements.txt`). CI/tool/doc-only changes no longer produce a new version.
### Fixed
- `subprocess.DETACHED_PROCESS` / `CREATE_NO_WINDOW` are Windows-only constants; guarded with `getattr(subprocess, …, 0)` so tests pass on Linux CI.
- Smoke test concurrency suite used invalid German plate format (`CC-00 0001`) — replaced with valid plates (`B-CC 0001`…`B-CC 0010`).
- `CHANGELOG_PATH` and `date` import restored in `tools/bump_version.py` after rebase loss.

## [1.4.2] – 2026-03-15

### Added
- Code signing for EXE builds (self-signed certificate, CI integration).
- Pre-release workflow for `develop` branch builds.

### Fixed
- Improved uninstaller reliability (tasklist polling, force-kill, MoveFileEx reboot fallback).
- Encoding fixes (`utf-8, errors="replace"`) in installer.
- Registry persistence for installer settings.

## [1.4.1] – 2026-03-10

### Added
- Develop branch pre-release builds with `⚠ TEST-VERSION` badge.
- Installer GUI improvements.

### Fixed
- Combined version bump and CI task into single workflow.

## [1.4.0] – 2026-03-05

### Added
- Dark mode with system-wide toggle and `data-bs-theme` support.
- Custom positions editor – define your own storage position names.
- Impressum page with Konami Code Easter Egg.
- Splash screen with spinning tire SVG and progress bar.
- Self-update system for deployed EXE installations.
- Desktop shortcut creation during installation.
- Idle screensaver with car-shop themed jokes and emojis.

### Changed
- Installer refactored into `installer/` subfolder.
- Consolidated CI workflows (`bump-version.yml` → `ci.yml`).

### Fixed
- Dev server Ctrl+C clean shutdown (signal handlers, `_stop_event` naming).
- SQLAlchemy deprecation warnings (`raw.connection` → `raw.driver_connection`).
- Path traversal protection on backup download route.
- CSRF validation uses `hmac.compare_digest()` for timing-safe comparison.
- Silent exceptions in backup manager now logged properly.
- `BackupManager` uses `SessionLocal.remove()` instead of `db.close()`.

## [1.3.2] – 2026-02-20

### Fixed
- Build process improvements.

## [1.3.1] – 2026-02-18

### Added
- Executable and installer EXE via PyInstaller.
- Desktop shortcut creation after installation.
- Unit tests (initial test suite).

### Changed
- Cleaned up project structure.

## [1.1.5] – 2026-02-10

### Added
- Initial release with core functionality.
- Wheel set CRUD (create, read, update, delete).
- Storage position management with grid view.
- Backup system with configurable interval and retention.
- CSV export for backups.
- Audit logging for all operations.
