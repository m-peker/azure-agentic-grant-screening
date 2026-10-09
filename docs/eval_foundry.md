# Foundry değerlendirmesi — Soruşturmacı agent

Komut: `python eval/foundry_eval.py`. Değerlendirme çalışmaları Foundry portalında, Evaluations altında görünür.

| Başvuru | Madde | Beklenen | Agent | Araç çağrısı | Foundry sonucu |
|---|---|---|---|---|---|
| MGA-2026-0147 | 4.6 | CONFIRMED | CONFIRMED ✅ | 6 | 1/1 geçti |
| MGA-2026-0388 | 6.2 | CONFIRMED | CONFIRMED ✅ | 4 | 1/1 geçti |
| MGA-2026-0213 | 6.2 | DISMISSED | DISMISSED ✅ | 5 | 1/1 geçti |

Foundry değerlendiricileri: task adherence, tool call accuracy, intent resolution (LLM-as-judge).
Beklenen karar sütunu golden set'ten gelir ve kodla kontrol edilir.
