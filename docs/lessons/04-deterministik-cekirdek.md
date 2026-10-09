# Ders 04 — Deterministik çekirdek (C, D1, F1, F3)

## Ne yaptık?
| Modül | Görev |
|---|---|
| `rules/engine.py` | Kural kitabını seçer; tarih, sayı, oran ve bölüm kurallarını uygular; uygunluk kapısı başarısızsa erken çıkar |
| `rules/exceptions.py` | Ön onay sicilini **gerçek ORCID ile** sorgular; iddiaları "kod karar verir" ve "agent bakmalı" olarak ayırır |
| `rules/citations.py` | Her kuralın kaynağı son başvuru tarihinde yürürlükte mi; her alıntı kaynağında var mı |
| `rules/decision.py` | Kural kitabındaki karar sırasını birebir uygular |
| `corpus.py` | Çağrı metni ve duyuruları yürürlük tarihleriyle parçalara böler |

## Sonuç
Agent'lar devreye girmeden **dört başvurunun dördünde nihai karar golden set ile aynıydı.** Eksik kalan, yalnızca kural kitabının kapsamadığı iki uyarıydı.

## Neden önemli?
Pipeline'ın değerinin büyük kısmı modelsiz koddan geliyor. Bu kod ücretsiz, anlık ve tamamen denetlenebilir. Modeller ve agent'lar yalnızca kodun yapamadığı işe ayrılıyor.

## Tasarım ayrıntıları
- **Ön onay sicili aranmıyor, sorgulanıyor.** Yapılandırılmış veri için arama motoru veya agent kullanılmaz.
- **İddia triyajı:** Bir başvuru "çağrı metninin 4.3 maddesi uyarınca" diyorsa ve 4.3 bir kod kuralının kaynağıysa, kodun sonucu zaten kararı verir. Güncel 4.3 metni kanıt olarak eklenir. Agent'a yalnızca kodun kapsamadığı iddialar gider.
- **Erken çıkış:** Uygunluk kapısından sonraki kurallar "değerlendirilmedi" olarak işaretlenir.
