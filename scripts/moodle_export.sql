-- =====================================================================
-- Выгрузка данных из Moodle 3.11.x для исследования по теме T4
-- (learning analytics: предсказание успеваемости по данным LMS)
--
-- Диалект: MySQL / MariaDB (стандарт для Moodle).
-- Схема этих таблиц идентична в Moodle 3.11-5.x, запросы переносимы.
-- Для PostgreSQL см. примечания в конце файла.
--
-- ПЕРЕД ЗАПУСКОМ настрой блок "ПАРАМЕТРЫ" ниже.
--
-- ВАЖНО: выполняй на РЕПЛИКЕ или на копии базы, не на боевом сервере.
-- Запрос к logstore_standard_log тяжёлый — на живой системе он способен
-- заметно просадить производительность для пользователей.
-- =====================================================================

-- ---------------------------------------------------------------------
-- ПАРАМЕТРЫ — заполни своими значениями
-- ---------------------------------------------------------------------

-- Соль для псевдонимизации. ЗАМЕНИ на собственную случайную строку.
-- Храни её отдельно от выгрузки и никому не передавай: без неё
-- восстановить исходные ID невозможно, с ней — тривиально.
SET @SALT = 'ЗАМЕНИ_МЕНЯ_НА_СЛУЧАЙНУЮ_СТРОКУ_МИНИМУМ_32_СИМВОЛА';

-- Период выгрузки (unix timestamp). Пример ниже — учебный год.
SET @DATE_FROM = UNIX_TIMESTAMP('2024-09-01');
SET @DATE_TO   = UNIX_TIMESTAMP('2025-06-30');

-- Минимальное число студентов в курсе. Курсы меньше этого порога
-- исключаются: по ним возможна реидентификация конкретного студента.
SET @MIN_STUDENTS = 10;

-- Префикс таблиц. По умолчанию mdl_ — проверь в config.php ($CFG->prefix).


-- =====================================================================
-- ЗАПРОС 1 — Каталог курсов
-- Выгрузи в: data/raw/courses.csv
--
-- ВНИМАНИЕ: поле course.format в Moodle — это формат ОТОБРАЖЕНИЯ курса
-- (topics/weeks/singleactivity), а НЕ форма обучения. Признак
-- "дистанционный / гибридный / очный" в Moodle отсутствует как таковой.
-- Его нужно получить из учебной части отдельной таблицей и присоединить
-- по course_id уже на этапе обработки. Без него разваливается RQ2.
-- =====================================================================

SELECT
    c.id                                    AS course_id,
    c.shortname                             AS course_code,
    c.format                                AS moodle_display_format,
    cat.name                                AS category,
    FROM_UNIXTIME(c.startdate)              AS start_date,
    FROM_UNIXTIME(c.enddate)                AS end_date,
    COUNT(DISTINCT ra.userid)               AS n_students
FROM mdl_course c
JOIN mdl_course_categories cat  ON cat.id = c.category
JOIN mdl_context ctx            ON ctx.instanceid = c.id
                               AND ctx.contextlevel = 50      -- CONTEXT_COURSE
JOIN mdl_role_assignments ra    ON ra.contextid = ctx.id
JOIN mdl_role r                 ON r.id = ra.roleid
                               AND r.shortname = 'student'
WHERE c.startdate BETWEEN @DATE_FROM AND @DATE_TO
  AND c.visible = 1
GROUP BY c.id, c.shortname, c.format, cat.name, c.startdate, c.enddate
HAVING COUNT(DISTINCT ra.userid) >= @MIN_STUDENTS
ORDER BY c.startdate, c.id;


-- =====================================================================
-- ЗАПРОС 2 — Состав студентов по курсам (псевдонимизированный)
-- Выгрузи в: data/raw/enrolments.csv
--
-- Реальные ID НЕ выгружаются — только хеш. Преподаватели и админы
-- отфильтрованы по роли.
-- =====================================================================

SELECT
    SHA2(CONCAT(u.id, @SALT), 256)          AS student_hash,
    c.id                                    AS course_id,
    FROM_UNIXTIME(ue.timestart)             AS enrolled_at
FROM mdl_user u
JOIN mdl_user_enrolments ue     ON ue.userid = u.id
JOIN mdl_enrol e                ON e.id = ue.enrolid
JOIN mdl_course c               ON c.id = e.courseid
JOIN mdl_context ctx            ON ctx.instanceid = c.id
                               AND ctx.contextlevel = 50
JOIN mdl_role_assignments ra    ON ra.contextid = ctx.id
                               AND ra.userid = u.id
JOIN mdl_role r                 ON r.id = ra.roleid
                               AND r.shortname = 'student'
WHERE c.startdate BETWEEN @DATE_FROM AND @DATE_TO
  AND u.deleted = 0
  AND c.visible = 1
ORDER BY c.id, student_hash;


-- =====================================================================
-- ЗАПРОС 3 — Активность по неделям (ядро анализа)
-- Выгрузи в: data/raw/weekly_activity.csv
--
-- Даёт понедельную агрегацию событий на каждого студента в каждом курсе.
-- Из этих данных на стороне Python считаются:
--   - total_events, active_days
--   - regularity: энтропия Шеннона распределения активности по неделям
--     (проверка гипотезы H1)
--   - first_week_activity (для RQ3)
--
-- Абсолютные даты не выгружаются — только номер недели от старта курса.
-- Это дополнительный барьер против реидентификации.
--
-- Запрос тяжёлый. Если база большая — гоняй по одному семестру за раз,
-- сузив @DATE_FROM/@DATE_TO.
-- =====================================================================

SELECT
    SHA2(CONCAT(l.userid, @SALT), 256)      AS student_hash,
    l.courseid                              AS course_id,
    FLOOR((l.timecreated - c.startdate) / 604800) AS week_num,  -- 604800 = 7 дней
    CASE
        WHEN l.eventname LIKE '%course_viewed%'        THEN 'course_view'
        WHEN l.eventname LIKE '%course_module_viewed%' THEN 'resource_view'
        WHEN l.eventname LIKE '%discussion%'
          OR l.eventname LIKE '%post_created%'         THEN 'forum_post'
        WHEN l.eventname LIKE '%forum%viewed%'         THEN 'forum_read'
        WHEN l.eventname LIKE '%submission%'           THEN 'submission'
        WHEN l.eventname LIKE '%quiz%attempt%'         THEN 'quiz_attempt'
        WHEN l.action = 'loggedin'                     THEN 'login'
        ELSE 'other'
    END                                     AS event_category,
    COUNT(*)                                AS n_events,
    COUNT(DISTINCT DATE(FROM_UNIXTIME(l.timecreated))) AS active_days
FROM mdl_logstore_standard_log l
JOIN mdl_course c               ON c.id = l.courseid
JOIN mdl_context ctx            ON ctx.instanceid = c.id
                               AND ctx.contextlevel = 50
JOIN mdl_role_assignments ra    ON ra.contextid = ctx.id
                               AND ra.userid = l.userid
JOIN mdl_role r                 ON r.id = ra.roleid
                               AND r.shortname = 'student'   -- только студенты
WHERE l.courseid > 1                                          -- 1 = системный курс
  AND l.timecreated BETWEEN @DATE_FROM AND @DATE_TO
  AND l.timecreated >= c.startdate
  AND l.origin != 'cli'                                       -- отсечь фоновые задачи
  AND c.visible = 1
GROUP BY student_hash, l.courseid, week_num, event_category
ORDER BY l.courseid, student_hash, week_num;


-- =====================================================================
-- ЗАПРОС 4 — Итоговые оценки (зависимая переменная)
-- Выгрузи в: data/raw/grades.csv
--
-- Оценки нормируются к 0-100, чтобы курсы с разными шкалами были
-- сопоставимы. Без нормировки регрессия по объединённой выборке
-- бессмысленна.
-- =====================================================================

SELECT
    SHA2(CONCAT(gg.userid, @SALT), 256)     AS student_hash,
    gi.courseid                             AS course_id,
    gi.itemtype                             AS item_type,      -- 'course' = итоговая
    gi.itemmodule                           AS item_module,
    gg.rawgrade                             AS raw_grade,
    gg.finalgrade                           AS final_grade,
    gi.grademax                             AS grade_max,
    ROUND(100.0 * gg.finalgrade / NULLIF(gi.grademax, 0), 2) AS grade_pct
FROM mdl_grade_grades gg
JOIN mdl_grade_items gi         ON gi.id = gg.itemid
JOIN mdl_course c               ON c.id = gi.courseid
WHERE c.startdate BETWEEN @DATE_FROM AND @DATE_TO
  AND gg.finalgrade IS NOT NULL
  AND c.visible = 1
ORDER BY gi.courseid, student_hash, gi.itemtype;


-- =====================================================================
-- ЗАПРОС 5 — Своевременность сдачи заданий (гипотеза H3)
-- Выгрузи в: data/raw/submissions.csv
--
-- lead_time_hours: за сколько часов до дедлайна сдано.
--   положительное  = сдал заранее
--   отрицательное  = сдал с опозданием
-- Это ключевая переменная для RQ3 — раннего предсказания.
-- =====================================================================

SELECT
    SHA2(CONCAT(sub.userid, @SALT), 256)    AS student_hash,
    a.course                                AS course_id,
    a.id                                    AS assignment_id,
    FLOOR((a.duedate - c.startdate) / 604800) AS due_week_num,
    sub.status                              AS status,
    ROUND((a.duedate - sub.timemodified) / 3600.0, 2) AS lead_time_hours,
    CASE WHEN sub.timemodified <= a.duedate THEN 1 ELSE 0 END AS on_time
FROM mdl_assign_submission sub
JOIN mdl_assign a               ON a.id = sub.assignment
JOIN mdl_course c               ON c.id = a.course
WHERE c.startdate BETWEEN @DATE_FROM AND @DATE_TO
  AND sub.status = 'submitted'
  AND a.duedate > 0                          -- задания без дедлайна не считаем
  AND c.visible = 1
ORDER BY a.course, student_hash, a.id;


-- =====================================================================
-- ЧЕГО ЗДЕСЬ НЕТ И ЧТО НУЖНО ДОБАВИТЬ ОТДЕЛЬНО
-- =====================================================================
--
-- 1. ФОРМА ОБУЧЕНИЯ (дистанционная / гибридная / очная).
--    В Moodle этого признака нет. Возьми в учебной части таблицу
--    соответствия и сохрани как data/raw/course_modes.csv в виде:
--        course_id,mode
--        1234,distance
--        1235,hybrid
--    Без этого не проверить RQ2 — а это половина новизны работы.
--
-- 2. БАЛЛ ПРИ ПОСТУПЛЕНИИ (или входной рейтинг).
--    Нужен как контрольная переменная: без него рецензент спросит,
--    не меряет ли модель просто исходную подготовку студента.
--    Формат data/raw/student_background.csv:
--        student_hash,entry_score,year_of_study,program
--    ВАЖНО: хешируй тем же @SALT, иначе таблицы не соединятся.
--
--
-- ПРОВЕРКА ПЕРЕД ОТПРАВКОЙ
-- =====================================================================
-- Открой каждый CSV и убедись глазами, что там НЕТ:
--   - ФИО, e-mail, телефонов, дат рождения
--   - исходных числовых userid (должны быть только 64-символьные хеши)
--   - текстов сообщений форума
-- Соль @SALT остаётся только у тебя и в репозиторий не попадает.
--
--
-- ПРИМЕЧАНИЯ ДЛЯ POSTGRESQL
-- =====================================================================
--   SHA2(CONCAT(x, @SALT), 256)  ->  encode(digest(x || :salt, 'sha256'), 'hex')
--                                    (требует расширение pgcrypto)
--   FROM_UNIXTIME(x)             ->  to_timestamp(x)
--   UNIX_TIMESTAMP('2024-09-01') ->  extract(epoch from date '2024-09-01')
--   DATE(FROM_UNIXTIME(x))       ->  to_timestamp(x)::date
--   SET @VAR = ...               ->  использовать psql-переменные \set
--                                    или подставить значения вручную
