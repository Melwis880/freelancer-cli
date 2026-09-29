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
- [x] Sadece GET atan HTTP istemcisi; başka istek türü hata verir (yönlendirme de izlenmez, token başka adrese gitmesin)
- [x] Token okuma (ortam değişkeni, yoksa `.env.local`); maskeleme
- [x] Hata yönetimi: 401 / 404 / 429 (kademeli bekleme, en fazla 3 tekrar) / zaman aşımı / bozuk JSON
- [x] Trace kaydı: `traces/YYYY-MM-DD.jsonl`, `run_id` + `seq` ile ilişkili, token asla yok
- [x] `--debug` genel bayrağı: aynı trace satırlarını anlık olarak ekrana (stderr) da basar, token maskeli
- [x] Senaryo listesi `tests/SCENARIOS.md` ve her biri için otomatik test:
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
Not: çekirdek hazır (`client.search_projects`, `client.get_project`, `models.merge_projects`); CLI komutları Faz 2'de bunlara bağlanacak.
Ek senaryolar: 14 (404), 15 (`--debug`), 16 (trace adımları), 17 (bozuk token), 18 (diğer API hataları), 19 (yönlendirme izlenmez), 20 (trace yazılamazsa uyarı). 13 Faz 2'ye ayrıldı.
**Faz 1 tamam (2026-09-29): 47 test geçiyor; 10 kasıtlı bozmanın 10'u da testlerde yakalandı.**

## Faz 2 - Komutlar
- [x] `flx whoami` - token'ı kontrol eder (sadece kullanıcı adı)
- [x] `flx search "<arama>" [--limit N] [--offset N] [--json]`
- [x] `flx project <id> [--json]` - tam açıklama, bütçe, teklifler, müşteri bilgisi
- [x] `flx scan [--json] [--only-new]` - `keywords.txt` kelimeleri, birleştirilmiş, tekrarsız, en yeni üstte
- [x] `--only-new`: görülen ilan ID'leri `state/seen.json`'da tutulur, sadece yeni ilanlar gösterilir (senaryo 13: ikinci taramada aynı ilan gelmez)
- [x] Varsayılan `keywords.txt`: n8n, make.com, zapier, ai agent, llm, chatbot, openai,
      python automation, python script, web scraping, data extraction
- [x] Eleme yok; her sonuçta: id, başlık, link, tür, bütçe alt/üst, para birimi, teklif sayısı,
      ortalama teklif, yayın zamanı, müşteri ülkesi, ödeme doğrulaması, açıklama
- [x] `scan` kelimeler arasında 1 sn bekler (API'yi yormamak ve 429 almamak için)
- [x] Tablo çıktısı terminal genişliğine uyar (kırpma/hizalama, bağımlılık yok) + `schema_version`'lı `--json`
Bitti sayılır: dört komut sahte API ile testleri geçiyor, tablo düzgün hizalanıyor; her değişiklikte tüm test takımı yeniden çalıştı.
Notlar: tabloda TÜR sütunu yok (saatlik bütçe `/h` ile görünür, JSON'da `type` var); dar terminalde önce AVG, sonra COUNTRY, VERIFIED, BIDS, AGE gizlenir.
`project` komutu müşteri bilgisini tek çağrıda almak için `projects/0.1/projects/?projects[]=<id>` kullanıyor (Faz 3'te doğrulanacak).
`--only-new` dışındaki komutlar `state/`'e dokunmaz. Yeni senaryolar: 13, 21-29.
**Faz 2 tamam (2026-09-29): 76 test geçiyor; 11 kasıtlı bozmanın 11'i de yakalandı (scratchpad kopyasında).**

## Faz 3 - Gerçek erişim
- [x] Freelancer geliştirici panelinde uygulama (sadece okuma yetkisi)
- [x] Token yolu: panelden hazır token mı, gerekirse `flx login` (OAuth) mı -> panel token'ı yetti, `flx login` gerekmedi
- [x] Token'ı `~/Projects/freelancer-cli/.env.local` dosyasına ben eklerim (sohbete asla yapıştırılmaz)
- [x] Canlı kontrol: `flx whoami`, `flx scan`; trace ile istekler doğrulanır (2026-09-29: 4 komut + 2x `scan --only-new` hepsi 200, 429 yok, ikinci tarama "No new projects.")
- [x] Arama parametre ve alan adlarını canlı yanıtla doğrula. 2026-09-29: `owner_id` ve `users` boş geliyor; müşteri ülkesi/ödeme doğrulaması sadece `owner_info=true` ile `owner_info.country.name` / `owner_info.status.payment_verified` alanlarında (düzeltildi). `projects[]` ucu çalışıyor. `project` komutunda da `owner_info` dolu geliyor (canlıda görüldü). Açık: en yüksek `limit` (şimdilik 100 varsayıldı)
Bitti sayılır: canlı `flx scan` gerçek ilanlar getiriyor ve trace beklenen yolu gösteriyor.
**Faz 3 tamam (2026-09-29).**

## Faz 4 - Dokümantasyon
- [x] Ön düzeltme (2026-09-29): XDG config klasörü (`~/.config/flx/`: token, `keywords.txt`, `seen.json`, `traces/`), çalışılan klasördeki `.env.local`/`keywords.txt` onu ezer; anahtar kelimeler daraltıldı (openai, chatbot, llm, ai agent, web scraping, data extraction, python script çıktı; langchain, crewai, ai agent development, llm integration, python web scraping girdi). Senaryo 30.
- [x] Başkaları için ayar yedeği: token/ayarlar `~/.config/flx/` altında da aranır (yukarıdaki ön düzeltmeyle tam XDG evi oldu)
- [x] İngilizce README: ne ve neden, kurulum, token, kullanım, JSON şeması, trace, "sadece okuma"
- [x] LICENSE (MIT); `pyproject.toml` SPDX lisans alanına geçti, `pip install -e .` hatasız (2026-09-29)
- [x] Kişisel veri içermeyen örnek çıktı (`examples/`, uydurma veriyle gerçek çıktı koduyla üretildi)
- [x] Vaka notları: Hangi sorunu çözüyor? Nasıl çalışıyor? Somut sonucu ne? (`CASE_STUDY.md`, İngilizce)
Bitti sayılır: projeyi bilmeyen biri README ile 5 dakikada `flx scan` çalıştırabiliyor.

## Faz 5 - Yayın
- [x] Ön temizlik (2026-09-29): repo kökündeki `traces/`, `state/`, `.env.local`, `keywords.txt` silindi (Meriç onayı); token artık sadece `~/.config/flx/.env.local`.
- [x] Canlı teşhis ve düzeltme (2026-09-29): canlı `scan` 3. kelimede zaman aşımına uğradı (istekler 8-28 sn). A/B ölçümü: `owner_info` olmadan 1,0 sn, ile 1,8 sn -> yavaşlığın asıl sebebi API tarafı, `owner_info` kaldı. `scan` artık hata veren kelimeyi atlıyor (senaryo 31, `schema_version` 2: `failed_keywords`). Zaman aşımı 20 sn kaldı.
- [x] Açık konu - alaka: v0.2'ye ertelendi (2026-09-29, Meriç kararı; hata değil, CLI zaten eleme yapmıyor). Ayrıntı aşağıda "v0.2" bölümünde.
- [x] Temiz oturumda `security-audit` -> `security.md` (2026-09-29): sır yok (geçmiş dahil). Orta: config klasörü izni zorlanmıyor (README'deki `mkdir -p` yüzünden canlıda 775), commit e-postası ilk gönderimde açığa çıkar. Düşük: `scan` uyarısında temizlenmemiş API metni, `--debug`'da C1/bidi, çalışılan klasöre güven, sınırsız yanıt okuma.
- [x] Temiz oturumda `optimize` -> `OPTIMIZATIONS.md` (2026-09-29): darboğaz yok, süre ağ + bekleme. Orta: `scan`'deki 1 sn bekleme istek süresinin üstüne ekleniyor (21 sn'nin 8'i; DECISIONS), tek zaman aşımı kelimeyi düşürüyor. Hızlı: sürüm iki yerde, testte sunucu kapanışı 1,2 sn, küçük tekrar/ölü kod.
- [x] Önemli bulguları düzelt, tüm testleri yeniden çalıştır (2026-09-29, Meriç onayı): security.md'deki tüm Orta/Düşük maddeler (config 700'e çekilir, `traces/` 700, `seen.json` rastgele adlı geçici dosyayla; `scan` uyarıları temizlenir; trace satırları ASCII; cwd dosyaları normal dosya/UTF-8/64 KiB, en fazla 50 kelime; yanıt en fazla 10 MiB, `RecursionError` yakalanır; README'de `mkdir -m 700` + `umask 077`). OPTIMIZATIONS F1 (başlangıçtan başlangıca 1 sn), F2 (zaman aşımında 1 tekrar), F4-F8. DECISIONS ve CLAUDE.md güncellendi. Yeni senaryolar 32, 33; 6, 25, 27, 30, 31 genişledi. 102 test geçiyor (süre 2,5 -> 1,3 sn). `schema_version` değişmedi (JSON alanı değişmedi).
- [x] Commit e-postası (2026-09-29, Meriç kararı): 15 commit `git filter-branch` ile GitHub noreply adresine çevrildi (tarihler ve dosya ağacı aynı); repo-yerel `user.email` artık noreply. Eski adres sadece yerel yedek `refs/original/` ve reflog'da duruyor; normal push'la gitmez.
- [x] CI: `.github/workflows/test.yml` her gönderimde tüm testleri çalıştırır (Python 3.10-3.13 + `pip install -e .`; GitHub'a gönderilince ilk kez gerçekten koşacak)
- [x] `v0.1.0` etiketi (2026-09-29, açıklamalı, `chore(release): 0.1.0` commit'inde; 102 test geçiyor, 12/12 kasıtlı bozma yakalandı)
- [ ] Sadece benim açık "evet"imden sonra: GitHub reposu ve gönderim
- [ ] İsteğe bağlı: vaka notları Sosyal Medya ajanına ("build breakdown" postu)
Bitti sayılır: herkese açık repo README ve çalışan CI ile yayında.

## v0.2 - Sonrası
- [ ] Alaka (2026-09-29 canlı tarama, 9 kelime, 21 sn, 0 hata, 102 ilan): kabaca 1/3'ü hedefe uygun, ~1/2'si ilgisiz (web sitesi, illüstrasyon, video, satış ortaklığı, tadilat). İlgisizler en yeni ilanlarda yoğun. Olası sebep: çok kelimeli terimlerdeki genel kelimeler ("development", "integration", "automation") gevşek eşleşiyor. Adaylar: kelime başına teşhis (hangi terim gürültü getiriyor), metin yerine `jobs[]` (beceri ID) filtresi, JSON'a `matched_keywords`.
