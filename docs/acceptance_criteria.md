# Критерии приёмки по шагам

Как пользоваться: для каждого шага из таблицы в `docs/pipeline.md` здесь записано, по каким признакам задача считается
выполненной. Агент `task-verifier` сверяет с ними каждую задачу. Если критериев для шага нет, он предлагает свои со
статусом `proposed` и задаёт вопросы владелице; после её ответа статус становится `confirmed <дата>`.

Каждый критерий проверяется командой или подсчётом. Формат:
`- [статус] критерий — как проверить`

## Общие (для любой задачи, которая меняет код или данные)
- [proposed] Все тесты проходят — `python -m pytest -q`
- [proposed] Ни одно решение владелицы не потеряно — `python -m rg_music.pipeline --check` без LOST_OWNER_DECISION
- [proposed] Изменились только ожидаемые числа — `--check` против HEAD показывает лишь то, что описано в задаче

<!-- Ниже по шагам: ## Шаг 7 · Слияние таблиц ... -->

## Шаг 7 · Слияние таблиц соревнований с выступлениями, сезоны в годы (merge.py; с шага 19 и родная Википедия)
- [proposed] Ни одна строка `routines_raw.csv` не потеряна: каждая есть в `routines_merged.csv` (по gymnast_page + table_index + row_index), кроме исключённых владелицей (`routine_exclusions.csv`) и заменённых испанской строкой (`dropped_english` в `merge_report.json`) — сверка скриптом
- [proposed] У каждого выступления год — одно число; строка из сезона («2022/2023») имеет `year_source` и пометку `expanded_from_season` — подсчёт по `routines_merged.csv`
- [proposed] `routine_id` уникален; каждая строка `routine_events.csv` ссылается на существующее выступление, повторов событий нет — подсчёт
- [proposed] Каждое решение владелицы шага применено: строки `routine_exclusions.csv` нет в выходе; пары `same_routine.csv` слиты (пометка `same_routine_by_owner`, отдельной строки соревнования нет); `native_conflict_decisions.csv`: both → испанская строка есть, english → её нет, spanish → она есть, а английские id из `english_routine_ids` удалены — сверка скриптом
- [proposed] Счёт в `merge_report.json` сходится: `competition_rows_in` = skipped + merged + added; `routines_out` = сумма `by_source` = строк в `routines_merged.csv`; `native_music_todo.csv` пуст (все испанские ячейки переведены) — подсчёт
