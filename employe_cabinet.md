# Employee Cabinet - Технический паспорт проекта

Дата обновления: 16.03.2026

## Оглавление

1. [Что это за проект](#что-это-за-проект)
2. [Технологический стек](#технологический-стек)
3. [Точки входа и запуск](#точки-входа-и-запуск)
4. [Архитектурная схема](#архитектурная-схема)
5. [Структура репозитория](#структура-репозитория)
6. [Детализация по app/core](#детализация-по-appcore)
7. [Детализация по app/modules](#детализация-по-appmodules)
8. [Полная карта роутов](#полная-карта-роутов)
9. [Модели и схемы (где что хранится)](#модели-и-схемы-где-что-хранится)
10. [Логирование: как реализовано и как использовать](#логирование-как-реализовано-и-как-использовать)
11. [Мониторинг и алерты](#мониторинг-и-алерты)
12. [Шаблоны, статика, фронтенд](#шаблоны-статика-фронтенд)
13. [Фоновые задачи и миграции](#фоновые-задачи-и-миграции)
14. [Быстрый навигатор для разработчика](#быстрый-навигатор-для-разработчика)

---

## Что это за проект

**Employee Cabinet** — корпоративная система на FastAPI для личного кабинета сотрудников и администрирования.

Основные задачи проекта:
- аутентификация и управление сессиями пользователей;
- управление профилем сотрудников;
- управление объектами компании и доступами к ним;
- загрузка, хранение и обновление документов;
- админ-панель (пользователи, роли, разрешения, аудит);
- мониторинг состояния системы, метрик и security-событий.

Проект ориентирован на web-интерфейс (Jinja2 шаблоны), но также содержит API-эндпоинты для операций и администрирования.

---

## Технологический стек

### Backend
- FastAPI
- SQLAlchemy 2.x
- Pydantic v2
- Uvicorn / Gunicorn

### База и инфраструктура
- PostgreSQL
- Redis
- Celery (фоновые задачи)

### Безопасность
- JWT (python-jose)
- CSRF middleware (starlette-csrf)
- Rate limiting (slowapi)

### Логи и наблюдаемость
- JSON-логирование
- Логи в БД (AuditLog)
- Ротация файлов логов
- Prometheus метрики
- Health checks

### UI / Frontend
- Jinja2
- Tailwind CSS (через npm scripts)

---

## Точки входа и запуск

### Главная точка входа
- [app/main.py](app/main.py)

### Docker
- [Dockerfile](Dockerfile)
- [docker-compose.yml](docker-compose.yml)

### Локальные зависимости
- [requirements.txt](requirements.txt)
- [package.json](package.json)

### Что делает main.py при старте
- конфигурирует логирование (stdout + DB + файловые хендлеры);
- подключает middleware (CORS, CSRF, AccessLog, RequestID, защита Swagger);
- монтирует статику;
- подключает роутеры модулей;
- запускает инициализацию мониторинга;
- поднимает периодическую очистку истекших сессий.

---

## Архитектурная схема

Проект логически разделен на 3 уровня:

1. **Платформа/инфраструктура**: [app/core](app/core)  
: конфиги, БД, middleware, логирование, мониторинг ядра, безопасность.

2. **Бизнес-модули**: [app/modules](app/modules)  
: auth, admin, objects, documents, profile, monitoring и т.д.

3. **Представление и ассеты**: [app/templates](app/templates), [app/static](app/static)  
: HTML-шаблоны страниц, CSS/JS и медиа.

---

## Структура репозитория

- [app](app) — основной код приложения
- [docs](docs) — документация по логам/мониторингу
- [logs](logs) — runtime-логи
- [app/migrations](app/migrations) — Alembic миграции
- [app/tests](app/tests) — unit/integration тесты
- [app/workers](app/workers) — Celery worker и задачи

Внутри [app](app):
- [app/core](app/core)
- [app/modules](app/modules)
- [app/services](app/services)
- [app/templates](app/templates)
- [app/static](app/static)
- [app/files](app/files)

---

## Детализация по app/core

### Конфигурация и инфраструктура
- [app/core/config.py](app/core/config.py)  
: все env-настройки, timezone, security-параметры, мониторинг-параметры.

- [app/core/database.py](app/core/database.py)  
: SQLAlchemy engine/session, dependency get_db.

- [app/core/request_id_middleware.py](app/core/request_id_middleware.py)  
: генерирует/пробрасывает X-Request-ID в запросе и ответе.

- [app/core/swagger_security.py](app/core/swagger_security.py)  
: ограничения доступа к Swagger/OpenAPI.

### Логирование
- [app/core/db_log_handler.py](app/core/db_log_handler.py)  
: кастомный logging.Handler для записи логов в БД (AuditLog).

- [app/core/log_cleanup.py](app/core/log_cleanup.py)  
: архивация/очистка просроченных логов.

- [app/core/logging/actions.py](app/core/logging/actions.py)  
: единая точка логирования бизнес-событий через log_event(...).

- [app/core/logging/middleware.py](app/core/logging/middleware.py)  
: access-лог каждого HTTP-запроса.

- [app/core/logging/handlers.py](app/core/logging/handlers.py)  
: ротация и компрессия файлов логов.

- [app/core/logging/formatters.py](app/core/logging/formatters.py)  
: JSON/compact/development форматтеры.

- [app/core/logging/filters.py](app/core/logging/filters.py)  
: маскирование чувствительных данных и PII.

### Мониторинг ядра
- [app/core/monitoring](app/core/monitoring)  
: метрики, алерты, детектор аномалий, health checks.

### Уведомления
- [app/core/notifications](app/core/notifications)  
: email/telegram нотификаторы для критичных событий.

---

## Детализация по app/modules

### auth
Папка: [app/modules/auth](app/modules/auth)

Отвечает за:
- регистрацию и логин;
- refresh/logout;
- OTP/2FA сценарии;
- восстановление пароля;
- управление пользовательскими сессиями;
- зависимости для текущего пользователя.

Ключевые файлы:
- [app/modules/auth/routes.py](app/modules/auth/routes.py) — HTTP-роуты auth.
- [app/modules/auth/service.py](app/modules/auth/service.py) — бизнес-логика авторизации.
- [app/modules/auth/models.py](app/modules/auth/models.py) — User/Session/OTP/LoginAttempt/Department.
- [app/modules/auth/schemas.py](app/modules/auth/schemas.py) — Pydantic-схемы auth.
- [app/modules/auth/dependencies.py](app/modules/auth/dependencies.py) — auth dependencies.

### admin
Папка: [app/modules/admin](app/modules/admin)

Отвечает за:
- админское управление пользователями;
- управление ролями/правами;
- просмотр и экспорт логов;
- управление отделами;
- управление пользовательскими сессиями;
- управление mapping-ами категорий.

Ключевые файлы:
- [app/modules/admin/routes.py](app/modules/admin/routes.py)
- [app/modules/admin/models.py](app/modules/admin/models.py) (AuditLog, UserAgentCache).

### objects
Папка: [app/modules/objects](app/modules/objects)

Отвечает за:
- CRUD объектов;
- архив/активация/деактивация;
- карточку объекта;
- доступы пользователей/отделов к объекту;
- подкатегории документов объекта.

Ключевые файлы:
- [app/modules/objects/routes.py](app/modules/objects/routes.py)
- [app/modules/objects/service.py](app/modules/objects/service.py)
- [app/modules/objects/models.py](app/modules/objects/models.py)
- [app/modules/objects/schemas.py](app/modules/objects/schemas.py)

### documents
Папка: [app/modules/documents](app/modules/documents)

Отвечает за:
- загрузку документов к объектам;
- обновление документа и файла;
- удаление и пакетные операции;
- скачивание отдельных файлов и ZIP.

Ключевые файлы:
- [app/modules/documents/routes.py](app/modules/documents/routes.py)
- [app/modules/documents/service.py](app/modules/documents/service.py)
- [app/modules/documents/models.py](app/modules/documents/models.py)
- [app/modules/documents/schemas.py](app/modules/documents/schemas.py)
- [app/modules/documents/service_mappings.py](app/modules/documents/service_mappings.py)

### profile
Папка: [app/modules/profile](app/modules/profile)

Отвечает за:
- просмотр и обновление профиля;
- загрузку аватара;
- смену пароля.

Ключевые файлы:
- [app/modules/profile/routes.py](app/modules/profile/routes.py)
- [app/modules/profile/schemas.py](app/modules/profile/schemas.py)

### monitoring
Папка: [app/modules/monitoring](app/modules/monitoring)

Отвечает за админские endpoints мониторинга:
- метрики;
- алерты (просмотр/резолв);
- health;
- dashboard и страницы алертов;
- просмотр security-логов.

Ключевые файлы:
- [app/modules/monitoring/routes.py](app/modules/monitoring/routes.py)
- [app/modules/monitoring/service.py](app/modules/monitoring/service.py)
- [app/modules/monitoring/service_alerts.py](app/modules/monitoring/service_alerts.py)
- [app/modules/monitoring/models.py](app/modules/monitoring/models.py)
- [app/modules/monitoring/schemas.py](app/modules/monitoring/schemas.py)

### permissions
Папка: [app/modules/permissions](app/modules/permissions)

Отвечает за:
- таблицы разрешений;
- маппинг role->permission;
- персональные разрешения;
- subsection access.

Ключевой файл:
- [app/modules/permissions/models.py](app/modules/permissions/models.py)

### access
Папка: [app/modules/access](app/modules/access)

Отвечает за:
- ACL-модели и enum-ы;
- сервисные проверки доступа;
- декораторы/контракты доступа.

Ключевые файлы:
- [app/modules/access/models_sql.py](app/modules/access/models_sql.py)
- [app/modules/access/models.py](app/modules/access/models.py)
- [app/modules/access/service.py](app/modules/access/service.py)
- [app/modules/access/decorators.py](app/modules/access/decorators.py)

### Остальные каталоги modules
- [app/modules/audit](app/modules/audit)
- [app/modules/departments](app/modules/departments)
- [app/modules/integration_1c](app/modules/integration_1c)
- [app/modules/notifications](app/modules/notifications)
- [app/modules/reports](app/modules/reports)
- [app/modules/search](app/modules/search)
- [app/modules/tasks](app/modules/tasks)

Часть этих каталогов сейчас используется как задел для расширения.

---

## Полная карта роутов

Ниже указаны роуты, обнаруженные в route-файлах.

### 1) Auth (базовый префикс: /api/v1/auth)
Файл: [app/modules/auth/routes.py](app/modules/auth/routes.py)

- GET /api/v1/auth/login-page
- GET /api/v1/auth/register-page
- POST /api/v1/auth/register
- POST /api/v1/auth/login
- POST /api/v1/auth/refresh
- GET /api/v1/auth/logout
- GET /api/v1/auth/me
- PATCH /api/v1/auth/me
- POST /api/v1/auth/change-password
- POST /api/v1/auth/password-reset/request
- POST /api/v1/auth/password-reset/confirm
- POST /api/v1/auth/otp/request
- POST /api/v1/auth/otp/verify
- GET /api/v1/auth/sessions
- DELETE /api/v1/auth/sessions/{session_id}

### 2) Profile (базовый префикс: /profile)
Файл: [app/modules/profile/routes.py](app/modules/profile/routes.py)

- GET /profile
- POST /profile/update
- POST /profile/upload-avatar
- POST /profile/change-password

### 3) Objects (базовый префикс: /objects)
Файл: [app/modules/objects/routes.py](app/modules/objects/routes.py)

- GET /objects
- GET /objects/create
- POST /objects/create
- GET /objects/{object_id}/edit
- POST /objects/{object_id}/edit
- GET /objects/{object_id}
- POST /objects/{object_id}/delete
- GET /objects/admin/all
- POST /objects/{object_id}/restore
- POST /objects/{object_id}/activate
- POST /objects/{object_id}/deactivate
- POST /objects/{object_id}/archive
- POST /objects/{object_id}/unarchive
- POST /objects/{object_id}/access/grant
- POST /objects/{object_id}/access/{user_id}/revoke
- POST /objects/{object_id}/access/grant-department
- POST /objects/{object_id}/access/{user_id}/update
- GET /objects/{object_id}/subcategories
- POST /objects/{object_id}/subcategories/create
- POST /objects/{object_id}/subcategories/{subcategory_id}/delete
- POST /objects/{object_id}/subcategories/{subcategory_id}/update

### 4) Documents (базовый префикс: /documents)
Файл: [app/modules/documents/routes.py](app/modules/documents/routes.py)

- POST /documents/objects/{object_id}/upload
- POST /documents/objects/{object_id}/{document_id}/update
- POST /documents/objects/{object_id}/{document_id}/delete
- GET /documents/{document_id}/download
- GET /documents/objects
- POST /documents/{document_id}/update
- POST /documents/batch-delete
- POST /documents/batch-download

### 5) Admin (базовый префикс: /admin)
Файл: [app/modules/admin/routes.py](app/modules/admin/routes.py)

- GET /admin/users
- POST /admin/users/{user_id}/activate
- POST /admin/users/{user_id}/deactivate
- POST /admin/users/{user_id}/role
- DELETE /admin/users/{user_id}
- POST /admin/users/{user_id}/edit
- POST /admin/users/{user_id}/reset-password
- GET /admin/logs
- GET /admin/logs/{log_id}/detail
- GET /admin/logs/export
- GET /admin/logs/export/json
- GET /admin/logs/stats
- GET /admin/departments
- POST /admin/departments
- PUT /admin/departments/{department_id}
- DELETE /admin/departments/{department_id}
- GET /admin/users/{user_id}/sessions
- POST /admin/sessions/{session_id}/revoke
- POST /admin/users/{user_id}/sessions/revoke-all
- POST /admin/users/{user_id}/sessions/revoke-others
- GET /admin/category-mappings
- PUT /admin/category-mappings/{category}
- GET /admin/permissions
- GET /admin/users/{user_id}/permissions
- PUT /admin/users/{user_id}/permissions
- GET /admin/users/{user_id}/subsection-access
- PUT /admin/users/{user_id}/subsection-access/{subsection_id}
- GET /admin/subsections
- GET /admin/sections/{section_id}/subsections

### 6) Monitoring (базовый префикс: /admin/monitoring)
Файл: [app/modules/monitoring/routes.py](app/modules/monitoring/routes.py)

- GET /admin/monitoring/metrics
- GET /admin/monitoring/alerts
- GET /admin/monitoring/alerts/{alert_id}
- POST /admin/monitoring/alerts/{alert_id}/resolve
- GET /admin/monitoring/alerts/counts
- GET /admin/monitoring/health
- GET /admin/monitoring/stats
- GET /admin/monitoring/logs
- GET /admin/monitoring/logs/security
- GET /admin/monitoring/dashboard
- GET /admin/monitoring/alerts-page
- POST /admin/monitoring/alerts/resolve-bulk

### 7) Системные роуты приложения
Файл: [app/main.py](app/main.py)

- GET /
- GET /health
- GET /dashboard
- GET /docs-access-denied

---

## Модели и схемы (где что хранится)

### Auth
- [app/modules/auth/models.py](app/modules/auth/models.py): Department, User, Session, OTP, LoginAttempt.
- [app/modules/auth/schemas.py](app/modules/auth/schemas.py): UserCreate/UserLogin/UserRead/UserUpdate, TokenResponse, OTP*, PasswordReset*, SessionRead, Department*.

### Admin
- [app/modules/admin/models.py](app/modules/admin/models.py): LogLevel, UserAgentCache, AuditLog.

### Objects
- [app/modules/objects/models.py](app/modules/objects/models.py): Object, ObjectAccess, ObjectAccessRole, DocumentSection.
- [app/modules/objects/schemas.py](app/modules/objects/schemas.py): ObjectCreate/Update/Read, ObjectAccessCreate/Update/Read.

### Documents
- [app/modules/documents/models.py](app/modules/documents/models.py): DocumentSubcategory, DocumentCategoryMapping, Document.
- [app/modules/documents/schemas.py](app/modules/documents/schemas.py): DocumentCategoryEnum и DTO для документов/подкатегорий.

### Monitoring
- [app/modules/monitoring/models.py](app/modules/monitoring/models.py): AlertSeverity, AlertType, Alert.
- [app/modules/monitoring/schemas.py](app/modules/monitoring/schemas.py): ответы и payload для alerts/health/stats/logs.

### Permissions
- [app/modules/permissions/models.py](app/modules/permissions/models.py): Permission, RolePermission, UserPermission, Subsection, UserSubsectionAccess.

### Access
- [app/modules/access/models_sql.py](app/modules/access/models_sql.py): ACLEffect, PermissionType, ACL.
- [app/modules/access/models.py](app/modules/access/models.py): enum-ы и контрактные схемы уровня доступа.

---

## Логирование: как реализовано и как использовать

### Где настраивается
- [app/main.py](app/main.py) — базовый LOGGING_CONFIG и подключение file handlers.

### Ключевые механизмы
- [app/core/logging/actions.py](app/core/logging/actions.py)  
: единая функция log_event(...), категоризация событий, доп.данные, интеграция с алертами.

- [app/core/logging/middleware.py](app/core/logging/middleware.py)  
: access-логи всех HTTP-запросов, latency, user context.

- [app/core/request_id_middleware.py](app/core/request_id_middleware.py)  
: request_id для трассировки через цепочку вызовов.

- [app/core/db_log_handler.py](app/core/db_log_handler.py)  
: запись логов в БД с expires_at (TTL-политика по уровню).

- [app/core/logging/handlers.py](app/core/logging/handlers.py)  
: файлы логов с ротацией и gzip-компрессией.

- [app/core/logging/filters.py](app/core/logging/filters.py)  
: редактирование/маскирование чувствительных данных и PII.

### Куда пишутся логи
- stdout (JSON)
- БД (таблица AuditLog)
- файловые логи:
  - /app/logs/app/app.log
  - /app/logs/security/security.log
  - /app/logs/system/system.log

### Рекомендуемый способ логирования в коде

1. Использовать унифицированный метод из actions.py:
- импорт: from core.logging.actions import log_event
- вызов (async): await log_event(...)

2. Передавать:
- event: стабильное имя события (snake_case)
- request: если есть (для request_id, ip, user_agent)
- actor/target_user: если это действие пользователя
- create_alert=True: для security-критичных событий

3. Избегать записи секретов в лог.

Дополнительно можно использовать стандартный logger:
- logging.getLogger("app")
- logging.getLogger("security")
- logging.getLogger("system")

---

## Мониторинг и алерты

Разделение ответственности:
- [app/core/monitoring](app/core/monitoring) — движок мониторинга и detection;
- [app/modules/monitoring](app/modules/monitoring) — API-уровень и админские страницы.

Поддерживается:
- сбор метрик для Prometheus;
- health checks (быстрый и детальный);
- управление алертами (просмотр/фильтр/резолв);
- страницы dashboard и alerts-page;
- интеграции уведомлений (email/telegram при настройке env).

Документация:
- [docs/LOGGING.md](docs/LOGGING.md)
- [docs/MONITORING.md](docs/MONITORING.md)

---

## Шаблоны, статика, фронтенд

### Шаблоны
- [app/templates/web](app/templates/web) — страницы интерфейса
- [app/templates/components](app/templates/components) — переиспользуемые компоненты
- [app/templates/emails](app/templates/emails) — email-шаблоны

### Статика
- [app/static/css](app/static/css)
- [app/static/js](app/static/js)
- [app/static/images](app/static/images)
- [app/static/avatars](app/static/avatars)

### Сборка CSS
Скрипты в [package.json](package.json):
- npm run build:css
- npm run watch:css

---

## Фоновые задачи и миграции

- [app/workers/celery.py](app/workers/celery.py)
- [app/workers/tasks.py](app/workers/tasks.py)

Назначение:
- выполнение фоновых задач и отложенной обработки.

Миграции:
- [app/migrations](app/migrations)
- [app/migrations/versions](app/migrations/versions)

Назначение:
- контроль версий схемы БД и разворачивание изменений.

---

## Быстрый навигатор для разработчика

Если нужно изменить:

- логин/регистрацию/сессии: [app/modules/auth](app/modules/auth)
- профиль и аватар: [app/modules/profile](app/modules/profile)
- объекты и доступы: [app/modules/objects](app/modules/objects)
- документы и загрузку файлов: [app/modules/documents](app/modules/documents)
- админ-панель и аудит: [app/modules/admin](app/modules/admin)
- мониторинг и алерты: [app/modules/monitoring](app/modules/monitoring) и [app/core/monitoring](app/core/monitoring)
- глобальные настройки: [app/core/config.py](app/core/config.py)
- подключение БД: [app/core/database.py](app/core/database.py)
- middleware запроса: [app/core/request_id_middleware.py](app/core/request_id_middleware.py)
- стратегию логирования: [app/core/logging](app/core/logging) + [app/main.py](app/main.py)

---

Этот файл подготовлен как “паспорт проекта”, который можно передать другому разработчику/команде для быстрого погружения в кодовую базу.
