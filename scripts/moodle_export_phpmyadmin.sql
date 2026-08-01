-- =====================================================================
-- ВЫГРУЗКА ДАННЫХ ИЗ MOODLE 3.11 — версия для phpMyAdmin
--
-- Отличие от moodle_export.sql: значения подставлены прямо в текст
-- запросов. В phpMyAdmin переменные SET @VAR не сохраняются между
-- отдельными нажатиями «Вперёд», поэтому там они не работают.
--
-- Схема таблиц в Moodle 3.11 и 5.x для этих запросов идентична.
-- =====================================================================
--
-- ПОДГОТОВКА (делается один раз, в любом текстовом редакторе)
-- ---------------------------------------------------------------------
-- Открой этот файл в Блокноте и сделай автозамену (Ctrl+H) трёх строк:
--
--   __SALT__        ->  своя случайная строка, 32+ символа
--                       например: k7Qm2xR9pL4vN8wZ3tY6bH1jF5dS0aG7
--                       ВАЖНО: замени во ВСЕХ пяти запросах одинаково,
--                       иначе таблицы не соединятся по student_hash
--
--   __DATE_FROM__   ->  начало периода, например  2024-09-01
--   __DATE_TO__     ->  конец периода,   например  2025-06-30
--
-- Соль сохрани отдельно (в заметках, не в этом файле) и никому не
-- передавай. Без неё восстановить, кто есть кто, невозможно.
--
--
-- КАК ВЫПОЛНЯТЬ В phpMyAdmin
-- ---------------------------------------------------------------------
-- 1. Слева выбери базу Moodle (обычно называется moodle)
-- 2. Сверху вкладка «SQL»
-- 3. Вставь ОДИН запрос (от SELECT до точки с запятой) — не весь файл
-- 4. Нажми «Вперёд» / «Go»
-- 5. Под таблицей результатов найди ссылку «Экспорт» / «Export»
-- 6. Формат: CSV. Поставь галочку «Поместить названия столбцов
--    в первой строке» / «Put columns names in the first row»
-- 7. Нажми «Вперёд» — файл скачается
-- 8. Переименуй по имени из заголовка запроса и повтори для следующего
--
-- ЕСЛИ ЗАПРОС ОТВАЛИВАЕТСЯ ПО ТАЙМАУТУ (чаще всего запрос 3):
--   Сузь период — гоняй по одному семестру за раз. Например сначала
--   2024-09-01 .. 2025-01-31, потом 2025-02-01 .. 2025-06-30.
--   Полученные CSV потом просто склеиваются.
--
-- ЕСЛИ ПРЕФИКС ТАБЛИЦ НЕ mdl_:
--   Посмотри в config.php значение $CFG->prefix и сделай автозамену
--   mdl_ на свой префикс.
-- =====================================================================


-- =====================================================================
-- ЗАПРОС 1 из 5  ->  сохранить как  courses.csv
-- Каталог курсов с числом студентов
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
                               AND ctx.contextlevel = 50
JOIN mdl_role_assignments ra    ON ra.contextid = ctx.id
JOIN mdl_role r                 ON r.id = ra.roleid
                               AND r.shortname = 'student'
WHERE c.startdate BETWEEN UNIX_TIMESTAMP('__DATE_FROM__')
                      AND UNIX_TIMESTAMP('__DATE_TO__')
  AND c.visible = 1
GROUP BY c.id, c.shortname, c.format, cat.name, c.startdate, c.enddate
HAVING COUNT(DISTINCT ra.userid) >= 10
ORDER BY c.startdate, c.id;


-- =====================================================================
-- ЗАПРОС 2 из 5  ->  сохранить как  enrolments.csv
-- Состав студентов по курсам. Реальные ID не выгружаются, только хеш.
-- =====================================================================

SELECT
    SHA2(CONCAT(u.id, '__SALT__'), 256)     AS student_hash,
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
WHERE c.startdate BETWEEN UNIX_TIMESTAMP('__DATE_FROM__')
                      AND UNIX_TIMESTAMP('__DATE_TO__')
  AND u.deleted = 0
  AND c.visible = 1
ORDER BY c.id, student_hash;


-- =====================================================================
-- ЗАПРОС 3 из 5  ->  сохранить как  weekly_activity.csv
-- ЯДРО АНАЛИЗА. Самый тяжёлый запрос — при таймауте дели по семестрам.
-- Абсолютные даты не выгружаются, только номер недели от старта курса.
-- =====================================================================

SELECT
    SHA2(CONCAT(l.userid, '__SALT__'), 256) AS student_hash,
    l.courseid                              AS course_id,
    FLOOR((l.timecreated - c.startdate) / 604800) AS week_num,
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
                               AND r.shortname = 'student'
WHERE l.courseid > 1
  AND l.timecreated BETWEEN UNIX_TIMESTAMP('__DATE_FROM__')
                        AND UNIX_TIMESTAMP('__DATE_TO__')
  AND l.timecreated >= c.startdate
  AND l.origin != 'cli'
  AND c.visible = 1
GROUP BY student_hash, l.courseid, week_num, event_category
ORDER BY l.courseid, student_hash, week_num;


-- =====================================================================
-- ЗАПРОС 4 из 5  ->  сохранить как  grades.csv
-- Оценки, нормированные к 0-100. itemtype='course' — итоговая за курс.
-- =====================================================================

SELECT
    SHA2(CONCAT(gg.userid, '__SALT__'), 256) AS student_hash,
    gi.courseid                             AS course_id,
    gi.itemtype                             AS item_type,
    gi.itemmodule                           AS item_module,
    gg.rawgrade                             AS raw_grade,
    gg.finalgrade                           AS final_grade,
    gi.grademax                             AS grade_max,
    ROUND(100.0 * gg.finalgrade / NULLIF(gi.grademax, 0), 2) AS grade_pct
FROM mdl_grade_grades gg
JOIN mdl_grade_items gi         ON gi.id = gg.itemid
JOIN mdl_course c               ON c.id = gi.courseid
WHERE c.startdate BETWEEN UNIX_TIMESTAMP('__DATE_FROM__')
                      AND UNIX_TIMESTAMP('__DATE_TO__')
  AND gg.finalgrade IS NOT NULL
  AND c.visible = 1
ORDER BY gi.courseid, student_hash, gi.itemtype;


-- =====================================================================
-- ЗАПРОС 5 из 5  ->  сохранить как  submissions.csv
-- Своевременность сдачи. lead_time_hours: + сдал заранее, - опоздал.
-- =====================================================================

SELECT
    SHA2(CONCAT(sub.userid, '__SALT__'), 256) AS student_hash,
    a.course                                AS course_id,
    a.id                                    AS assignment_id,
    FLOOR((a.duedate - c.startdate) / 604800) AS due_week_num,
    sub.status                              AS status,
    ROUND((a.duedate - sub.timemodified) / 3600.0, 2) AS lead_time_hours,
    CASE WHEN sub.timemodified <= a.duedate THEN 1 ELSE 0 END AS on_time
FROM mdl_assign_submission sub
JOIN mdl_assign a               ON a.id = sub.assignment
JOIN mdl_course c               ON c.id = a.course
WHERE c.startdate BETWEEN UNIX_TIMESTAMP('__DATE_FROM__')
                      AND UNIX_TIMESTAMP('__DATE_TO__')
  AND sub.status = 'submitted'
  AND a.duedate > 0
  AND c.visible = 1
ORDER BY a.course, student_hash, a.id;


-- =====================================================================
-- ПРОВЕРКА ПЕРЕД ОТПРАВКОЙ — обязательно
-- =====================================================================
-- Открой каждый из пяти CSV в Excel и убедись, что там НЕТ:
--   - ФИО, e-mail, телефонов, дат рождения
--   - обычных числовых userid (в столбце student_hash должны быть
--     строки из 64 символов вида a3f9c2e1...)
--   - текстов сообщений форума
--
-- Если в student_hash видны короткие числа вместо длинных строк —
-- значит автозамена __SALT__ не сработала. Проверь и перезапусти.
--
--
-- ЧЕГО В MOODLE НЕТ И ЧТО НУЖНО ВЗЯТЬ В УЧЕБНОЙ ЧАСТИ
-- =====================================================================
-- 1. course_modes.csv — форма обучения по каждому курсу:
--        course_id,mode
--        1234,distance
--        1235,hybrid
--        1236,onsite
--    Поле course.format в Moodle — это формат ОТОБРАЖЕНИЯ (topics/weeks),
--    а не форма обучения. Такого признака в Moodle нет вообще.
--
-- 2. student_background.csv — балл при поступлении:
--        student_hash,entry_score,year_of_study,program
--    Хешировать ТОЙ ЖЕ солью, иначе не соединится с остальными файлами.
