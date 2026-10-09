# Ders 10 — Geri bildirim döngüsü: agent'tan kurala

## Ne yaptık?
1. `scripts/feedback_report.py`, denetim kayıtlarından **kanıtı doğrulanmış ve uzmanca onaylanmış** agent bulgularını çağrı maddelerine göre topladı. Çıkan adaylar §4.6 hizmet alımı ve §6.2 etik oldu, uzman notları da yanlarında.
2. Kural kitabı **v3**, 2026-10-01'den itibaren yürürlükte. İki yeni kural içeriyor:
   - **R-BUD-05:** Sayısal ön koşulu kod kontrol ediyor (hizmet satırı 100.000 TL'yi aşıyor mu). Aşmıyorsa model hiç çağrılmıyor. Aşıyorsa alıntı zorunlu tek bir model çağrısı "sağlayıcı ve teklif var mı" sorusunu değerlendiriyor.
   - **R-ETH-01:** "İnsan kaynaklı veri var mı?" ve "Etik belgesi eklenmiş mi?" soruları alıntı zorunlu tek bir çağrıyla değerlendiriliyor.
3. Kapsam boşluğu kendiliğinden küçüldü. Açık risk taraması artık 4.6 ve 6.2'ye bakmıyor.

## Sonuç (`docs/eval_report_v2.md` ve `docs/eval_report_v3.md`, 3'er deneme)
| | v2 | v3 |
|---|---|---|
| Nihai karar | 12/12 | 12/12 |
| Şablon | 12/12 | 12/12 |
| Kural sonucu | 75/75 | 93/93 |
| Agent çalıştırması | 6 | **0** |
| Ortalama maliyet, tam akış | 0,0132 $ | **0,0098 $** |

Etik kuralı artık her başvuruda bir çağrı yaptığı için buğday başvurusu v3'te biraz daha pahalı (0,0069 $ → 0,0085 $).

## Ders
Agent'lar bilinmeyeni keşfetmek içindir. Bir risk birkaç kez bulunup onaylandığında artık bilinen bir risktir ve kurala dönüşmelidir. Kural daha ucuz, daha tekrarlanabilir ve daha kolay denetlenir. İnsan geri bildirimi sistemi bu yönde eğitir. Model eğitilmiyor, **kural kitabı** gelişiyor.

## Sürüm yönetimi
- Kural kitabı tarama tarihine göre seçiliyor. Karşılaştırma için `GRANT_RULEBOOK=2` ile sürüm sabitlenebiliyor.
- Workflow durumu sürüm numarasını taşıyor. Checkpoint'ten devam eden bir akış başka bir sürüme kaymıyor.
- Denetim kaydı hangi kural kitabının kullanıldığını içeriyor.
