# Docker Migration Guide

## Проблема
При попытке запустить миграцию командой:
```bash
docker exec -it employees_app alembic revision --autogenerate -m "" upgrade head
```

Возникает ошибка, потому что эта команда **неправильная**. Она пытается объединить две разные команды Alembic в одну:
1. `alembic revision --autogenerate -m ""` - создание новой миграции
2. `alembic upgrade head` - применение миграций

## Правильные команды для Docker

### 1. Применить миграции (ОСНОВНАЯ КОМАНДА)
Чтобы применить существующие миграции к базе данных:

```bash
docker exec -it employees_app sh -c "cd /app && alembic upgrade head"
```

Или если приложение находится в другой директории:
```bash
docker exec -it employees_app alembic upgrade head
```

### 2. Проверить текущую версию базы данных
```bash
docker exec -it employees_app sh -c "cd /app && alembic current"
```

### 3. Посмотреть историю миграций
```bash
docker exec -it employees_app sh -c "cd /app && alembic history"
```

### 4. Откатить последнюю миграцию
```bash
docker exec -it employees_app sh -c "cd /app && alembic downgrade -1"
```

### 5. Создать новую миграцию (автогенерация)
```bash
docker exec -it employees_app sh -c "cd /app && alembic revision --autogenerate -m 'Описание изменений'"
```

⚠️ **Важно**: Всегда указывайте осмысленное описание в `-m`, не оставляйте пустым!

## Использование скрипта-помощника

Для удобства создан скрипт `migrate.sh`, который упрощает работу с миграциями:

### Настройка
```bash
# Сделать скрипт исполняемым (один раз)
chmod +x migrate.sh

# Опционально: установить имя контейнера (если не employees_app)
export DOCKER_CONTAINER_NAME=your_container_name
```

### Примеры использования

#### Применить все миграции
```bash
./migrate.sh upgrade
```

#### Применить следующую миграцию
```bash
./migrate.sh upgrade +1
```

#### Откатить последнюю миграцию
```bash
./migrate.sh downgrade -1
```
(Скрипт попросит подтверждение)

#### Проверить текущую версию
```bash
./migrate.sh current
```

#### Посмотреть историю
```bash
./migrate.sh history
```

#### Создать новую миграцию
```bash
./migrate.sh autogenerate "Add new field to users"
```

#### Помощь
```bash
./migrate.sh help
```

## Пошаговая инструкция для применения миграций

### Шаг 1: Проверить, что контейнер запущен
```bash
docker ps | grep employees_app
```

Если контейнер не запущен:
```bash
docker-compose up -d
```

### Шаг 2: Создать резервную копию БД (ОБЯЗАТЕЛЬНО!)
```bash
docker exec employees_app pg_dump -U postgres -d your_database > backup_$(date +%Y%m%d_%H%M%S).sql
```

Или подключиться к контейнеру PostgreSQL:
```bash
docker exec postgres_container pg_dump -U your_user -d your_database > backup.sql
```

### Шаг 3: Проверить текущую версию БД
```bash
./migrate.sh current
# или
docker exec -it employees_app sh -c "cd /app && alembic current"
```

### Шаг 4: Применить миграции
```bash
./migrate.sh upgrade
# или
docker exec -it employees_app sh -c "cd /app && alembic upgrade head"
```

### Шаг 5: Проверить результат
```bash
./migrate.sh current
```

Должно показать:
```
001 (head)
```

### Шаг 6: Проверить данные в БД
Подключиться к базе данных и проверить:
```bash
docker exec -it employees_app psql -U postgres -d your_database

# В psql:
\dt                          # Показать все таблицы
SELECT * FROM departments;   # Проверить отделы
SELECT id, email, department_id FROM users LIMIT 5;  # Проверить пользователей
```

## Распространенные ошибки и решения

### Ошибка: "Container 'employees_app' is not running"
**Решение:**
```bash
# Проверить имя контейнера
docker ps

# Использовать правильное имя
export DOCKER_CONTAINER_NAME=actual_container_name
./migrate.sh upgrade
```

### Ошибка: "Can't locate revision identified by 'head'"
**Решение:** База данных не инициализирована. Нужно пометить текущую версию:
```bash
docker exec -it employees_app sh -c "cd /app && alembic stamp head"
```

### Ошибка: "Target database is not up to date"
**Решение:** Просто примените миграции:
```bash
./migrate.sh upgrade
```

### Ошибка: "Table 'alembic_version' doesn't exist"
**Решение:** Первый раз инициализируем Alembic:
```bash
docker exec -it employees_app sh -c "cd /app && alembic stamp base"
docker exec -it employees_app sh -c "cd /app && alembic upgrade head"
```

### Ошибка: Connection refused / Database connection error
**Решение:** Проверить, что база данных доступна:
```bash
# Проверить переменные окружения
docker exec employees_app env | grep POSTGRES

# Проверить сеть Docker
docker network ls
docker network inspect your_network
```

## Откат миграции (если что-то пошло не так)

### Откатить последнюю миграцию
```bash
./migrate.sh downgrade -1
```

Или вручную:
```bash
docker exec -it employees_app sh -c "cd /app && alembic downgrade -1"
```

### Восстановить из резервной копии
```bash
# Остановить приложение
docker-compose down

# Восстановить базу данных
docker exec -i postgres_container psql -U your_user -d your_database < backup.sql

# Запустить приложение
docker-compose up -d
```

## Docker Compose пример

Если у вас нет docker-compose.yml, вот базовый пример:

```yaml
version: '3.8'

services:
  app:
    container_name: employees_app
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:password@db:5432/employee_cabinet
      - POSTGRES_HOST=db
      - POSTGRES_PORT=5432
      - POSTGRES_DB=employee_cabinet
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=password
    depends_on:
      - db
    volumes:
      - ./app:/app
    command: uvicorn main:app --host 0.0.0.0 --port 8000 --reload

  db:
    image: postgres:15
    container_name: employees_db
    environment:
      - POSTGRES_DB=employee_cabinet
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=password
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

## Команды для разных сценариев

### Применить конкретную миграцию
```bash
docker exec -it employees_app sh -c "cd /app && alembic upgrade 001"
```

### Откатить до конкретной версии
```bash
docker exec -it employees_app sh -c "cd /app && alembic downgrade 001"
```

### Посмотреть SQL без применения
```bash
docker exec -it employees_app sh -c "cd /app && alembic upgrade head --sql"
```

### Проверить, что миграция применится корректно (dry run)
```bash
# Alembic не имеет встроенного dry-run, но можно посмотреть SQL:
docker exec -it employees_app sh -c "cd /app && alembic upgrade head --sql" > migration.sql
cat migration.sql
```

## Логи и отладка

### Включить подробные логи
```bash
docker exec -it employees_app sh -c "cd /app && alembic -c alembic.ini upgrade head -v"
```

### Посмотреть логи контейнера
```bash
docker logs employees_app
docker logs employees_app --tail 100 -f  # Последние 100 строк, follow mode
```

### Подключиться к контейнеру для отладки
```bash
docker exec -it employees_app /bin/bash
# или если bash нет:
docker exec -it employees_app /bin/sh

# Внутри контейнера:
cd /app
alembic current
alembic history
python -c "from core.config import settings; print(settings.DATABASE_URL)"
```

## Автоматизация миграций

### В CI/CD
Добавить в pipeline:
```bash
# Дождаться готовности базы данных
docker exec employees_app sh -c "until pg_isready -h db -U postgres; do sleep 1; done"

# Применить миграции
docker exec employees_app sh -c "cd /app && alembic upgrade head"
```

### При старте приложения
Можно добавить в Dockerfile или entrypoint script:
```bash
#!/bin/bash
# entrypoint.sh

# Дождаться базы данных
echo "Waiting for database..."
while ! pg_isready -h $POSTGRES_HOST -p $POSTGRES_PORT; do
  sleep 1
done

# Применить миграции
echo "Running migrations..."
cd /app && alembic upgrade head

# Запустить приложение
echo "Starting application..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
```

## Поддержка

При возникновении проблем:
1. Проверьте имя контейнера: `docker ps`
2. Проверьте логи: `docker logs employees_app`
3. Проверьте подключение к БД внутри контейнера
4. Посмотрите текущую версию: `./migrate.sh current`
5. Посмотрите историю: `./migrate.sh history`

## Полезные ссылки
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [Docker Documentation](https://docs.docker.com/)
- [Основная документация по миграциям](./MIGRATION_GUIDE.md)
