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

## [1.6.3] – 2026-04-13

### Added
- **Smoke and Release Acceptance Test coverage extended** — language selector, tire details toggle, and seasonal tracking toggle are now exercised in both the EXE smoke test and the RAT (Phase 1b-ext and Phase 1c).
- **Ruff linter** — replaces flake8; runs on every push and PR before the version bump is allowed to proceed, ensuring no build or release can start with lint failures.
- **`[Unreleased]` guard in version bump** — `tools/bump_version.py` warns when the changelog section is empty before stamping a release, so release notes are never silently blank.
- **`tools/updater.py` now linted as production code** — it was previously excluded from all lint checks despite being the source auto-updater for deployed installations.

### Changed
- **Release Acceptance Test re-enabled** — was temporarily disabled during the German licence-plate validation fix; it now runs again on every `master` push, pull request to `master`, and manual dispatch.
- **Dependencies consolidated in `pyproject.toml`** — runtime deps moved to `[project.dependencies]`; test/lint deps to `[project.optional-dependencies] test`. `requirements.txt` and `requirements-test.txt` now simply delegate to `pip install .` / `pip install .[test]`.
- **Python minimum version raised to 3.12** — `requires-python`, ruff `target-version`, and all CI jobs updated to Python 3.12.
- **Version bump also updates `pyproject.toml`** — `tools/bump_version.py` now keeps `[project].version` in sync with `config.py` so there is a single source of truth per commit.

### Fixed
- **SSL certificate verification failure in corporate networks** — the self-updater (`tsm/self_update.py`) and standalone updater (`tools/updater.py`) now call `ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)` on Windows so that enterprise root CAs deployed via Group Policy are trusted. Certificate verification is not disabled; the trust store is extended.
- **Code quality: unused imports, variable shadowing, unreachable code** — removed across `tsm/`, `installer/`, and test files as part of the ruff migration.
- **Multi-line f-string in `backup_manager.py`** — expression was only valid from Python 3.12; rewritten to be compatible.

## [1.6.2] – 2026-04-10

## [1.6.1] – 2026-04-02

## [1.6.0] – 2026-03-27

## [1.5.8] – 2026-03-27

## [1.5.7] – 2026-03-27

### Changed
- **CI/CD pipeline restructured into a single `ci.yml`** with clearly separated jobs:
  - `changes` — path-change detection
  - `test-app` — unit tests (all branches/PRs)
  - `test-installer` — installer unit tests (only when `installer/` changed)
  - `bump` — version bump artifact (master/develop only)
  - `build` — Windows EXE build, code signing, artifact upload (all branches/PRs)
  - `smoke` — EXE smoke tests as a separate job (all branches/PRs)
  - `commit-bump` — commits version bump and git tag (master/develop, requires smoke + test-installer pass)
  - `release` — creates GitHub Release (master/develop, requires smoke + test-installer pass)
- Build and EXE smoke tests now run on **every branch and PR** (not only `master`/`develop`). Version bump commit and release are still restricted to `master`/`develop`.
- `commit-bump` and `release` are now blocked if `smoke` or `test-installer` fail — a failing smoke or installer test prevents any version from being committed or released. Both jobs may be skipped (no change in their scope), but never silently ignored.
- Installer `restore-db` headless CLI mode and `RestoreProgressWindow` GUI for restoring a database from a backup file with schema validation.
- `validate_sqlite_file()` extended with schema validation — checks required tables (`wheel_sets`, `settings`, `audit_log`) and mandatory columns via `sqlite3` read-only URI mode before accepting a restore candidate.
- Secret key (`TSM_SECRET_KEY`) field in installer GUI marked as optional with explanatory hint text.

## [1.5.6] – 2026-03-27

## [1.5.5] – 2026-03-27

## [1.5.4] – 2026-03-26

## [1.5.3] – 2026-03-26
### Added
- **Extended tire details** (optional feature flag in Settings) — each wheel set can store tyre manufacturer, tyre size, age/DOT, season (Sommer / Winter / Allwetter), rim type (Stahl / Alu), and a free-text exchange note. All columns are nullable; existing records are unaffected.
- **Seasonal overdue detection** — when seasonal tracking is enabled, wheel sets stored past their seasonal exchange window are highlighted with a pulsing red row and a ⚠ warning icon. Rules: Sommer tyres are overdue Jan–Apr; Winter tyres are overdue Jul–Sep; swap windows May–Jun and Oct–Dec are not flagged.
- Season badges with icons on the wheel set list (☀ Sommer, ❄ Winter, 🌦 Allwetter); the exchange note is shown as a tooltip on the badge.
- Settings toggles for **Erweiterte Reifendaten** and **Saisonale Radverwaltung** (seasonal tracking is only available when extended tire details is enabled). Both flags are stored in the database and backwards-compatible via auto-migration.
- **English language support** — the UI language can now be switched between German and English in Settings. Language choice is persisted per-installation in the database.
- Lightweight dict-based i18n module (`tsm/i18n.py`) with ~80 translation keys; no `.po`/`.mo` compilation required — fully compatible with PyInstaller EXE builds.
- Language selector dropdown in the Settings → Appearance card (🇩🇪 Deutsch / 🇬🇧 English).

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
