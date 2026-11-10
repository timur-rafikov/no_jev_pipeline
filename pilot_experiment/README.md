# Пилот: базовое качество малого судьи на агентских трейсах

Исследовательский вопрос: как LLM-судья (≤4B) сопоставляет свидетельства исполнения с заявлениями в агентском трейсе и как на это влияют содержание заявления и его источник. Этот репозиторий — первый шаг: **базовый прогон судьи на 50 исходных трейсах без вставленных заявлений**.

- `traces_50.jsonl` — 50 трейсов BFCL multi-turn (25 успешных и 25 провальных по метке BFCL, 50 уникальных задач).
- `baseline_judge.py` — один прямой проход, логиты Yes/No, метрики. Без reasoning, без API.
- `index.csv`, `manifest.json` — сводка и манифест отбора (seed `pilot-50`).

**Оговорка:** метка — оценка BFCL по состоянию симулятора, а не проверенный видимый исход трейса. Метрики показывают согласие судьи с BFCL, не точность относительно истины.

## Запуск в Docker (нужен NVIDIA GPU и nvidia-container-toolkit)

```bash
docker build -t judge-pilot .
docker run --rm --gpus all -v "$PWD/data:/data" judge-pilot
docker run --rm -v "$PWD/data:/data" judge-pilot summarize --results /data/out/baseline_results.jsonl
```

Веса (~5 ГБ) скачиваются при первом запуске в `data/hf` и переиспользуются. Результаты — в `data/out/`. Прогон продолжаемый: повторный запуск пропускает готовые трейсы.

## Запуск на vast.ai без Docker

Инстанс из шаблона PyTorch (CUDA), затем `git clone <repo> && cd <repo> && bash run_on_vast.sh`.
Для запуска образа из реестра его нужно сначала собрать и опубликовать (в репозиторий это не включено).

## Локально

```bash
pip install -r requirements.txt   # Python 3.10+
python3 baseline_judge.py render
python3 baseline_judge.py run --model openbmb/MiniCPM5-2B
python3 baseline_judge.py summarize
```
Устройство выбирается само: cuda, затем mps, затем cpu. Одна оценка локального прогона на Apple M3: 11–22 с на трейс (4,8–10,3 тыс. токенов). Образ и сборка Docker здесь **не проверялись**.

## Данные и лицензия

Трейсы получены из публичных исполнений [HuanzhiMao/BFCL-Result](https://github.com/HuanzhiMao/BFCL-Result) (release 2025-11-03, commit `cadd76a8…`), лицензия Apache-2.0 (`LICENSE-DATA.txt`, `NOTICE-DATA.txt`). Лицензия на код репозитория не выбрана.
