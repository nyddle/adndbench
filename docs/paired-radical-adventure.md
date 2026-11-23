# Парный запуск объединённого приключения

`scripts/paired_radical_adventure.py` подключает `radical_adventure.Game` к
тому же проверенному парному исполнителю, что [отдельные векторы](paired-codex-calibration.md).
Он работает в своём процессе и каталоге планов; существующие серии или их код
не изменяются. Модели — GPT‑6 Luna и GPT‑6.2 Astra с `low` reasoning, общие
миры, одинаковые правила, ограничения и длина истории. Это разведочный Codex
CLI, не строго изолированная среда и не прежний Chat Completions API протокол.

Из корня workspace, например:

```bash
python3 scripts/paired_radical_adventure.py init integrated-dev \
  --memory medium --navigation medium --quests hard --combat off --party off \
  --dev-worlds 1 --holdout-worlds 3 --max-turns 200 \
  --max-actions 80 --context-turns 80 --max-calls 180 --max-input-tokens 5000000
python3 scripts/paired_radical_adventure.py run integrated-dev --split dev
python3 scripts/paired_radical_adventure.py status integrated-dev
# Только после выбора и фиксации протокола и завершения одной общей dev-пары:
python3 scripts/paired_radical_adventure.py seal integrated-dev
python3 scripts/paired_radical_adventure.py run integrated-dev --split holdout
```

`--memory easy|medium|hard|extreme`, `--navigation easy|medium|hard`,
`--quests medium|hard|extreme`, `--combat off|easy|medium|hard` и
`--party on|off` задаются отдельно. При сравнении одной оси фиксируйте все
остальные и ограничения; правила, параметры и источники сохраняются в плане.
Одинаковый seed даёт один и тот же мир для обеих моделей внутри плана;
новый план создаёт новые seed, поэтому это не парное сравнение уровней между
планами. Сначала полезно проверять память, ориентирование и квесты с боем и
партией `off`, а затем изучать эти механики отдельно и вместе.

План и результаты закрыты правами владельца в
`~/.local/share/adndbench/paired-radical-adventures/`. Сиды dev и holdout
независимы, правила `seal`, контроль количества запросов и input tokens, учёт
неопределённых попыток и отсутствие автоматических повторов описаны в общей
инструкции. Неполные и технически оборвавшиеся партии нельзя считать
поражениями. `max-actions` — лимит пилота, `max-turns` — правило самой игры.
Контекстное окно обязано вмещать всю историю до меньшего из этих двух лимитов,
чтобы не исключить одноразовую подсказку из условия. Токенный ограничитель
проверяется между запросами и может быть превышен одним запросом; он не является
денежным лимитом. `status` показывает конфигурацию и агрегаты без seed.

Ввод игрока и аудит не раскрывают скрытую карту, seed или код. При неверном
коде на открываемом замке одна попытка корректно расходуется; произвольный
текст нормализуется в заведомо неверный код, а правильный код сохраняется.
Открытые формы действий не перечисляют все возможные коды или ещё не встреченных
спутников. Ходы сохраняются без scratchpad и затем воспроизводятся со сверкой
наблюдений. Источник и транзитивные локальные зависимости фиксируются SHA;
изменение сценария либо любого из двух runner блокирует продолжение.

Офлайн-проверка, без вызовов модели:
`python3 -m unittest scripts.test_paired_radical_adventure -v`.
