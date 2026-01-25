# Muffin Wallet HW3

Проект состоит из:

- сервиса `muffin-wallet` (Spring Boot);
- миграций БД на Liquibase (отдельный Docker-образ);
- Helm-чартов в `deploy/charts`;
- `helmfile.yaml` в `deploy/` для развёртывания всего стека.

Миграции запускаются как Helm‐hook’и (`pre-install`, `pre-upgrade`, `pre-rollback`) через отдельный Job.

---

## Предварительные требования

- установлен Docker;
- установлен Kubernetes-кластер;
- установлен `helm` и `helmfile`;
- есть запущенный PostgreSQL (url/логин/пароль прописаны в `values.yaml` чарта `muffin-wallet`), для dev можно запустить compose `muffin-wallet/local-env/docker-compose.yaml`;
- доступен Docker-registry для пуша образов.

---

## 1. Сборка и публикация образов

Определяем переменные (подставь свои значения):

```bash
export REGISTRY=<your-registry>
export VERSION=1.0.0
```

### 1.1 Образ сервиса muffin-wallet

Из папки muffin-wallet:

```bash
docker build -t $REGISTRY/muffin-wallet:$VERSION .
docker push $REGISTRY/muffin-wallet:$VERSION
```

### 1.2 Образ миграций muffin-wallet

Из папки `muffin-wallet`:

```bash
docker build \
  -f MigrationDockerfile \
  -t ${REGISTRY}/muffin-wallet-migrations:${VERSION} \
  .

docker push $REGISTRY/muffin-wallet-migrations:$VERSION
```

## 2. Настройка Helm values

Открываем `deploy/muffin-wallet/values.yaml` и указываем репозитории/теги образов и тег БД

## 3. Деплой через Helmfile

Из папки `deploy`:

```bash
helmfile apply
```

`helmfile apply`:

подтянет чарт `muffin-wallet`;

создаст `Job` с миграциями (`db-migration-job.yaml`), который выполнит `liquibase update`;

поднимет Deployment, Service, Ingress и т.д.

### 3.2. Запуск тестов (helm tests)

Из той же папки `deploy`:

```bash
helmfile test
```

Эта команда выполнит `helm test` для релизов, описанных в `helmfile.yam` (см `tests/test-connection.yaml` в каждом чарте).

## 4. Откат релиза и откат миграций

Если нужно откатить релиз muffin-wallet:

1. Смотрим историю релиза:
    ```bash
    helm history muffin-wallet
    ```

2. Откатываем релиз:
    ```bash
    helm rollback muffin-wallet <REVISION>
    ```

Перед изменением ресурсов Helm запустит `Job` `db-migration-rollback-job.yaml` с хуком `pre-rollback`, который выполнит:
```bash
liquibase --changelog-file=changelog/db.changelog-master.yaml rollback <dbTag>
```
и вернёт схему БД к тегу, указанному в `migrations.dbTag`.

## 5. Удаление релиза

Из папки `deploy`:

```bash
helmfile destroy
```
