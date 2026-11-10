# Результаты пилота (50 трейсов, базовый прогон судьи, без вставленных заявлений)

Файл на прогон: по строке на трейс, поля `case_id`, `label` (метка BFCL), `n_tokens`, `logp_yes`, `logp_no`, `p_yes_norm`.
В прогонах с рассуждением (`*_think`) дополнительно `think_tokens`, `finished_thinking`, `own_answer`, `thinking`.

| файл | модель | вход | рассуждение |
|---|---|---|---|
| minicpm5_2b_full_nothink | MiniCPM5-2B | полный трейс | нет |
| qwen3_14b_full_nothink / _think | Qwen3-14B | полный трейс | нет / да |
| qwen3_14b_nosys_nothink / _think | Qwen3-14B | без системного промпта и описаний инструментов | нет / да |
| qwen3_14b_compact_nothink / _think | Qwen3-14B | то же + простые метки ролей | нет / да |

- `all_runs_wide.csv` — вероятность «Да» по всем прогонам в одной таблице, с BFCL-меткой и ручной категорией.
- `manual_review.csv` — ручная разметка (моя, не независимая): success_ok / genuine_visible / genuine_weak / looks_success.
- `*_PARTIAL_mac_13traces.jsonl` — неполный локальный прогон на Mac (13 из 50), для справки.
- `qwen3_14b_think_probe_6traces.jsonl` — пробный запуск рассуждения на 6 трейсах (батч 3).
Сэмплирование в прогонах с рассуждением: температура 0,6, top_p 0,95, top_k 20, seed 0.
