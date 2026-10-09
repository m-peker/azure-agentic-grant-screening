# Ders 01 — Senaryo ve golden set

## Ne yaptık?
- Kurgusal bir vakıf, bir çağrı metni (v1 ve v2), üç duyuru, bir ön onay sicili ve onaylı eksiklik şablonları hazırladık.
- **Dört başvurunun her biri ayrı bir yolu sınıyor:** istisna başarısızlığı, temiz otomatik geçiş, gizli prompt injection ve erken çıkış.
- PDF'leri `scripts/build_pdfs.py` üretiyor. `::hidden::` satırları beyaz renkli 1 puntoluk metin olarak basılıyor.
- `scenario/golden/expected_results.json` her başvurunun beklenen kural sonuçlarını, kararını ve şablonlarını içeriyor. Bütün yüzdeleri ve toplamları elle hesapladık.

## Neden önemli?
Golden set olmadan "sistem çalışıyor" iddiası ölçülemez. Faz 8'deki iki ciddi hata da golden set sayesinde bulundu.

## Tasarım ipuçları
- **Her tuzak bir öğrenme hedefine bağlı.** Eski çağrı metni yürürlük filtresini, yanlış toplam satırı "rakamlar koddan" ilkesini, ön onay sicili "yapılandırılmış veriyi sorgula, arama" ilkesini sınıyor.
- **Kural kitabında bilinçli boşluk bırakıldı.** Hizmet alımı ve etik kuralları v2'de yok. Agent'ların gerçek bir işi oldu ve geri bildirim döngüsü bunları v3'e ekledi.
- **Herkese açık repo için:** T.C. kimlik numaraları 0 ile başlıyor, telefonlarda 000 alan kodu var, e-postalar `.example` alan adını kullanıyor. Hiçbiri gerçek bir kişiye denk gelemez.
