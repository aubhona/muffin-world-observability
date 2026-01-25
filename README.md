# Muffin Wallet

Проект состоит из сервиса muffin-wallet (Spring Boot), muffin-currency (Golang), миграций БД на Liquibase и Helm-чартов для развёртывания в Kubernetes с мониторингом через Prometheus.

## Содержание

- [Требования](#требования)
- [Установка и запуск](#установка-и-запуск)
- [Проверка работоспособности](#проверка-работоспособности)
- [Мониторинг с Prometheus](#мониторинг-с-prometheus)
- [PromQL запросы](#promql-запросы)
- [Тестирование метрик](#тестирование-метрик)
- [Grafana](#grafana)
- [Структура проекта](#структура-проекта)
- [Откат релиза](#откат-релиза)
- [Удаление](#удаление)

## Требования

- Docker
- Minikube
- kubectl
- helm (версия 3.x)
- helmfile

## Установка и запуск

### 1. Запуск minikube

```bash
minikube start --cpus=4 --memory=8192
minikube addons enable ingress
minikube addons enable metrics-server
```

### 2. Настройка доступа через ingress

Для работы ingress нужно запустить `minikube tunnel` в отдельном терминале:

```bash
# В отдельном терминале (оставить запущенным)
sudo minikube tunnel
```

После запуска tunnel добавить в `/etc/hosts`:

```bash
echo "127.0.0.1 muffin-wallet.com prometheus.local grafana.local" | sudo tee -a /etc/hosts
```

### 3. Запуск PostgreSQL

```bash
cd muffin-wallet/local-env
docker-compose up -d
```

### 4. Сборка образов

Если нужно пересобрать образы:

```bash
export REGISTRY=your-registry
export VERSION=1.1.0

cd muffin-wallet
docker build -t $REGISTRY/muffin-wallet:$VERSION .
docker push $REGISTRY/muffin-wallet:$VERSION

docker build -f MigrationDockerfile -t $REGISTRY/muffin-wallet-migrations:$VERSION .
docker push $REGISTRY/muffin-wallet-migrations:$VERSION
```

Обновить `deploy/charts/muffin-wallet/values.yaml` с новыми значениями registry и tag.

### 5. Развертывание через helmfile

```bash
cd deploy
helmfile repos
helmfile apply
```

Эта команда развернет:
- kube-prometheus-stack в namespace monitoring
- muffin-currency в namespace default
- muffin-wallet в namespace default

Ожидайте 3-5 минут пока все поды запустятся.

## Проверка работоспособности

### Проверка статуса подов

```bash
kubectl get pods -n monitoring
kubectl get pods -n default
```

Все поды должны быть в статусе Running.

### Проверка ServiceMonitor

```bash
kubectl get servicemonitor -n default
```

Должен быть создан servicemonitor для muffin-wallet.

### Доступ к интерфейсам

После запуска `minikube tunnel` и настройки hosts файла сервисы доступны по адресам:

- Muffin Wallet API: http://muffin-wallet.com
- Prometheus: http://prometheus.local (если включен ingress для Prometheus)
- Grafana: http://grafana.local (если включен ingress для Grafana, admin/admin)

**Важно:** `minikube tunnel` должен быть запущен для работы ingress.

### Проверка в Prometheus UI

Откройте http://prometheus.local и перейдите в Status -> Targets. Найдите target с именем `default/muffin-wallet/0`. Статус должен быть UP.

Выполните простой запрос в Graph:

```promql
up{job="muffin-wallet"}
```

Результат должен быть равен количеству подов указанном в replicaSet (2).

### Проверка метрик приложения

Через ingress (требуется запущенный `minikube tunnel`):

```bash
curl http://muffin-wallet.com/actuator/prometheus
```

Альтернативно, через port-forward (не требуется tunnel):

```bash
kubectl port-forward -n default svc/muffin-wallet 8081:80
curl http://localhost:8081/actuator/prometheus
```

## Мониторинг с Prometheus

### Архитектура

В проекте используется kube-prometheus-stack, который включает:
- Prometheus Operator
- Prometheus сервер с постоянным хранением (30 дней, 10GB)
- Grafana для визуализации
- Node Exporter для метрик узлов Kubernetes
- Kube State Metrics для метрик объектов Kubernetes

Метрики приложения собираются через ServiceMonitor, который автоматически настраивает Prometheus на сбор метрик с endpoint /actuator/prometheus.

### Сбор метрик

Spring Boot Actuator экспортирует следующие типы метрик:

- HTTP метрики (http_server_requests_*)
- Метрики пула соединений HikariCP (hikaricp_connections_*)
- JVM метрики (jvm_memory_*, jvm_gc_*, jvm_threads_*)
- Метрики Tomcat (tomcat_threads_*)

Prometheus собирает метрики каждые 15 секунд согласно настройкам в ServiceMonitor.

### Постоянное хранение

Prometheus настроен с PersistentVolume:
- Retention: 30 дней
- Storage: 10GB
- Access mode: ReadWriteOnce

Это позволяет хранить исторические данные и анализировать тренды.

## PromQL запросы

Ниже представлены основные запросы для выполнения задания. Представлены в формате вставки в Grafana. Для выполнения в Prometheus $__rate_interval заменить на желаемый интервал подсчёта.

### 1. Количество запросов в секунду по каждому методу REST API

```promql
sum by (method, uri) (
  rate(http_server_requests_seconds_count{
    service="muffin-wallet",
    uri!~"/actuator.*|/swagger-ui.*|/v3/api-docs.*|/swagger-resources.*|/webjars.*|/favicon\\.ico"
  }[$__rate_interval])
)
```

Этот запрос показывает RPS (requests per second) с разбивкой по HTTP методу (GET, POST) и URI, исключая enpoint по сборку метрик/сваггера.

### 2. Количество ошибок

```promql
sum(
  rate(logback_events_total{
    service="muffin-wallet",
    level="error"
  }[$__rate_interval])
)
```

### 3. 99-й персентиль времени ответа HTTP

```promql
histogram_quantile(0.99,
    sum by (uri, method, le) (
      rate(http_server_requests_seconds_bucket{
        service="muffin-wallet",
        uri!~"/actuator.*|/swagger-ui.*|/v3/api-docs.*|/swagger-resources.*|/webjars.*|/favicon\\.ico"
      }[$__rate_interval])
    )
  )
```

Результат в секундах. С учетом добавленных sleep в БД (для получения количества активных соединений), значения будут около 0.2-0.3s для транзакций.

### 4. Количество активных соединений к базе данных

#### Активные соединения:

```promql
sum(hikaricp_connections_active{service="muffin-wallet"})
```

### Дополнительные метрики

#### Общее количество соединений в пуле:

```promql
sum(hikaricp_connections_active{service="muffin-wallet"})
```

#### Потоки, ожидающие соединение:

```promql
sum(hikaricp_connections_pending{service="muffin-wallet"})
```

#### CPU:

```promql
sum(process_cpu_usage{service="muffin-wallet"})
```

## Тестирование метрик

### Генерация нагрузки

Для тестирования метрик используйте скрипт:

```bash
cd deploy
pip install aiohttp
./generate-load.py

# С параметрами
./generate-load.py --concurrent 200 --requests 2000 --sleep 0.01
```

Параметры:
- `--url` - базовый URL приложения
- `--requests` - общее количество запросов
- `--sleep` - задержка между пакетами запросов
- `--concurrent` - количество одновременных запросов (по умолчанию 10)

Скрипт создаст кошельки и выполнит серию запросов к API.  
После завершения подождите 1-2 минуты и проверьте метрики в Prometheus.  
На период работы скрипта RPS должен подняться ~ на значение requests/sleep, и упасть после завершения скрипта. 
Аналогичный график должен быть Log errors rate, причём он должен совпадать с метрикой RPS GET /**, т.к. эта метрика пишется,если был вызван несуществующий endpoint, и как раз в этом случае и пишется error лог.  
HTTP latency должен быть большой для endpoint транзакций (/v1/muffin-wallet/{id}/transaction): значения будут около 0.2-0.3s из-за добавления sleep в запрос в БД.
Это нужно было делать для отслеживания количества активных подключений в базу (у меня метрика прокрасилась при запуске генератора с параметрами --concurrent 200 --requests 2000 --sleep 0.01).

### Ручные запросы через ingress

Создать кошелек:

```bash
curl -X POST http://muffin-wallet.com/v1/muffin-wallets \
  -H "Content-Type: application/json" \
  -d '{"owner_name": "Test Wallet", "type": "CARAMEL"}'
```

Получить список кошельков:

```bash
curl http://muffin-wallet.com/v1/muffin-wallets
```

Получить конкретный кошелек:

```bash
curl http://muffin-wallet.com/v1/muffin-wallet/{id}
```

Выполнить транзакцию:

```bash
curl -X POST http://muffin-wallet.com/v1/muffin-wallet/{from_id}/transaction \
  -H "Content-Type: application/json" \
  -d '{"to_muffin_wallet_id": "{to_id}", "amount": 100.50}'
```

Сгенерировать ошибки для тестирования метрик:

```bash
curl http://muffin-wallet.com/v1/nonexistent
```

## Grafana

Grafana доступна по адресу http://grafana.local (логин: admin, пароль: admin).

Предустановленные дашборды:
- **muffin-wallet metrics** - основной дашборд с панелями для всех требуемых заданием метрик (создается автоматически при деплое)
- Java SpringBoot APM
- JVM (Micrometer)

Дашборд "muffin-wallet metrics" автоматически создается через ConfigMap с label `grafana_dashboard: "1"`. Grafana sidecar автоматически подхватывает дашборды из таких ConfigMap.

Панели в дашборде:
1. **RPS by method + uri** - количество запросов в секунду по методам
2. **Log errors rate** - количество ошибок в логах
3. **HTTP latency p99** - 99-й персентиль времени ответа
4. **DB connections (HikariCP)** - активные соединения к БД

После развертывания дашборд появится автоматически в списке дашбордов Grafana.

## Структура проекта

```
hw5/
├── README.md
├── muffin-wallet/               
├── muffin-currency/             
└── deploy/
    ├── helmfile.yaml            # Оркестрация развертывания
    ├── generate-load.py         # Скрипт генерации нагрузки (python)
    └── charts/
        ├── kube-prometheus-stack/
        │   └── values.yaml      # Конфигурация Prometheus Operator
        ├── muffin-wallet/
        │   ├── values.yaml      # Конфигурация приложения
        │   └── templates/
        │       ├── servicemonitor.yaml    # Сбор метрик
        │       ├── grafana-dashboard.yaml # Кастомный дашборд
        │       └── service.yaml           # Service
        └── muffin-currency/
```

## Откат релиза

Посмотреть историю:

```bash
helm history muffin-wallet
```

Откатить релиз:

```bash
helm rollback muffin-wallet <REVISION>
```

Перед откатом запустится Job db-migration-rollback-job, который откатит схему БД.

## Удаление

Удалить все релизы:

```bash
cd deploy
helmfile destroy
```

Удалить namespace:

```bash
kubectl delete namespace monitoring
```

Остановить minikube:

```bash
minikube stop
```
