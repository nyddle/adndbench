# Промежуточная парная проверка памяти

`scripts/paired_intermediate_memory.py` — отдельный план поверх общего парного
Codex-исполнителя. В задаче восемь персонажей и 24 упорядоченных обмена,
показанных группами до шести; одно решение после каждого блока и конечный ответ.
Это отдельный протокол, не тождественный модели, действующей между каждым
обменом. Целевая вещь задаётся только в конце. Уровень выбрали как промежуточный
между предыдущими dev-условиями; его ожидаемую долю успехов ещё нужно измерить.

```sh
python3 scripts/paired_intermediate_memory.py init middle-memory \
  --dev-worlds 2 --holdout-worlds 3 --max-actions 10 --context-turns 10 \
  --max-calls 45 --max-input-tokens 1200000
python3 scripts/paired_intermediate_memory.py run middle-memory --split dev
python3 scripts/paired_intermediate_memory.py status middle-memory
# После выбора этой конфигурации и завершения хотя бы одной dev-пары:
python3 scripts/paired_intermediate_memory.py seal middle-memory
python3 scripts/paired_intermediate_memory.py run middle-memory --split holdout
```

Luna и Astra используют один seed на мир, одинаковые low reasoning, правила,
историю и лимиты. Разделы dev и holdout независимы. Окно обязано сохранять все
начальные сведения вплоть до меньшего из игрового и исследовательского лимитов;
неподходящие настройки отклоняются до создания плана. Текущий ответ определяется
по полученным наблюдениям, не из скрытого состояния. Уровень сложности и ответы
моделей не должны подбираться по holdout.

Сид и журналы хранятся в приватном каталоге
`~/.local/share/adndbench/paired-intermediate-memory/`; status выводит агрегаты.
Каждый вызов записывается как inflight до отправки. Технический сбой, действие
инструмента, неизвестный исход и лимит исследовательского процесса не являются
неверным игровым ответом. Никаких автоматических повторов. Ограничитель токенов
срабатывает между запросами и может быть превышен одним вызовом; это не денежный
лимит. Источники и зависимости, включая `hard_memory_navigation.py`, проверяются
по fingerprint. Общая методика и ограничения Codex-изоляции — в
[paired-codex-calibration.md](paired-codex-calibration.md).

Без модельных запросов: `python3 -m unittest scripts.test_paired_intermediate_memory -v`.
