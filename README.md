# О проекте

Сегментация дорожной поверхности. Пользователь загружает картинку через браузер, а нейросеть строит маску дороги. Это лёгкая версия проекта, оптимизированная для дешёвого сервера.

Система состоит из двух частей:

- **`server/`** — FastAPI на VPS. Принимает картинки, хранит задачи в SQLite, отдаёт результаты, раздаёт задачи воркеру и чистит старые файлы.
- **`worker/`** — ML-воркер на твоей машине. Опрашивает сервер, гоняет нейросеть на процессоре и возвращает результат.

Общение между воркером и сервером происходит по HTTP. Вместо Redis используется SQLite, чтобы всё работало на дешёвом VPS. Реализация с Redis и Docker доступна по [ссылке](https://github.com/Lebanvla/science_work_site).

---

## Запуск

### Сервер (на VPS)

#### 1. Настройка Python-окружения

```bash
cd server
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

#### 2. Установка и настройка Nginx

Nginx будет принимать запросы из интернета на порт 80 и передавать их на `uvicorn`.

Установи nginx:
```bash
sudo apt update
sudo apt install nginx -y
```

Скопируй конфиг из проекта в системную папку nginx:
```bash
sudo cp nginx/roadseg.conf /etc/nginx/sites-available/roadseg
sudo ln -s /etc/nginx/sites-available/roadseg /etc/nginx/sites-enabled/
```

Удали дефолтный конфиг nginx, чтобы он не перехватывал запросы:
```bash
sudo rm /etc/nginx/sites-enabled/default
```

Проверь синтаксис и перезапусти nginx:
```bash
sudo nginx -t
sudo systemctl restart nginx
```

#### 3. Запуск сервера

```bash
source .venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8000
```

После этого сайт будет доступен по адресу `http://<IP_VPS>` (через Nginx).

---

### Воркер

```bash
cd worker
python -m venv .venv
source .venv/bin/activate

# Ставим CPU-версию torch, чтобы не качать тяжелые CUDA-библиотеки
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

pip install -r requirements.txt
cp .env.example .env

python worker.py
```

> Запускать строго из папки компонента — импорты в коде относительные.

---

## Настройки `.env`

### `server/.env`

| Переменная | По умолчанию | Что значит |
|---|---|---|
| `SERVER_HOST` | `0.0.0.0` | Интерфейс для uvicorn. |
| `SERVER_PORT` | `8000` | Порт для uvicorn. |
| `MAX_UPLOAD_SIZE_BYTES` | `26214400` | Максимальный размер картинки (25 МБ). |
| `WORKER_TOKEN` | — | **Обязательно.** Токен для воркера. Должен совпадать с `worker/.env`. |
| `CLEANUP_INPUT_DELAY_SECONDS` | `600` | Через сколько секунд удалять исходник после завершения. |
| `CLEANUP_OUTPUT_DELAY_SECONDS` | `3600` | Через сколько секунд удалять результат после завершения. |
| `CLEANUP_INTERVAL_SECONDS` | `60` | Как часто просыпается очистка файлов. |
| `TASK_STALE_SECONDS` | `1800` | Через сколько секунд задача считается зависшей. |
| `DB_PATH` | `storage/tasks.db` | Путь к SQLite. |

### `worker/.env`

| Переменная | По умолчанию | Что значит |
|---|---|---|
| `API_BASE_URL` | `http://127.0.0.1:8000` | Адрес сервера. |
| `WORKER_TOKEN` | — | **Обязательно.** Тот же, что в `server/.env`. |
| `POLL_INTERVAL_SECONDS` | `5` | Как часто опрашивать сервер. |
| `MODEL_NAME` | `nvidia/segformer-b0-...` | HuggingFace-модель. |
| `ROAD_CLASS_NAME` | `road` | Имя класса дороги. |
| `ROAD_CLASS_INDEX` | — | Явный индекс класса. |
| `DEVICE` | `auto` | `auto` / `cuda` / `cpu`. |

### Как сгенерировать токен

Выполни в терминале:
```bash
openssl rand -hex 32
```

Полученную строку вставь в **оба** `.env` файла — значения должны совпадать, иначе сервер вернёт 403.

---

## API (кратко)

**Публичные эндпоинты:**

- `GET /` — веб-интерфейс
- `POST /predict` — загрузить картинку, вернёт `task_id` и `picture_hash`
- `GET /get/{picture_hash}` — узнать статус: `processing` / `ready` / `error`
- `GET /static/output/{file}` — получить готовый PNG

**Для воркера (нужен заголовок `Authorization: Bearer <WORKER_TOKEN>`):**

- `GET /worker/tasks/pending` — взять задачу в работу
- `GET /worker/tasks/{id}/image` — скачать исходник
- `POST /worker/tasks/{id}/result` — загрузить результат
- `POST /worker/tasks/{id}/fail` — сообщить об ошибке

---

## Частые проблемы

- **403 на `/worker/*`** — токены в двух `.env` не совпадают.
- **`ModuleNotFoundError: config`** — запускаешь не из папки компонента.
- **`Connection refused`** — сервер не на `0.0.0.0`, порт закрыт фаерволом или неверный `API_BASE_URL`.
- **Задача висит в `processing`** — воркер упал, очистка вернёт задачу в `pending` через `TASK_STALE_SECONDS`.
- **`Result file was already cleaned up`** — пользователь открыл результат позже `CLEANUP_OUTPUT_DELAY_SECONDS`, увеличь таймаут.