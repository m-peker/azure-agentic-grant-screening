# Yükleme için örnek başvurular

Arayüzde **Gelen başvurular → Yükle** ile denemek için. Sistemin daha önce görmediği, tamamen kurgusal iki başvuru. Başvuru numarasını yükleme sırasında sistem verir.

| Dosya | Beklenen ön değerlendirme | Neden |
|---|---|---|
| `ornek-1-biyokomur.pdf` | **Uygun** | Dolaylı gider %8,9, ekipman %26,5, süre 20 ay, 60.000 TL'lik hizmet alımının sağlayıcısı ve teklifi var, insan verisi yok |
| `ornek-2-deprem.pdf` | **Eksiklik var** | Süre 28 ay (sınır 24); 150.000 TL'lik hizmet alımında sağlayıcı ve teklif yok. Tuzak: "anonimleştirilmiş titreşim verileri" insan verisi değildir, etik kuralı tetiklenmemeli |

Kendi PDF'inizi de yükleyebilirsiniz. Pipeline bu çağrının başvuru formuna göre ayarlıdır; farklı biçimdeki bir belgede bulamadığı bilgileri "Kontrol edin" olarak işaretler ve başvuruyu uzman incelemesine gönderir.

PDF'leri yeniden üretmek için: `python scripts/build_pdfs.py --samples`
