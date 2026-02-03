# Muffin World Observability

Проект состоит из двух интегрированных микросервисов: muffin-wallet (Spring Boot) для управления кошельками и транзакциями, и muffin-currency (Golang) для конвертации валют. Включает миграции БД на Liquibase и Helm-чарты для развёртывания в Kubernetes. Реализован полный стек наблюдаемости: мониторинг через Prometheus, логирование через Loki и распределённый трейсинг через Tempo.

## Содержание

- [Требования](#требования)
- [Установка и запуск](#установка-и-запуск)
- [Проверка работоспособности](#проверка-работоспособности)
- [Проверка интеграции с muffin-currency](#проверка-интеграции-с-muffin-currency)
- [Мониторинг с Prometheus](#мониторинг-с-prometheus)
- [PromQL запросы](#promql-запросы)
- [Тестирование метрик](#тестирование-метрик)
- [Grafana](#grafana)
- [Логирование с Loki](#логирование-с-loki)
- [Трейсинг с Tempo](#трейсинг-с-tempo)
- [Поиск логов по TraceID и уровню](#поиск-логов-по-traceid-и-уровню)
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

muffin-currency читает `ZIPKIN_ENDPOINT` из переменной окружения (для отправки трейсов в Tempo). muffin-wallet собран с зависимостями для трейсинга (Brave, Zipkin reporter, datasource-micrometer для БД). Без пересборки образов трейсы не будут собираться.

Для локального тестирования в minikube:

```bash
cd muffin-currency
eval $(minikube docker-env)
docker build -t aubhon/muffin-currency:1.1.1 .
cd ..

cd muffin-wallet
./gradlew clean build -x test
eval $(minikube docker-env)
docker build -t aubhon/muffin-wallet:1.1.1 .
docker build -f MigrationDockerfile -t aubhon/muffin-wallet-migrations:1.1.1 .
cd ..
```

Для публикации в registry обновить tag и push, затем обновить `deploy/charts/muffin-wallet/values.yaml` и образ в чарте muffin-currency.

### 5. Развертывание через helmfile

```bash
cd deploy
helmfile repos
helmfile apply
```

Эта команда развернет:
- kube-prometheus-stack (Prometheus, Grafana, datasources Loki/Tempo) в namespace monitoring
- loki-stack (Loki + Promtail) в namespace monitoring
- tempo в namespace monitoring
- grafana-dashboards (дашборд Muffin Observability) в namespace monitoring
- muffin-currency в namespace default
- muffin-wallet в namespace default

Ожидайте 5-7 минут пока все поды запустятся.

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

Должны быть созданы servicemonitor для muffin-wallet и muffin-currency.

### Доступ к интерфейсам

После запуска `minikube tunnel` и настройки hosts файла сервисы доступны по адресам:

- Muffin Wallet API: http://muffin-wallet.com
- Prometheus: http://prometheus.local (если включен ingress для Prometheus)
- Grafana: http://grafana.local (если включен ingress для Grafana, admin/admin)

**Важно:** `minikube tunnel` должен быть запущен для работы ingress.

### Проверка в Prometheus UI

Откройте http://prometheus.local и перейдите в Status -> Targets. Должны быть таргеты `default/muffin-wallet/0` и `default/muffin-currency/0`. Статус обоих — UP.

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

### Проверка интеграции с muffin-currency

muffin-wallet при переводе между разными валютами вызывает muffin-currency за курсом (endpoint `/rate?from=X&to=Y`), конвертация выполняется в памяти, схема БД не меняется. Валюты: CARAMEL, CHOKOLATE, PLAIN.

Проверка:

```bash
# Создать два кошелька с разными валютами
curl -X POST http://muffin-wallet.com/v1/muffin-wallets -H "Content-Type: application/json" -d '{"owner_name": "A", "type": "CARAMEL"}'
curl -X POST http://muffin-wallet.com/v1/muffin-wallets -H "Content-Type: application/json" -d '{"owner_name": "B", "type": "CHOKOLATE"}'

# Транзакция с конвертацией (подставить id из ответов)
curl -X POST http://muffin-wallet.com/v1/muffin-wallet/<FROM_ID>/transaction \
  -H "Content-Type: application/json" \
  -d '{"to_muffin_wallet_id": "<TO_ID>", "amount": 100, "from_currency": "CARAMEL", "to_currency": "CHOKOLATE"}'
```

В логах muffin-wallet будут вызовы currency, в логах muffin-currency — обработка `/rate`. В Tempo (Grafana Explore -> Tempo -> Search) видна цепочка: POST transaction (wallet) -> GET /rate (currency).

## Мониторинг с Prometheus

### Архитектура

В проекте используется kube-prometheus-stack, который включает:
- Prometheus Operator
- Prometheus сервер с постоянным хранением (30 дней, 10GB)
- Grafana для визуализации
- Node Exporter для метрик узлов Kubernetes
- Kube State Metrics для метрик объектов Kubernetes

Метрики приложений собираются через ServiceMonitor: muffin-wallet — с /actuator/prometheus, muffin-currency — с /metrics. В values kube-prometheus-stack заданы serviceMonitorSelector и serviceMonitorNamespaceSelector так, чтобы подхватывались ServiceMonitor из namespace default.

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

Скрипт создаёт кошельки трёх валют (CARAMEL, CHOKOLATE, PLAIN) и выполняет транзакции с конвертацией — при разных валютах вызывается muffin-currency за курсом.  
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

Выполнить транзакцию (с конвертацией — указать from_currency и to_currency):

```bash
curl -X POST http://muffin-wallet.com/v1/muffin-wallet/{from_id}/transaction \
  -H "Content-Type: application/json" \
  -d '{"to_muffin_wallet_id": "{to_id}", "amount": 100.50, "from_currency": "CARAMEL", "to_currency": "CHOKOLATE"}'
```

Сгенерировать ошибки для тестирования метрик:

```bash
curl http://muffin-wallet.com/v1/nonexistent
```

## Grafana

Grafana доступна по адресу http://grafana.local (логин: admin, пароль: admin).

Дополнительные datasource (настроены в kube-prometheus-stack): Loki для логов, Tempo для трейсов. Связь логов и трейсов по traceId включена (из лога можно перейти к трейсу, из трейса — к логам).

Дашборды:
- **Muffin Observability** — общий дашборд (chart grafana-dashboards): метрики muffin-wallet и muffin-currency, логи Loki, трейсы Tempo. Подхватывается sidecar по label `grafana_dashboard: "1"`.
- Java SpringBoot APM, JVM (Micrometer), Postgres — из kube-prometheus-stack.

В дашборде Muffin Observability: RPS по методам/URI, Log errors rate, HTTP latency p99, DB connections (HikariCP), панели логов и трейсов. Трейсы удобнее смотреть в Explore -> Tempo -> Search.

После развертывания дашборды появятся автоматически в списке дашбордов Grafana.

## Логирование с Loki

Loki и Promtail развёрнуты в namespace monitoring (loki-stack). Promtail собирает логи из подов кластера и отправляет в Loki. Парсинг — в запросах LogQL: для muffin-currency используется `| json`, для muffin-wallet — `| regexp` по формату лога.

Примеры запросов в Grafana Explore (datasource Loki):

```logql
{container="muffin-wallet"}
{container="muffin-currency"} | json
{container="muffin-currency"} | json | level="ERROR"
{container="muffin-currency"} | json | trace_id="<id>"
{container="muffin-wallet"} | regexp `\[muffin-wallet,(?P<traceId>[^,]+),` | traceId="<id>"
```

Loki настроен с retention 30 дней, 10GB (в values loki-stack).

## Трейсинг с Tempo

Tempo развёрнут в namespace monitoring. Оба приложения отправляют трейсы по протоколу Zipkin (порт 9411). muffin-wallet: Micrometer Tracing (Brave), Zipkin reporter, datasource-micrometer для трейсинга обращений к БД. muffin-currency: переменная окружения ZIPKIN_ENDPOINT (в кластере указывается на tempo.monitoring.svc:9411).

Просмотр: Grafana -> Explore -> выбрать datasource Tempo -> Search -> Run query. Можно фильтровать по service name (muffin-wallet, muffin-currency). В трейсе видна цепочка вызовов. В настройках datasource Tempo включена связь с Loki (traces to logs).

Tempo настроен с retention 30 дней, 10GB.

## Поиск логов по TraceID и уровню

TraceID в логах muffin-wallet — в квадратных скобках: `[muffin-wallet,<traceId>,<spanId>]`. В muffin-currency — в JSON поле `trace_id`. Уровень в muffin-currency: поле `level` в JSON; в muffin-wallet — парсинг через regexp.

По TraceID (muffin-currency): `{container="muffin-currency"} | json | trace_id="YOUR_TRACE_ID"`

По TraceID (muffin-wallet): `{container="muffin-wallet"} | regexp \`\[muffin-wallet,(?P<traceId>[^,]+),\` | traceId="YOUR_TRACE_ID"`

По уровню ERROR (muffin-currency): `{container="muffin-currency"} | json | level="ERROR"`

По уровню ERROR (muffin-wallet): `{container="muffin-wallet"} | regexp \`\s(?P<level>\w+)\s\` | level="ERROR"`

TraceID для подстановки можно скопировать из Tempo: открыть трейс в Explore -> Tempo, скопировать traceId из атрибутов.

## Структура проекта

```
hw6/
├── README.md
├── muffin-wallet/               # Spring Boot
├── muffin-currency/             # Go
└── deploy/
    ├── helmfile.yaml            # Оркестрация развертывания
    ├── generate-load.py         # Скрипт генерации нагрузки (с конвертацией валют)
    └── charts/
        ├── kube-prometheus-stack/
        │   └── values.yaml      # Prometheus, Grafana, datasources Loki/Tempo
        ├── loki-stack/
        │   └── values.yaml      # Loki + Promtail
        ├── tempo/
        │   └── values.yaml      # Tempo для трейсов
        ├── grafana-dashboards/
        │   └── dashboards/      # Дашборд Muffin Observability (метрики, логи, трейсы)
        ├── muffin-wallet/
        │   ├── values.yaml
        │   └── templates/
        │       ├── servicemonitor.yaml, service.yaml, deployment.yaml
        │       ├── configmap.yaml, configmap-env.yaml, secret.yaml
        │       ├── db-migration-job.yaml, db-migration-rollback-job.yaml
        │       └── ingress.yaml
        └── muffin-currency/
            ├── values.yaml
            └── templates/
                ├── servicemonitor.yaml
                ├── service.yaml
                ├── deployment.yaml
                ├── _helpers.tpl
                └── tests/
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
