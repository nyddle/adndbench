# Три модели на сбалансированной короткой памяти

`scripts/three_model_balanced_memory.py` сравнивает GPT‑6 Luna, GPT‑6.2 Sol и
GPT‑6.2 Astra с одинаковым `reasoning_effort=low` и одинаковыми мирами. Уровни
`s4`, `s6`, `s8` используют четыре, шесть и восемь обменов соответственно,
разделённых на две последовательные группы. Во всех случаях ровно четыре
модельных действия, если нет невалидных ходов. Целевая вещь называется только
после последнего обмена. Этот отдельный протокол не смешивают с предыдущими
сериями grouped-memory.

```sh
python3 scripts/three_model_balanced_memory.py init short-memory-4 \
  --level s4 --dev-worlds 2 --holdout-worlds 3 \
  --max-actions 8 --context-turns 8 --max-calls 30 --max-input-tokens 850000
python3 scripts/three_model_balanced_memory.py run short-memory-4 --split dev
python3 scripts/three_model_balanced_memory.py status short-memory-4
# После выбора и фиксации протокола и завершения всей dev-тройки:
python3 scripts/three_model_balanced_memory.py seal short-memory-4
python3 scripts/three_model_balanced_memory.py run short-memory-4 --split holdout
```

Модели видят одни и те же правила и исходные сведения на одном seed. Новый план
генерирует новые сиды: уровни в отдельных планах сами по себе не составляют
парное сравнение одной истории, хотя генератор поддерживает вложенные префиксы
при одинаковом seed. Holdout сиды независимы от dev и недоступны для запуска до
`seal`. Начальная подсказка должна оставаться в окне контекста при всех
разрешённых ходах; некорректные лимиты отклоняются при создании плана.

Технические ошибки, неподтверждённые запросы и ограничения runner отдельно от
неправильных ответов. В status есть количество запланированных и завершённых
случаев и полных троек, а вычисленная точность относится только к терминальным
партиям. На малом числе миров это описательная проверка; по ней нельзя надёжно
оценить итоговую долю успеха. Инструментальные вызовы аудируются, но файловая
среда не полностью изолирована; это Codex CLI, а не прямой Chat Completions API.
Сиды и журналы приватны. Лимит токенов проверяется между запросами и может быть
превышен одним запросом; это не денежный лимит. Никаких автоматических повторов.
Дополнительные ограничения и методика в [paired-codex-calibration.md](paired-codex-calibration.md).

Офлайн-тесты: `python3 -m unittest scripts.test_three_model_balanced_memory -v`.

### Fresh holdout fork after a dev pilot

If a sealed or unsealed study has fully completed dev episodes but an untouched
holdout, `scripts/fork_balanced_holdout.py SOURCE DESTINATION` creates a new,
private study. It replays every dev transcript, copies the dev receipts, creates
fresh random holdout seeds disjoint from both source pools, and records source
and destination hashes, the code fingerprint and old/new budgets in
`audit.json`. It does not modify the source study or call a model. The fork
requires a new destination name and is initially unsealed; inspect it, seal it,
then run holdout with `three_model_balanced_memory.py`. The source holdout must
remain untouched and must not be used as an additional tuning set after seeing
the new holdout results. The fork is a new holdout sample, not the old holdout
with an amended budget.

For the s4 three-model pilot, `--holdout-worlds 3 --max-calls 75
--max-input-tokens 1500000` allows 36 normal calls plus extra actions and sets
an explicit input-token guard. The input limit is checked before each call and
can be exceeded by the final call. A call may incur costs even on a technical
failure; failed or interrupted calls are never automatically retried. Other
protocol parameters, models, effort, context and game rules are copied exactly.

### Продолжение оставшихся партий после технического сбоя

В плане `expanded-memory-s8` один вызов holdout получил `turn_failed`; исходный
исполнитель остановил всю серию. Отдельный `scripts/continue_balanced_holdout.py`
проверяет неизменность запечатанного плана, отказывается от работы при
неопределённом `inflight`, фиксирует приватный audit с SHA продолжателя и
исполнителя и запускает только оставшиеся `ready` партии. Партии в состоянии
`technical_error` не повторяются. Действуют исходные накопительные лимиты и
исходные наблюдения, prompt, модели и правила; лимит времени является лимитом
на отдельный запуск. Изменение механизма остановки необходимо указывать в
публикации вместе с техническим пропуском и числом полных троек. Тесты:
`python3 -m unittest scripts.test_continue_balanced_holdout -v`.
