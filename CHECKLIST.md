# Контрольный список для устранения проблем

## ✅ Перед запуском миграций

- [ ] **Контейнеры запущены**
  ```bash
  docker ps
  ```
  Должны быть запущены контейнеры с приложением и базой данных.

- [ ] **Создана резервная копия БД**
  ```bash
  docker exec employees_app pg_dump -U postgres -d employee_cabinet > backup_$(date +%Y%m%d).sql
  ```

- [ ] **База данных доступна**
  ```bash
  docker exec employees_app psql -U postgres -d employee_cabinet -c "SELECT 1;"
  ```
  Должно вернуть: `1`

- [ ] **Переменные окружения настроены**
  ```bash
  docker exec employees_app env | grep POSTGRES
  ```
  Должны быть: POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD

## ✅ Проверка перед применением

- [ ] **Проверить текущую версию миграции**
  ```bash
  ./migrate.sh current
  ```
  
- [ ] **Посмотреть историю миграций**
  ```bash
  ./migrate.sh history
  ```

- [ ] **Убедиться, что миграция не применена**
  ```bash
  docker exec -it employees_app psql -U postgres -d employee_cabinet -c "\dt departments"
  ```
  Если таблица departments уже существует, миграция может быть уже применена.

## ✅ Применение миграций

- [ ] **Применить миграцию**
  ```bash
  ./migrate.sh upgrade
  ```
  
  Или вручную:
  ```bash
  docker exec -it employees_app sh -c "cd /app && alembic upgrade head"
  ```

- [ ] **Проверить, что миграция применилась**
  ```bash
  ./migrate.sh current
  ```
  Должно показать: `001 (head)`

## ✅ Проверка после миграции

- [ ] **Таблица departments создана**
  ```bash
  docker exec -it employees_app psql -U postgres -d employee_cabinet -c "\dt departments"
  ```

- [ ] **В таблице 6 отделов**
  ```bash
  docker exec -it employees_app psql -U postgres -d employee_cabinet -c "SELECT COUNT(*) FROM departments;"
  ```
  Должно вернуть: `6`

- [ ] **У таблицы users есть поле department_id**
  ```bash
  docker exec -it employees_app psql -U postgres -d employee_cabinet -c "\d users" | grep department_id
  ```

- [ ] **У таблицы users НЕТ старого поля department (текст)**
  ```bash
  docker exec -it employees_app psql -U postgres -d employee_cabinet -c "\d users" | grep "department "
  ```
  Не должно ничего найти (или только department_id)

- [ ] **Пользователи назначены на отделы**
  ```bash
  docker exec -it employees_app psql -U postgres -d employee_cabinet -c "SELECT COUNT(*) FROM users WHERE department_id IS NOT NULL;"
  ```

## ✅ Проверка приложения

- [ ] **Приложение запускается без ошибок**
  ```bash
  docker logs employees_app --tail 50
  ```
  Не должно быть ошибок валидации или миграции.

- [ ] **API отвечает**
  ```bash
  curl http://localhost:8000/docs
  ```
  Или откройте в браузере: http://localhost:8000

- [ ] **Админ-панель работает**
  Откройте: http://localhost:8000/admin/users
  
- [ ] **Dropdown с отделами отображается**
  В админ-панели нажмите "Редактировать" на любом пользователе.
  Поле "Отдел" должно быть dropdown с 6 вариантами:
  - Бухгалтерия
  - Кадры
  - Инженерия
  - Юридический
  - Администрация
  - Общий

- [ ] **Можно изменить отдел пользователя**
  Выберите отдел и сохраните. Проверьте, что изменения применились.

## 🔴 Если что-то не работает

### Проблема: Контейнер не запущен
```bash
# Запустить контейнеры
docker-compose up -d

# Проверить статус
docker ps
```

### Проблема: База данных не отвечает
```bash
# Проверить логи БД
docker logs postgres_container_name

# Перезапустить БД
docker-compose restart db
```

### Проблема: Миграция не применяется
```bash
# Посмотреть подробный вывод
docker exec -it employees_app sh -c "cd /app && alembic upgrade head -v"

# Проверить логи
docker logs employees_app --tail 100
```

### Проблема: Ошибка "Can't locate revision"
```bash
# Инициализировать alembic_version
docker exec -it employees_app sh -c "cd /app && alembic stamp base"
docker exec -it employees_app sh -c "cd /app && alembic upgrade head"
```

### Проблема: Ошибка "Table already exists"
```bash
# Проверить текущую версию
docker exec -it employees_app sh -c "cd /app && alembic current"

# Если показывает что-то старое, пометить текущую версию
docker exec -it employees_app sh -c "cd /app && alembic stamp 001"
```

### Проблема: Приложение не запускается после миграции
```bash
# 1. Посмотреть логи
docker logs employees_app

# 2. Откатить миграцию
./migrate.sh downgrade -1

# 3. Восстановить из бэкапа
docker exec -i postgres_container psql -U postgres -d employee_cabinet < backup_DATE.sql

# 4. Попробовать снова
./migrate.sh upgrade
```

## 📊 Команды для диагностики

```bash
# Версия Alembic
docker exec employees_app alembic --version

# Текущая ревизия
docker exec -it employees_app sh -c "cd /app && alembic current"

# История миграций
docker exec -it employees_app sh -c "cd /app && alembic history"

# Список таблиц в БД
docker exec -it employees_app psql -U postgres -d employee_cabinet -c "\dt"

# Структура таблицы users
docker exec -it employees_app psql -U postgres -d employee_cabinet -c "\d users"

# Структура таблицы departments
docker exec -it employees_app psql -U postgres -d employee_cabinet -c "\d departments"

# Количество записей
docker exec -it employees_app psql -U postgres -d employee_cabinet -c "SELECT 
  (SELECT COUNT(*) FROM users) as users_count,
  (SELECT COUNT(*) FROM departments) as departments_count,
  (SELECT COUNT(*) FROM users WHERE department_id IS NOT NULL) as users_with_department;"
```

## 💾 Восстановление

Если всё пошло не так:

1. **Остановить приложение**
   ```bash
   docker-compose down
   ```

2. **Восстановить БД из резервной копии**
   ```bash
   docker-compose up -d db
   docker exec -i postgres_container psql -U postgres -d employee_cabinet < backup_ДАТА.sql
   ```

3. **Запустить приложение**
   ```bash
   docker-compose up -d
   ```

4. **Проверить, что всё работает**
   ```bash
   curl http://localhost:8000/docs
   ```

## 📞 Получить помощь

Если проблема не решена:

1. Соберите диагностическую информацию:
   ```bash
   echo "=== Docker PS ===" > debug_info.txt
   docker ps >> debug_info.txt
   echo -e "\n=== App Logs ===" >> debug_info.txt
   docker logs employees_app --tail 100 >> debug_info.txt
   echo -e "\n=== Alembic Current ===" >> debug_info.txt
   docker exec employees_app sh -c "cd /app && alembic current" >> debug_info.txt 2>&1
   echo -e "\n=== Environment ===" >> debug_info.txt
   docker exec employees_app env | grep POSTGRES >> debug_info.txt
   ```

2. Просмотрите файл `debug_info.txt`

3. Используйте документацию:
   - [DOCKER_MIGRATION_GUIDE.md](./DOCKER_MIGRATION_GUIDE.md)
   - [EXAMPLES.md](./EXAMPLES.md)
   - [QUICK_REFERENCE.md](./QUICK_REFERENCE.md)
