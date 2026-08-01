# Верификация библиографии

## Статус: ЗАВЕРШЕНА (2026-08-01)

Все 96 источников прогнаны через Crossref API скриптом
`scripts/verify_dois.py`. Сетевое ограничение, из-за которого прошлый
прогон был невозможен, снято — `api.crossref.org` доступен.

```bash
python3 scripts/verify_dois.py bibliography/refs.json -o bibliography/refs_verified.json
```

Полный машинный результат — в `bibliography/refs_verified.json`.

## Итог

| Статус | Кол-во | Что значит |
|---|---|---|
| `OK` | 89 | DOI существует, заглавие и год совпадают |
| `TITLE_MISMATCH` | 3 | DOI существует, заглавие в Crossref записано иначе — разобрано вручную, все три подтверждены |
| `NO_DOI` | 3 | В исходном отчёте DOI не был указан вовсе |
| `NON_CROSSREF_RA` | 1 | DOI зарегистрирован, но не в Crossref (JaLC) |

**Несуществующих источников не обнаружено. Из библиографии ничего не
удалено.**

Это главный вывод: отчёт LeapSpace сгенерирован ИИ, но список литературы
в нём — не выдумка. 93 из 96 записей имеют живой, разрешающийся DOI.

## Источники [14] и [33] — тревога была ложной

Прошлая проверка веб-поиском пометила их как «не найдены». Crossref
разрешает оба без нареканий:

| # | Запись | Результат |
|---|---|---|
| [14] | Alowayr, A. (2025) Learning analytics systems to improve the quality of students' outcomes | **Существует.** `10.24874/IJQR19.01-19`, Int. J. for Quality Research, т. 19, № 1, с. 297–312, издатель — Faculty of Engineering, University of Kragujevac. Заглавие совпадает дословно (sim = 1.0), DOI резолвится на `ijqr.net/journal/v19-n1/19.pdf` |
| [33] | Katsumi, M., Fox, M. (2018) Ontologies for transportation research: A survey | **Существует.** `10.1016/j.trc.2018.01.023`, Transportation Research Part C, Elsevier. Совпадение дословное |

### Важно: в старой версии этого документа была ошибка нумерации

Под номером [33] прошлая проверка описывала работу **Asadova (2026)** про
Central Asian higher education. Это неверно: в `bibliography/refs.json` и
в исходном отчёте Асадова идёт под номером **[32]**, а [33] — это
Katsumi & Fox. Та же ошибка была в `docs/01-topic-selection.md`, исправлена.

Сама работа Асадовой тоже проверена и **существует**:

> Asadova, Y. (2026) Technology-enhanced learning environments in Central
> Asian higher education: A four-study, multi-institutional
> quasi-experimental research program (N = 945). *International Journal of
> Educational Research*, т. 139, ст. 103044. `10.1016/j.ijer.2026.103044`

Единственный автор — Yulduz Asadova; ISSN 0883-0355 соответствует IJER;
запись депонирована 2026-07-11; DOI резолвится на Elsevier
(`S0883035526001151`). Для темы T4 это существенно: [32] — прямое
подтверждение центральноазиатского контекста, на котором строится новизна.

## Что было исправлено

### [57] — опечатка в DOI, а не выдуманный источник

Указанный в отчёте DOI `10.47836/mjmhs18.5.25` не существует (404 и в
Crossref, и на doi.org). Поиск по заглавию нашёл запись с DOI
`10.47836/mjmhs.18.5.25` — **отличие в одной точке**:

> Malik, A.S., Malik, R.H. (2022) Tips for Managing Resistance to
> Innovation in Medical Education. *Malaysian Journal of Medicine and
> Health Sciences*, 18(5), 180–189.

Авторы, журнал, год и заглавие совпадают полностью. DOI исправлен в
`refs.json` и `references.bib`.

### [30] — неверный год

BMC Nursing, `10.1186/s12912-026-04296-6`. Заглавие совпадает дословно,
но в Crossref год публикации — **2026**, а не 2025. Исправлено.

## Разобранные вручную расхождения

### `TITLE_MISMATCH` — все три подтверждены

Скрипт считает fuzzy-ratio заглавия; низкий ratio здесь не означает
проблему с источником:

| # | Причина расхождения |
|---|---|
| [1] | Zaikin (2022). В Crossref заглавие книги записано коротко — «Open Distance Learning», без подзаголовка «Fundamentals, Developments, and Modelling». DOI `10.1201/9781003132615` верен |
| [17] | Wong-Fajardo et al. (2023). В Crossref заглавие на языке оригинала: «Implementación de un modelo integrado de gestión académica con LMS en el sistema universitario». В отчёте — английский перевод. Журнал PUBLICACIONES, DOI верен |
| [18] | Nightingale (2003). В Crossref только первая часть заглавия — «Changing a Business School Corporate Culture», без «Teaching in the 21st Century on a Different Blackboard». DOI верен |

### `NON_CROSSREF_RA` — [93] существует

`10.24507/icicelb.17.07.651` (Chang, 2026, ICIC Express Letters Part B)
в Crossref отсутствует. Это **не** признак выдумки: DOI зарегистрирован
в **JaLC** (Japan Link Center), а Crossref API чужие агентства не видит.
Проверено:

- `https://doi.org/doiRA/10.24507/icicelb.17.07.651` → `{"RA": "JaLC"}`;
- DOI резолвится на реальный PDF `icicelb.org/ellb/contents/2026/7/elb-17-07-03.pdf`
  (том 17, выпуск 7 — совпадает с номером в DOI);
- контрольные несуществующие DOI под тем же префиксом
  (`10.24507/icicelb.99.99.999`) отдают `"DOI does not exist"`.

Ровно этот случай и есть главная ловушка автоматической чистки: удали
источник по признаку «нет в Crossref» — и потеряешь живую работу.

## Осталось непроверенным: 3 записи без DOI

Здесь Crossref бессилен — DOI не указан в самом отчёте. Поиск по
заглавию и автору точного совпадения не дал; это **не** доказательство
выдумки, но и не подтверждение.

| # | Запись | Комментарий |
|---|---|---|
| [20] | Mulyani et al. (2022) Development of an integrated academic management system in higher education. *Res Militaris* | Есть ссылка на Scopus ID `85141165503`. **Отдельная проблема:** Res Militaris исключён из Scopus за манипуляции с цитированием — цитировать его в статье, метящей в Q1, не стоит независимо от того, существует ли работа |
| [23] | Farajollahi et al. (2010) A conceptual model for effective distance learning in higher education. *TOJDE* | Автор реален и публикуется ровно по этой теме. TOJDE начал депонировать DOI позже 2010 г., поэтому отсутствие в Crossref ожидаемо. Проверять по архиву журнала |
| [70] | Chaw, L.Y., Tang, C.M. (2017) The voice of the students: needs and expectations from learning management systems. *Proceedings of ECEL* | Авторы реальны, их смежная работа «What Makes Learning Management Systems Effective for Learning?» (`10.1177/0047239518795828`, JETS 2018) подтверждена. Материалы конференций в Crossref попадают редко. Проверять по сборнику ECEL |

Порядок действий по ним: найти в архиве журнала/сборника, взять
выходные данные оттуда. До этого метка `UNVERIFIED` в `references.bib`
не снимается.

## Проверка честности самого канала

Прежде чем доверять ответам API, endpoint проверен контрольными
запросами: заведомо несуществующие DOI (`10.9999/totally.fake.doi.12345`,
`10.1016/j.ijer.2026.999999`) возвращают 404, а известный реальный DOI
возвращает корректные метаданные. Ответы Crossref в этом окружении
достоверны.

## Что изменено в скрипте

`scripts/verify_dois.py` доработан по следам разбора — старая версия
объявила бы [57] и [93] несуществующими:

1. При `404` от Crossref запрашивается реестр DOI (`doi.org/doiRA/`).
   Если DOI зарегистрирован в другом агентстве — статус
   `NON_CROSSREF_RA`, а не `NOT_FOUND`.
2. При `404` выполняется поиск по заглавию. Если находится запись с
   близким заглавием — статус `DOI_TYPO` с предложением верного DOI
   (именно так был пойман [57]).
3. `NOT_FOUND` теперь выставляется только когда DOI не существует **ни в
   одном** агентстве, и такие записи печатаются отдельным списком как
   кандидаты на удаление.

## Правило работы

Метка в поле `note` каждой записи `references.bib`:

- `VERIFIED crossref <дата>` — можно цитировать;
- `VERIFIED doi-registry (JaLC) <дата>` — можно цитировать, DOI живой;
- `UNVERIFIED` — цитировать нельзя до ручной проверки (осталось 3).

Перед подачей статьи прогнать скрипт ещё раз: записи 2026 года свежие,
метаданные у них могут уточняться.
