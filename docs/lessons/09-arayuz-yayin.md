# Ders 09 — Program Uzmanı arayüzü, denetim kaydı, yayına alma

## Mimari
```
pipeline (yerel) ──► Cosmos DB "results"   ◄── web arayüzü (App Service, MI)
                                                  │ uzman kararı
workflow sync   ◄── Cosmos DB "decisions"  ◄──────┘
       │ checkpoint'ten devam
       └──► Cosmos DB "audit" (SHA-256 mühürlü kayıt)
```

| Bileşen | Seçim | Neden |
|---|---|---|
| Veri | Cosmos DB **serverless**, yerel kimlik doğrulama kapalı | Sabit ücret yok; Entra ID veri düzlemi rolü |
| Arayüz | **App Service F1** (ücretsiz), FastAPI | Container Apps için gereken Container Registry ayda yaklaşık 5 $ sabit ücret yazıyor |
| Giriş | **Easy Auth + Entra ID**, "atama gerekli" | Yalnızca atanmış kullanıcılar girebilir; uzman adı oturumdan gelir |
| Sır | İstemci sırrı **yalnızca Key Vault'ta** | Web uygulaması managed identity ile Key Vault referansı üzerinden okur; durum "Resolved" |

```bash
python scripts/deploy_webapp.py
python scripts/run_workflow.py sync    # arayüzde verilen kararları uygula
```

## Güvenlik dersleri
- **Başvuru metni saldırgan verisidir.** Arayüz her değeri HTML olarak kaçışlıyor, yoksa XSS mümkün olurdu.
- **CSRF:** Durum değiştiren POST istekleri Origin veya Referer kontrolünden geçiyor. Kaynağı olmayan istek 403 alıyor.
- **Sır hiçbir zaman ekrana, diske veya repoya gitmiyor.** Entra'dan doğrudan Key Vault'a yazılıyor.

## Karşılaşılan tuzaklar
| Tuzak | Çözüm |
|---|---|
| `az ... --settings "@Microsoft.KeyVault(...)"` başarısız | CLI, `@` ile başlayan argümanı dosya yolu sanıyor. Ayar JSON dosyasıyla gönderildi |
| "Cannot use auth v2 commands" | Yeni uygulamalar v1 yapılandırmasıyla başlıyor; `auth config-version upgrade` |
| Tarayıcı dışı istek 401, tarayıcı 302 | Easy Auth tarayıcıyı User-Agent başlığına göre ayırıyor; ikisi de korumalı |

## Uçtan uca test
Arayüzde karar verildi, `sync` workflow'u checkpoint'ten devam ettirdi, sonuç "Tamamlandı" oldu ve denetim kaydı yazıldı.
