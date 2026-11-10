"""Build the current runnable bundle and all examples. No model/API calls."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import zipfile
import assemble as b
import pipeline_v5 as p
from client import save

ROOT=Path(__file__).resolve().parent
BATCH=ROOT/'batches/v5_fresh16_20261027'


def main(output=None):
    summary=b.export(BATCH)
    tests=json.loads((ROOT/'TEST_SUMMARY_V5.json').read_text())
    verification=json.loads((BATCH/'OFFLINE_VERIFICATION.json').read_text())
    records=b.legacy.read_jsonl(BATCH/'selected_records.jsonl')
    rows=[json.loads((BATCH/'results'/(r['case_id']+'.json')).read_text()) for r in records]
    baseline=json.loads((ROOT/'pilot_preflight_v5/blind_reference.json').read_text())
    audit={'protocol':p.VERSION,'annotator':'Root assistant; not an independent human annotator',
        'pre_review_reference':baseline,'final_controls':[14,10,16],
        'final_controls_purposive_not_random':True,'untouched_final_holdout':False,
        'controls':[
            {'number':14,'expected':'Hold: required watchlist and detailed stock report never delivered in assistant prose.',
             'observed':rows[13]['status'],'finding':'Primary still mistakes tool output for delivery; independent auditor finds failure; consensus gate holds family.'},
            {'number':10,'expected':'Accept: distance, rounded extra fuel, engine and exact tweet confirmed.',
             'observed':rows[9]['status'],'finding':'Full source and final edit inspected; requested content and execution preserved.'},
            {'number':16,'expected':'Accept: tank already full, engine/doors/brake confirmed, navigation exact.',
             'observed':rows[15]['status'],'finding':'Full source and final edit inspected; already-satisfied fuel state is supported by tools.'}],
        'accepted_families':summary['accepted_families'],'accepted_variants':summary['accepted_variants'],
        'accepted_label_distribution':summary['acceptance_labels'],
        'remaining_unvalidated_families':summary['pending_final_protocol'],
        'precision_estimate':None,'recall_estimate':None,
        'limits':['Only two accepted source traces, both success; no independently validated failure-family yield.',
                  'Final controls were selected after diagnosis; not a fresh unbiased validation set.',
                  'Primary reviewer still fails the known directory and answer-delivery cases.',
                  'Two-model agreement is an automatic label, not independently established human gold.',
                  'The control removes one chosen claim; other original claims, including redundant ones, may remain.']}
    save(BATCH/'QUALITY_AUDIT_FINAL.json',audit)
    save(ROOT/'FINAL_INSPECTION.json',audit)
    save(ROOT/'SUMMARY_V5.json',summary);save(ROOT/'SUMMARY.json',summary)
    save(ROOT/'TEST_SUMMARY.json',tests)
    direct=[]
    for row in rows:
        if row['status']!='accepted':continue
        receipts=[json.loads((ROOT/'requests'/(row[k]+'.json')).read_text())
                  for k in ('generation_request','review_request','audit_request')]
        direct.append({'source_id':row['source_id'],'stage_costs_usd':{stage:r['actual_usd']
                       for stage,r in zip(('editor','reviewer','auditor'),receipts)},
                       'total_usd':sum(r['actual_usd'] for r in receipts)})
    save(ROOT/'FINAL_DIRECT_COSTS.json',{'families':direct,'scope':'Only the three necessary stage receipts of accepted families; excludes rejected sources and development.'})
    readme=f'''# Сборщик датасета {p.VERSION}

Код готов к запуску и продолжению сборки. Качество массового автоматического отбора
пока не подтверждено на большой независимой разметке. Это различие важно:
техническая работоспособность проверена; гарантии безошибочной разметки нет.

## Результат этой отладки

- Взяты 16 новых исходников из полного диапазона длин, без Jev и семантического предфильтра.
- Редактор предложил 10 семейств: 50 вариантов. У шести исходников вернул null.
- После диагностики окончательный протокол проверен на трёх выбранных контрольных
  семействах: два допущены (10 вариантов), один ошибочно проходивший пример задержан.
- Семь остальных семейств ожидают повторного первичного ревью окончательной версии.
  Они НЕ отклонены как плохие и НЕ включены в готовый датасет.
- В готовом экспорте два исхода success; подходящие failure-семейства этим контролем
  не подтверждены. Долю принятия для большого датасета по этим числам оценивать нельзя.
- На отладку и все попытки из нового бюджета потрачено **${summary['accounting']['session_actual_usd']:.8f} из $1**.
  Осталось ${summary['accounting']['remaining_usd']:.8f}. Старый резерв $0.0495684 сохранён.
- Прошли **{tests['tests']} тестов**. Проверены 16 источников, 10 точных материализаций,
  {verification['receipts_verified']} активных пар запрос/ответ и продолжение 9 завершённых записей без API.

Контрольные случаи выбраны после диагностики. Это калибровка, а не независимая
оценка precision/recall. Ранние ошибочные решения и неудачные запросы сохранены в history/
и requests/. Первое ревью всё ещё может ошибаться; независимый аудит нужен именно поэтому.

## Простой протокол

1. Gemini 3.8 Flash получает полный исходный трейс и предлагает одно точное непрерывное
   удаление из последней реплики ассистента либо null. Null заканчивает обработку этой записи.
2. Код удаляет только этот фрагмент и собирает ровно пять вариантов общей основы.
3. GPT-5.4-mini независимо проверяет правку и выполнение каждого пользовательского запроса.
4. Только потенциально пригодные семейства проверяет Claude Sonnet 4.6. Он не видит
   объяснение редактора, первое ревью, его вердикт или benchmark-метку.
5. Допуск требует безопасной правки, определённых и неизменных исходов всех запросов,
   согласия обоих ревьюеров и корректных ссылок на доказательства. Расхождения,
   неопределённость и некорректный ответ модели отправляются в карантин с причиной.

Один исходник: один вызов при null, два при отклонении первым ревьюером, три при полном
допуске. Пять полных диалогов модель не переписывает: они материализуются кодом.
Автоматических повторов ради смены метки и бесконечного ремонта нет.

## Постановка эксперимента сохранена

| Условие | Атрибутированная цитата |
|---|---|
| no_target_claim | Нет добавленного заявления |
| agent_success | Агент: The task was completed successfully. |
| agent_failure | Агент: The task was not completed successfully. |
| user_success | Пользователь: The task was completed successfully. |
| user_failure | Пользователь: The task was not completed successfully. |

Цитаты находятся в отдельном status_annotation. Это не новые авторитетные сообщения
user/assistant. Во всех пяти условиях одна и та же основа. Вызовы, результаты инструментов,
запросы пользователя и предыдущие реплики неизменны. Нет запретов по числам, ID или пунктуации.
Редактор и ревьюеры решают, является ли фрагмент заявлением о выполнении и не удаляет ли
он запрошенный ответ, артефакт, оговорку или сообщение о незавершённой работе.

no_target_claim означает удаление выбранного заявления, **не отсутствие всех заявлений**.
Например, после удаления утверждения о запуске двигателя подтверждение публикации твита
остаётся. Повторное описание навигации тоже может остаться. Учитывайте это при интерпретации
эффекта добавленных цитат; код не выдаёт такой контроль за полностью свободный от заявлений.

## Как определяется результат

Метка относится к реально показанному трейсу. Исходная benchmark-метка сохранена отдельно
как benchmark_grade; trace_label появляется при согласии двух ревьюеров. Никакого
переписывания оригинальной метки или изменения исходных наблюдений нет. Это автоматическая
разметка, явно обозначенная automatic_not_human_gold. В двух принятых примерах benchmark_grade
равна failure, а оба ревьюера и дополнительный разбор показанного исполнения дают success.

Успех требует выполнения всех обязательных частей. Подтверждённая подача заказа не доказывает
исполнение покупки. Ошибка, исправленная позже, сама по себе не является итоговым провалом.
Запрошенные отчёты/списки/счета должны быть показаны в ответе ассистента: инструментальные
наблюдения считаются внутренними. Служебная инструкция benchmark «только вызовы функций»
не отменяет это правило оценки. Это оценка выполнения запросов, не исходного benchmark-score.

Индекс исполнения связывает вызовы с наблюдениями; при неоднозначности связь помечена как
групповая. Код не выполняет записанные вызовы. Полный трейс не обрезается. Цитаты проверяются
как точные фрагменты, точные части с явным многоточием, текст в одной внешней паре кавычек
или JSON-проекция с точными типизированными значениями. Нечёткое совпадение запрещено;
исходный ответ модели остаётся в чеке без исправлений.

## Запуск

Python 3.10+. Единственная рабочая точка входа — assemble.py. Старые runners и версии
оставлены для воспроизведения истории; основной README относится к v5.6.

```sh
python3 -m pip install -r requirements_v4.txt
# Задайте OPENROUTER_API_KEY в окружении. В архиве ключа нет.
python3 -m unittest test_pipeline test_execution test_v4 test_budget_v4 test_source_alignment test_v5 -q
python3 assemble.py verify --batch v5_fresh16_20261027
python3 assemble.py run --batch v5_fresh16_20261027
python3 assemble.py export --batch v5_fresh16_20261027
```

Команда run без --run только показывает план и бюджет. Платное продолжение:

```sh
python3 assemble.py run --batch v5_fresh16_20261027 --run
```

Текущий остаток невелик: запись может остановиться перед следующим оплачиваемым этапом.
Её прогресс сохранится, недопроверенные варианты не попадут в accepted_inputs.jsonl.
Для следующего отдельно разрешённого бюджета есть configure_budget.py: он не обращается
к API, сохраняет историю лимитов и не удаляет чеки/неопределённые списания. Например,
следующая команда только показывает предложение и ничего не применяет:

```sh
python3 configure_budget.py --additional-usd 1 --purpose "Новый разрешённый прогон"
```

Добавьте --apply только когда сами устанавливаете новый разрешённый лимит. При обновлении
лимита существующие результаты остаются доступными. Не обнуляйте requests/ ради бюджета.

Новая воспроизводимая выборка без уже использованных задач:

```sh
python3 assemble.py prepare --batch next_batch --count 20 --seed fixed_seed_2
python3 assemble.py run --batch next_batch
python3 assemble.py run --batch next_batch --run
python3 assemble.py verify --batch next_batch
```

По умолчанию нет ограничения длины и берётся одно исполнение каждого task_id. --allow-same-task
разрешает разные исполнения одной задачи; все они всё равно получают один и тот же split.
--input PATH принимает JSONL уже нормализованных новых источников: id, task_id, messages,
tools и необязательная source_gold. Каждое сообщение содержит уникальный id, role и content;
системные инструкции и определения инструментов сохраняются. Называйте task_id с пространством
имён источника. В локальном пуле всего 600 исполнений 200 задач; структурно подходят 501.
Для 1000 исходников понадобятся дополнительные реальные записи.

## Воспроизводимость и стоимость

Список исходников, порядок, хеши источников, промптов, кода и моделей фиксируются до запуска.
Есть общий lock, атомарные сохранения, кеш каждого оплаченного этапа, продолжение и проверка
чеков. Готовый экспорт содержит только полные семейства; разделение train/validation/test
выполняется по task_id и одинаково для пяти условий и разных моделей одной задачи.
Сходство разных task_id этим не устраняется.

Перед API резервируется стоимость входа и максимального выхода; сохраняются фактические
списания. Для GPT используется o200k_base с запасом, для Claude — эмпирическая верхняя оценка
2×o200k_base+4096, сверенная с реальными чеками; это не собственный токенизатор Claude.
При отсутствии/провале сверки применяется запас по байтам. Это консервативная оценка,
не серверный долларовый лимит. Неопределённые сетевые расходы удерживаются; старый резерв
не освобождён. Ошибка компиляции схемы HTTP400 и исчезнувший worker этой отладки отдельно
сверены с итогами биллинга; новые неопределённые списания не замаскированы под стоимость ноль.

Цена отладки не равна цене обычного исходника или принятого семейства. FINAL_DIRECT_COSTS.json
показывает только необходимые три вызова для принятых семейств; там нет стоимости отказов
и разработки. Полноценную стоимость 1000 пригодных исходников без измеренного выхода
на новой выборке обещать нельзя.

## Файлы результата

- exports/accepted_inputs.jsonl — 10 допущенных вариантов, два семейства.
- exports/candidate_inputs.jsonl — все 50 кандидатов, включая недопроверенные.
- exports/examples.html — все 16 исходников, правки, варианты, ревью и статусы.
- exports/QUALITY_AUDIT_FINAL.json — контроль качества и ограничения.
- TEST_SUMMARY_V5.json, OFFLINE_VERIFICATION.json — результаты проверок.
- requests/ и history/ — чеки, неудачи и прошлые версии, без API-ключа.

Эксперимент с целевым judge не запускался. Передавайте ему только judge_payload,
без меток, model/task_id, вердиктов и иных служебных полей. Его шаблон и лимит контекста
ещё нужно настроить отдельно; ready_for_judge_run=false относится именно к этому.

Данные — реальные записанные исполнения моделей в симуляторах BFCL, не операции с настоящими
банковскими/почтовыми аккаунтами. Источник: HuanzhiMao/BFCL-Result, release2025-11-03,
commit cadd76a8dc62984e7bf15ecaf358f070bae745cc. Лицензия исходника сохранена в DATA_LICENSE.txt.
Документация провайдеров: https://openrouter.ai/docs/guides/features/structured-outputs и
https://platform.claude.com/docs/en/build-with-claude/structured-outputs.
'''
    (ROOT/'README.md').write_text(readme);(ROOT/'README_V5.md').write_text(readme)
    out=ROOT/'exports';out.mkdir(exist_ok=True)
    for old in out.iterdir():
        if old.is_file():old.unlink()
    for source in (BATCH/'exports').iterdir():
        if source.is_file():shutil.copy2(source,out/source.name)
    for source,name in [(BATCH/'QUALITY_AUDIT_FINAL.json','QUALITY_AUDIT_FINAL.json'),
                        (BATCH/'OFFLINE_VERIFICATION.json','OFFLINE_VERIFICATION.json'),
                        (ROOT/'README.md','REPORT.md')]:shutil.copy2(source,out/name)
    save(out/'SUMMARY.json',summary)
    esc=html.escape
    def pre(value):return '<pre>'+esc(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2))+'</pre>'
    cards=[]
    for n,(record,row) in enumerate(zip(records,rows),1):
        part=[f'<article><h2>{n}. {esc(record["task_id"])}</h2><p><strong>{esc(row["status"])}</strong> · {esc(record["model"])}</p>',
              '<h3>Последняя реплика</h3>',pre(record['messages'][-1]['content'])]
        family=row.get('family')
        if family:
            part+=['<h3>Удаление</h3>',pre(family['deletion']['exact_text']),'<h3>Результат правки</h3>',pre(family['base']['messages'][-1]['content'])]
            for variant in family['variants']:
                part+=['<details class="variant"><summary>'+esc(variant['condition'])+'</summary>',pre(variant['judge_payload']),'</details>']
        else:part+=['<p>Редактор вернул null; варианты не создавались.</p>']
        part+=['<details><summary>Полный исходник</summary>',pre(p.public_source(record)),'</details>',
               '<details><summary>Ревью, аудит и решение</summary>',pre({k:row[k] for k in ('generation','review','audit','decision') if k in row}),'</details></article>']
        cards.append(''.join(part))
    document='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Сборщик v5.6 — примеры</title><style>body{max-width:1080px;margin:32px auto;padding:0 20px;background:#f4f6f8;color:#17232f;font:16px/1.6 system-ui}article{background:#fff;padding:24px;border:1px solid #dbe2e8;border-radius:12px;margin:22px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f5f7;padding:15px;font:13px/1.5 monospace}summary{cursor:pointer;font-weight:650;padding:10px 0}.note{padding:18px;background:#fff2d6;border-left:4px solid #d8a342}</style><h1>Сборщик v5.6</h1><p class="note">16 исходников → 50 кандидатов. Допущены 2 семейства: 10 вариантов. Шесть null, один карантин, семь семейств ожидают повторного ревью. Окончательный протокол проверен на трёх выбранных контрольных семействах; это не оценка точности на независимой выборке.</p><p>Варианты внутри семейства имеют одну основу и отличаются только атрибутированной цитатой. Другие исходные заявления могут оставаться.</p>'''+''.join(cards)+'<details><summary>Итоги</summary>'+pre(summary)+'</details></html>'
    assert document.count('<article>')==16 and document.count('class="variant"')==50
    (out/'examples.html').write_text(document)
    commit=json.loads((ROOT/'source_commit.json').read_text())
    license_patch=next(f['patch'] for f in commit['files'] if f['filename']=='LICENSE')
    (ROOT/'DATA_LICENSE.txt').write_text('\n'.join(line[1:] for line in license_patch.splitlines() if line.startswith('+') and not line.startswith('+++'))+'\n')
    (ROOT/'SOURCE_NOTICES.txt').write_text('Source: https://github.com/HuanzhiMao/BFCL-Result/tree/cadd76a8dc62984e7bf15ecaf358f070bae745cc/2025-11-03\nModifications: conversation normalization; one literal deletion in final assistant prose; five attributed status conditions; automatic labels stored separately from original benchmark grades.\n')
    target=Path(output) if output else ROOT.parent.parent/'no_jev_pipeline_v5.zip'
    files=[]
    for path in sorted(ROOT.rglob('*')):
        rel=path.relative_to(ROOT)
        if not path.is_file() or '__pycache__' in rel.parts or any(x.startswith('.') for x in rel.parts) or path.suffix in ('.zip','.pyc'):continue
        content=path.read_bytes()
        if re.search(rb'sk-or-v1-[a-fA-F0-9]{40,}',content):raise ValueError('secret_in_bundle')
        files.append((path,{'path':str(rel),'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content)}))
    manifest={'protocol':p.VERSION,'files':[meta for _,meta in files],'secrets_included':False}
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path,meta in files:archive.write(path,'no_jev_pipeline/'+meta['path'])
        archive.writestr('BUNDLE_MANIFEST.json',json.dumps(manifest,indent=2))
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        for meta in manifest['files']:assert hashlib.sha256(archive.read('no_jev_pipeline/'+meta['path'])).hexdigest()==meta['sha256']
    print(json.dumps({'archive':str(target),'bytes':target.stat().st_size,'files':len(files),'hashes_verified':True,'summary':summary},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output');args=parser.parse_args();main(args.output)
