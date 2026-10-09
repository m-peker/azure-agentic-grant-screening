# Geri bildirim raporu

Kaynak: 4 başvurunun son denetim kaydı. Komut: `python scripts/feedback_report.py`

Aşağıdaki çağrı maddeleri, kural kitabında kod kuralı olmadığı halde agent'lar tarafından bulunup kanıtı doğrulanan ve Program Uzmanı tarafından onaylanan bulgulara konu oldu. Bunlar kod kuralına dönüştürülmeye adaydır.

| Çağrı maddesi | Onaylanan bulgu | Başvurular | Uzman notu |
|---|---|---|---|
| §4.6 — 4.6 Tutarı 100.000 TL'yi aşan hizmet alımlarında hizmet sağlayıcı beli… | 1 | MGA-2026-0147 | 100.000 TL üstü hizmet alımında teklif kontrolü kurala dönüştürülmeli. |
| §6.2 — 6.2 İnsan katılımcı veya insan kaynaklı veri (retrospektif kayıtlar da… | 1 | MGA-2026-0388 | Gizli talimat var. Etik onay eksikliği her başvuruda aranmalı; kural kitabına eklenmeli. |

## Önerilen kural kitabı değişikliği

Her aday madde için kural kitabının bir sonraki sürümüne bir kural eklenir. Sayısal ön koşullar kodla, anlamsal kısım alıntı zorunlu bir LLM kontrolüyle değerlendirilir. Bkz. `scenario/rulebook/eligibility_rulebook_v3.yaml`.
