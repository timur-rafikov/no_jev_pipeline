"""Verify and export the completed ten-task pilot. No API calls."""
import copy
import hashlib
import json
import re
import zipfile
from collections import Counter
from html import escape
from pathlib import Path
from client import Client,save
from pipeline import (VERSION,canonical,digest,freeze,generation_payload,review_payload,
                      materialize,mechanical_check,decide)
from prepare_data import normalize

ROOT=Path(__file__).resolve().parent
BATCH=ROOT/'batches/v3_new10_20261026'

def jsonl(path,rows):path.write_text(''.join(canonical(r)+'\n' for r in rows))
def detail(title,value):
    return '<details><summary>'+escape(title)+'</summary><pre>'+escape(json.dumps(value,ensure_ascii=False,indent=2))+'</pre></details>'

def render_report(s,rows):
    table=[]
    labels={'accepted':'Принято','quarantined':'Карантин','operational_error':'Ошибка обработки'}
    notes={
        '01':'Удалено подтверждение записи в файл. Исход failure сохраняется.',
        '02':'Правка допустима; видимый трейс и метка benchmark расходятся.',
        '03':'Правка допустима; есть оговорка к трактовке успеха покупки.',
        '04':'Удалён заголовок, все запрошенные реквизиты сохранены.',
        '05':'Удалено подтверждение действий; успех виден в инструментах.',
        '06':'Финал содержит только синтаксис вызовов, без подходящего заявления.',
        '07':'Нет подходящего заявления; пустая ссылка на удаление вызвала ошибку валидатора.',
        '08':'Финал — []; нет заявления. Та же ошибка валидатора.',
        '09':'Финал — обещание будущих действий. Та же ошибка валидатора.',
        '10':'Правка допустима; видимый трейс и метка benchmark расходятся.'}
    for r in rows:
        table.append('| '+r['task_id'].replace('multi_turn_base_','')+' | '+labels.get(r['status'],r['status'])+' | '+str(5 if r['status']=='accepted' else 0)+' | '+notes[r['case_id'][-2:]]+' |')
    report=f'''# Новый пайплайн: 10 новых трейсов и проверка качества

Пайплайн принял **{s['accepted_families']} исходника и {s['accepted_variants']} вариантов**.
Всего создано {s['candidate_families']} комплектов / {s['candidate_variants']} кандидатов;
остальные четыре исходника не содержат подходящего заявления в последней реплике.
Генерация и отдельное ревью выполнены для всех десяти записей. У трёх нулевых кандидатов
содержательный отказ модели не превратился в штатное решение из-за ошибки валидации.

## Результаты неизменённого семантического протокола v3

| Задание BFCL | Решение пайплайна | Принятых вариантов | Причина |
|---|---|---:|---|
{chr(10).join(table)}

По формальным статусам: 4 принято, 3 карантина, 3 ошибки обработки. Четыре принятых
комплекта имеют метки failure, success, success, success соответственно. Сами неуспешные
исполнения полезны для эксперимента и не отбрасываются только из-за провала задачи.

## Как проверено качество

Ассистент сначала прочитал исходники и реальные удаления, записал оценки, затем открыл
решения ревьюера и benchmark-метки. Сохранены оба этапа: `audit/*before_verdicts.json`
и `audit/QUALITY_AUDIT.json`. Это дополнительная модельная проверка, не человеческий gold.

- Во всех **6 созданных комплектах** я не обнаружил удаления запрошенного ответа,
  существенной оговорки или свидетельства ошибки. В четырёх случаях без кандидата
  не обнаружено очевидно пропущенного допустимого удаления.
- Из **4 принятых** комплектов **3 (15 вариантов)** не вызвали замечаний при этой проверке.
  У **одного (5 вариантов, задание128)** сохранён флаг неоднозначной трактовки исхода:
  пользователь просит приобретение акций и статус после исполнения, а трейс подтверждает
  размещение заявки со статусом Open и её последующую отмену. Ревьюер и benchmark считают
  это успехом; перед чтением их решений аудит отметил неоднозначность. Правка сама по себе
  допустима. Эти пять вариантов не удалены и не перемечены автоматически.
- В **задании93** выявлена конкретная ошибка ревьюера: он повторил утверждение агента
  «выше40psi», хотя инструмент показал35/35/32/32psi. Этот трейс не попал в принятые данные,
  но ошибка показывает, что модельная проверка исхода ещё может поверить утверждению агента.
- В задании127 ревьюер также не учёл, что символы NVDA/BDX уже названы в реплике,
  когда оценивал вывод watchlist. Это не повлияло на отсутствие допустимого удаления.

Выгрузка `accepted_inputs.jsonl` содержит все20 принятых вариантов с флагами аудита.
`accepted_without_audit_caution.jsonl` содержит15 вариантов без отмеченной неоднозначности.
`accepted_with_audit_caution.jsonl` содержит оставшиеся5. Это прозрачные представления
результатов аудита; исходные решения пайплайна сохранены без ручной подмены.

## Почему два хороших изменения остались в карантине

Для заданий130 и126 записанные результаты инструментов создают заявку12447 и успешно
возвращают её детали/отмену. Однако опубликованный scoring replay создаёт12446 и затем
сообщает, что запрошенной12447 не существует. Поэтому одинаковые вызовы оцениваются как
ошибка в scoring replay, хотя видимый исходный трейс показывает успех.

Это наблюдаемое расхождение между inference-трейсом и проверочным replay; его точная
причина пока не установлена. Нельзя объявлять ревьюера ошибочным только за несогласие
с такой меткой, либо автоматически принимать эти записи без решения вопроса о ground truth.
Оба комплекта сохранены в карантине; доказательства — `audit/source_label_conflicts.json`.

## Технический дефект нулевого кандидата

В трёх ответах ревьюер вернул `deletion=null`, `edit_verdict=unsafe` и пустой
`edit_evidence_ids`. Код v3 требует непустой список даже при отсутствии правки и выдаёт
`invalid_edit_evidence`. Исходные ответы API сохранены; ошибка не выдана за отказ по качеству.
Во всех трёх случаях аудит также не нашёл подходящего заявления. Этот дефект нужно
исправить в следующей версии обработки null; во время пилота критерии приёма не менялись.

## Расходы

- Подтверждённый расход этого запуска: **${s['confirmed_run_cost_usd']:.6f}**.
- Для одного прерванного сетевого запроса без ответа сохранён резерв
  **${s['unresolved_run_reserve_usd']:.6f}**. Он не считается нулевой стоимостью.
- Подтверждённый расход плюс этот резерв: **${s['run_cost_including_reserve_usd']:.6f}**.
- Всего было {s['attempted_api_calls']} попыток API: 10 генераций, 10 завершённых ревью
  и одно прерванное ревью. Повтор прерванного ревью выполнен один раз с тем же промптом;
  первая неизвестная стоимость остаётся зарезервированной. Генерация повторно не оплачивалась.
- Остаток общего разрешённого бюджета после всех резервов:
  **${s['accounting']['remaining_usd']:.6f}**. Общий лимит увеличен по явному согласию
  пользователя с$0.50 до$1.00. Новые расходы укладываются в дополнительный лимит$0.50.

## Выборка и ограничения

Выбраны десять уникальных task_id без пересечений с доступной историей:1 файловый трейс,
3 автомобильных,6 торговых. Порядок задан хешем, размер сообщений ограничен36000байтами,
метка и пригодность к удалению при выборе не использовались. Это та же область выборки,
что в прошлом пилоте; она не представляет весь BFCL. Недоступные ранние архивы проверить
на пересечения невозможно. Выборка и промпты зафиксированы до новых платных запросов.

20вариантов из10исходников — результат этой десятки, не оценка выхода на всём датасете.
Точность/recall на большой независимой разметке не измерены. Новых регулярных выражений
или запретов на числа/пунктуацию не добавлялось. Смысл правки проверяла отдельная LLM.
Во время запуска изменялась только обработка сетевого возобновления и продолжения
после технических ошибок, чтобы все10выбранных задач получили генерацию и ревью.

Постановка: одно выбранное заявление удаляется из последней реплики. Общий BASE
используется в пяти условиях: без добавленного заявления; агент успех/провал;
пользователь успех/провал. Заявления — отдельные атрибутированные цитаты. Другие исходные
утверждения, включая повторные подтверждения, остаются. Это не глобальное удаление всех
заявлений об успехе. Для всех30кандидатов код проверил идентичность BASE и точность правки.

Сам эксперимент с целевым judge ещё не запускался; токенизатор/контекстный лимит judge
не настроен. Поэтому у входов сохранён `ready_for_judge_run=false`.

## Происхождение данных и восстановление после блокировки

Использованы опубликованные исполнения BFCL-Result, commit
`cadd76a8dc62984e7bf15ecaf358f070bae745cc`, релиз2025-11-03. Автоматическая проверка
остановила передачу, приняв поля тестовых карт за чувствительные реквизиты. До продолжения
точные значения были сопоставлены с открытыми `initial_config` соответствующих задач,
а код TradingBot проверен: он читает состояние сценария и меняет его в памяти.
Подключения к реальным пользовательским финансовым счетам не было. Проверяемые источники
и хеши сохранены в `provenance/PUBLIC_SIMULATOR_PROVENANCE.json`.

Первичные источники:
- https://github.com/HuanzhiMao/BFCL-Result
- https://github.com/ShishirPatil/gorilla/blob/6ea57973c7a6097fd7c5915698c54c17c5b1b6c8/berkeley-function-call-leaderboard/bfcl_eval/data/BFCL_v4_multi_turn_base.json
- https://github.com/ShishirPatil/gorilla/blob/6ea57973c7a6097fd7c5915698c54c17c5b1b6c8/berkeley-function-call-leaderboard/bfcl_eval/eval_checker/multi_turn_eval/func_source_code/trading_bot.py
- https://gorilla.cs.berkeley.edu/blogs/13_bfcl_v3_multi_turn.html

## Файлы

`exports/examples.html` — все10исходников, все30кандидатов,20принятых вариантов,
ревью и выводы аудита. `requests/` — запросы, ответы и стоимость без API-ключа.
`batches/v3_new10_20261026/` — зафиксированная выборка, исходные решения и аудит.
Прежний пилот сохранён в `history/v3_prior_new10/`.

В корне проекта можно выполнить `python3 export_results.py` для бесплатной проверки
и пересборки артефактов. `python3 -m unittest -v test_pipeline test_execution`
проверяет код без сети. `python3 run_new10.py` показывает состояние без платных вызовов.
Не удаляйте финансовый журнал при продолжении работы.
'''
    report=re.sub(r'(?<=\d)(?=[А-Яа-яЁё])|(?<=[А-Яа-яЁё])(?=\d|\$)', ' ',report)
    return re.sub(r'(?<=\d)(?=psi\b)', ' ',report)

def main():
    manifest=json.loads((BATCH/'selection_manifest.json').read_text())
    assert freeze(ROOT)==manifest['protocol']
    records=list(map(json.loads,(BATCH/'selected_records.jsonl').read_text().splitlines()))
    raw={r['id']:r for r in map(json.loads,(BATCH/'selected_raw.jsonl').read_text().splitlines())}
    audit=json.loads((BATCH/'audit/QUALITY_AUDIT.json').read_text())
    audits={r['case_id']:r for r in audit['cases']}
    client=Client();account=client.accounting()
    receipts={p.stem:json.loads(p.read_text()) for p in (ROOT/'requests').glob('*.json')}
    scoped={h:r for h,r in receipts.items() if r['tag'].get('case') in audits}
    rows=[];candidates=[];accepted=[];clear=[];caution=[];checks=[]
    for record,entry in zip(records,manifest['selected']):
        assert digest(record)==entry['source_hash']
        reconstructed=normalize(raw[record['id']]['result'],record['model'],record['source_gold'])
        assert reconstructed['messages']==record['messages']
        assert reconstructed['raw_result_sha256']==record['raw_result_sha256']
        result=json.loads((BATCH/'results'/(record['case_id']+'.json')).read_text())
        rr=[(h,r) for h,r in scoped.items() if r['tag']['case']==record['case_id'] and r.get('parsed') is not None]
        # The frozen pilot made one semantic attempt per task; no edit repairs occurred.
        gens=[(h,r) for h,r in rr if r['tag']['stage']=='generation']
        reviews=[(h,r) for h,r in rr if r['tag']['stage']=='review']
        assert len(gens)==len(reviews)==1
        gh,g=gens[0];rh,v=reviews[0]
        gen=g['parsed'];review=v['parsed']
        family=None if gen['deletion'] is None else materialize(record,gen['deletion'])
        if family:mechanical_check(record,family)
        assert g['request']==client.priced(generation_payload(record))[0]
        assert v['request']==client.priced(review_payload(record,family))[0]
        validation_error=None;decision=None
        try:decision=decide(record,family,review)
        except ValueError as e:validation_error=str(e)
        if validation_error:
            assert result['status']=='operational_error' and validation_error=='invalid_edit_evidence'
            assert family is None and review['edit_evidence_ids']==[]
        else:
            assert decision==result['attempts'][-1]['decision']
            assert result['status']==decision['status']
            assert result['attempts'][-1]['generation_request']==gh
            assert result['attempts'][-1]['review_request']==rh
        row={**result,'task_id':record['task_id'],'source_gold':record['source_gold'],
             'generation':gen,'family':family,'review':review,'decision':decision,
             'validation_error':validation_error,'generation_receipt':gh,'review_receipt':rh,
             'quality_audit':audits[record['case_id']]}
        rows.append(row)
        if family:
            for variant in family['variants']:
                flat={'case_id':record['case_id'],'task_id':record['task_id'],'source_id':record['id'],
                      'protocol':VERSION,'family_status':result['status'],'ready_for_judge_run':False,
                      'label':None if decision is None else decision['original_outcome'],
                      'quality_flag':audits[record['case_id']]['quality_flag'],
                      'condition':variant['condition'],'judge_payload':variant['judge_payload']}
                candidates.append(flat)
                if result['status']=='accepted':
                    accepted.append(flat)
                    (clear if flat['quality_flag']=='clear' else caution).append(flat)
        checks.append({'case_id':record['case_id'],'original_reconstructed':True,'requests_match_frozen_prompts':True,
                       'family_verified':family is not None,'decision_replayed':decision is not None,
                       'recorded_validation_error':validation_error})
    for h,r in receipts.items():
        assert r['request_hash']==digest(r['request'])
        assert h==r.get('receipt_id',r['request_hash'])
    confirmed=sum(r.get('actual_usd') or 0 for r in scoped.values())
    held=sum(r['reserve_usd'] for r in scoped.values() if r.get('actual_usd') is None)
    start=json.loads((BATCH/'START_ACCOUNTING.json').read_text())
    assert abs(account['actual_usd']-start['actual_usd']-confirmed)<1e-10
    assert confirmed+held<=0.5
    assert account['actual_usd']+account['unresolved_reserved_usd']<=account['budget_usd']
    assert len(rows)==10 and len(accepted)==20 and len(candidates)==30
    tests=json.loads((ROOT/'TEST_SUMMARY.json').read_text())
    summary={'scope':'Ten new task IDs; actual live v3 calls, not historical review replay','protocol':VERSION,
             'selected':10,'generation_and_review_responses_received':10,
             'statuses':dict(Counter(r['status'] for r in rows)),
             'accepted_families':len(accepted)//5,'accepted_variants':len(accepted),
             'candidate_families':len(candidates)//5,'candidate_variants':len(candidates),
             'accepted_variants_without_audit_caution':len(clear),'accepted_variants_with_audit_caution':len(caution),
             'audit_counts':audit['counts'],'confirmed_run_cost_usd':confirmed,'unresolved_run_reserve_usd':held,
             'run_cost_including_reserve_usd':confirmed+held,'attempted_api_calls':len(scoped),
             'completed_api_calls':sum(r.get('parsed') is not None for r in scoped.values()),
             'cost_per_attempted_source_usd':confirmed/10,'accounting':account,
             'total_authorized_usd':1.0,'total_confirmed_spend_usd':0.288047224+account['actual_usd'],
             'semantic_protocol_changed_during_pilot':False,'lexical_or_numeric_vetoes_added':False,
             'tests':tests,'judge_experiment_run':False,'human_gold_accuracy_measured':False,
             'technical_failures_not_counted_as_semantic_rejections':True}
    out=ROOT/'exports';out.mkdir(exist_ok=True)
    for name,data in [('all_results',rows),('candidate_inputs',candidates),('accepted_inputs',accepted),
                      ('accepted_without_audit_caution',clear),('accepted_with_audit_caution',caution)]:
        jsonl(out/(name+'.jsonl'),data)
    save(BATCH/'FINAL_SUMMARY.json',summary);save(ROOT/'SUMMARY.json',summary);save(out/'SUMMARY.json',summary)
    save(out/'OFFLINE_VERIFICATION.json',{'passed':True,'cases':checks,'request_receipts_checked':len(scoped),
                                         'source_hashes_verified':True,'secrets_included':False,
                                         'validation_failures_reported_not_hidden':True})
    report=render_report(summary,rows)
    (ROOT/'README.md').write_text(report);(out/'REPORT.md').write_text(report)
    (BATCH/'README.txt').write_text('The run is complete. Read ../../exports/REPORT.md and FINAL_SUMMARY.json.\nThe preflight estimate is historical; actual costs are in FINAL_SUMMARY.json.\n')
    html='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>10 новых трейсов — результаты</title><style>body{font:16px/1.6 system-ui;color:#1c2937;background:#f2f5f8;margin:0}main{max-width:1100px;margin:auto;padding:24px}header,article{background:white;border:1px solid #d7e0e7;border-radius:12px;padding:22px;margin-bottom:20px}h1{line-height:1.2}h2{font-size:21px}summary{cursor:pointer;font-weight:600;padding:8px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7fa;padding:14px;font-size:13px}.accepted{border-left:6px solid #25825b}.other{border-left:6px solid #bb8240}.note{background:#fff1d6;padding:14px}</style><main>'''
    html+='<header><h1>10 новых исходников → 20 принятых вариантов</h1><p>Создано 30 кандидатов; принято 4 комплекта. 15 вариантов без замечаний аудита, 5 с оговоркой к трактовке исхода.</p><p class="note">Аудит выполнен ассистентом, не независимыми людьми. Три случая не прошли формальную обработку null-кандидата. Целевой judge ещё не запускался.</p>'
    html+=detail('Отчёт',report)+detail('Числа и расходы',summary)+'</header>'
    for record,row in zip(records,rows):
        html+='<article class="'+('accepted' if row['status']=='accepted' else 'other')+'"><h2>'+escape(row['case_id']+' · '+row['task_id'])+'</h2><p><b>'+escape(row['status'])+'</b> · '+escape(row['quality_audit']['quality_flag'])+'</p>'
        html+=detail('Исходный трейс полностью',record['messages'])
        html+=detail('Удаление и объяснение генератора',row['generation'])
        if row['family']:
            html+=detail('Последняя реплика после удаления',row['family']['base']['messages'][-1])
            for v in row['family']['variants']:html+=detail(v['condition']+' — полный вариант',v['judge_payload'])
        html+=detail('Ревью',row['review'])+detail('Решение/ошибка валидации',{'decision':row['decision'],'validation_error':row['validation_error']})
        html+=detail('Дополнительная проверка качества',row['quality_audit'])+'</article>'
    html+='</main></html>';(out/'examples.html').write_text(html)
    files=[]
    for p in sorted(ROOT.rglob('*')):
        if not p.is_file():continue
        rel=p.relative_to(ROOT)
        if any(x.startswith('.') or x=='__pycache__' or x.startswith('tmp') for x in rel.parts):continue
        if p.suffix not in ('.py','.json','.jsonl','.md','.html','.txt'):continue
        if p.name.endswith('_tree.json') or p.name=='BUNDLE_MANIFEST.json':continue
        data=p.read_bytes()
        if re.search(rb'sk-or-v1-[A-Za-z0-9]{20,}',data):raise ValueError('credential_in_bundle')
        files.append((p,str(rel),hashlib.sha256(data).hexdigest()))
    save(ROOT/'BUNDLE_MANIFEST.json',{'files':[{'path':r,'sha256':h,'bytes':p.stat().st_size} for p,r,h in files]})
    target=ROOT.parent/'no_jev_pipeline_results.zip'
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p,rel,h in files:z.write(p,'no_jev_pipeline/'+rel)
        z.write(ROOT/'BUNDLE_MANIFEST.json','BUNDLE_MANIFEST.json')
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        for p,rel,h in files:assert hashlib.sha256(z.read('no_jev_pipeline/'+rel)).hexdigest()==h
    print(json.dumps({'summary':summary,'archive':str(target),'archive_bytes':target.stat().st_size,'verified':True},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
