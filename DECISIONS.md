# DECISIONS - flx

Her satır: karar - neden. Bir karar sessizce değiştirilmez; değişmesi gerekirse önce Meriç'e sorulur.

## Mimari
- Python, sadece standart kütüphane - tedarik zinciri riski yok, kurulum kolay.
- Veri kaynağı resmi REST API (`https://www.freelancer.com/api/projects/0.1/...`), `Freelancer-OAuth-V1` başlığı - resmi SDK eski ve bakımı belirsiz.
- CLI sadece veri getirir; eleme ve puanlama teklif ajanının işi - bir araç, bir iş.
- `scan` metin kelimelerine (`keywords.txt`) ek olarak Freelancer beceri ID'leriyle (`skills.txt`, `jobs[]` parametresi) arar; her beceri ayrı istek (tek istekte büyük kategori listeyi dolduruyor). Metin sadece tek kelimelik niş terimler için - API çok kelimeli metni gevşek eşleştiriyor (canlı ölçüm: 4 terimde ifade 80 sonucun 1'inde, tırnak yok sayılıyor), beceri eşleşmesi birebir. Varsayılan beceriler tek tek ölçülerek seçildi; "AI Automation" (3380) yarı video/satış işi getirdiği için yerine "AI Chatbot Development" (2916) ve "Agentic AI" (3132) girdi. Son ölçüm (83 ilan, elle okundu): ~56 açıkça uygun, 7 sınırda, 20 dışı; gürültünün çoğu Zapier/AI etiketli idari-satış işleri, müşterinin etiketinden geliyor, arama yönteminden değil (2026-09-30). Eşleştirmeyi API yapar, CLI kendisi eleme yapmaz; her ilan `skills` alanıyla beceri adlarını taşır ki teklif ajanı eleyebilsin (2026-09-30, Meriç onayı).
- `flx skills <ad>`: beceri listesini (tek GET) çeker, adı metni içerenleri gösterir - `skills.txt` için ID bulmak; ilanlar değil beceri adları süzülür, "CLI eleme yapmaz" kuralına dokunmaz (2026-09-30, Meriç onayı).
- Çekirdek (`client`, `models`) komut katmanından ayrı - ileride bir MCP katmanı aynı çekirdeği kullanabilsin.
- JSON çıktısı `schema_version` taşır - şema değişince teklif ajanı bozulmasın. 3: ilanlara `skills`, `scan`'e `skills`/`failed_skills` (2026-09-30).
- `auth` modülünde `flx login` (OAuth) için `NotImplementedError` yer tutucusu - token panelden alınamazsa doldurulacak; o zamana kadar hiçbir şey çalışıyormuş gibi davranmaz.
- Alt komutlar standart `argparse` ile - bağımlılık yok.

## Güvenlik
- Sadece GET; başka her istek türü kod seviyesinde hata verir - teklif veya mesaj gönderimi fiziksel olarak imkânsız.
- API yanıtı en fazla 10 MiB okunur, fazlası hata; aşırı iç içe JSON çökme değil, anlaşılır hata - bozuk veya kötü niyetli bir yanıt belleği doldurmasın (2026-09-29, Meriç onayı, security.md).
- Yönlendirmeler (3xx) izlenmez, anlaşılır hata verir - token asla başka bir sunucuya gitmesin (2026-09-29, Meriç onayı).
- API'den gelen metinler terminale basılmadan önce kontrol/biçim karakterlerinden (ANSI kaçış dizileri, bidi, sıfır genişlikli karakterler) temizlenir; `--json` bunları silmez, kaçışlı yazar - kötü niyetli bir ilan başlığı terminali bozamasın (terminal injection) (2026-09-29, Meriç onayı). `scan` uyarıları da aynı temizlikten geçer (2026-09-29, security.md).
- Dosyaların evi `~/.config/flx/` (`$XDG_CONFIG_HOME/flx`): token (`.env.local`), `keywords.txt`, `skills.txt`, `seen.json`, `traces/`. İlk çalıştırmada klasör (sadece sahibi okuyabilir, 700) ve varsayılan `keywords.txt` ile `skills.txt` oluşturulur, var olan asla ezilmez. Klasör zaten varsa ve başkalarına açıksa (ör. `mkdir -p` ile 775) her çalıştırmada 700'e çekilir; `traces/` da 700 (2026-09-29, Meriç onayı, security.md). Trace dosyaları 600; daha açık bir `traces/` ya da trace dosyası bir sonraki yazımda sıkılaştırılır - trace her aramayı ve hatayı kaydeder (2026-09-30, Meriç onayı, security-audit bulgu 4). Çalışılan klasörde `.env.local`, `keywords.txt` veya `skills.txt` varsa o kullanılır (geliştirici kolaylığı) - `flx` kurulunca her klasörden çalışsın (2026-09-29, Meriç kararı; önceki "Faz 4'te sadece yedek" planının yerine). Bu dosyalar güvenilmeyen bir klasörden gelebileceği için: sadece normal dosya, UTF-8, en fazla 64 KiB; `scan` dosya başına en fazla 50 kelime/beceri alır - FIFO veya `/dev/zero` flx'i kilitlemesin, dev bir liste kullanıcının token'ıyla binlerce istek attırmasın (2026-09-29, Meriç onayı, security.md).
- Token sırası: `FREELANCER_TOKEN` ortam değişkeni, sonra çalışılan klasördeki `.env.local`, sonra `~/.config/flx/.env.local`; ekrana, hata mesajına ve trace'e asla yazılmaz.
- Diske erişim: sadece `.env.local`, `keywords.txt` ve `skills.txt` okunur; sadece config klasörü (ilk çalıştırmada), varsayılan `keywords.txt` ve `skills.txt`, `traces/` ve `seen.json` (sadece görülen ilan ID'leri, `--only-new` için) yazılır. Hepsi `~/.config/flx/` altında, repo dışında.
- Girdi: arama metni URL'e güvenli kodlanır; ilan ID'si sadece sayı kabul edilir, değilse istek atılmaz.
- `scan`'de iki kelimenin istekleri arasında en az 1 sn olur, başlangıçtan başlangıca ölçülür: istek zaten 1 sn'den uzun sürdüyse ayrıca beklenmez - API'yi yormamak, 429 riskini düşürmek, boşuna beklememek (2026-09-29, Meriç onayı, OPTIMIZATIONS F1; önceki "her kelimeden sonra 1 sn" kuralının yerine; 9 kelimelik taramada ~8 sn kazanç).
- Zaman aşımı (20 sn): istek 2 sn sonra bir kez tekrar denenir, ikinci zaman aşımında hata (`scan`'de o kelime atlanır). Diğer ağ hataları tekrarlanmaz - yavaş API günlerinde kelime kaybını azaltmak; GET tekrarı zararsız (2026-09-29, Meriç onayı, OPTIMIZATIONS F2).
- 429 (hız limiti): kademeli bekleme ile en fazla 3 tekrar (1, 2, 4 sn; `Retry-After` varsa o, en fazla 10 sn); sonra anlaşılır hata - Meriç'in tercihi, 2026-09-29.

## Trace
- Her çalıştırma `~/.config/flx/traces/YYYY-MM-DD.jsonl` dosyasına yazılır, her zaman açık - sorun anında geçmiş hazır olsun; hangi klasörden çalıştırılırsa çalıştırılsın tek yerde toplansın.
- Her satır: `run_id`, `seq`, zaman, komut, adım, uç nokta, parametreler, durum kodu, süre (ms), sonuç sayısı, hata - aynı `run_id` tek çalıştırmanın tüm adımlarını bağlar.
- Token hiçbir zaman yazılmaz; ilan açıklamaları kısaltılır.
- Satırlar saf ASCII yazılır (ASCII dışı karakterler `\uXXXX` kaçışlı) - trace'teki API metni `--debug` ya da `cat` ile terminale kontrol/bidi karakteri olarak ulaşamasın (2026-09-29, Meriç onayı, security.md).
- `--debug` bayrağı trace satırlarını ayrıca stderr'e basar (token maskeli) - canlı izleme için.

## Kalite
- Her gönderimde GitHub Actions ile tüm testler çalışır - regresyonlar erken yakalansın.
