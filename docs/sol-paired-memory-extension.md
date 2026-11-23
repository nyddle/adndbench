# Sol на прежних dev-мирах памяти

`scripts/sol_paired_memory_extension.py` добавляет GPT‑6.2 Sol к завершённым
партиям Luna и Astra на dev-мирах `radical-memory-base` — по 12 обменов в
компактном протоколе. Это разведочное сравнение трёх моделей, а не оценка на
holdout и не окончательная калибровка.

```sh
python3 scripts/sol_paired_memory_extension.py init radical-memory-base-sol --source radical-memory-base
python3 scripts/sol_paired_memory_extension.py run radical-memory-base-sol
python3 scripts/sol_paired_memory_extension.py status radical-memory-base-sol
```

Init проверяет fingerprint исходного плана и воспроизводит все завершённые
партии обеих моделей. Новый приватный план получает только исходные dev-сиды,
проверенные исходы и их hashes, а также тот же системный prompt, версию CLI,
контекст, low reasoning и лимиты. Holdout не копируется, команду его запуска
этот runner не предоставляет. Исходные файлы не изменяются. Отпечаток и новый
приватный каталог изолируют эксперимент от ранее идущих серий.

Сетевой сбой, неопределённый запрос и лимит исполнителя не являются неверным
ответом; автоматические повторы отключены. Codex CLI проверяет события вызовов
инструментов, но не создаёт полной файловой изоляции и не равен Chat Completions
API. Ограничитель токенов срабатывает между запросами, а не является денежным
лимитом. См. [общую инструкцию](paired-codex-calibration.md).

Проверка без модели: `python3 -m unittest scripts.test_sol_paired_memory_extension -v`.
