# PROGRESS - flx (Freelancer.com için sadece okuma yapan CLI)

Amaç: Freelancer.com'daki uygun AI/otomasyon ilanlarını hızlıca bulmak ve hem benim hem de
ileride kurulacak teklif ajanı için temiz veri olarak sunmak. Kararlar: DECISIONS.md.

Durum: [ ] yapılacak, [x] bitti

## Faz 0 - Kurulum
- [x] `~/Projects/freelancer-cli`, `git init`, `.gitignore` (`.env*`, `traces/`, `__pycache__/`, `.venv/`)
- [x] Paket iskeleti: `src/flx/`, `flx` komutunu tanımlayan `pyproject.toml`, `python -m flx`
- [x] CLI mimarisi: standart `argparse` ile alt komutlar (`whoami`, `search`, `project`, `scan`)
- [x] Gelecek özellikler için yer tutucu: `auth` modülünde `flx login` -> `NotImplementedError`
- [x] Test altyapısı: standart `unittest`, `tests/`
- [x] PROGRESS.md, DECISIONS.md, CLAUDE.md yerinde
Bitti sayılır: `python -m flx --help` tüm alt komutları gösteriyor, `python -m unittest` hatasız.
Not: kurulmadan önce `PYTHONPATH=src python -m flx ...`; kurulumdan sonra (`pip install -e .`) sadece `flx ...`.
**Faz 0 tamam (2026-09-29): 5 test geçiyor, komutlar henüz 'not built yet' ile dürüstçe hata veriyor.**

## Faz 1 - Güvenli çekirdek, trace ve senaryolar
- [ ] Sadece GET atan HTTP istemcisi; başka istek türü hata verir
- [ ] Token okuma (ortam değişkeni, yoksa `.env.local`); maskeleme
- [ ] Hata yönetimi: 401 / 404 / 429 (kademeli bekleme, en fazla 3 tekrar) / zaman aşımı / bozuk JSON
- [ ] Trace kaydı: `traces/YYYY-MM-DD.jsonl`, `run_id` + `seq` ile ilişkili, token asla yok
- [ ] `--debug` genel bayrağı: aynı trace satırlarını anlık olarak ekrana (stderr) da basar, token maskeli
- [ ] Senaryo listesi `tests/SCENARIOS.md` ve her biri için otomatik test:
      1. Normal arama sonuç döner
      2. Boş sonuç
      3. Token yok -> istek atılmadan net mesaj
      4. 401 geçersiz veya süresi dolmuş token
      5. 429 hız limiti -> 1, 2, 4 sn bekleyerek en fazla 3 tekrar, sonra anlaşılır hata
      6. Ağ hatası / zaman aşımı
      7. Bozuk JSON veya eksik alan -> çökmez, alan boş gelir
      8. GET dışı istek -> hata
      9. Sayı olmayan ilan ID'si -> istek atılmadan hata
      10. Özel karakterli arama ("c++ & n8n") doğru kodlanır
      11. `scan`'de aynı ilan iki kelimede çıkarsa tek kayıt
      12. Trace dosyasında token geçmiyor
Bitti sayılır: 12 senaryonun hepsi testte geçiyor; bir test çalıştırmasının trace'i beklenen adımları gösteriyor.

## Faz 2 - Komutlar
- [ ] `flx whoami` - token'ı kontrol eder (sadece kullanıcı adı)
- [ ] `flx search "<arama>" [--limit N] [--offset N] [--json]`
- [ ] `flx project <id> [--json]` - tam açıklama, bütçe, teklifler, müşteri bilgisi
- [ ] `flx scan [--json] [--only-new]` - `keywords.txt` kelimeleri, birleştirilmiş, tekrarsız, en yeni üstte
- [ ] `--only-new`: görülen ilan ID'leri `state/seen.json`'da tutulur, sadece yeni ilanlar gösterilir (senaryo 13: ikinci taramada aynı ilan gelmez)
- [ ] Varsayılan `keywords.txt`: n8n, make.com, zapier, ai agent, llm, chatbot, openai,
      python automation, python script, web scraping, data extraction
- [ ] Eleme yok; her sonuçta: id, başlık, link, tür, bütçe alt/üst, para birimi, teklif sayısı,
      ortalama teklif, yayın zamanı, müşteri ülkesi, ödeme doğrulaması, açıklama
- [ ] `scan` kelimeler arasında 1 sn bekler (API'yi yormamak ve 429 almamak için)
- [ ] Tablo çıktısı terminal genişliğine uyar (kırpma/hizalama, bağımlılık yok) + `schema_version`'lı `--json`
Bitti sayılır: dört komut sahte API ile testleri geçiyor, tablo düzgün hizalanıyor; her değişiklikte tüm test takımı yeniden çalıştı.

## Faz 3 - Gerçek erişim
- [ ] Freelancer geliştirici panelinde uygulama (sadece okuma yetkisi)
- [ ] Token yolu: panelden hazır token mı, gerekirse `flx login` (OAuth) mı
- [ ] Token'ı `~/Projects/freelancer-cli/.env.local` dosyasına ben eklerim (sohbete asla yapıştırılmaz)
- [ ] Canlı kontrol: `flx whoami`, `flx scan`; trace ile istekler doğrulanır
Bitti sayılır: canlı `flx scan` gerçek ilanlar getiriyor ve trace beklenen yolu gösteriyor.

## Faz 4 - Dokümantasyon
- [ ] Başkaları için ayar yedeği: token/ayarlar `~/.config/flx/` altında da aranır
- [ ] İngilizce README: ne ve neden, kurulum, token, kullanım, JSON şeması, trace, "sadece okuma"
- [ ] LICENSE (MIT)
- [ ] Kişisel veri içermeyen örnek çıktı
- [ ] Vaka notları: Hangi sorunu çözüyor? Nasıl çalışıyor? Somut sonucu ne?
Bitti sayılır: projeyi bilmeyen biri README ile 5 dakikada `flx scan` çalıştırabiliyor.

## Faz 5 - Yayın
- [ ] Temiz oturumda `security-audit` -> `security.md`
- [ ] Temiz oturumda `optimize` -> `OPTIMIZATIONS.md`
- [ ] Önemli bulguları düzelt, tüm testleri yeniden çalıştır
- [ ] CI: `.github/workflows/test.yml` her gönderimde tüm testleri çalıştırır
- [ ] `v0.1.0` etiketi
- [ ] Sadece benim açık "evet"imden sonra: GitHub reposu ve gönderim
- [ ] İsteğe bağlı: vaka notları Sosyal Medya ajanına ("build breakdown" postu)
Bitti sayılır: herkese açık repo README ve çalışan CI ile yayında.
