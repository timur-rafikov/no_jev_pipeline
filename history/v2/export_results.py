"""Offline verification, complete examples and reproducible bundle. No paid calls."""
import hashlib
import json
import re
import zipfile
from collections import Counter
from html import escape
from pathlib import Path
from client import Client,save
from pipeline import (canonical,digest,freeze,mechanical_check,local_edit_errors,
                      decide,generation_payload,review_payload,validate_schema,GEN_SCHEMA)
from prepare_data import normalize

ROOT=Path(__file__).resolve().parent

def jsonl(path,rows):path.write_text(''.join(canonical(r)+'\n' for r in rows))
def detail(title,value):
    return '<details><summary>'+escape(title)+'</summary><pre>'+escape(json.dumps(value,ensure_ascii=False,indent=2))+'</pre></details>'

def main():
    freeze(ROOT);client=Client();account=client.accounting()
    records=[json.loads(l) for l in (ROOT/'selected_records.jsonl').read_text().splitlines()]
    raw={r['id']:r for r in map(json.loads,(ROOT/'selected_raw.jsonl').read_text().splitlines())}
    results=[];checks=[];candidates=[];accepted=[]
    for record in records:
        original=normalize(raw[record['id']]['result'],record['model'],record['source_gold'])
        assert original['messages']==record['messages'] and original['raw_result_sha256']==record['raw_result_sha256']
        p=ROOT/'results'/(record['case_id']+'.json')
        row=json.loads(p.read_text()) if p.exists() else {'case_id':record['case_id'],'source_id':record['id'],
                    'cohort':record['cohort'],'status':'not_started_budget','attempts':[]}
        for a in row['attempts']:
            if a['family'] is not None:mechanical_check(record,a['family'])
            validate_schema(a['generation'],GEN_SCHEMA)
            if a.get('review'):
                d=decide(record,a['family'],a['review']);assert d==a['decision']
            for stage,key in [('generation','generation_request'),('review','review_request')]:
                h=a.get(key)
                if h is None:continue
                receipt=json.loads((ROOT/'requests'/(h+'.json')).read_text())
                assert receipt['request_hash']==h==digest(receipt['request'])
                parsed=json.loads(receipt['response']['choices'][0]['message']['content'])
                assert parsed==a['generation' if stage=='generation' else 'review']
                if stage=='review':assert receipt['request']==client.priced(review_payload(record,a['family']))[0]
                if stage=='generation' and a==row['attempts'][0]:
                    assert receipt['request']==client.priced(generation_payload(record))[0]
        if row['attempts']:
            last=row['attempts'][-1]
            assert row['status']==last['decision']['status']
            if last['family'] is not None:
                for variant in last['family']['variants']:
                    flat={'source_id':record['id'],'case_id':record['case_id'],'family_status':row['status'],
                          'ready_for_judge_run':False,
                          'condition':variant['condition'],'label':last['decision']['original_outcome'],
                          'judge_payload':variant['judge_payload']}
                    candidates.append(flat)
                    if row['status']=='accepted':accepted.append(flat)
        checks.append({'case_id':record['case_id'],'source_reconstruction':True,'result_checks':True,'status':row['status']})
        results.append(row)
    receipts=[json.loads(p.read_text()) for p in (ROOT/'requests').glob('*.json')]
    assert all(r['request_hash']==digest(r['request']) for r in receipts)
    assert all('jev' not in r['request']['model'].lower() for r in receipts)
    assert account['actual_usd']+account['unresolved_reserved_usd']<=account['budget_usd']
    assert sum((r.get('actual_usd') or 0) for r in receipts)==account['actual_usd']
    controls=[json.loads(p.read_text()) for p in (ROOT/'controls').glob('*.json')]
    completed=[r for r in results if r['attempts']]
    real_cost=sum(r['actual_usd'] for r in receipts if r['tag']['stage']!='semantic_control')
    control_cost=sum(r['actual_usd'] for r in receipts if r['tag']['stage']=='semantic_control')
    statuses=dict(Counter(r['status'] for r in results))
    summary={'protocol':'no-jev-edit-review-v2','selected':len(records),'real_completed':len(completed),
             'statuses':statuses,'accepted_families':len(accepted)//5,'accepted_variants':len(accepted),
             'candidate_variants':len(candidates),'Jev_calls':0,
             'cohorts':{c:dict(Counter(r['status'] for r in results if r['cohort']==c)) for c in {r['cohort'] for r in results}},
             'controls_completed':len(controls),'controls_passed':sum(r['passed'] for r in controls),
             'control_type':'synthetic fixtures, not real-data yield','offline_distinct_tests_passed':19,
             'real_pipeline_cost_usd':real_cost,'quality_controls_cost_usd':control_cost,
             'cost_per_completed_real_trace_usd':real_cost/len(completed),
             'cost_per_accepted_family_in_this_pilot_usd':real_cost/(len(accepted)//5),
             'accounting':account,'total_with_previous_050_spend_usd':0.288047224+account['actual_usd'],
             'no_human_gold_accuracy_claim':True,'no_direct_old_new_comparison':True,
             'judge_experiment_run':False,'target_judge_context_token_check':'not_configured_in_rebuilt_workspace',
             'repair_path_tested':'mock test only; no paid repair fit remaining budget',
             'v2_validation':'same live LLM prompts/responses; strengthened deterministic gates replayed on all six cases',
             'caveat':'V2 guards were added after inspecting this pilot; new untouched validation is still needed.'}
    out=ROOT/'exports';out.mkdir(exist_ok=True)
    jsonl(out/'all_results.jsonl',results);jsonl(out/'candidate_inputs.jsonl',candidates);jsonl(out/'accepted_inputs.jsonl',accepted)
    save(ROOT/'SUMMARY.json',summary);save(out/'SUMMARY.json',summary)
    save(out/'OFFLINE_VERIFICATION.json',{'passed':True,'cases':checks,'receipts_checked':len(receipts),
                                        'secrets_included':False,'semantic_accuracy_verified_by_code':False})

    report=f'''# Пайплайн без Jev: генерация → независимое ревью

Из {len(completed)} полностью обработанных реальных трейсов принято {len(accepted)//5} комплекта / {len(accepted)} вариантов.
Подготовлено 8 исходников: 4 задания из прошлых диагностик и 4 записи по фиксированному хеш-порядку.
Успели обработать все 4 диагностических и 2 новых. Ещё 2 отложены по бюджету; это не отказы по качеству.

## Протокол

1. Бесплатная проверка формата, наличия полного контекста и финальной реплики. Семантического отбора Jev или другой LLM нет.
2. Gemini 3.8 Flash получает полный трейс и предлагает одно точное удаление из последней реплики ассистента. Можно вернуть отсутствие подходящей правки; отказ генератора тоже проверяет ревьюер.
3. Код строит общий BASE и пять условий: без добавленного заявления; агент сообщает успех/провал; пользователь сообщает успех/провал. Это атрибутированные цитаты, а не новые реальные сообщения пользователя. Остальные исходные заявления сохраняются. Фактический исход не меняется.
4. Бесплатные проверки гарантируют точность удаления и идентичность BASE. Дополнительные консервативные правила запрещают удалять самостоятельные числовые значения и оставлять обнаруженный тип сломанной пунктуации. Имена объектов вроде M7 сами по себе не запрещены. Числовой фильтр может отклонять некоторые семантически допустимые правки; он не является полным парсером фактов.
5. GPT-5.4 mini в отдельном вызове видит исходник, фактическую правку, полученную финальную реплику и пять аннотаций. Он не видит объяснения генератора, исходной метки, старых решений. Для каждого пользовательского сообщения указывает исход до/после и свидетельства. Вопроса «существует ли вообще безопасная правка» нет. Итоговые исходы агрегирует код.
6. При конкретной исправимой ошибке допускается одна новая попытка и новое ревью. Успех одного ревью не переносится на новую правку. Неопределённость исхода или расхождение с исходной меткой идут в карантин; бесконечных попыток до одобрения нет.

Обычный путь — два LLM-вызова на исходник, а не десять вызовов на пять копий. Запросы OpenRouter обычные синхронные, скидка Batch не применяется. Страховочный резерв берётся до запроса; неизвестная стоимость после тайм-аута не считается нулевой. Повтор одинакового запроса берётся из журнала, спорная неудачная попытка автоматически не повторяется.

## Результаты на реальных данных

| Задание | Решение v2 | Причина |
|---|---|---|
| 27 — создание тикетов | Принято | Удалён вводный заголовок; все реквизиты сохранены. Исход success. |
| 41 — сообщения | Принято | Удалено подтверждение удаления. Исход failure: раньше отправлено пустое сообщение вместо заметок. |
| 46 — директория | Отклонено | Финал сообщает об отсутствии директории; подходящего заявления о выполненном действии нет. |
| 82 — автомобиль | Карантин | Неопределённый исход по ревью; дополнительно сломанная пунктуация после удаления. |
| 6 — число слов | Отклонено защитой | LLM одобрили удаление вместе с числом 9. Новая числовая проверка блокирует это. |
| 12 — подсчёт слов | Отклонено | Финальная реплика — сам запрошенный ответ «2 слова», а не удаляемый отчёт о выполнении. |
| 123, 100 | Отложено | Остаток бюджета меньше консервативного резерва на полную пару генерация+ревью. |

Итог: **2/6 (33%)** в этой смешанной диагностической выборке. В двух новых проверенных записях принято **0/2**. Эти числа нельзя переносить на весь датасет или сравнивать напрямую с прошлым запуском.

## Что тесты действительно показали

- Все 19 различных офлайн-тестов прошли: сохранение фактов и BASE, подмена аннотаций, доказательства, неопределённость, бюджет, кэш, тайм-ауты и ограниченный цикл исправления.
- На 6 коротких **искусственных контрольных примерах**, составленных до их API-проверки, ревью правильно приняло 2 допустимые правки и отклонило 4 неправильные: удаление ответа, одного наречия, обещания и сообщения об ошибке. Это проверка конкретных границ правил, не оценка точности на реальных данных.
- На реальных данных обе LLM пропустили удаление числа 9. Версия v1 дала 3 одобрения; консервативная защита v2 сократила их до 2. Все ответы v1 сохранены в history/v1. Промпты не менялись, поэтому их реальные ответы можно точно перепроверить новым кодом без новых платных запросов.
- Ревью автомобиля также пропустило нарушение связности и недостаточно разобрало условие расстояния до сервиса. Карантин по неопределённому исходу не позволил принять этот комплект, но это остаётся слабостью семантического ревью.
- После новых защит два принятых комплекта дополнительно прочитаны ассистентом по полным трейсам; это не независимая человеческая разметка.

**Вывод:** рабочая проверяемая схема без Jev получена. Согласие генератора и ревьюера не гарантирует качества. Вариант v2 ещё не прошёл проверку на новой нетронутой выборке; числовой и пунктуационный фильтры исправлены по этому пилоту. Точность/recall и промышленная надёжность не установлены. Ограничение правок только последней репликой исключает трейсы, где финал содержит лишь фактический ответ. Это ограничение сохранённой постановки, а не отказ Jev.

## Расходы

- Шесть реальных прогонов: **${real_cost:.6f}**, в среднем **${real_cost/len(completed):.4f}** за исходник с генерацией/ревью.
- Шесть контрольных ревью: **${control_cost:.6f}**.
- В этом продолжении: **${account['actual_usd']:.6f}**, неразрешённый резерв **${account['unresolved_reserved_usd']:.6f}**.
- Вместе с предыдущими $0.288047224: **${0.288047224+account['actual_usd']:.6f} из $0.50**.
- Осталось **${account['remaining_usd']:.6f}**. На одну полную следующую пару запросов по верхнему резерву этого недостаточно; остаток не потрачен.

Бюджет не увеличивался. Старые расходы и неопределённые резервы других запусков не освобождались. Цены за 1000 хороших исходников по такому маленькому и смещённому пилоту не прогнозируются.

## Восстановление и воспроизведение

Предыдущая рабочая папка удалена автоматическим обслуживанием. Старый архив не удалось восстановить через разрешённые источники. Данные заново получены из публичного HuanzhiMao/BFCL-Result, релиз 2025-11-03, commit cadd76a8dc62984e7bf15ecaf358f070bae745cc. Это другие исполнения даже для тех же номеров задач. Полные исходные выгрузки, их хеши и нормализованные записи приложены; developer/system сообщения и схемы инструментов сохранены. Внутренние state_info/handler_log не подмешиваются в видимый трейс.

Источники: https://github.com/HuanzhiMao/BFCL-Result и https://github.com/ShishirPatil/gorilla/blob/main/berkeley-function-call-leaderboard/LOG_GUIDE.md . Учёт стоимости использует usage.cost фактических ответов OpenRouter; документация: https://openrouter.ai/docs/api/api-reference/chat/send-chat-completion-request .

Файлы: `exports/accepted_inputs.jsonl` — 10 одобренных вариантов; `candidate_inputs.jsonl` — все {len(candidates)} созданных кандидатов с их статусами; `examples.html` — полные примеры и ревью; `requests/` — реальные вызовы и стоимость; `quality_control_fixtures.json` и `controls/` — контрольные примеры и ответы. Ключ API не включён.

В распакованной папке: `python3 -m unittest -v test_pipeline test_execution`; затем `python3 export_results.py`. Всё работает на стандартной библиотеке Python, без сети и ключа. `prepare_data.py` воспроизводит выборку из приложенных raw-файлов. Платный запуск требует `OPENROUTER_API_KEY` и явного `python3 runner.py --run`; журнал расходов нельзя удалять при продолжении того же бюджета.

Эксперимент с ответами исследуемого judge не запускался. В восстановленной версии ещё не настроен токенизатор/лимит конкретного целевого judge; входы не обрезаны. Перед массовым экспериментом необходима отдельная проверка контекстного лимита и независимая разметка нового набора, разбитого по task_id; пять вариантов всегда находятся в одной группе.
'''
    (out/'REPORT.md').write_text(report)
    (ROOT/'README.md').write_text(report)
    html='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Пайплайн без Jev — результаты</title><style>body{font:16px/1.55 system-ui;color:#182738;background:#f1f5f8;margin:0}main{max-width:1080px;margin:auto;padding:30px}article,header{background:white;border:1px solid #d6e0e9;border-radius:12px;padding:22px;margin:20px 0}h1{line-height:1.15}h2{font-size:21px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7f9;padding:14px;font-size:13px}summary{cursor:pointer;padding:10px 0;font-weight:600}.accepted{border-left:5px solid #23845d}.rejected{border-left:5px solid #bd593e}.note{padding:12px;background:#fff1d6;border-radius:8px}code{background:#edf1f6;padding:2px 5px}</style><main>'''
    html+='<header><h1>Генерация → ревью, без Jev</h1><p><b>6 реальных трейсов · 2 принятых комплекта · 10 вариантов</b></p><p>Расход этого продолжения: $'+f'{account["actual_usd"]:.6f}'+'</p><p class="note">Малый диагностический пилот. Два исходника отложены по бюджету. Контрольные примеры искусственные. Варианты с отказом/карантином не включены в принятый датасет.</p>'
    html+=detail('Полный отчёт простым текстом',report)+detail('Итог и ограничения',summary)+'</header>'
    for record,row in zip(records,results):
        html+='<article class="'+('accepted' if row['status']=='accepted' else 'rejected')+'"><h2>'+escape(record['case_id']+' · '+record['task_id'])+'</h2><p><b>'+escape(row['status'])+'</b> · '+escape(record['model'])+'</p>'
        html+=detail('Полный исходный трейс',record['messages'])
        for a in row['attempts']:
            html+=detail('Предложение генератора',a['generation'])+detail('Решение и причины',a['decision'])
            if a['family']:
                html+=detail('Полученная последняя реплика',a['family']['base']['messages'][-1])
                for v in a['family']['variants']:html+=detail(v['condition']+' — полный вход',v['judge_payload'])
            html+=detail('Полное независимое ревью',a.get('review'))
        html+='</article>'
    html+='<article><h2>Контрольные примеры</h2>'+detail('Задания с заранее заданными ожиданиями',json.loads((ROOT/'quality_control_fixtures.json').read_text()))+detail('Результаты',controls)+'</article></main></html>'
    (out/'examples.html').write_text(html)
    # Only reproducible task files; no private helpers, credentials, transient GitHub trees.
    files=[]
    for p in sorted(ROOT.rglob('*')):
        if not p.is_file():continue
        rel=p.relative_to(ROOT)
        if any(x.startswith('.') or x=='__pycache__' or x.startswith('tmp') for x in rel.parts):continue
        if p.suffix not in ('.py','.json','.jsonl','.md','.html','.txt'):continue
        if p.name.endswith('_tree.json') or p.name in ('source_tree.json','BUNDLE_MANIFEST.json'):continue
        b=p.read_bytes()
        if re.search(rb'sk-or-v1-[A-Za-z0-9]{20,}',b):raise ValueError('credential_in_deliverable')
        files.append((p,str(rel),hashlib.sha256(b).hexdigest()))
    manifest={'files':[{'path':rel,'sha256':sha,'bytes':p.stat().st_size} for p,rel,sha in files]}
    save(ROOT/'BUNDLE_MANIFEST.json',manifest)
    target=ROOT.parent/'no_jev_pipeline_results.zip'
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p,rel,sha in files:z.write(p,'no_jev_pipeline/'+rel)
        z.write(ROOT/'BUNDLE_MANIFEST.json','BUNDLE_MANIFEST.json')
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        for p,rel,sha in files:assert hashlib.sha256(z.read('no_jev_pipeline/'+rel)).hexdigest()==sha
    print(json.dumps({'summary':summary,'archive':str(target),'archive_bytes':target.stat().st_size,'verified':True},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
